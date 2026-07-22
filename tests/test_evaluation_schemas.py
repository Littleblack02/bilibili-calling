import pytest
from pydantic import ValidationError

from app.evaluation.schemas import (
    EntityLinkingExample,
    RagQaExample,
    RecommendationEventExample,
    validate_public_record,
)


def test_evaluation_schemas_accept_versioned_deidentified_records():
    entity = EntityLinkingExample.model_validate({
        "schema_version": "1.0",
        "id": "el-001",
        "split": "dev",
        "domain": "ai",
        "text": "LangGraph Agent 实战",
        "expected_concepts": ["https://bilibili.local/ontology/LangGraph"],
        "ambiguous": False,
        "should_abstain": False,
    })
    qa = RagQaExample.model_validate({
        "schema_version": "1.0",
        "id": "qa-001",
        "split": "dev",
        "question": "RAG 的索引阶段包括什么？",
        "answerable": True,
        "expected_bvids": ["BV1TEST00001"],
        "key_facts": ["切分", "向量化"],
    })
    rec = RecommendationEventExample.model_validate({
        "schema_version": "1.0",
        "session_hash": "a" * 64,
        "event_time": "2026-07-20T10:00:00Z",
        "event_type": "viewed",
        "bvid": "BV1TEST00001",
    })
    assert entity.schema_version == qa.schema_version == rec.schema_version == "1.0"


def test_evaluation_records_reject_direct_identifiers_and_secrets():
    with pytest.raises(ValueError):
        validate_public_record({
            "schema_version": "1.0",
            "session_id": "real-session",
            "text": "SESSDATA=private-cookie",
        })
    with pytest.raises(ValidationError):
        RecommendationEventExample.model_validate({
            "schema_version": "1.0",
            "session_hash": "not-a-sha256",
            "event_time": "2026-07-20T10:00:00Z",
            "event_type": "viewed",
            "bvid": "BV1TEST00001",
        })
