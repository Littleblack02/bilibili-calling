"""
智能晋升策略

多维度评分决定记忆是否晋升到 LTM：
1. 基础重要性分数
2. 信息密度（实体词数量）
3. 时效性调整
4. 工具结果复用价值
5. 对话连续性
"""
from typing import List, Dict, Any, Optional
import re
from app.services.memory.base import MemoryEntry, MemoryType
from app.utils.logger import get_logger

logger = get_logger(__name__)


class PromotionScorer:
    """
    智能晋升评分器

    评分维度：
    - 基础分：importance * 权重
    - 实体密度分：提取的实体越多，信息量越大
    - 类型调整分：fact/tool_result 加分，conversation 减分
    - 上下文分：对话中围绕同一主题的加分
    """

    # 各维度权重配置
    WEIGHTS = {
        "importance_base": 2.0,       # importance 基础权重
        "entity_density": 0.5,        # 每个实体的分数（上限 5 分）
        "entity_cap": 10,             # 实体计分上限
        "type_fact": 3.0,             # fact 类型加分
        "type_tool_result": 2.0,       # tool_result 类型加分
        "type_interest": 2.0,         # interest 类型加分
        "type_conversation": -1.0,     # conversation 类型减分
        "topic_consistency": 2.0,     # 话题一致性权重
    }

    # 晋升阈值
    PROMOTION_THRESHOLD = 7.0

    # 实体识别正则（中文为主，兼容英文）
    ENTITY_PATTERNS = [
        # 技术名词、工具、框架
        r'(?:Python|JavaScript|React|Vue|Angular|Docker|Kubernetes|Linux|MySQL|Redis|MongoDB|Git)',
        # B站相关实体
        r'(?:BV[a-zA-Z0-9]{10}|av\d+|cv\d+)',
        # 视频/UP主/收藏夹相关
        r'(?:UP主|视频|收藏夹|弹幕|分区)',
        # 数字 + 单位（时间、大小、数量）
        r'\d+\s*(?:分钟|小时|天|周|月|年|秒|GB|MB|KB|万|亿|粉丝|播放)',
        # 带引号的专有名词
        r'["""\'""\'].{2,10}["""\'""\']',
        # 方括号内的标签
        r'\[[\u4e00-\u9fa5a-zA-Z0-9]+\]',
    ]

    def __init__(self, topic_context: Optional[Dict[str, Any]] = None):
        """
        Args:
            topic_context: 当前对话的话题上下文
                {
                    "current_topic": str,        # 当前话题
                    "topic_keywords": [str],    # 话题关键词
                    "conversation_turns": int, # 本话题的对话轮次
                    "topic_history": [str],     # 历史话题列表
                }
        """
        self.topic_context = topic_context or {}

    def score(self, entry: MemoryEntry) -> Dict[str, Any]:
        """
        对单条记忆进行综合评分

        Returns:
            {
                "total_score": float,
                "breakdown": {
                    "importance_base": float,
                    "entity_density": float,
                    "type_adjustment": float,
                    "topic_consistency": float,
                },
                "should_promote": bool,
                "reasons": [str],  # 加分/减分原因
            }
        """
        breakdown = {}
        reasons = []

        # 1. 基础重要性分
        importance_score = entry.importance * self.WEIGHTS["importance_base"]
        breakdown["importance_base"] = importance_score

        # 2. 实体密度分
        entities = self._extract_entities(entry.content)
        entity_score = min(len(entities) * self.WEIGHTS["entity_density"], self.WEIGHTS["entity_cap"])
        breakdown["entity_density"] = entity_score
        if entities:
            reasons.append(f"包含 {len(entities)} 个实体: {entities[:3]}")

        # 3. 类型调整分
        type_adjustment = 0
        if entry.memory_type == MemoryType.FACT.value or entry.memory_type == "fact":
            type_adjustment = self.WEIGHTS["type_fact"]
            reasons.append("fact 类型，信息价值高")
        elif entry.memory_type == MemoryType.TOOL_RESULT.value or entry.memory_type == "tool_result":
            type_adjustment = self.WEIGHTS["type_tool_result"]
            reasons.append("tool_result 类型，具有工具复用价值")
        elif entry.memory_type == MemoryType.INTEREST.value or entry.memory_type == "interest":
            type_adjustment = self.WEIGHTS["type_interest"]
            reasons.append("interest 类型，反映用户兴趣")
        elif entry.memory_type == MemoryType.CONVERSATION.value or entry.memory_type == "conversation":
            type_adjustment = self.WEIGHTS["type_conversation"]
            reasons.append("conversation 类型，降低分数")
        breakdown["type_adjustment"] = type_adjustment

        # 4. 话题一致性分
        topic_score = self._calc_topic_consistency(entry)
        breakdown["topic_consistency"] = topic_score

        # 总分
        total = importance_score + entity_score + type_adjustment + topic_score
        breakdown["total"] = total
        should_promote = total >= self.PROMOTION_THRESHOLD

        if should_promote:
            reasons.append(f"总分 {total:.1f} >= 阈值 {self.PROMOTION_THRESHOLD}，晋升 LTM")

        return {
            "total_score": total,
            "breakdown": breakdown,
            "should_promote": should_promote,
            "reasons": reasons
        }

    def _extract_entities(self, content: str) -> List[str]:
        """提取实体词"""
        entities = []
        for pattern in self.ENTITY_PATTERNS:
            matches = re.findall(pattern, content, re.IGNORECASE)
            entities.extend(matches)
        # 去重
        return list(set(entities))

    def _calc_topic_consistency(self, entry: MemoryEntry) -> float:
        """计算话题一致性分数"""
        if not self.topic_context:
            return 0.0

        topic_keywords = self.topic_context.get("topic_keywords", [])
        if not topic_keywords:
            return 0.0

        content_lower = entry.content.lower()
        matched = sum(1 for kw in topic_keywords if kw.lower() in content_lower)
        max_possible = len(topic_keywords)

        # 对话轮次越多，说明话题越深入，值得晋升
        conversation_turns = self.topic_context.get("conversation_turns", 0)
        topic_depth_bonus = min(conversation_turns * 0.3, 1.5)

        consistency_score = (matched / max_possible) * self.WEIGHTS["topic_consistency"] + topic_depth_bonus
        return consistency_score

    def batch_score(self, entries: List[MemoryEntry]) -> List[Dict[str, Any]]:
        """批量评分"""
        return [self.score(entry) for entry in entries]


class TopicTracker:
    """
    话题追踪器

    维护当前对话的话题状态，用于晋升评分
    """

    def __init__(self):
        self.current_topic: Optional[str] = None
        self.topic_keywords: List[str] = []
        self.conversation_turns: int = 0
        self.topic_history: List[Dict[str, Any]] = []

    def update(self, user_message: str, assistant_response: str = ""):
        """
        根据对话更新话题状态

        Args:
            user_message: 用户消息
            assistant_response: 助手回复（可选）
        """
        # 简单的话题切换检测（新消息首句与当前话题关键词重叠率 < 30% 则视为切换）
        new_topic_indicators = self._extract_topic_indicators(user_message)
        if new_topic_indicators:
            overlap = self._calc_overlap(new_topic_indicators, self.topic_keywords)
            if overlap < 0.3:
                # 话题切换，保存旧话题
                if self.current_topic:
                    self.topic_history.append({
                        "topic": self.current_topic,
                        "keywords": self.topic_keywords,
                        "turns": self.conversation_turns
                    })
                # 开始新话题
                self.current_topic = new_topic_indicators[0]
                self.topic_keywords = new_topic_indicators
                self.conversation_turns = 1
            else:
                # 同一话题继续
                self.conversation_turns += 1
                # 扩展关键词
                for kw in new_topic_indicators:
                    if kw not in self.topic_keywords:
                        self.topic_keywords.append(kw)
        elif assistant_response:
            self.conversation_turns += 1

    def _extract_topic_indicators(self, text: str) -> List[str]:
        """从文本中提取话题关键词"""
        # 简单策略：提取前 N 个实词
        # 实际项目中可以用 LLM 或更复杂的 NLP
        words = re.findall(r'[\u4e00-\u9fa5a-zA-Z0-9]{2,8}', text)
        # 过滤停用词
        stopwords = {"的", "了", "是", "在", "我", "你", "他", "她", "它", "这", "那", "有", "和", "就", "不", "也", "都", "要", "会", "能", "可以", "一个", "什么", "怎么", "为什么", "如何", "怎样"}
        words = [w for w in words if w not in stopwords]
        return words[:5]  # 取前 5 个作为话题指标

    def _calc_overlap(self, list1: List[str], list2: List[str]) -> float:
        """计算两个列表的重叠率"""
        if not list2:
            return 0.0
        overlap = sum(1 for item in list1 if item in list2)
        return overlap / len(list2)

    def get_context(self) -> Dict[str, Any]:
        """获取当前话题上下文"""
        return {
            "current_topic": self.current_topic,
            "topic_keywords": self.topic_keywords,
            "conversation_turns": self.conversation_turns,
            "topic_history": self.topic_history
        }

    def reset(self):
        """重置话题状态"""
        if self.current_topic and self.conversation_turns > 2:
            # 保留历史，避免丢失
            self.topic_history.append({
                "topic": self.current_topic,
                "keywords": self.topic_keywords,
                "turns": self.conversation_turns
            })
        self.current_topic = None
        self.topic_keywords = []
        self.conversation_turns = 0
