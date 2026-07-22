from datetime import datetime, timedelta

from app.services.recommendation.profile_schema import normalize_profile
from app.services.recommendation.ranking import blend_llm_scores, diversify, score_candidates


def _candidates():
    now = datetime.utcnow()
    return [
        {
            "bvid": "BV_AI_1", "title": "AI Agent 实战教程", "mid": 1,
            "author": "教程UP", "play": 50_000, "pubdate": now - timedelta(days=2),
            "recall_source": "interest", "recall_tag": "AI",
        },
        {
            "bvid": "BV_AI_2", "title": "AI 入门", "mid": 1,
            "author": "教程UP", "play": 20_000, "pubdate": now - timedelta(days=5),
            "recall_source": "interest", "recall_tag": "AI",
        },
        {
            "bvid": "BV_AI_3", "title": "AI 新闻", "mid": 1,
            "author": "教程UP", "play": 10_000, "pubdate": now - timedelta(days=1),
            "recall_source": "interest", "recall_tag": "AI",
        },
        {
            "bvid": "BV_MUSIC", "title": "今日音乐现场", "mid": 2,
            "author": "音乐UP", "play": 1_000_000, "pubdate": now,
            "recall_source": "trending", "recall_category": "音乐",
        },
    ]


def test_profile_schema_unifies_legacy_fields():
    profile = normalize_profile({
        "unified_tags": {"AI": 0.8},
        "recent_interests": {"Agent": 1.0},
    })
    legacy = profile.as_legacy_dict()
    assert legacy["interest_tags"] == {"AI": 0.8, "Agent": 1.0}
    assert legacy["top_interests"][0] == ("Agent", 1.0)


def test_profile_schema_preserves_v2_absolute_relative_and_confidence_fields():
    rag = "https://bilibili.local/ontology/RAG"
    profile = normalize_profile({"profile_features": {
        "concept_absolute_affinities": {rag: 0.2},
        "concept_relative_shares": {rag: 1.0},
        "recent_concept_absolute_affinities": {},
        "recent_concept_relative_shares": {},
        "profile_evidence_mass": 0.3,
        "profile_recency_confidence": 0.0,
        "calibration": {"tau": 1.5},
    }})
    assert profile.concept_absolute_affinities == {rag: 0.2}
    assert profile.concept_relative_shares == {rag: 1.0}
    assert profile.profile_evidence_mass == 0.3
    assert profile.profile_recency_confidence == 0.0
    legacy = profile.as_legacy_dict()
    assert legacy["concept_absolute_affinities"] == {rag: 0.2}
    assert legacy["calibration"] == {"tau": 1.5}


def test_ontology_and_multi_interest_features_affect_candidate_score():
    ai = "https://bilibili.local/ontology/ArtificialIntelligence"
    llm = "https://bilibili.local/ontology/LargeLanguageModel"
    profile = normalize_profile({
        "profile_features": {
            "concept_affinities": {ai: 1.0},
            "recent_concept_affinities": {llm: 0.9},
            "multi_interests": [{
                "concept_id": ai,
                "label": "人工智能",
                "weight": 1.0,
                "concepts": [{"concept_id": llm, "label": "大语言模型", "weight": 1.0}],
            }],
        }
    })
    candidates = [
        {"bvid": "AI", "title": "大语言模型入门", "mid": 1, "recall_source": "trending"},
        {"bvid": "MUSIC", "title": "音乐现场", "mid": 2, "recall_source": "trending"},
    ]
    ranked = score_candidates(candidates, profile)
    assert ranked[0]["bvid"] == "AI"
    assert ranked[0]["feature_scores"]["ontology_match"] > 0
    assert ranked[0]["feature_scores"]["multi_interest"] > 0
    assert ranked[0]["matched_concepts"]


def test_multi_interest_uses_temperature_attention_across_matching_clusters():
    langgraph = "https://bilibili.local/ontology/LangGraph"
    python = "https://bilibili.local/ontology/Python"
    profile = normalize_profile({"profile_features": {
        "multi_interests": [
            {
                "concept_id": "agent",
                "label": "AI智能体",
                "weight": 0.9,
                "concepts": [{"concept_id": langgraph, "weight": 0.9}],
            },
            {
                "concept_id": "programming",
                "label": "编程",
                "weight": 0.6,
                "concepts": [{"concept_id": python, "weight": 0.6}],
            },
        ]
    }})
    item = score_candidates([
        {"bvid": "BOTH", "title": "LangGraph Python 实战", "recall_source": "trending"}
    ], profile)[0]
    matches = item["matched_interest_clusters"]
    assert len(matches) == 2
    assert abs(sum(match["attention_weight"] for match in matches) - 1.0) < 0.0002
    scores = [match["score"] for match in matches]
    assert min(scores) < item["feature_scores"]["multi_interest"] < max(scores)


def test_legacy_weight_config_is_merged_with_new_features():
    profile = normalize_profile({"interest_tags": {"AI": 1.0}})
    ranked = score_candidates(_candidates(), profile, weights={"content_match": 1.0})
    assert ranked
    assert all("ontology_match" in item["feature_scores"] for item in ranked)


def test_negative_feedback_lowers_related_score():
    profile = normalize_profile({"interest_tags": {"AI": 1.0}})
    baseline = score_candidates(_candidates(), profile)
    penalized = score_candidates(_candidates(), profile, negative_topics={"AI"})
    baseline_score = next(item["rec_score"] for item in baseline if item["bvid"] == "BV_AI_1")
    penalized_item = next(item for item in penalized if item["bvid"] == "BV_AI_1")
    assert penalized_item["rec_score"] < baseline_score
    assert penalized_item["negative_penalty"] == 0.35


def test_positive_feedback_boosts_related_topic():
    profile = normalize_profile({"interest_tags": {"AI": 0.5}})
    baseline = score_candidates(_candidates(), profile)
    boosted = score_candidates(_candidates(), profile, positive_topics={"AI"}, positive_up_mids={1})
    baseline_score = next(item["rec_score"] for item in baseline if item["bvid"] == "BV_AI_1")
    boosted_item = next(item for item in boosted if item["bvid"] == "BV_AI_1")
    assert boosted_item["rec_score"] > baseline_score
    assert boosted_item["feedback_bonus"] == 0.25


def test_weighted_feedback_affinity_changes_score():
    profile = normalize_profile({"interest_tags": {"AI": 0.8}})
    negative = score_candidates(_candidates(), profile, topic_affinity={"AI": -0.6})
    positive = score_candidates(_candidates(), profile, topic_affinity={"AI": 0.6})
    negative_score = next(item["rec_score"] for item in negative if item["bvid"] == "BV_AI_1")
    positive_item = next(item for item in positive if item["bvid"] == "BV_AI_1")
    assert positive_item["rec_score"] > negative_score
    assert positive_item["feedback_affinity"] == 0.6


def test_diversity_limits_same_up_and_fills_top_k():
    profile = normalize_profile({"interest_tags": {"AI": 1.0}})
    ranked = score_candidates(_candidates(), profile)
    result = diversify(ranked, limit=3, max_per_up=2)
    assert len(result) == 3
    assert sum(item["mid"] == 1 for item in result) <= 2
    assert any(item["mid"] == 2 for item in result)


def test_rule_scores_remain_distinct_without_llm():
    profile = normalize_profile({"interest_tags": {"AI": 1.0}})
    ranked = score_candidates(_candidates(), profile)
    assert len({item["rec_score"] for item in ranked}) > 1
    assert all("feature_scores" in item for item in ranked)


def test_uniform_or_invalid_llm_scores_preserve_rule_order_and_differences():
    profile = normalize_profile({"interest_tags": {"AI": 1.0}})
    ranked = score_candidates(_candidates(), profile)
    llm = [
        {"bvid": item["bvid"], "rec_score": 0.5 if index else "not-a-number"}
        for index, item in enumerate(ranked)
    ]
    blended = blend_llm_scores(ranked, llm, llm_weight=0.25)
    assert [item["bvid"] for item in blended] == [item["bvid"] for item in ranked]
    assert len({item["rec_score"] for item in blended}) > 1


def test_quality_uses_view_velocity_instead_of_raw_popularity_only():
    now = datetime.utcnow()
    profile = normalize_profile({})
    candidates = [
        {
            "bvid": "BV_NEW", "title": "新视频", "mid": 10, "play": 80_000,
            "pubdate": now - timedelta(days=1), "recall_source": "trending",
        },
        {
            "bvid": "BV_OLD", "title": "老视频", "mid": 11, "play": 1_000_000,
            "pubdate": now - timedelta(days=365), "recall_source": "trending",
        },
    ]
    ranked = score_candidates(candidates, profile, now=now)
    by_bvid = {item["bvid"]: item for item in ranked}
    assert by_bvid["BV_NEW"]["feature_scores"]["quality"] > by_bvid["BV_OLD"]["feature_scores"]["quality"]


def test_diversity_rewards_source_and_duration_coverage():
    candidates = [
        {"bvid": "A", "title": "AI 教程一", "mid": 1, "rec_score": 0.90, "recall_source": "interest", "duration": 900},
        {"bvid": "B", "title": "AI 教程二", "mid": 2, "rec_score": 0.89, "recall_source": "interest", "duration": 800},
        {"bvid": "C", "title": "音乐现场", "mid": 3, "rec_score": 0.87, "recall_source": "trending", "duration": 180},
    ]
    result = diversify(candidates, limit=2, max_per_up=1, diversity_strength=0.3)
    assert {item["recall_source"] for item in result} == {"interest", "trending"}
    assert {"medium", "short"} == {
        "short" if item["duration"] < 300 else "medium" for item in result
    }


def test_cold_start_still_returns_ranked_exploration_results():
    profile = normalize_profile({})
    ranked = score_candidates(_candidates(), profile, exploration_level=0.7)
    result = diversify(ranked, limit=3, max_per_up=2)
    assert len(result) == 3
    assert all(item["feature_scores"]["exploration"] == 0.7 for item in result)
    assert len({item["rec_score"] for item in result}) > 1
