"""
用户画像构建服务

从用户的收藏夹、封面理解、对话历史中构建用户画像
"""
import asyncio
from typing import Dict, List, Any, Optional
from collections import Counter
from datetime import datetime, timedelta
from loguru import logger

from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session_factory
from app.models import (
    FavoriteVideo, FavoriteFolder, VideoCache, VideoCoverAnalysis,
    UserInterestProfile, UserProfileEmbedding,
    LongTermMemory, GlobalKnowledge
)
from app.services.gemma.cover_analyzer import get_cover_analyzer


class ProfileBuilder:
    """用户画像构建器"""

    def __init__(self):
        self.cover_analyzer = get_cover_analyzer()

    async def build_profile_from_favorites(
        self,
        session_id: str,
        force_rebuild: bool = False
    ) -> Dict[str, Any]:
        """
        从收藏夹构建用户画像

        Args:
            session_id: 用户会话 ID
            force_rebuild: 是否强制重建

        Returns:
            用户画像字典
        """
        logger.info(f"开始构建用户画像: {session_id}")

        # 1. 获取用户收藏的视频
        favorite_videos = await self._get_favorite_videos(session_id)

        if not favorite_videos:
            logger.warning(f"用户没有收藏视频: {session_id}")
            return self._get_empty_profile(session_id)

        # 2. 获取视频详情和封面分析
        enriched_videos = await self._enrich_videos_with_cover_analysis(favorite_videos)

        # 3. 提取兴趣标签
        interest_tags = await self._extract_interest_tags(enriched_videos)

        # 4. 分析分区分布
        category_distribution = self._analyze_category_distribution(enriched_videos)

        # 5. 提取关注的 UP 主
        followed_ups = self._extract_followed_ups(enriched_videos)

        # 6. 分析视觉风格偏好
        visual_style_preference = self._analyze_visual_style_preference(enriched_videos)

        # 7. 分析内容类型偏好
        content_type_preference = self._analyze_content_type_preference(enriched_videos)

        # 8. 计算置信度
        confidence_score = self._calculate_confidence(len(enriched_videos))

        # 构建画像
        profile = {
            "session_id": session_id,
            "interest_tags": interest_tags,
            "followed_ups": followed_ups,
            "category_distribution": category_distribution,
            "total_favorites": len(enriched_videos),
            "visual_style_preference": visual_style_preference,
            "content_type_preference": content_type_preference,
            "confidence_score": confidence_score,
            "last_update_source": "sync",
            "updated_at": datetime.utcnow()
        }

        # 9. 保存到数据库
        await self._save_profile(profile)

        # 10. 生成向量并存储到 ChromaDB
        await self._vectorize_and_store_profile(profile)

        logger.info(f"用户画像构建完成: {session_id}")
        return profile

    async def _get_favorite_videos(self, session_id: str) -> List[Dict[str, Any]]:
        """获取用户收藏的视频"""
        async with async_session_factory() as db:
            # 查询用户收藏的视频
            result = await db.execute(
                select(
                    VideoCache.bvid,
                    VideoCache.title,
                    VideoCache.description,
                    VideoCache.owner_name,
                    VideoCache.owner_mid,
                    VideoCache.pic_url,
                    VideoCache.duration,
                    FavoriteFolder.title.label("folder_title"),
                    FavoriteFolder.media_id.label("folder_media_id")
                )
                .join(FavoriteVideo, FavoriteVideo.bvid == VideoCache.bvid)
                .join(FavoriteFolder, FavoriteFolder.id == FavoriteVideo.folder_id)
                .where(FavoriteFolder.session_id == session_id)
                .where(FavoriteVideo.is_selected == True)
            )

            videos = []
            for row in result.fetchall():
                videos.append({
                    "bvid": row.bvid,
                    "title": row.title,
                    "description": row.description or "",
                    "owner_name": row.owner_name or "",
                    "owner_mid": row.owner_mid,
                    "pic_url": row.pic_url or "",
                    "duration": row.duration or 0,
                    "folder_title": row.folder_title or "",
                    "folder_media_id": row.folder_media_id
                })

            return videos

    async def _enrich_videos_with_cover_analysis(
        self,
        videos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """用封面分析结果丰富视频信息"""
        enriched = []

        for video in videos:
            bvid = video["bvid"]

            # 获取封面分析结果
            cover_analysis = await self.cover_analyzer.analyze_cover(
                bvid=bvid,
                pic_url=video["pic_url"],
                title=video["title"],
                force_reanalyze=False
            )

            # 合并信息
            video_with_analysis = {
                **video,
                "visual_tags": cover_analysis.get("visual_tags", []),
                "visual_summary": cover_analysis.get("visual_summary", ""),
                "quality_score": cover_analysis.get("quality_score", 0.5),
                "style_category": cover_analysis.get("style_category", "unknown")
            }

            enriched.append(video_with_analysis)

        return enriched

    async def _extract_interest_tags(
        self,
        videos: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """
        提取兴趣标签

        来源：
        1. 视频标题关键词
        2. 视觉标签（封面理解）
        3. 描述关键词
        """
        all_tags = []

        for video in videos:
            # 标题关键词
            title_tags = self._extract_keywords_from_text(video["title"])
            all_tags.extend(title_tags)

            # 视觉标签
            visual_tags = video.get("visual_tags", [])
            all_tags.extend(visual_tags)

            # 描述关键词
            if video.get("description"):
                desc_tags = self._extract_keywords_from_text(video["description"])
                all_tags.extend(desc_tags[:5])  # 只取前5个

        # 统计频率
        tag_counter = Counter(all_tags)

        # 转换为权重（归一化到 0~1）
        total = sum(tag_counter.values())
        if total == 0:
            return {}

        interest_tags = {
            tag: count / total
            for tag, count in tag_counter.most_common(20)  # 取前20个
        }

        return interest_tags

    def _extract_keywords_from_text(self, text: str) -> List[str]:
        """从文本中提取关键词"""
        import re

        # 中文分词（简单实现）
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,}', text)

        # 英文单词
        english_words = re.findall(r'[A-Za-z]{3,}', text)

        # 常见停用词
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

    def _analyze_category_distribution(
        self,
        videos: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """分析分区分布"""
        # 从视觉标签中提取分区信息
        category_mapping = {
            "教程": "教程",
            "编程": "科技",
            "科技": "科技",
            "知识": "知识",
            "科普": "知识",
            "新闻": "新闻",
            "娱乐": "娱乐",
            "游戏": "游戏",
            "音乐": "音乐",
            "实战": "实战",
            "理论": "理论"
        }

        categories = []
        for video in videos:
            visual_tags = video.get("visual_tags", [])
            for tag in visual_tags:
                category = category_mapping.get(tag, "其他")
                categories.append(category)

        if not categories:
            return {"其他": 1.0}

        # 统计分布
        category_counter = Counter(categories)
        total = sum(category_counter.values())

        return {
            cat: count / total
            for cat, count in category_counter.most_common()
        }

    def _extract_followed_ups(
        self,
        videos: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """提取关注的 UP 主"""
        up_counter = Counter()

        for video in videos:
            owner_name = video.get("owner_name", "")
            owner_mid = video.get("owner_mid")

            if owner_name and owner_mid:
                up_counter[(owner_mid, owner_name)] += 1

        # 转换为列表，按收藏数量排序
        followed_ups = [
            {
                "mid": mid,
                "name": name,
                "score": count / len(videos)  # 归一化得分
            }
            for (mid, name), count in up_counter.most_common(10)
        ]

        return followed_ups

    def _analyze_visual_style_preference(
        self,
        videos: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """分析视觉风格偏好"""
        style_counter = Counter()

        for video in videos:
            style_category = video.get("style_category", "unknown")
            style_counter[style_category] += 1

        if not style_counter:
            return {"unknown": 1.0}

        total = sum(style_counter.values())
        return {
            style: count / total
            for style, count in style_counter.most_common()
        }

    def _analyze_content_type_preference(
        self,
        videos: List[Dict[str, Any]]
    ) -> Dict[str, float]:
        """分析内容类型偏好（实战 vs 理论）"""
        # 从视觉标签中判断
        practical_tags = ["实战", "教程", "项目", "代码"]
        theoretical_tags = ["理论", "原理", "基础", "介绍"]

        practical_count = 0
        theoretical_count = 0

        for video in videos:
            visual_tags = video.get("visual_tags", [])
            for tag in visual_tags:
                if any(pt in tag for pt in practical_tags):
                    practical_count += 1
                elif any(tt in tag for tt in theoretical_tags):
                    theoretical_count += 1

        total = practical_count + theoretical_count
        if total == 0:
            return {"实战": 0.5, "理论": 0.5}

        return {
            "实战": practical_count / total,
            "理论": theoretical_count / total
        }

    def _calculate_confidence(self, video_count: int) -> float:
        """计算画像置信度"""
        # 视频数量越多，置信度越高
        # 10个视频 = 0.5, 50个视频 = 0.8, 100个视频 = 0.95
        if video_count < 10:
            return 0.3
        elif video_count < 50:
            return 0.5 + (video_count - 10) / 40 * 0.3
        else:
            return min(0.95, 0.8 + (video_count - 50) / 50 * 0.15)

    async def _save_profile(self, profile: Dict[str, Any]):
        """保存画像到数据库"""
        async with async_session_factory() as db:
            # 检查是否已存在
            existing = await db.execute(
                select(UserInterestProfile).where(
                    UserInterestProfile.session_id == profile["session_id"]
                )
            )
            existing_profile = existing.scalar_one_or_none()

            if existing_profile:
                # 更新
                await db.execute(
                    update(UserInterestProfile)
                    .where(UserInterestProfile.session_id == profile["session_id"])
                    .values(
                        interest_tags=profile["interest_tags"],
                        followed_ups=profile["followed_ups"],
                        category_distribution=profile["category_distribution"],
                        total_favorites=profile["total_favorites"],
                        visual_style_preference=profile["visual_style_preference"],
                        content_type_preference=profile["content_type_preference"],
                        confidence_score=profile["confidence_score"],
                        last_update_source=profile["last_update_source"],
                        updated_at=profile["updated_at"]
                    )
                )
            else:
                # 新增
                new_profile = UserInterestProfile(
                    session_id=profile["session_id"],
                    interest_tags=profile["interest_tags"],
                    followed_ups=profile["followed_ups"],
                    category_distribution=profile["category_distribution"],
                    total_favorites=profile["total_favorites"],
                    visual_style_preference=profile["visual_style_preference"],
                    content_type_preference=profile["content_type_preference"],
                    confidence_score=profile["confidence_score"],
                    last_update_source=profile["last_update_source"]
                )
                db.add(new_profile)

            await db.commit()

    async def _vectorize_and_store_profile(self, profile: Dict[str, Any]):
        """向量化画像并存储到 ChromaDB"""
        try:
            from app.config import settings
            from langchain_chroma import Chroma
            from langchain_core.documents import Document

            # 延迟导入避免循环依赖
            def _get_embeddings():
                try:
                    from langchain_community.embeddings import DashScopeEmbeddings
                    return DashScopeEmbeddings(
                        dashscope_api_key=settings.openai_api_key,
                        model=settings.embedding_model
                    )
                except Exception as e:
                    logger.warning(f"DashScopeEmbeddings 不可用: {e}")
                    from langchain_openai import OpenAIEmbeddings
                    return OpenAIEmbeddings(
                        api_key=settings.openai_api_key,
                        base_url=settings.openai_base_url,
                        model=settings.embedding_model
                    )

            # 1. 将用户画像转换为文本描述
            profile_text = self._profile_to_text(profile)

            if not profile_text or len(profile_text.strip()) < 10:
                logger.warning(f"画像文本为空，跳过向量化: {profile.get('session_id')}")
                return

            # 2. 初始化 Embeddings
            embeddings = _get_embeddings()

            # 3. 初始化 ChromaDB (使用专门的 user_profiles collection)
            vectorstore = Chroma(
                collection_name="user_profiles",
                embedding_function=embeddings,
                persist_directory=str(settings.chroma_dir)
            )

            # 4. 创建文档
            doc = Document(
                page_content=profile_text,
                metadata={
                    "session_id": profile.get("session_id", ""),
                    "type": "user_profile",
                    "total_favorites": profile.get("total_favorites", 0),
                    "confidence_score": profile.get("confidence_score", 0.0),
                    "last_update_source": profile.get("last_update_source", "unknown"),
                    "created_at": datetime.utcnow().isoformat()
                }
            )

            # 5. 删除旧的向量（如果存在）
            try:
                vectorstore._collection.delete(
                    where={"session_id": profile.get("session_id", "")}
                )
            except Exception as e:
                logger.debug(f"删除旧画像向量失败（可能不存在）: {e}")

            # 6. 添加新向量
            vectorstore.add_documents([doc])

            # 7. 获取向量ID并更新数据库
            collection = vectorstore._collection
            result = collection.get(
                where={"session_id": profile.get("session_id", "")},
                limit=1
            )

            if result and result.get("ids"):
                vector_id = result["ids"][0]
                await self._save_vector_id_to_db(
                    profile.get("session_id", ""),
                    vector_id
                )

            logger.info(f"画像向量化完成: {profile.get('session_id')}, vector_id: {vector_id if result else 'N/A'}")

        except Exception as e:
            logger.error(f"画像向量化失败: {profile.get('session_id')}, {e}")
            # 不抛出异常，避免影响主流程

    def _profile_to_text(self, profile: Dict[str, Any]) -> str:
        """将用户画像转换为文本描述"""
        parts = []

        # 兴趣标签
        interest_tags = profile.get("interest_tags", {})
        if interest_tags:
            top_interests = sorted(interest_tags.items(), key=lambda x: x[1], reverse=True)[:10]
            interest_text = ", ".join([f"{tag}({score:.2f})" for tag, score in top_interests])
            parts.append(f"兴趣标签: {interest_text}")

        # 关注的UP主
        followed_ups = profile.get("followed_ups", [])
        if followed_ups:
            up_names = [up.get("name", "未知") for up in followed_ups[:5]]
            parts.append(f"关注的UP主: {', '.join(up_names)}")

        # 分区分布
        category_dist = profile.get("category_distribution", {})
        if category_dist:
            category_text = ", ".join([f"{cat}({count})" for cat, count in category_dist.items()])
            parts.append(f"内容分区分布: {category_text}")

        # 视觉风格偏好
        visual_style = profile.get("visual_style_preference", {})
        if visual_style:
            style_text = ", ".join([f"{style}({score:.2f})" for style, score in visual_style.items()])
            parts.append(f"视觉风格偏好: {style_text}")

        # 内容类型偏好
        content_type = profile.get("content_type_preference", {})
        if content_type:
            type_text = ", ".join([f"{t}({score:.2f})" for t, score in content_type.items()])
            parts.append(f"内容类型偏好: {type_text}")

        # 统计信息
        total_favorites = profile.get("total_favorites", 0)
        confidence = profile.get("confidence_score", 0.0)
        parts.append(f"收藏总数: {total_favorites}, 画像置信度: {confidence:.2f}")

        # 兴趣变化
        interest_shift = profile.get("recent_interest_shift")
        if interest_shift:
            parts.append(f"最近兴趣变化: 从'{interest_shift.get('from', '')}'转向'{interest_shift.get('to', '')}'")

        # 短期焦点
        short_focus = profile.get("short_term_focus")
        if short_focus:
            parts.append(f"当前关注焦点: {short_focus.get('focus', '')} ({short_focus.get('reason', '')})")

        return " | ".join(parts)

    async def _save_vector_id_to_db(self, session_id: str, vector_id: str):
        """保存向量ID到数据库"""
        try:
            async with async_session_factory() as db:
                result = await db.execute(
                    select(UserInterestProfile).where(
                        UserInterestProfile.session_id == session_id
                    )
                )
                profile = result.scalar_one_or_none()

                if profile:
                    # 更新 UserProfileEmbeddingIndex 记录
                    from app.models import UserProfileEmbeddingIndex

                    # 查找是否已有记录
                    embed_result = await db.execute(
                        select(UserProfileEmbeddingIndex).where(
                            UserProfileEmbeddingIndex.session_id == session_id
                        )
                    )
                    embed_record = embed_result.scalar_one_or_none()

                    # 构建摘要文本
                    profile_data = {
                        "interest_tags": profile.interest_tags or {},
                        "followed_ups": profile.followed_ups or [],
                        "total_favorites": profile.total_favorites or 0,
                        "category_distribution": profile.category_distribution or {}
                    }
                    summary_text = self._profile_to_text(profile_data)[:500]

                    if embed_record:
                        # 更新现有记录
                        embed_record.embedding_id = vector_id
                        embed_record.summary_text = summary_text
                        embed_record.total_videos = profile.total_favorites or 0
                        embed_record.total_tags = len(profile.interest_tags or {})
                        embed_record.updated_at = datetime.utcnow()
                    else:
                        # 创建新记录
                        new_embed_record = UserProfileEmbeddingIndex(
                            session_id=session_id,
                            embedding_id=vector_id,
                            summary_text=summary_text,
                            total_videos=profile.total_favorites or 0,
                            total_tags=len(profile.interest_tags or {}),
                            model_name=settings.embedding_model,
                            last_updated_from="profile_build"
                        )
                        db.add(new_embed_record)

                    await db.commit()
                    logger.debug(f"向量ID已保存到数据库: {session_id}")

        except Exception as e:
            logger.error(f"保存向量ID失败: {session_id}, {e}")
            # 不抛出异常，避免影响主流程

    def _get_empty_profile(self, session_id: str) -> Dict[str, Any]:
        """返回空画像"""
        return {
            "session_id": session_id,
            "interest_tags": {},
            "followed_ups": [],
            "category_distribution": {},
            "total_favorites": 0,
            "visual_style_preference": {},
            "content_type_preference": {},
            "confidence_score": 0.0,
            "last_update_source": "sync",
            "updated_at": datetime.utcnow()
        }

    async def update_profile_from_conversation(
        self,
        session_id: str,
        conversation_summary: str
    ) -> Dict[str, Any]:
        """
        从对话历史更新用户画像

        Args:
            session_id: 用户会话 ID
            conversation_summary: 对话摘要

        Returns:
            更新后的用户画像
        """
        logger.info(f"从对话更新用户画像: {session_id}")

        try:
            # 1. 获取当前画像
            current_profile = await self._get_current_profile(session_id)

            # 2. 使用 LLM 从对话摘要中提取兴趣点
            new_interests = await self._extract_interests_from_conversation(conversation_summary)

            # 3. 更新兴趣标签（合并现有和新发现的兴趣）
            updated_interest_tags = self._merge_interest_tags(
                current_profile.get("interest_tags", {}),
                new_interests
            )

            # 4. 检测兴趣变化
            interest_shift = self._detect_interest_shift(
                current_profile.get("interest_tags", {}),
                new_interests
            )

            # 5. 更新短期焦点
            short_term_focus = self._update_short_term_focus(
                new_interests,
                conversation_summary
            )

            # 6. 保存更新后的画像
            updated_profile = await self._save_updated_profile(
                session_id=session_id,
                interest_tags=updated_interest_tags,
                interest_shift=interest_shift,
                short_term_focus=short_term_focus,
                current_profile=current_profile
            )

            logger.info(f"对话更新画像完成: {session_id}, 新兴趣数: {len(new_interests)}")
            return updated_profile

        except Exception as e:
            logger.error(f"从对话更新画像失败: {session_id}, {e}")
            # 返回当前画像作为降级方案
            return await self._get_current_profile(session_id)

    async def _get_current_profile(self, session_id: str) -> Dict[str, Any]:
        """获取当前用户画像"""
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
                    "confidence_score": profile.confidence_score or 0.5,
                    "recent_interest_shift": profile.recent_interest_shift,
                    "short_term_focus": profile.short_term_focus
                }
            else:
                # 如果没有现有画像，返回空画像
                return self._get_empty_profile(session_id)

    async def _extract_interests_from_conversation(self, conversation_summary: str) -> Dict[str, float]:
        """从对话摘要中提取兴趣点"""
        try:
            # 延迟导入避免循环依赖
            from app.config import settings

            # 动态导入 LangChain 组件
            def _get_chat_openai():
                from langchain_openai import ChatOpenAI
                return ChatOpenAI

            def _get_prompt_template():
                from langchain_core.prompts import ChatPromptTemplate
                return ChatPromptTemplate

            def _get_output_parser():
                from langchain_core.output_parsers import StrOutputParser
                return StrOutputParser

            ChatOpenAI = _get_chat_openai()
            ChatPromptTemplate = _get_prompt_template()
            StrOutputParser = _get_output_parser()

            # 初始化 LLM
            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.llm_model,
                temperature=0.3
            )

            # 创建提示模板
            interest_extraction_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一个用户兴趣分析专家。请从用户对话中提取出用户感兴趣的话题和标签。

规则：
1. 识别对话中提到的话题、技术、概念等
2. 为每个话题分配一个重要性分数（0.1-1.0）
3. 只提取明确的兴趣点，不要猜测
4. 返回格式：JSON对象，key是话题名称，value是分数

示例输出：
{{
    "深度学习": 0.9,
    "计算机视觉": 0.8,
    "PyTorch": 0.7
}}
"""),
                ("human", "请分析以下对话内容，提取用户的兴趣点：\n\n{conversation}")
            ])

            # 构建处理链
            chain = (
                {"conversation": lambda x: x}
                | interest_extraction_prompt
                | llm
                | StrOutputParser()
            )

            # 调用 LLM
            import json
            response = await chain.ainvoke(conversation_summary)

            # 解析 JSON 响应
            # 清理可能的 markdown 代码块标记
            response = response.strip()
            if response.startswith("```json"):
                response = response[7:]
            if response.startswith("```"):
                response = response[3:]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()

            interests = json.loads(response)
            logger.info(f"从对话提取兴趣点: {list(interests.keys())}")
            return interests

        except Exception as e:
            logger.warning(f"LLM 兴趣提取失败: {e}")
            # 降级：使用简单的关键词匹配
            return self._fallback_interest_extraction(conversation_summary)

    def _fallback_interest_extraction(self, conversation_summary: str) -> Dict[str, float]:
        """降级方案：简单的关键词提取"""
        # 常见技术关键词映射
        tech_keywords = {
            "python": 0.7, "java": 0.7, "javascript": 0.7, "c++": 0.7,
            "深度学习": 0.8, "机器学习": 0.8, "人工智能": 0.8, "ai": 0.7,
            "pytorch": 0.7, "tensorflow": 0.7, "keras": 0.6,
            "计算机视觉": 0.8, "自然语言处理": 0.8, "nlp": 0.7,
            "数据结构": 0.6, "算法": 0.6, "数据库": 0.6,
            "前端": 0.6, "后端": 0.6, "全栈": 0.7,
            "react": 0.6, "vue": 0.6, "angular": 0.6,
            "docker": 0.6, "kubernetes": 0.7, "微服务": 0.7
        }

        found_interests = {}
        summary_lower = conversation_summary.lower()

        for keyword, score in tech_keywords.items():
            if keyword.lower() in summary_lower:
                found_interests[keyword] = score

        logger.info(f"降级提取兴趣点: {list(found_interests.keys())}")
        return found_interests

    def _merge_interest_tags(
        self,
        current_tags: Dict[str, float],
        new_tags: Dict[str, float]
    ) -> Dict[str, float]:
        """合并现有和新发现的兴趣标签"""
        merged = current_tags.copy()

        for tag, score in new_tags.items():
            if tag in merged:
                # 已存在的标签，更新分数（加权平均）
                merged[tag] = (merged[tag] * 0.7 + score * 0.3)
            else:
                # 新标签，直接添加
                merged[tag] = score

        # 按分数排序并限制数量
        sorted_tags = dict(sorted(merged.items(), key=lambda x: x[1], reverse=True)[:20])
        return sorted_tags

    def _detect_interest_shift(
        self,
        current_tags: Dict[str, float],
        new_tags: Dict[str, float]
    ) -> Optional[Dict[str, Any]]:
        """检测兴趣变化"""
        if not current_tags or not new_tags:
            return None

        # 找出上升最快的新兴趣
        rising_interests = []
        for tag, score in new_tags.items():
            current_score = current_tags.get(tag, 0)
            if score > current_score + 0.3:  # 分数提升超过0.3
                rising_interests.append({
                    "tag": tag,
                    "from": current_score,
                    "to": score,
                    "change": score - current_score
                })

        if rising_interests:
            # 取变化最大的兴趣
            top_shift = max(rising_interests, key=lambda x: x["change"])
            return {
                "from": next((tag for tag, score in current_tags.items() if score == max(current_tags.values())), "未知"),
                "to": top_shift["tag"],
                "detected_at": datetime.utcnow().isoformat()
            }

        return None

    def _update_short_term_focus(
        self,
        new_interests: Dict[str, float],
        conversation_summary: str
    ) -> Optional[Dict[str, Any]]:
        """更新短期焦点"""
        if not new_interests:
            return None

        # 找出最强烈的兴趣
        top_interest = max(new_interests.items(), key=lambda x: x[1])

        # 提取对话中的关键信息作为原因
        focus_reason = f"在对话中表现出对'{top_interest[0]}'的强烈兴趣"

        return {
            "focus": top_interest[0],
            "score": top_interest[1],
            "reason": focus_reason,
            "detected_at": datetime.utcnow().isoformat()
        }

    async def _save_updated_profile(
        self,
        session_id: str,
        interest_tags: Dict[str, float],
        interest_shift: Optional[Dict[str, Any]],
        short_term_focus: Optional[Dict[str, Any]],
        current_profile: Dict[str, Any]
    ) -> Dict[str, Any]:
        """保存更新后的画像"""
        async with async_session_factory() as db:
            # 查找现有画像
            result = await db.execute(
                select(UserInterestProfile).where(
                    UserInterestProfile.session_id == session_id
                )
            )
            profile = result.scalar_one_or_none()

            if profile:
                # 更新现有画像
                profile.interest_tags = interest_tags
                profile.recent_interest_shift = interest_shift
                profile.short_term_focus = short_term_focus
                profile.updated_at = datetime.utcnow()
                profile.last_update_source = "chat"
            else:
                # 创建新画像
                new_profile = UserInterestProfile(
                    session_id=session_id,
                    interest_tags=interest_tags,
                    category_distribution=current_profile.get("category_distribution", {}),
                    followed_ups=current_profile.get("followed_ups", []),
                    total_favorites=current_profile.get("total_favorites", 0),
                    recent_interest_shift=interest_shift,
                    short_term_focus=short_term_focus,
                    confidence_score=0.5,  # 从对话更新的置信度较低
                    last_update_source="chat"
                )
                db.add(new_profile)

            await db.commit()

            # 构建完整的画像数据用于向量化
            profile_for_vectorization = {
                "session_id": session_id,
                "interest_tags": interest_tags,
                "category_distribution": current_profile.get("category_distribution", {}),
                "followed_ups": current_profile.get("followed_ups", []),
                "total_favorites": current_profile.get("total_favorites", 0),
                "visual_style_preference": current_profile.get("visual_style_preference", {}),
                "content_type_preference": current_profile.get("content_type_preference", {}),
                "confidence_score": profile.confidence_score if profile else 0.5,
                "recent_interest_shift": interest_shift,
                "short_term_focus": short_term_focus,
                "last_update_source": "chat"
            }

            # 异步向量化画像（不阻塞主流程）
            try:
                await self._vectorize_and_store_profile(profile_for_vectorization)
            except Exception as e:
                logger.warning(f"画像向量化失败（不影响主流程）: {e}")

            # 返回更新后的画像
            profile_for_vectorization["updated"] = True
            return profile_for_vectorization


# 单例
_profile_builder: Optional[ProfileBuilder] = None


def get_profile_builder() -> ProfileBuilder:
    """获取画像构建器单例"""
    global _profile_builder
    if _profile_builder is None:
        _profile_builder = ProfileBuilder()
    return _profile_builder
