"""
账号控制相关工具实现
"""
import time
from typing import List, Optional
from app.services.tools.base import BaseTool, ToolResult
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OrganizeFavoritesTool(BaseTool):
    """整理收藏夹工具"""

    name = "organize_favorites"
    description = "自动整理B站收藏夹，支持按关键词、时长、UP主等条件分类整理，可预览或实际执行。"
    agent_type = "account"
    parameters = {
        "type": "object",
        "properties": {
            "folder_id": {
                "type": "integer",
                "description": "要整理的收藏夹ID"
            },
            "mode": {
                "type": "string",
                "enum": ["auto", "keyword", "duration", "uploader"],
                "description": "整理模式：auto=自动分析, keyword=按关键词, duration=按时长, uploader=按UP主",
                "default": "auto"
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "description": "关键词列表（keyword模式使用）",
                "default": []
            },
            "dry_run": {
                "type": "boolean",
                "description": "是否只预览不实际执行",
                "default": True
            },
            "target_folder_id": {
                "type": "integer",
                "description": "目标收藏夹ID（移动模式使用）"
            }
        },
        "required": ["folder_id"]
    }

    async def execute(
        self,
        folder_id: int,
        mode: str = "auto",
        keywords: List[str] = None,
        dry_run: bool = True,
        target_folder_id: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        try:
            # 调用AccountAgent的实际整理逻辑
            from app.services.agents.account_agent import AccountAgent
            from app.services.memory.manager import MemoryManager

            # 创建AccountAgent实例
            session_id = kwargs.get("session_id", "default_session")
            memory = MemoryManager(session_id=session_id)
            account_agent = AccountAgent(memory=memory, session_id=session_id)

            # 调用Agent的整理方法
            params = {
                "folder_id": folder_id,
                "mode": mode,
                "dry_run": dry_run,
                "target_folder_id": target_folder_id,
                "keywords": keywords or []
            }

            result = await account_agent._organize_favorites(params)

            execution_time = int((time.time() - start_time) * 1000)
            result.execution_time_ms = execution_time
            return result

        except Exception as e:
            logger.error(f"OrganizeFavoritesTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="account_organize_favorites",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class ScheduleSyncTool(BaseTool):
    """定时同步工具"""

    name = "schedule_sync"
    description = "设置或取消收藏夹定时同步任务，支持按小时、天、周等周期自动同步收藏夹。"
    agent_type = "account"
    parameters = {
        "type": "object",
        "properties": {
            "folder_ids": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "要同步的收藏夹ID列表"
            },
            "schedule_type": {
                "type": "string",
                "enum": ["hourly", "daily", "weekly"],
                "description": "同步周期：hourly=每小时, daily=每天, weekly=每周"
            },
            "action": {
                "type": "string",
                "enum": ["create", "cancel", "list"],
                "description": "操作类型：create=创建任务, cancel=取消任务, list=列出任务",
                "default": "create"
            },
            "task_id": {
                "type": "integer",
                "description": "任务ID（cancel操作需要）"
            }
        },
        "required": ["action"]
    }

    async def execute(
        self,
        action: str,
        folder_ids: List[int] = None,
        schedule_type: str = "daily",
        task_id: Optional[int] = None,
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        try:
            # 调用AccountAgent的实际调度逻辑
            from app.services.agents.account_agent import AccountAgent
            from app.services.memory.manager import MemoryManager

            # 创建AccountAgent实例
            session_id = kwargs.get("session_id", "default_session")
            memory = MemoryManager(session_id=session_id)
            account_agent = AccountAgent(memory=memory, session_id=session_id)

            # 调用Agent的调度方法
            params = {
                "action": action,
                "folder_ids": folder_ids or [],
                "schedule_type": schedule_type,
                "task_id": task_id
            }

            result = await account_agent._schedule_sync(params)

            execution_time = int((time.time() - start_time) * 1000)
            result.execution_time_ms = execution_time
            return result

        except Exception as e:
            logger.error(f"ScheduleSyncTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="account_schedule_sync",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )


class GetFavoritesTool(BaseTool):
    """获取收藏夹信息工具"""

    name = "get_favorites"
    description = "获取用户的收藏夹列表和详细信息。"
    agent_type = "account"
    parameters = {
        "type": "object",
        "properties": {
            "folder_id": {
                "type": "integer",
                "description": "收藏夹ID（可选，不提供则返回所有收藏夹）"
            }
        },
        "required": []
    }

    async def execute(self, folder_id: Optional[int] = None, **kwargs) -> ToolResult:
        start_time = time.time()
        try:
            # 调用AccountAgent的实际获取收藏夹逻辑
            from app.services.agents.account_agent import AccountAgent
            from app.services.memory.manager import MemoryManager

            # 创建AccountAgent实例
            session_id = kwargs.get("session_id", "default_session")
            memory = MemoryManager(session_id=session_id)
            account_agent = AccountAgent(memory=memory, session_id=session_id)

            # 调用Agent的获取收藏夹方法
            params = {
                "folder_id": folder_id,
                "session_id": session_id
            }

            result = await account_agent._get_favorites(params)

            execution_time = int((time.time() - start_time) * 1000)
            result.execution_time_ms = execution_time
            return result

        except Exception as e:
            logger.error(f"GetFavoritesTool error: {e}")
            return ToolResult(
                success=False,
                error=str(e),
                source="account_get_favorites",
                execution_time_ms=int((time.time() - start_time) * 1000)
            )
