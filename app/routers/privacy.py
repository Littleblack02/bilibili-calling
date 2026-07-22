"""Explicit privacy controls and confirmed user-data deletion endpoints."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import UserContentSignal
from app.services.privacy import (
    delete_profile_evidence, delete_user_data, paused_channels,
    set_channel_participation,
)


router = APIRouter(prefix="/privacy", tags=["隐私"])


class ChannelControl(BaseModel):
    enabled: bool


class ConfirmedDeletion(BaseModel):
    scope: Literal["cookies", "profile", "all"]
    confirmation: str


@router.get("/{session_id}/controls")
async def get_privacy_controls(session_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(UserContentSignal.source, func.count(UserContentSignal.id))
        .where(UserContentSignal.session_id == session_id)
        .group_by(UserContentSignal.source)
    )
    paused = await paused_channels(db, session_id)
    evidence_result = await db.execute(
        select(UserContentSignal)
        .where(UserContentSignal.session_id == session_id)
        .order_by(UserContentSignal.occurred_at.desc(), UserContentSignal.last_seen_at.desc())
        .limit(100)
    )
    return {
        "session_id": session_id,
        "channels": {
            source: {"evidence_count": count, "enabled": source not in paused}
            for source, count in result.all()
        },
        "paused_channels": sorted(paused),
        "evidence": [
            {
                "id": signal.id, "source": signal.source,
                "item_id": signal.item_id, "title": signal.title or signal.item_id,
                "occurred_at": signal.occurred_at, "last_seen_at": signal.last_seen_at,
                "is_active": signal.is_active,
            }
            for signal in evidence_result.scalars()
        ],
        "deletion_scopes": ["cookies", "profile", "all"],
    }


@router.delete("/{session_id}/evidence/{signal_id}")
async def remove_profile_evidence(
    session_id: str, signal_id: int, confirmed: bool = False,
    db: AsyncSession = Depends(get_db),
):
    if not confirmed:
        raise HTTPException(status_code=409, detail="需要明确确认删除画像证据")
    try:
        return await delete_profile_evidence(db, session_id, signal_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.put("/{session_id}/channels/{channel}")
async def control_profile_channel(
    session_id: str, channel: str, request: ChannelControl,
    db: AsyncSession = Depends(get_db),
):
    try:
        return await set_channel_participation(db, session_id, channel, request.enabled)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/{session_id}/delete")
async def confirmed_user_data_deletion(
    session_id: str, request: ConfirmedDeletion,
    db: AsyncSession = Depends(get_db),
):
    expected = {
        "cookies": "DELETE COOKIES",
        "profile": "DELETE PROFILE",
        "all": "DELETE ALL",
    }[request.scope]
    if request.confirmation != expected:
        raise HTTPException(status_code=409, detail=f"请输入确认短语：{expected}")
    report = await delete_user_data(db, session_id, request.scope)
    if request.scope in {"cookies", "all"}:
        from app.routers.auth import login_sessions
        login_sessions.pop(session_id, None)
    return {"success": True, **report}
