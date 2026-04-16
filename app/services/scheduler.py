"""
任务调度服务（基于APScheduler）
"""
from typing import Dict, Any, Optional, Callable
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime, timedelta
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class SchedulerService:
    """基于APScheduler的任务调度服务"""

    _instance: Optional["SchedulerService"] = None

    def __init__(self):
        if SchedulerService._instance is not None:
            raise RuntimeError("SchedulerService is a singleton. Use get_instance().")

        self.scheduler = AsyncIOScheduler(timezone=settings.scheduler_timezone)
        self.jobs: Dict[str, Dict[str, Any]] = {}  # task_id -> job_info
        logger.info("SchedulerService initialized")

    @classmethod
    def get_instance(cls) -> "SchedulerService":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def start(self):
        """启动调度器"""
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")

    def stop(self):
        """停止调度器"""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def is_running(self) -> bool:
        """检查调度器是否运行中"""
        return self.scheduler.running

    async def add_sync_task(
        self,
        session_id: str,
        folder_ids: list[int],
        schedule_type: str,
        task_id: Optional[str] = None,
        **kwargs
    ) -> str:
        """
        添加收藏夹同步任务

        Args:
            session_id: 会话ID
            folder_ids: 收藏夹ID列表
            schedule_type: 调度类型（hourly/daily/weekly）
            task_id: 任务ID（可选）
            **kwargs: 额外参数

        Returns:
            str: 任务ID
        """
        if task_id is None:
            task_id = f"sync_{session_id}_{schedule_type}_{datetime.utcnow().timestamp()}"

        # 创建触发器
        if schedule_type == "hourly":
            trigger = IntervalTrigger(hours=1)
        elif schedule_type == "daily":
            trigger = IntervalTrigger(days=1)
        elif schedule_type == "weekly":
            trigger = IntervalTrigger(weeks=1)
        else:
            raise ValueError(f"Unknown schedule_type: {schedule_type}")

        # 定义任务函数
        async def sync_job():
            logger.info(f"Running sync task {task_id} for session {session_id}")
            try:
                from app.services.bilibili import BilibiliService
                from app.database import async_session_factory
                from app.models import FavoriteFolder, FavoriteVideo, VideoCache, UserSession
                from sqlalchemy import select

                # 获取用户会话信息
                async with async_session_factory() as db:
                    session_result = await db.execute(
                        select(UserSession).where(UserSession.session_id == session_id)
                    )
                    user_session = session_result.scalar_one_or_none()

                    if not user_session:
                        logger.error(f"User session not found: {session_id}")
                        return

                    if not user_session.bili_mid:
                        logger.warning(f"No Bilibili user ID for session: {session_id}")
                        return

                # 调用B站API同步收藏夹
                async with BilibiliService(
                    sessdata=user_session.sessdata,
                    bili_jct=user_session.bili_jct,
                    dedeuserid=user_session.dedeuserid
                ) as bili:
                    # 获取用户的收藏夹列表
                    favorites = await bili.get_user_favorites(user_session.bili_mid)

                    async with async_session_factory() as db:
                        for folder_id in folder_ids:
                            # 找到对应的收藏夹
                            folder = next((f for f in favorites if f.get('media_id') == folder_id), None)
                            if not folder:
                                logger.warning(f"Folder {folder_id} not found in Bilibili favorites")
                                continue

                            # 获取收藏夹中的所有视频
                            videos = await bili.get_all_favorite_videos(folder_id)

                            logger.info(f"Synced folder {folder.get('title')}: {len(videos)} videos")

                            # 更新数据库
                            for video in videos:
                                bvid = video.get('bvid')

                                # 检查视频是否已存在
                                existing = await db.execute(
                                    select(FavoriteVideo).where(
                                        FavoriteVideo.bvid == bvid,
                                        FavoriteVideo.folder_id == folder_id
                                    )
                                )
                                existing_video = existing.scalar_one_or_none()

                                if not existing_video:
                                    # 添加新视频到数据库
                                    new_video = FavoriteVideo(
                                        folder_id=folder_id,
                                        bvid=bvid,
                                        is_selected=True
                                    )
                                    db.add(new_video)

                                    # 更新或创建 VideoCache 记录
                                    cache_result = await db.execute(
                                        select(VideoCache).where(VideoCache.bvid == bvid)
                                    )
                                    cache_video = cache_result.scalar_one_or_none()

                                    if not cache_video:
                                        new_cache = VideoCache(
                                            bvid=bvid,
                                            title=video.get('title', ''),
                                            description=video.get('description', ''),
                                            owner_name=video.get('owner', {}).get('name', ''),
                                            owner_mid=video.get('owner', {}).get('mid'),
                                            duration=video.get('duration'),
                                            pic_url=video.get('pic', '')
                                        )
                                        db.add(new_cache)

                            # 更新收藏夹同步时间
                            folder_result = await db.execute(
                                select(FavoriteFolder).where(FavoriteFolder.id == folder_id)
                            )
                            folder_record = folder_result.scalar_one_or_none()
                            if folder_record:
                                folder_record.last_sync_at = datetime.utcnow()
                                folder_record.media_count = len(videos)

                            await db.commit()

                logger.info(f"Sync task completed for session {session_id}, folders {folder_ids}")

            except Exception as e:
                logger.error(f"Sync task error for session {session_id}: {e}")
                import traceback
                traceback.print_exc()

        # 添加任务
        self.scheduler.add_job(
            sync_job,
            trigger=trigger,
            id=task_id,
            replace_existing=True
        )

        # 获取任务的下次执行时间（只在调度器运行后有效）
        next_run = None
        if self.scheduler.running:
            sync_job_retrieved = self.scheduler.get_job(task_id)
            if sync_job_retrieved and sync_job_retrieved.next_run_time:
                next_run = sync_job_retrieved.next_run_time.isoformat()

        # 记录任务信息
        self.jobs[task_id] = {
            "session_id": session_id,
            "task_type": "sync_favorites",
            "schedule_type": schedule_type,
            "folder_ids": folder_ids,
            "next_run_time": next_run,
            "created_at": datetime.utcnow().isoformat()
        }

        logger.info(f"Added sync task: {task_id}")
        return task_id

    async def add_recommendation_check(self, session_id: str, interval_minutes: int = 360) -> str:
        """
        添加推荐检查任务（每6小时执行一次，用于更新候选池）

        Args:
            session_id: 会话ID
            interval_minutes: 检查间隔（分钟，默认360分钟=6小时）

        Returns:
            str: 任务ID
        """
        task_id = f"rec_check_{session_id}"

        trigger = IntervalTrigger(minutes=interval_minutes)

        async def check_recommendations():
            logger.info(f"Checking recommendations for session {session_id}")
            try:
                # 实际执行推荐检查
                from app.services.recommendation.recommendation_service import get_recommendation_service
                from app.services.bilibili import BilibiliService

                # 获取推荐服务
                rec_service = get_recommendation_service()

                # 生成新的推荐
                recommendations = await rec_service.generate_recommendations(
                    session_id=session_id,
                    limit=5,
                    save_to_candidates=True
                )

                logger.info(f"Recommendation check completed: {session_id}, found {len(recommendations)} new recommendations")

                # 注：推送逻辑已在recommendation.py中实现
                # 可以通过WebSocket实时推送，或保存到消息队列异步处理

            except Exception as e:
                logger.error(f"Recommendation check failed for session {session_id}: {e}")

        self.scheduler.add_job(
            check_recommendations,
            trigger=trigger,
            id=task_id,
            replace_existing=True
        )

        # 获取任务的下次执行时间（只在调度器运行后有效）
        next_run = None
        if self.scheduler.running:
            check_job = self.scheduler.get_job(task_id)
            if check_job and check_job.next_run_time:
                next_run = check_job.next_run_time.isoformat()

        self.jobs[task_id] = {
            "session_id": session_id,
            "task_type": "check_recommendations",
            "schedule_type": f"interval_{interval_minutes}m",
            "next_run_time": next_run,
            "created_at": datetime.utcnow().isoformat()
        }

        logger.info(f"Added recommendation check task: {task_id} (每{interval_minutes}分钟执行)")
        return task_id

    async def add_daily_push_task(
        self,
        session_id: str,
        push_times: list = None,
        enable_prefetch: bool = True
    ) -> dict:
        """
        添加每日定点推送任务（默认12:00和18:00推送）

        支持预取-推送模式：
        - 预取时间（11:00, 17:00）：提前生成推荐并存入子Agent专用缓存
        - 推送时间（12:00, 18:00）：从子Agent缓存读取并推送

        注意：使用独立的 PrefetchRecommendationCache 表，与主Agent的 ShortTermMemory 分离

        Args:
            session_id: 会话ID
            push_times: 推送时间列表，默认["12:00", "18:00"]
            enable_prefetch: 是否启用预取模式（默认True）

        Returns:
            dict: 包含预取任务ID和推送任务ID的字典
        """
        if push_times is None:
            push_times = ["12:00", "18:00"]

        prefetch_task_ids = []
        push_task_ids = []

        for push_time in push_times:
            # 解析推送时间
            push_hour, push_minute = map(int, push_time.split(':'))

            # 计算预取时间（提前1小时）
            prefetch_hour = push_hour - 1
            prefetch_time = f"{prefetch_hour:02d}:00"

            # 添加预取任务（如果启用）
            if enable_prefetch:
                prefetch_task_id = f"prefetch_{session_id}_{prefetch_hour}"
                prefetch_trigger = CronTrigger(hour=prefetch_hour, minute=0)

                async def prefetch_recommendations():
                    logger.info(f"执行预取任务: {session_id} at {prefetch_time}")
                    try:
                        from app.services.recommendation.recommendation_service import get_recommendation_service
                        from app.models import PrefetchRecommendationCache
                        from app.database import async_session_factory
                        import json as json_module

                        # 生成推荐
                        rec_service = get_recommendation_service()
                        recommendations = await rec_service.generate_recommendations(
                            session_id=session_id,
                            limit=15,
                            save_to_candidates=True
                        )

                        if recommendations:
                            async with async_session_factory() as db:
                                from sqlalchemy import delete

                                # 清除旧的预取缓存（同一推送时间）
                                await db.execute(
                                    delete(PrefetchRecommendationCache).where(
                                        PrefetchRecommendationCache.session_id == session_id,
                                        PrefetchRecommendationCache.target_push_time == push_time
                                    )
                                )

                                # 创建新的预取缓存（使用独立的子Agent缓存表）
                                now = datetime.utcnow()
                                cache = PrefetchRecommendationCache(
                                    session_id=session_id,
                                    target_push_time=push_time,
                                    recommendations=json_module.dumps(recommendations, ensure_ascii=False),
                                    prefetch_hour=prefetch_hour,
                                    count=len(recommendations),
                                    prefetched_at=now,
                                    expires_at=now + timedelta(hours=2),
                                    is_pushed=False
                                )
                                db.add(cache)
                                await db.commit()

                            logger.info(f"预取完成: {session_id} at {prefetch_time}, 保存{len(recommendations)}条推荐到子Agent缓存")
                        else:
                            logger.info(f"预取无结果: {session_id} at {prefetch_time}")

                    except Exception as e:
                        logger.error(f"预取失败: {session_id} at {prefetch_time}: {e}")
                        import traceback
                        traceback.print_exc()

                self.scheduler.add_job(
                    prefetch_recommendations,
                    trigger=prefetch_trigger,
                    id=prefetch_task_id,
                    replace_existing=True
                )

                # 获取任务的下次执行时间（只在调度器运行后有效）
                next_run = None
                if self.scheduler.running:
                    prefetch_job = self.scheduler.get_job(prefetch_task_id)
                    if prefetch_job and prefetch_job.next_run_time:
                        next_run = prefetch_job.next_run_time.isoformat()

                self.jobs[prefetch_task_id] = {
                    "session_id": session_id,
                    "task_type": "prefetch",
                    "schedule_type": f"daily_{prefetch_time}",
                    "target_push_time": push_time,
                    "prefetch_time": prefetch_time,
                    "next_run_time": next_run,
                    "created_at": datetime.utcnow().isoformat()
                }

                prefetch_task_ids.append(prefetch_task_id)
                logger.info(f"添加预取任务: {prefetch_task_id} (每天{prefetch_time}执行，为{push_time}准备)")

            # 添加推送任务
            push_task_id = f"daily_push_{session_id}_{push_hour}_{push_minute}"
            push_trigger = CronTrigger(hour=push_hour, minute=push_minute)

            async def push_recommendations():
                logger.info(f"执行定时推送: {session_id} at {push_time}")
                try:
                    from app.services.recommendation.recommendation_service import get_recommendation_service
                    from app.models import PrefetchRecommendationCache
                    from app.database import async_session_factory
                    from sqlalchemy import select, update
                    import json as json_module

                    recommendations = []
                    source = "realtime"

                    # 尝试从子Agent专用缓存读取预取的推荐
                    if enable_prefetch:
                        async with async_session_factory() as db:
                            result_db = await db.execute(
                                select(PrefetchRecommendationCache).where(
                                    PrefetchRecommendationCache.session_id == session_id,
                                    PrefetchRecommendationCache.target_push_time == push_time
                                )
                            )
                            cache = result_db.scalar_one_or_none()

                            if cache:
                                # 检查是否已过期
                                now = datetime.utcnow()
                                if not cache.expires_at or cache.expires_at > now:
                                    try:
                                        recommendations = json_module.loads(cache.recommendations)
                                        source = "prefetch"
                                        logger.info(f"从子Agent缓存读取{len(recommendations)}条预取推荐")

                                        # 标记为已推送
                                        await db.execute(
                                            update(PrefetchRecommendationCache).where(
                                                PrefetchRecommendationCache.id == cache.id
                                            ).values(
                                                is_pushed=True,
                                                pushed_at=now,
                                                push_source="prefetch"
                                            )
                                        )
                                        await db.commit()
                                    except json_module.JSONDecodeError:
                                        recommendations = []
                                else:
                                    logger.info(f"子Agent缓存已过期: {session_id} at {push_time}")

                    # 如果没有预取数据，实时生成
                    if not recommendations:
                        logger.info(f"无预取数据，实时生成推荐: {session_id}")
                        rec_service = get_recommendation_service()
                        recommendations = await rec_service.generate_recommendations(
                            session_id=session_id,
                            limit=10,
                            save_to_candidates=True
                        )
                        source = "realtime"

                    if recommendations:
                        # 构建推送消息
                        push_message = {
                            "type": "daily_recommendations",
                            "session_id": session_id,
                            "data": {
                                "push_time": push_time,
                                "count": len(recommendations),
                                "recommendations": recommendations[:10],
                                "source": source,
                                "timestamp": datetime.utcnow().isoformat()
                            }
                        }

                        # 通过WebSocket推送
                        try:
                            from app.routers.websocket_manager import manager
                            await manager.send_personal_message(push_message, session_id)
                            logger.info(f"推送成功发送: {session_id}, {len(recommendations)}条推荐 (来源: {source})")
                        except Exception as ws_error:
                            logger.warning(f"WebSocket推送失败: {ws_error}")
                            await self._save_pending_push(session_id, push_message)

                        # 推送成功后删除缓存（短期记忆）
                        try:
                            async with async_session_factory() as db:
                                from sqlalchemy import delete
                                await db.execute(
                                    delete(PrefetchRecommendationCache).where(
                                        PrefetchRecommendationCache.session_id == session_id,
                                        PrefetchRecommendationCache.target_push_time == push_time
                                    )
                                )
                                await db.commit()
                            logger.info(f"已删除预取缓存: {session_id} at {push_time}")
                        except Exception as cache_error:
                            logger.warning(f"删除缓存失败: {cache_error}")

                        logger.info(f"定时推送完成: {session_id} at {push_time}")
                    else:
                        logger.info(f"暂无新推荐: {session_id} at {push_time}")

                except Exception as e:
                    logger.error(f"定时推送失败: {session_id} at {push_time}: {e}")
                    import traceback
                    traceback.print_exc()

            self.scheduler.add_job(
                push_recommendations,
                trigger=push_trigger,
                id=push_task_id,
                replace_existing=True
            )

            # 获取任务的下次执行时间（只在调度器运行后有效）
            next_run = None
            if self.scheduler.running:
                push_job = self.scheduler.get_job(push_task_id)
                if push_job and push_job.next_run_time:
                    next_run = push_job.next_run_time.isoformat()

            self.jobs[push_task_id] = {
                "session_id": session_id,
                "task_type": "daily_push",
                "schedule_type": f"daily_{push_time}",
                "push_time": push_time,
                "prefetch_enabled": enable_prefetch,
                "next_run_time": next_run,
                "created_at": datetime.utcnow().isoformat()
            }

            push_task_ids.append(push_task_id)
            logger.info(f"添加定时推送任务: {push_task_id} (每天{push_time}执行)")

        return {
            "prefetch_task_ids": prefetch_task_ids,
            "push_task_ids": push_task_ids,
            "message": f"已设置{len(prefetch_task_ids)}个预取任务和{len(push_task_ids)}个推送任务"
        }

    async def _save_pending_push(self, session_id: str, message: dict):
        """保存待推送消息"""
        try:
            from app.models import PushHistory
            import json

            async with async_session_factory() as db:
                push_record = PushHistory(
                    session_id=session_id,
                    message_type=message.get("type"),
                    message_content=json.dumps(message, ensure_ascii=False),
                    sent_at=datetime.utcnow(),
                    status="pending"
                )
                db.add(push_record)
                await db.commit()
                logger.info(f"待推送消息已保存: {session_id}")

        except Exception as e:
            logger.error(f"保存待推送消息失败: {e}")

    async def add_auto_collect_task(
        self,
        session_id: str,
        schedule_type: str = "daily",
        limit: int = 5
    ) -> str:
        """
        添加智能投送任务 - 定期分析收藏夹并投送相关视频

        Args:
            session_id: 会话ID
            schedule_type: 调度类型 (daily/weekly)
            limit: 每次投送的视频数量

        Returns:
            str: 任务ID
        """
        task_id = f"auto_collect_{session_id}"

        # 根据调度类型设置触发器
        if schedule_type == "daily":
            # 每天早上9点执行
            trigger = CronTrigger(hour=9, minute=0)
        elif schedule_type == "weekly":
            # 每周一早上9点执行
            trigger = CronTrigger(day_of_week="mon", hour=9, minute=0)
        else:
            raise ValueError(f"Unsupported schedule_type: {schedule_type}")

        async def auto_collect_job():
            """智能投送任务执行函数"""
            logger.info(f"Running auto-collect task for session {session_id}")

            try:
                # 调用智能推荐工具
                from app.deerflow_tools.bilibili_tools import intelligent_recommend_tool

                result_str = intelligent_recommend_tool(session_id=session_id, limit=limit)

                import json
                result = json.loads(result_str)

                if result.get("success"):
                    logger.info(f"Auto-collect completed: added {result.get('added_count', 0)} videos for session {session_id}")
                else:
                    logger.error(f"Auto-collect failed: {result.get('error', 'Unknown error')}")

            except Exception as e:
                logger.error(f"Auto-collect job error for session {session_id}: {e}")

        job = self.scheduler.add_job(
            auto_collect_job,
            trigger=trigger,
            id=task_id,
            replace_existing=True
        )

        self.jobs[task_id] = {
            "session_id": session_id,
            "task_type": "auto_collect",
            "schedule_type": schedule_type,
            "limit": limit,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "created_at": datetime.utcnow().isoformat()
        }

        logger.info(f"Added auto-collect task: {task_id} (schedule: {schedule_type})")
        return task_id

    async def add_cron_task(
        self,
        task_id: str,
        func: Callable,
        cron_expression: str,
        **kwargs
    ) -> str:
        """
        添加Cron任务

        Args:
            task_id: 任务ID
            func: 任务函数
            cron_expression: Cron表达式（如"0 9 * * *"）
            **kwargs: 额外参数

        Returns:
            str: 任务ID
        """
        # 解析cron表达式
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError(f"Invalid cron expression: {cron_expression}")

        trigger = CronTrigger(
            minute=parts[0],
            hour=parts[1],
            day=parts[2],
            month=parts[3],
            day_of_week=parts[4]
        )

        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=task_id,
            replace_existing=True,
            **kwargs
        )

        self.jobs[task_id] = {
            "task_type": "cron",
            "cron_expression": cron_expression,
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
            "created_at": datetime.utcnow().isoformat()
        }

        logger.info(f"Added cron task: {task_id}")
        return task_id

    async def list_tasks(self, session_id: Optional[str] = None) -> list[Dict[str, Any]]:
        """
        列出任务

        Args:
            session_id: 会话ID（可选，过滤指定会话的任务）

        Returns:
            任务列表
        """
        tasks = []

        for job in self.scheduler.get_jobs():
            job_info = self.jobs.get(job.id, {})

            # 过滤
            if session_id and job_info.get("session_id") != session_id:
                continue

            tasks.append({
                "id": job.id,
                "name": job.name,
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                "trigger": str(job.trigger),
                "info": job_info
            })

        return tasks

    async def remove_task(self, task_id: str) -> bool:
        """
        移除任务

        Args:
            task_id: 任务ID

        Returns:
            bool: 是否成功
        """
        try:
            self.scheduler.remove_job(task_id)
            if task_id in self.jobs:
                del self.jobs[task_id]
            logger.info(f"Removed task: {task_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove task {task_id}: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        """暂停任务"""
        try:
            job = self.scheduler.get_job(task_id)
            if job:
                job.pause()
                logger.info(f"Paused task: {task_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to pause task {task_id}: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复任务"""
        try:
            job = self.scheduler.get_job(task_id)
            if job:
                job.resume()
                logger.info(f"Resumed task: {task_id}")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to resume task {task_id}: {e}")
            return False

    async def run_task_now(self, task_id: str) -> bool:
        """立即运行任务"""
        try:
            job = self.scheduler.get_job(task_id)
            if job:
                job.modify(next_run_time=datetime.utcnow())
                logger.info(f"Scheduled task {task_id} to run now")
                return True
            return False
        except Exception as e:
            logger.error(f"Failed to run task {task_id}: {e}")
            return False

    async def add_profile_update_task(self, session_id: str) -> str:
        """
        添加用户画像更新任务（每10天执行一次，更新后删除旧画像）

        Args:
            session_id: 会话ID

        Returns:
            str: 任务ID
        """
        task_id = f"profile_update_{session_id}"

        # 每10天执行一次
        trigger = IntervalTrigger(days=10)

        async def update_profile():
            logger.info(f"执行用户画像更新: {session_id}")
            try:
                from app.services.profile.multi_source_profile_builder import get_multi_source_profile_builder
                from app.models import UserSession
                from app.database import async_session_factory
                from sqlalchemy import select

                # 获取用户 cookies
                cookies = None
                async with async_session_factory() as db:
                    result = await db.execute(
                        select(UserSession).where(UserSession.session_id == session_id)
                    )
                    user_session = result.scalar_one_or_none()

                if user_session:
                    cookies = {
                        "SESSDATA": user_session.sessdata,
                        "bili_jct": user_session.bili_jct,
                        "DedeUserID": user_session.dedeuserid
                    }

                # 构建新画像
                profile_builder = get_multi_source_profile_builder()
                new_profile = await profile_builder.build_comprehensive_profile(
                    session_id=session_id,
                    cookies=cookies,
                    force_rebuild=True
                )

                if new_profile:
                    logger.info(f"用户画像更新成功: {session_id}")
                    # 更新成功后，清理超过10天的旧画像
                    await self.cleanup_old_profiles(session_id, keep_days=10)
                else:
                    logger.warning(f"用户画像更新失败: {session_id}")

            except Exception as e:
                logger.error(f"用户画像更新异常: {session_id}: {e}")
                import traceback
                traceback.print_exc()

        self.scheduler.add_job(
            update_profile,
            trigger=trigger,
            id=task_id,
            replace_existing=True
        )

        # 获取任务的下次执行时间
        next_run = None
        if self.scheduler.running:
            job = self.scheduler.get_job(task_id)
            if job and job.next_run_time:
                next_run = job.next_run_time.isoformat()

        self.jobs[task_id] = {
            "session_id": session_id,
            "task_type": "profile_update",
            "schedule_type": "interval_10days",
            "next_run_time": next_run,
            "created_at": datetime.utcnow().isoformat()
        }

        logger.info(f"添加用户画像更新任务: {task_id} (每10天执行)")
        return task_id

    async def cleanup_old_profiles(self, session_id: str, keep_days: int = 10) -> int:
        """
        清理旧的用户画像记录（删除超过N天的记录）

        每10天由调度器触发，删除旧的 UserInterestProfile 记录。

        Args:
            session_id: 会话ID
            keep_days: 保留天数，默认10天

        Returns:
            int: 删除的记录数
        """
        try:
            from app.models import UserInterestProfile
            from app.database import async_session_factory
            from sqlalchemy import delete
            from datetime import timedelta

            # 计算截止日期：超过10天的记录应该被删除
            cutoff_date = datetime.utcnow() - timedelta(days=keep_days)

            async with async_session_factory() as db:
                # 删除超过10天的旧画像记录
                result = await db.execute(
                    delete(UserInterestProfile).where(
                        UserInterestProfile.session_id == session_id,
                        UserInterestProfile.updated_at < cutoff_date
                    )
                )
                await db.commit()

            deleted_count = result.rowcount if hasattr(result, 'rowcount') else 0
            logger.info(f"清理旧画像: {session_id}, 删除{deleted_count}条超过{keep_days}天的记录")
            return deleted_count

        except Exception as e:
            logger.error(f"清理旧画像失败: {session_id}: {e}")
            return 0


# 全局调度器服务实例
def get_scheduler_service() -> SchedulerService:
    """获取全局调度器服务实例"""
    return SchedulerService.get_instance()


scheduler_service = get_scheduler_service()
