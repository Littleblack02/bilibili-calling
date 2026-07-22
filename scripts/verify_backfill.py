"""Verify ontology backfill and idempotent replacement on a disposable DB."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
import tempfile

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.models import Base, OntologyConcept, VideoCache, VideoConcept  # noqa: E402
from scripts.backfill_ontology import backfill  # noqa: E402


async def _verify(database: Path) -> dict[str, object]:
    database_url = f"sqlite+aiosqlite:///{database.as_posix()}"
    engine = create_async_engine(database_url, echo=False, future=True)
    factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add_all([
                VideoCache(
                    bvid="BVBF000001",
                    title="LangGraph Agent 工作流实战",
                    description="使用 Python 和 RAG 构建智能体。",
                ),
                VideoCache(
                    bvid="BVBF000002",
                    title="机器学习入门教程",
                    description="神经网络基础知识。",
                ),
                VideoCache(
                    bvid="BVBF000003",
                    title="摇滚音乐现场",
                    description="乐队演奏与音乐制作。",
                ),
            ])
            await db.commit()

        first_processed, first_written = await backfill(
            2, session_factory=factory, initialize=None
        )
        second_processed, second_written = await backfill(
            2, session_factory=factory, initialize=None
        )
        async with factory() as db:
            video_concepts = int((await db.execute(
                select(func.count()).select_from(VideoConcept)
            )).scalar_one())
            ontology_concepts = int((await db.execute(
                select(func.count()).select_from(OntologyConcept)
            )).scalar_one())
            versions = set((await db.execute(
                select(VideoConcept.ontology_version)
            )).scalars())
        checks = {
            "fixture_videos_processed": first_processed == 3 == second_processed,
            "annotations_created": first_written >= 3 and video_concepts == second_written,
            "idempotent_replacement": first_written == second_written == video_concepts,
            "canonical_concepts_materialized": ontology_concepts > 0,
            "version_recorded": versions == {"bili-ontology-2.0.0"},
        }
        return {
            "schema_version": "1.0",
            "database_scope": "disposable_temporary_sqlite",
            "metrics": {
                "videos": first_processed,
                "video_concepts": video_concepts,
                "ontology_concepts": ontology_concepts,
            },
            "checks": checks,
            "passed": all(checks.values()),
        }
    finally:
        await engine.dispose()


def verify() -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="bili-backfill-verify-") as temporary:
        return asyncio.run(_verify(Path(temporary) / "backfill.db"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "backfill.json",
    )
    args = parser.parse_args()
    report = verify()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
