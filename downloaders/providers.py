"""Downloader provider facade for Instagram job media."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from downloaders.common import DownloadResult
from downloaders.instagram_gallery_dl import download_instagram_post
from downloaders.instagram_yt_dlp import download_instagram_video


class DownloadProvider(ABC):
    """Common interface for media download backends."""

    name: str
    media_types: frozenset[str]

    @abstractmethod
    async def download(
        self,
        shortcode: str,
        output_dir: Path,
        workspace: Path,
        timeout_sec: int,
        cookie_file: Path | None,
    ) -> DownloadResult:
        """Downloads one Instagram post into output_dir."""


class GalleryDlImageDownloader(DownloadProvider):
    """gallery-dl downloader for Instagram photos and carousels."""

    name = "gallery-dl"
    media_types = frozenset({"photo", "carousel"})

    async def download(
        self,
        shortcode: str,
        output_dir: Path,
        workspace: Path,
        timeout_sec: int,
        cookie_file: Path | None,
    ) -> DownloadResult:
        return await download_instagram_post(shortcode, output_dir, workspace, timeout_sec, cookie_file)


class YtDlpVideoDownloader(DownloadProvider):
    """yt-dlp downloader for Instagram videos and reels."""

    name = "yt-dlp"
    media_types = frozenset({"video", "reel"})

    async def download(
        self,
        shortcode: str,
        output_dir: Path,
        workspace: Path,
        timeout_sec: int,
        cookie_file: Path | None,
    ) -> DownloadResult:
        return await download_instagram_video(shortcode, output_dir, workspace, timeout_sec, cookie_file)


_DOWNLOADERS: tuple[DownloadProvider, ...] = (
    GalleryDlImageDownloader(),
    YtDlpVideoDownloader(),
)


def downloader_for_media_type(media_type: str | None) -> DownloadProvider | None:
    """Returns the downloader that owns media_type."""
    normalized = (media_type or "unknown").strip().lower()
    for downloader in _DOWNLOADERS:
        if normalized in downloader.media_types:
            return downloader
    return None
