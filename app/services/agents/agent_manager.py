"""
Agent管理器 - 简化版，仅保留 SupervisorAgent 作为 DeerFlow 降级兜底
"""
from typing import Optional
from app.services.agents.base import BaseAgent
from app.services.agents.supervisor import SupervisorAgent
from app.services.memory.manager import MemoryManager
from app.utils.logger import get_logger

logger = get_logger(__name__)


class AgentManager:
    """
    Agent 管理器（简化版）

    职责：
    1. 仅管理 SupervisorAgent
    2. 作为 DeerFlow 的降级兜底

    注意：DeerFlow 是主系统，此处仅在 DeerFlow 不可用时作为备选
    """

    _instance: Optional["AgentManager"] = None

    def __init__(self):
        if AgentManager._instance is not None:
            raise RuntimeError("AgentManager is a singleton. Use get_instance().")

        logger.info("AgentManager initialized (simplified, Supervisor only)")

    @classmethod
    def get_instance(cls) -> "AgentManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_supervisor(
        self,
        session_id: str,
        memory: Optional[MemoryManager] = None
    ) -> SupervisorAgent:
        """获取 SupervisorAgent 实例"""
        if memory is None:
            memory = MemoryManager(session_id)
        return SupervisorAgent(
            memory=memory,
            session_id=session_id,
            agent_manager=None  # 降级模式不需要 agent_manager 循环引用
        )

    def list_agents(self) -> list[str]:
        """列出所有可用的 Agent 类型"""
        return ["Supervisor"]

    def get_agent_info(self, agent_type: str) -> dict:
        """获取 Agent 信息"""
        if agent_type == "Supervisor":
            return {
                "name": "Supervisor",
                "description": "主控 Agent，负责意图分析 + 多轮对话记忆注入 + 结果汇总"
            }
        return {}

    def get_all_agents_info(self) -> dict:
        """获取所有 Agent 信息"""
        return {"Supervisor": self.get_agent_info("Supervisor")}


# 全局单例
_agent_manager_instance: Optional[AgentManager] = None


def get_agent_manager() -> AgentManager:
    """获取全局 Agent 管理器实例"""
    global _agent_manager_instance
    if _agent_manager_instance is None:
        _agent_manager_instance = AgentManager()
    return _agent_manager_instance
