"""Чтение и обновление runtime-настроек из PostgreSQL."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import DEFAULT_SETTINGS
from models import Setting


async def get_settings_map(db: AsyncSession) -> dict[str, Any]:
    """Возвращает дефолты, переопределённые значениями из таблицы settings."""
    values = dict(DEFAULT_SETTINGS)
    rows = (await db.execute(select(Setting))).scalars().all()
    for row in rows:
        values[row.key] = row.value
    return values


async def seed_default_settings(db: AsyncSession) -> None:
    """Создаёт отсутствующие настройки с безопасными дефолтами."""
    existing = set((await db.execute(select(Setting.key))).scalars().all())
    for key, value in DEFAULT_SETTINGS.items():
        if key not in existing:
            db.add(Setting(key=key, value=value))
    await db.commit()


async def update_settings_map(db: AsyncSession, patch: dict[str, Any]) -> dict[str, Any]:
    """Обновляет только известные ключи настроек."""
    allowed = set(DEFAULT_SETTINGS)
    for key, value in patch.items():
        if key not in allowed:
            continue
        row = await db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=value))
        else:
            row.value = value
    await db.commit()
    return await get_settings_map(db)
