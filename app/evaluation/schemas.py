"""Strict, privacy-safe schemas for reproducible V2 evaluation data."""
from __future__ import annotations

from datetime import datetime
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


Split = Literal["train", "dev", "test"]
_FORBIDDEN_KEYS = {
    "session_id", "sessdata", "bili_jct", "csrf", "cookie", "cookies",
    "username", "uname", "email", "phone", "refresh_token",
}
_SECRET_TEXT = re.compile(
    r"(?i)(SESSDATA\s*[:=]|bili_jct\s*[:=]|refresh_token\s*[:=]|enc:v1:)"
)


def validate_public_record(record: dict[str, Any]) -> dict[str, Any]:
    """Reject direct identifiers or credential material before fixture storage."""
    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).casefold() in _FORBIDDEN_KEYS:
                    raise ValueError(f"Evaluation record contains forbidden field: {key}")
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, str) and _SECRET_TEXT.search(value):
            raise ValueError("Evaluation record contains credential-like text")

    visit(record)
    # Ensure it is JSON serializable without custom secret-bearing objects.
    json.dumps(record, ensure_ascii=False)
    return record


class EvaluationBase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"


class EntityLinkingExample(EvaluationBase):
    id: str = Field(pattern=r"^el-[A-Za-z0-9_.-]+$")
    split: Split
    domain: Literal["ai", "game", "animation", "music", "film", "knowledge", "life"]
    text: str = Field(min_length=1, max_length=5000)
    expected_concepts: list[str] = Field(default_factory=list)
    ambiguous: bool = False
    should_abstain: bool = False

    @field_validator("expected_concepts")
    @classmethod
    def concepts_are_canonical(cls, values: list[str]) -> list[str]:
        for value in values:
            if not value.startswith("https://bilibili.local/ontology/"):
                raise ValueError("Expected concepts must use canonical ontology IRIs")
        return values


class RagQaExample(EvaluationBase):
    id: str = Field(pattern=r"^qa-[A-Za-z0-9_.-]+$")
    split: Split
    question: str = Field(min_length=2, max_length=1000)
    answerable: bool
    expected_bvids: list[str] = Field(default_factory=list)
    expected_chunk_indexes: list[int] = Field(default_factory=list)
    key_facts: list[str] = Field(default_factory=list)
    expected_citation_ids: list[str] = Field(default_factory=list)
    question_type: Literal[
        "direct", "synonym", "cross_video", "negation",
        "unanswerable", "timestamp", "ambiguous",
    ] = "direct"

    @field_validator("expected_bvids")
    @classmethod
    def bvids_are_valid(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(r"BV[A-Za-z0-9]{10}", value):
                raise ValueError(f"Invalid BVID: {value}")
        return values

    @field_validator("expected_citation_ids")
    @classmethod
    def citations_are_valid(cls, values: list[str]) -> list[str]:
        for value in values:
            if not re.fullmatch(r"BV[A-Za-z0-9]{10}#\d+", value):
                raise ValueError(f"Invalid citation ID: {value}")
        return values


class RagChunkExample(EvaluationBase):
    bvid: str = Field(pattern=r"^BV[A-Za-z0-9]{10}$")
    title: str = Field(min_length=1, max_length=300)
    chunk_index: int = Field(ge=0)
    start_time: float = Field(ge=0)
    end_time: float = Field(gt=0)
    concept_ids: list[str] = Field(default_factory=list)
    content: str = Field(min_length=20, max_length=5000)

    @field_validator("concept_ids")
    @classmethod
    def chunk_concepts_are_canonical(cls, values: list[str]) -> list[str]:
        if any(not value.startswith("https://bilibili.local/ontology/") for value in values):
            raise ValueError("Chunk concepts must use canonical ontology IRIs")
        return values


class RecommendationEventExample(EvaluationBase):
    session_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    event_time: datetime
    event_type: Literal[
        "impression", "click", "viewed", "favorite", "watch_later",
        "dismiss", "block_topic", "block_up", "like",
    ]
    bvid: str = Field(pattern=r"^BV[A-Za-z0-9]{10}$")
    topic: str | None = Field(default=None, max_length=100)
    up_mid_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @field_validator("event_time")
    @classmethod
    def event_time_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("event_time must include a timezone")
        return value


class RecommendationItemExample(EvaluationBase):
    """Static candidate metadata available before the evaluation cutoff."""

    bvid: str = Field(pattern=r"^BV[A-Za-z0-9]{10}$")
    topic: str = Field(min_length=1, max_length=100)
    concept_id: str
    domain: Literal["ai", "game", "animation", "music", "film", "knowledge", "life"]
    up_mid_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    published_at: datetime
    popularity: float = Field(ge=0.0, le=1.0)
    quality: float = Field(ge=0.0, le=1.0)
    recall_source: Literal[
        "interest", "followed_up", "dynamic_feed", "vector_rediscovery"
    ]
    hydrated: bool = True

    @field_validator("concept_id")
    @classmethod
    def concept_is_canonical(cls, value: str) -> str:
        if not value.startswith("https://bilibili.local/ontology/"):
            raise ValueError("concept_id must use a canonical ontology IRI")
        return value

    @field_validator("published_at")
    @classmethod
    def published_at_is_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("published_at must include a timezone")
        return value
