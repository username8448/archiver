"""Application-wide Instagram provider instance."""

from __future__ import annotations

from providers.instagram import InstagramPreviewProvider


def create_instagram_provider():
    """Creates the only supported Instagram provider."""
    return InstagramPreviewProvider()


instagram_provider = create_instagram_provider()
