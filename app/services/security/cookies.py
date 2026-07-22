"""Versioned authenticated encryption for Bilibili session credentials."""
from __future__ import annotations

import base64
import hashlib
import os
import re
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy import Text
from sqlalchemy.types import TypeDecorator

from app.config import settings


ENVELOPE_PREFIX = "enc:v1:"
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(SESSDATA|bili_jct|csrf|DedeUserID)\b\s*[:=]\s*([^\s;,}\]]+)"
)
_ENVELOPE = re.compile(r"enc:v1:[A-Za-z0-9_.-]+:[A-Za-z0-9_=-]+")
_SESSION_ASSIGNMENT = re.compile(
    r"(?i)\b(session(?:_id)?)\b\s*[:=]\s*([A-Za-z0-9_.-]{8,128})"
)
_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)


def _session_digest(value: str) -> str:
    return hashlib.sha256(("log-session-v1:" + value).encode()).hexdigest()[:16]


class CookieEncryptionUnavailable(RuntimeError):
    """Raised when an authenticated session would otherwise be stored plaintext."""


class CookieDecryptionError(RuntimeError):
    """Raised for malformed ciphertext, unknown key versions or authentication failure."""


class CookieCipher:
    """AES-GCM envelope encryption with explicit key IDs for safe rotation."""

    def __init__(self, keys: dict[str, bytes], active_key_id: str | None) -> None:
        self.keys = keys
        self.active_key_id = active_key_id or (next(iter(keys), None))
        if self.active_key_id and self.active_key_id not in keys:
            raise CookieEncryptionUnavailable(
                f"BILIBILI_COOKIE_ACTIVE_KEY_ID '{self.active_key_id}' is not configured"
            )

    @classmethod
    def from_settings(cls) -> "CookieCipher":
        secret = settings.bilibili_cookie_encryption_keys.get_secret_value().strip()
        keys: dict[str, bytes] = {}
        if secret:
            for entry in secret.split(","):
                key_id, separator, encoded = entry.strip().partition("=")
                if not separator or not key_id or not encoded:
                    raise CookieEncryptionUnavailable(
                        "BILIBILI_COOKIE_ENCRYPTION_KEYS must use key_id=urlsafe_base64 format"
                    )
                try:
                    material = base64.urlsafe_b64decode(encoded.encode("ascii"))
                except Exception as exc:
                    raise CookieEncryptionUnavailable(
                        f"Cookie key '{key_id}' is not valid URL-safe base64"
                    ) from exc
                if len(material) != 32:
                    raise CookieEncryptionUnavailable(
                        f"Cookie key '{key_id}' must decode to exactly 32 bytes"
                    )
                keys[key_id] = material
        return cls(keys, settings.bilibili_cookie_active_key_id.strip() or None)

    @property
    def available(self) -> bool:
        return bool(self.keys and self.active_key_id)

    @staticmethod
    def is_encrypted(value: str | None) -> bool:
        return bool(value and value.startswith(ENVELOPE_PREFIX))

    @staticmethod
    def _aad(key_id: str) -> bytes:
        return f"bilibili-calling|session-cookie|v1|{key_id}".encode("utf-8")

    def encrypt(self, value: str | None) -> str | None:
        if value in (None, ""):
            return value
        if self.is_encrypted(value):
            return value
        if not self.available or not self.active_key_id:
            raise CookieEncryptionUnavailable(
                "Configure BILIBILI_COOKIE_ENCRYPTION_KEYS before storing a Bilibili login"
            )
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.keys[self.active_key_id]).encrypt(
            nonce, value.encode("utf-8"), self._aad(self.active_key_id)
        )
        payload = base64.urlsafe_b64encode(nonce + ciphertext).decode("ascii")
        return f"{ENVELOPE_PREFIX}{self.active_key_id}:{payload}"

    def decrypt(self, value: str | None) -> str | None:
        if value in (None, "") or not self.is_encrypted(value):
            # Read compatibility for existing rows. New writes still fail
            # closed, and the migration command upgrades these legacy values.
            return value
        try:
            _, version, key_id, payload = value.split(":", 3)
            if version != "v1":
                raise CookieDecryptionError(f"Unsupported cookie envelope version: {version}")
            key = self.keys.get(key_id)
            if key is None:
                raise CookieDecryptionError(f"Cookie key version '{key_id}' is unavailable")
            decoded = base64.urlsafe_b64decode(payload.encode("ascii"))
            if len(decoded) < 29:
                raise CookieDecryptionError("Encrypted cookie payload is truncated")
            plaintext = AESGCM(key).decrypt(decoded[:12], decoded[12:], self._aad(key_id))
            return plaintext.decode("utf-8")
        except CookieDecryptionError:
            raise
        except (InvalidTag, ValueError, UnicodeError) as exc:
            raise CookieDecryptionError("Encrypted cookie authentication failed") from exc

    def rotate(self, value: str | None) -> str | None:
        """Decrypt any configured envelope and re-encrypt with the active key."""
        if value in (None, ""):
            return value
        return self.encrypt(self.decrypt(value))


class EncryptedCookieText(TypeDecorator):
    """SQLAlchemy type that keeps the existing TEXT schema but encrypts values."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: Any) -> str | None:
        return CookieCipher.from_settings().encrypt(value)

    def process_result_value(self, value: str | None, dialect: Any) -> str | None:
        return CookieCipher.from_settings().decrypt(value)


def redact_sensitive_text(value: Any) -> str:
    text = str(value)
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    text = _ENVELOPE.sub("[ENCRYPTED_COOKIE]", text)
    text = _SESSION_ASSIGNMENT.sub(
        lambda match: f"session_hash={_session_digest(match.group(2))}", text
    )
    return _UUID.sub(lambda match: f"session_hash={_session_digest(match.group(0))}", text)


def redact_log_record(record: dict[str, Any]) -> bool:
    """Loguru filter that mutates message/extra before any sink receives it."""
    record["message"] = redact_sensitive_text(record.get("message", ""))
    if isinstance(record.get("extra"), dict):
        record["extra"] = {
            key: redact_sensitive_text(value)
            if key.casefold() in {"sessdata", "bili_jct", "csrf", "cookie", "cookies", "session_id"}
            else value
            for key, value in record["extra"].items()
        }
    return True
