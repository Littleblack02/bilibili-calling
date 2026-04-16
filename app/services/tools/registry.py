"""
工具注册中心
"""
from typing import Dict, List, Optional, Type
from app.services.tools.base import BaseTool, ToolError
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册中心，按Agent类型分组管理"""

    _instance: Optional["ToolRegistry"] = None

    def __init__(self):
        if ToolRegistry._instance is not None:
            raise RuntimeError("ToolRegistry is a singleton. Use get_instance().")

        self._tools: Dict[str, Dict[str, BaseTool]] = {}  # agent_type -> {tool_name -> tool_instance}
        self._tool_classes: Dict[str, Type[BaseTool]] = {}  # tool_name -> tool_class
        logger.info("ToolRegistry initialized")

    @classmethod
    def get_instance(cls) -> "ToolRegistry":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, tool: BaseTool) -> None:
        """
        注册工具

        Args:
            tool: 工具实例
        """
        agent_type = tool.agent_type
        tool_name = tool.name

        if not agent_type:
            raise ToolError(f"Tool {tool_name} must have an agent_type")

        if agent_type not in self._tools:
            self._tools[agent_type] = {}

        self._tools[agent_type][tool_name] = tool
        self._tool_classes[tool_name] = tool.__class__

        logger.info(f"Registered tool: {tool_name} (agent: {agent_type})")

    def register_class(self, tool_class: Type[BaseTool]) -> None:
        """
        注册工��类（延迟实例化）

        Args:
            tool_class: 工具类
        """
        tool_name = tool_class.name
        agent_type = tool_class.agent_type

        if not tool_name:
            raise ToolError(f"Tool class must have a name")

        if not agent_type:
            raise ToolError(f"Tool {tool_name} must have an agent_type")

        # 保存类引用
        self._tool_classes[tool_name] = tool_class

        # 按Agent类型分组
        if agent_type not in self._tools:
            self._tools[agent_type] = {}

        # 创建临时实例用于获取元数据
        temp_instance = tool_class()
        self._tools[agent_type][tool_name] = temp_instance

        logger.info(f"Registered tool class: {tool_name} (agent: {agent_type})")

    def get_tools_by_agent(self, agent_type: str) -> List[BaseTool]:
        """
        获取指定Agent的所有工具

        Args:
            agent_type: Agent类型

        Returns:
            工具列表
        """
        return list(self._tools.get(agent_type, {}).values())

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """
        获取指定名称的工具

        Args:
            name: 工具名称

        Returns:
            工具实例或None
        """
        for agent_tools in self._tools.values():
            if name in agent_tools:
                return agent_tools[name]
        return None

    def get_all_tools(self) -> Dict[str, List[BaseTool]]:
        """获取所有工具（按Agent类型分组）"""
        return self._tools

    def get_all_tool_names(self) -> List[str]:
        """获取所有工具名称"""
        return list(self._tool_classes.keys())

    def get_tool_schemas_for_agent(self, agent_type: str) -> List[Dict]:
        """
        获取指定Agent的工具Schema（用于LLM Function Calling）

        Args:
            agent_type: Agent类型

        Returns:
            工具Schema列表
        """
        tools = self.get_tools_by_agent(agent_type)
        schemas = []

        for tool in tools:
            schemas.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters
            })

        return schemas

    def has_tool(self, name: str) -> bool:
        """检查工具是否存在"""
        return name in self._tool_classes

    def get_agent_types(self) -> List[str]:
        """获取所有Agent类型"""
        return list(self._tools.keys())

    def list_tools_by_agent(self) -> Dict[str, List[str]]:
        """列出每个Agent的工具名称"""
        result = {}
        for agent_type, tools in self._tools.items():
            result[agent_type] = list(tools.keys())
        return result


# 全局工具注册中心实例
tool_registry = ToolRegistry.get_instance()
