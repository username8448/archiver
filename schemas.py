"""Pydantic-схемы публичного API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class SetupStatusResponse(BaseModel):
    configured: bool
    database_connected: bool = False
    needs_login: bool = True
    error: str | None = None


class HealthResponse(BaseModel):
    status: str
    database_connected: bool
    vault_ready: bool
    version: str
    admins_initialized: bool
    error: str | None = None


class SetupInitializeRequest(BaseModel):
    admin_username: str = Field(min_length=3, max_length=120)
    admin_password: str = Field(min_length=8)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=120)
    password: str = Field(min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any]


class AccountResponse(BaseModel):
    id: str
    username: str
    secret_kind: str
    status: str
    is_default: bool
    failure_reason: str | None = None
    last_validated_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ProfilePreviewRequest(BaseModel):
    target: str
    limit: int | None = Field(default=None, ge=1, le=200)
    force_refresh: bool = False


class ProfilePreviewResponse(BaseModel):
    ok: bool = True
    source: Literal["fresh", "cache"] = "fresh"
    error: dict[str, Any] | None = None
    cached_until: datetime | None = None
    from_cache: bool = False
    profile: dict[str, Any]


class JobCreateRequest(BaseModel):
    target: str
    mode: Literal["meta-only", "last-n", "selected", "all-media"] = "last-n"
    shortcodes: list[str] = Field(default_factory=list)
    limit: int | None = Field(default=None, ge=1, le=500)
    options: dict[str, Any] = Field(default_factory=dict)


class JobItemResponse(BaseModel):
    id: int
    shortcode: str
    target: str | None = None
    media_type: str | None = None
    status: str
    error_code: str | None = None
    error_message: str | None = None
    result_path: str | None = None
    metadata_path: str | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class JobStatusResponse(BaseModel):
    ok: bool = True
    id: str
    job_id: str
    target: str
    username: str
    mode: str
    status: str
    items_done: int
    items_total: int
    completed_items: int
    failed_items: int
    retry_after_at: datetime | None = None
    failure_reason: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    archive_ready: bool = False
    can_resume: bool = False
    download_url: str | None = None
    manifest_url: str | None = None
    result_dir: str | None = None
    archive_filename: str | None = None
    archive_size_bytes: int | None = None
    items: list[JobItemResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
