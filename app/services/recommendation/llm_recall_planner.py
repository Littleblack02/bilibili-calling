"""LLM tool-call planner for profile-driven Bilibili candidate recall."""
from __future__ import annotations

import json
import math
import re
from typing import Any

from openai import AsyncOpenAI

from app.config import settings
from app.services.ontology import get_ontology_service


class RecommendationPlanningError(RuntimeError):
    """The model did not produce a valid, executable recall tool call."""


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "search_bilibili_videos",
        "description": (
            "根据用户画像生成 1 到 5 个 B站视频搜索请求。应用只执行这个白名单工具，"
            "模型不能直接访问网络。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 5,
                    "items": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "minLength": 1, "maxLength": 60},
                            "order": {
                                "type": "string",
                                "enum": ["totalrank", "pubdate"],
                            },
                            "reason": {"type": "string", "minLength": 1, "maxLength": 160},
                            "interest_label": {
                                "type": "string",
                                "minLength": 1,
                                "maxLength": 60,
                            },
                            "priority": {"type": "number", "minimum": 0, "maximum": 1},
                        },
                        "required": [
                            "query", "order", "reason", "interest_label", "priority"
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["queries"],
            "additionalProperties": False,
        },
    },
}


def _finite_score(value: Any) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.5
    if not math.isfinite(score):
        return 0.5
    return max(0.0, min(1.0, score))


def _clean_text(value: Any, limit: int) -> str:
    text = re.sub(r"<[^>]+>", "", str(value or ""))
    return " ".join(text.split()).strip()[:limit]


class LLMRecallPlanner:
    """Ask the configured model to call a constrained Bilibili search tool."""

    @staticmethod
    def _profile_payload(
        profile: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        ontology = get_ontology_service()
        interests = sorted(
            (profile.get("interest_tags") or {}).items(),
            key=lambda row: float(row[1]),
            reverse=True,
        )[:10]
        recent = sorted(
            (profile.get("recent_interests") or {}).items(),
            key=lambda row: float(row[1]),
            reverse=True,
        )[:8]
        ontology_interests = []
        concept_affinities = (
            profile.get("concept_absolute_affinities")
            or profile.get("concept_affinities")
            or {}
        )
        for concept_id, score in sorted(
            concept_affinities.items(),
            key=lambda row: float(row[1]),
            reverse=True,
        )[:10]:
            concept = ontology.concept(str(concept_id))
            if concept:
                ontology_interests.append({
                    "concept_id": concept_id,
                    "label": concept["label"],
                    "score": _finite_score(score),
                })
        return {
            "interest_tags": interests,
            "recent_interests": recent,
            "ontology_interests": ontology_interests,
            "multi_interests": (profile.get("multi_interests") or [])[:5],
            "current_intent": context.get("query") or profile.get("current_intent"),
            "mode": context.get("mode", "balanced"),
        }

    async def _call_model(self, payload: dict[str, Any]) -> str:
        client = AsyncOpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
        )
        provider_options: dict[str, Any] = {}
        if "dashscope.aliyuncs.com" in settings.openai_base_url.casefold():
            provider_options["extra_body"] = {
                "enable_thinking": settings.recommendation_llm_enable_thinking
            }
        response = await client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是推荐召回规划器。只依据提供的聚合画像和 Ontology 兴趣，"
                        "调用 search_bilibili_videos。查询词要具体、多样、可在B站直接搜索；"
                        "不得推断或编造画像中不存在的敏感属性。"
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=False, default=str),
                },
            ],
            tools=[SEARCH_TOOL],
            temperature=0.2,
            max_tokens=1200,
            **provider_options,
        )
        message = response.choices[0].message
        tool_calls = list(message.tool_calls or [])
        matching = [
            call for call in tool_calls
            if getattr(getattr(call, "function", None), "name", None)
            == "search_bilibili_videos"
        ]
        if not matching:
            raise RecommendationPlanningError(
                "大模型没有调用 search_bilibili_videos 工具"
            )
        return str(matching[0].function.arguments or "")

    @staticmethod
    def _validate_arguments(raw_arguments: str) -> list[dict[str, Any]]:
        try:
            payload = json.loads(raw_arguments)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RecommendationPlanningError("大模型搜索工具参数不是有效 JSON") from exc
        rows = payload.get("queries") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or not rows:
            raise RecommendationPlanningError("大模型搜索工具没有生成查询")

        queries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for row in rows[:5]:
            if not isinstance(row, dict):
                continue
            query = _clean_text(row.get("query"), 60)
            normalized = query.casefold()
            if not query or normalized in seen:
                continue
            order = str(row.get("order") or "totalrank")
            if order not in {"totalrank", "pubdate"}:
                order = "totalrank"
            reason = _clean_text(row.get("reason"), 160)
            interest_label = _clean_text(row.get("interest_label"), 60)
            if not reason or not interest_label:
                continue
            seen.add(normalized)
            queries.append({
                "query": query,
                "order": order,
                "reason": reason,
                "interest_label": interest_label,
                "priority": round(_finite_score(row.get("priority")), 4),
            })
        if not queries:
            raise RecommendationPlanningError("大模型搜索工具参数未通过白名单校验")
        return queries

    async def plan(
        self,
        profile: dict[str, Any],
        context: dict[str, Any],
        *,
        require_success: bool,
    ) -> dict[str, Any]:
        payload = self._profile_payload(profile, context)
        try:
            raw_arguments = await self._call_model(payload)
            queries = self._validate_arguments(raw_arguments)
            return {
                "required": require_success,
                "applied": True,
                "model": settings.llm_model,
                "tool": "search_bilibili_videos",
                "queries": queries,
            }
        except Exception as exc:
            if require_success:
                if isinstance(exc, RecommendationPlanningError):
                    raise
                raise RecommendationPlanningError(
                    f"大模型召回规划失败：{exc}"
                ) from exc
            return {
                "required": False,
                "applied": False,
                "reason": "model_error",
                "queries": [],
            }


_llm_recall_planner: LLMRecallPlanner | None = None


def get_llm_recall_planner() -> LLMRecallPlanner:
    global _llm_recall_planner
    if _llm_recall_planner is None:
        _llm_recall_planner = LLMRecallPlanner()
    return _llm_recall_planner
