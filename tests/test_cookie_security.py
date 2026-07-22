import asyncio
import base64
import os

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Base, UserSession
from app.services.security.cookies import (
    CookieCipher,
    CookieEncryptionUnavailable,
    redact_sensitive_text,
)
from app.routers import auth


def _key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")


def test_cookie_cipher_round_trip_rotation_and_redaction(monkeypatch):
    old_key = _key()
    active_key = _key()
    monkeypatch.setattr(
        settings,
        "bilibili_cookie_encryption_keys",
        SecretStr(f"old={old_key},active={active_key}"),
    )
    monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "active")
    cipher = CookieCipher.from_settings()

    encrypted = cipher.encrypt("very-secret-cookie")
    assert encrypted.startswith("enc:v1:active:")
    assert "very-secret-cookie" not in encrypted
    assert cipher.decrypt(encrypted) == "very-secret-cookie"
    assert cipher.decrypt("legacy-plaintext") == "legacy-plaintext"

    redacted = redact_sensitive_text(
        "SESSDATA=very-secret-cookie; bili_jct: csrf-secret; " + encrypted
    )
    assert "very-secret-cookie" not in redacted
    assert "csrf-secret" not in redacted
    assert encrypted not in redacted
    session_id = "a7a1eb10-80cf-4f3d-9b62-3c083cd0ad98"
    session_redacted = redact_sensitive_text(f"session_id={session_id} Session: {session_id}")
    assert session_id not in session_redacted
    assert "session_hash=" in session_redacted


def test_cookie_cipher_refuses_new_plaintext_without_key(monkeypatch):
    monkeypatch.setattr(settings, "bilibili_cookie_encryption_keys", SecretStr(""))
    monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "")
    with pytest.raises(CookieEncryptionUnavailable):
        CookieCipher.from_settings().encrypt("must-not-be-plaintext")


def test_user_session_cookie_columns_store_ciphertext(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            settings,
            "bilibili_cookie_encryption_keys",
            SecretStr(f"test={_key()}"),
        )
        monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "test")
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'security.db'}")
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(UserSession(
                session_id="security-test",
                sessdata="plain-sessdata",
                bili_jct="plain-csrf",
                dedeuserid="123",
            ))
            await db.commit()
        async with engine.connect() as connection:
            row = (await connection.execute(text(
                "SELECT sessdata, bili_jct FROM user_sessions WHERE session_id='security-test'"
            ))).one()
            assert "plain-sessdata" not in row.sessdata
            assert "plain-csrf" not in row.bili_jct
            assert row.sessdata.startswith("enc:v1:test:")
        async with factory() as db:
            loaded = await db.get(UserSession, 1)
            assert loaded.sessdata == "plain-sessdata"
            assert loaded.bili_jct == "plain-csrf"
        await engine.dispose()

    asyncio.run(scenario())


def test_confirmed_login_fails_closed_before_cache_or_database(monkeypatch):
    class ConfirmedLogin:
        async def poll_qrcode_status(self, _qrcode_key):
            return {
                "status": "confirmed",
                "message": "ok",
                "cookies": {
                    "SESSDATA": "must-not-be-cached",
                    "bili_jct": "must-not-be-cached-either",
                    "DedeUserID": "123",
                },
            }

        async def close(self):
            return None

    class UntouchedDatabase:
        def add(self, _record):
            raise AssertionError("database must not be touched without an encryption key")

    async def scenario():
        monkeypatch.setattr(settings, "bilibili_cookie_encryption_keys", SecretStr(""))
        monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "")
        monkeypatch.setattr(auth, "BilibiliService", ConfirmedLogin)
        before = set(auth.login_sessions)
        with pytest.raises(HTTPException) as error:
            await auth.poll_qrcode_status("no-key", UntouchedDatabase())
        assert error.value.status_code == 503
        assert set(auth.login_sessions) == before

    asyncio.run(scenario())


def test_logout_revokes_persisted_session_and_erases_credentials(tmp_path, monkeypatch):
    async def scenario():
        monkeypatch.setattr(
            settings,
            "bilibili_cookie_encryption_keys",
            SecretStr(f"test={_key()}"),
        )
        monkeypatch.setattr(settings, "bilibili_cookie_active_key_id", "test")
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'logout.db'}")
        factory = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with factory() as db:
            db.add(UserSession(
                session_id="logout-test",
                sessdata="plain-sessdata",
                bili_jct="plain-csrf",
                dedeuserid="123",
                is_valid=True,
            ))
            await db.commit()
            await auth.logout("logout-test", db)
        async with engine.connect() as connection:
            row = (await connection.execute(text(
                "SELECT is_valid, sessdata, bili_jct FROM user_sessions "
                "WHERE session_id='logout-test'"
            ))).one()
            assert row.is_valid == 0
            assert row.sessdata is None
            assert row.bili_jct is None
        await engine.dispose()

    asyncio.run(scenario())
