import json
from typing import Optional
from langchain.tools import tool

from app.services.profile.profile_builder import get_profile_builder
from app.services.profile.interest_updater import get_interest_updater


@tool("build_user_profile", parse_docstring=True)
def build_user_profile_tool(
    session_id: str,
    force_rebuild: bool = False
) -> str:
    """构建或更新用户兴趣画像（基于收藏夹 + 封面理解）

    使用此工具来从用户的收藏夹中提取兴趣标签、关注 UP主、内容偏好等信息。
    这对于个性化推荐非常重要。

    Args:
        session_id: 用户会话 ID
        force_rebuild: 是否强制重建画像（默认 false，使用缓存）

    Returns:
        JSON 字符串，包含用户画像：
        {
            "session_id": str,
            "interest_tags": Dict[str, float],
            "followed_ups": List[Dict],
            "category_distribution": Dict,
            "total_favorites": int,
            "visual_style_preference": Dict,
            "content_type_preference": Dict,
            "recent_interest_shift": Optional[Dict],
            "short_term_focus": Optional[Dict],
            "confidence_score": float
        }
    """
    import asyncio

    async def _build():
        builder = get_profile_builder()
        return await builder.build_profile_from_favorites(
            session_id=session_id,
            force_rebuild=force_rebuild
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_build())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"session_id": session_id, "error": f"画像构建失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("update_profile_from_conversation", parse_docstring=True)
def update_profile_from_conversation_tool(
    session_id: str,
    conversation_summary: str,
    query_topics: list
) -> str:
    """从对话历史更新用户画像（短期兴趣）

    使用此工具根据用户的对话内容更新短期兴趣焦点。
    这有助于捕捉用户当前阶段的学习重点和偏好变化。

    Args:
        session_id: 用户会话 ID
        conversation_summary: 对话摘要（Gemma 4 生成）
        query_topics: 用户查询的主题列表（如 ["LangChain", "RAG", "向量数据库"]）

    Returns:
        JSON 字符串，包含更新结果：
        {
            "session_id": str,
            "short_term_focus": Dict,
            "focus_shift": Optional[Dict],
            "updated_profile": Dict
        }
    """
    import asyncio

    async def _update():
        updater = get_interest_updater()
        return await updater.update_from_conversation(
            session_id=session_id,
            conversation_summary=conversation_summary,
            query_topics=query_topics
        )

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_update())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"session_id": session_id, "error": f"画像更新失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("get_user_profile", parse_docstring=True)
def get_user_profile_tool(
    session_id: str
) -> str:
    """获取用户当前画像

    使用此工具查看用户的兴趣画像，包括兴趣标签、关注 UP主、内容偏好等。

    Args:
        session_id: 用户会话 ID

    Returns:
        JSON 字符串，包含用户画像：
        {
            "session_id": str,
            "interest_tags": Dict[str, float],
            "followed_ups": List[Dict],
            "category_distribution": Dict,
            "total_favorites": int,
            "visual_style_preference": Dict,
            "content_type_preference": Dict,
            "recent_interest_shift": Optional[Dict],
            "short_term_focus": Optional[Dict],
            "confidence_score": float
        }
    """
    import asyncio

    async def _get():
        from app.models import UserInterestProfile
        from app.database import async_session_factory
        from sqlalchemy import select

        async with async_session_factory() as db:
            result = await db.execute(
                select(UserInterestProfile).where(
                    UserInterestProfile.session_id == session_id
                )
            )
            profile = result.scalar_one_or_none()

            if profile:
                return {
                    "session_id": profile.session_id,
                    "interest_tags": profile.interest_tags or {},
                    "followed_ups": profile.followed_ups or [],
                    "category_distribution": profile.category_distribution or {},
                    "total_favorites": profile.total_favorites or 0,
                    "visual_style_preference": profile.visual_style_preference or {},
                    "content_type_preference": profile.content_type_preference or {},
                    "recent_interest_shift": profile.recent_interest_shift,
                    "short_term_focus": profile.short_term_focus,
                    "confidence_score": profile.confidence_score or 0.5
                }
            else:
                return {
                    "session_id": session_id,
                    "error": "画像不存在，请先使用 build_user_profile 构建"
                }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_get())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"session_id": session_id, "error": f"获取画像失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)
