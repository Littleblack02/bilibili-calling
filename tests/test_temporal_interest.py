from datetime import datetime, timedelta

from app.services.recommendation.temporal_interest import (
    build_temporal_ontology_features,
    temporal_weight,
)


RAG = "https://bilibili.local/ontology/RAG"


def test_old_favorites_and_bangumi_do_not_dominate_recent_consumption():
    now = datetime(2026, 7, 20)
    recent_history, _ = temporal_weight(
        "history", {"occurred_at": now - timedelta(days=1)}, now=now
    )
    old_favorite, _ = temporal_weight(
        "favorites", {"occurred_at": now - timedelta(days=730)}, now=now
    )
    old_bangumi, _ = temporal_weight(
        "bangumi", {"occurred_at": now - timedelta(days=730)}, now=now
    )
    assert recent_history > old_favorite
    assert recent_history > old_bangumi
    assert old_favorite > 0  # durable evidence keeps a small floor


def test_unknown_timestamp_is_not_marked_recent():
    _, details = temporal_weight("favorites", {}, now=datetime(2026, 7, 20))
    assert details["time_known"] is False
    assert details["age_days"] > 45


def test_profile_builds_multiple_semantic_interest_clusters():
    now = datetime(2026, 7, 20)
    features = build_temporal_ontology_features({
        "history": [
            {"title": "LangGraph AI Agent 实战", "occurred_at": now - timedelta(days=1)},
            {"title": "家常美食做饭教程", "occurred_at": now - timedelta(days=2)},
        ]
    }, now=now)
    labels = {cluster["label"] for cluster in features["multi_interests"]}
    assert len(labels) >= 2
    assert features["recent_concept_affinities"]
    assert features["source_freshness"]["history"]["timestamp_coverage"] == 1.0


def test_v2_old_singleton_keeps_low_absolute_affinity_and_recency_confidence():
    now = datetime(2026, 7, 20)
    features = build_temporal_ontology_features({
        "favorites": [{
            "bvid": "BV1OLD000001",
            "title": "RAG",
            "occurred_at": now - timedelta(days=730),
        }]
    }, now=now, v2_enabled=True)
    assert 0 < features["concept_absolute_affinities"][RAG] < 0.25
    assert features["concept_affinities"][RAG] < 0.25
    assert features["concept_relative_shares"][RAG] == 1.0
    assert features["profile_recency_confidence"] < 0.1


def test_v2_old_favorite_is_at_most_quarter_of_recent_history_for_same_concept():
    now = datetime(2026, 7, 20)
    old = build_temporal_ontology_features({
        "favorites": [{"title": "RAG", "occurred_at": now - timedelta(days=730)}]
    }, now=now, v2_enabled=True)
    recent = build_temporal_ontology_features({
        "history": [{"title": "RAG", "occurred_at": now - timedelta(days=1)}]
    }, now=now, v2_enabled=True)
    assert (
        old["concept_absolute_affinities"][RAG]
        / recent["concept_absolute_affinities"][RAG]
        <= 0.25
    )


def test_v2_deduplicates_same_content_and_exposure_has_no_positive_affinity():
    now = datetime(2026, 7, 20)
    item = {"bvid": "BV1DEDUP0001", "title": "RAG", "occurred_at": now - timedelta(days=1)}
    once = build_temporal_ontology_features({"history": [item]}, now=now, v2_enabled=True)
    repeated = build_temporal_ontology_features({"history": [item, dict(item)]}, now=now, v2_enabled=True)
    correlated = build_temporal_ontology_features(
        {"history": [item], "favorites": [dict(item)]}, now=now, v2_enabled=True
    )
    favorite_only = build_temporal_ontology_features(
        {"favorites": [item]}, now=now, v2_enabled=True
    )
    exposure_only = build_temporal_ontology_features(
        {"dynamic_feed": [item]}, now=now, v2_enabled=True
    )
    assert repeated["concept_raw_scores"][RAG] == once["concept_raw_scores"][RAG]
    assert correlated["concept_raw_scores"][RAG] > once["concept_raw_scores"][RAG]
    assert correlated["concept_raw_scores"][RAG] < (
        once["concept_raw_scores"][RAG] + favorite_only["concept_raw_scores"][RAG]
    )
    assert exposure_only["concept_absolute_affinities"] == {}


def test_v2_unknown_time_is_not_recent_and_empty_profile_is_finite():
    features = build_temporal_ontology_features(
        {"favorites": [{"title": "RAG"}]},
        now=datetime(2026, 7, 20),
        v2_enabled=True,
    )
    assert features["recent_concept_absolute_affinities"] == {}
    assert features["profile_recency_confidence"] == 0.0
    empty = build_temporal_ontology_features({}, now=datetime(2026, 7, 20), v2_enabled=True)
    assert empty["concept_absolute_affinities"] == {}
    assert empty["concept_relative_shares"] == {}
    assert empty["profile_evidence_mass"] == 0.0
    assert empty["profile_recency_confidence"] == 0.0


def test_v2_clusters_stop_at_meaningful_intermediate_concepts():
    now = datetime(2026, 7, 20)
    features = build_temporal_ontology_features({
        "history": [
            {"title": "LangGraph", "occurred_at": now - timedelta(days=1)},
            {"title": "Python", "occurred_at": now - timedelta(days=1)},
            {"title": "音乐", "occurred_at": now - timedelta(days=1)},
        ]
    }, now=now, v2_enabled=True)
    labels = {cluster["label"] for cluster in features["multi_interests"]}
    assert {"AI智能体", "编程", "音乐"}.issubset(labels)
    assert "科技" not in labels
    assert all("evidence_mass" in cluster for cluster in features["multi_interests"])
    assert all("recent_weight" in cluster for cluster in features["multi_interests"])
