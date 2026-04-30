"""Common helpers for controlled media downloader subprocesses."""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from dataclasses import dataclass, field
from pathlib import Path


MEDIA_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".gif",
    ".mp4",
    ".mov",
    ".m4v",
    ".webm",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".webm"}
SIDECAR_EXTENSIONS = {".json", ".txt"}
MAX_DIAGNOSTIC_CHARS = 800


@dataclass(slots=True)
class DownloadResult:
    ok: bool
    media_files: list[str] = field(default_factory=list)
    metadata_file: str | None = None
    sidecar_files: list[str] = field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None


def module_available(module_name: str) -> bool:
    """Checks an optional downloader module without importing it."""
    return importlib.util.find_spec(module_name) is not None


def instagram_post_url(shortcode: str) -> str:
    """Builds the canonical Instagram post URL for a real shortcode."""
    return f"https://www.instagram.com/p/{shortcode}/"


def ensure_inside(root: Path, path: Path) -> Path:
    """Resolves a path and rejects traversal outside root."""
    root_resolved = root.resolve()
    path_resolved = path.resolve()
    if path_resolved != root_resolved and root_resolved not in path_resolved.parents:
        raise ValueError("Path escapes job workspace")
    return path_resolved


def collect_media_files(output_dir: Path, workspace: Path) -> list[str]:
    """Returns media files under output_dir as workspace-relative POSIX paths."""
    output_dir = ensure_inside(workspace, output_dir)
    files: list[str] = []
    if not output_dir.exists():
        return files
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS:
            files.append(path.resolve().relative_to(workspace.resolve()).as_posix())
    return files


def collect_sidecar_files(output_dir: Path, workspace: Path) -> list[str]:
    """Returns downloader sidecar files under output_dir as workspace-relative POSIX paths."""
    output_dir = ensure_inside(workspace, output_dir)
    files: list[str] = []
    if not output_dir.exists():
        return files
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SIDECAR_EXTENSIONS:
            files.append(path.resolve().relative_to(workspace.resolve()).as_posix())
    return files


def has_video_file(media_files: list[str]) -> bool:
    """True if a media file list contains a video-like extension."""
    return any(Path(path).suffix.lower() in VIDEO_EXTENSIONS for path in media_files)


def truncate_diagnostic(value: str) -> str:
    """Keeps subprocess diagnostics short and secret-safe."""
    text = " ".join((value or "").split())
    if len(text) <= MAX_DIAGNOSTIC_CHARS:
        return text
    return text[:MAX_DIAGNOSTIC_CHARS].rstrip() + "..."


async def run_python_module(
    module_name: str,
    args: list[str],
    cwd: Path,
    timeout_sec: int,
) -> tuple[int, str, str]:
    """Runs an optional downloader module without shell interpolation."""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module_name,
        *args,
        cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_sec)
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise TimeoutError(f"{module_name} timed out after {timeout_sec}s")
    return (
        process.returncode or 0,
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
    )
