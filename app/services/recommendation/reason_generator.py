"""
推荐理由生成服务

使用 Gemma 4 为推荐视频生成自然语言推荐理由
"""
from typing import List, Dict, Any, Optional
from loguru import logger
import asyncio


class ReasonGenerator:
    """推荐理由生成器"""

    async def generate_reasons(
        self,
        user_profile: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        为推荐视频生成推荐理由

        Args:
            user_profile: 用户画像
            candidates: 候选视频列表（已打分）

        Returns:
            带推荐理由的候选视频列表
        """
        logger.info(f"开始生成推荐理由: {len(candidates)} 个候选")

        if not candidates:
            return []

        from app.config import settings

        # 规则理由是稳定默认路径；LLM 与辅助重排使用同一开关。
        top_candidates = candidates[:settings.recommendation_llm_top_n]
        if not settings.recommendation_llm_rerank_enabled:
            return self._generate_default_reasons(candidates, user_profile)

        # 构建 Gemma 4 提示词
        prompt = self._build_reason_prompt(user_profile, top_candidates)

        # 调用 Gemma 4
        try:
            result = await asyncio.wait_for(
                self._call_gemma_for_reasons(prompt),
                timeout=settings.recommendation_llm_timeout_seconds,
            )
            candidates_with_reasons = self._parse_reason_results(top_candidates, result)
            if len(candidates) > len(top_candidates):
                candidates_with_reasons.extend(
                    self._generate_default_reasons(candidates[len(top_candidates):], user_profile)
                )
            return candidates_with_reasons

        except Exception as e:
            logger.error(f"生成推荐理由失败: {e}")
            # 返回默认理由
            return self._generate_default_reasons(candidates, user_profile)

    def _build_reason_prompt(
        self,
        user_profile: Dict[str, Any],
        candidates: List[Dict[str, Any]]
    ) -> str:
        """构建推荐理由生成提示词"""
        # 用户画像摘要
        top_interests = user_profile.get("top_interests") or sorted(
            user_profile.get("interest_tags", {}).items(), key=lambda item: item[1], reverse=True
        )[:10]
        interests_str = ", ".join([tag for tag, _ in top_interests])
        ups_str = ", ".join([up["name"] for up in user_profile.get("followed_ups", [])])
        recency_confidence = user_profile.get("profile_recency_confidence")
        temporal_summary = "未提供"
        if isinstance(recency_confidence, (int, float)):
            temporal_summary = (
                "主要是历史兴趣证据" if recency_confidence < 0.15 else "存在近期兴趣证据"
            )

        profile_desc = f"""
用户画像：
- 兴趣标签：{interests_str}
- 关注UP主：{ups_str}
- 兴趣时效：{temporal_summary}
"""

        # 候选视频列表
        candidates_desc = "\n".join([
            f"{i+1}. {cand['title']} (播放量: {cand.get('play', 0)}, UP主: {cand.get('author', '未知')}, "
            f"召回源: {cand.get('recall_source', 'unknown')}, 命中兴趣: {cand.get('matched_interest') or '无'})"
            for i, cand in enumerate(candidates)
        ])

        prompt = f"""{profile_desc}

以下是为该用户推荐的视频列表：

{candidates_desc}

请为每个视频生成推荐理由（1-2句话），说明：
1. 为什么推荐这个视频（与用户兴趣/UP主的关联）
2. 只引用上面提供的真实证据，不得编造观看、收藏、关注或点赞行为

请以 JSON 格式返回：
{{
  "reasons": [
    {{"index": 1, "reason": "因为你经常学习AI编程，且关注了XX UP主，这个视频..."}},
    {{"index": 2, "reason": "这个视频的质量很高，播放量X万，且内容是..."}},
    ...
  ]
}}

只返回 JSON，不要其他内容。"""

        return prompt

    async def _call_gemma_for_reasons(self, prompt: str) -> str:
        """调用百炼模型生成推荐理由"""
        from app.config import settings
        from openai import AsyncOpenAI
        import json

        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url
        )

        try:
            provider_options: Dict[str, Any] = {}
            if "dashscope.aliyuncs.com" in settings.openai_base_url.casefold():
                provider_options["extra_body"] = {
                    "enable_thinking": settings.recommendation_llm_enable_thinking
                }
            response = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": "你是严谨的视频推荐助手。只能依据输入中的画像、召回源和视频字段解释，不得编造用户行为。"},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=2000,
                temperature=0.3,
                **provider_options,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"调用百炼失败: {e}")
            return "{}"

    def _parse_reason_results(
        self,
        candidates: List[Dict[str, Any]],
        result: str
    ) -> List[Dict[str, Any]]:
        """解析推荐理由结果"""
        import json

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

        try:
            if data is None:
                raise json.JSONDecodeError("无法解析 JSON", json_str, 0)

            reasons = data.get("reasons", [])

            # 创建 index -> reason 的映射
            reason_map = {
                item["index"] - 1: item["reason"]
                for item in reasons
            }

            # 将理由应用到候选视频
            defaults = self._generate_default_reasons(candidates, {})
            candidates_with_reasons = []
            for i, cand in enumerate(candidates):
                if i in reason_map:
                    cand["rec_reason"] = reason_map[i]
                else:
                    cand["rec_reason"] = defaults[i]["rec_reason"]

                candidates_with_reasons.append(cand)

            return candidates_with_reasons

        except (json.JSONDecodeError, KeyError) as e:
            logger.error(f"解析推荐理由失败: {e}")
            return self._generate_default_reasons(candidates, {})

    def _generate_default_reasons(
        self,
        candidates: List[Dict[str, Any]],
        user_profile: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """生成默认推荐理由（基于规则）"""
        top_interests = user_profile.get("top_interests") or sorted(
            user_profile.get("interest_tags", {}).items(), key=lambda item: item[1], reverse=True
        )[:10]
        interest_tags = [tag for tag, _ in top_interests]
        followed_up_names = [up["name"] for up in user_profile.get("followed_ups", [])]
        evidence_mass = user_profile.get("profile_evidence_mass", 0.0)
        recency_confidence = user_profile.get("profile_recency_confidence")
        historical_only = bool(
            isinstance(recency_confidence, (int, float))
            and float(recency_confidence) < 0.15
            and isinstance(evidence_mass, (int, float))
            and float(evidence_mass) > 0
        )

        candidates_with_reasons = []

        for cand in candidates:
            reasons = []

            # 1. 召回源理由
            recall_source = cand.get("recall_source", "")
            if recall_source == "interest":
                tag = cand.get("recall_tag", "")
                if tag in interest_tags:
                    if historical_only:
                        reasons.append(f"你的历史兴趣曾涉及「{tag}」")
                    else:
                        reasons.append(f"你对「{tag}」感兴趣")
            elif recall_source == "followed_up":
                up_name = cand.get("recall_up_name", "")
                if up_name in followed_up_names:
                    reasons.append(f"你关注了「{up_name}」UP主")
            elif recall_source == "category":
                category = cand.get("recall_category", "")
                reasons.append(f"你喜欢「{category}」分区的内容")
            elif recall_source == "trending":
                reasons.append("这是当前热门视频")
            elif recall_source == "recent_interest":
                if historical_only:
                    reasons.append(
                        f"与你较早的「{cand.get('recall_tag', '相关主题')}」历史兴趣匹配"
                    )
                else:
                    reasons.append(f"与你近期的「{cand.get('recall_tag', '相关主题')}」兴趣匹配")
            elif recall_source == "context_query":
                reasons.append(f"匹配你这次输入的「{cand.get('recall_tag', '主题')}」")
            elif recall_source == "llm_planned":
                label = cand.get("recall_interest_label") or cand.get("recall_tag", "主题")
                reasons.append(f"大模型根据你的「{label}」画像兴趣规划了这次检索")
            elif recall_source == "vector_rediscovery":
                reasons.append("与当前主题在你的收藏知识库中语义相近")
            elif recall_source == "series_update":
                reasons.append(f"与你正在追的「{cand.get('recall_tag', '系列')}」相关")
            elif recall_source == "dynamic_following":
                reasons.append("来自你关注动态中的近期投稿")

            matched_concepts = cand.get("matched_concepts") or []
            ontology_path = cand.get("ontology_path") or []
            if matched_concepts:
                label = matched_concepts[0].get("label")
                if ontology_path:
                    first_edge = ontology_path[0]
                    reasons.append(
                        f"本体关系显示「{first_edge.get('from')}」与「{first_edge.get('to')}」相关"
                    )
                elif label:
                    qualifier = "历史兴趣" if historical_only else "兴趣"
                    reasons.append(f"语义上命中你的「{label}」{qualifier}")

            # 2. 质量理由
            play = cand.get("play", 0)
            if play > 100000:
                reasons.append(f"播放量{play//10000}万+，较受关注")
            elif play > 10000:
                reasons.append(f"播放量{play//10000}万，受关注")

            # 合并理由
            matched_interest = cand.get("matched_interest")
            if matched_interest and not reasons:
                reasons.append(f"内容与你的「{matched_interest}」兴趣匹配")

            if reasons:
                default_reason = "因为" + "、".join(reasons[:2]) + "，推荐给你。"
            else:
                default_reason = "作为本次探索内容推荐，不代表你已有相关观看或收藏行为。"

            candidates_with_reasons.append({
                **cand,
                "rec_reason": default_reason
            })

        return candidates_with_reasons


# 单例
_reason_generator: Optional[ReasonGenerator] = None


def get_reason_generator() -> ReasonGenerator:
    """获取推荐理由生成器单例"""
    global _reason_generator
    if _reason_generator is None:
        _reason_generator = ReasonGenerator()
    return _reason_generator
