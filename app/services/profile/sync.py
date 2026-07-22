"""Transactional profile-sync lifecycle with snapshot-safe invalidation."""
from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Literal
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProfileSyncRun, UserContentSignal
from app.services.profile.signals import upsert_user_content_signal


ChannelKind = Literal["snapshot", "event_stream"]
SNAPSHOT_CHANNELS = {
    "favorites", "bangumi", "cinema", "watchlater", "followings",
    "subscribed_tags", "favorite_collections", "favorite_topics",
    "favorite_articles", "favorite_courses", "favorite_notes", "courses",
    "special_followings", "whisper_followings", "fan_medals", "manga",
}
EVENT_STREAM_CHANNELS = {"history", "live_history", "dynamic_feed"}


def channel_kind(channel: str) -> ChannelKind:
    return "event_stream" if channel in EVENT_STREAM_CHANNELS else "snapshot"


def idempotency_key(session_id: str, channel: str, request_key: str) -> str:
    raw = f"{session_id}|{channel}|{request_key}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def begin_sync_run(
    db: AsyncSession,
    *,
    session_id: str,
    channel: str,
    request_key: str,
    cursor: dict[str, Any] | None = None,
) -> ProfileSyncRun:
    key = idempotency_key(session_id, channel, request_key)
    result = await db.execute(
        select(ProfileSyncRun).where(ProfileSyncRun.idempotency_key == key)
    )
    run = result.scalar_one_or_none()
    if run:
        return run
    run = ProfileSyncRun(
        run_id=str(uuid.uuid4()),
        idempotency_key=key,
        session_id=session_id,
        channel=channel,
        channel_kind=channel_kind(channel),
        status="running",
        capability_status="working",
        cursor=cursor or {},
        schema_version="2.0",
    )
    db.add(run)
    await db.flush()
    return run


async def upsert_sync_signal(
    db: AsyncSession, run: ProfileSyncRun, **signal: Any
) -> UserContentSignal:
    if run.status not in {"running", "retrying"}:
        raise ValueError(f"Cannot write to sync run in status {run.status}")
    if signal.get("session_id") not in (None, run.session_id):
        raise ValueError("Signal session does not match sync run")
    if signal.get("source") not in (None, run.channel):
        raise ValueError("Signal source does not match sync run")
    signal["session_id"] = run.session_id
    signal["source"] = run.channel
    signal["sync_run_id"] = run.run_id
    return await upsert_user_content_signal(db, **signal)


async def complete_sync_run(
    db: AsyncSession,
    run: ProfileSyncRun,
    *,
    item_count: int,
    page_count: int,
    cursor: dict[str, Any] | None = None,
    full_snapshot: bool = False,
    http_status: int | None = 200,
) -> int:
    """Complete a run and invalidate missing snapshot rows only on full success."""
    now = datetime.utcnow()
    run.status = "success"
    run.capability_status = "working"
    run.finished_at = now
    run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
    run.item_count = max(0, item_count)
    run.page_count = max(0, page_count)
    run.cursor = cursor or {}
    run.full_snapshot = bool(full_snapshot)
    run.http_status = http_status
    invalidated = 0
    if run.channel_kind == "snapshot" and full_snapshot:
        result = await db.execute(
            update(UserContentSignal)
            .where(
                UserContentSignal.session_id == run.session_id,
                UserContentSignal.source == run.channel,
                UserContentSignal.is_active.is_(True),
                or_(
                    UserContentSignal.last_seen_sync_id.is_(None),
                    UserContentSignal.last_seen_sync_id != run.run_id,
                ),
            )
            .values(is_active=False, last_seen_at=now)
        )
        invalidated = int(result.rowcount or 0)
    await db.flush()
    from app.services.observability import metrics
    metrics.inc("profile_sync_runs_total", channel=run.channel, status="success")
    metrics.observe("profile_sync_duration_ms", run.duration_ms, channel=run.channel)
    return invalidated


async def fail_sync_run(
    db: AsyncSession,
    run: ProfileSyncRun,
    *,
    status: str = "failed",
    capability_status: str = "degraded",
    error_summary: str,
    http_status: int | None = None,
    cursor: dict[str, Any] | None = None,
) -> None:
    now = datetime.utcnow()
    run.status = status
    run.capability_status = capability_status
    run.finished_at = now
    run.duration_ms = max(0, int((now - run.started_at).total_seconds() * 1000))
    run.http_status = http_status
    run.cursor = cursor or run.cursor or {}
    # Error summaries are bounded and must never contain raw response bodies.
    run.error_summary = str(error_summary).replace("\n", " ")[:500]
    run.full_snapshot = False
    await db.flush()
    from app.services.observability import metrics
    metrics.inc("profile_sync_runs_total", channel=run.channel, status=status)
    metrics.observe("profile_sync_duration_ms", run.duration_ms, channel=run.channel)
