"""Сохранение результата задачи и сборка ZIP-архива."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

from config import DEFAULT_ARCHIVE_DIR


def workspace_for_job(archive_dir: str | None, job_id: str) -> Path:
    """Возвращает каталог рабочей области job."""
    root = Path(archive_dir or DEFAULT_ARCHIVE_DIR).expanduser()
    workspace = root / "jobs" / job_id
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def write_json(path: Path, payload: Any) -> None:
    """Пишет JSON с UTF-8 и читаемым форматированием."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def build_zip(workspace: Path, job_id: str) -> Path:
    """Упаковывает рабочую область job в ZIP."""
    zip_path = workspace.parent.parent / f"{job_id}.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in workspace.rglob("*"):
            if path.is_file():
                zf.write(path, path.relative_to(workspace))
    return zip_path
