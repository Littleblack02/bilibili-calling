"""
Agent基类定义
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from app.services.tools.base import ToolResult
from app.services.memory.manager import MemoryManager
from app.utils.logger import get_logger


class BaseAgent(ABC):
    """所有Agent的基类"""

    name: str = ""  # Agent名称
    description: str = ""  # 描述，供Supervisor判断调用谁

    def __init__(self, memory: MemoryManager, session_id: str):
        """
        初始化Agent

        Args:
            memory: 记忆管理器
            session_id: 会话ID
        """
        self.memory = memory
        self.session_id = session_id
        self.logger = get_logger(f"agent.{self.name.lower()}")

    @abstractmethod
    async def process(self, task: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        处理任务

        Args:
            task: 任务字典
                - task_type: 任务类型
                - params: 任务参数
                - task_id: 任务ID（可选）
            context: 上下文信息
                - session_id: 会话ID
                - user_id: 用户ID（可选）

        Returns:
            ToolResult: 执行结果
        """
        pass

    async def think(self, task: Dict[str, Any], context: Dict[str, Any]) -> str:
        """
        Agent的思考过程（日志记录）

        Args:
            task: 任务字典
            context: 上下文

        Returns:
            str: 思考内容
        """
        thought = f"[{self.name}] 正在处理任务: {task.get('task_type', 'unknown')}"
        params = task.get('params', {})
        if params:
            thought += f" | 参数: {list(params.keys())}"
        return thought

    async def before_process(self, task: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
        """
        处理前钩子

        Args:
            task: 原始任务
            context: 上下文

        Returns:
            处理后的任务
        """
        # 记录思考过程到记忆
        thought = await self.think(task, context)
        await self.memory.remember(
            content=thought,
            memory_type="tool_result",
            importance=1,
            metadata={"agent": self.name, "task_type": task.get("task_type")}
        )
        self.logger.info(thought)

        return task

    async def after_process(
        self,
        result: ToolResult,
        task: Dict[str, Any],
        context: Dict[str, Any]
    ) -> ToolResult:
        """
        处理后钩子

        Args:
            result: 执行结果
            task: 任务
            context: 上下文

        Returns:
            处理后的结果
        """
        # 记录结果到记忆
        if result.success:
            summary = f"[{self.name}] 任务成功: {task.get('task_type')}"
            if result.execution_time_ms:
                summary += f" | 耗时: {result.execution_time_ms}ms"
        else:
            summary = f"[{self.name}] 任务失败: {task.get('task_type')} | 错误: {result.error}"

        await self.memory.remember(
            content=summary,
            memory_type="tool_result",
            importance=2,
            metadata={
                "agent": self.name,
                "task_type": task.get("task_type"),
                "success": result.success
            }
        )

        return result

    async def execute(self, task: Dict[str, Any], context: Dict[str, Any]) -> ToolResult:
        """
        执行任务（包含前后钩子）

        Args:
            task: 任务字典
            context: 上下文

        Returns:
            ToolResult: 执行结果
        """
        # 前处理
        processed_task = await self.before_process(task, context)

        # 执行
        try:
            result = await self.process(processed_task, context)
        except Exception as e:
            self.logger.error(f"Agent {self.name} execution error: {e}")
            result = ToolResult(
                success=False,
                error=str(e),
                source=f"agent_{self.name.lower()}"
            )

        # 后处理
        return await self.after_process(result, processed_task, context)

    def get_info(self) -> Dict[str, Any]:
        """获取Agent信息"""
        return {
            "name": self.name,
            "description": self.description,
            "session_id": self.session_id
        }
