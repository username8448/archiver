"""Безопасные дефолты приложения без пользовательских секретов."""

import os
from pathlib import Path


APP_NAME = "Instagram Archiver"
APP_VERSION = "1.0.0"

PROJECT_ROOT = Path(__file__).resolve().parent
STATIC_DIR = PROJECT_ROOT / "static"

STATE_DIR = Path.home() / ".instagram_archiver"
BOOTSTRAP_FILE = STATE_DIR / "bootstrap.json"
VAULT_DIR = STATE_DIR / "vault"
MASTER_KEY_FILE = STATE_DIR / "master.key"
DEFAULT_ARCHIVE_DIR = STATE_DIR / "archives"

SESSION_COOKIE_NAME = "archiver_session"
SESSION_TTL_SECONDS = 60 * 60 * 12
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "").lower() in {"1", "true", "yes", "on"}

MAX_UPLOAD_BYTES = 5 * 1024 * 1024

DEFAULT_SETTINGS = {
    "preview_cache_ttl_sec": 3600,
    "rate_limit_wait_sec": 3600,
    "scheduler_interval_sec": 60,
    "default_preview_posts": 24,
    "archive_dir": str(DEFAULT_ARCHIVE_DIR),
    "max_active_jobs": 1,
    "comments_limit": 500,
}

RESUMABLE_FAILURES = {
    "RATE_LIMIT",
    "NETWORK_ERROR",
    "DOWNLOAD_ERROR",
    "ARCHIVE_ERROR",
}

CRITICAL_FAILURES = {
    "LOGIN_REQUIRED",
    "CHECKPOINT_REQUIRED",
    "PRIVATE_PROFILE",
    "PROFILE_NOT_FOUND",
}


def ensure_state_dirs() -> None:
    """Создаёт скрытые локальные каталоги с приватными правами."""
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    VAULT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    DEFAULT_ARCHIVE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
