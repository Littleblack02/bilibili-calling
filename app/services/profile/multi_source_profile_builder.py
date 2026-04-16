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
    LongTermMemory
)
from app.services.gemma.cover_analyzer import get_cover_analyzer
from app.services.bilibili import BilibiliService


class MultiSourceProfileBuilder:
    """多数据源用户画像构建器"""

    # 每通道采集数量限制
    MAX_FAVORITES = 10      # 收藏夹每个取10个
    MAX_HISTORY = 10        # 历史记录取10条
    MAX_WATCHLATER = 10     # 稍后观看取10个
    MAX_CINEMA = 10         # 影视收藏取10个

    # 兴趣标签权重（用于综合评分）
    SOURCE_WEIGHTS = {
        "favorites": 1.0,     # 收藏夹权重最高
        "history": 0.8,       # 历史记录
        "watchlater": 0.6,    # 稍后观看
        "bangumi": 0.7,       # 追番
        "cinema": 0.7,        # 影视收藏
    }

    def __init__(self):
        self.cover_analyzer = get_cover_analyzer()
        self.enable_cover_analysis = True  # 启用封面分析

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
        logger.info(f"开始构建多数据源用户画像: {session_id}")

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
            has_data = any(len(data_sources.get(k, [])) > 0 for k in ["favorites", "bangumi", "history", "watchlater"])
            if not has_data:
                logger.info(f"数据库中没有已有数据，开始采集: {session_id}")
            else:
                # 数据库有数据时，仍然尝试获取关注列表（因为关注列表不保存在视频数据库中）
                try:
                    async with bilibili:
                        user_info = await bilibili.get_user_info()
                        mid = user_info.get("mid", 0) if user_info else 0
                        if mid:
                            followings = await self._collect_followings(bilibili, mid)
                            data_sources["followings"] = followings
                            logger.info(f"从API获取关注列表: {len(followings)} 个UP主")
                except Exception as e:
                    logger.warning(f"获取关注列表失败: {e}")
        else:
            data_sources = {}

        if force_rebuild or not any(len(data_sources.get(k, [])) > 0 for k in ["favorites", "bangumi", "history", "watchlater"]):
            try:
                async with bilibili:
                    # 并行采集所有数据源
                    data_sources = await self._collect_all_sources(bilibili, session_id)
            except Exception as e:
                logger.error(f"采集数据源失败: {e}")
                # 如果采集失败，尝试从数据库读取已有数据
                data_sources = await self._load_from_database(session_id)

        if not data_sources or not any(len(data_sources.get(k, [])) > 0 for k in ["favorites", "bangumi", "history", "watchlater"]):
            logger.warning(f"没有采集到任何数据: {session_id}")
            return self._get_empty_profile(session_id)

        # 2. 保存采集的数据到数据库
        await self._save_collected_data(session_id, data_sources)

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
            weight=self.SOURCE_WEIGHTS["favorites"]
        )
        recent_tags = self._extract_tags_from_list(
            data_sources.get("history", []),
            weight=self.SOURCE_WEIGHTS["history"]
        )
        watchlater_tags = self._extract_tags_from_list(
            data_sources.get("watchlater", []),
            weight=self.SOURCE_WEIGHTS["watchlater"]
        )

        # 5. 提取番剧偏好
        bangumi_prefs = self._extract_bangumi_preferences(data_sources.get("bangumi", []))

        # 6. 提取影视偏好
        cinema_prefs = self._extract_cinema_preferences(data_sources.get("cinema", []))

        # 7. 统一兴趣标签（加权合并）
        unified_tags = self._merge_tags_with_weights({
            "favorites": favorite_tags,
            "history": recent_tags,
            "watchlater": watchlater_tags,
            "bangumi": bangumi_prefs.get("tags", {}),
            "cinema": cinema_prefs.get("tags", {}),
        })

        # 8. 提取关注的 UP 主（使用真实关注列表）
        followings_list = data_sources.get("followings", [])
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
            "primary_interests": self._get_top_interests(unified_tags, top_n=10),
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

        logger.info(f"多数据源画像构建完成: {session_id}, 数据源: {profile['data_sources']}")
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

        # 并行执行
        results = await asyncio.gather(*tasks, return_exceptions=True)

        data_sources = {}
        source_names = ["favorites", "bangumi", "history", "watchlater", "followings"]

        for i, result in enumerate(results):
            source_name = source_names[i]
            if isinstance(result, Exception):
                logger.warning(f"采集 {source_name} 失败: {result}")
                data_sources[source_name] = []
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
            # 只取前10个追番
            bangumi_list = bangumi_list[:10]

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
            } for item in watchlater[:self.MAX_WATCHLATER]]

        except Exception as e:
            logger.error(f"采集稍后观看失败: {e}")
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
            return []

    async def _load_from_database(self, session_id: str) -> Dict[str, List[Dict]]:
        """从数据库加载已有数据"""
        data_sources = {"favorites": [], "bangumi": [], "history": [], "watchlater": [], "followings": []}

        try:
            async with async_session_factory() as db:
                # 加载收藏夹
                result = await db.execute(
                    select(VideoCache, FavoriteFolder.title.label("folder_title"))
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
                        "source": "watchlater"
                    })

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
        weight: float = 1.0
    ) -> Dict[str, float]:
        """从视频列表中提取兴趣标签"""
        all_tags = []

        for item in items:
            # 标题关键词
            title = item.get("title", "")
            title_tags = self._extract_keywords_from_text(title)
            all_tags.extend(title_tags)

            # 描述关键词
            desc = item.get("description", "")
            if desc:
                desc_tags = self._extract_keywords_from_text(desc)
                all_tags.extend(desc_tags[:5])

            # 分区名称
            tname = item.get("tname", "")
            if tname:
                all_tags.append(tname)

            # UP主领域（作为标签）
            owner_name = item.get("owner_name", "")
            if owner_name:
                all_tags.append(f"UP:{owner_name}")

        # 统计频率并加权
        tag_counter = Counter(all_tags)
        total = sum(tag_counter.values())

        if total == 0:
            return {}

        return {
            tag: (count / total) * weight
            for tag, count in tag_counter.most_common(20)
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
            weight = self.SOURCE_WEIGHTS.get(source, 0.5)
            for tag, score in tags.items():
                if tag in merged:
                    merged[tag] = max(merged[tag], score * weight)
                else:
                    merged[tag] = score * weight

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
                    "score": 1.0,  # 所有关注的UP主都给予最高权重
                    "source": "following"
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
        source_score = min(active_sources / 5, 1.0) * 0.3

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
        data_sources: Dict[str, List[Dict]]
    ):
        """保存采集的数据到数据库"""
        try:
            async with async_session_factory() as db:
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
                            total_episodes=item.get("progress", {}).get("total_episodes", 0)
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
                    "data_sources": profile.get("data_sources", []),
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
