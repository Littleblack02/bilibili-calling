"""
推荐系统相关工具实现
"""
import time
from typing import List, Optional
from app.services.tools.base import BaseTool, ToolResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class GetRecommendationsTool(BaseTool):
    """获取个性化推荐工具"""

    name = "get_recommendations"
    description = "根据用户的兴趣偏好和历史行为，获取个性化的视频推荐。支持多种推荐策略。"
    agent_type = "recommendation"
    parameters = {
        "type": "object",
        "properties": {
            "num": {
                "type": "integer",
                "description": "推荐数量",
                "default": 10,
                "minimum": 1,
                "maximum": 50
            },
            "rec_type": {
                "type": "string",
                "enum": ["all", "up_follow", "keyword_match", "trending", "collaborative"],
                "description": "推荐类型：all=综合, up_follow=UP主追踪, keyword_match=关键词匹配, trending=热榜, collaborative=协同过滤",
                "default": "all"
            },
            "session_id": {
                "type": "string",
                "description": "会话ID（用于个性化）"
            }
        },
        "required": ["session_id"]
    }

    async def execute(
        self,
        session_id: str,
        num: int = 10,
        rec_type: str = "all",
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        try:
            # 调用实际的推荐服务
            from app.services.recommendation.recommendation_service import get_recommendation_service

            recommendation_service = get_recommendation_service()

            # 调用推荐服务生成推荐
            recommendations = await recommendation_service.generate_recommendations(
                session_id=session_id,
                limit=num,
                save_to_candidates=True
            )

            # 格式化返回结果
            formatted_recommendations = []
            for rec in recommendations[:num]:
                formatted_recommendations.append({
                    "bvid": rec.get("bvid", ""),
                    "title": rec.get("title", ""),
                    "author": rec.get("author", ""),
                    "reason": rec.get("rec_reason", ""),
                    "score": rec.get("rec_score", 0.0),
                    "type": rec.get("recall_source", rec_type),
                    "play": rec.get("play", 0),
                    "pic_url": rec.get("pic_url", "")
                })

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data=formatted_recommendations,
                source="recommendation_get",
                execution_time_ms=execution_time,
                metadata={
                    "session_id": session_id,
                    "rec_type": rec_type,
                    "count": len(formatted_recommendations)
                }
            )
        except Exception as e:
            logger.error(f"GetRecommendationsTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="recommendation_get",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class UpdateInterestTool(BaseTool):
    """更新兴趣画像工具"""

    name = "update_interest"
    description = "分析用户收藏夹，自动更新用户的兴趣画像，包括兴趣标签、偏好UP主等。"
    agent_type = "recommendation"
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "会话ID"
            },
            "force": {
                "type": "boolean",
                "description": "是否强制更新（忽略缓存）",
                "default": False
            }
        },
        "required": ["session_id"]
    }

    async def execute(
        self,
        session_id: str,
        force: bool = False,
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        try:
            # 调用实际的画像构建服务
            from app.services.profile.profile_builder import get_profile_builder

            profile_builder = get_profile_builder()

            # 从收藏夹重建用户画像
            profile = await profile_builder.build_profile_from_favorites(
                session_id=session_id,
                force_rebuild=force
            )

            # 格式化返回结果
            formatted_profile = {
                "session_id": session_id,
                "interest_tags": profile.get("interest_tags", {}),
                "followed_ups": profile.get("followed_ups", []),
                "category_distribution": profile.get("category_distribution", {}),
                "total_favorites": profile.get("total_favorites", 0),
                "confidence_score": profile.get("confidence_score", 0.0),
                "visual_style_preference": profile.get("visual_style_preference", {}),
                "content_type_preference": profile.get("content_type_preference", {}),
                "updated": profile.get("updated", True),
                "last_update_source": profile.get("last_update_source", "sync")
            }

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data=formatted_profile,
                source="recommendation_update_interest",
                execution_time_ms=execution_time,
                metadata={"session_id": session_id, "force": force}
            )
        except Exception as e:
            logger.error(f"UpdateInterestTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="recommendation_update_interest",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetUserProfileTool(BaseTool):
    """获取用户画像工具"""

    name = "get_user_profile"
    description = "获取用户的兴趣画像和偏好信息，用于个性化推荐。"
    agent_type = "recommendation"
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "会话ID"
            }
        },
        "required": ["session_id"]
    }

    async def execute(self, session_id: str, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            # 从数据库获取用户画像
            from app.database import get_db_context
            from app.models import UserInterestProfile
            from sqlalchemy import select

            async with get_db_context() as db:
                result = await db.execute(
                    select(UserInterestProfile).where(
                        UserInterestProfile.session_id == session_id
                    )
                )
                profile = result.scalar_one_or_none()

                if profile:
                    # 提取top兴趣
                    interest_tags = profile.interest_tags or {}
                    top_interests = sorted(interest_tags.items(), key=lambda x: x[1], reverse=True)[:10]

                    # 提取关注的UP主
                    followed_ups = profile.followed_ups or []

                    formatted_profile = {
                        "session_id": session_id,
                        "top_interests": [tag for tag, score in top_interests],
                        "interest_tags": interest_tags,
                        "followed_ups": followed_ups,
                        "followed_ups_count": len(followed_ups),
                        "total_favorites": profile.total_favorites or 0,
                        "category_distribution": profile.category_distribution or {},
                        "confidence_score": profile.confidence_score or 0.0,
                        "last_updated": profile.updated_at.isoformat() if profile.updated_at else None,
                        "last_update_source": profile.last_update_source,
                        "recent_interest_shift": profile.recent_interest_shift,
                        "short_term_focus": profile.short_term_focus
                    }
                else:
                    # 如果没有画像，返回空画像
                    formatted_profile = {
                        "session_id": session_id,
                        "top_interests": [],
                        "interest_tags": {},
                        "followed_ups": [],
                        "followed_ups_count": 0,
                        "total_favorites": 0,
                        "category_distribution": {},
                        "confidence_score": 0.0,
                        "last_updated": None,
                        "last_update_source": None,
                        "message": "用户画像不存在，请先调用 update_interest 工具创建画像"
                    }

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data=formatted_profile,
                source="recommendation_user_profile",
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"GetUserProfileTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="recommendation_user_profile",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class FeedbackTool(BaseTool):
    """推荐反馈工具"""

    name = "feedback"
    description = "对推荐结果提供反馈（喜欢/不喜欢），用于优化后续推荐。"
    agent_type = "recommendation"
    parameters = {
        "type": "object",
        "properties": {
            "session_id": {
                "type": "string",
                "description": "会话ID"
            },
            "bvid": {
                "type": "string",
                "description": "视频BV号"
            },
            "action": {
                "type": "string",
                "enum": ["like", "dislike", "view", "ignore"],
                "description": "反馈动作：like=喜欢, dislike=不喜欢, view=查看, ignore=忽略"
            },
            "rec_id": {
                "type": "integer",
                "description": "推荐记录ID（可选）"
            }
        },
        "required": ["session_id", "bvid", "action"]
    }

    async def execute(
        self,
        session_id: str,
        bvid: str,
        action: str,
        rec_id: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        try:
            # 保存反馈到数据库
            from app.database import get_db_context
            from app.models import CandidateRecommendation, RecommendationHistory
            from sqlalchemy import select, and_
            from datetime import datetime

            async with get_db_context() as db:
                # 查找对应的候选推荐记录
                if rec_id:
                    candidate = await db.execute(
                        select(CandidateRecommendation).where(
                            and_(
                                CandidateRecommendation.id == rec_id,
                                CandidateRecommendation.session_id == session_id
                            )
                        )
                    )
                    candidate_rec = candidate.scalar_one_or_none()

                    if candidate_rec:
                        # 更新候选推荐状态
                        if action == "like":
                            candidate_rec.user_feedback = "positive"
                            candidate_rec.feedback_score = 1.0
                        elif action == "dislike":
                            candidate_rec.user_feedback = "negative"
                            candidate_rec.feedback_score = -1.0
                        elif action == "view":
                            candidate_rec.user_feedback = "viewed"
                            candidate_rec.feedback_score = 0.5
                        elif action == "ignore":
                            candidate_rec.user_feedback = "ignored"
                            candidate_rec.feedback_score = 0.0

                        candidate_rec.feedback_at = datetime.utcnow()

                # 创建反馈历史记录
                feedback_history = RecommendationHistory(
                    session_id=session_id,
                    recommended_bvid=bvid,
                    user_action=action,
                    rec_id=rec_id,
                    created_at=datetime.utcnow()
                )
                db.add(feedback_history)

                await db.commit()

            result = {
                "session_id": session_id,
                "bvid": bvid,
                "action": action,
                "recorded": True,
                "rec_id": rec_id
            }

            execution_time = int((time.time() - start_time) * 1000)
            return ToolResult(
                success=True,
                data=result,
                source="recommendation_feedback",
                execution_time_ms=execution_time
            )
        except Exception as e:
            logger.error(f"FeedbackTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="recommendation_feedback",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
