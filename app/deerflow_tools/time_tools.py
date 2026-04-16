import json
from datetime import datetime, timedelta
from typing import Optional
from langchain.tools import tool


# 推送时间点（实际推送时间）
PUSH_HOURS = [12, 18]
# 预取时间点（提前1小时检索视频）
PREFETCH_HOURS = [11, 17]


@tool("get_current_time", parse_docstring=True)
def get_current_time_tool(
    format: str = "%H:%M"
) -> str:
    """获取当前时间

    使用此工具获取当前系统时间，用于时间相关的判断和操作。

    Args:
        format: 时间格式，默认"%H:%M"返回如"12:00"格式

    Returns:
        JSON字符串，包含当前时间信息：
        {
            "current_time": "12:00",
            "current_datetime": "2026-04-13 12:00:00",
            "hour": 12,
            "minute": 0,
            "is_push_time": true,
            "is_prefetch_time": false,
            "message": "现在是12:00，是推送推荐的时间"
        }
    """
    now = datetime.now()

    current_hour = now.hour
    is_push_time = current_hour in PUSH_HOURS
    is_prefetch_time = current_hour in PREFETCH_HOURS

    result = {
        "current_time": now.strftime("%H:%M"),
        "current_datetime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "hour": current_hour,
        "minute": now.minute,
        "is_push_time": is_push_time,
        "is_prefetch_time": is_prefetch_time,
        "push_times": PUSH_HOURS,
        "prefetch_times": PREFETCH_HOURS,
        "message": f"现在是{now.strftime('%H:%M')}"
    }

    if is_push_time:
        if current_hour == 12:
            result["message"] = "现在是12:00，是午餐时间，适宜推送推荐视频"
        elif current_hour == 18:
            result["message"] = "现在是18:00，是下班时间，适宜推送推荐视频"
        result["recommendation_triggered"] = True
    elif is_prefetch_time:
        if current_hour == 11:
            result["message"] = "现在是11:00，是午餐前预取时间，请开始检索推荐视频并存入缓存"
        elif current_hour == 17:
            result["message"] = "现在是17:00，是下班前预取时间，请开始检索推荐视频并存入缓存"
        result["prefetch_triggered"] = True
    else:
        next_push = "12:00" if current_hour < 12 else "18:00"
        next_prefetch = "11:00" if current_hour < 11 else "17:00"
        if current_hour >= 18:
            next_push = "明天12:00"
            next_prefetch = "明天11:00"
        result["message"] += f"，下次推送时间: {next_push}，下次预取时间: {next_prefetch}"
        result["recommendation_triggered"] = False
        result["prefetch_triggered"] = False

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("check_recommendation_needed", parse_docstring=True)
def check_recommendation_needed_tool(
    session_id: str
) -> str:
    """检查是否需要推送推荐或预取推荐

    检查当前时间是否是推送时间点或预取时间点，并返回相关信息。
    - 预取时间（11:00, 17:00）：需要检索视频并存入缓存
    - 推送时间（12:00, 18:00）：需要从缓存读取推荐并推送

    Args:
        session_id: 用户会话ID

    Returns:
        JSON字符串，包含检查结果：
        {
            "should_push": true/false,
            "should_prefetch": true/false,
            "current_time": "12:00",
            "message": "现在是推送时间，应该从缓存读取推荐并推送"
        }
    """
    now = datetime.now()
    current_hour = now.hour

    should_push = current_hour in PUSH_HOURS
    should_prefetch = current_hour in PREFETCH_HOURS

    result = {
        "should_push": should_push,
        "should_prefetch": should_prefetch,
        "current_time": now.strftime("%H:%M"),
        "hour": current_hour,
        "session_id": session_id,
        "push_times": PUSH_HOURS,
        "prefetch_times": PREFETCH_HOURS,
        "message": ""
    }

    if should_push:
        time_label = "中午" if current_hour == 12 else "傍晚"
        result["message"] = f"现在是{time_label}推送时间（{current_hour}:00），应该从子Agent缓存读取预取的视频推荐并推送给用户"
        result["action"] = "push"
    elif should_prefetch:
        time_label = "上午" if current_hour == 11 else "下午"
        result["message"] = f"现在是{time_label}预取时间（{current_hour}:00），应该基于用户画像检索推荐视频并存入子Agent专用缓存，等待推送时间发送"
        result["action"] = "prefetch"
    else:
        # 计算下次时间和类型
        if current_hour < 11:
            next_time = "11:00"
            next_action = "预取"
        elif current_hour < 12:
            next_time = "12:00"
            next_action = "推送"
        elif current_hour < 17:
            next_time = "17:00"
            next_action = "预取"
        elif current_hour < 18:
            next_time = "18:00"
            next_action = "推送"
        else:
            next_time = "明天11:00"
            next_action = "预取"
        result["message"] = f"现在不是关键时间点，下次{next_action}时间: {next_time}"
        result["action"] = "none"

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("save_prefetch_recommendations", parse_docstring=True)
def save_prefetch_recommendations_tool(
    session_id: str,
    recommendations: str
) -> str:
    """保存预取的推荐视频到子Agent专用缓存

    在预取时间点，子Agent检索到推荐视频后，使用此工具将结果存入专用缓存。
    存入后会被标记为未推送状态，等推送时间到达时主Agent通知子Agent读取并推送。
    此缓存与主Agent的 ShortTermMemory 完全独立，互不影响。

    Args:
        session_id: 用户会话ID
        recommendations: 推荐视频列表的JSON字符串

    Returns:
        JSON字符串，包含保存结果：
        success: 是否保存成功
        count: 保存的推荐数量
        target_push_time: 目标推送时间
        message: 操作结果描述
    """
    import asyncio

    async def _save():
        from app.models import PrefetchRecommendationCache
        from app.database import async_session_factory

        try:
            recs = json.loads(recommendations)
            if not isinstance(recs, list):
                return {
                    "success": False,
                    "error": "recommendations 应该是视频列表"
                }

            now = datetime.now()
            # 确定是午餐预取还是下班预取
            target_push_time = "12:00" if now.hour == 11 else "18:00"

            async with async_session_factory() as db:
                # 使用 upsert：先删除旧记录，再插入新记录
                from sqlalchemy import delete, select

                # 删除该会话该推送时间的旧缓存
                await db.execute(
                    delete(PrefetchRecommendationCache).where(
                        PrefetchRecommendationCache.session_id == session_id,
                        PrefetchRecommendationCache.target_push_time == target_push_time
                    )
                )

                # 创建新的缓存记录
                cache = PrefetchRecommendationCache(
                    session_id=session_id,
                    target_push_time=target_push_time,
                    recommendations=json.dumps(recs, ensure_ascii=False),
                    prefetch_hour=now.hour,
                    count=len(recs),
                    prefetched_at=now,
                    expires_at=now + timedelta(hours=2),
                    is_pushed=False
                )
                db.add(cache)
                await db.commit()

            return {
                "success": True,
                "count": len(recs),
                "target_push_time": target_push_time,
                "prefetch_hour": now.hour,
                "expires_at": (now + timedelta(hours=2)).isoformat(),
                "message": f"已保存{len(recs)}条推荐到子Agent专用缓存，将在{target_push_time}推送时间发送给用户"
            }

        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"JSON解析失败: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"保存失败: {str(e)}"
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_save())
        finally:
            loop.close()
    except Exception as e:
        result = {"success": False, "error": str(e)}

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("get_prefetch_recommendations", parse_docstring=True)
def get_prefetch_recommendations_tool(
    session_id: str,
    target_push_time: str = None
) -> str:
    """从子Agent专用缓存读取预取的推荐视频

    在推送时间点，主Agent通知子Agent使用此工具读取之前预存的推荐视频，然后进行推送操作。
    此缓存与主Agent的 ShortTermMemory 完全独立，互不影响。

    Args:
        session_id: 用户会话ID
        target_push_time: 目标推送时间，可选，默认自动判断当前时间应该读取哪个时间点的预取

    Returns:
        JSON字符串，包含预取的推荐列表：
        success: 是否成功
        count: 推荐数量
        recommendations: 推荐列表
        is_pushed: 是否已推送
        message: 操作结果描述
    """
    import asyncio

    async def _get():
        from app.models import PrefetchRecommendationCache
        from app.database import async_session_factory
        from sqlalchemy import select

        try:
            now = datetime.now()

            # 如果未指定推送时间，根据当前小时判断
            if target_push_time is None:
                if now.hour == 12:
                    target_push_time = "12:00"
                elif now.hour == 18:
                    target_push_time = "18:00"
                else:
                    return {
                        "success": False,
                        "error": f"当前时间 {now.hour}:00 不是推送时间点"
                    }

            async with async_session_factory() as db:
                # 查询该会话的预取缓存
                result_db = await db.execute(
                    select(PrefetchRecommendationCache).where(
                        PrefetchRecommendationCache.session_id == session_id,
                        PrefetchRecommendationCache.target_push_time == target_push_time
                    )
                )
                cache = result_db.scalar_one_or_none()

            if not cache:
                return {
                    "success": True,
                    "count": 0,
                    "recommendations": [],
                    "is_pushed": False,
                    "message": f"未找到{target_push_time}的预取缓存，可能尚未执行预取或已过期"
                }

            # 检查是否已过期
            if cache.expires_at and now > cache.expires_at:
                return {
                    "success": True,
                    "count": 0,
                    "recommendations": [],
                    "is_expired": True,
                    "message": f"{target_push_time}的预取缓存已过期，需要重新生成推荐"
                }

            # 解析推荐内容
            try:
                recommendations = json.loads(cache.recommendations)
            except json.JSONDecodeError:
                recommendations = []

            return {
                "success": True,
                "count": len(recommendations),
                "target_push_time": target_push_time,
                "recommendations": recommendations,
                "is_pushed": cache.is_pushed,
                "prefetched_at": cache.prefetched_at.isoformat() if cache.prefetched_at else None,
                "message": f"已读取{len(recommendations)}条预取推荐，可以进行推送"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"读取失败: {str(e)}"
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_get())
        finally:
            loop.close()
    except Exception as e:
        result = {"success": False, "error": str(e)}

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("mark_prefetch_as_pushed", parse_docstring=True)
def mark_prefetch_as_pushed_tool(
    session_id: str,
    target_push_time: str = None
) -> str:
    """标记预取缓存为已推送状态

    在推送完成后调用此工具，将缓存标记为已推送状态，避免重复推送。

    Args:
        session_id: 用户会话ID
        target_push_time: 目标推送时间，可选，默认自动判断当前时间

    Returns:
        JSON字符串，包含操作结果：
        success: 是否成功
        target_push_time: 推送时间
        pushed_at: 推送时间戳
        message: 操作结果描述
    """
    import asyncio

    async def _mark():
        from app.models import PrefetchRecommendationCache
        from app.database import async_session_factory
        from sqlalchemy import update

        try:
            now = datetime.now()

            if target_push_time is None:
                if now.hour == 12:
                    target_push_time = "12:00"
                elif now.hour == 18:
                    target_push_time = "18:00"

            if not target_push_time:
                return {
                    "success": False,
                    "error": "无法确定推送时间"
                }

            async with async_session_factory() as db:
                await db.execute(
                    update(PrefetchRecommendationCache).where(
                        PrefetchRecommendationCache.session_id == session_id,
                        PrefetchRecommendationCache.target_push_time == target_push_time
                    ).values(
                        is_pushed=True,
                        pushed_at=now
                    )
                )
                await db.commit()

            return {
                "success": True,
                "target_push_time": target_push_time,
                "pushed_at": now.isoformat(),
                "message": f"{target_push_time}的预取缓存已标记为已推送"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"标记失败: {str(e)}"
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_mark())
        finally:
            loop.close()
    except Exception as e:
        result = {"success": False, "error": str(e)}

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("clear_prefetch_cache", parse_docstring=True)
def clear_prefetch_cache_tool(
    session_id: str,
    target_push_time: str = None
) -> str:
    """清除预取缓存（子Agent专用）

    清除指定会话的预取推荐缓存，通常在推送完成后或需要重新生成时调用。
    此操作只影响子Agent的 PrefetchRecommendationCache 缓存，不会影响主Agent的 ShortTermMemory。

    Args:
        session_id: 用户会话ID
        target_push_time: 可选，只清除指定推送时间的缓存

    Returns:
        JSON字符串，包含清除结果：
        success: 是否成功
        target_push_time: 推送时间
        message: 操作结果描述
    """
    import asyncio

    async def _clear():
        from app.models import PrefetchRecommendationCache
        from app.database import async_session_factory
        from sqlalchemy import delete

        try:
            async with async_session_factory() as db:
                query = delete(PrefetchRecommendationCache).where(
                    PrefetchRecommendationCache.session_id == session_id
                )
                if target_push_time:
                    query = query.where(
                        PrefetchRecommendationCache.target_push_time == target_push_time
                    )
                await db.execute(query)
                await db.commit()

            return {
                "success": True,
                "target_push_time": target_push_time,
                "message": "子Agent预取缓存已清除"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"清除失败: {str(e)}"
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_clear())
        finally:
            loop.close()
    except Exception as e:
        result = {"success": False, "error": str(e)}

    return json.dumps(result, ensure_ascii=False, indent=2)


@tool("get_prefetch_cache_status", parse_docstring=True)
def get_prefetch_cache_status_tool(
    session_id: str
) -> str:
    """获取预取缓存状态

    查看当前会话的预取缓存情况，包括各推送时间的缓存状态。

    Args:
        session_id: 用户会话ID

    Returns:
        JSON字符串，包含缓存状态：
        success: 是否成功
        session_id: 会话ID
        cache_status: 各推送时间的缓存状态
        message: 操作结果描述
    """
    import asyncio

    async def _get_status():
        from app.models import PrefetchRecommendationCache
        from app.database import async_session_factory
        from sqlalchemy import select

        try:
            async with async_session_factory() as db:
                result_db = await db.execute(
                    select(PrefetchRecommendationCache).where(
                        PrefetchRecommendationCache.session_id == session_id
                    )
                )
                caches = result_db.scalars().all()

            cache_status = {
                "12:00": {"exists": False, "count": 0, "is_pushed": False, "prefetched_at": None},
                "18:00": {"exists": False, "count": 0, "is_pushed": False, "prefetched_at": None}
            }

            for cache in caches:
                if cache.target_push_time in cache_status:
                    cache_status[cache.target_push_time] = {
                        "exists": True,
                        "count": cache.count,
                        "is_pushed": cache.is_pushed,
                        "prefetched_at": cache.prefetched_at.isoformat() if cache.prefetched_at else None,
                        "expires_at": cache.expires_at.isoformat() if cache.expires_at else None
                    }

            return {
                "success": True,
                "session_id": session_id,
                "cache_status": cache_status,
                "message": "缓存状态查询成功"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"查询失败: {str(e)}"
            }

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_get_status())
        finally:
            loop.close()
    except Exception as e:
        result = {"success": False, "error": str(e)}

    return json.dumps(result, ensure_ascii=False, indent=2)
