"""Чтение и обновление runtime-настроек из PostgreSQL."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from archive import resolve_archive_root
from config import DEFAULT_SETTINGS
from models import Setting

logger = logging.getLogger("instagram_archiver")


class SettingsValidationError(ValueError):
    """Raised when a runtime setting fails safe validation."""


INT_SETTING_RANGES = {
    "preview_cache_ttl_sec": (60, 86_400),
    "rate_limit_wait_sec": (60, 86_400),
    "scheduler_interval_sec": (5, 3_600),
    "default_preview_posts": (1, 200),
    "max_active_jobs": (1, 10),
    "max_concurrent_downloads": (1, 10),
    "download_timeout_sec": (10, 3_600),
    "download_retry_attempts": (1, 10),
    "comments_limit": (0, 5_000),
}


def validate_setting_value(key: str, value: Any) -> Any:
    """Coerces and validates one known setting value."""
    if key == "archive_dir":
        if not isinstance(value, str) or not value.strip():
            raise SettingsValidationError("archive_dir must be a non-empty string")
        try:
            return str(resolve_archive_root(value.strip()))
        except ValueError as exc:
            raise SettingsValidationError(str(exc)) from exc

    if key in INT_SETTING_RANGES:
        if isinstance(value, bool):
            raise SettingsValidationError(f"{key} must be an integer")
        try:
            number = int(value)
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError(f"{key} must be an integer") from exc
        minimum, maximum = INT_SETTING_RANGES[key]
        if number < minimum or number > maximum:
            raise SettingsValidationError(f"{key} must be between {minimum} and {maximum}")
        return number

    if key not in DEFAULT_SETTINGS:
        raise SettingsValidationError(f"Unknown setting: {key}")
    return value


async def get_settings_map(db: AsyncSession) -> dict[str, Any]:
    """Возвращает дефолты, переопределённые значениями из таблицы settings."""
    values = {key: validate_setting_value(key, value) for key, value in DEFAULT_SETTINGS.items()}
    rows = (await db.execute(select(Setting))).scalars().all()
    for row in rows:
        if row.key not in DEFAULT_SETTINGS:
            continue
        try:
            values[row.key] = validate_setting_value(row.key, row.value)
        except SettingsValidationError:
            logger.info("Ignoring invalid stored setting %s", row.key)
    return values


async def seed_default_settings(db: AsyncSession) -> None:
    """Создаёт отсутствующие настройки с безопасными дефолтами."""
    existing = set((await db.execute(select(Setting.key))).scalars().all())
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(Setting(key=key, value=validate_setting_value(key, value)))
    await db.commit()


async def update_settings_map(db: AsyncSession, patch: dict[str, Any]) -> dict[str, Any]:
    """Обновляет только известные ключи настроек."""
    allowed = set(DEFAULT_SETTINGS)
    for key, value in patch.items():
        if key not in allowed:
            continue
        value = validate_setting_value(key, value)
        row = await db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    await db.commit()
    return await get_settings_map(db)
