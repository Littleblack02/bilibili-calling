"""Normalization and persistence for cross-channel Bilibili user signals."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserContentSignal


def parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            # Bilibili APIs use seconds, but tolerate millisecond timestamps.
            timestamp = float(value)
            if timestamp > 10_000_000_000:
                timestamp /= 1000.0
            return datetime.utcfromtimestamp(timestamp)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        if raw.isdigit():
            return parse_datetime(int(raw))
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def make_signal_key(
    session_id: str,
    source: str,
    item_type: str,
    item_id: str,
    occurred_at: datetime | None = None,
    repeated: bool = False,
) -> str:
    occurrence = occurred_at.isoformat(timespec="seconds") if repeated and occurred_at else "active"
    raw = f"{session_id}|{source}|{item_type}|{item_id}|{occurrence}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def upsert_user_content_signal(
    db: AsyncSession,
    *,
    session_id: str,
    source: str,
    item_type: str,
    item_id: str,
    title: str | None = None,
    description: str | None = None,
    creator_mid: int | None = None,
    creator_name: str | None = None,
    category: str | None = None,
    tags: list[str] | None = None,
    strength: float = 1.0,
    occurred_at: datetime | int | float | str | None = None,
    payload: dict[str, Any] | None = None,
    repeated: bool = False,
    sync_run_id: str | None = None,
) -> UserContentSignal:
    parsed_time = parse_datetime(occurred_at)
    signal_key = make_signal_key(
        session_id,
        source,
        item_type,
        str(item_id),
        parsed_time,
        repeated=repeated,
    )
    result = await db.execute(
        select(UserContentSignal).where(UserContentSignal.signal_key == signal_key)
    )
    signal = result.scalar_one_or_none()
    values = {
        "session_id": session_id,
        "source": source,
        "item_type": item_type,
        "item_id": str(item_id),
        "title": title,
        "description": description,
        "creator_mid": creator_mid,
        "creator_name": creator_name,
        "category": category,
        "tags": tags or [],
        "strength": max(0.0, min(2.0, float(strength))),
        "occurred_at": parsed_time,
        "payload": json.loads(json.dumps(payload or {}, ensure_ascii=False, default=str)),
        "is_active": True,
        "last_seen_at": datetime.utcnow(),
        "last_seen_sync_id": sync_run_id,
    }
    if signal is None:
        signal = UserContentSignal(signal_key=signal_key, **values)
        db.add(signal)
    else:
        for key, value in values.items():
            setattr(signal, key, value)
    return signal


def signal_to_profile_item(signal: UserContentSignal) -> dict[str, Any]:
    return {
        "id": signal.item_id,
        "bvid": signal.item_id if signal.item_type == "video" else "",
        "title": signal.title or "",
        "description": signal.description or "",
        "owner_mid": signal.creator_mid,
        "owner_name": signal.creator_name or "",
        "tname": signal.category or "",
        "tags": signal.tags or [],
        "source": signal.source,
        "occurred_at": signal.occurred_at,
        "strength": signal.strength,
        "payload": signal.payload or {},
    }
