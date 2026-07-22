"""Encrypt legacy session cookies and rotate old key envelopes.

The command is dry-run by default.  It reads the raw SQLite values so the
SQLAlchemy compatibility layer cannot hide rows that still need migration.
It never prints credential values.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.security.cookies import CookieCipher


@dataclass(frozen=True)
class MigrationReport:
    scanned_rows: int = 0
    legacy_plaintext_fields: int = 0
    stale_key_fields: int = 0
    changed_rows: int = 0
    applied: bool = False


def _key_id(value: str | None) -> str | None:
    if not CookieCipher.is_encrypted(value):
        return None
    parts = value.split(":", 3)
    return parts[2] if len(parts) == 4 else None


def migrate_sqlite_database(database: Path, *, apply: bool = False) -> MigrationReport:
    """Return a secret-free migration report and optionally update atomically."""
    database = database.resolve()
    if not database.is_file():
        raise FileNotFoundError(f"SQLite database does not exist: {database}")
    cipher = CookieCipher.from_settings()
    if not cipher.available:
        raise RuntimeError("A valid active cookie encryption key is required")

    scanned = plaintext = stale = changed = 0
    connection = sqlite3.connect(database)
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='user_sessions'"
        ).fetchone()
        if not table:
            raise RuntimeError("Database has no user_sessions table")
        connection.execute("BEGIN IMMEDIATE" if apply else "BEGIN")
        rows = connection.execute(
            "SELECT id, sessdata, bili_jct FROM user_sessions ORDER BY id"
        ).fetchall()
        scanned = len(rows)
        for row_id, sessdata, bili_jct in rows:
            values = [sessdata, bili_jct]
            migrated: list[str | None] = []
            row_changed = False
            for value in values:
                if value in (None, ""):
                    migrated.append(value)
                    continue
                if CookieCipher.is_encrypted(value):
                    if _key_id(value) == cipher.active_key_id:
                        # Authenticate even current envelopes during the audit.
                        cipher.decrypt(value)
                        migrated.append(value)
                    else:
                        stale += 1
                        migrated.append(cipher.rotate(value))
                        row_changed = True
                else:
                    plaintext += 1
                    migrated.append(cipher.encrypt(value))
                    row_changed = True
            if row_changed:
                changed += 1
                if apply:
                    connection.execute(
                        "UPDATE user_sessions SET sessdata=?, bili_jct=? WHERE id=?",
                        (migrated[0], migrated[1], row_id),
                    )
        if apply:
            connection.commit()
        else:
            connection.rollback()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return MigrationReport(scanned, plaintext, stale, changed, apply)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        type=Path,
        default=Path("data/bilibili_rag.db"),
        help="SQLite database path (default: data/bilibili_rag.db)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit changes; without this flag the command is a dry run",
    )
    args = parser.parse_args()
    report = migrate_sqlite_database(args.database, apply=args.apply)
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
