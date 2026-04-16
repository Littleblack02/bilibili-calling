"""
记忆压缩服务

长会话优化：将多条对话压缩为摘要，释放 STM 空间
"""
from typing import List, Dict, Any, Optional
from datetime import datetime
from app.services.memory.base import MemoryEntry
from app.utils.logger import get_logger

logger = get_logger(__name__)


class MemoryCompressor:
    """
    对话历史压缩器

    将多条对话记忆压缩为摘要，避免上下文无限膨胀
    """

    def __init__(self):
        self._llm = None

    @property
    def llm(self):
        """懒加载 LLM"""
        if self._llm is None:
            from langchain_openai import ChatOpenAI
            from app.config import settings
            self._llm = ChatOpenAI(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model=settings.llm_model,
                temperature=0.3
            )
        return self._llm

    async def compress(
        self,
        memories: List[MemoryEntry],
        target_length: int = 3
    ) -> str:
        """
        将多条记忆压缩为摘要

        Args:
            memories: 要压缩的记忆列表
            target_length: 目标摘要条数

        Returns:
            压缩后的摘要文本
        """
        if not memories:
            return ""

        # 按话题分组
        groups = self._group_by_topic(memories)

        summaries = []
        for topic, group_memories in groups.items():
            # 每组生成一个摘要
            summary = await self._summarize_group(group_memories, topic)
            summaries.append(f"【{topic}】{summary}")

        return "\n\n".join(summaries)

    def _group_by_topic(self, memories: List[MemoryEntry]) -> Dict[str, List[MemoryEntry]]:
        """
        按话题分组

        简单策略：根据关键词重叠度分组
        """
        if len(memories) <= 3:
            # 记忆太少，不分组
            return {"会话摘要": memories}

        # 提取关键词
        all_keywords = set()
        memory_keywords = {}
        for mem in memories:
            keywords = self._extract_keywords(mem.content)
            memory_keywords[mem.id] = set(keywords)
            all_keywords.update(keywords)

        # 构建话题聚类（简单贪心算法）
        groups = {}
        assigned = set()

        for mem in memories:
            if mem.id in assigned:
                continue

            # 找到与当前记忆相关的其他记忆
            related = [mem]
            assigned.add(mem.id)

            for other in memories:
                if other.id in assigned:
                    continue

                overlap = self._calc_overlap(
                    memory_keywords[mem.id],
                    memory_keywords[other.id]
                )

                if overlap > 0.3:
                    related.append(other)
                    assigned.add(other.id)

            # 确定话题名称
            topic = self._determine_topic(related)
            groups[topic] = related

        return groups

    async def _summarize_group(self, memories: List[MemoryEntry], topic: str) -> str:
        """对一组记忆生成摘要"""
        # 构建对话文本
        conversation = []
        for mem in memories:
            if mem.memory_type == "conversation":
                conversation.append(f"- {mem.content}")
            else:
                conversation.append(f"[{mem.memory_type}] {mem.content}")

        conversation_text = "\n".join(conversation)

        # LLM 压缩
        prompt = f"""请将以下对话压缩为3句话的摘要。

要求：
1. 保留关键信息（数字、名称、结论）
2. 删除重复和冗余表达
3. 输出格式简洁
4. 总长度控制在100字以内

对话内容：
{conversation_text}

摘要："""

        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate

            chain = ChatPromptTemplate.from_template(prompt) | self.llm | StrOutputParser()
            summary = await chain.ainvoke({})
            return summary.strip()

        except Exception as e:
            logger.warning(f"LLM 压缩失败，降级到简单拼接: {e}")
            # 降级：取前 3 条的摘要
            return "；".join([m.content[:50] for m in memories[:3]])

    def _extract_keywords(self, text: str) -> List[str]:
        """提取关键词"""
        import re

        # 简单策略：提取 2-4 字的中文词和英文词
        chinese_words = re.findall(r'[\u4e00-\u9fa5]{2,4}', text)
        english_words = re.findall(r'[a-zA-Z]{3,10}', text)

        return chinese_words + english_words

    def _calc_overlap(self, set1: set, set2: set) -> float:
        """计算两个集合的重叠率"""
        if not set2:
            return 0.0
        intersection = set1 & set2
        return len(intersection) / len(set2)

    def _determine_topic(self, memories: List[MemoryEntry]) -> str:
        """确定话题名称"""
        # 策略：从第一条记忆提取关键词作为话题
        if not memories:
            return "未知话题"

        first_mem = memories[0]
        keywords = self._extract_keywords(first_mem.content)

        if keywords:
            return keywords[0]
        else:
            # 截取前 8 个字符作为话题
            return first_mem.content[:8]

    async def scheduled_compress(
        self,
        session_id: str,
        target_count: int = 20,
        importance_threshold: int = 3
    ) -> Dict[str, Any]:
        """
        定期压缩任务（可挂到定时器）

        Args:
            session_id: 会话 ID
            target_count: 触发压缩的 STM 条数阈值
            importance_threshold: 只压缩低于此重要性的记忆

        Returns:
            压缩结果
        """
        from app.services.memory.manager import MemoryManager

        manager = MemoryManager(session_id)
        result = await manager.compress_memories(
            target_count=target_count,
            importance_threshold=importance_threshold
        )

        return result
