"""Абстрактный интерфейс провайдера архивации."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
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

    @abstractmethod
    async def download_post(
        self,
        account,
        username: str,
        shortcode: str,
        target_dir: Path,
        include_media: bool,
        include_comments: bool,
        comments_limit: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        """Скачивает одну публикацию и возвращает metadata/comments."""
