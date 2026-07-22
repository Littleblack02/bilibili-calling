import asyncio
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, UserInterestProfile
from app.services.recommendation.recommendation_service import RecommendationService
from app.services.recommendation import recommendation_service as service_module


def test_full_flow_filters_before_top_k_and_keeps_trace(monkeypatch):
    async def scenario():
        service = RecommendationService()
        candidates = [
            {
                "bvid": f"BV{index}", "title": f"AI 教程 {index}", "author": f"UP{index}",
                "mid": index, "play": 1000 * index, "duration": 300 + index,
                "pubdate": datetime.utcnow(), "recall_source": source,
                "recall_tag": "AI", "raw_recall_score": 0.9 - index * 0.03,
            }
            for index, source in enumerate(
                ["interest", "recent_interest", "trending", "context_query", "series_update"], start=1
            )
        ]

        async def ensure_profile(_session_id):
            return {"interest_tags": {"AI": 1.0}, "recent_interests": {"AI": 0.8}}

        async def cookies(_session_id):
            return {}

        async def recall(*_args, **_kwargs):
            return candidates

        hydration_calls = []

        async def hydrate(_bili, rows):
            hydration_calls.append([row["bvid"] for row in rows])
            return [{**row, "hydration_status": "success", "hydration_coverage": 1.0}
                    for row in rows]

        class FakeBili:
            def __init__(self, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

        async def filter_candidates(**kwargs):
            # 模拟已收藏/已看过滤发生在最终取 3 条之前。
            return [item for item in kwargs["candidates"] if item["bvid"] != "BV1"]

        async def preferences(*_args, **_kwargs):
            return {
                "excluded_bvids": set(), "blocked_topics": set(), "blocked_up_mids": set(),
                "negative_topics": set(), "negative_up_mids": set(),
                "positive_topics": set(), "positive_up_mids": set(),
                "topic_affinity": {}, "up_affinity_feedback": {},
            }

        async def reasons(user_profile, candidates):
            return [{**item, "rec_reason": f"命中兴趣 {item['matched_interest']}"} for item in candidates]

        async def save_batch(**kwargs):
            assert kwargs["requested_count"] == 3
            assert all("feature_scores" in item for item in kwargs["recommendations"])
            return "batch-test"

        async def save_pool(**_kwargs):
            return None

        async def failing_llm(**_kwargs):
            raise ValueError("invalid llm response")

        async def llm_plan(*_args, **_kwargs):
            return {
                "required": False,
                "applied": True,
                "model": "test-model",
                "tool": "search_bilibili_videos",
                "queries": [{
                    "query": "AI 教程",
                    "order": "totalrank",
                    "reason": "画像兴趣",
                    "interest_label": "AI",
                    "priority": 0.9,
                }],
            }

        monkeypatch.setattr(service, "_ensure_profile", ensure_profile)
        monkeypatch.setattr(service, "_get_user_cookies", cookies)
        monkeypatch.setattr(service.candidate_recall, "recall_candidates", recall)
        monkeypatch.setattr(service.candidate_hydrator, "hydrate_candidates", hydrate)
        monkeypatch.setattr(service_module, "BilibiliService", FakeBili)
        monkeypatch.setattr(service, "_filter_ineligible", filter_candidates)
        monkeypatch.setattr(service.event_service, "get_preference_state", preferences)
        monkeypatch.setattr(service.reason_generator, "generate_reasons", reasons)
        monkeypatch.setattr(service.event_service, "save_batch", save_batch)
        monkeypatch.setattr(service, "_save_to_candidate_pool", save_pool)
        monkeypatch.setattr(service.llm_recall_planner, "plan", llm_plan)
        monkeypatch.setattr(service.llm_reranker, "rerank_candidates", failing_llm)
        monkeypatch.setattr(service_module.settings, "recommendation_llm_rerank_enabled", True)
        monkeypatch.setattr(service_module.settings, "recommendation_llm_required", False)
        monkeypatch.setattr(service_module.settings, "candidate_hydration_enabled", True)

        result = await service.generate_recommendations("session", limit=3)
        assert len(result) == 3
        assert all(item["bvid"] != "BV1" for item in result)
        assert all(item["batch_id"] == "batch-test" for item in result)
        assert all(item["algorithm_version"] for item in result)
        assert all("feature_scores" in item for item in result)
        assert all(item["hydration_status"] == "success" for item in result)
        assert hydration_calls == [[item["bvid"] for item in candidates]]
        assert len({item["recall_source"] for item in result}) >= 3

    asyncio.run(scenario())


def test_profile_freshness_refreshes_stale_and_reuses_fresh(tmp_path, monkeypatch):
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'profile.db'}")
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(service_module, "async_session_factory", factory)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(UserInterestProfile(
                session_id="stale", interest_tags={"旧兴趣": 0.8},
                updated_at=datetime.utcnow() - timedelta(days=3),
            ))
            db.add(UserInterestProfile(
                session_id="fresh", interest_tags={"新鲜缓存": 0.9},
                updated_at=datetime.utcnow(),
            ))
            await db.commit()

        service = RecommendationService()
        refresh_calls = []

        async def cookies(_session_id):
            return {}

        async def refresh(**kwargs):
            refresh_calls.append(kwargs["session_id"])
            return {"unified_tags": {"增量兴趣": 1.0}, "updated_at": datetime.utcnow()}

        monkeypatch.setattr(service, "_get_user_cookies", cookies)
        monkeypatch.setattr(service.multi_source_profile_builder, "build_comprehensive_profile", refresh)

        stale = await service._ensure_profile("stale")
        fresh = await service._ensure_profile("fresh")
        assert stale["interest_tags"] == {"增量兴趣": 1.0}
        assert fresh["interest_tags"] == {"新鲜缓存": 0.9}
        assert refresh_calls == ["stale"]
        eligible = await service._filter_ineligible(
            "fresh",
            [
                {"bvid": "BLOCK_TOPIC", "title": "游戏攻略", "mid": 1, "duration": 100},
                {"bvid": "BLOCK_UP", "title": "普通视频", "mid": 2, "duration": 100},
                {"bvid": "SAFE", "title": "知识教程", "mid": 3, "duration": 100},
            ],
            blocked_topics={"游戏"},
            blocked_up_mids={2},
        )
        assert [item["bvid"] for item in eligible] == ["SAFE"]
        await engine.dispose()

    asyncio.run(scenario())
