"""
推荐服务
"""
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, and_, desc
from app.database import async_session_factory as async_session_maker
from app.models import (
    UserInterestProfile,
    RecommendationHistory,
    Favorite,
    ScheduledTask
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RecommendationService:
    """推荐服务（被动请求 + 主动推送）"""

    def __init__(self):
        pass

    async def get_recommendations(
        self,
        session_id: str,
        num: int = 10,
        rec_type: str = "all"
    ) -> List[Dict[str, Any]]:
        """
        生成推荐（三路：UP主追踪 + 关键词匹配 + 个性化热榜）

        Args:
            session_id: 会话ID
            num: 推荐数量
            rec_type: 推荐类型（all/up_follow/keyword_match/trending/collaborative）

        Returns:
            推荐列表
        """
        all_recommendations = []

        # 获取用户画像
        profile = await self._get_or_create_profile(session_id)

        if rec_type in ["all", "up_follow"]:
            # UP主追踪推荐
            up_recs = await self._recommend_by_up_follow(profile, num // 3)
            all_recommendations.extend(up_recs)

        if rec_type in ["all", "keyword_match"]:
            # 关键词匹配推荐
            keyword_recs = await self._recommend_by_keywords(profile, num // 3)
            all_recommendations.extend(keyword_recs)

        if rec_type in ["all", "trending"]:
            # 热门推荐
            trending_recs = await self._recommend_by_trending(num // 3)
            all_recommendations.extend(trending_recs)

        # 去重并排序
        seen_bvids = set()
        unique_recs = []
        for rec in all_recommendations:
            bvid = rec.get("bvid")
            if bvid and bvid not in seen_bvids:
                seen_bvids.add(bvid)
                unique_recs.append(rec)

        # 按分数排序
        unique_recs.sort(key=lambda x: x.get("score", 0), reverse=True)

        # 记录推荐历史
        for rec in unique_recs[:num]:
            await self._record_recommendation(session_id, rec, rec_type)

        return unique_recs[:num]

    async def _recommend_by_up_follow(
        self,
        profile: UserInterestProfile,
        limit: int
    ) -> List[Dict[str, Any]]:
        """基于关注的UP主推荐"""
        recommendations = []
        followed_ups = profile.followed_ups or []

        try:
            # 调用Bilibili API获取UP主最新视频
            from app.services.bilibili import BilibiliService

            async with BilibiliService() as bili:
                for up_info in followed_ups[:5]:
                    mid = up_info.get("mid")
                    up_name = up_info.get("name", "未知UP主")

                    if not mid:
                        continue

                    # 获取UP主的最新视频
                    up_videos_result = await bili.get_up_videos(mid=mid, pn=1, ps=2)
                    up_videos = up_videos_result.get("videos", [])

                    for video in up_videos:
                        recommendations.append({
                            "bvid": video.get("bvid", ""),
                            "title": video.get("title", ""),
                            "author": up_name,
                            "reason": f"你关注的UP主{up_name}更新了",
                            "score": up_info.get("score", 0.8),
                            "type": "up_follow",
                            "pic": video.get("pic", ""),
                            "duration": video.get("duration", 0)
                        })

                    if len(recommendations) >= limit:
                        break

        except Exception as e:
            logger.error(f"Failed to fetch UP videos: {e}")
            # Fallback到模拟数据
            for up_info in followed_ups[:limit]:
                recommendations.append({
                    "bvid": f"BV{up_info['mid']}xxxx",
                    "title": f"{up_info['name']}的最新视频",
                    "reason": f"你关注的UP主{up_info['name']}更新了",
                    "score": up_info.get("score", 0.8),
                    "type": "up_follow"
                })

        return recommendations[:limit]

    async def _recommend_by_keywords(
        self,
        profile: UserInterestProfile,
        limit: int
    ) -> List[Dict[str, Any]]:
        """基于关键词推荐"""
        recommendations = []
        interest_tags = profile.interest_tags or {}

        # 取top关键词
        top_keywords = sorted(interest_tags.items(), key=lambda x: x[1], reverse=True)[:5]

        try:
            # 调用Bilibili API搜索
            from app.services.bilibili import BilibiliService

            async with BilibiliService() as bili:
                for keyword, score in top_keywords:
                    # 使用关键词搜索B站
                    search_results = await bili.search_bilibili(
                        keyword=keyword,
                        search_type="video"
                    )

                    items = search_results.get("items", [])
                    for item in items[:2]:  # 每个关键词取前2个结果
                        recommendations.append({
                            "bvid": item.get("bvid", ""),
                            "title": item.get("title", ""),
                            "author": item.get("author", ""),
                            "reason": f"基于你对'{keyword}'的兴趣",
                            "score": score * 0.9,
                            "type": "keyword_match",
                            "pic": item.get("pic", ""),
                            "play": item.get("play", 0)
                        })

                    if len(recommendations) >= limit:
                        break

        except Exception as e:
            logger.error(f"Failed to search by keywords: {e}")
            # Fallback到模拟数据
            for keyword, score in top_keywords:
                recommendations.append({
                    "bvid": f"BV{keyword}xxxx",
                    "title": f"关于'{keyword}'的推荐视频",
                    "reason": f"基于你对'{keyword}'的兴趣",
                    "score": score * 0.9,
                    "type": "keyword_match"
                })

        return recommendations[:limit]

    async def _recommend_by_trending(self, limit: int) -> List[Dict[str, Any]]:
        """基于热榜推荐"""
        try:
            # 调用Bilibili API获取热榜
            from app.services.bilibili import BilibiliService

            async with BilibiliService() as bili:
                # 获取热榜数据
                trending_result = await bili.get_trending(rid=0)  # rid=0 为全站热榜

                videos = trending_result.get("videos", [])

                recommendations = []
                for i, video in enumerate(videos[:limit]):
                    recommendations.append({
                        "bvid": video.get("bvid", ""),
                        "title": video.get("title", ""),
                        "author": video.get("owner", {}).get("name", ""),
                        "reason": "B站热门推荐",
                        "score": 0.9 - (i * 0.05),  # 递减分数
                        "type": "trending",
                        "pic": video.get("pic", ""),
                        "play": video.get("stat", {}).get("view", 0)
                    })

                return recommendations

        except Exception as e:
            logger.error(f"Failed to fetch trending: {e}")
            # Fallback到模拟数据
            return [
                {
                    "bvid": f"BV1trending{i}",
                    "title": f"热门视频{i}",
                    "reason": "B站热门推荐",
                    "score": 0.7,
                    "type": "trending"
                }
                for i in range(limit)
            ]

    async def check_and_push_new_videos(self, session_id: str) -> None:
        """检查新视频并通过WebSocket推送"""
        try:
            # 获取用户画像
            profile = await self._get_or_create_profile(session_id)

            # 生成新的推荐
            new_recommendations = await self.get_recommendations(
                session_id=session_id,
                num=3,
                rec_type="all"
            )

            if new_recommendations:
                logger.info(f"Found {len(new_recommendations)} new recommendations for {session_id}")

                # 实现WebSocket推送逻辑
                # 这里可以集成WebSocket连接管理器
                from app.models import UserSession
                from sqlalchemy import select

                async with async_session_maker() as session:
                    # 获取用户会话信息
                    stmt = select(UserSession).where(UserSession.session_id == session_id)
                    result = await session.execute(stmt)
                    user_session = result.scalar_one_or_none()

                if user_session:
                    # 构建推送消息
                    push_message = {
                        "type": "new_recommendations",
                        "session_id": session_id,
                        "data": {
                            "count": len(new_recommendations),
                            "recommendations": new_recommendations[:5],
                            "timestamp": datetime.utcnow().isoformat()
                        }
                    }

                    # 实际的WebSocket推送
                    try:
                        from app.routers.websocket_manager import manager

                        # 发送WebSocket推送消息
                        await manager.send_personal_message(push_message, session_id)

                        logger.info(f"WebSocket push sent for session {session_id}: {len(new_recommendations)} new videos")

                    except Exception as ws_error:
                        logger.warning(f"WebSocket push failed for session {session_id}: {ws_error}")
                        # 即使WebSocket推送失败，推荐数据仍然保存到历史记录

                    logger.info(f"Push notification sent for session {session_id}: {len(new_recommendations)} new videos")

                    # 可以保存到推送历史记录
                    await self._save_push_history(session_id, push_message)

            else:
                logger.info(f"No new recommendations found for session {session_id}")

        except Exception as e:
            logger.error(f"Failed to check and push new videos: {e}")

    async def _save_push_history(self, session_id: str, message: dict) -> None:
        """保存推送历史"""
        try:
            from app.models import PushHistory
            from datetime import datetime

            async with async_session_maker() as session:
                push_record = PushHistory(
                    session_id=session_id,
                    message_type=message.get("type"),
                    message_content=str(message),
                    sent_at=datetime.utcnow(),
                    status="sent"
                )
                session.add(push_record)
                await session.commit()

        except Exception as e:
            logger.error(f"Failed to save push history: {e}")

    async def push_trending_digest(self, session_id: str) -> None:
        """每日热榜摘要推送"""
        try:
            # 获取用户画像以个性化推荐
            profile = await self._get_or_create_profile(session_id)

            # 获取热榜数据
            trending_recs = await self._recommend_by_trending(limit=10)

            if trending_recs:
                # 生成热榜摘要
                digest_summary = await self._generate_trending_summary(trending_recs, profile)

                # 构建推送消息
                digest_message = {
                    "type": "trending_digest",
                    "session_id": session_id,
                    "data": {
                        "title": "今日B站热榜摘要",
                        "summary": digest_summary,
                        "videos": trending_recs[:5],
                        "timestamp": datetime.utcnow().isoformat()
                    }
                }

                # 实际的推送逻辑
                try:
                    from app.routers.websocket_manager import manager

                    # 通过WebSocket推送给用户
                    await manager.send_personal_message(digest_message, session_id)

                    logger.info(f"Trending digest pushed via WebSocket for session {session_id}: {len(trending_recs)} videos")

                except Exception as ws_error:
                    logger.warning(f"WebSocket push failed for trending digest (session {session_id}): {ws_error}")
                    # 可以添加其他推送方式作为fallback（邮件、短信等）
                    logger.info(f"Trending digest prepared for session {session_id}: {len(trending_recs)} videos")

                # 保存推送历史
                await self._save_push_history(session_id, digest_message)

        except Exception as e:
            logger.error(f"Failed to push trending digest: {e}")

    async def _generate_trending_summary(self, trending_recs: list, profile: UserInterestProfile) -> str:
        """生成热榜摘要"""
        try:
            # 使用LLM生成热榜摘要
            from app.config import settings
            from langchain_openai import ChatOpenAI
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser

            # 准备视频信息
            videos_text = "\n".join([
                f"{i+1}. {rec.get('title', '')} - {rec.get('author', '未知UP主')}"
                for i, rec in enumerate(trending_recs[:10])
            ])

            # 构建摘要提示词
            summary_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一个视频内容摘要专家。
请根据提供的视频列表，生成一个简洁的B站热榜摘要。

要求：
1. 总结3-5个主要主题或趋势
2. 提及用户可能感兴趣的内容（基于其兴趣标签）
3. 语言简洁，每条摘要不超过30字
4. 使用友好的语气

输出格式：
- 今日B站热榜涵盖：主题1、主题2、主题3...
- 推荐你看：基于你的兴趣..."""),
                ("human", """用户兴趣：{user_interests}

今日热榜视频：
{videos_text}

请生成热榜摘要：""")
            ])

            # 获取LLM实例
            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.llm_model,
                temperature=0.7
            )

            # 构建处理链
            chain = summary_prompt | llm | StrOutputParser()

            # 生成摘要
            user_interests = ", ".join(list(profile.interest_tags.keys())[:5]) if profile.interest_tags else "暂无"

            summary = await chain.ainvoke({
                "user_interests": user_interests,
                "videos_text": videos_text
            })

            return summary.strip()

        except Exception as e:
            logger.error(f"Failed to generate trending summary: {e}")
            # Fallback到简单摘要
            return f"今日B站热榜包含{len(trending_recs)}个热门视频，涵盖多个领域和话题。"

    async def update_interest_profile(self, session_id: str) -> Dict[str, Any]:
        """
        从收藏夹中提取并更新兴趣画像（关键词 + UP主）

        Args:
            session_id: 会话ID

        Returns:
            更新后的画像
        """
        try:
            # 获取收藏视频
            async with async_session_maker() as session:
                stmt = select(Favorite).where(Favorite.session_id == session_id)
                result = await session.execute(stmt)
                favorites = result.scalars().all()

            # 提取关键词（从标题和标签）
            keyword_counts = {}
            up_counts = {}

            for fav in favorites:
                # 使用NLP提取关键词
                extracted_keywords = await self._extract_keywords_from_text(
                    f"{fav.title} {fav.description or ''}"
                )

                # 统计关键词
                for keyword in extracted_keywords:
                    keyword_counts[keyword] = keyword_counts.get(keyword, 0) + 1

                # 统计UP主
                if fav.mid:
                    up_name = fav.author or f"UP{fav.mid}"
                    up_counts[fav.mid] = {
                        "name": up_name,
                        "count": up_counts.get(fav.mid, {}).get("count", 0) + 1,
                        "mid": fav.mid
                    }

            # 归一化分数
            total_keywords = sum(keyword_counts.values()) or 1
            interest_tags = {
                k: v / total_keywords
                for k, v in keyword_counts.items()
            }

            # 构建UP主列表
            followed_ups = [
                {
                    "mid": v["mid"],
                    "name": v["name"],
                    "score": v["count"] / len(favorites) if favorites else 0
                }
                for v in up_counts.values()
            ]
            followed_ups.sort(key=lambda x: x["score"], reverse=True)

            # 更新或创建画像
            async with async_session_maker() as session:
                stmt = select(UserInterestProfile).where(
                    UserInterestProfile.session_id == session_id
                )
                result = await session.execute(stmt)
                profile = result.scalar_one_or_none()

                if profile:
                    profile.interest_tags = interest_tags
                    profile.followed_ups = followed_ups
                    profile.total_favorites = len(favorites)
                    profile.updated_at = datetime.utcnow()
                else:
                    profile = UserInterestProfile(
                        session_id=session_id,
                        interest_tags=interest_tags,
                        followed_ups=followed_ups,
                        total_favorites=len(favorites)
                    )
                    session.add(profile)

                await session.commit()
                await session.refresh(profile)

            logger.info(f"Updated interest profile for session {session_id}")

            return {
                "session_id": session_id,
                "interest_tags": interest_tags,
                "followed_ups": followed_ups,
                "total_favorites": len(favorites)
            }

        except Exception as e:
            logger.error(f"Failed to update interest profile: {e}")
            return {
                "session_id": session_id,
                "interest_tags": {},
                "followed_ups": [],
                "total_favorites": 0
            }

    async def _get_or_create_profile(self, session_id: str) -> UserInterestProfile:
        """获取或创建用户画像"""
        async with async_session_maker() as session:
            stmt = select(UserInterestProfile).where(
                UserInterestProfile.session_id == session_id
            )
            result = await session.execute(stmt)
            profile = result.scalar_one_or_none()

            if not profile:
                profile = UserInterestProfile(
                    session_id=session_id,
                    interest_tags={},
                    followed_ups=[],
                    total_favorites=0
                )
                session.add(profile)
                await session.commit()
                await session.refresh(profile)

            return profile

    async def _record_recommendation(
        self,
        session_id: str,
        recommendation: Dict[str, Any],
        rec_type: str
    ) -> None:
        """记录推荐历史"""
        try:
            async with async_session_maker() as session:
                history = RecommendationHistory(
                    session_id=session_id,
                    recommended_bvid=recommendation.get("bvid"),
                    rec_type=rec_type,
                    rec_reason=recommendation.get("reason", ""),
                    score=recommendation.get("score", 0.0)
                )
                session.add(history)
                await session.commit()
        except Exception as e:
            logger.error(f"Failed to record recommendation: {e}")

    async def submit_feedback(
        self,
        session_id: str,
        bvid: str,
        action: str
    ) -> bool:
        """
        提交推荐反馈

        Args:
            session_id: 会话ID
            bvid: 视频BV号
            action: 用户动作（viewed/favorited/dismissed/ignored）

        Returns:
            是否成功
        """
        try:
            async with async_session_maker() as session:
                stmt = select(RecommendationHistory).where(
                    and_(
                        RecommendationHistory.session_id == session_id,
                        RecommendationHistory.recommended_bvid == bvid
                    )
                ).order_by(desc(RecommendationHistory.created_at))

                result = await session.execute(stmt)
                history = result.scalar_one_or_none()

                if history:
                    history.user_action = action
                    history.shown_at = datetime.utcnow()
                    await session.commit()
                    return True

                return False

        except Exception as e:
            logger.error(f"Failed to submit feedback: {e}")
            return False

    async def _extract_keywords_from_text(self, text: str) -> List[str]:
        """使用NLP从文本中提取关键词"""
        try:
            # 方法1: 使用LLM进行关键词提取
            from app.config import settings
            from langchain_openai import ChatOpenAI
            from langchain_core.prompts import ChatPromptTemplate
            from langchain_core.output_parsers import StrOutputParser

            # 构建关键词提取提示词
            keyword_prompt = ChatPromptTemplate.from_messages([
                ("system", """你是一个关键词提取专家。
请从给定的文本中提取3-5个最重要的关键词。

规则：
1. 关键词应该是名词或专业术语
2. 优先提取技术名词、领域术语
3. 过滤掉停用词和通用词
4. 按重要性排序

输出格式：直接返回关键词列表，用逗号分隔
例如：深度学习, 神经网络, Python"""),
                ("human", "请从以下文本中提取关键词：\n\n{text}")
            ])

            # 直接使用百炼模型
            try:
                from langchain_openai import ChatOpenAI
                from langchain_core.output_parsers import StrOutputParser

                llm = ChatOpenAI(
                    api_key=settings.openai_api_key,
                    base_url=settings.openai_base_url,
                    model=settings.llm_model,
                    temperature=0.3
                )

                # 构建处理链
                chain = keyword_prompt | llm | StrOutputParser()

                # 提取关键词
                result = await chain.ainvoke({"text": text})

                # 解析关键词
                keywords = [kw.strip() for kw in result.split(",") if kw.strip()]
                return keywords[:5]

            except Exception as e:
                logger.debug(f"LLM keyword extraction failed: {e}")

                # Fallback: 简单规则提取
                return self._fallback_keyword_extraction(text)

        except Exception as e:
            logger.error(f"Keyword extraction failed: {e}")
            return self._fallback_keyword_extraction(text)

    def _fallback_keyword_extraction(self, text: str) -> List[str]:
        """降级的关键词提取方案"""
        # 常见技术关键词词典
        tech_keywords = {
            "python": ["Python", "python", "PYTHON"],
            "java": ["Java", "java", "JAVA"],
            "javascript": ["JavaScript", "javascript", "JS", "js"],
            "深度学习": ["深度学习", "DL", "deeplearning"],
            "机器学习": ["机器学习", "ML", "machinelearning"],
            "人工智能": ["人工智能", "AI", "artificialintelligence"],
            "tensorflow": ["TensorFlow", "tensorflow", "tf"],
            "pytorch": ["PyTorch", "pytorch"],
            "react": ["React", "react", "前端"],
            "vue": ["Vue", "vue", "前端框架"],
            "算法": ["算法", "algorithm"],
            "数据结构": ["数据结构", "data structure"],
            "数据库": ["数据库", "database", "MySQL", "MongoDB"],
            "云计算": ["云计算", "cloud computing"],
            "区块链": ["区块链", "blockchain"],
            "微服务": ["微服务", "microservices"]
        }

        found_keywords = []

        # 在标题中搜索关键词
        text_lower = text.lower()
        for keyword, variants in tech_keywords.items():
            for variant in variants:
                if variant.lower() in text_lower:
                    found_keywords.append(keyword)
                    break

        # 按频率过滤（出现多次的关键词）
        keyword_counts = {}
        for kw in found_keywords:
            keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

        # 按出现频率排序
        sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
        return [kw for kw, count in sorted_keywords[:5]]
