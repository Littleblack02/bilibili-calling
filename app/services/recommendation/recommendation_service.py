"""
推荐服务（完整流程）

编排：候选召回 → LLM 重排 → 理由生成 → 保存候选池
"""
from typing import List, Dict, Any, Optional
from loguru import logger
from datetime import datetime, timedelta
import asyncio
import time

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import (
    CandidatePool, FinalRecommendation, UserInterestProfile,
    FavoriteVideo, FavoriteFolder, VideoCache, CandidateRecommendation
)
from app.services.recommendation.candidate_recalls import get_candidate_recall
from app.services.recommendation.candidate_hydration import get_candidate_hydrator
from app.services.bilibili import BilibiliService
from app.services.recommendation.llm_reranker import get_llm_reranker
from app.services.recommendation.reason_generator import get_reason_generator
from app.services.profile.profile_builder import get_profile_builder
from app.services.profile.multi_source_profile_builder import get_multi_source_profile_builder
from app.services.recommendation.event_service import get_recommendation_event_service
from app.services.recommendation.profile_schema import normalize_profile
from app.services.recommendation.ranking import blend_llm_scores, diversify, score_candidates
from app.services.ontology import get_ontology_service
from app.config import settings
from app.services.observability import batch_id_var, metrics, safe_hash


class RecommendationService:
    """推荐服务"""

    def __init__(self):
        self.candidate_recall = get_candidate_recall()
        self.candidate_hydrator = get_candidate_hydrator()
        self.llm_reranker = get_llm_reranker()
        self.reason_generator = get_reason_generator()
        self.profile_builder = get_profile_builder()
        self.multi_source_profile_builder = get_multi_source_profile_builder()
        self.event_service = get_recommendation_event_service()

    async def generate_recommendations(
        self,
        session_id: str,
        limit: int = 10,
        save_to_candidates: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        生成推荐（完整流程）

        Args:
            session_id: 用户会话 ID
            limit: 返回数量
            save_to_candidates: 是否保存到候选池

        Returns:
            推荐视频列表
        """
        context = dict(context or {})
        started = time.perf_counter()
        session_ref = safe_hash(session_id)
        effective_flags = settings.v2_feature_flags(session_id)
        context.setdefault("v2_feature_flags", effective_flags)
        logger.info(f"开始生成推荐: session_hash={session_ref}, mode={context.get('mode', 'balanced')}")

        # 1. 获取/构建用户画像
        raw_profile = await self._ensure_profile(session_id)
        profile_model = normalize_profile(raw_profile)
        if not context.get("query") and profile_model.current_intent:
            context["query"] = profile_model.current_intent
        if context.get("query"):
            profile_model.current_intent = context["query"]
        profile = profile_model.as_legacy_dict()

        # 2. 获取用户 cookies
        cookies = await self._get_user_cookies(session_id)

        # 3. 候选召回
        candidates = await self.candidate_recall.recall_candidates(
            session_id,
            limit_per_channel=max(20, limit * 4),
            cookies=cookies,
            profile=profile,
            context=context,
        )

        if not candidates:
            metrics.inc("recommendation_outcomes_total", outcome="empty_recall")
            metrics.observe("recommendation_total_duration_ms", (time.perf_counter() - started) * 1000)
            logger.warning(f"召回结果为空: session_hash={session_ref}")
            return []
        for source in {str(item.get("recall_source") or "unknown") for item in candidates}:
            metrics.observe(
                "recommendation_recall_source_candidates",
                sum(1 for item in candidates if str(item.get("recall_source") or "unknown") == source),
                source=source,
            )

        # V2 candidates carry only BVID + recall trace through merge. Hydrate
        # each unique BVID once before eligibility filtering and ranking.
        if effective_flags["candidate_hydration"]:
            async with BilibiliService(
                sessdata=cookies.get("SESSDATA"),
                bili_jct=cookies.get("bili_jct"),
                dedeuserid=cookies.get("DedeUserID"),
            ) as bili:
                candidates = await self.candidate_hydrator.hydrate_candidates(
                    bili, candidates
                )

        # 3. 排除已收藏、已反馈和近期已曝光内容。过滤发生在 Top-K 之前。
        preference_state = await self.event_service.get_preference_state(
            session_id, settings.recommendation_recent_exposure_days
        )
        eligible_candidates = await self._filter_ineligible(
            session_id=session_id,
            candidates=candidates,
            excluded_bvids=preference_state["excluded_bvids"],
            allow_favorited=context.get("mode") == "rediscover",
            max_duration=context.get("max_duration"),
            blocked_topics=preference_state["blocked_topics"],
            blocked_up_mids=preference_state["blocked_up_mids"],
            blocked_concept_ids=preference_state.get("blocked_concept_ids", set()),
        )
        metrics.observe(
            "recommendation_filter_rate",
            1.0 - (len(eligible_candidates) / len(candidates) if candidates else 0.0),
        )
        metrics.observe(
            "recommendation_repeat_exposure_rate",
            sum(1 for item in candidates if item.get("bvid") in preference_state["excluded_bvids"])
            / len(candidates),
        )

        # 4. 可解释规则排序是主链路，任何时候都能独立返回有效结果。
        ranking_started = time.perf_counter()
        ranked_candidates = score_candidates(
            eligible_candidates,
            profile_model,
            negative_topics=preference_state["negative_topics"],
            negative_up_mids=preference_state["negative_up_mids"],
            positive_topics=preference_state["positive_topics"],
            positive_up_mids=preference_state["positive_up_mids"],
            topic_affinity=preference_state["topic_affinity"],
            concept_affinity=preference_state.get("concept_affinity", {}),
            up_affinity_feedback=preference_state["up_affinity_feedback"],
            weights=settings.recommendation_scoring_weights,
            mode=context.get("mode", "balanced"),
            exploration_level=float(context.get("exploration_level", 0.3)),
        )

        # 可选 LLM 只对小规模候选辅助打分，并与规则分混合。
        if settings.recommendation_llm_rerank_enabled and ranked_candidates:
            llm_input = [dict(item, rule_score=item["rec_score"]) for item in ranked_candidates[:settings.recommendation_llm_top_n]]
            try:
                llm_ranked = await asyncio.wait_for(
                    self.llm_reranker.rerank_candidates(
                        session_id=session_id,
                        user_profile=profile,
                        candidates=llm_input,
                        top_k=len(llm_input),
                    ),
                    timeout=settings.recommendation_llm_timeout_seconds,
                )
                ranked_candidates = blend_llm_scores(ranked_candidates, llm_ranked, llm_weight=0.25)
            except Exception as exc:
                logger.warning(f"LLM 辅助重排超时或失败，保留规则排序: {exc}")

        reranked_candidates = diversify(
            ranked_candidates,
            limit=limit,
            max_per_up=settings.recommendation_max_per_up,
            diversity_strength=0.20 + 0.25 * float(context.get("exploration_level", 0.3)),
        )
        metrics.observe("recommendation_ranking_duration_ms", (time.perf_counter() - ranking_started) * 1000)
        diversity_keys = {
            tuple(match.get("concept_id") for match in (item.get("matched_concepts") or []) if isinstance(match, dict))
            or (str(item.get("recall_tag") or item.get("recall_category") or "unknown"),)
            for item in reranked_candidates
        }
        metrics.observe(
            "recommendation_list_topic_diversity",
            len(diversity_keys) / len(reranked_candidates) if reranked_candidates else 0.0,
        )

        # 5. 生成可信推荐理由（默认使用特征模板）。
        candidates_with_reasons = await self.reason_generator.generate_reasons(
            user_profile=profile,
            candidates=reranked_candidates
        )

        # 6. 保存批次和候选池，响应字段同时兼容现有前端。
        batch_id = await self.event_service.save_batch(
            session_id=session_id,
            algorithm_version=settings.recommendation_algorithm_version,
            requested_count=limit,
            recommendations=candidates_with_reasons,
            context=context,
        )
        batch_id_var.set(batch_id)
        final_candidates = [
            {
                **item,
                "reason": item.get("rec_reason", ""),
                "score": item.get("rec_score", 0.0),
                "type": item.get("recall_source", "unknown"),
                "pic": item.get("pic_url", ""),
                "batch_id": batch_id,
                "algorithm_version": settings.recommendation_algorithm_version,
            }
            for item in candidates_with_reasons
        ]

        if save_to_candidates:
            await self._save_to_candidate_pool(
                session_id=session_id,
                candidates=final_candidates
            )

        metrics.inc("recommendation_outcomes_total", outcome="success")
        metrics.observe("recommendation_total_duration_ms", (time.perf_counter() - started) * 1000)
        logger.info(f"推荐生成完成: session_hash={session_ref}, 推荐数: {len(final_candidates)}")
        return final_candidates

    async def _get_user_cookies(self, session_id: str) -> Dict[str, str]:
        """获取用户 cookies"""
        from app.models import UserSession
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(UserSession).where(
                        UserSession.session_id == session_id
                    )
                )
                user_session = result.scalar_one_or_none()

                if user_session:
                    return {
                        "SESSDATA": user_session.sessdata or "",
                        "bili_jct": user_session.bili_jct or "",
                        "DedeUserID": user_session.dedeuserid or ""
                    }
        except Exception as e:
            logger.warning(f"获取用户 cookies 失败: {e}")

        return {}

    async def _ensure_profile(self, session_id: str) -> Dict[str, Any]:
        """确保用户画像存在"""
        # 尝试从数据库获取
        async with async_session_factory() as db:
            result = await db.execute(
                select(UserInterestProfile).where(
                    UserInterestProfile.session_id == session_id
                )
            )
            profile = result.scalar_one_or_none()

        if profile:
            cached_profile = self._profile_record_to_dict(profile)
            updated_at = profile.updated_at
            max_age = timedelta(hours=settings.recommendation_profile_max_age_hours)
            if updated_at and datetime.utcnow() - updated_at <= max_age:
                return cached_profile

            # 画像过期时只使用已经同步到本地的数据做增量刷新；失败时保留旧画像，
            # 不让画像刷新成为推荐接口的单点故障。
            logger.info(f"用户画像已过期，尝试增量刷新: {session_id}")
            try:
                cookies = await self._get_user_cookies(session_id)
                refreshed = await self.multi_source_profile_builder.build_comprehensive_profile(
                    session_id=session_id,
                    cookies=cookies,
                    force_rebuild=False,
                )
                if refreshed.get("unified_tags"):
                    return self._multi_source_profile_to_dict(refreshed)
                logger.warning(f"画像增量刷新结果为空，继续使用缓存画像: {session_id}")
            except Exception as exc:
                logger.warning(f"画像增量刷新失败，继续使用缓存画像: {session_id}, {exc}")
            return cached_profile
        else:
            # 构建新画像 - 使用多数据源画像构建器
            logger.info(f"用户画像不存在，开始构建多数据源画像: {session_id}")
            try:
                # 获取用户会话信息以获取cookies
                from app.models import UserSession
                from sqlalchemy import select as sa_select

                async with async_session_factory() as db:
                    result = await db.execute(
                        sa_select(UserSession).where(UserSession.session_id == session_id)
                    )
                    user_session = result.scalar_one_or_none()

                if user_session:
                    # 构建cookies字典
                    cookies = {
                        "SESSDATA": user_session.sessdata,
                        "bili_jct": user_session.bili_jct,
                        "DedeUserID": user_session.dedeuserid
                    }

                    # 使用多数据源画像构建器
                    new_profile = await self.multi_source_profile_builder.build_comprehensive_profile(
                        session_id=session_id,
                        cookies=cookies,
                        force_rebuild=True
                    )

                    # 转换为推荐服务需要的格式
                    return self._multi_source_profile_to_dict(new_profile)
                else:
                    # 降级到单数据源构建
                    logger.warning(f"用户会话不存在，降级到单数据源画像构建: {session_id}")
                    new_profile = await self.profile_builder.build_profile_from_favorites(session_id)
                    return new_profile

            except Exception as e:
                logger.error(f"多数据源画像构建失败，降级到单数据源: {e}")
                # 降级方案：使用单数据源
                new_profile = await self.profile_builder.build_profile_from_favorites(session_id)
                return new_profile

    @staticmethod
    def _profile_record_to_dict(profile: UserInterestProfile) -> Dict[str, Any]:
        """把数据库画像转换为推荐服务唯一使用的兼容字典。"""
        features = profile.profile_features if isinstance(profile.profile_features, dict) else {}
        return {
            "interest_tags": profile.interest_tags or {},
            "category_distribution": profile.category_distribution or {},
            "followed_ups": profile.followed_ups or [],
            "total_favorites": profile.total_favorites or 0,
            "visual_style_preference": profile.visual_style_preference or {},
            "content_type_preference": profile.content_type_preference or {},
            "confidence_score": profile.confidence_score or 0.5,
            "recent_interests": profile.recent_interest_shift or {},
            "current_intent": (
                (profile.short_term_focus or {}).get("focus")
                if isinstance(profile.short_term_focus, dict)
                else None
            ),
            "updated_at": profile.updated_at,
            "profile_features": features,
            **features,
        }

    @staticmethod
    def _multi_source_profile_to_dict(profile: Dict[str, Any]) -> Dict[str, Any]:
        """统一多数据源画像字段，避免 unified_tags/interest_tags 漂移。"""
        features = profile.get("profile_features") if isinstance(profile.get("profile_features"), dict) else {}
        return {
            "interest_tags": profile.get("unified_tags", profile.get("interest_tags", {})),
            "category_distribution": profile.get("category_distribution", {}),
            "followed_ups": profile.get("followed_ups", []),
            "total_favorites": profile.get("total_analyzed", profile.get("total_favorites", 0)),
            "visual_style_preference": profile.get("visual_style_preference", {}),
            "content_type_preference": profile.get("content_type_preference", {}),
            "confidence_score": profile.get("confidence_score", 0.5),
            "recent_interests": profile.get("recent_interests", profile.get("recent_interest_shift", {})),
            "current_intent": profile.get("current_intent"),
            "data_sources": profile.get("data_sources", []),
            "source_counts": profile.get("source_counts", {}),
            "bangumi_following": profile.get("bangumi_following", []),
            "cinema_favorites": profile.get("cinema_favorites", []),
            "updated_at": profile.get("updated_at", datetime.utcnow()),
            "profile_features": features,
            **features,
        }

    async def _filter_ineligible(
        self,
        session_id: str,
        candidates: List[Dict[str, Any]],
        excluded_bvids: set[str] | None = None,
        allow_favorited: bool = False,
        max_duration: int | None = None,
        blocked_topics: set[str] | None = None,
        blocked_up_mids: set[int] | None = None,
        blocked_concept_ids: set[str] | None = None,
    ) -> List[Dict[str, Any]]:
        """在排序前过滤已收藏、旧版已处理和事件层排除的视频。"""
        excluded_bvids = set(excluded_bvids or set())
        blocked_topics_lower = {topic.lower() for topic in (blocked_topics or set())}
        ontology = get_ontology_service()
        blocked_matches = [
            match.concept_id
            for topic in blocked_topics_lower
            for match in ontology.resolve_text(topic, limit=5)
        ]
        blocked_concept_ids = set(blocked_concept_ids or set()) | ontology.descendants(
            blocked_matches
        )
        blocked_up_mids = blocked_up_mids or set()
        async with async_session_factory() as db:
            # 查询用户已收藏的视频 BV 号
            result = await db.execute(
                select(VideoCache.bvid)
                .join(FavoriteVideo, FavoriteVideo.bvid == VideoCache.bvid)
                .join(FavoriteFolder, FavoriteFolder.id == FavoriteVideo.folder_id)
                .where(FavoriteFolder.session_id == session_id)
                .where(FavoriteVideo.is_selected == True)
            )

            favorited_bvids = {row[0] for row in result.fetchall()}

            legacy_result = await db.execute(
                select(CandidateRecommendation.bvid).where(
                    CandidateRecommendation.session_id == session_id,
                    CandidateRecommendation.status.in_(["accepted", "rejected"]),
                )
            )
            excluded_bvids.update(row[0] for row in legacy_result.fetchall())
            if not allow_favorited:
                excluded_bvids.update(favorited_bvids)

            # 过滤
            filtered = [
                cand for cand in candidates
                if cand.get("bvid") not in excluded_bvids
                and cand.get("mid") not in blocked_up_mids
                and not any(
                    topic in (
                        f"{cand.get('title', '')} {cand.get('recall_tag', '')} "
                        f"{cand.get('recall_category', '')}"
                    ).lower()
                    for topic in blocked_topics_lower
                )
                and not blocked_concept_ids.intersection(
                    match.concept_id for match in ontology.resolve_text(
                        f"{cand.get('title', '')} {cand.get('recall_tag', '')} "
                        f"{cand.get('recall_category', '')}",
                        limit=12,
                    )
                )
                and (
                    not max_duration
                    or not cand.get("duration")
                    or self._safe_duration(cand.get("duration")) <= max_duration
                )
            ]

            logger.info(f"过滤不可推荐内容: {len(candidates)} -> {len(filtered)}")
            return filtered

    @staticmethod
    def _safe_duration(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    async def _save_to_candidate_pool(
        self,
        session_id: str,
        candidates: List[Dict[str, Any]]
    ):
        """保存到候选池"""
        async with async_session_factory() as db:
            for cand in candidates:
                # 检查是否已存在
                existing = await db.execute(
                    select(CandidateRecommendation).where(
                        and_(
                            CandidateRecommendation.session_id == session_id,
                            CandidateRecommendation.bvid == cand.get("bvid")
                        )
                    )
                )
                existing_record = existing.scalar_one_or_none()

                # 计算过期时间（7天后）
                expires_at = datetime.utcnow() + timedelta(days=7)

                if existing_record:
                    # 更新（如果状态是 pending）
                    if existing_record.status == 'pending':
                        existing_record.rec_score = cand.get("rec_score", 0.0)
                        existing_record.rec_reason = cand.get("rec_reason", "")
                        existing_record.expires_at = expires_at
                        existing_record.updated_at = datetime.utcnow()
                else:
                    # 新增
                    new_candidate = CandidateRecommendation(
                        session_id=session_id,
                        bvid=cand.get("bvid", ""),
                        rec_type=cand.get("recall_source", "unknown"),
                        rec_score=cand.get("rec_score", 0.0),
                        rec_reason=cand.get("rec_reason", ""),
                        title=cand.get("title", ""),
                        author=cand.get("author", ""),
                        mid=cand.get("mid", 0),
                        play=cand.get("play", 0),
                        duration=cand.get("duration", 0),
                        pic_url=cand.get("pic_url", ""),
                        pubdate=cand.get("pubdate"),
                        status='pending',
                        expires_at=expires_at
                    )
                    db.add(new_candidate)

            await db.commit()
            logger.info(f"保存到候选池: {session_id}, {len(candidates)} 条")

    async def get_candidate_recommendations(
        self,
        session_id: str,
        status: str = 'pending',
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        获取候选推荐列表

        Args:
            session_id: 用户会话 ID
            status: 状态筛选 (pending/accepted/rejected)
            limit: 返回数量

        Returns:
            候选推荐列表
        """
        async with async_session_factory() as db:
            result = await db.execute(
                select(CandidateRecommendation)
                .where(
                    and_(
                        CandidateRecommendation.session_id == session_id,
                        CandidateRecommendation.status == status
                    )
                )
                .order_by(CandidateRecommendation.rec_score.desc())
                .limit(limit)
            )

            candidates = []
            for record in result.scalars():
                candidates.append({
                    "id": record.id,
                    "bvid": record.bvid,
                    "title": record.title,
                    "author": record.author,
                    "play": record.play,
                    "pic_url": record.pic_url,
                    "rec_score": record.rec_score,
                    "rec_reason": record.rec_reason,
                    "status": record.status,
                    "created_at": record.created_at,
                    "expires_at": record.expires_at
                })

            return candidates

    async def accept_recommendation(
        self,
        session_id: str,
        candidate_id: int,
        target_media_id: int
    ) -> bool:
        """
        接受推荐（添加到收藏夹）

        Args:
            session_id: 用户会话 ID
            candidate_id: 候选推荐 ID
            target_media_id: 目标收藏夹 ID

        Returns:
            是否成功
        """
        # 更新候选状态为 accepted
        # 注：如需实��添加到收藏夹，可调用 add_to_favorites 工具
        async with async_session_factory() as db:
            result = await db.execute(
                select(CandidateRecommendation).where(
                    and_(
                        CandidateRecommendation.session_id == session_id,
                        CandidateRecommendation.id == candidate_id
                    )
                )
            )
            candidate = result.scalar_one_or_none()

            if candidate:
                candidate.status = 'accepted'
                candidate.updated_at = datetime.utcnow()
                await db.commit()
                return True

            return False

    async def reject_recommendation(
        self,
        session_id: str,
        candidate_id: int,
        feedback: Optional[str] = None
    ) -> bool:
        """
        拒绝推荐

        Args:
            session_id: 用户会话 ID
            candidate_id: 候选推荐 ID
            feedback: 用户反馈（可选）

        Returns:
            是否成功
        """
        async with async_session_factory() as db:
            result = await db.execute(
                select(CandidateRecommendation).where(
                    and_(
                        CandidateRecommendation.session_id == session_id,
                        CandidateRecommendation.id == candidate_id
                    )
                )
            )
            candidate = result.scalar_one_or_none()

            if candidate:
                candidate.status = 'rejected'
                candidate.user_feedback = feedback
                candidate.updated_at = datetime.utcnow()
                await db.commit()
                return True

            return False


# 单例
_recommendation_service: Optional[RecommendationService] = None


def get_recommendation_service() -> RecommendationService:
    """获取推荐服务单例"""
    global _recommendation_service
    if _recommendation_service is None:
        _recommendation_service = RecommendationService()
    return _recommendation_service
