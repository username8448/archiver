"""Чтение и запись скрытого bootstrap-файла приложения."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import dataclass

from config import BOOTSTRAP_FILE, ensure_state_dirs


@dataclass(frozen=True)
class BootstrapConfig:
    """Минимальная конфигурация, нужная до подключения к Postgres."""

    database_url: str
    app_secret: str


def _private_chmod(path) -> None:
    try:
        os.chmod(path, 0o600)
    except PermissionError:
        pass


def load_bootstrap() -> BootstrapConfig | None:
    """Возвращает скрытую bootstrap-конфигурацию, если первый запуск уже пройден."""
    env_database_url = os.getenv("DATABASE_URL")
    if env_database_url:
        return BootstrapConfig(
            database_url=env_database_url,
            app_secret=os.getenv("APP_SECRET", "environment"),
        )
    if not BOOTSTRAP_FILE.exists():
        return None
    data = json.loads(BOOTSTRAP_FILE.read_text(encoding="utf-8"))
    return BootstrapConfig(
        database_url=data["database_url"],
        app_secret=data["app_secret"],
    )


def is_configured() -> bool:
    """Проверяет, доступна ли bootstrap-конфигурация или DATABASE_URL."""
    return bool(os.getenv("DATABASE_URL")) or BOOTSTRAP_FILE.exists()


def save_bootstrap(database_url: str) -> BootstrapConfig:
    """Сохраняет PostgreSQL URL и служебный app secret вне проекта."""
    ensure_state_dirs()
    cfg = BootstrapConfig(
        database_url=database_url,
        app_secret=secrets.token_urlsafe(48),
    )
    tmp_path = BOOTSTRAP_FILE.with_suffix(".tmp")
    tmp_path.write_text(
        json.dumps(
            {"database_url": cfg.database_url, "app_secret": cfg.app_secret},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    _private_chmod(tmp_path)
    tmp_path.replace(BOOTSTRAP_FILE)
    _private_chmod(BOOTSTRAP_FILE)
    return cfg
