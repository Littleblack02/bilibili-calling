"""
长期记忆实现（SQLite + ChromaDB 向量检索）

已修复：
1. 使用真实的 DashScope/OpenAI embedding（替换假 MD5 向量）
2. 统一使用 settings.chroma_dir 路径（修复路径不一致）
3. 与 RAG 服务共用同一个 ChromaDB 实例
"""
from typing import List, Optional
from datetime import datetime
from sqlalchemy import select, and_, desc
from app.services.memory.base import BaseMemory, MemoryEntry, MemoryType
from app.models import LongTermMemory as LTMModel
from app.database import async_session_factory as async_session_maker
from app.services.memory.embeddings import get_memory_embeddings
from app.utils.logger import get_logger
import json

logger = get_logger(__name__)


class LongTermMemory(BaseMemory):
    """跨会话长期记忆（SQLite + ChromaDB）"""

    COLLECTION_PREFIX = "memory_"

    def __init__(self, session_id: str):
        super().__init__(session_id)
        self._embedder = None
        self._collection = None

    @property
    def embedder(self):
        """懒加载 embedding 实例"""
        if self._embedder is None:
            self._embedder = get_memory_embeddings()
        return self._embedder

    @property
    def collection(self):
        """懒加载 ChromaDB collection"""
        if self._collection is None:
            collection_name = f"{self.COLLECTION_PREFIX}{self.session_id.replace('-', '_')}"
            self._collection = self.embedder.get_or_create_collection(
                name=collection_name,
                metadata={"hnsw:space": "cosine"}
            )
            logger.debug(f"LongTermMemory: collection 已初始化 {collection_name}")
        return self._collection

    async def remember(
        self,
        content: str,
        memory_type: str = MemoryType.PREFERENCE,
        importance: int = 3,
        tags: List[str] = None,
        metadata: dict = None,
        expires_in_hours: Optional[int] = None
    ) -> MemoryEntry:
        """存储记忆到长期记忆"""
        try:
            async with async_session_maker() as session:
                # 创建数据库记录
                db_memory = LTMModel(
                    session_id=self.session_id,
                    content=content,
                    memory_type=memory_type,
                    importance=importance,
                    tags=tags or [],
                    extra_data=metadata or {},
                    created_at=datetime.utcnow()
                )

                session.add(db_memory)
                await session.commit()
                await session.refresh(db_memory)

                # 添加到向量数据库（使用真实 embedding）
                if self.collection:
                    try:
                        # 使用真实的语义向量
                        embedding = self.embedder.embed_query(content)
                        vector_id = str(db_memory.id)

                        self.collection.add(
                            ids=[vector_id],
                            embeddings=[embedding],
                            documents=[content],
                            metadatas=[{
                                "memory_id": db_memory.id,
                                "memory_type": memory_type,
                                "importance": importance,
                                "tags": json.dumps(tags or []),
                                "created_at": db_memory.created_at.isoformat()
                            }]
                        )

                        # 更新 vector_id
                        db_memory.vector_id = vector_id
                        await session.commit()
                        logger.debug(f"LongTermMemory: 已存入向量库 id={db_memory.id}")

                    except Exception as e:
                        logger.error(f"LongTermMemory: 存入向量库失败: {e}")

                return self._db_to_entry(db_memory)

        except Exception as e:
            logger.error(f"LongTermMemory: 存储失败: {e}")
            raise

    async def recall(
        self,
        query: str,
        limit: int = 5,
        memory_type: Optional[str] = None
    ) -> List[MemoryEntry]:
        """从长期记忆中检索（向量相似度匹配）"""
        try:
            async with async_session_maker() as session:
                # 优先使用向量检索
                if self.collection and query and query.strip():
                    try:
                        query_embedding = self.embedder.embed_query(query)

                        where_clause = {}
                        if memory_type:
                            where_clause["memory_type"] = memory_type

                        results = self.collection.query(
                            query_embeddings=[query_embedding],
                            n_results=limit,
                            where=where_clause if where_clause else None
                        )

                        if results and results.get('ids') and results['ids'][0]:
                            memory_ids = [int(id_) for id_ in results['ids'][0]]

                            stmt = (
                                select(LTMModel)
                                .where(
                                    and_(
                                        LTMModel.id.in_(memory_ids),
                                        LTMModel.session_id == self.session_id
                                    )
                                )
                            )
                            db_result = await session.execute(stmt)
                            memories = db_result.scalars().all()

                            memories_dict = {m.id: m for m in memories}
                            sorted_memories = [
                                memories_dict[mid] for mid in memory_ids if mid in memories_dict
                            ]

                            for mem in sorted_memories:
                                await self.update_access(mem.id)

                            return [self._db_to_entry(m) for m in sorted_memories]

                    except Exception as e:
                        logger.warning(f"LongTermMemory: 向量检索失败，降级到文本匹配: {e}")

                # 降级：SQLite LIKE 文本匹配
                conditions = [LTMModel.session_id == self.session_id]

                if query and query.strip():
                    conditions.append(LTMModel.content.contains(query))

                if memory_type:
                    conditions.append(LTMModel.memory_type == memory_type)

                stmt = (
                    select(LTMModel)
                    .where(and_(*conditions))
                    .order_by(desc(LTMModel.importance), desc(LTMModel.access_count))
                    .limit(limit)
                )

                result = await session.execute(stmt)
                memories = result.scalars().all()

                for mem in memories:
                    await self.update_access(mem.id)

                return [self._db_to_entry(m) for m in memories]

        except Exception as e:
            logger.error(f"LongTermMemory: 检索失败: {e}")
            return []

    async def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """获取最近的记忆"""
        try:
            async with async_session_maker() as session:
                stmt = (
                    select(LTMModel)
                    .where(LTMModel.session_id == self.session_id)
                    .order_by(desc(LTMModel.created_at))
                    .limit(limit)
                )

                result = await session.execute(stmt)
                memories = result.scalars().all()
                return [self._db_to_entry(m) for m in memories]

        except Exception as e:
            logger.error(f"LongTermMemory: 获取最近记忆失败: {e}")
            return []

    async def update_access(self, memory_id: int) -> None:
        """更新访问统计"""
        try:
            async with async_session_maker() as session:
                stmt = select(LTMModel).where(
                    and_(
                        LTMModel.id == memory_id,
                        LTMModel.session_id == self.session_id
                    )
                )
                result = await session.execute(stmt)
                memory = result.scalar_one_or_none()

                if memory:
                    memory.access_count += 1
                    memory.last_accessed = datetime.utcnow()
                    await session.commit()

        except Exception as e:
            logger.error(f"LongTermMemory: 更新访问统计失败: {e}")

    async def delete(self, memory_id: int) -> bool:
        """删除记忆"""
        try:
            async with async_session_maker() as session:
                stmt = select(LTMModel).where(
                    and_(
                        LTMModel.id == memory_id,
                        LTMModel.session_id == self.session_id
                    )
                )
                result = await session.execute(stmt)
                memory = result.scalar_one_or_none()

                if memory:
                    # 从 ChromaDB 删除
                    if self.collection and memory.vector_id:
                        try:
                            self.collection.delete(ids=[memory.vector_id])
                        except Exception as e:
                            logger.error(f"LongTermMemory: 从向量库删除失败: {e}")

                    await session.delete(memory)
                    await session.commit()
                    return True

                return False

        except Exception as e:
            logger.error(f"LongTermMemory: 删除失败: {e}")
            return False

    async def clear(self) -> int:
        """清空所有记忆"""
        try:
            async with async_session_maker() as session:
                stmt = select(LTMModel).where(
                    LTMModel.session_id == self.session_id
                )
                result = await session.execute(stmt)
                memories = result.scalars().all()
                count = len(memories)

                # 从 ChromaDB 删除
                if self.collection:
                    try:
                        vector_ids = [m.vector_id for m in memories if m.vector_id]
                        if vector_ids:
                            self.collection.delete(ids=vector_ids)
                    except Exception as e:
                        logger.error(f"LongTermMemory: 清空向量库失败: {e}")

                for memory in memories:
                    await session.delete(memory)

                await session.commit()
                return count

        except Exception as e:
            logger.error(f"LongTermMemory: 清空失败: {e}")
            return 0

    def _db_to_entry(self, db_memory: LTMModel) -> MemoryEntry:
        """数据库模型转换为 MemoryEntry"""
        return MemoryEntry(
            id=db_memory.id,
            session_id=db_memory.session_id,
            content=db_memory.content,
            memory_type=db_memory.memory_type,
            importance=db_memory.importance,
            tags=db_memory.tags or [],
            extra_data=db_memory.extra_data or {},
            created_at=db_memory.created_at,
            access_count=db_memory.access_count,
            last_accessed=db_memory.last_accessed
        )
