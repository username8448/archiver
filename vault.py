"""Encrypted vault для Instagram session/cookie файлов вне проекта."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from cryptography.fernet import Fernet

from config import MASTER_KEY_FILE, VAULT_DIR, ensure_state_dirs


def _chmod_private(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except PermissionError:
        pass


def ensure_master_key() -> bytes:
    """Создаёт или читает master key Fernet в скрытой директории."""
    ensure_state_dirs()
    if MASTER_KEY_FILE.exists():
        return MASTER_KEY_FILE.read_bytes()
    key = Fernet.generate_key()
    MASTER_KEY_FILE.write_bytes(key)
    _chmod_private(MASTER_KEY_FILE)
    return key


def _fernet() -> Fernet:
    return Fernet(ensure_master_key())


def save_secret(raw_bytes: bytes) -> str:
    """Шифрует bytes и возвращает secret_id без раскрытия пути наружу."""
    ensure_state_dirs()
    secret_id = str(uuid.uuid4())
    encrypted = _fernet().encrypt(raw_bytes)
    path = VAULT_DIR / f"{secret_id}.bin"
    path.write_bytes(encrypted)
    _chmod_private(path)
    return secret_id


def replace_secret(secret_id: str, raw_bytes: bytes) -> None:
    """Перезаписывает encrypted secret без изменения публичного secret_id."""
    ensure_state_dirs()
    path = VAULT_DIR / f"{secret_id}.bin"
    encrypted = _fernet().encrypt(raw_bytes)
    tmp_path = VAULT_DIR / f".{secret_id}.{uuid.uuid4().hex}.tmp"
    try:
        tmp_path.write_bytes(encrypted)
        _chmod_private(tmp_path)
        tmp_path.replace(path)
        _chmod_private(path)
    finally:
        try:
            tmp_path.unlink()
        except FileNotFoundError:
            pass


def load_secret(secret_id: str) -> bytes:
    """Расшифровывает secret по id."""
    path = VAULT_DIR / f"{secret_id}.bin"
    return _fernet().decrypt(path.read_bytes())


def delete_secret(secret_id: str | None) -> None:
    """Удаляет encrypted secret, если он существует."""
    if not secret_id:
        return
    path = VAULT_DIR / f"{secret_id}.bin"
    try:
        path.unlink()
    except FileNotFoundError:
        pass
