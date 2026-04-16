"""
记忆系统基类
"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
from datetime import datetime, timedelta
from enum import Enum


class MemoryType(str, Enum):
    """记忆类型"""
    CONVERSATION = "conversation"
    PREFERENCE = "preference"
    FACT = "fact"
    TOOL_RESULT = "tool_result"
    INTEREST = "interest"


class MemoryEntry(BaseModel):
    """记忆条目"""
    id: Optional[int] = None
    session_id: str
    content: str
    memory_type: str  # conversation / preference / fact / tool_result / interest
    importance: int = 1  # 1-5, >=3 自动持久化到长期记忆
    tags: List[str] = []
    extra_data: Dict[str, Any] = {}  # 与 SQLAlchemy LongTermMemory.extra_data 保持一致
    created_at: datetime = None
    expires_at: Optional[datetime] = None
    access_count: int = 0
    last_accessed: Optional[datetime] = None

    class Config:
        arbitrary_types_allowed = True

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "content": self.content,
            "memory_type": self.memory_type,
            "importance": self.importance,
            "tags": self.tags,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None
        }


class BaseMemory(ABC):
    """记忆系统基类"""

    def __init__(self, session_id: str):
        self.session_id = session_id

    @abstractmethod
    async def remember(
        self,
        content: str,
        memory_type: str = MemoryType.CONVERSATION,
        importance: int = 1,
        tags: List[str] = None,
        metadata: Dict[str, Any] = None,
        expires_in_hours: Optional[int] = None
    ) -> MemoryEntry:
        """
        存储记忆

        Args:
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要性（1-5）
            tags: 标签列表
            metadata: 额外元数据
            expires_in_hours: 过期时间（小时），None表示不过期

        Returns:
            MemoryEntry: 创建的记忆条目
        """
        pass

    @abstractmethod
    async def recall(
        self,
        query: str,
        limit: int = 5,
        memory_type: Optional[str] = None
    ) -> List[MemoryEntry]:
        """
        检索记忆

        Args:
            query: 查询内容
            limit: 返回数量限制
            memory_type: 记忆类型过滤

        Returns:
            List[MemoryEntry]: 相关记忆列表
        """
        pass

    @abstractmethod
    async def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """获取最近的记忆"""
        pass

    @abstractmethod
    async def update_access(self, memory_id: int) -> None:
        """更新访问次数和时间"""
        pass

    @abstractmethod
    async def delete(self, memory_id: int) -> bool:
        """删除记忆"""
        pass

    @abstractmethod
    async def clear(self) -> int:
        """清空所有记忆，返回删除数量"""
        pass

    def _calculate_expiration(self, hours: Optional[int]) -> Optional[datetime]:
        """计算过期时间"""
        if hours is None:
            return None
        return datetime.utcnow() + timedelta(hours=hours)

    def _should_promote_to_long_term(self, importance: int) -> bool:
        """判断是否应该提升到长期记忆"""
        return importance >= 3
