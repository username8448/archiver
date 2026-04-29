"""Optional yt-dlp fallback for one Instagram video post."""

from __future__ import annotations

from pathlib import Path

from downloaders.common import (
    DownloadResult,
    collect_media_files,
    ensure_inside,
    instagram_post_url,
    module_available,
    run_python_module,
    truncate_diagnostic,
)


async def download_instagram_video(
    shortcode: str,
    output_dir: Path,
    workspace: Path,
    timeout_sec: int,
) -> DownloadResult:
    """Attempts video download for one post using yt-dlp."""
    if not module_available("yt_dlp"):
        return DownloadResult(
            ok=False,
            error_code="YT_DLP_NOT_AVAILABLE",
            error_message="yt-dlp is not installed in the application environment.",
        )

    try:
        output_dir = ensure_inside(workspace, output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return DownloadResult(ok=False, error_code="STORAGE_ERROR", error_message=str(exc))
    except ValueError as exc:
        return DownloadResult(ok=False, error_code="STORAGE_ERROR", error_message=str(exc))

    before = set(collect_media_files(output_dir, workspace))
    try:
        code, stdout, stderr = await run_python_module(
            "yt_dlp",
            [
                "--no-playlist",
                "--paths",
                str(output_dir),
                "--output",
                "%(id)s.%(ext)s",
                instagram_post_url(shortcode),
            ],
            cwd=workspace,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        return DownloadResult(ok=False, error_code="TIMEOUT", error_message=str(exc))
    except OSError as exc:
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_message=str(exc))

    media_files = collect_media_files(output_dir, workspace)
    new_files = [path for path in media_files if path not in before]
    if code != 0:
        message = truncate_diagnostic(stderr or stdout) or "yt-dlp failed"
        return DownloadResult(
            ok=False,
            media_files=new_files,
            error_code="DOWNLOAD_FAILED",
            error_message=message,
        )
    if not new_files:
        return DownloadResult(
            ok=False,
            error_code="MEDIA_NOT_AVAILABLE",
            error_message="yt-dlp did not produce a video file for this post.",
        )
    return DownloadResult(ok=True, media_files=new_files)
