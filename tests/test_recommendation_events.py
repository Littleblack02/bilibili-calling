import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.models import Base, RecommendationEvent, UserWatchHistory
from app.services.recommendation import event_service as event_module


def test_event_dedup_preferences_and_metrics(tmp_path, monkeypatch):
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'events.db'}")
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(event_module, "async_session_factory", factory)

        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        service = event_module.RecommendationEventService()
        batch_id = await service.save_batch(
            session_id="session-1",
            algorithm_version="rules-v1",
            requested_count=1,
            recommendations=[{"bvid": "BV1", "rec_score": 0.8, "recall_source": "interest"}],
        )
        assert await service.record_event(
            "session-1", "BV1", "impression", batch_id=batch_id,
            event_data={"recall_source": "interest"},
        )
        assert not await service.record_event("session-1", "BV1", "impression", batch_id=batch_id)
        assert await service.record_event("session-1", "BV1", "click", batch_id=batch_id)
        assert await service.record_event(
            "session-1", "BV1", "dismiss", batch_id=batch_id, topic="AI", up_mid=42
        )

        state = await service.get_preference_state("session-1")
        assert "BV1" in state["excluded_bvids"]
        assert "AI" in state["negative_topics"]
        assert 42 in state["negative_up_mids"]
        assert state["positive_topics"] == set()
        assert state["topic_affinity"]["AI"] < 0
        assert state["up_affinity_feedback"][42] < 0
        assert state["blocked_topics"] == set()

        await service.record_event(
            "session-1", "BV3", "dismiss", topic="音乐", up_mid=99,
            reason_code="temporary",
        )
        state = await service.get_preference_state("session-1")
        assert "音乐" not in state["negative_topics"]
        assert "音乐" not in state["topic_affinity"]
        assert 99 not in state["up_affinity_feedback"]

        await service.record_event("session-1", "BV2", "block_topic", topic="游戏")
        state = await service.get_preference_state("session-1")
        assert state["blocked_topics"] == {"游戏"}
        await service.record_event("session-1", "__preference__", "unblock_topic", topic="游戏")
        state = await service.get_preference_state("session-1")
        assert state["blocked_topics"] == set()

        async with factory() as db:
            db.add(UserWatchHistory(
                session_id="session-1", bvid="BV1", view_at=int(datetime.utcnow().timestamp()) + 1
            ))
            await db.commit()

        metrics = await service.metrics("session-1")
        assert metrics["events"]["impression"] == 1
        assert metrics["events"]["dismiss"] == 2
        assert metrics["ctr"] == 1.0
        assert metrics["dismiss_rate"] == 2.0
        assert metrics["dismiss_reasons"] == {"unspecified": 1, "temporary": 1}
        assert metrics["channel_contribution"] == {"interest": 1}
        assert metrics["inferred_watched_clicks"] == 1
        assert metrics["watch_completion_available"] is False
        await engine.dispose()

    asyncio.run(scenario())


def test_concept_feedback_propagates_directionally_and_keeps_evidence(tmp_path, monkeypatch):
    async def scenario():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'concept-events.db'}")
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        monkeypatch.setattr(event_module, "async_session_factory", factory)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        service = event_module.RecommendationEventService()
        await service.record_event("s", "BV1", "favorite", topic="RAG")
        await service.record_event(
            "s", "BV2", "dismiss", topic="LangGraph", reason_code="not_relevant"
        )
        await service.record_event("s", "BV3", "dismiss", topic="音乐", reason_code="temporary")
        state = await service.get_preference_state("s")

        rag = "https://bilibili.local/ontology/RAG"
        llm = "https://bilibili.local/ontology/LargeLanguageModel"
        langgraph = "https://bilibili.local/ontology/LangGraph"
        python = "https://bilibili.local/ontology/Python"
        technology = "https://bilibili.local/ontology/Technology"
        ai = "https://bilibili.local/ontology/ArtificialIntelligence"
        assert state["concept_affinity"][rag] > state["concept_affinity"][llm] > 0
        assert state["concept_affinity"][langgraph] < 0
        assert python not in state["negative_concept_ids"]
        assert "https://bilibili.local/ontology/Music" not in state["negative_concept_ids"]

        await service.record_event("s", "BV4", "block_topic", topic="LangGraph")
        state = await service.get_preference_state("s")
        assert langgraph in state["blocked_concept_ids"]
        assert python not in state["blocked_concept_ids"]
        assert technology not in state["blocked_concept_ids"]
        await service.record_event("s", "__preference__", "unblock_topic", topic="LangGraph")
        assert langgraph not in (await service.get_preference_state("s"))["blocked_concept_ids"]

        await service.record_event("s", "BV5", "block_topic", topic="AI")
        state = await service.get_preference_state("s")
        assert ai in state["blocked_concept_ids"]
        assert rag in state["blocked_concept_ids"]
        assert technology not in state["blocked_concept_ids"]

        async with factory() as db:
            stored = (await db.execute(select(RecommendationEvent).where(
                RecommendationEvent.bvid == "BV1"
            ))).scalar_one()
            assert stored.event_data["concept_ids"] == [rag]
            assert stored.event_data["concept_evidence"][0]["matched_label"] == "RAG"
        await engine.dispose()

    asyncio.run(scenario())
