"""
Agents包初始化 - 简化版，仅包含 SupervisorAgent + AgentManager
"""
from app.services.agents.agent_manager import AgentManager, get_agent_manager
from app.services.agents.base import BaseAgent
from app.services.agents.supervisor import SupervisorAgent

__all__ = [
    "AgentManager",
    "get_agent_manager",
    "BaseAgent",
    "SupervisorAgent",
]
