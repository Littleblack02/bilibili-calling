"""Backfill deterministic ontology annotations for locally cached videos.

Usage:
    python scripts/backfill_ontology.py --batch-size 100 --database-url sqlite+aiosqlite:///data/copy.db
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.database import async_session_factory, init_db  # noqa: E402
from app.models import Base, VideoCache  # noqa: E402
from app.services.ontology import get_ontology_service  # noqa: E402
from app.services.ontology.repository import replace_video_annotations  # noqa: E402


async def backfill(
    batch_size: int,
    *,
    session_factory=async_session_factory,
    initialize=init_db,
) -> tuple[int, int]:
    if initialize is not None:
        await initialize()
    ontology = get_ontology_service()
    processed = 0
    annotations_written = 0
    offset = 0
    while True:
        async with session_factory() as db:
            result = await db.execute(
                select(VideoCache).order_by(VideoCache.bvid).offset(offset).limit(batch_size)
            )
            videos = list(result.scalars())
            if not videos:
                break
            for video in videos:
                annotations = ontology.annotate_video(
                    video.title or "", video.description or ""
                )
                annotations_written += await replace_video_annotations(
                    db, video.bvid, annotations, ontology
                )
                processed += 1
            await db.commit()
        offset += len(videos)
    return processed, annotations_written


async def _run_with_database_url(
    database_url: str,
    batch_size: int,
) -> tuple[int, int]:
    engine = create_async_engine(database_url, echo=False, future=True)
    local_session_factory = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        return await backfill(
            batch_size,
            session_factory=local_session_factory,
            initialize=None,
        )
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill video ontology annotations")
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument(
        "--database-url",
        help="Explicit async SQLAlchemy URL. Use a backup or temporary DB for verification.",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be positive")
    if args.database_url:
        processed, annotations = asyncio.run(
            _run_with_database_url(args.database_url, args.batch_size)
        )
    else:
        processed, annotations = asyncio.run(backfill(args.batch_size))
    report = {
        "processed": processed,
        "annotations_written": annotations,
        "batch_size": args.batch_size,
        "database_scope": "explicit" if args.database_url else "configured_default",
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
