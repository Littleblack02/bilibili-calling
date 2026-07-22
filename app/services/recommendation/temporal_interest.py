"""Time-aware multi-interest user modeling.

This is a deterministic production bridge to the mechanisms used by temporal
attention and multi-interest recommenders: every behavior is weighted by what
it was, when it happened, and which semantic interest cluster it supports.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
import math
from typing import Any, Iterable

from app.config import settings
from app.services.ontology import OntologyService, get_ontology_service
from app.services.profile.signals import parse_datetime


@dataclass(frozen=True)
class SourcePolicy:
    base_weight: float
    half_life_days: float
    floor: float
    recent_window_days: float
    semantics: str


SOURCE_POLICIES: dict[str, SourcePolicy] = {
    # Explicit and recent actions are strongest. Old durable actions keep a
    # small floor instead of permanently dominating the profile.
    "history": SourcePolicy(1.00, 10, 0.00, 21, "consumed"),
    "live_history": SourcePolicy(0.85, 7, 0.00, 14, "consumed"),
    "watchlater": SourcePolicy(0.82, 30, 0.05, 45, "intent"),
    "favorites": SourcePolicy(0.90, 150, 0.10, 45, "durable_interest"),
    "bangumi": SourcePolicy(0.78, 120, 0.08, 45, "durable_interest"),
    "cinema": SourcePolicy(0.68, 180, 0.08, 45, "durable_interest"),
    "manga": SourcePolicy(0.72, 120, 0.08, 45, "durable_interest"),
    "favorite_topics": SourcePolicy(0.76, 120, 0.08, 45, "durable_interest"),
    "favorite_articles": SourcePolicy(0.74, 120, 0.08, 45, "durable_interest"),
    "favorite_courses": SourcePolicy(0.86, 180, 0.10, 60, "intent"),
    "favorite_notes": SourcePolicy(0.80, 120, 0.08, 45, "intent"),
    "favorite_collections": SourcePolicy(0.74, 180, 0.08, 45, "durable_interest"),
    "subscribed_tags": SourcePolicy(0.72, 240, 0.12, 60, "durable_interest"),
    "courses": SourcePolicy(0.88, 240, 0.12, 60, "intent"),
    "fan_medals": SourcePolicy(0.68, 180, 0.10, 45, "creator_affinity"),
    "special_followings": SourcePolicy(0.72, 365, 0.15, 60, "creator_affinity"),
    "whisper_followings": SourcePolicy(0.50, 365, 0.10, 60, "creator_affinity"),
    "followings": SourcePolicy(0.34, 365, 0.08, 45, "creator_affinity"),
    # Seeing a followed feed item is exposure, not preference; keep it weak.
    "dynamic_feed": SourcePolicy(0.10, 2, 0.00, 3, "exposure"),
}


DEFAULT_POLICY = SourcePolicy(0.45, 90, 0.05, 30, "consumed")


def policy_for(source: str) -> SourcePolicy:
    return SOURCE_POLICIES.get(source, DEFAULT_POLICY)


def item_occurred_at(item: dict[str, Any]) -> datetime | None:
    for field in (
        "occurred_at", "view_at", "fav_time", "favorited_at", "add_time",
        "mtime", "pubtime", "pubdate", "ctime", "updated_at", "created_at",
    ):
        parsed = parse_datetime(item.get(field))
        if parsed:
            return parsed
    payload = item.get("payload")
    if isinstance(payload, dict):
        for field in ("occurred_at", "view_at", "add_time", "mtime", "ctime"):
            parsed = parse_datetime(payload.get(field))
            if parsed:
                return parsed
    return None


def temporal_weight(
    source: str,
    item: dict[str, Any],
    now: datetime | None = None,
) -> tuple[float, dict[str, Any]]:
    now = now or datetime.utcnow()
    policy = policy_for(source)
    occurred_at = item_occurred_at(item)
    if occurred_at is None:
        # Unknown timestamps must not masquerade as recent. Use a conservative
        # prior appropriate for durable vs. ephemeral sources.
        assumed_age = policy.half_life_days * (2.0 if policy.floor else 1.0)
        age_days = assumed_age
        time_known = False
    else:
        age_days = max(0.0, (now - occurred_at).total_seconds() / 86400.0)
        time_known = True
    decay = math.exp(-math.log(2.0) * age_days / max(1.0, policy.half_life_days))
    recency = policy.floor + (1.0 - policy.floor) * decay
    raw_strength = item.get("strength", 1.0)
    try:
        strength = max(0.0, min(2.0, float(raw_strength)))
    except (TypeError, ValueError):
        strength = 1.0
    weight = max(0.0, min(1.5, policy.base_weight * recency * strength))
    return round(weight, 6), {
        "source": source,
        "semantics": policy.semantics,
        "occurred_at": occurred_at.isoformat() if occurred_at else None,
        "time_known": time_known,
        "age_days": round(age_days, 2),
        "recency": round(recency, 6),
        "base_weight": policy.base_weight,
        "half_life_days": policy.half_life_days,
        "final_weight": round(weight, 6),
    }


def _item_text(item: dict[str, Any]) -> str:
    tags = item.get("tags") or []
    if isinstance(tags, dict):
        tags = list(tags)
    if not isinstance(tags, list):
        tags = [str(tags)]
    return " ".join(filter(None, [
        str(item.get("title") or ""),
        str(item.get("description") or ""),
        str(item.get("tname") or item.get("category") or ""),
        " ".join(str(tag) for tag in tags[:20]),
    ]))


def _content_identity(source: str, item: dict[str, Any], index: int) -> str:
    """Use a channel-independent identity when available for correlation control."""
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
    for field in ("bvid", "aid", "season_id", "ep_id"):
        value = item.get(field) or payload.get(field)
        if value not in (None, ""):
            return f"{field}:{value}"
    # Generic IDs are often channel-local and must not accidentally merge
    # unrelated objects from different APIs.
    for field in ("id", "item_id"):
        value = item.get(field) or payload.get(field)
        if value not in (None, ""):
            return f"{source}:{field}:{value}"
    return f"{source}:anonymous:{index}"


def _correlated_strength(values: Iterable[float], secondary_discount: float) -> float:
    """Bound correlated signals using strongest evidence plus discounted noisy-OR."""
    ordered = sorted((max(0.0, float(value)) for value in values if value > 0), reverse=True)
    if not ordered:
        return 0.0
    combined = min(0.999999, ordered[0])
    for secondary in ordered[1:]:
        discounted = min(0.999999, secondary * secondary_discount)
        combined = 1.0 - (1.0 - combined) * (1.0 - discounted)
    return combined


def _bounded_affinities(
    scores: dict[str, float], tau: float, limit: int = 40
) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    ranked = sorted(scores.items(), key=lambda row: row[1], reverse=True)[:limit]
    retained = {concept_id: max(0.0, score) for concept_id, score in ranked if score > 0}
    total = sum(retained.values())
    absolute = {
        concept_id: round(1.0 - math.exp(-score / tau), 6)
        for concept_id, score in retained.items()
    }
    shares = {
        concept_id: round(score / total, 6)
        for concept_id, score in retained.items()
    } if total > 0 else {}
    raw = {concept_id: round(score, 6) for concept_id, score in retained.items()}
    return raw, absolute, shares


def _build_v2_features(
    data_sources: dict[str, list[dict[str, Any]]],
    ontology: OntologyService,
    now: datetime,
    evidence_limit: int,
) -> dict[str, Any]:
    tau = float(settings.temporal_affinity_tau)
    secondary_discount = float(settings.temporal_secondary_signal_discount)
    grouped: dict[str, list[dict[str, Any]]] = {}
    evidence: list[dict[str, Any]] = []
    source_stats: dict[str, dict[str, Any]] = {}

    for source, items in data_sources.items():
        if not isinstance(items, list):
            continue
        source_weights: list[float] = []
        known_times = 0
        newest: datetime | None = None
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            weight, details = temporal_weight(source, item, now=now)
            source_weights.append(weight)
            occurred_at = item_occurred_at(item)
            if occurred_at:
                known_times += 1
                newest = max(newest, occurred_at) if newest else occurred_at
            policy = policy_for(source)
            # Exposure is useful for fatigue/candidate control but is never
            # positive preference evidence.
            effective_weight = 0.0 if policy.semantics == "exposure" else weight
            matches = ontology.resolve_text(_item_text(item), limit=12)
            identity = _content_identity(source, item, index)
            grouped.setdefault(identity, []).append({
                "source": source,
                "semantics": policy.semantics,
                "weight": effective_weight,
                "details": details,
                "matches": matches,
                "item": item,
                "identity": identity,
                "is_recent": bool(
                    occurred_at is not None
                    and details["age_days"] <= policy.recent_window_days
                ),
            })
            if matches and len(evidence) < evidence_limit:
                for match in matches:
                    if len(evidence) >= evidence_limit:
                        break
                    evidence.append({
                        "concept_id": match.concept_id,
                        "concept_label": match.label,
                        "source": source,
                        "semantics": policy.semantics,
                        "deduplication_group": identity,
                        "item_id": str(item.get("bvid") or item.get("id") or item.get("item_id") or ""),
                        "title": str(item.get("title") or "")[:200],
                        "pre_dedup_contribution": round(effective_weight * match.confidence, 6),
                        **details,
                    })
        source_stats[source] = {
            "count": len(items),
            "average_effective_weight": round(sum(source_weights) / len(source_weights), 4) if source_weights else 0.0,
            "timestamp_coverage": round(known_times / len(items), 4) if items else 0.0,
            "newest_at": newest.isoformat() if newest else None,
            "policy": asdict(policy_for(source)),
        }

    concept_scores: dict[str, float] = {}
    recent_scores: dict[str, float] = {}
    concept_latest: dict[str, datetime] = {}
    evidence_mass = 0.0
    recent_mass = 0.0
    contribution_details: list[dict[str, Any]] = []

    for identity, signals in grouped.items():
        # Collapse repeated rows within the same semantic group first. This
        # makes re-running a sync or saving one video in two folders idempotent.
        semantic_masses: dict[str, float] = {}
        recent_semantic_masses: dict[str, float] = {}
        concept_semantics: dict[str, dict[str, float]] = {}
        recent_concept_semantics: dict[str, dict[str, float]] = {}
        for signal in signals:
            semantics = signal["semantics"]
            weight = float(signal["weight"])
            semantic_masses[semantics] = max(semantic_masses.get(semantics, 0.0), weight)
            if signal["is_recent"]:
                recent_semantic_masses[semantics] = max(
                    recent_semantic_masses.get(semantics, 0.0), weight
                )
            occurred_at = item_occurred_at(signal["item"])
            for match in signal["matches"]:
                contribution = weight * match.confidence
                by_semantic = concept_semantics.setdefault(match.concept_id, {})
                by_semantic[semantics] = max(by_semantic.get(semantics, 0.0), contribution)
                if signal["is_recent"]:
                    recent_by_semantic = recent_concept_semantics.setdefault(match.concept_id, {})
                    recent_by_semantic[semantics] = max(
                        recent_by_semantic.get(semantics, 0.0), contribution
                    )
                if occurred_at:
                    previous = concept_latest.get(match.concept_id)
                    concept_latest[match.concept_id] = max(previous, occurred_at) if previous else occurred_at

        group_mass = _correlated_strength(semantic_masses.values(), secondary_discount)
        group_recent_mass = _correlated_strength(recent_semantic_masses.values(), secondary_discount)
        evidence_mass += group_mass
        recent_mass += group_recent_mass
        for concept_id, by_semantic in concept_semantics.items():
            combined = _correlated_strength(by_semantic.values(), secondary_discount)
            if combined <= 0:
                continue
            concept_scores[concept_id] = concept_scores.get(concept_id, 0.0) + combined
            recent_combined = _correlated_strength(
                recent_concept_semantics.get(concept_id, {}).values(), secondary_discount
            )
            if recent_combined > 0:
                recent_scores[concept_id] = recent_scores.get(concept_id, 0.0) + recent_combined
            contribution_details.append({
                "deduplication_group": identity,
                "concept_id": concept_id,
                "semantic_groups": dict(sorted(by_semantic.items())),
                "combined_contribution": round(combined, 6),
                "recent_contribution": round(recent_combined, 6),
            })

    raw_scores, absolute, shares = _bounded_affinities(concept_scores, tau)
    recent_raw, recent_absolute, recent_shares = _bounded_affinities(recent_scores, tau)
    recency_confidence = 0.0
    if evidence_mass > 0 and recent_mass > 0:
        recent_coverage = min(1.0, recent_mass / evidence_mass)
        recency_confidence = recent_coverage * (1.0 - math.exp(-recent_mass / tau))

    clusters: dict[str, dict[str, Any]] = {}
    for concept_id, affinity in absolute.items():
        cluster = ontology.top_cluster(
            concept_id, max_hops=int(settings.interest_cluster_max_hops)
        ) or {"concept_id": concept_id, "label": concept_id}
        row = clusters.setdefault(cluster["concept_id"], {
            "concept_id": cluster["concept_id"],
            "label": cluster["label"],
            "weight": 0.0,
            "recent_weight": 0.0,
            "evidence_mass": 0.0,
            "relative_share": 0.0,
            "last_occurred_at": None,
            "concepts": [],
        })
        row["weight"] = 1.0 - (1.0 - row["weight"]) * (1.0 - affinity)
        recent_affinity = recent_absolute.get(concept_id, 0.0)
        row["recent_weight"] = 1.0 - (
            (1.0 - row["recent_weight"]) * (1.0 - recent_affinity)
        )
        row["evidence_mass"] += raw_scores.get(concept_id, 0.0)
        row["relative_share"] += shares.get(concept_id, 0.0)
        occurred_at = concept_latest.get(concept_id)
        if occurred_at:
            current = parse_datetime(row["last_occurred_at"])
            latest = max(current, occurred_at) if current else occurred_at
            row["last_occurred_at"] = latest.isoformat()
        concept = ontology.concept(concept_id) or {"label": concept_id}
        row["concepts"].append({
            "concept_id": concept_id,
            "label": concept["label"],
            "weight": affinity,
            "recent_weight": recent_affinity,
            "evidence_mass": raw_scores.get(concept_id, 0.0),
            "relative_share": shares.get(concept_id, 0.0),
        })

    multi_interests: list[dict[str, Any]] = []
    for row in clusters.values():
        row["concepts"] = sorted(
            row["concepts"], key=lambda item: item["weight"], reverse=True
        )[:8]
        for field in ("weight", "recent_weight", "evidence_mass", "relative_share"):
            row[field] = round(row[field], 6)
        multi_interests.append(row)
    multi_interests.sort(key=lambda row: row["weight"], reverse=True)

    return {
        "schema_version": "2.0",
        "model": "temporal-multi-interest-ontology-v2",
        "ontology_version": ontology.VERSION,
        "generated_at": now.isoformat(),
        # Compatibility fields now hold bounded absolute values; they are no
        # longer divided by the strongest concept in a profile.
        "concept_affinities": absolute,
        "recent_concept_affinities": recent_absolute,
        "concept_raw_scores": raw_scores,
        "recent_concept_raw_scores": recent_raw,
        "concept_absolute_affinities": absolute,
        "concept_relative_shares": shares,
        "recent_concept_absolute_affinities": recent_absolute,
        "recent_concept_relative_shares": recent_shares,
        "profile_evidence_mass": round(evidence_mass, 6),
        "profile_recency_confidence": round(recency_confidence, 6),
        "calibration": {
            "method": "one_minus_exp_negative_raw_over_tau",
            "tau": tau,
            "tau_interpretation": "raw evidence mass at tau maps to 0.632 absolute affinity",
            "secondary_signal_discount": secondary_discount,
        },
        "multi_interests": multi_interests[:8],
        "source_freshness": source_stats,
        "interest_evidence": evidence,
        "contribution_details": contribution_details[:evidence_limit],
    }


def build_temporal_ontology_features(
    data_sources: dict[str, list[dict[str, Any]]],
    ontology: OntologyService | None = None,
    now: datetime | None = None,
    evidence_limit: int = 80,
    v2_enabled: bool | None = None,
) -> dict[str, Any]:
    ontology = ontology or get_ontology_service()
    now = now or datetime.utcnow()
    if v2_enabled is None:
        v2_enabled = settings.temporal_affinity_v2_enabled
    if v2_enabled:
        return _build_v2_features(data_sources, ontology, now, evidence_limit)
    concept_scores: dict[str, float] = {}
    recent_scores: dict[str, float] = {}
    evidence: list[dict[str, Any]] = []
    source_stats: dict[str, dict[str, Any]] = {}

    for source, items in data_sources.items():
        if not isinstance(items, list):
            continue
        source_weights: list[float] = []
        known_times = 0
        newest: datetime | None = None
        for item in items:
            if not isinstance(item, dict):
                continue
            weight, details = temporal_weight(source, item, now=now)
            source_weights.append(weight)
            occurred_at = item_occurred_at(item)
            if occurred_at:
                known_times += 1
                newest = max(newest, occurred_at) if newest else occurred_at
            matches = ontology.resolve_text(_item_text(item), limit=12)
            if not matches:
                continue
            policy = policy_for(source)
            is_recent = details["age_days"] <= policy.recent_window_days
            for match in matches:
                contribution = weight * match.confidence
                concept_scores[match.concept_id] = concept_scores.get(match.concept_id, 0.0) + contribution
                if is_recent:
                    recent_scores[match.concept_id] = recent_scores.get(match.concept_id, 0.0) + contribution
                if len(evidence) < evidence_limit:
                    evidence.append({
                        "concept_id": match.concept_id,
                        "concept_label": match.label,
                        "source": source,
                        "item_id": str(item.get("bvid") or item.get("id") or item.get("item_id") or ""),
                        "title": str(item.get("title") or "")[:200],
                        **details,
                    })
        source_stats[source] = {
            "count": len(items),
            "average_effective_weight": round(sum(source_weights) / len(source_weights), 4) if source_weights else 0.0,
            "timestamp_coverage": round(known_times / len(items), 4) if items else 0.0,
            "newest_at": newest.isoformat() if newest else None,
            "policy": asdict(policy_for(source)),
        }

    def normalize(scores: dict[str, float]) -> dict[str, float]:
        if not scores:
            return {}
        maximum = max(scores.values()) or 1.0
        return dict(sorted(
            ((concept_id, round(min(1.0, score / maximum), 4)) for concept_id, score in scores.items()),
            key=lambda row: row[1],
            reverse=True,
        )[:40])

    concept_affinities = normalize(concept_scores)
    recent_concept_affinities = normalize(recent_scores)

    clusters: dict[str, dict[str, Any]] = {}
    for concept_id, affinity in concept_affinities.items():
        cluster = ontology.top_cluster(concept_id) or {"concept_id": concept_id, "label": concept_id}
        row = clusters.setdefault(cluster["concept_id"], {
            "concept_id": cluster["concept_id"],
            "label": cluster["label"],
            "weight": 0.0,
            "concepts": [],
        })
        row["weight"] += affinity
        concept = ontology.concept(concept_id) or {"label": concept_id}
        row["concepts"].append({
            "concept_id": concept_id,
            "label": concept["label"],
            "weight": affinity,
        })

    multi_interests = []
    for row in clusters.values():
        row["concepts"] = sorted(row["concepts"], key=lambda item: item["weight"], reverse=True)[:8]
        row["weight"] = round(min(1.0, row["weight"] / max(1, len(row["concepts"]))), 4)
        multi_interests.append(row)
    multi_interests.sort(key=lambda row: row["weight"], reverse=True)

    return {
        "model": "temporal-multi-interest-ontology-v1",
        "ontology_version": ontology.VERSION,
        "generated_at": now.isoformat(),
        "concept_affinities": concept_affinities,
        "recent_concept_affinities": recent_concept_affinities,
        "multi_interests": multi_interests[:8],
        "source_freshness": source_stats,
        "interest_evidence": evidence,
    }
