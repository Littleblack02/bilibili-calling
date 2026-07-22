"""推荐系统内部使用的稳定用户画像结构。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RecommendationProfile(BaseModel):
    long_term_interests: dict[str, float] = Field(default_factory=dict)
    recent_interests: dict[str, float] = Field(default_factory=dict)
    current_intent: str | None = None
    followed_ups: list[dict[str, Any]] = Field(default_factory=list)
    category_distribution: dict[str, float] = Field(default_factory=dict)
    blocked_topics: list[str] = Field(default_factory=list)
    blocked_up_mids: list[int] = Field(default_factory=list)
    confidence_score: float = 0.0
    updated_at: datetime | None = None
    concept_affinities: dict[str, float] = Field(default_factory=dict)
    recent_concept_affinities: dict[str, float] = Field(default_factory=dict)
    concept_absolute_affinities: dict[str, float] = Field(default_factory=dict)
    concept_relative_shares: dict[str, float] = Field(default_factory=dict)
    recent_concept_absolute_affinities: dict[str, float] = Field(default_factory=dict)
    recent_concept_relative_shares: dict[str, float] = Field(default_factory=dict)
    profile_evidence_mass: float = 0.0
    profile_recency_confidence: float = 0.0
    calibration: dict[str, Any] = Field(default_factory=dict)
    multi_interests: list[dict[str, Any]] = Field(default_factory=list)
    source_freshness: dict[str, dict[str, Any]] = Field(default_factory=dict)
    ontology_version: str | None = None
    profile_model: str | None = None

    @property
    def interest_tags(self) -> dict[str, float]:
        """合并长期和近期兴趣，近期兴趣优先。"""
        merged = dict(self.long_term_interests)
        for tag, score in self.recent_interests.items():
            merged[tag] = max(float(score), float(merged.get(tag, 0.0)))
        return merged

    def as_legacy_dict(self) -> dict[str, Any]:
        tags = self.interest_tags
        return {
            "interest_tags": tags,
            "top_interests": sorted(tags.items(), key=lambda item: item[1], reverse=True)[:10],
            "recent_interests": self.recent_interests,
            "current_intent": self.current_intent,
            "followed_ups": self.followed_ups,
            "category_distribution": self.category_distribution,
            "blocked_topics": self.blocked_topics,
            "blocked_up_mids": self.blocked_up_mids,
            "confidence_score": self.confidence_score,
            "updated_at": self.updated_at,
            "concept_affinities": self.concept_affinities,
            "recent_concept_affinities": self.recent_concept_affinities,
            "concept_absolute_affinities": self.concept_absolute_affinities,
            "concept_relative_shares": self.concept_relative_shares,
            "recent_concept_absolute_affinities": self.recent_concept_absolute_affinities,
            "recent_concept_relative_shares": self.recent_concept_relative_shares,
            "profile_evidence_mass": self.profile_evidence_mass,
            "profile_recency_confidence": self.profile_recency_confidence,
            "calibration": self.calibration,
            "multi_interests": self.multi_interests,
            "source_freshness": self.source_freshness,
            "ontology_version": self.ontology_version,
            "profile_model": self.profile_model,
        }


def normalize_profile(raw: dict[str, Any] | None) -> RecommendationProfile:
    raw = raw or {}
    features = raw.get("profile_features") if isinstance(raw.get("profile_features"), dict) else {}
    long_term = (
        raw.get("long_term_interests")
        or raw.get("unified_tags")
        or raw.get("interest_tags")
        or {}
    )
    recent = raw.get("recent_interests") or raw.get("recent_tags") or {}
    updated_at = raw.get("updated_at")
    if isinstance(updated_at, str):
        try:
            updated_at = datetime.fromisoformat(updated_at)
        except ValueError:
            updated_at = None
    def numeric_scores(values: Any) -> dict[str, float]:
        if not isinstance(values, dict):
            return {}
        scores: dict[str, float] = {}
        for key, value in values.items():
            if isinstance(value, (int, float)):
                scores[str(key)] = float(value)
        return scores

    return RecommendationProfile(
        long_term_interests=numeric_scores(long_term),
        recent_interests=numeric_scores(recent),
        current_intent=raw.get("current_intent"),
        followed_ups=raw.get("followed_ups") or [],
        category_distribution=raw.get("category_distribution") or {},
        blocked_topics=raw.get("blocked_topics") or [],
        blocked_up_mids=raw.get("blocked_up_mids") or [],
        confidence_score=float(raw.get("confidence_score") or 0.0),
        updated_at=updated_at,
        concept_affinities=numeric_scores(
            raw.get("concept_affinities") or features.get("concept_affinities") or {}
        ),
        recent_concept_affinities=numeric_scores(
            raw.get("recent_concept_affinities")
            or features.get("recent_concept_affinities")
            or {}
        ),
        concept_absolute_affinities=numeric_scores(
            raw.get("concept_absolute_affinities")
            or features.get("concept_absolute_affinities")
            or raw.get("concept_affinities")
            or features.get("concept_affinities")
            or {}
        ),
        concept_relative_shares=numeric_scores(
            raw.get("concept_relative_shares")
            or features.get("concept_relative_shares")
            or {}
        ),
        recent_concept_absolute_affinities=numeric_scores(
            raw.get("recent_concept_absolute_affinities")
            or features.get("recent_concept_absolute_affinities")
            or raw.get("recent_concept_affinities")
            or features.get("recent_concept_affinities")
            or {}
        ),
        recent_concept_relative_shares=numeric_scores(
            raw.get("recent_concept_relative_shares")
            or features.get("recent_concept_relative_shares")
            or {}
        ),
        profile_evidence_mass=float(
            raw.get("profile_evidence_mass")
            or features.get("profile_evidence_mass")
            or 0.0
        ),
        profile_recency_confidence=float(
            raw.get("profile_recency_confidence")
            or features.get("profile_recency_confidence")
            or 0.0
        ),
        calibration=(raw.get("calibration") or features.get("calibration") or {}),
        multi_interests=(
            raw.get("multi_interests") or features.get("multi_interests") or []
        ),
        source_freshness=(
            raw.get("source_freshness") or features.get("source_freshness") or {}
        ),
        ontology_version=raw.get("ontology_version") or features.get("ontology_version"),
        profile_model=raw.get("profile_model") or features.get("model"),
    )
