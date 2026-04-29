"""Controlled gallery-dl adapter for one Instagram post."""

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


async def download_instagram_post(
    shortcode: str,
    output_dir: Path,
    workspace: Path,
    timeout_sec: int,
) -> DownloadResult:
    """Downloads media for one public Instagram post into output_dir."""
    if not module_available("gallery_dl"):
        return DownloadResult(
            ok=False,
            error_code="GALLERY_DL_NOT_AVAILABLE",
            error_message="gallery-dl is not installed in the application environment.",
        )

    try:
        output_dir = ensure_inside(workspace, output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return DownloadResult(ok=False, error_code="STORAGE_ERROR", error_message=str(exc))
    except ValueError as exc:
        return DownloadResult(ok=False, error_code="STORAGE_ERROR", error_message=str(exc))

    try:
        code, stdout, stderr = await run_python_module(
            "gallery_dl",
            [
                "--dest",
                str(output_dir),
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
    if code != 0:
        message = truncate_diagnostic(stderr or stdout) or "gallery-dl failed"
        return DownloadResult(
            ok=False,
            media_files=media_files,
            error_code="DOWNLOAD_FAILED",
            error_message=message,
        )
    if not media_files:
        return DownloadResult(
            ok=False,
            error_code="MEDIA_NOT_AVAILABLE",
            error_message="gallery-dl did not produce media files for this post.",
        )
    return DownloadResult(ok=True, media_files=media_files)
