import base64
import os
from pathlib import Path
import sqlite3

from pydantic import SecretStr

from app.config import settings
from app.services.security.cookies import CookieCipher
from scripts.migrate_session_cookies import migrate_sqlite_database
from scripts.validate_evaluation_data import validate_directory


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def _legacy_database(path: Path, old_cipher: CookieCipher) -> None:
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE user_sessions ("
        "id INTEGER PRIMARY KEY, sessdata TEXT, bili_jct TEXT)"
    )
    connection.execute(
        "INSERT INTO user_sessions VALUES (?, ?, ?)",
        (1, "legacy-sessdata", old_cipher.encrypt("old-csrf")),
    )
    connection.commit()
    connection.close()


def test_cookie_migration_is_dry_run_by_default_and_rotates_atomically(tmp_path, monkeypatch):
    old_key = _key()
    new_key = _key()
    monkeypatch.setattr(settings, "bilibili_cookie_encryption_keys", SecretStr(f"old={old_key}"))
    monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "old")
    old_cipher = CookieCipher.from_settings()
    database = tmp_path / "legacy.db"
    _legacy_database(database, old_cipher)

    monkeypatch.setattr(
        settings,
        "bilibili_cookie_encryption_keys",
        SecretStr(f"new={new_key},old={old_key}"),
    )
    monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "new")

    dry_run = migrate_sqlite_database(database)
    assert dry_run.legacy_plaintext_fields == 1
    assert dry_run.stale_key_fields == 1
    assert dry_run.changed_rows == 1
    assert not dry_run.applied
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT sessdata, bili_jct FROM user_sessions"
        ).fetchone()
    assert before[0] == "legacy-sessdata"
    assert before[1].startswith("enc:v1:old:")

    applied = migrate_sqlite_database(database, apply=True)
    assert applied.applied
    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT sessdata, bili_jct FROM user_sessions"
        ).fetchone()
    assert after[0].startswith("enc:v1:new:")
    assert after[1].startswith("enc:v1:new:")
    assert "legacy-sessdata" not in after[0]


def test_committed_evaluation_examples_validate():
    root = Path(__file__).resolve().parents[1]
    counts = validate_directory(root / "evaluation")
    assert counts == {
        "entity_linking.jsonl": 471,
        "rag_chunks.jsonl": 126,
        "rag_qa.jsonl": 150,
        "recommendation_events.jsonl": 1328,
        "recommendation_items.jsonl": 1008,
    }
