import asyncio
import json

import pytest

from app.config import settings
from app.services.recommendation.candidate_recalls import CandidateRecall
from app.services.recommendation.llm_recall_planner import (
    LLMRecallPlanner,
    RecommendationPlanningError,
)
from app.services.recommendation.llm_reranker import LLMReranker
from app.services.recommendation.recommendation_service import (
    RecommendationModelRequiredError,
    RecommendationService,
)


def test_model_recommendation_is_required_by_default():
    assert settings.recommendation_llm_rerank_enabled is True
    assert settings.recommendation_llm_required is True


def test_llm_recall_planner_requires_and_validates_search_tool_call(monkeypatch):
    async def scenario():
        planner = LLMRecallPlanner()
        captured = {}

        async def call_model(payload):
            captured.update(payload)
            return json.dumps({
                "queries": [{
                    "query": "<em>RAG</em> 工程实践",
                    "order": "pubdate",
                    "reason": "匹配近期 RAG 兴趣",
                    "interest_label": "检索增强生成",
                    "priority": 0.92,
                }]
            }, ensure_ascii=False)

        monkeypatch.setattr(planner, "_call_model", call_model)
        plan = await planner.plan(
            {
                "interest_tags": {"RAG": 0.9},
                "recent_interests": {"LangGraph": 0.7},
            },
            {"mode": "learning"},
            require_success=True,
        )
        assert captured["interest_tags"][0][0] == "RAG"
        assert plan["applied"] is True
        assert plan["tool"] == "search_bilibili_videos"
        assert plan["queries"][0]["query"] == "RAG 工程实践"
        assert plan["queries"][0]["order"] == "pubdate"

    asyncio.run(scenario())


def test_llm_recall_planner_rejects_missing_queries():
    with pytest.raises(RecommendationPlanningError):
        LLMRecallPlanner._validate_arguments('{"queries": []}')


def test_llm_planned_channel_executes_only_validated_queries():
    class FakeBili:
        def __init__(self):
            self.calls = []

        async def search_bilibili(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "items": [{
                "bvid": "BV-LLM",
                "title": "<em>RAG</em> 新进展",
                "author": "UP",
                "mid": 42,
                "play": 100,
                "duration": "03:20",
                "pubdate": 1_700_000_000,
                "pic": "cover",
            }]}

    async def scenario():
        bili = FakeBili()
        rows = await CandidateRecall()._recall_by_llm_plan(
            bili,
            {
                "tool": "search_bilibili_videos",
                "model": "test-model",
                "queries": [{
                    "query": "RAG 工程实践",
                    "order": "pubdate",
                    "reason": "画像匹配",
                    "interest_label": "RAG",
                    "priority": 0.9,
                }],
            },
            limit=5,
        )
        assert bili.calls == [{
            "keyword": "RAG 工程实践",
            "search_type": "video",
            "order": "pubdate",
            "page": 1,
        }]
        assert rows[0]["recall_source"] == "llm_planned"
        assert rows[0]["recall_lookup"]["model"] == "test-model"

    asyncio.run(scenario())


def test_required_llm_rerank_rejects_partial_or_invalid_model_scores():
    reranker = object.__new__(LLMReranker)
    candidates = [
        {"bvid": "A", "title": "A"},
        {"bvid": "B", "title": "B"},
    ]
    with pytest.raises(ValueError, match="全部候选"):
        reranker._parse_rerank_result(
            candidates,
            '{"scores":[{"index":1,"score":0.8,"reason":"ok"}]}',
            require_success=True,
        )
    with pytest.raises(ValueError, match="0 到 1"):
        reranker._parse_rerank_result(
            candidates,
            '{"scores":[{"index":1,"score":2},{"index":2,"score":0.2}]}',
            require_success=True,
        )


def test_required_model_configuration_fails_fast(monkeypatch):
    monkeypatch.setattr(settings, "recommendation_llm_required", True)
    monkeypatch.setattr(settings, "recommendation_llm_rerank_enabled", True)
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "llm_model", "")
    with pytest.raises(RecommendationModelRequiredError, match="缺少配置"):
        RecommendationService._validate_llm_configuration()


def test_required_model_failure_cannot_silently_return_rule_ranking(monkeypatch):
    class FailingReranker:
        async def rerank_candidates(self, **_kwargs):
            raise TimeoutError("model timeout")

    async def scenario():
        service = object.__new__(RecommendationService)
        service.llm_reranker = FailingReranker()
        context = {}
        monkeypatch.setattr(settings, "recommendation_llm_required", True)
        monkeypatch.setattr(settings, "recommendation_llm_rerank_enabled", True)
        with pytest.raises(RecommendationModelRequiredError, match="重排失败"):
            await service._apply_llm_rerank(
                session_id="session",
                profile={"interest_tags": {"RAG": 1.0}},
                ranked_candidates=[{
                    "bvid": "BV1",
                    "title": "RAG",
                    "rec_score": 0.8,
                }],
                context=context,
            )
        assert context["llm_rerank"]["applied"] is False

    asyncio.run(scenario())
