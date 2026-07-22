"""User-controlled profile evidence, channel participation and data deletion."""
from __future__ import annotations

from collections import defaultdict
import hashlib
from typing import Any, Literal

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Base, FavoriteFolder, FavoriteVideo, GlobalKnowledge, UserContentSignal,
    UserInterestProfile, UserSession,
)
from app.config import settings
from app.services.ontology import get_ontology_service
from app.services.profile.signals import signal_to_profile_item
from app.services.recommendation.temporal_interest import build_temporal_ontology_features


DeletionScope = Literal["cookies", "profile", "all"]


def session_hash(session_id: str) -> str:
    return hashlib.sha256(("privacy-audit-v1:" + session_id).encode()).hexdigest()[:16]


async def _profile(db: AsyncSession, session_id: str) -> UserInterestProfile | None:
    result = await db.execute(select(UserInterestProfile).where(
        UserInterestProfile.session_id == session_id
    ))
    return result.scalar_one_or_none()


async def paused_channels(db: AsyncSession, session_id: str) -> set[str]:
    profile = await _profile(db, session_id)
    features = profile.profile_features if profile and isinstance(profile.profile_features, dict) else {}
    privacy = features.get("privacy") if isinstance(features.get("privacy"), dict) else {}
    return {str(value) for value in privacy.get("paused_channels", []) if value}


async def rebuild_profile_from_active_evidence(db: AsyncSession, session_id: str) -> dict[str, Any]:
    """Recompute semantic profile immediately after a privacy control change."""
    paused = await paused_channels(db, session_id)
    result = await db.execute(select(UserContentSignal).where(
        UserContentSignal.session_id == session_id,
        UserContentSignal.is_active == True,
    ))
    sources: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for signal in result.scalars():
        if signal.source not in paused:
            sources[signal.source].append(signal_to_profile_item(signal))
    features = build_temporal_ontology_features(
        dict(sources),
        v2_enabled=settings.v2_feature_flags(session_id)["temporal_affinity_v2"],
    )
    features["privacy"] = {
        "paused_channels": sorted(paused),
        "participating_channels": sorted(sources),
    }
    profile = await _profile(db, session_id)
    if profile:
        ontology = get_ontology_service()
        profile.profile_features = features
        profile.interest_tags = {
            (ontology.concept(concept_id) or {"label": concept_id})["label"]: score
            for concept_id, score in features.get("concept_absolute_affinities", {}).items()
        }
        profile.recent_interest_shift = {
            (ontology.concept(concept_id) or {"label": concept_id})["label"]: score
            for concept_id, score in features.get("recent_concept_absolute_affinities", {}).items()
        }
        profile.last_update_source = "privacy_control"
    return features


async def set_channel_participation(
    db: AsyncSession, session_id: str, channel: str, enabled: bool
) -> dict[str, Any]:
    channel = channel.strip()
    if not channel or len(channel) > 50:
        raise ValueError("Invalid profile channel")
    profile = await _profile(db, session_id)
    if not profile:
        raise LookupError("Profile not found")
    features = dict(profile.profile_features or {})
    privacy = dict(features.get("privacy") or {})
    paused = {str(value) for value in privacy.get("paused_channels", [])}
    if enabled:
        paused.discard(channel)
    else:
        paused.add(channel)
    privacy["paused_channels"] = sorted(paused)
    features["privacy"] = privacy
    profile.profile_features = features
    await db.flush()
    rebuilt = await rebuild_profile_from_active_evidence(db, session_id)
    await db.commit()
    return {
        "channel": channel, "enabled": enabled,
        "paused_channels": rebuilt["privacy"]["paused_channels"],
        "participating_channels": rebuilt["privacy"]["participating_channels"],
    }


async def delete_profile_evidence(
    db: AsyncSession, session_id: str, signal_id: int
) -> dict[str, Any]:
    result = await db.execute(select(UserContentSignal).where(
        UserContentSignal.id == signal_id,
        UserContentSignal.session_id == session_id,
    ))
    signal = result.scalar_one_or_none()
    if not signal:
        raise LookupError("Profile evidence not found")
    source = signal.source
    item_id = signal.item_id
    await db.delete(signal)
    await db.flush()
    await rebuild_profile_from_active_evidence(db, session_id)
    await db.commit()
    return {"deleted": True, "evidence_id": signal_id, "source": source, "item_id": item_id}


async def delete_user_data(
    db: AsyncSession, session_id: str, scope: DeletionScope
) -> dict[str, Any]:
    counts: dict[str, int] = {}
    if scope == "cookies":
        result = await db.execute(update(UserSession).where(
            UserSession.session_id == session_id
        ).values(sessdata=None, bili_jct=None, dedeuserid=None, is_valid=False))
        counts["user_sessions_credentials_cleared"] = int(result.rowcount or 0)
        await db.commit()
        return {"scope": scope, "session_hash": session_hash(session_id), "counts": counts}

    if scope == "profile":
        for model in (UserContentSignal, UserInterestProfile):
            result = await db.execute(delete(model).where(model.session_id == session_id))
            counts[model.__tablename__] = int(result.rowcount or 0)
        await db.commit()
        return {"scope": scope, "session_hash": session_hash(session_id), "counts": counts}

    if scope != "all":
        raise ValueError("Unsupported deletion scope")

    folder_rows = await db.execute(select(FavoriteFolder.id).where(
        FavoriteFolder.session_id == session_id
    ))
    folder_ids = [row[0] for row in folder_rows]
    if folder_ids:
        result = await db.execute(delete(FavoriteVideo).where(FavoriteVideo.folder_id.in_(folder_ids)))
        counts[FavoriteVideo.__tablename__] = int(result.rowcount or 0)

    # Every session-owned table participates automatically, including future
    # additive models. Shared caches and ontology tables have no session_id and
    # are intentionally preserved.
    for table in reversed(Base.metadata.sorted_tables):
        if "session_id" not in table.c:
            continue
        result = await db.execute(delete(table).where(table.c.session_id == session_id))
        counts[table.name] = counts.get(table.name, 0) + int(result.rowcount or 0)

    global_rows = await db.execute(select(GlobalKnowledge))
    for row in global_rows.scalars():
        sources = [value for value in (row.source_sessions or []) if value != session_id]
        if sources != (row.source_sessions or []):
            row.source_sessions = sources
            row.source_count = len(sources)
            if not sources:
                row.is_active = False
    await db.commit()
    return {"scope": scope, "session_hash": session_hash(session_id), "counts": counts}
