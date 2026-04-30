"""Абстрактный интерфейс провайдера архивации."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ProviderError(Exception):
    """Ошибка провайдера с машинным reason для jobs/status."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


class BaseProvider(ABC):
    """Минимальный контракт провайдера социальной платформы."""

    @abstractmethod
    def normalize_target(self, value: str) -> str:
        """Преобразует URL или @username в нормализованный username."""

    @abstractmethod
    async def validate_account(self, account) -> tuple[bool, str | None]:
        """Проверяет пригодность сохранённого account secret."""

    @abstractmethod
    async def profile_preview(self, account, username: str, limit: int) -> dict[str, Any]:
        """Возвращает профиль и последние публикации."""
