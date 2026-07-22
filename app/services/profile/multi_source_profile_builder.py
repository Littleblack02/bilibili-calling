"""
多数据源用户画像构建器（Phase 2 重构）

支持的数据源：
1. 收藏夹（favorites）- 长期兴趣
2. 追番列表（bangumi）- 番剧偏好
3. 历史记录（history）- 即时兴趣
4. 稍后观看（watchlater）- 潜在兴趣
5. 影视收藏（cinema）- 影视偏好

每通道取样策略：
- 收藏夹：前10个视频（去重）
- 追番：全部（一般不多）
- 历史记录：最近50条
- 稍后观看：全部
- 影视收藏：全部
"""
import asyncio
import json
from typing import Dict, List, Any, Optional, Set
from collections import Counter
from datetime import datetime, timedelta
from loguru import logger

from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import (
    FavoriteVideo, FavoriteFolder, VideoCache, VideoCoverAnalysis,
    UserInterestProfile, UserProfileEmbeddingIndex,
    UserBangumi, UserWatchHistory, UserWatchLater, UserCinema, BangumiUpdateLog,
    LongTermMemory, UserContentSignal
)
from app.services.gemma.cover_analyzer import get_cover_analyzer
from app.services.bilibili import BilibiliService
from app.services.ontology import get_ontology_service
from app.services.recommendation.temporal_interest import (
    build_temporal_ontology_features,
    item_occurred_at,
    temporal_weight,
)
from app.services.profile.signals import parse_datetime, signal_to_profile_item, upsert_user_content_signal
from app.services.profile.sync import (
    begin_sync_run,
    complete_sync_run,
    fail_sync_run,
)
from app.config import settings


class MultiSourceProfileBuilder:
    """多数据源用户画像构建器"""

    # 每通道采集数量限制
    MAX_FAVORITES = 10      # 收藏夹每个取10个
    MAX_HISTORY = 10        # 历史记录取10条
    MAX_WATCHLATER = 10     # 稍后观看取10个
    MAX_CINEMA = 10         # 影视收藏取10个
    MAX_CINEMA_SYNC_ITEMS = 300  # 超过此安全上限时只做部分快照，禁止失效旧信号

    # 兴趣标签权重（用于综合评分）
    # Base/source/recency weights are centralized in temporal_interest.py.
    # This compatibility map is retained for older callers only.
    SOURCE_WEIGHTS = {
        "favorites": 0.90,
        "history": 1.00,
        "watchlater": 0.82,
        "bangumi": 0.78,
        "cinema": 0.68,
    }

    def __init__(self):
        self.cover_analyzer = get_cover_analyzer()
        self.enable_cover_analysis = True  # 启用封面分析

    @staticmethod
    def _has_meaningful_data(data_sources: Dict[str, List[Dict]]) -> bool:
        """Exposure-only dynamic items do not constitute a user profile alone."""
        return any(
            isinstance(items, list) and items
            for source, items in (data_sources or {}).items()
            if source not in {"dynamic_feed", "extended"}
        )

    async def build_comprehensive_profile(
        self,
        session_id: str,
        cookies: Dict[str, str] = None,
        force_rebuild: bool = False
    ) -> Dict[str, Any]:
        """
        构建全面的用户画像（多数据源）

        Args:
            session_id: 用户会话 ID
            cookies: B站登录 cookies
            force_rebuild: 是否强制重建

        Returns:
            完整的用户画像字典
        """
        logger.info("开始构建多数据源用户画像")
        from app.services.privacy import paused_channels
        async with async_session_factory() as privacy_db:
            privacy_paused = await paused_channels(privacy_db, session_id)

        # 1. 采集所有数据源
        data_sources = {}
        bilibili = BilibiliService(
            sessdata=cookies.get("SESSDATA") if cookies else None,
            bili_jct=cookies.get("bili_jct") if cookies else None,
            dedeuserid=cookies.get("DedeUserID") if cookies else None
        )

        if not force_rebuild:
            # 不强制重建时，优先从数据库加载已有数据
            logger.info(f"尝试从数据库加载已有数据: {session_id}")
            data_sources = await self._load_from_database(session_id)
            has_data = self._has_meaningful_data(data_sources)
            if not has_data:
                logger.info(f"数据库中没有已有数据，开始采集: {session_id}")
            else:
                # 数据库有数据时也刷新账号级通道。这样升级前已有收藏的
                # 用户无需清库或强制重建，就能补齐新增画像信号。
                try:
                    async with bilibili:
                        user_info = await bilibili.get_user_info()
                        mid = user_info.get("mid", 0) if user_info else 0
                        if mid:
                            followings, cinema, extended = await asyncio.gather(
                                self._collect_followings(bilibili, mid),
                                self._collect_cinema(bilibili),
                                bilibili.get_extended_profile_channels(mid),
                            )
                            statuses = bilibili.profile_channel_statuses()
                            if statuses.get("followings", {}).get("status") == "success":
                                data_sources["followings"] = followings
                            if statuses.get("cinema", {}).get("status") == "success":
                                data_sources["cinema"] = cinema
                            for source, items in extended.items():
                                normalized = [
                                    self._normalize_extended_item(source, item)
                                    for item in items
                                    if isinstance(item, dict)
                                ]
                                if statuses.get(source, {}).get("status") == "success":
                                    data_sources[source] = [
                                        item for item in normalized if item.get("title")
                                    ]
                            logger.info(
                                f"增量刷新画像通道: 关注={len(followings)}, "
                                f"影视={len(cinema)}, 扩展={len(extended)}"
                            )
                except Exception as e:
                    logger.warning(f"增量刷新账号画像通道失败，保留本地数据: {e}")
        else:
            data_sources = {}

        if force_rebuild or not self._has_meaningful_data(data_sources):
            try:
                async with bilibili:
                    # 并行采集所有数据源
                    data_sources = await self._collect_all_sources(bilibili, session_id)
            except Exception as e:
                logger.error(f"采集数据源失败: {e}")
                # 如果采集失败，尝试从数据库读取已有数据
                data_sources = await self._load_from_database(session_id)

        # Paused channels retain their raw evidence for reversible privacy
        # control, but they are excluded from profile computation immediately.
        data_sources = {
            source: items for source, items in data_sources.items()
            if source not in privacy_paused
        }

        if not self._has_meaningful_data(data_sources):
            logger.warning(f"没有采集到任何数据: {session_id}")
            return self._get_empty_profile(session_id)

        # 2. 保存采集的数据到数据库
        channel_sync_statuses = bilibili.profile_channel_statuses()
        await self._save_collected_data(
            session_id, data_sources, channel_sync_statuses=channel_sync_statuses
        )

        # 3. 合并去重视频列表
        all_videos = self._merge_and_deduplicate(data_sources)

        # 4. 分析封面风格（新增）
        visual_style_preference = {}
        if self.enable_cover_analysis and all_videos:
            logger.info(f"开始分析封面风格: {session_id}")
            visual_style_preference = await self._analyze_cover_styles(all_videos, session_id)

        # 4. 提取各维度兴趣标签
        favorite_tags = self._extract_tags_from_list(
            data_sources.get("favorites", []),
            source="favorites",
        )
        recent_tags = self._extract_tags_from_list(
            data_sources.get("history", []),
            source="history",
        )
        watchlater_tags = self._extract_tags_from_list(
            data_sources.get("watchlater", []),
            source="watchlater",
        )

        # 5. 提取番剧偏好
        bangumi_prefs = self._extract_bangumi_preferences(data_sources.get("bangumi", []))
        bangumi_temporal_tags = self._extract_tags_from_list(
            data_sources.get("bangumi", []), source="bangumi"
        )

        # 6. 提取影视偏好
        cinema_prefs = self._extract_cinema_preferences(data_sources.get("cinema", []))
        cinema_temporal_tags = self._extract_tags_from_list(
            data_sources.get("cinema", []), source="cinema"
        )

        # 7. Time-aware ontology profile: old favorites/bangumi decay, while
        # recent consumption and explicit intent remain strong. Concepts are
        # represented as multiple semantic clusters instead of one flat vector.
        profile_features = build_temporal_ontology_features(
            data_sources,
            v2_enabled=settings.v2_feature_flags(session_id)["temporal_affinity_v2"],
        )
        profile_features["privacy"] = {
            "paused_channels": sorted(privacy_paused),
            "participating_channels": sorted(data_sources),
        }
        ontology = get_ontology_service()
        ontology_tags = {}
        for concept_id, score in profile_features.get("concept_affinities", {}).items():
            concept = ontology.concept(concept_id)
            if concept:
                ontology_tags[concept["label"]] = score
        recent_ontology_tags = {}
        for concept_id, score in profile_features.get("recent_concept_affinities", {}).items():
            concept = ontology.concept(concept_id)
            if concept:
                recent_ontology_tags[concept["label"]] = score

        # 8. 统一兴趣标签（时间加权 + Ontology 规范化）
        tag_sources = {
            "favorites": favorite_tags,
            "history": recent_tags,
            "watchlater": watchlater_tags,
            "bangumi": {**bangumi_prefs.get("tags", {}), **bangumi_temporal_tags},
            "cinema": {**cinema_prefs.get("tags", {}), **cinema_temporal_tags},
            "ontology": ontology_tags,
        }
        for source, items in data_sources.items():
            if source in tag_sources or source in {"followings", "special_followings", "whisper_followings"}:
                continue
            if isinstance(items, list) and items:
                tag_sources[source] = self._extract_tags_from_list(items, source=source)
        unified_tags = self._merge_tags_with_weights(tag_sources)

        # 8. 提取关注的 UP 主（使用真实关注列表）
        followings_list = list(data_sources.get("followings", []))
        for source, score in (("special_followings", 1.0), ("whisper_followings", 0.65)):
            for item in data_sources.get(source, []):
                followings_list.append({
                    "mid": item.get("owner_mid") or item.get("id"),
                    "name": item.get("owner_name") or item.get("title"),
                    "face": (item.get("payload") or {}).get("face", ""),
                    "sign": (item.get("payload") or {}).get("sign", ""),
                    "profile_score": score,
                    "following_source": source,
                })
        followed_ups = self._extract_followed_ups(all_videos, followings_list)

        # 9. 分析分区分布
        category_distribution = self._analyze_category_distribution(all_videos)

        # 10. 构建完整画像
        profile = {
            "session_id": session_id,
            # 长期兴趣（收藏夹）
            "favorite_tags": favorite_tags,
            "favorite_categories": self._get_category_from_tags(favorite_tags),
            "favorite_ups": [u for u in followed_ups if u.get("source") == "favorite"][:10],
            # 即时兴趣（历史记录）
            "recent_tags": recent_tags,
            "recent_categories": self._get_category_from_tags(recent_tags),
            "recent_ups": [u for u in followed_ups if u.get("source") == "history"][:10],
            # 番剧偏好
            "bangumi_following": bangumi_prefs.get("list", []),
            "bangumi_types": bangumi_prefs.get("types", {}),
            "bangumi_genres": bangumi_prefs.get("genres", []),
            # 影视偏好
            "cinema_favorites": cinema_prefs.get("list", []),
            "cinema_types": cinema_prefs.get("types", {}),
            "cinema_genres": cinema_prefs.get("genres", []),
            # 统一兴趣（最重要）
            "unified_tags": unified_tags,
            "recent_interests": self._merge_tags_with_weights({
                "history": recent_tags,
                "ontology": recent_ontology_tags,
            }),
            "primary_interests": self._get_top_interests(unified_tags, top_n=10),
            "profile_features": profile_features,
            # 关注的 UP 主
            "followed_ups": followed_ups,  # 移除数量限制，返回所有UP主
            # 分区分布
            "category_distribution": category_distribution,
            # 内容类型偏好
            "content_type_preference": {
                "video": self._calculate_type_ratio(all_videos, "video"),
                "bangumi": len(bangumi_prefs.get("list", [])) / max(len(all_videos), 1),
                "cinema": len(cinema_prefs.get("list", [])) / max(len(all_videos), 1),
            },
            # 统计信息
            "total_analyzed": len(all_videos),
            "data_sources": list(data_sources.keys()),
            "source_counts": {k: len(v) for k, v in data_sources.items()},
            "channel_sync_statuses": channel_sync_statuses,
            # 置信度
            "confidence_score": self._calculate_confidence(data_sources),
            "last_update_source": "multi_source_sync",
            "updated_at": datetime.utcnow()
        }

        # 11. 保存画像到数据库
        await self._save_profile(profile)

        # 12. 向量化并存储到 ChromaDB
        await self._vectorize_and_store_profile(profile)

        # 13. 生成毒舌总结
        profile["summary"] = await self._generate_profile_summary(profile)
        logger.info(f"画像总结生成完成: {profile['summary'][:50]}...")

        # 14. 保存到长期记忆
        await self._save_to_long_term_memory(profile)

        logger.info(f"多数据源画像构建完成，数据源: {profile['data_sources']}")
        return profile

    async def _collect_all_sources(
        self,
        bilibili: BilibiliService,
        session_id: str
    ) -> Dict[str, List[Dict]]:
        """并行采集所有数据源"""
        logger.info(f"开始并行采集数据源...")

        # 获取用户信息（获取 mid）
        user_info = await bilibili.get_user_info()
        # get_user_info 返回 {"mid": xxx, ...} 或 {}
        mid = user_info.get("mid", 0) if user_info else 0
        logger.info(f"获取到用户 mid: {mid}")

        # 并行执行所有采集任务
        tasks = []

        # 1. 收藏夹
        tasks.append(self._collect_favorites(bilibili, session_id))

        # 2. 追番（需要 mid）
        if mid:
            tasks.append(self._collect_bangumi(bilibili, mid))
        else:
            logger.warning("无法获取 mid，跳过追番采集")
            tasks.append(asyncio.sleep(0, result=[]))

        # 3. 历史记录
        tasks.append(self._collect_history(bilibili))

        # 4. 稍后观看
        tasks.append(self._collect_watchlater(bilibili))

        # 5. 关注列表（需要 mid）
        if mid:
            tasks.append(self._collect_followings(bilibili, mid))
        else:
            logger.warning("无法获取 mid，跳过关注列表采集")
            tasks.append(asyncio.sleep(0, result=[]))

        # 6. 影视收藏内容
        tasks.append(self._collect_cinema(bilibili))

        # 7. 其他可读用户信号：话题/专栏/课程/笔记/追漫/
        # 直播历史/特别关注等。每路内部失败隔离。
        if mid:
            tasks.append(bilibili.get_extended_profile_channels(mid))
        else:
            tasks.append(asyncio.sleep(0, result={}))

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data_sources = {}
        source_names = [
            "favorites", "bangumi", "history", "watchlater", "followings",
            "cinema", "extended",
        ]

        for i, result in enumerate(results):
            source_name = source_names[i]
            if isinstance(result, Exception):
                logger.warning(f"采集 {source_name} 失败: {result}")
                data_sources[source_name] = []
            else:
                if source_name == "extended":
                    for extended_name, items in result.items():
                        normalized = [
                            self._normalize_extended_item(extended_name, item)
                            for item in items
                            if isinstance(item, dict)
                        ]
                        data_sources[extended_name] = [item for item in normalized if item.get("title")]
                        logger.info(f"采集 {extended_name}: {len(data_sources[extended_name])} 条")
                else:
                    data_sources[source_name] = result
                    logger.info(f"采集 {source_name}: {len(result)} 条")

        return data_sources

    async def _collect_favorites(
        self,
        bilibili: BilibiliService,
        session_id: str
    ) -> List[Dict]:
        """采集收藏夹数据"""
        try:
            # 从数据库获取收藏夹信息
            async with async_session_factory() as db:
                signal_result = await db.execute(
                    select(UserContentSignal).where(
                        UserContentSignal.session_id == session_id,
                        UserContentSignal.source == "favorites",
                        UserContentSignal.is_active == True,
                    )
                )
                favorite_signals = {signal.item_id: signal for signal in signal_result.scalars()}
                result = await db.execute(
                    select(FavoriteVideo.bvid, VideoCache.title, VideoCache.description,
                           VideoCache.owner_name, VideoCache.owner_mid, VideoCache.pic_url,
                           FavoriteFolder.title.label("folder_title"))
                    .join(FavoriteFolder, FavoriteFolder.id == FavoriteVideo.folder_id)
                    .join(VideoCache, VideoCache.bvid == FavoriteVideo.bvid)
                    .where(FavoriteFolder.session_id == session_id)
                    .where(FavoriteVideo.is_selected == True)
                    .limit(self.MAX_FAVORITES * 3)  # 多取一些，后面会按收藏夹去重
                )

                videos = []
                seen_bvids = set()
                folder_count = Counter()

                for row in result.fetchall():
                    bvid = row.bvid
                    if bvid in seen_bvids:
                        continue

                    folder_title = row.folder_title or "默认"
                    if folder_count.get(folder_title, 0) >= self.MAX_FAVORITES:
                        continue

                    videos.append({
                        "bvid": bvid,
                        "title": row.title,
                        "description": row.description or "",
                        "owner_name": row.owner_name,
                        "owner_mid": row.owner_mid,
                        "pic_url": row.pic_url,
                        "folder_title": folder_title,
                        "occurred_at": (
                            favorite_signals[bvid].occurred_at
                            if bvid in favorite_signals else None
                        ),
                        "strength": (
                            favorite_signals[bvid].strength
                            if bvid in favorite_signals else 1.0
                        ),
                        "source": "favorites"
                    })

                    seen_bvids.add(bvid)
                    folder_count[folder_title] += 1

                return videos

        except Exception as e:
            logger.error(f"采集收藏夹数据失败: {e}")
            return []

    async def _collect_bangumi(
        self,
        bilibili: BilibiliService,
        mid: int
    ) -> List[Dict]:
        """采集追番数据（只取前10个，去掉无意义的标签）"""
        try:
            bangumi_list = await bilibili.get_user_bangumi(mid=mid)
            # 需要过滤掉的无意义标签
            skip_patterns = [
                '第.*季', '第.*部', '第.*篇',  # 第几季/部/篇
                '训练篇', '特别篇', 'OAD', 'OVA',
                'SP', '剧场版', '总集篇',
                '中配版', '日配版', '国配版', '双语版',
                '高清版', '完整版', '重置版',
            ]

            import re

            def clean_title(title: str) -> str:
                """清理标题，去掉无意义的标签"""
                # 去掉第X季/第X部/第X篇
                title = re.sub(r'第[一二三四五六七八九十百千\d]+[季部篇]', '', title)
                # 去掉其他标记
                for pattern in ['训练篇', '特别篇', 'OAD', 'OVA', 'SP', '剧场版', '总集篇',
                               '中配版', '日配版', '国配版', '双语版',
                               '高清版', '完整版', '重置版']:
                    title = title.replace(pattern, '')
                # 清理多余空格
                title = re.sub(r'\s+', ' ', title).strip()
                return title

            return [{
                "season_id": item.get("season_id", 0),
                "title": clean_title(item.get("title", "")),
                "cover": item.get("cover", ""),
                "type": item.get("type", 1),
                "progress": item.get("progress", {}),
                "status": item.get("status", "watching"),
                "source": "bangumi"
            } for item in bangumi_list]

        except Exception as e:
            logger.error(f"采集追番数据失败: {e}")
            bilibili._record_profile_channel_status(
                "bangumi", status="failed", capability_status="degraded",
                error_summary=f"profile normalization failed: {type(e).__name__}",
            )
            return []

    async def _collect_history(
        self,
        bilibili: BilibiliService
    ) -> List[Dict]:
        """采集历史记录"""
        try:
            history = await bilibili.get_watch_history(pn=1, ps=self.MAX_HISTORY)
            return [{
                "bvid": item.get("bvid", ""),
                "title": item.get("title", ""),
                "cover": item.get("cover", ""),
                "owner_name": item.get("owner", {}).get("name", ""),
                "owner_mid": item.get("owner", {}).get("mid", 0),
                "duration": item.get("duration", 0),
                "progress": item.get("progress", 0),
                "view_at": item.get("view_at", 0),
                "tname": item.get("tname", ""),
                "source": "history"
            } for item in history]

        except Exception as e:
            logger.error(f"采集历史记录失败: {e}")
            bilibili._record_profile_channel_status(
                "history", status="failed", capability_status="degraded",
                error_summary=f"profile normalization failed: {type(e).__name__}",
            )
            return []

    async def _collect_watchlater(
        self,
        bilibili: BilibiliService
    ) -> List[Dict]:
        """采集稍后观看"""
        try:
            watchlater = await bilibili.get_watchlater_list()
            return [{
                "bvid": item.get("bvid", ""),
                "title": item.get("title", ""),
                "cover": item.get("cover", ""),
                "owner_name": item.get("owner", {}).get("name", ""),
                "owner_mid": item.get("owner", {}).get("mid", 0),
                "duration": item.get("duration", 0),
                "add_time": item.get("add_time", 0),
                "source": "watchlater"
            } for item in watchlater]

        except Exception as e:
            logger.error(f"采集稍后观看失败: {e}")
            bilibili._record_profile_channel_status(
                "watchlater", status="failed", capability_status="degraded",
                error_summary=f"profile normalization failed: {type(e).__name__}",
            )
            return []

    async def _collect_followings(
        self,
        bilibili: BilibiliService,
        mid: int
    ) -> List[Dict]:
        """采集��注列表"""
        try:
            followings = await bilibili.get_all_followings(mid)
            return [{
                "mid": item.get("mid", 0),
                "name": item.get("uname", ""),
                "face": item.get("face", ""),
                "sign": item.get("sign", ""),
                "official": item.get("official", {}),
                "vip": item.get("vip", {}),
                "source": "following"
            } for item in followings]

        except Exception as e:
            logger.error(f"采集关注列表失败: {e}")
            bilibili._record_profile_channel_status(
                "followings", status="failed", capability_status="degraded",
                error_summary=f"profile normalization failed: {type(e).__name__}",
            )
            return []

    async def _collect_cinema(self, bilibili: BilibiliService) -> List[Dict]:
        """采集用户影视类收藏夹的代表内容。"""
        try:
            folders = await bilibili.get_cinema_favorites()
            folder_status = bilibili.profile_channel_statuses().get("cinema", {})
            if not folders:
                return []
            videos: list[dict[str, Any]] = []
            cinema_folders = [folder for folder in folders if folder.get("type") != "other"]
            aggregate_success = folder_status.get("status") == "success"
            aggregate_full = bool(folder_status.get("full_snapshot"))
            total_pages = int(folder_status.get("page_count") or 0)
            error_summary = folder_status.get("error_summary")
            for folder in cinema_folders:
                rows = await bilibili.get_cinema_favorite_videos(
                    int(folder.get("media_id", 0)),
                    ps=50,
                )
                page_status = bilibili.profile_channel_statuses().get("cinema", {})
                total_pages += int(page_status.get("page_count") or 0)
                if page_status.get("status") != "success":
                    aggregate_success = False
                    aggregate_full = False
                    error_summary = page_status.get("error_summary")
                else:
                    aggregate_full = aggregate_full and bool(
                        page_status.get("full_snapshot")
                    )
                for row in rows:
                    owner = row.get("owner") or {}
                    videos.append({
                        **row,
                        "owner_mid": owner.get("mid"),
                        "owner_name": owner.get("name"),
                        "tname": folder.get("type") or "影视",
                        "folder_title": folder.get("title"),
                        "occurred_at": row.get("fav_time") or row.get("pubdate"),
                        "source": "cinema",
                    })
                    if len(videos) >= self.MAX_CINEMA_SYNC_ITEMS:
                        aggregate_full = False
                        break
                if len(videos) >= self.MAX_CINEMA_SYNC_ITEMS:
                    break
            bilibili._record_profile_channel_status(
                "cinema",
                status="success" if aggregate_success else "failed",
                capability_status="working" if aggregate_success else "degraded",
                count=len(videos),
                page_count=total_pages,
                full_snapshot=aggregate_success and aggregate_full,
                error_summary=error_summary,
            )
            return videos
        except Exception as exc:
            logger.warning(f"影视信号采集失败: {exc}")
            bilibili._record_profile_channel_status(
                "cinema", status="failed", capability_status="degraded",
                error_summary=f"profile collection failed: {type(exc).__name__}",
            )
            return []

    @staticmethod
    def _nested(item: Dict[str, Any], *paths: str) -> Any:
        for path in paths:
            value: Any = item
            for part in path.split("."):
                value = value.get(part) if isinstance(value, dict) else None
            if value not in (None, "", [], {}):
                return value
        return None

    def _normalize_extended_item(self, source: str, item: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize heterogeneous Bilibili response shapes for profile modeling."""
        title = self._nested(
            item,
            "title", "name", "uname", "tag_name", "topic_name", "season_title",
            "org_title", "room_title", "medal_info.medal_name",
            "modules.module_dynamic.major.archive.title",
            "modules.module_dynamic.major.pgc.title",
            "modules.module_dynamic.desc.text",
        ) or ""
        description = self._nested(
            item,
            "description", "desc", "summary", "intro", "sign",
            "modules.module_dynamic.desc.text",
        ) or ""
        creator_mid = self._nested(
            item,
            "owner_mid", "mid", "uid", "up_mid", "upper.mid", "author.mid",
            "medal_info.target_id", "modules.module_author.mid",
        )
        creator_name = self._nested(
            item,
            "owner_name", "uname", "author_name", "upper.name", "author.name",
            "medal_info.target_name", "modules.module_author.name",
        ) or ""
        item_id = self._nested(
            item,
            "bvid", "id", "id_str", "tag_id", "topic_id", "season_id",
            "media_id", "roomid", "room_id", "comic_id", "mid",
            "modules.module_dynamic.major.archive.bvid",
        )
        occurred_at = self._nested(
            item,
            "occurred_at", "view_at", "fav_time", "add_time", "mtime", "ctime",
            "pub_ts", "pubtime", "last_time", "modules.module_author.pub_ts",
        )
        category = self._nested(item, "tname", "category", "type_name", "area_name") or ""
        tags = []
        raw_tags = item.get("tags") or item.get("tag_list") or []
        if isinstance(raw_tags, list):
            for tag in raw_tags:
                if isinstance(tag, str):
                    tags.append(tag)
                elif isinstance(tag, dict):
                    value = tag.get("name") or tag.get("tag_name")
                    if value:
                        tags.append(str(value))

        strength = 1.0
        if source == "fan_medals":
            level = self._nested(item, "medal_info.level", "level") or 1
            try:
                strength = min(1.5, 0.6 + float(level) / 30.0)
            except (TypeError, ValueError):
                strength = 0.8
        elif source == "dynamic_feed":
            strength = 0.2
        elif source in {"special_followings", "favorite_courses", "courses"}:
            strength = 1.2

        return {
            "id": str(item_id or f"{source}:{title}"),
            "bvid": self._nested(item, "bvid", "modules.module_dynamic.major.archive.bvid") or "",
            "title": str(title),
            "description": str(description),
            "owner_mid": int(creator_mid) if str(creator_mid or "").isdigit() else None,
            "owner_name": str(creator_name),
            "tname": str(category),
            "tags": tags,
            "occurred_at": occurred_at,
            "strength": strength,
            "item_type": (
                "creator" if source in {"special_followings", "whisper_followings", "fan_medals"}
                else "video" if self._nested(item, "bvid", "modules.module_dynamic.major.archive.bvid")
                else source.rstrip("s")
            ),
            "source": source,
            "payload": item,
        }

    async def _load_from_database(self, session_id: str) -> Dict[str, List[Dict]]:
        """从数据库加载已有数据"""
        data_sources = {"favorites": [], "bangumi": [], "history": [], "watchlater": [], "followings": []}

        try:
            async with async_session_factory() as db:
                # 加载收藏夹
                result = await db.execute(
                    select(
                        VideoCache,
                        FavoriteFolder.title.label("folder_title"),
                        FavoriteVideo.created_at.label("observed_at"),
                    )
                    .join(FavoriteVideo, FavoriteVideo.bvid == VideoCache.bvid)
                    .join(FavoriteFolder, FavoriteFolder.id == FavoriteVideo.folder_id)
                    .where(FavoriteFolder.session_id == session_id)
                    .where(FavoriteVideo.is_selected == True)
                    .limit(100)
                )

                for row in result.fetchall():
                    data_sources["favorites"].append({
                        "bvid": row.bvid,
                        "title": row.title,
                        "description": row.description,
                        "owner_name": row.owner_name,
                        "owner_mid": row.owner_mid,
                        "pic_url": row.pic_url,
                        "folder_title": row.folder_title,
                        # This is only a local observation fallback. When the
                        # API supplied fav_time, the normalized signal below
                        # replaces it with the actual event time.
                        "occurred_at": None,
                        "observed_at": row.observed_at,
                        "source": "favorites"
                    })

                # 加载追番
                result = await db.execute(
                    select(UserBangumi).where(UserBangumi.session_id == session_id)
                )
                for record in result.scalars():
                    data_sources["bangumi"].append({
                        "season_id": record.season_id,
                        "title": record.title,
                        "cover": record.cover,
                        "type": record.bangumi_type,
                        "status": record.status,
                        # updated_at is a database synchronization time, not a
                        # follow event. Unknown add_time must remain unknown so
                        # an old bangumi entry cannot masquerade as recent.
                        "occurred_at": record.add_time,
                        "source": "bangumi"
                    })

                # 加载历史记录
                result = await db.execute(
                    select(UserWatchHistory)
                    .where(UserWatchHistory.session_id == session_id)
                    .order_by(UserWatchHistory.view_at.desc())
                    .limit(self.MAX_HISTORY)
                )
                for record in result.scalars():
                    data_sources["history"].append({
                        "bvid": record.bvid,
                        "title": record.title,
                        "cover": record.cover,
                        "owner_name": record.owner_name,
                        "owner_mid": record.owner_mid,
                        "tname": record.tname,
                        "view_at": record.view_at,
                        "duration": record.duration,
                        "progress": record.progress,
                        "strength": (
                            min(1.2, max(0.2, (record.progress or 0) / max(1, record.duration or 1)))
                            if record.duration else 0.7
                        ),
                        "source": "history"
                    })

                # 加载稍后观看
                result = await db.execute(
                    select(UserWatchLater)
                    .where(UserWatchLater.session_id == session_id)
                    .where(UserWatchLater.status == 'pending')
                )
                for record in result.scalars():
                    data_sources["watchlater"].append({
                        "bvid": record.bvid,
                        "title": record.title,
                        "cover": record.cover,
                        "owner_name": record.owner_name,
                        "owner_mid": record.owner_mid,
                        "add_time": record.add_time,
                        "source": "watchlater"
                    })

                # Load every normalized extended signal. It also restores real
                # favorite timestamps that the legacy FavoriteVideo table does
                # not contain.
                signal_result = await db.execute(
                    select(UserContentSignal).where(
                        UserContentSignal.session_id == session_id,
                        UserContentSignal.is_active == True,
                    )
                )
                for signal in signal_result.scalars():
                    item = signal_to_profile_item(signal)
                    source_items = data_sources.setdefault(signal.source, [])
                    existing = next((row for row in source_items if str(
                        row.get("bvid") or row.get("id") or row.get("item_id") or ""
                    ) == signal.item_id), None)
                    if existing is not None:
                        existing["occurred_at"] = signal.occurred_at
                        existing["strength"] = signal.strength
                        existing["tags"] = signal.tags or existing.get("tags", [])
                    else:
                        source_items.append(item)

        except Exception as e:
            logger.error(f"从数据库加载数据失败: {e}")

        return data_sources

    def _merge_and_deduplicate(self, data_sources: Dict[str, List[Dict]]) -> List[Dict]:
        """合并所有数据源并去重"""
        all_videos = []
        seen_bvids = set()

        # 按优先级顺序处理
        priority_order = ["favorites", "history", "watchlater", "cinema"]

        for source in priority_order:
            videos = data_sources.get(source, [])
            for video in videos:
                bvid = video.get("bvid", "")
                if bvid and bvid not in seen_bvids:
                    all_videos.append(video)
                    seen_bvids.add(bvid)

        return all_videos

    def _extract_tags_from_list(
        self,
        items: List[Dict],
        source: str,
    ) -> Dict[str, float]:
        """从列表中提取兴趣标签，按信号时间和强度加权。"""
        weighted_tags: Counter[str] = Counter()
        item_weights: list[float] = []

        for item in items:
            item_weight, _ = temporal_weight(source, item)
            item_weights.append(item_weight)
            # 标题关键词
            title = item.get("title", "")
            title_tags = self._extract_keywords_from_text(title)
            for tag in title_tags:
                weighted_tags[tag] += item_weight

            # 描述关键词
            desc = item.get("description", "")
            if desc:
                desc_tags = self._extract_keywords_from_text(desc)
                for tag in desc_tags[:5]:
                    weighted_tags[tag] += item_weight * 0.6

            # 分区名称
            tname = item.get("tname", "")
            if tname:
                weighted_tags[tname] += item_weight * 0.8

            # UP主领域（作为标签）
            owner_name = item.get("owner_name", "")
            if owner_name:
                weighted_tags[f"UP:{owner_name}"] += item_weight * 0.35

        total = sum(weighted_tags.values())

        if total == 0:
            return {}

        average_freshness = sum(item_weights) / max(1, len(item_weights))
        return {
            tag: round((count / total) * average_freshness, 6)
            for tag, count in weighted_tags.most_common(30)
        }

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        import re

        if not text:
            return []

        # 中文词
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', text)
        # 英文词
        english_words = re.findall(r'[A-Za-z]{3,}', text)

        # 停用词
        stopwords = {
            "视频", "这个", "什么", "怎么", "如何", "为什么", "可以", "需要", "应该",
            "一个", "一些", "还有", "或者", "但是", "因为", "所以", "然后", "之后",
            "看看", "推荐", "分享", "教程", "讲解", "介绍"
        }

        keywords = []
        for word in chinese_words + english_words:
            word = word.strip()
            word_lower = word.lower()
            if word and word not in stopwords and len(word) >= 2:
                # 过滤纯数字和太短的
                if not word.isdigit() and len(word) >= 2:
                    keywords.append(word)

        return keywords

    def _extract_bangumi_preferences(self, bangumi_list: List[Dict]) -> Dict[str, Any]:
        """提取番剧偏好"""
        if not bangumi_list:
            return {"list": [], "types": {}, "genres": [], "tags": {}}

        # 番剧类型映射
        type_map = {
            1: "番剧",
            2: "电影",
            3: "纪录片",
            4: "综艺",
            5: "电视剧"
        }

        # 提取类型
        types = Counter()
        tags = []
        genres = []

        for item in bangumi_list:
            # 类型
            bangumi_type = item.get("type", 1)
            type_name = type_map.get(bangumi_type, "其他")
            types[type_name] += 1

            # 标题关键词
            title = item.get("title", "")
            title_tags = self._extract_keywords_from_text(title)
            tags.extend(title_tags)

            # 尝试从标题提取题材
            genre_keywords = ["热血", "恋爱", "冒险", "科幻", "日常", "搞笑", "治愈",
                            "战斗", "奇幻", "校园", "百合", "机战", "运动", "音乐"]
            for kw in genre_keywords:
                if kw in title:
                    genres.append(kw)

        # 归一化类型分布
        total = sum(types.values())
        type_dist = {k: v / total for k, v in types.items()}

        # 归一化标签
        tag_counter = Counter(tags)
        tag_total = sum(tag_counter.values())
        normalized_tags = {k: v / tag_total * 0.7 for k, v in tag_counter.most_common(20)}

        return {
            "list": bangumi_list,
            "types": type_dist,
            "genres": list(set(genres)),
            "tags": normalized_tags
        }

    def _extract_cinema_preferences(self, cinema_list: List[Dict]) -> Dict[str, Any]:
        """提取影视偏好"""
        if not cinema_list:
            return {"list": [], "types": {}, "genres": [], "tags": {}}

        # 影视类型
        types = Counter()
        tags = []
        genres = []

        for item in cinema_list:
            # 类型
            media_type = item.get("media_type", "other")
            types[media_type] += 1

            # 标题关键词
            title = item.get("title", "")
            title_tags = self._extract_keywords_from_text(title)
            tags.extend(title_tags)

            # 题材关键词
            genre_keywords = ["动作", "喜剧", "剧情", "科幻", "悬疑", "恐怖", "动画",
                            "战争", "犯罪", "爱情", "惊悚", "冒险", "奇幻"]
            for kw in genre_keywords:
                if kw in title:
                    genres.append(kw)

        # 归一化
        total = sum(types.values())
        type_dist = {k: v / total for k, v in types.items()}

        tag_counter = Counter(tags)
        tag_total = sum(tag_counter.values())
        normalized_tags = {k: v / tag_total * 0.7 for k, v in tag_counter.most_common(20)}

        return {
            "list": cinema_list,
            "types": type_dist,
            "genres": list(set(genres)),
            "tags": normalized_tags
        }

    def _merge_tags_with_weights(
        self,
        tag_sources: Dict[str, Dict[str, float]]
    ) -> Dict[str, float]:
        """合并多来源标签（带权重）"""
        merged = {}

        for source, tags in tag_sources.items():
            # Source policy has already been applied per item. Ontology scores
            # are canonical confidence values and receive a small precision
            # bonus without overwhelming direct evidence.
            weight = 1.05 if source == "ontology" else 1.0
            for tag, score in tags.items():
                if tag in merged:
                    merged[tag] = min(1.0, merged[tag] + score * weight * 0.5)
                else:
                    merged[tag] = min(1.0, score * weight)

        # 按分数排序并取前20
        sorted_tags = dict(
            sorted(merged.items(), key=lambda x: x[1], reverse=True)[:20]
        )

        return sorted_tags

    def _extract_followed_ups(self, videos: List[Dict], followings: List[Dict] = None) -> List[Dict[str, Any]]:
        """提取关注的 UP 主"""
        # 如果有真正的关注列表，优先使用
        if followings and len(followings) > 0:
            logger.info(f"使用真实关注列表: {len(followings)} 个UP主")
            return [
                {
                    "mid": up.get("mid", 0),
                    "name": up.get("name", ""),
                    "face": up.get("face", ""),
                    "sign": up.get("sign", ""),
                    "count": 0,  # 关注列表没有出现次数
                    "score": float(up.get("profile_score", 0.55)),
                    "source": up.get("following_source", "following")
                }
                for up in followings
            ]

        # 回退到从视频中提取（旧逻辑）
        up_counter = Counter()
        up_source = {}

        for video in videos:
            owner_name = video.get("owner_name", "")
            owner_mid = video.get("owner_mid")
            source = video.get("source", "")

            if owner_name and owner_mid:
                key = (owner_mid, owner_name)
                up_counter[key] += 1
                if key not in up_source:
                    up_source[key] = source

        total = len(videos) if videos else 1

        followed_ups = [
            {
                "mid": mid,
                "name": name,
                "count": count,
                "score": count / total,
                "source": up_source.get((mid, name), "mixed")
            }
            for (mid, name), count in up_counter.most_common()  # 移除数量限制，返回所有UP主
        ]

        return followed_ups

    def _analyze_category_distribution(self, videos: List[Dict]) -> Dict[str, float]:
        """分析分区分布"""
        # 分区映射
        category_mapping = {
            "动画": "动画", "动画情报": "动画", "完结动画": "动画",
            "连载动画": "动画", "MAD·AMV": "二次元", "MMD·3D": "二次元",
            "特摄": "特摄", "COSPLAY": "二次元",
            "游戏": "游戏", "单机游戏": "游戏", "网络游戏": "游戏",
            "手机游戏": "游戏", "电子竞技": "游戏", "桌游GMAT": "游戏",
            "音游": "游戏", "游戏视频": "游戏",
            "科技": "科技", "知识": "知识", "社科": "知识", "人文": "知识",
            "历史": "知识", "校园": "知识", "职场": "知识",
            "汽车": "科技", "数码": "科技", "生活": "生活", "日常": "生活",
            "美食": "生活", "动物圈": "生活", "手工": "生活", "绘画": "生活",
            "音乐": "音乐", "翻唱": "音乐", "演奏": "音乐", "VOCALOID": "音乐",
            "电音": "音乐", "MV": "音乐", "乐评": "音乐",
            "影视": "影视", "影视杂谈": "影视", "短片": "影视", "预告": "影视",
            "电影": "影视", "电视剧": "影视", "综艺": "影视",
            "纪录片": "纪录片",
            "娱乐": "娱乐", "八卦": "娱乐", "明星": "娱乐",
            "体育": "体育", "篮球": "体育", "足球": "体育", "健身": "体育",
            "资讯": "资讯", "热点": "资讯"
        }

        categories = []

        for video in videos:
            tname = video.get("tname", "")
            if tname:
                category = category_mapping.get(tname, "其他")
                categories.append(category)

        if not categories:
            return {"其他": 1.0}

        counter = Counter(categories)
        total = sum(counter.values())

        return {
            cat: count / total
            for cat, count in counter.most_common()
        }

    def _get_category_from_tags(self, tags: Dict[str, float]) -> Dict[str, float]:
        """从标签中推断分区"""
        category_keywords = {
            "教程": "教程", "编程": "科技", "代码": "科技", "开发": "科技",
            "Python": "科技", "Java": "科技", "AI": "科技", "机器学习": "科技",
            "游戏": "游戏", "原神": "游戏", "王者荣耀": "游戏",
            "美食": "生活", "做菜": "生活", "烹饪": "生活",
            "音乐": "音乐", "歌曲": "音乐", "翻唱": "音乐",
            "番剧": "动画", "动漫": "动画",
        }

        inferred = Counter()
        for tag in tags.keys():
            for kw, cat in category_keywords.items():
                if kw in tag:
                    inferred[cat] += tags.get(tag, 0)

        if not inferred:
            return {}

        total = sum(inferred.values())
        return {cat: count / total for cat, count in inferred.most_common()}

    def _get_top_interests(self, unified_tags: Dict[str, float], top_n: int = 10) -> List[str]:
        """获取主要兴趣列表"""
        sorted_tags = sorted(unified_tags.items(), key=lambda x: x[1], reverse=True)
        return [tag for tag, score in sorted_tags[:top_n]]

    def _calculate_type_ratio(self, videos: List[Dict], expected_type: str) -> float:
        """计算内容类型占比"""
        if not videos:
            return 0.0

        type_videos = [v for v in videos if v.get("source") == expected_type]
        return len(type_videos) / len(videos)

    def _calculate_confidence(self, data_sources: Dict[str, List]) -> float:
        """计算画像置信度"""
        # 统计有效数据源数量
        active_sources = sum(1 for v in data_sources.values() if len(v) > 0)
        source_score = min(active_sources / 8, 1.0) * 0.3

        # 统计总数据量
        total_items = sum(len(v) for v in data_sources.values())
        volume_score = min(total_items / 100, 1.0) * 0.4

        # 收藏夹数据占比（最重要）
        favorites_count = len(data_sources.get("favorites", []))
        favorites_score = min(favorites_count / 20, 1.0) * 0.3

        confidence = source_score + volume_score + favorites_score
        return min(confidence, 0.98)

    async def _save_collected_data(
        self,
        session_id: str,
        data_sources: Dict[str, List[Dict]],
        channel_sync_statuses: Dict[str, Dict[str, Any]] | None = None,
    ):
        """保存采集的数据到数据库"""
        try:
            async with async_session_factory() as db:
                sync_runs = {}
                if settings.v2_feature_flags(session_id)["profile_sync_v2"]:
                    for source, status in (channel_sync_statuses or {}).items():
                        sync_runs[source] = await begin_sync_run(
                            db,
                            session_id=session_id,
                            channel=source,
                            request_key=(
                                f"profile-build:{status.get('request_key') or datetime.utcnow().isoformat()}"
                            ),
                            cursor=status.get("cursor") or {},
                        )
                # 保存追番（去重）
                seen_bangumi = set()
                for item in data_sources.get("bangumi", []):
                    season_id = item.get("season_id", 0)
                    if not season_id:
                        continue

                    # 跳过同一批次中的重复数据
                    key = (session_id, season_id)
                    if key in seen_bangumi:
                        continue
                    seen_bangumi.add(key)

                    from app.models import UserBangumi
                    from sqlalchemy import select as sa_select

                    result = await db.execute(
                        sa_select(UserBangumi).where(
                            and_(
                                UserBangumi.session_id == session_id,
                                UserBangumi.season_id == season_id
                            )
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if existing:
                        existing.title = item.get("title", "")
                        existing.cover = item.get("cover", "")
                        existing.bangumi_type = item.get("type", 1)
                        existing.status = item.get("status", "watching")
                        existing.watched_episodes = item.get("progress", {}).get("watched_episodes", 0)
                        existing.total_episodes = item.get("progress", {}).get("total_episodes", 0)
                        existing.add_time = parse_datetime(item.get("add_time")) or existing.add_time
                    else:
                        new_bangumi = UserBangumi(
                            session_id=session_id,
                            season_id=season_id,
                            media_id=item.get("media_id", season_id),
                            title=item.get("title", ""),
                            cover=item.get("cover", ""),
                            bangumi_type=item.get("type", 1),
                            status=item.get("status", "watching"),
                            watched_episodes=item.get("progress", {}).get("watched_episodes", 0),
                            total_episodes=item.get("progress", {}).get("total_episodes", 0),
                            add_time=parse_datetime(item.get("add_time")),
                        )
                        db.add(new_bangumi)

                # 保存历史记录
                for item in data_sources.get("history", []):
                    bvid = item.get("bvid", "")
                    view_at = item.get("view_at", 0)
                    if not bvid or not view_at:
                        continue

                    from app.models import UserWatchHistory
                    from sqlalchemy import select as sa_select

                    result = await db.execute(
                        sa_select(UserWatchHistory).where(
                            and_(
                                UserWatchHistory.session_id == session_id,
                                UserWatchHistory.bvid == bvid,
                                UserWatchHistory.view_at == view_at
                            )
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if not existing:
                        new_history = UserWatchHistory(
                            session_id=session_id,
                            bvid=bvid,
                            aid=item.get("aid", 0),
                            title=item.get("title", ""),
                            cover=item.get("cover", ""),
                            owner_mid=item.get("owner_mid"),
                            owner_name=item.get("owner_name", ""),
                            duration=item.get("duration", 0),
                            progress=item.get("progress", 0),
                            view_at=view_at,
                            tname=item.get("tname", "")
                        )
                        db.add(new_history)

                # 保存稍后观看
                for item in data_sources.get("watchlater", []):
                    bvid = item.get("bvid", "")
                    if not bvid:
                        continue

                    from app.models import UserWatchLater
                    from sqlalchemy import select as sa_select

                    result = await db.execute(
                        sa_select(UserWatchLater).where(
                            and_(
                                UserWatchLater.session_id == session_id,
                                UserWatchLater.bvid == bvid
                            )
                        )
                    )
                    existing = result.scalar_one_or_none()

                    if not existing:
                        new_watchlater = UserWatchLater(
                            session_id=session_id,
                            bvid=bvid,
                            aid=item.get("aid", 0),
                            title=item.get("title", ""),
                            cover=item.get("cover", ""),
                            owner_mid=item.get("owner_mid"),
                            owner_name=item.get("owner_name", ""),
                            duration=item.get("duration", 0),
                            add_time=item.get("add_time", 0),
                            status="pending"
                        )
                        db.add(new_watchlater)

                # Persist all current and future channels in one normalized
                # signal table so profile algorithms do not need a new schema
                # for every Bilibili surface.
                for source, items in data_sources.items():
                    if not isinstance(items, list):
                        continue
                    for index, item in enumerate(items):
                        if not isinstance(item, dict):
                            continue
                        item_id = (
                            item.get("bvid") or item.get("season_id") or item.get("media_id")
                            or item.get("id") or item.get("item_id") or item.get("mid")
                            or item.get("tag_id") or f"{source}-{index}"
                        )
                        item_type = item.get("item_type") or (
                            "video" if item.get("bvid") else
                            "creator" if item.get("mid") or item.get("owner_mid") else
                            "content"
                        )
                        repeated = source in {"history", "live_history"}
                        await upsert_user_content_signal(
                            db,
                            session_id=session_id,
                            source=source,
                            item_type=item_type,
                            item_id=str(item_id),
                            title=item.get("title") or item.get("name") or item.get("room_title"),
                            description=item.get("description") or item.get("desc") or item.get("sign"),
                            creator_mid=item.get("owner_mid") or item.get("mid"),
                            creator_name=item.get("owner_name") or item.get("uname") or item.get("author"),
                            category=item.get("tname") or item.get("category"),
                            tags=item.get("tags") if isinstance(item.get("tags"), list) else [],
                            strength=item.get("strength", 1.0),
                            occurred_at=item_occurred_at(item),
                            payload={
                                key: value for key, value in item.items()
                                if key not in {"description", "content", "subtitle"}
                            },
                            repeated=repeated,
                            sync_run_id=(
                                sync_runs[source].run_id if source in sync_runs else None
                            ),
                        )

                for source, run in sync_runs.items():
                    status = (channel_sync_statuses or {}).get(source, {})
                    if status.get("status") == "success":
                        await complete_sync_run(
                            db,
                            run,
                            item_count=int(status.get("count") or len(data_sources.get(source, []))),
                            page_count=int(status.get("page_count") or 0),
                            cursor=status.get("cursor") or {},
                            full_snapshot=bool(status.get("full_snapshot")),
                            http_status=status.get("http_status", 200),
                        )
                    else:
                        await fail_sync_run(
                            db,
                            run,
                            status=str(status.get("status") or "failed"),
                            capability_status=str(
                                status.get("capability_status") or "degraded"
                            ),
                            error_summary=str(
                                status.get("error_summary") or "channel collection failed"
                            ),
                            http_status=status.get("http_status"),
                            cursor=status.get("cursor") or {},
                        )

                await db.commit()
                logger.info(f"采集数据已保存到数据库: {session_id}")

        except Exception as e:
            logger.error(f"保存采集数据失败: {e}")

    async def _save_profile(self, profile: Dict[str, Any]):
        """保存画像到数据库"""
        try:
            async with async_session_factory() as db:
                from sqlalchemy import select as sa_select

                result = await db.execute(
                    sa_select(UserInterestProfile).where(
                        UserInterestProfile.session_id == profile["session_id"]
                    )
                )
                existing = result.scalar_one_or_none()

                if existing:
                    # 更新
                    await db.execute(
                        update(UserInterestProfile)
                        .where(UserInterestProfile.session_id == profile["session_id"])
                        .values(
                            interest_tags=profile.get("unified_tags", {}),
                            followed_ups=profile.get("followed_ups", []),
                            category_distribution=profile.get("category_distribution", {}),
                            total_favorites=profile.get("total_analyzed", 0),
                            recent_interest_shift=profile.get("recent_interests", {}),
                            profile_features=profile.get("profile_features", {}),
                            confidence_score=profile.get("confidence_score", 0.5),
                            last_update_source=profile.get("last_update_source", "multi_source_sync"),
                            updated_at=datetime.utcnow()
                        )
                    )
                else:
                    from app.models import UserInterestProfile as UIPModel
                    new_profile = UIPModel(
                        session_id=profile["session_id"],
                        interest_tags=profile.get("unified_tags", {}),
                        followed_ups=profile.get("followed_ups", []),
                        category_distribution=profile.get("category_distribution", {}),
                        total_favorites=profile.get("total_analyzed", 0),
                        recent_interest_shift=profile.get("recent_interests", {}),
                        profile_features=profile.get("profile_features", {}),
                        confidence_score=profile.get("confidence_score", 0.5),
                        last_update_source=profile.get("last_update_source", "multi_source_sync")
                    )
                    db.add(new_profile)

                await db.commit()
                logger.info(f"画像已保存: {profile['session_id']}")

        except Exception as e:
            logger.error(f"保存画像失败: {e}")

    async def _vectorize_and_store_profile(self, profile: Dict[str, Any]):
        """向量化画像并存储"""
        try:
            from app.config import settings
            from langchain_chroma import Chroma
            from langchain_core.documents import Document

            def _get_embeddings():
                try:
                    from langchain_community.embeddings import DashScopeEmbeddings
                    return DashScopeEmbeddings(
                        dashscope_api_key=settings.openai_api_key,
                        model=settings.embedding_model
                    )
                except Exception:
                    from langchain_openai import OpenAIEmbeddings
                    return OpenAIEmbeddings(
                        api_key=settings.openai_api_key,
                        base_url=settings.openai_base_url,
                        model=settings.embedding_model
                    )

            profile_text = self._profile_to_text(profile)
            if not profile_text or len(profile_text.strip()) < 10:
                logger.warning("画像文本为空，跳过向量化")
                return

            embeddings = _get_embeddings()
            vectorstore = Chroma(
                collection_name="user_profiles",
                embedding_function=embeddings,
                persist_directory=str(settings.chroma_dir)
            )

            doc = Document(
                page_content=profile_text,
                metadata={
                    "session_id": profile.get("session_id", ""),
                    "type": "multi_source_profile",
                    "confidence": profile.get("confidence_score", 0.0),
                    "data_sources": json.dumps(
                        profile.get("data_sources", []), ensure_ascii=False
                    ),
                    "updated_at": datetime.utcnow().isoformat()
                }
            )

            vectorstore.add_documents([doc])
            logger.info(f"画像已向量化: {profile.get('session_id')}")

        except Exception as e:
            logger.error(f"画像向量化失败: {e}")

    def _profile_to_text(self, profile: Dict[str, Any]) -> str:
        """将画像转换为文本描述"""
        parts = []

        # 统一兴趣标签
        unified_tags = profile.get("unified_tags", {})
        if unified_tags:
            top_interests = sorted(unified_tags.items(), key=lambda x: x[1], reverse=True)[:10]
            parts.append(f"综合兴趣: {', '.join([f'{t}({s:.2f})' for t, s in top_interests])}")

        features = profile.get("profile_features") or {}
        multi_interests = features.get("multi_interests") or []
        if multi_interests:
            parts.append("语义兴趣簇: " + ", ".join(
                f"{cluster.get('label')}({float(cluster.get('weight', 0)):.2f})"
                for cluster in multi_interests[:6]
                if cluster.get("label")
            ))

        # 关注的UP主
        followed_ups = profile.get("followed_ups", [])
        if followed_ups:
            up_names = [u.get("name", "未知") for u in followed_ups[:5] if u.get("name")]
            parts.append(f"关注UP主: {', '.join(up_names)}")

        # 分区分布
        cat_dist = profile.get("category_distribution", {})
        if cat_dist:
            parts.append(f"内容分区: {', '.join([f'{c}({s:.0%})' for c, s in cat_dist.items()])}")

        # 番剧偏好
        bangumi_types = profile.get("bangumi_types", {})
        if bangumi_types:
            parts.append(f"番剧类型: {', '.join([f'{t}({s:.0%})' for t, s in bangumi_types.items()])}")

        # 影视偏好
        cinema_types = profile.get("cinema_types", {})
        if cinema_types:
            parts.append(f"影视类型: {', '.join([f'{t}({s:.0%})' for t, s in cinema_types.items()])}")

        # 内容类型偏好
        content_pref = profile.get("content_type_preference", {})
        if content_pref:
            parts.append(f"内容形态: 视频{int(content_pref.get('video', 0)*100)}%, 番剧{int(content_pref.get('bangumi', 0)*100)}%, 影视{int(content_pref.get('cinema', 0)*100)}%")

        return " | ".join(parts)

    async def _generate_profile_summary(self, profile: Dict[str, Any]) -> str:
        """生成用户画像的毒舌总结"""
        try:
            from openai import AsyncOpenAI
            from app.config import settings

            # 构建提示词
            prompt = f"""你是一个毒舌的B站用户分析师，请根据以下用户数据，用幽默毒舌的风格总结这个用户的特点（150字以内）：

关注UP主数量: {len(profile.get('followed_ups', []))}
分析的视频总数: {profile.get('total_analyzed', 0)}
主要兴趣标签: {', '.join(profile.get('primary_interests', [])[:5])}
收藏分区: {', '.join(list(profile.get('favorite_categories', {}).keys())[:3]) if profile.get('favorite_categories') else '暂无'}

请用幽默毒舌的风格总结（可以适当调侃，但要有依据）：
"""

            client = AsyncOpenAI(
                api_key=settings.dashscope_api_key,
                base_url=settings.dashscope_base_url.replace("/api/v1", "/compatible-mode/v1")
            )

            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": "你是一个毒舌的B站用户分析师，说话有趣但有依据。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=100,  # 限制在50字左右
                temperature=0.8
            )

            summary = response.choices[0].message.content.strip()
            await client.close()
            return summary

        except Exception as e:
            logger.warning(f"生成画像总结失败: {e}")
            return self._generate_simple_summary(profile)

    def _generate_simple_summary(self, profile: Dict[str, Any]) -> str:
        """生成简单的画像总结（当LLM调用失败时）"""
        tags = profile.get("primary_interests", [])[:5]
        up_count = len(profile.get("followed_ups", []))
        total = profile.get("total_analyzed", 0)

        tag_str = "、".join(tags) if tags else "啥都看点"
        return f"这个用户关注了{up_count}个UP主，分析了{total}个视频，兴趣标签主要是{tag_str}。{up_count}个关注里肯定有一半是僵尸关注，谁不是呢？"

    async def _load_from_long_term_memory(self, session_id: str) -> Optional[Dict[str, Any]]:
        """从长期记忆加载最新的画像"""
        try:
            async with async_session_factory() as db:
                from sqlalchemy import select
                result = await db.execute(
                    select(LongTermMemory)
                    .where(LongTermMemory.session_id == session_id)
                    .where(LongTermMemory.memory_type == "user_profile")
                    .order_by(LongTermMemory.created_at.desc())
                )
                memory = result.scalars().first()

                if memory and memory.extra_data:
                    # 从 extra_data 中重建画像
                    extra = memory.extra_data
                    profile = {
                        "session_id": session_id,
                        "confidence_score": extra.get("confidence_score", 0.0),
                        "data_sources": extra.get("data_sources", []),
                        "unified_tags": extra.get("unified_tags", {}),
                        "primary_interests": list(extra.get("unified_tags", {}).keys())[:10],
                        "followed_ups": [],  # 长期记忆不保存完整UP主列表
                        "total_analyzed": 0,
                        "summary": extra.get("profile_summary", ""),
                        "category_distribution": {}
                    }
                    return profile

                return None

        except Exception as e:
            logger.error(f"从长期记忆加载失败: {e}")
            return None

    async def _save_to_long_term_memory(self, profile: Dict[str, Any]):
        """保存到长期记忆"""
        try:
            async with async_session_factory() as db:
                # 构建记忆内容
                memory_content = self._profile_to_text(profile)

                new_memory = LongTermMemory(
                    session_id=profile["session_id"],
                    content=memory_content,
                    memory_type="user_profile",
                    importance=5,
                    tags=profile.get("primary_interests", []),
                    extra_data={
                        "confidence_score": profile.get("confidence_score", 0.0),
                        "data_sources": profile.get("data_sources", []),
                        "unified_tags": profile.get("unified_tags", {}),
                        "profile_summary": profile.get("summary", "")  # 保存毒舌总结
                    }
                )
                db.add(new_memory)
                await db.commit()

                logger.info(f"画像已保存到长期记忆: {profile['session_id']}")

        except Exception as e:
            logger.error(f"保存到长期记忆失败: {e}")

    def _get_empty_profile(self, session_id: str) -> Dict[str, Any]:
        """返回空画像"""
        return {
            "session_id": session_id,
            "unified_tags": {},
            "recent_interests": {},
            "profile_features": {
                "model": "temporal-multi-interest-ontology-v1",
                "ontology_version": get_ontology_service().VERSION,
                "concept_affinities": {},
                "recent_concept_affinities": {},
                "multi_interests": [],
                "source_freshness": {},
                "interest_evidence": [],
            },
            "primary_interests": [],
            "followed_ups": [],
            "category_distribution": {},
            "bangumi_following": [],
            "bangumi_types": {},
            "bangumi_genres": [],
            "cinema_favorites": [],
            "cinema_types": {},
            "cinema_genres": [],
            "content_type_preference": {"video": 1.0, "bangumi": 0.0, "cinema": 0.0},
            "visual_style_preference": {},
            "total_analyzed": 0,
            "data_sources": [],
            "confidence_score": 0.0,
            "last_update_source": "empty",
            "updated_at": datetime.utcnow()
        }

    async def _analyze_cover_styles(
        self,
        videos: List[Dict[str, Any]],
        session_id: str
    ) -> Dict[str, float]:
        """
        分析视频封面风格，提取视觉偏好

        Args:
            videos: 视频列表
            session_id: 会话ID

        Returns:
            视觉风格偏好字典，如 {"教程": 0.7, "高质量": 0.8}
        """
        if not videos:
            return {}

        from collections import Counter
        visual_tags_counter = Counter()
        quality_scores = []
        style_categories = Counter()

        # 最多分析前10个视频的封面（避免耗时太长）
        for video in videos[:10]:
            bvid = video.get("bvid", "")
            # 兼容不同的字段名：pic_url（数据库）或 cover（API）
            pic_url = video.get("pic_url") or video.get("cover", "")
            title = video.get("title", "")

            if not bvid or not pic_url:
                continue

            try:
                # 调用封面分析器
                analysis = await self.cover_analyzer.analyze_cover(
                    bvid=bvid,
                    pic_url=pic_url,
                    title=title,
                    force_reanalyze=False  # 使用缓存结果
                )

                # 统计视觉标签
                for tag in analysis.get("visual_tags", []):
                    visual_tags_counter[tag] += 1

                # 统计质量分数
                quality_score = analysis.get("quality_score", 0.5)
                quality_scores.append(quality_score)

                # 统计风格分类
                style_category = analysis.get("style_category", "unknown")
                style_categories[style_category] += 1

            except Exception as e:
                logger.warning(f"封面分析失败 {bvid}: {e}")
                continue

        # 计算视觉偏好
        visual_preference = {}

        # 1. 视觉标签偏好（归一化）
        if visual_tags_counter:
            total_tags = sum(visual_tags_counter.values())
            visual_preference.update({
                f"tag_{tag}": count / total_tags
                for tag, count in visual_tags_counter.most_common(10)
            })

        # 2. 平均质量分数
        if quality_scores:
            avg_quality = sum(quality_scores) / len(quality_scores)
            visual_preference["avg_quality"] = avg_quality

        # 3. 风格分类偏好
        if style_categories:
            total_styles = sum(style_categories.values())
            visual_preference.update({
                f"style_{style}": count / total_styles
                for style, count in style_categories.items()
            })

        logger.info(f"封面分析完成: 分析了{len(quality_scores)}个封面, "
                    f"风格偏好: {dict(style_categories.most_common(3))}")

        return visual_preference


# 单例
_profile_builder: Optional['MultiSourceProfileBuilder'] = None


def get_multi_source_profile_builder() -> MultiSourceProfileBuilder:
    """获取多数据源画像构建器单例"""
    global _profile_builder
    if _profile_builder is None:
        _profile_builder = MultiSourceProfileBuilder()
    return _profile_builder
