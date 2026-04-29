"""Пароли и admin-сессии без внешнего хранилища секретов."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import timedelta

from models import utcnow


def hash_password(password: str) -> str:
    """Хеширует пароль PBKDF2-HMAC-SHA256 с индивидуальной солью."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 260_000)
    return "pbkdf2_sha256$260000$%s$%s" % (
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def verify_password(password: str, password_hash: str) -> bool:
    """Проверяет пароль против сохранённого PBKDF2-хеша."""
    try:
        algo, rounds, salt_b64, digest_b64 = password_hash.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(rounds))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def new_session_token() -> str:
    """Создаёт случайный bearer/cookie token."""
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    """Хеширует session token перед сохранением в БД."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def session_expires(ttl_seconds: int):
    """Возвращает срок действия admin-сессии."""
    return utcnow() + timedelta(seconds=ttl_seconds)
