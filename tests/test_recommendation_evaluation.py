from datetime import datetime

import pytest

from scripts.evaluate_recommendation import Evaluator, evaluate
from scripts.generate_recommendation_eval import CUTOFF, generate


def test_recommendation_fixture_is_strictly_time_split_and_reproducible(tmp_path):
    first = generate(tmp_path, sessions=21)
    first_events = (tmp_path / "recommendation_events.jsonl").read_bytes()
    second = generate(tmp_path, sessions=21)
    assert first["sha256"] == second["sha256"]
    assert first_events == (tmp_path / "recommendation_events.jsonl").read_bytes()
    assert first["sessions"] == 21
    assert first["items"] == 1008
    assert first["future_targets"] > 21


def test_evaluator_rejects_candidate_published_after_cutoff():
    item = {
        "bvid": "BVRC00000001", "topic": "RAG",
        "concept_id": "https://bilibili.local/ontology/RAG", "domain": "ai",
        "up_mid_hash": "a" * 64, "published_at": CUTOFF,
        "popularity": 0.5, "quality": 0.5, "recall_source": "interest", "hydrated": True,
    }
    events = [
        {"session_hash": "b" * 64, "event_time": CUTOFF.replace(year=2025), "event_type": "viewed", "bvid": item["bvid"], "topic": "RAG", "up_mid_hash": "a" * 64},
        {"session_hash": "b" * 64, "event_time": CUTOFF, "event_type": "favorite", "bvid": item["bvid"], "topic": "RAG", "up_mid_hash": "a" * 64},
    ]
    with pytest.raises(ValueError, match="future catalog leakage"):
        Evaluator([item], events, CUTOFF, 1)


def test_full_synthetic_recommendation_gate_and_ablations(tmp_path):
    generate(tmp_path, sessions=42)
    report = evaluate(tmp_path, datetime.fromisoformat("2026-06-01T00:00:00+00:00"), bootstrap=80)
    assert report["passed"]
    assert report["protocol"]["future_behavior_used_for_profile"] is False
    assert set(report["variants"]) >= {
        "baseline_v1", "full_v2", "no_time", "no_ontology", "no_clusters",
        "no_hydration", "no_dynamic", "weights_relevance", "weights_diversity",
    }
    assert all(len(bounds) == 2 for bounds in report["variants"]["full_v2"]["confidence_interval_95"].values())
    assert set(report["buckets_full_v2"]) == {"activity_bucket", "freshness_bucket", "domain_bucket"}
