"""
兴趣更新器服务

职责：
- 根据用户新收藏/新对话更新画像
- 处理长期兴趣和短期兴趣的融合
- 输出结构化更新建议
"""
from typing import Dict, List, Any, Optional
from loguru import logger
from datetime import datetime, timedelta
from collections import Counter

from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import UserInterestProfile, LongTermMemory, GlobalKnowledge
from app.services.gemma.cover_analyzer import get_cover_analyzer


class InterestUpdater:
    """兴趣更新器"""

    def __init__(self):
        self.cover_analyzer = get_cover_analyzer()

    async def update_from_new_favorites(
        self,
        session_id: str,
        new_favorite_bvids: List[str]
    ) -> Dict[str, Any]:
        """
        根据新收藏更新画像

        Args:
            session_id: 用户会话 ID
            new_favorite_bvids: 新收藏的视频 BV 号列表

        Returns:
            更新结果
        """
        logger.info(f"从新收藏更新画像: {session_id}, 新收藏数: {len(new_favorite_bvids)}")

        # 1. 获取当前画像
        current_profile = await self._get_current_profile(session_id)

        # 2. 分析新收藏的封面
        new_favorites_analysis = await self._analyze_new_favorites(new_favorite_bvids)

        # 3. 提取新兴趣标签
        new_interests = self._extract_new_interests(new_favorites_analysis)

        # 4. 检测兴趣变化
        interest_shift = self._detect_interest_shift(current_profile, new_interests)

        # 5. 融合长期和短期兴趣
        updated_profile = await self._merge_interests(current_profile, new_interests, interest_shift)

        # 6. 保存更新
        await self._save_profile_update(session_id, updated_profile)

        return {
            "session_id": session_id,
            "new_interests": new_interests,
            "interest_shift": interest_shift,
            "updated_profile": updated_profile
        }

    async def update_from_conversation(
        self,
        session_id: str,
        conversation_summary: str,
        query_topics: List[str]
    ) -> Dict[str, Any]:
        """
        根据对话更新画像

        Args:
            session_id: 用户会话 ID
            conversation_summary: 对话摘要
            query_topics: 用户查询的主题列表

        Returns:
            更新结果
        """
        logger.info(f"从对话更新画像: {session_id}, 主题数: {len(query_topics)}")

        # 1. 获取当前画像
        current_profile = await self._get_current_profile(session_id)

        # 2. 分析对话主题
        short_term_focus = self._analyze_conversation_focus(query_topics)

        # 3. 检测短期兴趣变化
        focus_shift = self._detect_focus_shift(current_profile, short_term_focus)

        # 4. 更新短期兴趣字段
        updated_profile = await self._update_short_term_focus(current_profile, short_term_focus, focus_shift)

        # 5. 保存更新
        await self._save_profile_update(session_id, updated_profile)

        return {
            "session_id": session_id,
            "short_term_focus": short_term_focus,
            "focus_shift": focus_shift,
            "updated_profile": updated_profile
        }

    async def _get_current_profile(self, session_id: str) -> Dict[str, Any]:
        """获取当前画像"""
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
                    "total_favorites": profile.total_favorites or 0,
                    "visual_style_preference": profile.visual_style_preference or {},
                    "content_type_preference": profile.content_type_preference or {},
                    "recent_interest_shift": profile.recent_interest_shift,
                    "short_term_focus": profile.short_term_focus,
                    "confidence_score": profile.confidence_score or 0.5
                }
            else:
                # 返回空画像
                return {
                    "interest_tags": {},
                    "category_distribution": {},
                    "followed_ups": [],
                    "total_favorites": 0,
                    "visual_style_preference": {},
                    "content_type_preference": {},
                    "recent_interest_shift": None,
                    "short_term_focus": None,
                    "confidence_score": 0.0
                }

    async def _analyze_new_favorites(self, bvids: List[str]) -> List[Dict[str, Any]]:
        """分析新收藏的封面"""
        analyzed = []

        for bvid in bvids:
            try:
                # 从数据库获取视频信息
                from app.models import VideoCache

                async with async_session_factory() as db:
                    result = await db.execute(
                        select(VideoCache).where(VideoCache.bvid == bvid)
                    )
                    video = result.scalar_one_or_none()

                    if not video:
                        continue

                    # 分析封面
                    cover_analysis = await self.cover_analyzer.analyze_cover(
                        bvid=bvid,
                        pic_url=video.pic_url or "",
                        title=video.title,
                        force_reanalyze=False
                    )

                    analyzed.append({
                        "bvid": bvid,
                        "title": video.title,
                        "visual_tags": cover_analysis.get("visual_tags", []),
                        "style_category": cover_analysis.get("style_category", "unknown"),
                        "quality_score": cover_analysis.get("quality_score", 0.5)
                    })

            except Exception as e:
                logger.error(f"分析新收藏失败: {bvid}, 错误: {e}")

        return analyzed

    def _extract_new_interests(self, analyzed_favorites: List[Dict[str, Any]]) -> Dict[str, float]:
        """从新收藏中提取兴趣标签"""
        all_tags = []

        for fav in analyzed_favorites:
            # 标题关键词
            title_tags = self._extract_keywords_from_text(fav["title"])
            all_tags.extend(title_tags)

            # 视觉标签
            visual_tags = fav.get("visual_tags", [])
            all_tags.extend(visual_tags)

        # 统计频率
        tag_counter = Counter(all_tags)

        # 转换为权重
        total = sum(tag_counter.values())
        if total == 0:
            return {}

        return {
            tag: count / total
            for tag, count in tag_counter.most_common(10)
        }

    def _detect_interest_shift(
        self,
        current_profile: Dict[str, Any],
        new_interests: Dict[str, float]
    ) -> Optional[Dict[str, Any]]:
        """检测兴趣变化"""
        current_tags = current_profile.get("interest_tags", {})

        if not current_tags:
            return None

        # 找出变化最大的标签
        current_top = set(list(current_tags.keys())[:3])
        new_top = set(list(new_interests.keys())[:3])

        if current_top == new_top:
            return None

        # 检测到变化
        return {
            "from": ", ".join(list(current_top)[:3]),
            "to": ", ".join(list(new_top)[:3]),
            "detected_at": datetime.utcnow().isoformat()
        }

    def _analyze_conversation_focus(self, query_topics: List[str]) -> Dict[str, Any]:
        """分析对话焦点"""
        # 统计主题频率
        topic_counter = Counter(query_topics)

        # 判断焦点类型
        top_topics = topic_counter.most_common(3)

        # 判断是入门还是进阶
        beginner_keywords = ["入门", "基础", "教程", "新手", "从零", "快速"]
        advanced_keywords = ["进阶", "深入", "原理", "源码", "优化", "实战"]

        focus_type = "通用"
        if any(kw in " ".join(query_topics) for kw in beginner_keywords):
            focus_type = "入门教程"
        elif any(kw in " ".join(query_topics) for kw in advanced_keywords):
            focus_type = "进阶深入"

        return {
            "focus": focus_type,
            "top_topics": [topic for topic, _ in top_topics],
            "reason": f"最近对话集中在 {focus_type}，主题包括: {', '.join([topic for topic, _ in top_topics[:2]])}",
            "detected_at": datetime.utcnow().isoformat()
        }

    def _detect_focus_shift(
        self,
        current_profile: Dict[str, Any],
        new_focus: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """检测焦点变化"""
        current_focus = current_profile.get("short_term_focus")

        if not current_focus:
            return None

        # 比较焦点
        if current_focus.get("focus") == new_focus.get("focus"):
            return None

        return {
            "from": current_focus.get("focus", "未知"),
            "to": new_focus.get("focus", "未知"),
            "detected_at": datetime.utcnow().isoformat()
        }

    async def _merge_interests(
        self,
        current_profile: Dict[str, Any],
        new_interests: Dict[str, float],
        interest_shift: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """融合长期和短期兴趣"""
        # 融合兴趣标签（加权平均，新兴趣权重更高）
        current_tags = current_profile.get("interest_tags", {})
        alpha = 0.3  # 旧兴趣权重

        merged_tags = {}
        all_tag_keys = set(list(current_tags.keys()) + list(new_interests.keys()))

        for tag in all_tag_keys:
            old_weight = current_tags.get(tag, 0.0)
            new_weight = new_interests.get(tag, 0.0)
            merged_tags[tag] = alpha * old_weight + (1 - alpha) * new_weight

        # 归一化
        total = sum(merged_tags.values())
        if total > 0:
            merged_tags = {tag: weight / total for tag, weight in merged_tags.items()}

        # 更新画像
        updated_profile = current_profile.copy()
        updated_profile["interest_tags"] = merged_tags
        updated_profile["total_favorites"] = current_profile.get("total_favorites", 0) + len(new_interests)
        updated_profile["recent_interest_shift"] = interest_shift
        updated_profile["last_update_source"] = "sync"
        updated_profile["updated_at"] = datetime.utcnow()

        return updated_profile

    async def _update_short_term_focus(
        self,
        current_profile: Dict[str, Any],
        new_focus: Dict[str, Any],
        focus_shift: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """更新短期焦点"""
        updated_profile = current_profile.copy()
        updated_profile["short_term_focus"] = new_focus
        updated_profile["last_update_source"] = "chat"
        updated_profile["updated_at"] = datetime.utcnow()

        return updated_profile

    async def _save_profile_update(self, session_id: str, profile: Dict[str, Any]):
        """保存画像更新"""
        async with async_session_factory() as db:
            await db.execute(
                update(UserInterestProfile)
                .where(UserInterestProfile.session_id == session_id)
                .values(
                    interest_tags=profile.get("interest_tags"),
                    followed_ups=profile.get("followed_ups"),
                    category_distribution=profile.get("category_distribution"),
                    total_favorites=profile.get("total_favorites"),
                    visual_style_preference=profile.get("visual_style_preference"),
                    content_type_preference=profile.get("content_type_preference"),
                    recent_interest_shift=profile.get("recent_interest_shift"),
                    short_term_focus=profile.get("short_term_focus"),
                    confidence_score=profile.get("confidence_score"),
                    last_update_source=profile.get("last_update_source"),
                    updated_at=profile.get("updated_at")
                )
            )
            await db.commit()

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        import re

        # 中文分词
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', text)

        # 英文单词
        english_words = re.findall(r'[A-Za-z]{3,}', text)

        # 停用词
        stopwords = {
            "视频", "这个", "什么", "怎么", "如何", "为什么", "可以", "需要", "应该",
            "一个", "一些", "还有", "或者", "但是", "因为", "所以", "然后", "之后"
        }

        keywords = []
        for word in chinese_words + english_words:
            word = word.strip()
            if word and word not in stopwords and len(word) >= 2:
                keywords.append(word)

        return keywords


# 单例
_interest_updater: Optional[InterestUpdater] = None


def get_interest_updater() -> InterestUpdater:
    """获取兴趣更新器单例"""
    global _interest_updater
    if _interest_updater is None:
        _interest_updater = InterestUpdater()
    return _interest_updater
