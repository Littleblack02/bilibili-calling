import json
from typing import Optional
from langchain.tools import tool

from app.services.recommendation.recommendation_service import get_recommendation_service


@tool("generate_recommendations", parse_docstring=True)
def generate_recommendations_tool(
    session_id: str,
    limit: int = 20
) -> str:
    """生成个性化推荐（基于用户画像 + 多路召回 + LLM 重排）

    使用此工具为用户生成个性化推荐。系统会：
    1. 分析用户兴趣画像
    2. 多路召回候选视频（兴趣/分区/热榜/UP主）
    3. 使用 Gemma 4 进行智能重排
    4. 生成推荐理由
    5. 保存到最终推荐表供用户确认

    Args:
        session_id: 用户会话 ID
        limit: 返回推荐数量（默认 20）

    Returns:
        JSON 字符串，包含推荐列表：
        {
            "count": int,
            "recommendations": [
                {
                    "bvid": str,
                    "title": str,
                    "author": str,
                    "play": int,
                    "pic_url": str,
                    "rec_score": float,
                    "rec_reason": str
                }
            ]
        }
    """
    import asyncio

    async def _generate():
        service = get_recommendation_service()
        recommendations = await service.generate_recommendations(
            session_id=session_id,
            limit=limit,
            save_to_candidates=True
        )

        return {
            "count": len(recommendations),
            "recommendations": recommendations
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_generate())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"error": f"推荐生成失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("get_candidate_recommendations", parse_docstring=True)
def get_candidate_recommendations_tool(
    session_id: str,
    status: str = "pending",
    limit: int = 20
) -> str:
    """获取最终推荐列表（供用户确认）

    使用此工具获取之前生成的推荐，展示给用户进行确认或拒绝。

    Args:
        session_id: 用户会话 ID
        status: 状态筛选 (pending=待确认, accepted=已接受, rejected=已拒绝)
        limit: 返回数量

    Returns:
        JSON 字符串，包含推荐列表：
        {
            "count": int,
            "candidates": [
                {
                    "id": int,
                    "bvid": str,
                    "title": str,
                    "author": str,
                    "play": int,
                    "pic_url": str,
                    "rec_score": float,
                    "rec_reason": str,
                    "status": str
                }
            ]
        }
    """
    import asyncio

    async def _get():
        service = get_recommendation_service()
        candidates = await service.get_candidate_recommendations(
            session_id=session_id,
            status=status,
            limit=limit
        )

        return {
            "count": len(candidates),
            "candidates": candidates
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
            {"error": f"获取推荐列表失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("accept_recommendation", parse_docstring=True)
def accept_recommendation_tool(
    session_id: str,
    candidate_id: int,
    target_media_id: int
) -> str:
    """接受推荐并添加到收藏夹

    使用此工具将用户确认的推荐视频添加到指定的收藏夹。

    Args:
        session_id: 用户会话 ID
        candidate_id: 最终推荐 ID（从 get_candidate_recommendations 获取）
        target_media_id: 目标收藏夹的 media_id

    Returns:
        JSON 字符串，包含操作结果：
        {
            "success": bool,
            "message": str
        }
    """
    import asyncio

    async def _accept():
        service = get_recommendation_service()
        success = await service.accept_recommendation(
            session_id=session_id,
            candidate_id=candidate_id,
            target_media_id=target_media_id
        )

        return {
            "success": success,
            "message": "已添加到收藏夹" if success else "添加失败"
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_accept())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"success": False, "message": f"操作失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("reject_recommendation", parse_docstring=True)
def reject_recommendation_tool(
    session_id: str,
    candidate_id: int,
    feedback: Optional[str] = None
) -> str:
    """拒绝推荐（可选提供反馈）

    使用此工具标记用户拒绝的推荐，并可选地记录用户反馈。
    这有助于优化未来的推荐策略。

    Args:
        session_id: 用户会话 ID
        candidate_id: 最终推荐 ID
        feedback: 用户反馈（可选，说明为什么拒绝）

    Returns:
        JSON 字符串，包含操作结果：
        {
            "success": bool,
            "message": str
        }
    """
    import asyncio

    async def _reject():
        service = get_recommendation_service()
        success = await service.reject_recommendation(
            session_id=session_id,
            candidate_id=candidate_id,
            feedback=feedback
        )

        return {
            "success": success,
            "message": "已标记为拒绝" if success else "操作失败"
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_reject())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"success": False, "message": f"操作失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("setup_recommendation_schedule", parse_docstring=True)
def setup_recommendation_schedule_tool(
    session_id: str,
    check_interval_hours: int = 6,
    push_times: list = None,
    enable_prefetch: bool = True
) -> str:
    """设置智能推荐定时任务（预取 + 推送）

    使用此工具为用户设置完整的智能推荐系统：
    1. 预取任务：在推送时间前1小时（11:00, 17:00）生成推荐并存入短期记忆
    2. 推送任务：在指定时间（12:00, 18:00）从短期记忆读取并推送

    预取-推送模式优势：
    - 推送时立即响应，无需等待推荐生成
    - 用户体验更流畅

    系统会自动：
    - 从数据库读取用户的登录信息（cookies）
    - 构建多数据源用户画像（收藏夹/追番/历史/稍后观看/影视）
    - 定期生成个性化推荐
    - 在指定时间推送推荐

    Args:
        session_id: 用户会话 ID
        check_interval_hours: 推荐检查间隔（小时，默认6小时）
        push_times: 推送时间列表，默认["12:00", "18:00"]
        enable_prefetch: 是否启用预取模式（默认True，预取时间会比推送时间提前1小时）

    Returns:
        JSON 字符串，包含任务信息：
        {
            "success": bool,
            "check_task_id": str,
            "prefetch_task_ids": list,
            "push_task_ids": list,
            "message": str
        }
    """
    import asyncio

    async def _setup():
        from app.services.scheduler import get_scheduler_service

        scheduler = get_scheduler_service()

        # 1. 创建推荐检查任务
        check_task_id = await scheduler.add_recommendation_check(
            session_id=session_id,
            interval_minutes=check_interval_hours * 60
        )

        # 2. 创建预取+推送任务
        _push_times = push_times if push_times is not None else ["12:00", "18:00"]

        task_result = await scheduler.add_daily_push_task(
            session_id=session_id,
            push_times=_push_times,
            enable_prefetch=enable_prefetch
        )

        prefetch_times = [f"{int(t.split(':')[0])-1:02d}:00" for t in _push_times]

        return {
            "success": True,
            "check_task_id": check_task_id,
            "prefetch_task_ids": task_result["prefetch_task_ids"],
            "push_task_ids": task_result["push_task_ids"],
            "prefetch_times": prefetch_times,
            "message": f"推荐系统已设置：每{check_interval_hours}小时检查一次，预取时间{', '.join(prefetch_times)}，推送时间{', '.join(_push_times)}"
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_setup())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"success": False, "error": f"设置失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("get_schedule_tasks", parse_docstring=True)
def get_schedule_tasks_tool(
    session_id: str
) -> str:
    """获取用户的所有定时任务

    使用此工具查看用户当前设置的所有定时任务，包括推荐检查和定点推送任务。

    Args:
        session_id: 用户会话 ID

    Returns:
        JSON 字符串，包含任务列表：
        {
            "count": int,
            "tasks": [
                {
                    "id": str,
                    "task_type": str,
                    "schedule_type": str,
                    "next_run_time": str
                }
            ]
        }
    """
    import asyncio

    async def _get_tasks():
        from app.services.scheduler import get_scheduler_service

        scheduler = get_scheduler_service()
        tasks = await scheduler.list_tasks(session_id=session_id)

        return {
            "count": len(tasks),
            "tasks": tasks
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_get_tasks())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"error": f"获取任务失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("remove_schedule_task", parse_docstring=True)
def remove_schedule_task_tool(
    task_id: str
) -> str:
    """删除定时任务

    使用此工具删除指定的定时任务。

    Args:
        task_id: 任务 ID（从 get_schedule_tasks 获取）

    Returns:
        JSON 字符串，包含操作结果：
        {
            "success": bool,
            "message": str
        }
    """
    import asyncio

    async def _remove():
        from app.services.scheduler import get_scheduler_service

        scheduler = get_scheduler_service()
        success = await scheduler.remove_task(task_id)

        return {
            "success": success,
            "message": "任务已删除" if success else "任务不存在"
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_remove())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"success": False, "message": f"删除失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("build_user_profile", parse_docstring=True)
def build_user_profile_tool(
    session_id: str,
    force_rebuild: bool = True
) -> str:
    """构建多数据源用户画像

    使用此工具手动触发用户画像构建。系统会并行采集5个数据源：
    1. 收藏夹（长期兴趣）
    2. 追番列表（番剧偏好）
    3. 观看历史（即时兴趣）
    4. 稍后观看（潜在兴趣）
    5. 影视收藏（影视偏好）

    采集完成后会进行去重、标签提取、权重计算，构建完整的用户画像。

    Args:
        session_id: 用户会话 ID
        force_rebuild: 是否强制重建（默认True）

    Returns:
        JSON 字符串，包含画像信息：
        {
            "success": bool,
            "data_sources": list,
            "total_analyzed": int,
            "primary_interests": list,
            "confidence_score": float,
            "message": str
        }
    """
    import asyncio

    async def _build():
        from app.services.profile.multi_source_profile_builder import get_multi_source_profile_builder
        from app.models import UserSession
        from app.database import async_session_factory
        from sqlalchemy import select as sa_select

        # 获取用户会话信息
        async with async_session_factory() as db:
            result = await db.execute(
                sa_select(UserSession).where(UserSession.session_id == session_id)
            )
            user_session = result.scalar_one_or_none()

        if not user_session:
            return {
                "success": False,
                "error": "用户会话不存在，请先登录"
            }

        # 构建cookies
        cookies = {
            "SESSDATA": user_session.sessdata,
            "bili_jct": user_session.bili_jct,
            "DedeUserID": user_session.dedeuserid
        }

        # 构建画像
        builder = get_multi_source_profile_builder()
        profile = await builder.build_comprehensive_profile(
            session_id=session_id,
            cookies=cookies,
            force_rebuild=force_rebuild
        )

        return {
            "success": True,
            "data_sources": profile.get("data_sources", []),
            "source_counts": profile.get("source_counts", {}),
            "total_analyzed": profile.get("total_analyzed", 0),
            "primary_interests": profile.get("primary_interests", [])[:10],
            "confidence_score": profile.get("confidence_score", 0.0),
            "category_distribution": profile.get("category_distribution", {}),
            "message": f"画像构建完成，分析了{profile.get('total_analyzed', 0)}个内容"
        }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_build())
        finally:
            loop.close()
    except Exception as e:
        return json.dumps(
            {"success": False, "error": f"构建失败: {str(e)}"},
            ensure_ascii=False
        )

    return json.dumps(result, ensure_ascii=False, indent=2)
