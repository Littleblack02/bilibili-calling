"""Verify empty/legacy SQLite upgrades on disposable databases only."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
import tempfile

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import Base


ROOT = Path(__file__).resolve().parents[1]
V2_TABLES = {
    "ontology_concepts", "ontology_relations", "video_concepts",
    "user_content_signals", "profile_sync_runs", "recommendation_batches",
    "recommendation_events",
}


def _config(database: Path) -> Config:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database.as_posix()}")
    return config


def _make_legacy(database: Path) -> None:
    engine = create_engine(f"sqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    engine.dispose()
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys=OFF")
        for table in V2_TABLES:
            connection.execute(f'DROP TABLE IF EXISTS "{table}"')
        profile_columns = {row[1] for row in connection.execute("PRAGMA table_info(user_interest_profiles)")}
        if "profile_features" in profile_columns:
            connection.execute("ALTER TABLE user_interest_profiles DROP COLUMN profile_features")
        connection.execute(
            "INSERT INTO user_sessions "
            "(session_id, bili_uname, sessdata, bili_jct, is_valid) VALUES (?, ?, ?, ?, ?)",
            ("legacy-session", "legacy-user", None, None, 1),
        )
        connection.execute(
            "INSERT INTO user_interest_profiles (session_id, interest_tags, confidence_score) VALUES (?, ?, ?)",
            ("legacy-session", '{"RAG": 0.4}', 0.4),
        )
        connection.commit()


def verify(work_dir: Path) -> dict[str, object]:
    work_dir.mkdir(parents=True, exist_ok=True)
    legacy = work_dir / "legacy-copy.db"
    empty = work_dir / "empty.db"
    _make_legacy(legacy)

    command.upgrade(_config(legacy), "head")
    command.upgrade(_config(legacy), "head")
    command.upgrade(_config(empty), "head")

    legacy_engine = create_engine(f"sqlite:///{legacy.as_posix()}")
    empty_engine = create_engine(f"sqlite:///{empty.as_posix()}")
    legacy_inspector = inspect(legacy_engine)
    empty_inspector = inspect(empty_engine)
    legacy_tables = set(legacy_inspector.get_table_names())
    empty_tables = set(empty_inspector.get_table_names())
    profile_columns = {column["name"] for column in legacy_inspector.get_columns("user_interest_profiles")}
    with legacy_engine.connect() as connection:
        preserved = connection.exec_driver_sql(
            "SELECT session_id, bili_uname FROM user_sessions WHERE session_id='legacy-session'"
        ).first()
        version = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one()
    legacy_engine.dispose()
    empty_engine.dispose()
    result = {
        "legacy_upgrade": V2_TABLES <= legacy_tables and "profile_features" in profile_columns,
        "empty_upgrade": set(Base.metadata.tables) <= empty_tables,
        "repeat_upgrade": version == "0001_v2",
        "seed_data_preserved": tuple(preserved or ()) == ("legacy-session", "legacy-user"),
        "revision": version,
        "irreversible": True,
        "rollback": "Disable V2 feature flags for code rollback; schema rollback requires restoring the pre-migration backup.",
    }
    result["passed"] = all(result[key] for key in (
        "legacy_upgrade", "empty_upgrade", "repeat_upgrade", "seed_data_preserved"
    ))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "evaluation" / "migration.json")
    args = parser.parse_args()
    if args.work_dir:
        report = verify(args.work_dir.resolve())
    else:
        with tempfile.TemporaryDirectory(prefix="bili-migration-verify-") as temporary:
            report = verify(Path(temporary))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
