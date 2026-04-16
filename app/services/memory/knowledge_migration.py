"""
跨会话知识迁移

从多会话记忆中提取通用知识，迁移到全局知识库
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from sqlalchemy import select, and_, func, or_
from app.models import GlobalKnowledge
from app.services.memory.base import MemoryEntry, MemoryType
from app.database import async_session_factory as async_session_maker
from app.services.memory.embeddings import get_memory_embeddings
from app.services.memory.long_term import LongTermMemory
from app.utils.logger import get_logger
import json

logger = get_logger(__name__)


class KnowledgeMigrator:
    """
    知识迁移器

    从单个或多个 session 的 LTM 中识别重复出现的知识，
    提取核心内容，迁移到全局知识库供所有会话共享
    """

    GLOBAL_KNOWLEDGE_COLLECTION = "global_knowledge"

    def __init__(self):
        self._embedder = None

    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_memory_embeddings()
        return self._embedder

    async def extract_from_session(
        self,
        session_id: str,
        min_occurrences: int = 2
    ) -> Dict[str, Any]:
        """
        从单个 session 的 LTM 中提取知识

        Args:
            session_id: 会话 ID
            min_occurrences: 最少出现次数

        Returns:
            提取结果
        """
        try:
            # 获取该 session 的所�� LTM 记忆
            ltm = LongTermMemory(session_id)
            all_memories = await ltm.get_recent(limit=1000)

            if not all_memories:
                return {"extracted": 0, "migrated": 0, "reason": "LTM 为空"}

            # 提取候选知识（fact / preference / interest 类型）
            candidates = [
                m for m in all_memories
                if m.memory_type in ["fact", "preference", "interest"]
                and m.importance >= 3
            ]

            if not candidates:
                return {"extracted": 0, "migrated": 0, "reason": "无候选知识"}

            # 按内容相似度聚类（简化：基于关键词重叠）
            clusters = self._cluster_by_similarity(candidates)

            # 对每个聚类，如果出现次数 >= min_occurrences，则迁移
            migrated = 0
            for cluster_id, cluster_memories in clusters.items():
                if len(cluster_memories) >= min_occurrences:
                    # 提取核心内容
                    core_content = await self._extract_core_content(cluster_memories)

                    # 存入全局知识库
                    await self._save_to_global_knowledge(
                        content=core_content["content"],
                        content_summary=core_content["summary"],
                        source_type=cluster_memories[0].memory_type,
                        source_sessions=[session_id],
                        confidence=1.0,  # 单 session，置信度设为 1.0
                        tags=cluster_memories[0].tags,
                        importance=cluster_memories[0].importance
                    )
                    migrated += 1

            logger.info(
                f"知识迁移: session={session_id}, "
                f"候选={len(candidates)}, 聚类={len(clusters)}, "
                f"迁移={migrated}"
            )

            return {
                "extracted": len(candidates),
                "migrated": migrated,
                "clusters": len(clusters)
            }

        except Exception as e:
            logger.error(f"知识迁移失败: {e}")
            return {"error": str(e)}

    async def extract_from_multi_sessions(
        self,
        session_ids: List[str],
        min_occurrences: int = 2
    ) -> Dict[str, Any]:
        """
        从多个 session 中提取跨会话通用知识

        Args:
            session_ids: 会话 ID 列表
            min_occurrences: 最少出现的 session 数量

        Returns:
            提取结果
        """
        try:
            # 收集所有 session 的 LTM 记忆
            all_memories = []
            for sid in session_ids:
                ltm = LongTermMemory(sid)
                memories = await ltm.get_recent(limit=500)
                for mem in memories:
                    mem.session_id = sid  # 标记来源
                all_memories.extend(memories)

            if not all_memories:
                return {"extracted": 0, "migrated": 0, "reason": "无 LTM 记忆"}

            # 聚类（跨 session）
            clusters = self._cluster_by_similarity(all_memories)

            migrated = 0
            for cluster_id, cluster_memories in clusters.items():
                # 统计不同 session 数量
                unique_sessions = set(m.session_id for m in cluster_memories)

                if len(unique_sessions) >= min_occurrences:
                    core_content = await self._extract_core_content(cluster_memories)

                    await self._save_to_global_knowledge(
                        content=core_content["content"],
                        content_summary=core_content["summary"],
                        source_type=cluster_memories[0].memory_type,
                        source_sessions=list(unique_sessions),
                        confidence=len(unique_sessions) / len(session_ids),
                        tags=cluster_memories[0].tags,
                        importance=cluster_memories[0].importance
                    )
                    migrated += 1

            return {
                "extracted": len(all_memories),
                "migrated": migrated,
                "clusters": len(clusters)
            }

        except Exception as e:
            logger.error(f"跨会话知识迁移失败: {e}")
            return {"error": str(e)}

    def _cluster_by_similarity(self, memories: List[MemoryEntry]) -> Dict[int, List[MemoryEntry]]:
        """
        按内容相似度聚类

        简化策略：基于关键词重叠度
        """
        clusters = {}
        cluster_id = 0

        for mem in memories:
            # 提取关键词
            keywords = set(self._extract_keywords(mem.content))

            # 查找相似聚类
            found_cluster = None
            for cid, cluster_memories in clusters.items():
                for cluster_mem in cluster_memories:
                    cluster_keywords = set(self._extract_keywords(cluster_mem.content))
                    overlap = self._calc_overlap(keywords, cluster_keywords)

                    if overlap > 0.5:
                        found_cluster = cid
                        break
                if found_cluster is not None:
                    break

            if found_cluster is not None:
                clusters[found_cluster].append(mem)
            else:
                clusters[cluster_id] = [mem]
                cluster_id += 1

        return clusters

    async def _extract_core_content(self, memories: List[MemoryEntry]) -> Dict[str, str]:
        """
        从一组相似记忆中提取核心内容

        Returns:
            {"content": str, "summary": str}
        """
        # 简单策略：选择最长且 importance 最高的内容
        best_mem = max(memories, key=lambda m: (m.importance, len(m.content)))

        # 生成摘要（可选，用 LLM）
        summary = await self._summarize_content(best_mem.content)

        return {
            "content": best_mem.content,
            "summary": summary
        }

    async def _summarize_content(self, content: str) -> str:
        """用 LLM 生成内容摘要"""
        try:
            from langchain_openai import ChatOpenAI
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate
            from app.config import settings

            llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.llm_model,
                temperature=0.3
            )

            prompt = ChatPromptTemplate.from_template(
                "请用一句话总结以下内容的核心要点（不超过30字）：\n\n{content}"
            )
            chain = prompt | llm | StrOutputParser()

            summary = await chain.ainvoke({"content": content[:500]})
            return summary.strip()

        except Exception as e:
            logger.warning(f"LLM 摘要失败: {e}")
            return content[:50]

    async def _save_to_global_knowledge(
        self,
        content: str,
        content_summary: str,
        source_type: str,
        source_sessions: List[str],
        confidence: float,
        tags: List[str],
        importance: int
    ):
        """保存到全局知识库"""
        async with async_session_maker() as session:
            # 检查是否已存在
            existing = await session.execute(
                select(GlobalKnowledge).where(
                    and_(
                        GlobalKnowledge.content == content,
                        GlobalKnowledge.source_type == source_type
                    )
                )
            )
            existing_item = existing.scalar_one_or_none()

            if existing_item:
                # 更新现有记录
                existing_item.source_count += 1
                existing_item.confidence = max(existing_item.confidence, confidence)
                existing_item.updated_at = datetime.utcnow()
            else:
                # 创建新记录
                new_knowledge = GlobalKnowledge(
                    content=content,
                    content_summary=content_summary,
                    source_type=source_type,
                    source_sessions=source_sessions,
                    source_count=len(source_sessions),
                    confidence=confidence,
                    tags=tags,
                    importance=importance,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow()
                )
                session.add(new_knowledge)

                # 添加到向量库
                try:
                    collection = self.embedder.get_or_create_collection(
                        name=self.GLOBAL_KNOWLEDGE_COLLECTION
                    )
                    embedding = self.embedder.embed_query(content)

                    # 暂时用 session.commit() 后获取 ID
                    await session.flush()
                    vector_id = f"global_{new_knowledge.id}"

                    collection.add(
                        ids=[vector_id],
                        embeddings=[embedding],
                        documents=[content],
                        metadatas=[{
                            "knowledge_id": new_knowledge.id,
                            "source_type": source_type,
                            "confidence": confidence,
                            "tags": json.dumps(tags or [])
                        }]
                    )

                    new_knowledge.vector_id = vector_id

                except Exception as e:
                    logger.error(f"全局知识向量存储失败: {e}")

            await session.commit()

    async def search_global_knowledge(
        self,
        query: str,
        limit: int = 5,
        source_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        搜索全局知识库

        Returns:
            知识列表，每个元素为 {"content": str, "summary": str, "confidence": float, ...}
        """
        try:
            # 向量检索
            collection = self.embedder.get_or_create_collection(self.GLOBAL_KNOWLEDGE_COLLECTION)
            query_embedding = self.embedder.embed_query(query)

            where_clause = {"source_type": source_type} if source_type else None

            results = collection.query(
                query_embeddings=[query_embedding],
                n_results=limit,
                where=where_clause
            )

            if not results or not results.get("ids"):
                return []

            # 从数据库获取完整记录
            async with async_session_maker() as session:
                knowledge_ids = [
                    int(id_.replace("global_", ""))
                    for id_ in results["ids"][0]
                ]

                stmt = select(GlobalKnowledge).where(
                    and_(
                        GlobalKnowledge.id.in_(knowledge_ids),
                        GlobalKnowledge.is_active == True
                    )
                )
                db_results = await session.execute(stmt)
                knowledge_items = db_results.scalars().all()

                # 构建返回结果
                knowledge_dict = {k.id: k for k in knowledge_items}
                ordered = []
                for kid in knowledge_ids:
                    if kid in knowledge_dict:
                        k = knowledge_dict[kid]
                        ordered.append({
                            "id": k.id,
                            "content": k.content,
                            "summary": k.content_summary,
                            "source_type": k.source_type,
                            "confidence": k.confidence,
                            "tags": k.tags,
                            "importance": k.importance
                        })

                return ordered

        except Exception as e:
            logger.error(f"全局知识检索失败: {e}")
            return []

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        import re
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        english_words = re.findall(r'[a-zA-Z]{3,10}', text)
        return chinese_words + english_words

    def _calc_overlap(self, set1: set, set2: set) -> float:
        """计算重叠率"""
        if not set2:
            return 0.0
        intersection = set1 & set2
        return len(intersection) / len(set2)
