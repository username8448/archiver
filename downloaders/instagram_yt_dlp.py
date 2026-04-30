"""Controlled yt-dlp adapter for one Instagram video/reel post."""

from __future__ import annotations

from pathlib import Path

from downloaders.common import (
    DownloadResult,
    collect_media_files,
    collect_sidecar_files,
    has_video_file,
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
    cookie_file: Path | None = None,
) -> DownloadResult:
    """Downloads one Instagram video/reel using yt-dlp."""
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

    try:
        args = [
            "--no-config",
            "--no-playlist",
            "--paths",
            str(output_dir),
            "--output",
            "%(id)s.%(ext)s",
            "--write-info-json",
        ]
        if cookie_file is not None:
            args.extend(["--cookies", str(cookie_file)])
        args.append(instagram_post_url(shortcode))
        code, stdout, stderr = await run_python_module(
            "yt_dlp",
            args,
            cwd=workspace,
            timeout_sec=timeout_sec,
        )
    except TimeoutError as exc:
        return DownloadResult(ok=False, error_code="TIMEOUT", error_message=str(exc))
    except OSError as exc:
        return DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_message=str(exc))

    media_files = collect_media_files(output_dir, workspace)
    sidecar_files = collect_sidecar_files(output_dir, workspace)
    if code != 0:
        message = truncate_diagnostic(stderr or stdout) or "yt-dlp failed"
        return DownloadResult(
            ok=False,
            media_files=media_files,
            sidecar_files=sidecar_files,
            error_code=_classify_yt_dlp_error(stderr or stdout),
            error_message=message,
        )
    if not has_video_file(media_files):
        return DownloadResult(
            ok=False,
            error_code="MEDIA_NOT_AVAILABLE",
            media_files=media_files,
            sidecar_files=sidecar_files,
            metadata_file=sidecar_files[0] if sidecar_files else None,
            error_message="yt-dlp did not produce a video file for this post.",
        )
    return DownloadResult(
        ok=True,
        media_files=media_files,
        metadata_file=sidecar_files[0] if sidecar_files else None,
        sidecar_files=sidecar_files,
    )


def _classify_yt_dlp_error(output: str) -> str:
    """Maps yt-dlp diagnostics to stable job error codes."""
    text = (output or "").lower()
    if "private" in text:
        return "PRIVATE_PROFILE"
    if (
        "login required" in text
        or "sign in" in text
        or "not logged in" in text
        or "cookies" in text
        or "http error 401" in text
        or "http error 403" in text
    ):
        return "LOGIN_REQUIRED"
    if "rate limit" in text or "too many requests" in text or "please wait" in text or "http error 429" in text:
        return "RATE_LIMIT"
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if (
        "temporary failure" in text
        or "connection" in text
        or "network" in text
        or "unable to download webpage" in text
        or "http error 5" in text
        or "remote end closed" in text
        or "tls" in text
    ):
        return "NETWORK_ERROR"
    if "no video" in text or "no formats" in text or "requested format is not available" in text:
        return "MEDIA_NOT_AVAILABLE"
    return "DOWNLOAD_FAILED"
