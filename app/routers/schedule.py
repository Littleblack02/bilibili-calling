from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from app.services.scheduler import scheduler_service
from app.utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/schedule", tags=["Schedule"])


class CreateSyncTaskRequest(BaseModel):
    """创建同步任务请求"""
    session_id: str
    folder_ids: List[int]
    schedule_type: str  # hourly/daily/weekly


class CreateRecTaskRequest(BaseModel):
    """创建推荐检查任务请求"""
    session_id: str
    interval_minutes: int = 360  # 默认6小时


class CreateAutoCollectRequest(BaseModel):
    """创建自动投送任务请求"""
    session_id: str
    schedule_type: str = "daily"  # daily/weekly
    limit: int = 5  # 每次投送的视频数量


class CreateDailyPushRequest(BaseModel):
    """创建每日定点推送任务请求"""
    session_id: str
    push_times: list = ["12:00", "18:00"]  # 推送时间列表


@router.post("/tasks/sync")
async def create_sync_task(request: CreateSyncTaskRequest):
    """创建收藏夹同步任务"""
    try:
        task_id = await scheduler_service.add_sync_task(
            session_id=request.session_id,
            folder_ids=request.folder_ids,
            schedule_type=request.schedule_type
        )

        return {
            "success": True,
            "task_id": task_id,
            "message": "同步任务已创建"
        }

    except Exception as e:
        logger.error(f"Create sync task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/recommendation")
async def create_recommendation_task(request: CreateRecTaskRequest):
    """创建推荐检查任务"""
    try:
        task_id = await scheduler_service.add_recommendation_check(
            session_id=request.session_id,
            interval_minutes=request.interval_minutes
        )

        return {
            "success": True,
            "task_id": task_id,
            "message": "推荐检查任务已创建"
        }

    except Exception as e:
        logger.error(f"Create recommendation task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/auto-collect")
async def create_auto_collect_task(request: CreateAutoCollectRequest):
    """创建智能投送任务 - 定期分析收藏夹并投送相关视频"""
    try:
        task_id = await scheduler_service.add_auto_collect_task(
            session_id=request.session_id,
            schedule_type=request.schedule_type,
            limit=request.limit
        )

        return {
            "success": True,
            "task_id": task_id,
            "message": f"智能投送任务已创建，将按{request.schedule_type}频率自动投送相关视频"
        }

    except Exception as e:
        logger.error(f"Create auto-collect task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/daily-push")
async def create_daily_push_task(request: CreateDailyPushRequest):
    """创建每日定点推送任务 - 在指定时间点推送推荐"""
    try:
        task_ids = await scheduler_service.add_daily_push_task(
            session_id=request.session_id,
            push_times=request.push_times
        )

        return {
            "success": True,
            "task_ids": task_ids,
            "message": f"每日推送任务已创建，将在{', '.join(request.push_times)}推送推荐",
            "count": len(task_ids)
        }

    except Exception as e:
        logger.error(f"Create daily push task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/tasks/{session_id}")
async def list_tasks(session_id: str):
    """列出任务"""
    try:
        tasks = await scheduler_service.list_tasks(session_id=session_id)

        return {
            "success": True,
            "tasks": tasks,
            "count": len(tasks)
        }

    except Exception as e:
        logger.error(f"List tasks error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/tasks/{task_id}")
async def remove_task(task_id: str):
    """删除任务"""
    try:
        success = await scheduler_service.remove_task(task_id)

        return {
            "success": success,
            "message": "任务已删除" if success else "任务不存在"
        }

    except Exception as e:
        logger.error(f"Remove task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/pause")
async def pause_task(task_id: str):
    """暂停任务"""
    try:
        success = await scheduler_service.pause_task(task_id)

        return {
            "success": success,
            "message": "任务已暂停" if success else "任务不存在"
        }

    except Exception as e:
        logger.error(f"Pause task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/resume")
async def resume_task(task_id: str):
    """恢复任务"""
    try:
        success = await scheduler_service.resume_task(task_id)

        return {
            "success": success,
            "message": "任务已恢复" if success else "任务不存在"
        }

    except Exception as e:
        logger.error(f"Resume task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/tasks/{task_id}/run")
async def run_task_now(task_id: str):
    """立即运行任务"""
    try:
        success = await scheduler_service.run_task_now(task_id)

        return {
            "success": success,
            "message": "任务已触发执行" if success else "任务不存在"
        }

    except Exception as e:
        logger.error(f"Run task error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
