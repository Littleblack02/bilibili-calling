"""
记忆管理器（统一接口）

已集成：
1. 智能晋���机制（多维度评分）
2. 遗忘机制（基于访问频率和时间）
3. 记忆压缩（长会话优化）
4. 跨会话迁移（全局知识库）
"""
from typing import List, Optional, Dict, Any
from datetime import datetime
from app.services.memory.base import MemoryEntry, MemoryType
from app.services.memory.short_term import ShortTermMemory as STM
from app.services.memory.long_term import LongTermMemory as LTM
from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryManager:
    """
    记忆管理器 - 提供统一的记忆系统接口

    分层策略：
    - 所有记忆先存入短期记忆（STM）
    - 智能评分决定是否晋升到长期记忆（LTM）
    - 检索时先查STM，再查LTM，合并去重
    - 遗忘机制定期清理过期/低价值记忆
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.stm = STM(session_id)
        self.ltm = LTM(session_id)
        self.promotion_threshold = settings.long_term_memory_threshold

        # 延迟导入智能晋升和遗忘模块
        self._promotion_scorer = None
        self._forgetting_policy = None

    @property
    def promotion_scorer(self):
        if self._promotion_scorer is None:
            from app.services.memory.promotion_criteria import PromotionScorer
            self._promotion_scorer = PromotionScorer()
        return self._promotion_scorer

    @property
    def forgetting_policy(self):
        if self._forgetting_policy is None:
            from app.services.memory.forgetting import ForgettingPolicy
            self._forgetting_policy = ForgettingPolicy()
        return self._forgetting_policy

    async def remember(
        self,
        content: str,
        memory_type: str = MemoryType.CONVERSATION,
        importance: int = 1,
        tags: List[str] = None,
        metadata: Dict[str, Any] = None,
        expires_in_hours: Optional[int] = None,
        enable_smart_promotion: bool = True
    ) -> MemoryEntry:
        """
        存储记忆（智能分层）

        Args:
            content: 记忆内容
            memory_type: 记忆类型
            importance: 重要性（1-5）
            tags: 标签
            metadata: 额外元数据
            expires_in_hours: 过期时间
            enable_smart_promotion: 是否启用智能晋升

        Returns:
            MemoryEntry: 存储的记忆条目
        """
        # 先存入短期记忆
        entry = await self.stm.remember(
            content=content,
            memory_type=memory_type,
            importance=importance,
            tags=tags,
            metadata=metadata,
            expires_in_hours=expires_in_hours
        )

        # 智能晋升判断
        if enable_smart_promotion:
            try:
                # 使用多维度评分
                score_result = self.promotion_scorer.score(entry)

                if score_result["should_promote"]:
                    await self.ltm.remember(
                        content=content,
                        memory_type=memory_type,
                        importance=importance,
                        tags=tags,
                        metadata=metadata,
                        expires_in_hours=None  # 长期记忆不过期
                    )
                    logger.debug(
                        f"智能晋升: memory_id={entry.id}, "
                        f"score={score_result['total_score']:.1f}, "
                        f"reasons={score_result['reasons']}"
                    )
                else:
                    logger.debug(
                        f"未达晋升阈值: memory_id={entry.id}, "
                        f"score={score_result['total_score']:.1f}"
                    )

            except Exception as e:
                # 降级到简单阈值判断
                logger.warning(f"智能晋升失败，降级到阈值判断: {e}")
                if importance >= self.promotion_threshold:
                    await self.ltm.remember(
                        content=content,
                        memory_type=memory_type,
                        importance=importance,
                        tags=tags,
                        metadata=metadata,
                        expires_in_hours=None
                    )

        return entry

    async def recall(
        self,
        query: str,
        limit: int = 5,
        memory_type: Optional[str] = None
    ) -> List[MemoryEntry]:
        """
        检索记忆（STM + LTM）

        Args:
            query: 查询内容
            limit: 返回数量限制
            memory_type: 记忆类型过滤

        Returns:
            List[MemoryEntry]: 相关记忆列表（STM和LTM合并）
        """
        # 并行检索STM和LTM
        import asyncio

        stm_limit = limit // 2 + 1  # STM占一半多一点
        ltm_limit = limit // 2  # LTM占一半

        stm_task = self.stm.recall(query, limit=stm_limit, memory_type=memory_type)
        ltm_task = self.ltm.recall(query, limit=ltm_limit, memory_type=memory_type)

        stm_results, ltm_results = await asyncio.gather(
            stm_task,
            ltm_task,
            return_exceptions=True
        )

        stm_memories = stm_results if not isinstance(stm_results, Exception) else []
        ltm_memories = ltm_results if not isinstance(ltm_results, Exception) else []

        # 合并去重（按内容）
        seen_contents = set()
        combined = []

        for memory in stm_memories + ltm_memories:
            content_key = memory.content[:100]  # 用前100字符作为去重键
            if content_key not in seen_contents:
                seen_contents.add(content_key)
                combined.append(memory)

        # 按重要性和时间排序
        combined.sort(key=lambda m: (m.importance, m.created_at or datetime.min), reverse=True)

        return combined[:limit]

    async def get_recent(self, limit: int = 10) -> List[MemoryEntry]:
        """获取最近的记忆（STM优先）"""
        stm_recent = await self.stm.get_recent(limit)

        if len(stm_recent) >= limit:
            return stm_recent[:limit]

        # STM不够，从LTM补充
        ltm_limit = limit - len(stm_recent)
        ltm_recent = await self.ltm.get_recent(ltm_limit)

        return stm_recent + ltm_recent

    async def get_context(self, query: Optional[str] = None, max_tokens: int = 2000) -> str:
        """
        获取上下文摘要（用于LLM prompt注入）

        Args:
            query: 相关查询（可选）
            max_tokens: 最大token数估算

        Returns:
            str: 上下文文本
        """
        memories = []
        if query:
            memories = await self.recall(query, limit=10)
        else:
            memories = await self.get_recent(limit=10)

        if not memories:
            return "无相关记忆"

        # 构建上下文
        context_parts = []
        total_length = 0

        for memory in memories:
            part = f"[{memory.memory_type}] {memory.content}"
            if total_length + len(part) > max_tokens:
                break
            context_parts.append(part)
            total_length += len(part)

        return "\n".join(context_parts)

    async def get_user_profile(self) -> Dict[str, Any]:
        """
        获取用户画像（从长期记忆中提取偏好和兴趣）

        Returns:
            用户画像字典
        """
        try:
            # 获取偏好类记忆
            preference_memories = await self.ltm.recall(
                query="",
                limit=50,
                memory_type=MemoryType.PREFERENCE
            )

            # 获取兴趣类记忆
            interest_memories = await self.ltm.recall(
                query="",
                limit=50,
                memory_type=MemoryType.INTEREST
            )

            # 简单提取（实际应该更复杂）
            interests = {}
            for mem in interest_memories:
                for tag in mem.tags:
                    interests[tag] = interests.get(tag, 0) + mem.importance

            preferences = [m.content for m in preference_memories[:5]]

            return {
                "session_id": self.session_id,
                "interests": dict(sorted(interests.items(), key=lambda x: x[1], reverse=True)[:10]),
                "preferences": preferences,
                "total_memories": len(preference_memories) + len(interest_memories)
            }

        except Exception as e:
            logger.error(f"Failed to get user profile: {e}")
            return {
                "session_id": self.session_id,
                "interests": {},
                "preferences": [],
                "total_memories": 0
            }

    async def cleanup_expired(self) -> Dict[str, int]:
        """清理过期的短期记忆"""
        try:
            stm_count = await self.stm.cleanup_expired()
            return {"stm_cleaned": stm_count}
        except Exception as e:
            logger.error(f"Failed to cleanup: {e}")
            return {"stm_cleaned": 0}

    async def apply_forgetting_policy(
        self,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        应用遗忘策略清理长期记忆

        Args:
            dry_run: True 则只评估不删除

        Returns:
            清理结果统计
        """
        from app.services.memory.forgetting import MemoryForgettingService

        service = MemoryForgettingService(forgetting_policy=self.forgetting_policy)
        return await service.cleanup_session(self.session_id, dry_run=dry_run)

    async def compress_memories(
        self,
        target_count: int = 20,
        importance_threshold: int = 3
    ) -> Dict[str, Any]:
        """
        压缩短期记忆（长会话优化）

        将多条对话压缩为摘要，释放 STM 空间

        Args:
            target_count: 触发压缩的 STM 条数阈值
            importance_threshold: 只压缩低于此重要性的记忆

        Returns:
            压缩结果
        """
        from app.services.memory.compressor import MemoryCompressor

        # 获取所有 STM 记忆
        all_stm = await self.stm.get_recent(limit=target_count * 2)

        if len(all_stm) < target_count:
            return {"compressed": False, "reason": "STM 条数不足"}

        # 过滤低重要性记忆
        to_compress = [m for m in all_stm if m.importance < importance_threshold]

        if len(to_compress) < 10:
            return {"compressed": False, "reason": "低重要性记忆不足"}

        try:
            compressor = MemoryCompressor()
            summary = await compressor.compress(to_compress)

            # 删除原始记忆，存入压缩后的摘要
            deleted_count = 0
            for mem in to_compress:
                if await self.stm.delete(mem.id):
                    deleted_count += 1

            # 存入压缩摘要（高 importance，确保不被遗忘）
            await self.stm.remember(
                content=summary,
                memory_type=MemoryType.CONVERSATION,
                importance=4,
                tags=["压缩摘要", "会话总结"]
            )

            logger.info(
                f"记忆压缩: session={self.session_id}, "
                f"原始={len(to_compress)}, 删除={deleted_count}"
            )

            return {
                "compressed": True,
                "original_count": len(to_compress),
                "deleted_count": deleted_count,
                "summary_length": len(summary)
            }

        except Exception as e:
            logger.error(f"记忆压缩失败: {e}")
            return {"compressed": False, "error": str(e)}

    async def extract_global_knowledge(self) -> Dict[str, Any]:
        """
        提取跨会话全局知识

        从当前 session 的 LTM 中识别重复出现的知识，迁移到全局知识库

        Returns:
            迁移结果
        """
        from app.services.memory.knowledge_migration import KnowledgeMigrator

        try:
            migrator = KnowledgeMigrator()
            result = await migrator.extract_from_session(self.session_id)

            logger.info(
                f"知识迁移: session={self.session_id}, "
                f"提取={result.get('extracted', 0)}, "
                f"迁移={result.get('migrated', 0)}"
            )

            return result

        except Exception as e:
            logger.error(f"知识迁移失败: {e}")
            return {"error": str(e)}

    async def enrich_context_with_global_knowledge(
        self,
        query: str
    ) -> str:
        """
        回答时补充全局知识

        Args:
            query: 用户查询

        Returns:
            增强后的上下文（包含全局知识）
        """
        from app.services.memory.knowledge_migration import KnowledgeMigrator

        try:
            migrator = KnowledgeMigrator()

            # 查询全局知识库
            global_knowledge = await migrator.search_global_knowledge(query, limit=3)

            # 查询当前 session 记忆
            session_memory = await self.recall(query, limit=5)

            # 合并，标注来源
            return self._format_enhanced_context(global_knowledge, session_memory)

        except Exception as e:
            logger.error(f"全局知识增强失败: {e}")
            # 降级到普通上下文
            return await self.get_context(query=query)

    def _format_enhanced_context(
        self,
        global_knowledge: List[Dict[str, Any]],
        session_memory: List[MemoryEntry]
    ) -> str:
        """格式化增强上下文"""
        parts = []

        if global_knowledge:
            parts.append("[全局知识]")
            for gk in global_knowledge:
                parts.append(f"- {gk['content_summary'] or gk['content']}")

        if session_memory:
            parts.append("[当前会话]")
            for mem in session_memory:
                parts.append(f"- {mem.content}")

        return "\n".join(parts) if parts else "无相关记忆"

    async def delete(self, memory_id: int, memory_type: str = "short") -> bool:
        """删除指定记忆"""
        try:
            if memory_type == "short":
                return await self.stm.delete(memory_id)
            else:
                return await self.ltm.delete(memory_id)
        except Exception as e:
            logger.error(f"Failed to delete memory: {e}")
            return False

    async def clear(self, memory_type: Optional[str] = None) -> int:
        """清空记忆"""
        try:
            count = 0
            if memory_type is None or memory_type == "short":
                count += await self.stm.clear()
            if memory_type is None or memory_type == "long":
                count += await self.ltm.clear()
            return count
        except Exception as e:
            logger.error(f"Failed to clear memories: {e}")
            return 0
