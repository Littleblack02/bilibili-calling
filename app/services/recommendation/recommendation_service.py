"""
推荐服务（完整流程）

编排：候选召回 → LLM 重排 → 理由生成 → 保存候选池
"""
from typing import List, Dict, Any, Optional
from loguru import logger
from datetime import datetime, timedelta

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import (
    CandidatePool, FinalRecommendation, UserInterestProfile,
    FavoriteVideo, FavoriteFolder, VideoCache, CandidateRecommendation
)
from app.services.recommendation.candidate_recalls import get_candidate_recall
from app.services.recommendation.llm_reranker import get_llm_reranker
from app.services.recommendation.reason_generator import get_reason_generator
from app.services.profile.profile_builder import get_profile_builder
from app.services.profile.multi_source_profile_builder import get_multi_source_profile_builder


class RecommendationService:
    """推荐服务"""

    def __init__(self):
        self.candidate_recall = get_candidate_recall()
        self.llm_reranker = get_llm_reranker()
        self.reason_generator = get_reason_generator()
        self.profile_builder = get_profile_builder()
        self.multi_source_profile_builder = get_multi_source_profile_builder()

    async def generate_recommendations(
        self,
        session_id: str,
        limit: int = 10,
        save_to_candidates: bool = True
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
        logger.info(f"开始生成推荐: {session_id}")

        # 1. 获取/构建用户画像
        profile = await self._ensure_profile(session_id)

        # 2. 获取用户 cookies
        cookies = await self._get_user_cookies(session_id)

        # 3. 候选召回
        candidates = await self.candidate_recall.recall_candidates(session_id, cookies=cookies)

        if not candidates:
            logger.warning(f"召回结果为空: {session_id}")
            return []

        # 3. LLM 重排
        reranked_candidates = await self.llm_reranker.rerank_candidates(
            session_id=session_id,
            user_profile=profile,
            candidates=candidates,
            top_k=limit
        )

        # 4. 生成推荐理由
        candidates_with_reasons = await self.reason_generator.generate_reasons(
            user_profile=profile,
            candidates=reranked_candidates
        )

        # 5. 过滤已收藏的视频
        filtered_candidates = await self._filter_already_favorited(
            session_id=session_id,
            candidates=candidates_with_reasons
        )

        # 6. 保存到候选池
        if save_to_candidates:
            await self._save_to_candidate_pool(
                session_id=session_id,
                candidates=filtered_candidates
            )

        logger.info(f"推荐生成完成: {session_id}, 推荐数: {len(filtered_candidates)}")
        return filtered_candidates

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
            # 转换为字典
            return {
                "interest_tags": profile.interest_tags or {},
                "category_distribution": profile.category_distribution or {},
                "followed_ups": profile.followed_ups or [],
                "total_favorites": profile.total_favorites or 0,
                "visual_style_preference": profile.visual_style_preference or {},
                "content_type_preference": profile.content_type_preference or {},
                "confidence_score": profile.confidence_score or 0.5
            }
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
                    return {
                        "interest_tags": new_profile.get("unified_tags", {}),
                        "category_distribution": new_profile.get("category_distribution", {}),
                        "followed_ups": new_profile.get("followed_ups", []),
                        "total_favorites": new_profile.get("total_analyzed", 0),
                        "visual_style_preference": {},
                        "content_type_preference": new_profile.get("content_type_preference", {}),
                        "confidence_score": new_profile.get("confidence_score", 0.5),
                        # 额外的多数据源信息
                        "data_sources": new_profile.get("data_sources", []),
                        "source_counts": new_profile.get("source_counts", {}),
                        "bangumi_following": new_profile.get("bangumi_following", []),
                        "cinema_favorites": new_profile.get("cinema_favorites", [])
                    }
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

    async def _filter_already_favorited(
        self,
        session_id: str,
        candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """过滤已收藏的视频"""
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

            # 过滤
            filtered = [
                cand for cand in candidates
                if cand.get("bvid") not in favorited_bvids
            ]

            logger.info(f"过滤已收藏: {len(candidates)} -> {len(filtered)}")
            return filtered

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
