"""
LLM 重排服务

使用 Gemma 4 对召回的候选视频进行排序打分
"""
import json
from typing import List, Dict, Any, Optional
from loguru import logger
from datetime import datetime

from app.services.gemma.cover_analyzer import get_cover_analyzer


class LLMReranker:
    """LLM 重排服务"""

    def __init__(self):
        self.cover_analyzer = get_cover_analyzer()

    async def rerank_candidates(
        self,
        session_id: str,
        user_profile: Dict[str, Any],
        candidates: List[Dict[str, Any]],
        top_k: int = 20
    ) -> List[Dict[str, Any]]:
        """
        使用 Gemma 4 对候选视频重排打分

        Args:
            session_id: 用户会话 ID
            user_profile: 用户画像
            candidates: 候选视频列表
            top_k: 返回前 K 个

        Returns:
            排序后的候选视频列表，带 rec_score 字段
        """
        logger.info(f"开始 LLM 重排: {session_id}, 候选数: {len(candidates)}")

        if not candidates:
            return []

        # 1. 准备重排的上下文
        rerank_context = self._prepare_rerank_context(user_profile, candidates)

        # 2. 调用 Gemma 4 批量打分
        scored_candidates = await self._batch_score_candidates(rerank_context)

        # 3. 排序并取 Top-K
        sorted_candidates = sorted(
            scored_candidates,
            key=lambda x: x.get("rec_score", 0.0),
            reverse=True
        )[:top_k]

        logger.info(f"LLM 重排完成: {session_id}, Top-{top_k}")
        return sorted_candidates

    def _prepare_rerank_context(
        self,
        user_profile: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """准备重排上下文"""
        # 提取用户画像的关键信息
        top_interests = sorted(
            user_profile.get("interest_tags", {}).items(),
            key=lambda x: x[1],
            reverse=True
        )[:5]

        followed_ups = user_profile.get("followed_ups", [])[:5]

        return {
            "user_profile": {
                "top_interests": top_interests,
                "followed_ups": followed_ups,
                "visual_preference": user_profile.get("visual_style_preference", {}),
                "content_preference": user_profile.get("content_type_preference", {})
            },
            "candidates": candidates[:50]  # 最多处理50个
        }

    async def _batch_score_candidates(
        self,
        context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """批量打分候选视频"""
        candidates = context["candidates"]
        user_profile = context["user_profile"]

        # 构建 Gemma 4 提示词
        prompt = self._build_rerank_prompt(user_profile, candidates)

        # 调用 Gemma 4
        try:
            result = await self._call_gemma_for_rerank(prompt)
            scored_candidates = self._parse_rerank_result(candidates, result)
            return scored_candidates

        except Exception as e:
            logger.error(f"LLM 打分失败: {e}")
            # 返回默认分数（基于规则的降级方案）
            return self._fallback_score_candidates(candidates, user_profile)

    def _build_rerank_prompt(
        self,
        user_profile: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> str:
        """构建重排提示词"""
        # 用户画像摘要
        interests_str = ", ".join([tag for tag, _ in user_profile.get("top_interests", [])])
        ups_str = ", ".join([up["name"] for up in user_profile.get("followed_ups", [])])

        profile_desc = f"""
用户画像：
- 兴趣标签：{interests_str}
- 关注UP主：{ups_str}
- 视觉偏好：{user_profile.get('visual_preference', {})}
- 内容偏好：{user_profile.get('content_preference', {})}
"""

        # 候选视频列表
        candidates_desc = "\n".join([
            f"{i+1}. {cand['title']} (播放量: {cand.get('play', 0)}, 召回源: {cand.get('recall_source', 'unknown')})"
            for i, cand in enumerate(candidates)
        ])

        prompt = f"""{profile_desc}

以下是候选视频列表：

{candidates_desc}

请根据用户画像，对每个候选视频打分（0~1），考虑以下因素：
1. 内容相关性：与用户兴趣标签的匹配度
2. UP主相关性：是否是用户关注的UP主或类似风格
3. 质量信号：播放量、发布时间
4. 召回源质量：兴趣召回 > UP主召回 > 分区召回 > 热榜召回

请以 JSON 格式返回，格式如下：
{{
  "scores": [
    {{"index": 1, "score": 0.85, "reason": "与用户兴趣高度相关"}},
    {{"index": 2, "score": 0.72, "reason": "UP主风格匹配"}},
    ...
  ]
}}

只返回 JSON，不要其他内容。"""

        return prompt

    async def _call_gemma_for_rerank(self, prompt: str) -> str:
        """调用百炼模型进行重排"""
        from app.config import settings
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )

        try:
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": "你是一个专业的视频排序助手，擅长根据用户偏好对视频进行排序。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=3000,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"调用百炼失败: {e}")
            return "{}"

    def _parse_rerank_result(
        self,
        candidates: List[Dict[str, Any]],
        result: str
    ) -> List[Dict[str, Any]]:
        """解析重排结果"""
        # 尝试提取 JSON 部分
        json_str = result.strip()
        if "```json" in json_str:
            start = json_str.find("```json") + 7
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()
        elif "```" in json_str:
            start = json_str.find("```") + 3
            end = json_str.find("```", start)
            json_str = json_str[start:end].strip()

        # 尝试解析，如果失败尝试修复截断的 JSON
        data = None
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            # 尝试修复截断：补充缺失的括号
            fixed = json_str
            open_braces = fixed.count("{") - fixed.count("}")
            open_brackets = fixed.count("[") - fixed.count("]")
            for _ in range(open_braces):
                fixed += "}"
            for _ in range(open_brackets):
                fixed += "]"
            # 移除末尾的逗号
            fixed = fixed.rstrip(", \n")
            try:
                data = json.loads(fixed)
                logger.info("成功修复截断的 JSON")
            except Exception:
                pass

        if data:
            try:
                scores = data.get("scores", [])

                # 创建 index -> score 的映射
                score_map = {
                    item["index"] - 1: {  # 转换为 0-based 索引
                        "score": item["score"],
                        "reason": item.get("reason", "")
                    }
                    for item in scores
                }

                # 将分数应用到候选视频
                scored_candidates = []
                for i, cand in enumerate(candidates):
                    if i in score_map:
                        cand["rec_score"] = score_map[i]["score"]
                        cand["rec_reason"] = score_map[i]["reason"]
                    else:
                        cand["rec_score"] = 0.5
                        cand["rec_reason"] = "未评分"

                    scored_candidates.append(cand)

                return scored_candidates
            except KeyError as e:
                logger.error(f"解析重排结果字段失败: {e}")

        logger.error(f"解析重排结果失败，返回默认分数")
        return [
            {
                **cand,
                "rec_score": 0.5,
                "rec_reason": "解析失败"
            }
            for cand in candidates
        ]

    def _fallback_score_candidates(
        self,
        candidates: List[Dict[str, Any]],
        user_profile: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """降级打分方案（基于规则）"""
        interest_tags = set(user_profile.get("top_interests", []))
        followed_up_mids = {up["mid"] for up in user_profile.get("followed_ups", [])}

        scored_candidates = []

        for cand in candidates:
            score = 0.5  # 基础分
            reasons = []

            # 1. 召回源加权
            recall_source = cand.get("recall_source", "")
            if recall_source == "interest":
                score += 0.2
                reasons.append("兴趣召回")
            elif recall_source == "followed_up":
                score += 0.15
                reasons.append("关注UP主")
            elif recall_source == "category":
                score += 0.1
                reasons.append("分区匹配")
            elif recall_source == "trending":
                score += 0.05
                reasons.append("热榜")

            # 2. UP主匹配
            if cand.get("mid") in followed_up_mids:
                score += 0.15
                reasons.append("关注UP主")

            # 3. 播放量加权（对数平滑）
            play = cand.get("play", 0)
            if play > 0:
                import math
                score += min(0.1, math.log10(play + 1) / 10)
                reasons.append(f"播放量{play}")

            # 4. 时效性加权（30天内加分）
            pubdate = cand.get("pubdate")
            if pubdate:
                days_old = (datetime.utcnow() - pubdate).days
                if days_old < 30:
                    score += (30 - days_old) / 300  # 最多加 0.1
                    reasons.append("新发布")

            # 限制在 0~1
            score = max(0.0, min(1.0, score))

            scored_candidates.append({
                **cand,
                "rec_score": score,
                "rec_reason": ", ".join(reasons) if reasons else "规则匹配"
            })

        return scored_candidates


# 单例
_llm_reranker: Optional[LLMReranker] = None


def get_llm_reranker() -> LLMReranker:
    """获取 LLM 重排服务单例"""
    global _llm_reranker
    if _llm_reranker is None:
        _llm_reranker = LLMReranker()
    return _llm_reranker
