from app.services.recommendation.reason_generator import ReasonGenerator


def test_low_recency_profile_is_explained_as_historical_not_recent():
    profile = {
        "interest_tags": {"RAG": 0.08},
        "profile_evidence_mass": 0.1,
        "profile_recency_confidence": 0.0,
    }
    candidate = {
        "bvid": "OLD",
        "title": "RAG 入门",
        "recall_source": "recent_interest",
        "recall_tag": "RAG",
        "matched_concepts": [{"label": "检索增强生成"}],
    }
    reason = ReasonGenerator()._generate_default_reasons([candidate], profile)[0]["rec_reason"]
    assert "历史兴趣" in reason
    assert "近期" not in reason
