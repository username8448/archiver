"""Media downloader adapters for job pipeline."""

from downloaders.providers import (
    DownloadProvider,
    GalleryDlImageDownloader,
    YtDlpVideoDownloader,
    downloader_for_media_type,
)

__all__ = [
    "DownloadProvider",
    "GalleryDlImageDownloader",
    "YtDlpVideoDownloader",
    "downloader_for_media_type",
]
