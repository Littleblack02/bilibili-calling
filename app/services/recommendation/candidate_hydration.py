"""Hydrate lightweight BVID candidates once, after multi-source merge."""
from __future__ import annotations

import asyncio
import copy
from datetime import datetime
import time
from typing import Any

from loguru import logger
from sqlalchemy import select

from app.config import settings
from app.database import async_session_factory
from app.models import VideoCache
from app.services.ontology import get_ontology_service


CRITICAL_RANKING_FIELDS = (
    "title", "description", "category", "author", "mid", "pubdate",
    "duration", "play", "like", "coin", "favorite", "comment",
)


class CandidateHydrator:
    def __init__(
        self,
        *,
        persist: bool = True,
        ttl_seconds: int | None = None,
        ontology: Any | None = None,
    ) -> None:
        self.persist = persist
        self.ttl_seconds = (
            settings.candidate_hydration_cache_ttl_seconds
            if ttl_seconds is None else max(0, int(ttl_seconds))
        )
        self.ontology = ontology or get_ontology_service()
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def hydrate_candidates(
        self,
        bili: Any,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Hydrate every unique BVID at most once and preserve recall evidence."""
        ordered_bvids = list(dict.fromkeys(
            str(item.get("bvid")) for item in candidates if item.get("bvid")
        ))
        if not ordered_bvids:
            return []

        db_records = await self._load_database_records(ordered_bvids)
        semaphore = asyncio.Semaphore(settings.candidate_hydration_concurrency)

        async def load(bvid: str) -> tuple[str, dict[str, Any]]:
            cached = self._cache.get(bvid)
            now = time.monotonic()
            if cached and now - cached[0] <= self.ttl_seconds:
                row = copy.deepcopy(cached[1])
                row["hydration_cache_hit"] = True
                return bvid, row
            async with semaphore:
                row = await self._fetch_one(bili, bvid, db_records.get(bvid))
            self._cache[bvid] = (time.monotonic(), copy.deepcopy(row))
            return bvid, row

        rows = await asyncio.gather(*(load(bvid) for bvid in ordered_bvids))
        hydrated_by_bvid = dict(rows)
        if self.persist:
            await self._persist_database_records(hydrated_by_bvid.values())

        output: list[dict[str, Any]] = []
        for candidate in candidates:
            bvid = str(candidate.get("bvid") or "")
            if not bvid:
                continue
            fallback = candidate.get("_recall_fallback")
            base = dict(fallback) if isinstance(fallback, dict) else {}
            base.update({key: value for key, value in candidate.items() if key != "_recall_fallback"})
            detail = hydrated_by_bvid.get(bvid, {})
            output.append({**base, **{
                key: value for key, value in detail.items()
                if value is not None
            }})
        return output

    async def _fetch_one(
        self,
        bili: Any,
        bvid: str,
        database_row: dict[str, Any] | None,
    ) -> dict[str, Any]:
        fetched_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        try:
            info_result, tag_result = await asyncio.wait_for(
                asyncio.gather(
                    bili.get_video_info(bvid),
                    bili.get_video_tags(bvid),
                ),
                timeout=settings.candidate_hydration_timeout_seconds,
            )
        except Exception as exc:
            info_result = {"success": False, "error": type(exc).__name__}
            tag_result = {"success": False, "error": type(exc).__name__}

        if not info_result.get("success"):
            if database_row:
                return {
                    **database_row,
                    "hydration_status": "cache_fallback",
                    "hydration_error": str(info_result.get("error") or "view unavailable")[:200],
                    "hydrated_at": fetched_at,
                    "hydration_cache_hit": True,
                }
            return {
                "bvid": bvid,
                "hydration_status": "failed",
                "hydration_error": str(info_result.get("error") or "view unavailable")[:200],
                "hydrated_at": fetched_at,
                "hydration_cache_hit": False,
                "hydration_coverage": 0.0,
            }

        data = info_result.get("data") or {}
        owner = data.get("owner") or {}
        stat = data.get("stat") or {}
        dimension = data.get("dimension") or {}
        ugc_season = data.get("ugc_season")
        tags = None
        if tag_result.get("success"):
            tags = [
                row.get("tag_name") or row.get("name")
                for row in (tag_result.get("tags") or [])
                if isinstance(row, dict) and (row.get("tag_name") or row.get("name"))
            ]
        published = data.get("pubdate")
        pubdate = datetime.fromtimestamp(published) if published else None
        summary = database_row.get("summary") if database_row else None
        concept_text = " ".join(filter(None, [
            data.get("title"), data.get("desc"), data.get("tname"),
            " ".join(tags or []),
        ]))
        concept_matches = self.ontology.resolve_text(concept_text)
        concepts = [{
            "concept_id": row.concept_id,
            "label": row.label,
            "confidence": row.confidence,
        } for row in concept_matches]
        detail = {
            "bvid": bvid,
            "aid": data.get("aid"),
            "cid": data.get("cid"),
            "title": data.get("title"),
            "description": data.get("desc"),
            "tags": tags,
            "category": data.get("tname"),
            "category_id": data.get("tid"),
            "collection": ({
                "id": ugc_season.get("id"), "title": ugc_season.get("title")
            } if isinstance(ugc_season, dict) else None),
            "author": owner.get("name"),
            "mid": owner.get("mid"),
            "pubdate": pubdate,
            "duration": data.get("duration"),
            "pic_url": data.get("pic"),
            "width": dimension.get("width"),
            "height": dimension.get("height"),
            "play": stat.get("view"),
            "like": stat.get("like"),
            "coin": stat.get("coin"),
            "favorite": stat.get("favorite"),
            "comment": stat.get("reply"),
            "danmaku": stat.get("danmaku"),
            "share": stat.get("share"),
            "summary": summary,
            "concept_ids": [row["concept_id"] for row in concepts],
            "concepts": concepts,
            "hydration_status": "success",
            "hydrated_at": fetched_at,
            "hydration_cache_hit": False,
        }
        present = sum(detail.get(field) is not None for field in CRITICAL_RANKING_FIELDS)
        detail["hydration_coverage"] = round(present / len(CRITICAL_RANKING_FIELDS), 6)
        detail["hydration_field_meta"] = {
            field: {
                "source": (
                    "video_cache" if field == "summary"
                    else "ontology" if field in {"concept_ids", "concepts"}
                    else "bilibili_archive_tags" if field == "tags"
                    else "bilibili_view"
                ),
                "fetched_at": fetched_at,
            }
            for field, value in detail.items()
            if value is not None and field not in {
                "hydration_status", "hydrated_at", "hydration_cache_hit",
                "hydration_coverage", "hydration_field_meta",
            }
        }
        return detail

    async def _load_database_records(
        self, bvids: list[str]
    ) -> dict[str, dict[str, Any]]:
        if not self.persist:
            return {}
        try:
            async with async_session_factory() as db:
                result = await db.execute(select(VideoCache).where(VideoCache.bvid.in_(bvids)))
                return {
                    row.bvid: {
                        "bvid": row.bvid,
                        "cid": row.cid,
                        "title": row.title,
                        "description": row.description,
                        "author": row.owner_name,
                        "mid": row.owner_mid,
                        "duration": row.duration,
                        "pic_url": row.pic_url,
                        "summary": row.content,
                    }
                    for row in result.scalars()
                }
        except Exception as exc:
            logger.warning(f"候选本地缓存读取失败，继续远程补全: {type(exc).__name__}")
            return {}

    async def _persist_database_records(self, rows: Any) -> None:
        successful = [row for row in rows if row.get("hydration_status") == "success"]
        if not successful:
            return
        try:
            async with async_session_factory() as db:
                bvids = [row["bvid"] for row in successful]
                result = await db.execute(select(VideoCache).where(VideoCache.bvid.in_(bvids)))
                existing = {row.bvid: row for row in result.scalars()}
                for row in successful:
                    record = existing.get(row["bvid"])
                    values = {
                        "cid": row.get("cid"), "title": row.get("title"),
                        "description": row.get("description"),
                        "owner_name": row.get("author"), "owner_mid": row.get("mid"),
                        "duration": row.get("duration"), "pic_url": row.get("pic_url"),
                    }
                    if record:
                        for field, value in values.items():
                            if value is not None:
                                setattr(record, field, value)
                    elif row.get("title"):
                        db.add(VideoCache(bvid=row["bvid"], **values))
                await db.commit()
        except Exception as exc:
            logger.warning(f"候选本地缓存写入失败，不影响当前推荐: {type(exc).__name__}")


_candidate_hydrator: CandidateHydrator | None = None


def get_candidate_hydrator() -> CandidateHydrator:
    global _candidate_hydrator
    if _candidate_hydrator is None:
        _candidate_hydrator = CandidateHydrator()
    return _candidate_hydrator
