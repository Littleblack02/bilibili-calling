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
from datetime import datetime, timedelta
import asyncio
import re

from app.services.bilibili import BilibiliService
from app.services.profile.profile_builder import get_profile_builder
from app.database import async_session_factory


def clean_bilibili_title(title: str) -> str:
    """去除B站返回的HTML高亮标签（如 <em class="keyword">）"""
    if not title:
        return ""
    # 移除所有 HTML 标签
    cleaned = re.sub(r'<[^>]+>', '', title)
    # 清理多余的空白字符
    cleaned = ' '.join(cleaned.split())
    return cleaned.strip()


class CandidateRecall:
    """候选召回服务"""

    def __init__(self):
        self.profile_builder = get_profile_builder()

    async def recall_candidates(
        self,
        session_id: str,
        limit_per_channel: int = 20,
        cookies: Dict[str, str] = None
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
        profile = await self._get_user_profile(session_id)

        # 2. 多路召回（统一使用一个 BilibiliService 实例，传入 cookies）
        candidates = []

        bili = BilibiliService(
            sessdata=cookies.get("SESSDATA") if cookies else None,
            bili_jct=cookies.get("bili_jct") if cookies else None,
            dedeuserid=cookies.get("DedeUserID") if cookies else None
        )

        async with bili:
            # 召回路1：兴趣召回
            interest_candidates = await self._recall_by_interest(bili, profile, limit_per_channel)
            candidates.extend(interest_candidates)
            await asyncio.sleep(0.3)  # 避免请求过快

            # 召回路2：分区召回
            category_candidates = await self._recall_by_category(bili, profile, limit_per_channel)
            candidates.extend(category_candidates)
            await asyncio.sleep(0.3)

            # 召回路3：热榜召回
            trending_candidates = await self._recall_by_trending(bili, limit_per_channel)
            candidates.extend(trending_candidates)
            await asyncio.sleep(0.3)

            # 召回路4：UP主召回
            up_candidates = await self._recall_by_followed_ups(bili, profile, limit_per_channel)
            candidates.extend(up_candidates)

        # 3. 去重
        deduplicated = self._deduplicate_candidates(candidates)

        # 4. 添加召回源标记
        for candidate in deduplicated:
            candidate["recall_source"] = candidate.get("recall_source", "unknown")

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
                            "duration": item.get("duration", 0),
                            "pic_url": item.get("pic", ""),
                            "pubdate": datetime.fromtimestamp(item.get("pubdate", 0)) if item.get("pubdate") else None,
                            "recall_source": "interest",
                            "recall_tag": tag
                        })

            except Exception as e:
                logger.error(f"兴趣召回失败: {tag}, 错误: {e}")

        return candidates

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
                            "duration": video.get("duration", 0),
                            "pic_url": "",
                            "pubdate": None,
                            "recall_source": "category",
                            "recall_category": category
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
                        "duration": video.get("duration", 0),
                        "pic_url": "",
                        "pubdate": None,
                        "recall_source": "trending"
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

        # 取关注最多的 5 个 UP 主
        top_ups = sorted(followed_ups, key=lambda x: x.get("score", 0), reverse=True)[:5]
        candidates = []

        for up in top_ups:
            mid = up.get("mid", 0)
            name = up.get("name", "")

            if not mid or not name:
                continue

            try:
                result = await bili.search_bilibili(
                    keyword=name,
                    search_type="video",
                    order="pubdate",
                    page=1
                )

                if result.get("success") and result.get("items"):
                    up_videos = [
                        item for item in result["items"]
                        if item.get("mid") == mid
                    ]

                    for video in up_videos[:limit // len(top_ups)]:
                        candidates.append({
                            "bvid": video.get("bvid", ""),
                            "title": clean_bilibili_title(video.get("title", "")),
                            "author": name,
                            "mid": mid,
                            "play": video.get("play", 0),
                            "duration": video.get("duration", 0),
                            "pic_url": video.get("pic", ""),
                            "pubdate": datetime.fromtimestamp(video.get("pubdate", 0)) if video.get("pubdate") else None,
                            "recall_source": "followed_up",
                            "recall_up_name": name
                        })

            except Exception as e:
                logger.error(f"UP主召回失败: {name}, 错误: {e}")

        return candidates

    def _deduplicate_candidates(
        self,
        candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """去重候选视频，并限制每个画像维度最多2条"""
        seen_bvids = set()
        deduplicated = []

        # 按画像维度统计数量
        tag_counts = {}
        category_counts = {}
        up_counts = {}
        trending_count = 0

        for candidate in candidates:
            bvid = candidate.get("bvid", "")
            if not bvid or bvid in seen_bvids:
                continue

            recall_source = candidate.get("recall_source", "unknown")

            # 细分维度限制：每个画像维度最多 2 条
            if recall_source == "interest":
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

            seen_bvids.add(bvid)
            deduplicated.append(candidate)

        return deduplicated


# 单例
_candidate_recall: Optional[CandidateRecall] = None


def get_candidate_recall() -> CandidateRecall:
    """获取候选召回服务单例"""
    global _candidate_recall
    if _candidate_recall is None:
        _candidate_recall = CandidateRecall()
    return _candidate_recall
