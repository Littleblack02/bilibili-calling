"""
候选召回服务

多路召回策略：
1. 兴趣召回：基于用户兴趣标签搜索 B站
2. 分区召回：基于用户收藏分区分布搜索
3. 热榜召回：每日热榜新视频
4. UP主召回：关注 UP 主的新作品
5. 协同召回：相似用户喜欢的视频
"""
from typing import List, Dict, Any, Optional
from loguru import logger
from datetime import datetime
import asyncio
import re

from sqlalchemy import select

from app.services.bilibili import BilibiliService
from app.services.profile.profile_builder import get_profile_builder
from app.services.recommendation.recall_calibration import calibrate_recall_candidates
from app.database import async_session_factory
from app.config import settings


def clean_bilibili_title(title: str) -> str:
    """去除B站返回的HTML高亮标签（如 <em class="keyword">）"""
    if not title:
        return ""
    # 移除所有 HTML 标签
    cleaned = re.sub(r'<[^>]+>', '', title)
    # 清理多余的空白字符
    cleaned = ' '.join(cleaned.split())
    return cleaned.strip()


def duration_seconds(value: Any) -> int:
    """兼容 B 站搜索接口的秒数与 `HH:MM:SS`/`MM:SS` 字符串。"""
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if isinstance(value, str):
        try:
            parts = [int(part) for part in value.strip().split(":")]
            if len(parts) in {2, 3}:
                return sum(part * (60 ** index) for index, part in enumerate(reversed(parts)))
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0
    return 0


class CandidateRecall:
    """候选召回服务"""

    def __init__(self):
        self.profile_builder = get_profile_builder()

    async def recall_candidates(
        self,
        session_id: str,
        limit_per_channel: int = 20,
        cookies: Dict[str, str] = None,
        profile: Dict[str, Any] = None,
        context: Dict[str, Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        多路召回候选视频

        Args:
            session_id: 用户会话 ID
            limit_per_channel: 每路召回的最大数量
            cookies: B站登录 cookies

        Returns:
            候选视频列表，去重后按召回源标记
        """
        logger.info(f"开始候选召回: {session_id}")

        # 1. 获取用户画像
        profile = profile or await self._get_user_profile(session_id)

        context = context or {}
        candidates = []

        # “重温收藏”模式才会返回本地已收藏内容；使用 Chroma 相似度而非伪造向量分。
        if context.get("mode") == "rediscover":
            vector_candidates = await self._recall_vector_rediscovery(
                session_id=session_id,
                query=context.get("query") or " ".join(list(profile.get("interest_tags", {}))[:5]),
                limit=limit_per_channel,
            )
            candidates.extend(vector_candidates)

        bili = BilibiliService(
            sessdata=cookies.get("SESSDATA") if cookies else None,
            bili_jct=cookies.get("bili_jct") if cookies else None,
            dedeuserid=cookies.get("DedeUserID") if cookies else None
        )

        async with bili:
            semaphore = asyncio.Semaphore(3)

            async def run_channel(name: str, factory):
                async with semaphore:
                    for attempt in range(2):
                        try:
                            return await asyncio.wait_for(factory(), timeout=45)
                        except Exception as exc:
                            if attempt == 1:
                                logger.warning(f"召回通道失败 [{name}]: {exc}")
                                return []
                            await asyncio.sleep(0.5)
                return []

            channels = [
                ("interest", lambda: self._recall_by_interest(bili, profile, limit_per_channel)),
                ("recent_interest", lambda: self._recall_by_recent_interest(bili, profile, limit_per_channel)),
                ("category", lambda: self._recall_by_category(bili, profile, limit_per_channel)),
                ("trending", lambda: self._recall_by_trending(bili, limit_per_channel)),
                ("followed_up", lambda: self._recall_by_followed_ups(bili, profile, limit_per_channel)),
                ("dynamic_following", lambda: self._recall_dynamic_feed(bili, limit_per_channel)),
                ("series_update", lambda: self._recall_series_updates(bili, session_id, limit_per_channel)),
            ]
            if context.get("query"):
                channels.append((
                    "context_query",
                    lambda: self._recall_by_context(bili, context["query"], limit_per_channel),
                ))
            llm_plan = context.get("llm_recall_plan") or {}
            if llm_plan.get("applied") and llm_plan.get("queries"):
                channels.append((
                    "llm_planned",
                    lambda: self._recall_by_llm_plan(
                        bili, llm_plan, limit_per_channel
                    ),
                ))
            channel_results = await asyncio.gather(*[
                run_channel(name, factory) for name, factory in channels
            ])
            for result in channel_results:
                candidates.extend(result)

        # 3. 去重
        deduplicated = self._deduplicate_candidates(candidates)

        # 4. 添加召回源标记
        for candidate in deduplicated:
            candidate["recall_source"] = candidate.get("recall_source", "unknown")

        effective_flags = context.get("v2_feature_flags") if isinstance(context, dict) else None
        hydration_enabled = (
            bool(effective_flags.get("candidate_hydration"))
            if isinstance(effective_flags, dict)
            else settings.candidate_hydration_enabled
        )
        if hydration_enabled:
            trace_fields = {
                "bvid", "recall_source", "recall_sources", "recall_evidence",
                "raw_recall_score", "calibrated_recall_score",
                "recall_score_calibrated", "recall_tag", "recall_category",
                "recall_up_name", "recall_lookup", "follow_prior", "favorited_at",
                "recall_plan_reason", "recall_interest_label",
            }
            deduplicated = [{
                **{key: value for key, value in candidate.items() if key in trace_fields},
                "_recall_fallback": {
                    key: value for key, value in candidate.items()
                    if key not in trace_fields
                },
            } for candidate in deduplicated]

        logger.info(f"候选召回完成: {session_id}, 候选数: {len(deduplicated)}")
        return deduplicated

    async def _get_user_profile(self, session_id: str) -> Dict[str, Any]:
        """获取用户画像"""
        from app.models import UserInterestProfile
        from sqlalchemy import select

        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(UserInterestProfile).where(
                        UserInterestProfile.session_id == session_id
                    )
                )
                profile = result.scalar_one_or_none()

                if profile:
                    return {
                        "interest_tags": profile.interest_tags or {},
                        "category_distribution": profile.category_distribution or {},
                        "followed_ups": profile.followed_ups or [],
                        "total_favorites": profile.total_favorites or 0
                    }
        except Exception as e:
            logger.warning(f"获取用户画像失败: {e}")

        # 返回默认画像
        return {
            "interest_tags": {},
            "category_distribution": {},
            "followed_ups": [],
            "total_favorites": 0
        }

    async def _recall_by_interest(
        self,
        bili: BilibiliService,
        profile: Dict[str, Any],
        limit: int
    ) -> List[Dict[str, Any]]:
        """兴趣召回：基于兴趣标签搜索"""
        interest_tags = profile.get("interest_tags", {})

        if not interest_tags:
            return []

        # 取权重最高的 5 个标签
        top_tags = sorted(interest_tags.items(), key=lambda x: x[1], reverse=True)[:5]
        candidates = []

        for tag, weight in top_tags:
            try:
                result = await bili.search_bilibili(
                    keyword=tag,
                    search_type="video",
                    order="totalrank",
                    page=1
                )

                if result.get("success") and result.get("items"):
                    for item in result["items"][:limit // len(top_tags)]:
                        candidates.append({
                            "bvid": item.get("bvid", ""),
                            "title": clean_bilibili_title(item.get("title", "")),
                            "author": clean_bilibili_title(item.get("author", "")),
                            "mid": item.get("mid", 0),
                            "play": item.get("play", 0),
                            "duration": duration_seconds(item.get("duration", 0)),
                            "pic_url": item.get("pic", ""),
                            "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)) if item.get("pubdate") else None,
                            "recall_source": "interest",
                            "recall_tag": tag,
                            "raw_recall_score": float(weight),
                        })

            except Exception as e:
                logger.error(f"兴趣召回失败: {tag}, 错误: {e}")

        return candidates

    async def _recall_by_recent_interest(
        self, bili: BilibiliService, profile: Dict[str, Any], limit: int
    ) -> List[Dict[str, Any]]:
        """近期兴趣优先召回新发布内容。"""
        recent = profile.get("recent_interests") or {}
        if not recent:
            return []
        top_tags = sorted(recent.items(), key=lambda item: item[1], reverse=True)[:3]
        candidates: List[Dict[str, Any]] = []
        per_tag = max(1, limit // len(top_tags))
        for tag, weight in top_tags:
            result = await bili.search_bilibili(
                keyword=tag, search_type="video", order="pubdate", page=1
            )
            for item in (result.get("items") or [])[:per_tag] if result.get("success") else []:
                candidates.append({
                    "bvid": item.get("bvid", ""),
                    "title": clean_bilibili_title(item.get("title", "")),
                    "author": clean_bilibili_title(item.get("author", "")),
                    "mid": item.get("mid", 0),
                    "play": item.get("play", 0),
                    "duration": duration_seconds(item.get("duration", 0)),
                    "pic_url": item.get("pic", ""),
                    "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)) if item.get("pubdate") else None,
                    "recall_source": "recent_interest",
                    "recall_tag": tag,
                    "raw_recall_score": float(weight),
                })
        return candidates

    async def _recall_by_context(
        self, bili: BilibiliService, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """使用用户本次明确输入的主题召回。"""
        query = clean_bilibili_title(query).strip()[:80]
        if not query:
            return []
        result = await bili.search_bilibili(
            keyword=query, search_type="video", order="totalrank", page=1
        )
        candidates: List[Dict[str, Any]] = []
        for item in (result.get("items") or [])[:limit] if result.get("success") else []:
            candidates.append({
                "bvid": item.get("bvid", ""),
                "title": clean_bilibili_title(item.get("title", "")),
                "author": clean_bilibili_title(item.get("author", "")),
                "mid": item.get("mid", 0),
                "play": item.get("play", 0),
                "duration": duration_seconds(item.get("duration", 0)),
                "pic_url": item.get("pic", ""),
                "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)) if item.get("pubdate") else None,
                "recall_source": "context_query",
                "recall_tag": query,
                "raw_recall_score": 1.0,
            })
        return candidates

    async def _recall_by_llm_plan(
        self,
        bili: BilibiliService,
        plan: Dict[str, Any],
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Execute only the validated search calls emitted by the LLM planner."""
        queries = [row for row in (plan.get("queries") or []) if isinstance(row, dict)][:5]
        if not queries:
            return []
        candidates: List[Dict[str, Any]] = []
        per_query = max(1, limit // len(queries))
        for spec in queries:
            query = clean_bilibili_title(str(spec.get("query") or "")).strip()[:60]
            if not query:
                continue
            order = str(spec.get("order") or "totalrank")
            if order not in {"totalrank", "pubdate"}:
                order = "totalrank"
            result = await bili.search_bilibili(
                keyword=query,
                search_type="video",
                order=order,
                page=1,
            )
            items = (result.get("items") or []) if result.get("success") else []
            for item in items[:per_query]:
                candidates.append({
                    "bvid": item.get("bvid", ""),
                    "title": clean_bilibili_title(item.get("title", "")),
                    "author": clean_bilibili_title(item.get("author", "")),
                    "mid": item.get("mid", 0),
                    "play": item.get("play", 0),
                    "duration": duration_seconds(item.get("duration", 0)),
                    "pic_url": item.get("pic", ""),
                    "pubdate": datetime.fromtimestamp(item.get("pubdate", 0))
                    if item.get("pubdate") else None,
                    "recall_source": "llm_planned",
                    "recall_tag": query,
                    "raw_recall_score": float(spec.get("priority", 0.5)),
                    "recall_plan_reason": str(spec.get("reason") or "")[:160],
                    "recall_interest_label": str(
                        spec.get("interest_label") or query
                    )[:60],
                    "recall_lookup": {
                        "tool": plan.get("tool"),
                        "model": plan.get("model"),
                        "query": query,
                        "order": order,
                    },
                })
        return candidates

    async def _recall_series_updates(
        self, bili: BilibiliService, session_id: str, limit: int
    ) -> List[Dict[str, Any]]:
        """根据正在追的番剧/系列标题召回最新相关内容。"""
        from app.models import UserBangumi

        async with async_session_factory() as db:
            result = await db.execute(
                select(UserBangumi)
                .where(UserBangumi.session_id == session_id, UserBangumi.status == "watching")
                .order_by(UserBangumi.updated_at.desc())
                .limit(3)
            )
            series = list(result.scalars())
        if not series:
            return []
        candidates: List[Dict[str, Any]] = []
        per_series = max(1, limit // len(series))
        for item in series:
            response = await bili.search_bilibili(
                keyword=item.title, search_type="video", order="pubdate", page=1
            )
            for video in (response.get("items") or [])[:per_series] if response.get("success") else []:
                candidates.append({
                    "bvid": video.get("bvid", ""),
                    "title": clean_bilibili_title(video.get("title", "")),
                    "author": clean_bilibili_title(video.get("author", "")),
                    "mid": video.get("mid", 0),
                    "play": video.get("play", 0),
                    "duration": duration_seconds(video.get("duration", 0)),
                    "pic_url": video.get("pic", ""),
                    "pubdate": datetime.fromtimestamp(video.get("pubdate", 0)) if video.get("pubdate") else None,
                    "recall_source": "series_update",
                    "recall_tag": item.title,
                    "raw_recall_score": 0.8,
                })
        return candidates

    async def _recall_vector_rediscovery(
        self, session_id: str, query: str, limit: int
    ) -> List[Dict[str, Any]]:
        """从用户本地 Chroma 知识库召回旧收藏，仅用于显式重温模式。"""
        if not query.strip():
            return []
        try:
            from app.routers.knowledge import get_rag_service
            from app.models import FavoriteFolder, FavoriteVideo, VideoCache

            rag = get_rag_service()
            vector_results = await asyncio.to_thread(rag.search_with_score, query, limit * 2)
            distances: Dict[str, float] = {}
            for document, distance in vector_results:
                bvid = (document.metadata or {}).get("bvid")
                if bvid and bvid not in distances:
                    distances[bvid] = float(distance)
            if not distances:
                return []

            async with async_session_factory() as db:
                result = await db.execute(
                    select(VideoCache, FavoriteVideo.created_at)
                    .join(FavoriteVideo, FavoriteVideo.bvid == VideoCache.bvid)
                    .join(FavoriteFolder, FavoriteFolder.id == FavoriteVideo.folder_id)
                    .where(
                        FavoriteFolder.session_id == session_id,
                        VideoCache.bvid.in_(list(distances)),
                    )
                )
                rows = list(result.all())
            # 同一视频可能存在于多个收藏夹，保留最早收藏时间用于“旧收藏再发现”。
            video_by_bvid: Dict[str, tuple[Any, datetime | None]] = {}
            for video, favorited_at in rows:
                existing = video_by_bvid.get(video.bvid)
                if not existing or (favorited_at and (not existing[1] or favorited_at < existing[1])):
                    video_by_bvid[video.bvid] = (video, favorited_at)
            videos = list(video_by_bvid.values())
            videos.sort(key=lambda row: distances.get(row[0].bvid, float("inf")))
            return [{
                "bvid": video.bvid,
                "title": video.title,
                "author": video.owner_name or "",
                "mid": video.owner_mid or 0,
                "play": 0,
                "duration": video.duration or 0,
                "pic_url": video.pic_url or "",
                "pubdate": None,
                "recall_source": "vector_rediscovery",
                "recall_tag": query,
                "favorited_at": favorited_at,
                "raw_recall_score": round(
                    0.8 * (1.0 / (1.0 + max(0.0, distances[video.bvid])))
                    + 0.2 * min(1.0, max(0, (datetime.utcnow() - favorited_at).days) / 365.0)
                    if favorited_at else 0.8 * (1.0 / (1.0 + max(0.0, distances[video.bvid]))),
                    4,
                ),
            } for video, favorited_at in videos[:limit]]
        except Exception as exc:
            logger.warning(f"本地向量重温召回不可用，跳过: {exc}")
            return []

    async def _recall_by_category(
        self,
        bili: BilibiliService,
        profile: Dict[str, Any],
        limit: int
    ) -> List[Dict[str, Any]]:
        """分区召回：基于分区分布搜索"""
        category_distribution = profile.get("category_distribution", {})

        if not category_distribution:
            return []

        # 取分布最高的 5 个分区
        top_categories = sorted(category_distribution.items(), key=lambda x: x[1], reverse=True)[:5]

        CATEGORY_TO_RID = {
            "科技": 36,
            "知识": 36,
            "游戏": 4,
            "娱乐": 5,
            "音乐": 3
        }

        candidates = []

        for category, weight in top_categories:
            rid = CATEGORY_TO_RID.get(category)
            if not rid:
                continue

            try:
                result = await bili.get_trending(rid=rid)

                if result.get("success") and result.get("videos"):
                    for video in result["videos"][:limit // len(top_categories)]:
                        candidates.append({
                            "bvid": video.get("bvid", ""),
                            "title": video.get("title", ""),
                            "author": video.get("owner", {}).get("name", ""),
                            "mid": video.get("owner", {}).get("mid", 0),
                            "play": video.get("stat", {}).get("view", 0),
                            "duration": duration_seconds(video.get("duration", 0)),
                            "pic_url": "",
                            "pubdate": None,
                            "recall_source": "category",
                            "recall_category": category,
                            "raw_recall_score": float(weight),
                        })

            except Exception as e:
                logger.error(f"分区召回失败: {category}, 错误: {e}")

        return candidates

    async def _recall_by_trending(self, bili: BilibiliService, limit: int) -> List[Dict[str, Any]]:
        """热榜召回：全站热榜"""
        candidates = []

        try:
            result = await bili.get_trending(rid=0)

            if result.get("success") and result.get("videos"):
                for video in result["videos"][:limit]:
                    candidates.append({
                        "bvid": video.get("bvid", ""),
                        "title": video.get("title", ""),
                        "author": video.get("owner", {}).get("name", ""),
                        "mid": video.get("owner", {}).get("mid", 0),
                        "play": video.get("stat", {}).get("view", 0),
                        "duration": duration_seconds(video.get("duration", 0)),
                        "pic_url": "",
                        "pubdate": None,
                        "recall_source": "trending",
                        "raw_recall_score": 0.5,
                    })

        except Exception as e:
            logger.error(f"热榜召回失败: {e}")

        return candidates

    async def _recall_by_followed_ups(
        self,
        bili: BilibiliService,
        profile: Dict[str, Any],
        limit: int
    ) -> List[Dict[str, Any]]:
        """UP主召回：关注 UP 主的新作品"""
        followed_ups = profile.get("followed_ups", [])

        if not followed_ups:
            return []

        # 取关注最多的 5 个 UP 主。特别关注、普通关注和弱关注使用显式先验；
        # 名称搜索只在 MID 直连接口失败时降级使用。
        top_ups = sorted(followed_ups, key=lambda x: x.get("score", 0), reverse=True)[:5]
        candidates = []
        per_up = max(1, limit // len(top_ups))
        follow_priors = {
            "special_followings": 1.0,
            "following": 0.72,
            "followings": 0.72,
            "whisper_followings": 0.45,
        }

        for up in top_ups:
            mid = up.get("mid", 0)
            name = up.get("name", "")

            if not mid or not name:
                continue

            try:
                direct = await bili.get_up_videos(mid=int(mid), ps=per_up, order="pubdate")
                lookup = "mid_direct"
                if direct.get("success"):
                    up_videos = direct.get("videos") or []
                else:
                    lookup = "name_search_fallback"
                    result = await bili.search_bilibili(
                        keyword=name,
                        search_type="video",
                        order="pubdate",
                        page=1,
                    )
                    up_videos = [
                        item for item in (result.get("items") or [])
                        if result.get("success") and int(item.get("mid") or 0) == int(mid)
                    ]

                source = str(up.get("source") or up.get("following_source") or "following")
                follow_prior = follow_priors.get(source, 0.60)
                profile_score = max(0.0, min(1.0, float(up.get("score", 0.5))))
                for video in up_videos[:per_up]:
                    video_mid = int(video.get("mid") or mid)
                    if video.get("mid") and video_mid != int(mid):
                        continue
                    published = video.get("created") or video.get("pubdate")
                    candidates.append({
                        "bvid": video.get("bvid", ""),
                        "title": clean_bilibili_title(video.get("title", "")),
                        "author": clean_bilibili_title(video.get("author", "")) or name,
                        "mid": int(mid),
                        "play": video.get("play"),
                        "duration": duration_seconds(
                            video.get("length", video.get("duration"))
                        ),
                        "pic_url": video.get("pic", ""),
                        "pubdate": datetime.fromtimestamp(published) if published else None,
                        "recall_source": "followed_up",
                        "recall_up_name": name,
                        "recall_lookup": lookup,
                        "follow_prior": follow_prior,
                        "raw_recall_score": round(
                            follow_prior * (0.65 + 0.35 * profile_score), 6
                        ),
                    })

            except Exception as e:
                logger.error(f"UP主召回失败: {name}, 错误: {e}")

        return candidates

    async def _recall_dynamic_feed(
        self, bili: BilibiliService, limit: int
    ) -> List[Dict[str, Any]]:
        """In-network candidate source inspired by X Algorithm's source split.

        Feed exposure is never converted into positive profile affinity; it is
        used only as a fresh candidate source and still passes normal ranking,
        filtering and diversity constraints.
        """
        rows = await bili.get_dynamic_feed()
        candidates: List[Dict[str, Any]] = []
        for item in rows:
            modules = item.get("modules") or {}
            major = ((modules.get("module_dynamic") or {}).get("major") or {})
            archive = major.get("archive") or {}
            author = modules.get("module_author") or {}
            bvid = archive.get("bvid")
            if not bvid:
                continue
            stat = archive.get("stat") or {}
            candidates.append({
                "bvid": bvid,
                "title": clean_bilibili_title(archive.get("title", "")),
                "author": author.get("name", ""),
                "mid": author.get("mid", 0),
                "play": stat.get("play", 0) if isinstance(stat, dict) else 0,
                "duration": duration_seconds(archive.get("duration_text", 0)),
                "pic_url": archive.get("cover", ""),
                "pubdate": datetime.fromtimestamp(author["pub_ts"]) if author.get("pub_ts") else None,
                "recall_source": "dynamic_following",
                "raw_recall_score": 0.65,
            })
            if len(candidates) >= limit:
                break
        return candidates

    def _deduplicate_candidates(
        self,
        candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """去重候选视频，并限制每个画像维度最多2条"""
        seen_by_bvid: Dict[str, Dict[str, Any]] = {}
        deduplicated = []

        # 按画像维度统计数量
        tag_counts = {}
        category_counts = {}
        up_counts = {}
        trending_count = 0

        for candidate in candidates:
            bvid = candidate.get("bvid", "")
            if not bvid:
                continue

            if bvid in seen_by_bvid:
                existing = seen_by_bvid[bvid]
                sources = existing.setdefault("recall_sources", [existing.get("recall_source", "unknown")])
                source = candidate.get("recall_source", "unknown")
                if source not in sources:
                    sources.append(source)
                existing.setdefault("recall_evidence", []).append({
                    "source": source,
                    "raw_score": candidate.get("raw_recall_score"),
                    "tag": candidate.get("recall_tag"),
                    "category": candidate.get("recall_category"),
                    "up_mid": candidate.get("mid") if source == "followed_up" else None,
                    "follow_prior": candidate.get("follow_prior"),
                })
                existing["raw_recall_score"] = max(
                    float(existing.get("raw_recall_score", 0.0)),
                    float(candidate.get("raw_recall_score", 0.0)),
                )
                continue

            recall_source = candidate.get("recall_source", "unknown")

            # 细分维度限制：每个画像维度最多 2 条
            if recall_source in {
                "interest", "recent_interest", "context_query", "llm_planned"
            }:
                tag = candidate.get("recall_tag", "")
                if tag_counts.get(tag, 0) >= 2:
                    continue
                tag_counts[tag] = tag_counts.get(tag, 0) + 1

            elif recall_source == "category":
                category = candidate.get("recall_category", "")
                if category_counts.get(category, 0) >= 2:
                    continue
                category_counts[category] = category_counts.get(category, 0) + 1

            elif recall_source == "followed_up":
                up_name = candidate.get("recall_up_name", "")
                if up_counts.get(up_name, 0) >= 2:
                    continue
                up_counts[up_name] = up_counts.get(up_name, 0) + 1

            elif recall_source == "trending":
                if trending_count >= 10:
                    continue
                trending_count += 1

            candidate["recall_sources"] = [recall_source]
            candidate["recall_evidence"] = [{
                "source": recall_source,
                "raw_score": candidate.get("raw_recall_score"),
                "tag": candidate.get("recall_tag"),
                "category": candidate.get("recall_category"),
                "up_mid": candidate.get("mid") if recall_source == "followed_up" else None,
                "follow_prior": candidate.get("follow_prior"),
            }]
            seen_by_bvid[bvid] = candidate
            deduplicated.append(candidate)

        return calibrate_recall_candidates(deduplicated)


# 单例
_candidate_recall: Optional[CandidateRecall] = None


def get_candidate_recall() -> CandidateRecall:
    """获取候选召回服务单例"""
    global _candidate_recall
    if _candidate_recall is None:
        _candidate_recall = CandidateRecall()
    return _candidate_recall
