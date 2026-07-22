"""推荐批次、行为事件、偏好和最小指标服务。"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from typing import Any
import uuid
from collections import Counter

from sqlalchemy import select

from app.database import async_session_factory
from app.models import RecommendationBatch, RecommendationEvent, UserWatchHistory
from app.services.ontology import get_ontology_service


VALID_EVENTS = {
    "impression", "click", "viewed", "favorite", "watch_later",
    "dismiss", "block_topic", "block_up", "like",
    "unblock_topic", "unblock_up",
}
NEGATIVE_EVENTS = {"dismiss", "block_topic", "block_up"}
EXCLUSION_EVENTS = {"viewed", "favorite", "dismiss", "block_topic", "block_up"}
POSITIVE_EVENTS = {"like", "favorite", "watch_later"}


def _dismiss_effect(reason_code: str | None) -> tuple[float, float, bool]:
    """返回负反馈强度、半衰期和是否应迁移到主题/UP 偏好。"""
    effects = {
        "temporary": (-0.15, 3.0, False),
        "too_long": (-0.20, 7.0, False),
        "too_old": (-0.25, 7.0, False),
        "not_relevant": (-0.70, 14.0, True),
    }
    return effects.get(reason_code, (-0.50, 14.0, True))


class RecommendationEventService:
    async def save_batch(
        self,
        session_id: str,
        algorithm_version: str,
        requested_count: int,
        recommendations: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> str:
        batch_id = str(uuid.uuid4())
        snapshot = [
            {
                "bvid": item.get("bvid"),
                "position": index,
                "recall_source": item.get("recall_source"),
                "recall_sources": item.get("recall_sources", [item.get("recall_source")]),
                "recall_tag": item.get("recall_tag"),
                "recall_category": item.get("recall_category"),
                "raw_recall_score": item.get("raw_recall_score"),
                "score": item.get("rec_score"),
                "feature_scores": item.get("feature_scores", {}),
                "matched_interest": item.get("matched_interest"),
                "matched_concepts": item.get("matched_concepts", []),
                "ontology_path": item.get("ontology_path", []),
                "matched_interest_cluster": item.get("matched_interest_cluster"),
                "feedback_affinity": item.get("feedback_affinity", 0.0),
                "negative_penalty": item.get("negative_penalty", 0.0),
                "mode_bonus": item.get("mode_bonus", 0.0),
                "mmr_score": item.get("mmr_score"),
            }
            for index, item in enumerate(recommendations, start=1)
        ]
        async with async_session_factory() as db:
            db.add(RecommendationBatch(
                batch_id=batch_id,
                session_id=session_id,
                algorithm_version=algorithm_version,
                requested_count=requested_count,
                returned_count=len(recommendations),
                context=context or {},
                recommendations=snapshot,
            ))
            await db.commit()
        return batch_id

    async def record_event(
        self,
        session_id: str,
        bvid: str,
        event_type: str,
        batch_id: str | None = None,
        reason_code: str | None = None,
        topic: str | None = None,
        up_mid: int | None = None,
        position: int | None = None,
        score: float | None = None,
        event_data: dict[str, Any] | None = None,
    ) -> bool:
        if event_type not in VALID_EVENTS:
            raise ValueError(f"不支持的推荐事件: {event_type}")
        normalized_event_data = dict(event_data or {})
        if topic:
            linked = get_ontology_service().link_text_v2(topic)
            concept_evidence = [
                {
                    "concept_id": row["concept_id"],
                    "label": row["label"],
                    "matched_label": row["matched_label"],
                    "confidence": row["confidence"],
                    "stage": row["stage"],
                }
                for row in linked["selected"]
            ]
            normalized_event_data["topic_text"] = topic
            normalized_event_data["concept_ids"] = [
                row["concept_id"] for row in concept_evidence
            ]
            normalized_event_data["concept_evidence"] = concept_evidence
            normalized_event_data["concept_link_rejection"] = (
                linked["rejection_reason"] if linked["rejected"] else None
            )
        async with async_session_factory() as db:
            existing = None
            if batch_id:
                result = await db.execute(select(RecommendationEvent.id).where(
                    RecommendationEvent.session_id == session_id,
                    RecommendationEvent.batch_id == batch_id,
                    RecommendationEvent.bvid == bvid,
                    RecommendationEvent.event_type == event_type,
                ))
                existing = result.scalar_one_or_none()
            if existing:
                return False
            db.add(RecommendationEvent(
                event_id=str(uuid.uuid4()),
                session_id=session_id,
                batch_id=batch_id,
                bvid=bvid,
                event_type=event_type,
                reason_code=reason_code,
                topic=topic,
                up_mid=up_mid,
                position=position,
                score=score,
                event_data=normalized_event_data,
            ))
            await db.commit()
        return True

    async def get_preference_state(self, session_id: str, exposure_days: int = 7) -> dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=exposure_days)
        feedback_cutoff = datetime.utcnow() - timedelta(days=180)
        async with async_session_factory() as db:
            result = await db.execute(select(RecommendationEvent).where(
                RecommendationEvent.session_id == session_id,
                (
                    RecommendationEvent.event_type.in_({*EXCLUSION_EVENTS, "unblock_topic", "unblock_up"})
                    | (
                        RecommendationEvent.event_type.in_({"impression", *POSITIVE_EVENTS})
                        & (RecommendationEvent.created_at >= feedback_cutoff)
                    )
                ),
            ))
            events = list(result.scalars())
        events.sort(key=lambda event: (event.created_at, event.id))
        active_topic_blocks: dict[str, bool] = {}
        active_concept_blocks: dict[str, bool] = {}
        active_up_blocks: dict[int, bool] = {}
        ontology = get_ontology_service()

        def event_concept_ids(event: RecommendationEvent) -> list[str]:
            payload = event.event_data if isinstance(event.event_data, dict) else {}
            stored = payload.get("concept_ids")
            if isinstance(stored, list):
                return [str(value) for value in stored if value]
            if event.topic:
                return [
                    row["concept_id"]
                    for row in ontology.link_text_v2(event.topic)["selected"]
                ]
            return []

        for event in events:
            if event.event_type == "block_topic" and event.topic:
                active_topic_blocks[event.topic] = True
                for concept_id in event_concept_ids(event):
                    active_concept_blocks[concept_id] = True
            elif event.event_type == "unblock_topic" and event.topic:
                active_topic_blocks[event.topic] = False
                for concept_id in event_concept_ids(event):
                    active_concept_blocks[concept_id] = False
            elif event.event_type == "block_up" and event.up_mid:
                active_up_blocks[event.up_mid] = True
            elif event.event_type == "unblock_up" and event.up_mid:
                active_up_blocks[event.up_mid] = False

        topic_affinity: dict[str, float] = {}
        concept_affinity: dict[str, float] = {}
        up_affinity: dict[int, float] = {}
        event_values = {
            "like": 0.7,
            "favorite": 1.0,
            "watch_later": 0.4,
            "dismiss": -0.7,
            "block_topic": -1.0,
            "block_up": -1.0,
        }
        now = datetime.utcnow()
        for event in events:
            if event.event_type not in event_values:
                continue
            if event.event_type == "block_topic" and event.topic and not active_topic_blocks.get(event.topic):
                continue
            if event.event_type == "block_up" and event.up_mid and not active_up_blocks.get(event.up_mid):
                continue
            value = event_values[event.event_type]
            half_life = 14.0 if value < 0 else 30.0
            should_affect_topic = True
            if event.event_type == "dismiss":
                value, half_life, should_affect_topic = _dismiss_effect(event.reason_code)
            if event.event_type not in {"block_topic", "block_up"}:
                age_days = max(0.0, (now - event.created_at).total_seconds() / 86400)
                value *= math.exp(-math.log(2) * age_days / half_life)
            if event.topic and should_affect_topic:
                topic_affinity[event.topic] = max(-1.0, min(1.0, topic_affinity.get(event.topic, 0.0) + value))
            if event.up_mid and should_affect_topic:
                up_affinity[event.up_mid] = max(-1.0, min(1.0, up_affinity.get(event.up_mid, 0.0) + value))
            concept_ids = event_concept_ids(event)
            if not concept_ids or not should_affect_topic:
                continue
            contributions: dict[str, float] = {}
            if event.event_type in {"favorite", "like", "watch_later"}:
                for concept_id, propagation in ontology.ancestors(
                    concept_ids, max_hops=2
                ).items():
                    contributions[concept_id] = value * propagation
            elif event.event_type == "dismiss":
                # not_relevant is intentionally local: broad parents must not
                # inherit a strong negative from one narrow mismatch.
                contributions = {concept_id: value for concept_id in concept_ids}
            elif event.event_type == "block_topic":
                if any(active_concept_blocks.get(concept_id) for concept_id in concept_ids):
                    descendants = ontology.descendants(concept_ids, max_hops=8)
                    contributions = {concept_id: -1.0 for concept_id in descendants}
            for concept_id, contribution in contributions.items():
                concept_affinity[concept_id] = max(-1.0, min(
                    1.0, concept_affinity.get(concept_id, 0.0) + contribution
                ))

        blocked_concept_ids: set[str] = set()
        for concept_id, active in active_concept_blocks.items():
            if active:
                blocked_concept_ids.update(
                    ontology.descendants([concept_id], max_hops=8)
                )

        return {
            "excluded_bvids": {
                event.bvid for event in events
                if event.event_type in {"viewed", "favorite", "dismiss"}
                or (event.event_type == "block_topic" and event.topic and active_topic_blocks.get(event.topic))
                or (event.event_type == "block_up" and event.up_mid and active_up_blocks.get(event.up_mid))
            },
            "negative_topics": {
                event.topic for event in events
                if event.topic and (
                    (event.event_type == "block_topic" and active_topic_blocks.get(event.topic))
                    or (
                        event.event_type == "dismiss"
                        and _dismiss_effect(event.reason_code)[2]
                        and event.created_at >= cutoff
                    )
                )
            },
            "negative_up_mids": {
                event.up_mid for event in events
                if event.up_mid and (
                    (event.event_type == "block_up" and active_up_blocks.get(event.up_mid))
                    or (
                        event.event_type == "dismiss"
                        and _dismiss_effect(event.reason_code)[2]
                        and event.created_at >= cutoff
                    )
                )
            },
            "blocked_topics": {
                topic for topic, active in active_topic_blocks.items() if active
            },
            "blocked_up_mids": {
                up_mid for up_mid, active in active_up_blocks.items() if active
            },
            "positive_topics": {
                event.topic for event in events
                if event.event_type in POSITIVE_EVENTS and event.topic and event.created_at >= cutoff
            },
            "positive_up_mids": {
                event.up_mid for event in events
                if event.event_type in POSITIVE_EVENTS and event.up_mid and event.created_at >= cutoff
            },
            "topic_affinity": topic_affinity,
            "concept_affinity": concept_affinity,
            "blocked_concept_ids": blocked_concept_ids,
            "positive_concept_ids": {
                concept_id for concept_id, value in concept_affinity.items() if value > 0
            },
            "negative_concept_ids": {
                concept_id for concept_id, value in concept_affinity.items() if value < 0
            },
            "up_affinity_feedback": up_affinity,
        }

    async def metrics(self, session_id: str, days: int = 30) -> dict[str, Any]:
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with async_session_factory() as db:
            result = await db.execute(
                select(RecommendationEvent).where(
                    RecommendationEvent.session_id == session_id,
                    RecommendationEvent.created_at >= cutoff,
                )
            )
            events = list(result.scalars())
            history_result = await db.execute(
                select(UserWatchHistory.bvid, UserWatchHistory.view_at).where(
                    UserWatchHistory.session_id == session_id,
                    UserWatchHistory.view_at >= int(cutoff.timestamp()),
                )
            )
            watched = list(history_result.all())
        counts = Counter(event.event_type for event in events)
        dismiss_reasons = Counter(
            event.reason_code or "unspecified" for event in events if event.event_type == "dismiss"
        )
        impressions = counts.get("impression", 0)
        clicks = counts.get("click", 0)
        impression_events = [event for event in events if event.event_type == "impression"]
        impression_bvids = [event.bvid for event in impression_events]
        repeated = max(0, len(impression_bvids) - len(set(impression_bvids)))
        channels = Counter(
            (event.event_data or {}).get("recall_source", "unknown")
            for event in impression_events
        )
        clicked_events = [event for event in events if event.event_type == "click"]
        inferred_watched_clicks = sum(
            1 for click in clicked_events
            if any(bvid == click.bvid and view_at >= int(click.created_at.timestamp()) for bvid, view_at in watched)
        )
        return {
            "window_days": days,
            "events": dict(counts),
            "dismiss_reasons": dict(dismiss_reasons),
            "ctr": round(clicks / impressions, 4) if impressions else 0.0,
            "dismiss_rate": round(counts.get("dismiss", 0) / impressions, 4) if impressions else 0.0,
            "favorite_rate": round(counts.get("favorite", 0) / impressions, 4) if impressions else 0.0,
            "repeat_exposure_rate": round(repeated / impressions, 4) if impressions else 0.0,
            "topic_coverage": len({event.topic for event in impression_events if event.topic}),
            "up_coverage": len({event.up_mid for event in impression_events if event.up_mid}),
            "channel_contribution": dict(channels),
            "inferred_watched_clicks": inferred_watched_clicks,
            "inferred_click_to_watch_rate": round(inferred_watched_clicks / clicks, 4) if clicks else 0.0,
            "observed": True,
            "watch_completion_available": False,
            "inference_note": "点击后观看由后续同步的B站历史推断，不代表播放完成率",
        }


_event_service: RecommendationEventService | None = None


def get_recommendation_event_service() -> RecommendationEventService:
    global _event_service
    if _event_service is None:
        _event_service = RecommendationEventService()
    return _event_service
