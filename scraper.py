"""Совместимая точка доступа к Instagram preview/download provider."""

from __future__ import annotations

import os

from providers.instagram import InstagrapiPreviewProvider, InstaloaderProvider


def create_instagram_provider():
    """Создаёт provider по env, сохраняя instaloader как безопасный default."""
    provider_name = os.getenv("INSTAGRAM_PREVIEW_PROVIDER", "instaloader").strip().lower()
    if provider_name in {"", "instaloader"}:
        return InstaloaderProvider()
    if provider_name == "instagrapi":
        return InstagrapiPreviewProvider()
    raise RuntimeError(
        "Unsupported INSTAGRAM_PREVIEW_PROVIDER. Use 'instaloader' or 'instagrapi'."
    )


instagram_provider = create_instagram_provider()
