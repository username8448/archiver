"""Сохранение результата задачи и сборка ZIP-архива."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from config import ARCHIVE_DIR_ALLOWED_ROOTS, DEFAULT_ARCHIVE_DIR
from instagram_ids import normalize_instagram_shortcode


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _is_inside(root: Path, path: Path) -> bool:
    return path == root or root in path.parents


def allowed_archive_roots() -> tuple[Path, ...]:
    """Returns resolved archive roots allowed to contain job workspaces and ZIPs."""
    roots = (DEFAULT_ARCHIVE_DIR, *ARCHIVE_DIR_ALLOWED_ROOTS)
    return tuple(dict.fromkeys(_resolve_path(root) for root in roots))


def resolve_archive_root(archive_dir: str | None) -> Path:
    """Normalizes archive_dir and rejects roots outside the configured allowlist."""
    root = _resolve_path(Path(archive_dir or DEFAULT_ARCHIVE_DIR))
    if not any(_is_inside(allowed_root, root) for allowed_root in allowed_archive_roots()):
        raise ValueError("Archive directory is outside allowed roots")
    root.mkdir(parents=True, exist_ok=True)
    return root


def ensure_inside(root: Path, path: Path) -> Path:
    """Resolves path and rejects traversal outside root."""
    root_resolved = _resolve_path(root)
    path_resolved = _resolve_path(path)
    if not _is_inside(root_resolved, path_resolved):
        raise ValueError("Path escapes archive workspace")
    return path_resolved


def ensure_allowed_archive_path(path: Path) -> Path:
    """Ensures path resolves under an allowed archive root."""
    resolved = _resolve_path(path)
    if not any(_is_inside(root, resolved) for root in allowed_archive_roots()):
        raise ValueError("Archive path is outside allowed roots")
    return resolved


def workspace_for_job(archive_dir: str | None, job_id: str) -> Path:
    """Возвращает каталог рабочей области job."""
    root = resolve_archive_root(archive_dir)
    safe_job_id = normalize_instagram_shortcode(job_id)
    workspace = ensure_inside(root, root / "jobs" / safe_job_id)
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def write_json(path: Path, payload: Any, root: Path) -> None:
    """Пишет JSON с UTF-8 и читаемым форматированием."""
    path = ensure_inside(root, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_zip(workspace: Path, job_id: str) -> Path:
    """Упаковывает рабочую область job в ZIP."""
    workspace = ensure_allowed_archive_path(workspace)
    archive_root = ensure_allowed_archive_path(workspace.parent.parent)
    safe_job_id = normalize_instagram_shortcode(job_id)
    zip_path = ensure_inside(archive_root, archive_root / f"{safe_job_id}.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in workspace.rglob("*"):
            if path.is_symlink():
                continue
            if path.is_file():
                path = ensure_inside(workspace, path)
                zf.write(path, path.relative_to(workspace))
    return zip_path
