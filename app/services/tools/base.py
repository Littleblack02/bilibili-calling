"""
工具基类定义
"""
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from pydantic import BaseModel
from enum import Enum


class ToolExecutionStatus(str, Enum):
    """工具执行状态"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    ERROR = "error"


class ToolResult(BaseModel):
    """工具执行结果"""
    success: bool
    data: Any = None
    error: Optional[str] = None
    source: str = "unknown"  # 标记数据来源
    execution_time_ms: Optional[int] = None
    metadata: Dict[str, Any] = {}

    class Config:
        arbitrary_types_allowed = True

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "source": self.source,
            "execution_time_ms": self.execution_time_ms,
            "metadata": self.metadata
        }


class BaseTool(ABC):
    """所有工具的基类"""

    name: str = ""  # 工具名称
    description: str = ""  # 工具描述，供LLM理解
    agent_type: str = ""  # 所属Agent类型 (rag/bilibili/account/recommendation/web)
    parameters: Dict = {}  # 参数Schema (JSON Schema格式)

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """
        执行工具

        Args:
            **kwargs: 工具参数

        Returns:
            ToolResult: 执行结果
        """
        pass

    async def validate_parameters(self, params: Dict) -> bool:
        """
        验证参数（可选实现）

        Args:
            params: 参数字典

        Returns:
            bool: 是否有效
        """
        # 基本验证：检查必需参数
        required_params = self.parameters.get("required", [])
        for param in required_params:
            if param not in params:
                return False
        return True

    async def before_execute(self, params: Dict) -> Dict:
        """
        执行前钩子（可选实现）

        Args:
            params: 原始参数

        Returns:
            处理后的参数
        """
        return params

    async def after_execute(self, result: ToolResult) -> ToolResult:
        """
        执行后钩子（可选实现）

        Args:
            result: 执行结果

        Returns:
            处理后的结果
        """
        return result


class ToolError(Exception):
    """工具执行异常"""

    def __init__(self, message: str, tool_name: str = "", original_error: Exception = None):
        self.message = message
        self.tool_name = tool_name
        self.original_error = original_error
        super().__init__(self.message)
