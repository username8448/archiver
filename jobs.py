"""Фоновый менеджер задач архивации."""

from __future__ import annotations

import asyncio
import logging
from contextlib import ExitStack
from datetime import timedelta
from time import monotonic
from typing import Any

from sqlalchemy import func, select

from archive import build_zip, workspace_for_job, write_json
from config import RESUMABLE_FAILURES
from database import session_context
from downloaders.common import DownloadResult, redact_diagnostic
from downloaders.cookies import downloader_cookie_file
from downloaders.providers import downloader_for_media_type
from instagram_ids import normalize_instagram_shortcode
from models import Account, Comment, Job, JobItem, Post, ProfileCache, utcnow
from providers.base import ProviderError
from scraper import instagram_provider
from settings_service import get_settings_map

ACTIVE_STATUSES = {"PENDING", "RUNNING", "WAITING", "queued", "running", "waiting"}
DONE_STATUSES = {"DONE", "completed"}
FAILED_STATUSES = {"FAILED", "failed"}
CANCELLED_STATUSES = {"CANCELLED", "cancelled"}
WAITING_STATUSES = {"WAITING", "waiting"}
RETRYABLE_DOWNLOAD_ERRORS = {"TIMEOUT", "NETWORK_ERROR", "DOWNLOAD_FAILED"}
PROFILE_INDEX_STAGES = {
    "prepare_session": "Готовим Instagram-сессию",
    "validate_session": "Проверяем Instagram-сессию",
    "fetch_profile": "Получаем профиль",
    "fetch_posts": "Получаем индекс публикаций",
    "save_index": "Сохраняем индекс",
    "done": "Индекс готов",
    "failed": "Индексация завершилась ошибкой",
}
ENRICHMENT_STAGE_LABELS = {
    "full_json": "Сохраняем JSON",
    "images": "Скачиваем изображения",
    "videos": "Скачиваем видео",
    "comments": "Скачиваем комментарии",
    "zip": "Собираем ZIP",
    "done": "Задача завершена",
    "failed": "Задача завершилась ошибкой",
    "waiting": "Пауза rate limit",
}
ENRICHMENT_STAGES = ("full_json", "images", "videos", "comments", "zip")
IMAGE_MEDIA_TYPES = {"photo", "carousel"}
VIDEO_MEDIA_TYPES = {"video", "reel"}
GLOBAL_ABORT_ERRORS = {
    "LOGIN_REQUIRED",
    "INVALID_SESSION",
    "CHECKPOINT_REQUIRED",
    "BAD_CREDENTIALS",
    "TWO_FACTOR_REQUIRED",
    "COOKIES_FORMAT_UNKNOWN",
    "UNSUPPORTED_LEGACY_SESSION",
    "RATE_LIMIT",
    "PRIVATE_PROFILE",
}
_scheduled: set[str] = set()
logger = logging.getLogger("uvicorn.error")


def _safe_timing_log(message: str, *args: object) -> None:
    safe_args = tuple(redact_diagnostic(str(arg)) if isinstance(arg, str) else arg for arg in args)
    logger.info(message, *safe_args)
    try:
        print(message % safe_args, flush=True)
    except Exception:
        pass


def _duration_ms(started_at: float) -> float:
    return round((monotonic() - started_at) * 1000, 2)


async def find_active_job(db) -> Job | None:
    """Возвращает активную сетевую задачу, если она есть."""
    return (
        await db.execute(
            select(Job)
            .where(Job.status.in_(ACTIVE_STATUSES))
            .order_by(Job.created_at.asc())
            .limit(1)
        )
    ).scalar_one_or_none()


def schedule_job(job_id: str) -> None:
    """Ставит job в фоновые asyncio-задачи текущего процесса."""
    if job_id in _scheduled:
        return
    _scheduled.add(job_id)
    task = asyncio.create_task(run_job(job_id))
    task.add_done_callback(lambda _: _scheduled.discard(job_id))


async def run_job(job_id: str) -> None:
    """Routes a scheduled job to its concrete worker."""
    async with session_context() as db:
        job = await db.get(Job, job_id)
        if job is None or job.status in DONE_STATUSES | CANCELLED_STATUSES:
            return
        job_type = getattr(job, "type", None) or "enrichment"

    if job_type == "profile_index":
        await run_profile_index_job(job_id)
        return
    await run_enrichment_job(job_id)


async def run_profile_index_job(job_id: str) -> None:
    """Indexes profile metadata and post metadata without downloading media."""
    started_at = monotonic()
    user_info_ms = 0.0
    user_medias_ms = 0.0
    save_index_ms = 0.0
    async with session_context() as db:
        job = await db.get(Job, job_id)
        if job is None or job.status in DONE_STATUSES | CANCELLED_STATUSES:
            return
        account = await db.get(Account, job.account_id) if job.account_id else None
        if account is None:
            await _fail_profile_index_job(db, job, "LOGIN_REQUIRED", "Не выбран аккаунт Instagram")
            return

        settings = await get_settings_map(db)
        workspace = workspace_for_job(settings.get("archive_dir"), job.id)
        limit = max(0, min(200, int((job.options or {}).get("limit", 24) or 0)))
        force_refresh = bool((job.options or {}).get("force_refresh", False))
        job.type = "profile_index"
        job.status = "RUNNING"
        job.result_dir = str(workspace)
        job.started_at = job.started_at or utcnow()
        job.finished_at = None
        job.failure_reason = None
        job.error_code = None
        job.error_message = None
        job.retry_after_at = None
        await _set_profile_index_stage(db, job, "prepare_session", 0, limit)
        _safe_timing_log(
            "profile_index_start job_id=%s target=%s limit=%s force_refresh=%s",
            job.id,
            job.username,
            limit,
            force_refresh,
        )

        try:
            await _set_profile_index_stage(db, job, "validate_session", 0, limit)
            validator = getattr(instagram_provider, "validate_account", None)
            if callable(validator):
                ok, reason = await validator(account)
                if not ok:
                    raise ProviderError(reason or "LOGIN_REQUIRED", "Instagram-сессия недействительна")

            await _set_profile_index_stage(db, job, "fetch_profile", 0, limit)
            step_started_at = monotonic()
            profile_info = await instagram_provider.profile_info(account, job.username, force_refresh=force_refresh)
            user_info_ms = _duration_ms(step_started_at)
            profile_pk = str(profile_info.pop("_pk", "") or "")
            media_count = _optional_int(profile_info.get("posts_count")) or 0
            media_limit = min(limit, media_count) if media_count > 0 and limit > 0 else 0
            posts: list[dict[str, Any]] = []

            if media_limit > 0:
                await _set_profile_index_stage(db, job, "fetch_posts", 0, media_limit)
                step_started_at = monotonic()
                posts = await instagram_provider.profile_medias_index(account, profile_pk, media_limit)
                user_medias_ms = _duration_ms(step_started_at)
                await _set_profile_index_stage(db, job, "fetch_posts", len(posts), media_limit)
            else:
                await _set_profile_index_stage(db, job, "fetch_posts", 0, 0)

            await _set_profile_index_stage(db, job, "save_index", len(posts), media_limit)
            step_started_at = monotonic()
            index_result = {"profile": profile_info, "posts": posts}
            cache_payload = dict(profile_info)
            cache_payload["posts"] = posts
            write_json(workspace / "profile.json", profile_info, workspace)
            write_json(workspace / "posts_index.json", posts, workspace)
            write_json(workspace / "index.json", index_result, workspace)

            now = utcnow()
            ttl = int(settings.get("preview_cache_ttl_sec", 3600))
            cache = await db.get(ProfileCache, job.username)
            if cache is None:
                db.add(
                    ProfileCache(
                        username=job.username,
                        payload=cache_payload,
                        fetched_at=now,
                        expires_at=now + timedelta(seconds=ttl),
                        account_id=account.id,
                    )
                )
            else:
                cache.payload = cache_payload
                cache.fetched_at = now
                cache.expires_at = now + timedelta(seconds=ttl)
                cache.account_id = account.id
            save_index_ms = _duration_ms(step_started_at)

            progress_payload = dict(job.progress_payload or {})
            progress_payload["result"] = index_result
            progress_payload["timings"] = {
                "user_info_ms": user_info_ms,
                "user_medias_ms": user_medias_ms,
                "save_index_ms": save_index_ms,
                "total_ms": _duration_ms(started_at),
            }
            job.progress_payload = progress_payload
            job.stage = "done"
            job.status = "DONE"
            job.progress_current = media_limit
            job.progress_total = media_limit
            job.current_item = None
            job.finished_at = utcnow()
            await db.commit()
            _safe_timing_log(
                "profile_index_done job_id=%s target=%s user_info_ms=%.2f user_medias_ms=%.2f save_index_ms=%.2f total_ms=%.2f",
                job.id,
                job.username,
                user_info_ms,
                user_medias_ms,
                save_index_ms,
                _duration_ms(started_at),
            )
        except ProviderError as exc:
            _safe_timing_log(
                "profile_index_failed job_id=%s target=%s error_code=%s total_ms=%.2f",
                job.id,
                job.username,
                exc.reason,
                _duration_ms(started_at),
            )
            await _fail_profile_index_job(db, job, exc.reason, exc.message)
        except Exception as exc:
            await _fail_profile_index_job(db, job, "PROVIDER_ERROR", redact_diagnostic(str(exc)))


async def run_enrichment_job(job_id: str) -> None:
    """Runs selective task-based enrichment/download work."""
    async with session_context() as db:
        job = await db.get(Job, job_id)
        if job is None or job.status in DONE_STATUSES | CANCELLED_STATUSES:
            return
        account = await db.get(Account, job.account_id) if job.account_id else None
        if account is None:
            await _fail_job(db, job, "LOGIN_REQUIRED", "Не выбран аккаунт Instagram", stage="failed")
            return

        settings = await get_settings_map(db)
        workspace = workspace_for_job(settings.get("archive_dir"), job.id)
        job.type = "enrichment"
        job.status = "RUNNING"
        job.result_dir = str(workspace)
        job.started_at = job.started_at or utcnow()
        job.finished_at = None
        job.failure_reason = None
        job.error_code = None
        job.error_message = None
        job.retry_after_at = None

        cache = await db.get(ProfileCache, job.username)
        cached_posts = _cached_posts_by_shortcode(cache)
        if cache:
            write_json(workspace / "profile.json", cache.payload, workspace)
        write_json(
            workspace / "README.txt",
            {
                "job_id": job.id,
                "username": job.username,
                "created_at": job.created_at.isoformat(),
                "note": "Архив создан локально Instagram Archiver.",
            },
            workspace,
        )

        rows = (
            await db.execute(
                select(JobItem)
                .where(JobItem.job_id == job.id)
                .order_by(JobItem.id.asc())
            )
        ).scalars().all()
        tasks = _job_tasks(job)
        _initialize_enrichment_items(rows, job.username, tasks)
        stages = _build_enrichment_stages(tasks, rows)
        await _update_enrichment_progress(db, job, "full_json", None, stages)

        comments_limit = int(settings.get("comments_limit", 500))
        download_timeout_sec = int(settings.get("download_timeout_sec", 300))
        download_retry_attempts = max(1, int(settings.get("download_retry_attempts", 2)))

        with ExitStack() as stack:
            cookie_file = None
            if tasks["images"] or tasks["videos"]:
                try:
                    cookies = await _downloader_cookies(account)
                    cookie_file = stack.enter_context(downloader_cookie_file(cookies))
                except ProviderError as exc:
                    await _fail_job(db, job, exc.reason, exc.message, stage="failed")
                    return
                except Exception as exc:
                    await _fail_job(db, job, "DOWNLOAD_ERROR", redact_diagnostic(str(exc)), stage="failed")
                    return

            if not await _run_full_json_stage(db, job, account, workspace, rows, cached_posts, tasks, stages):
                return
            _refresh_media_stage_totals(stages, tasks, rows)
            await _update_enrichment_progress(db, job, "images", None, stages)

            if not await _run_download_stage(
                db,
                job,
                account,
                workspace,
                rows,
                cached_posts,
                tasks,
                stages,
                "images",
                "image_status",
                IMAGE_MEDIA_TYPES,
                download_timeout_sec,
                cookie_file,
                download_retry_attempts,
            ):
                return
            if not await _run_download_stage(
                db,
                job,
                account,
                workspace,
                rows,
                cached_posts,
                tasks,
                stages,
                "videos",
                "video_status",
                VIDEO_MEDIA_TYPES,
                download_timeout_sec,
                cookie_file,
                download_retry_attempts,
            ):
                return
            if not await _run_comments_stage(
                db,
                job,
                account,
                workspace,
                rows,
                tasks,
                stages,
                comments_limit,
            ):
                return

        if not await _run_zip_stage(db, job, workspace, tasks, stages):
            return

        _finalize_enrichment_items(rows)
        job.stage = "done"
        job.status = "DONE"
        job.current_item = None
        job.failure_reason = None
        job.error_code = None
        job.error_message = None
        job.finished_at = utcnow()
        await _refresh_job_counters(db, job)
        await _update_enrichment_progress(db, job, "done", None, stages, commit=False)
        await db.commit()


async def _set_profile_index_stage(
    db,
    job: Job,
    stage: str,
    current: int,
    total: int,
    current_item: str | None = None,
) -> None:
    job.status = "RUNNING"
    job.stage = stage
    job.progress_current = max(0, int(current or 0))
    job.progress_total = max(0, int(total or 0))
    job.current_item = current_item
    payload = dict(job.progress_payload or {})
    payload["stage_label"] = PROFILE_INDEX_STAGES.get(stage, stage)
    job.progress_payload = payload
    await db.commit()
    _safe_timing_log(
        "profile_index_stage job_id=%s target=%s stage=%s current=%s total=%s",
        job.id,
        job.username,
        stage,
        job.progress_current,
        job.progress_total,
    )


async def _fail_profile_index_job(db, job: Job, reason: str, message: str) -> None:
    safe_message = redact_diagnostic(message)
    job.status = "FAILED"
    job.stage = "failed"
    job.failure_reason = reason
    job.error_code = reason
    job.error_message = safe_message
    job.current_item = None
    job.finished_at = utcnow()
    payload = dict(job.progress_payload or {})
    payload["stage_label"] = PROFILE_INDEX_STAGES["failed"]
    job.progress_payload = payload
    await db.commit()


def _job_tasks(job: Job) -> dict[str, bool]:
    options = job.options if isinstance(job.options, dict) else {}
    tasks = options.get("tasks")
    if not isinstance(tasks, dict):
        include_media = bool(options.get("media", job.mode != "meta-only")) and job.mode != "meta-only"
        tasks = {
            "full_json": True,
            "images": include_media,
            "videos": include_media,
            "comments": bool(options.get("comments", False)),
            "zip": bool(options.get("zip", True)),
        }
    return {
        "full_json": bool(tasks.get("full_json", True)),
        "images": bool(tasks.get("images", False)),
        "videos": bool(tasks.get("videos", False)),
        "comments": bool(tasks.get("comments", False)),
        "zip": bool(tasks.get("zip", True)),
    }


def _initialize_enrichment_items(rows: list[JobItem], username: str, tasks: dict[str, bool]) -> None:
    for item in rows:
        media_type = _normalize_media_type(item.media_type)
        item.target = username
        item.status = "PENDING"
        item.started_at = item.started_at or utcnow()
        item.finished_at = None
        item.current_stage = None
        item.error_reason = None
        item.error_code = None
        item.error_message = None
        item.media_done = False
        item.metadata_done = False
        item.comments_done = False
        item.full_json_status = "queued" if tasks["full_json"] else "skipped"
        item.image_status = "queued" if tasks["images"] and media_type in IMAGE_MEDIA_TYPES else "skipped"
        item.video_status = "queued" if tasks["videos"] and media_type in VIDEO_MEDIA_TYPES else "skipped"
        item.comments_status = "queued" if tasks["comments"] else "skipped"


def _build_enrichment_stages(tasks: dict[str, bool], rows: list[JobItem]) -> dict[str, dict[str, Any]]:
    stages: dict[str, dict[str, Any]] = {}
    for stage in ENRICHMENT_STAGES:
        enabled = bool(tasks.get(stage, False))
        total = _stage_total(stage, enabled, rows)
        stages[stage] = {
            "enabled": enabled,
            "current": 0,
            "total": total,
            "status": "queued" if enabled else "skipped",
        }
    return stages


def _stage_total(stage: str, enabled: bool, rows: list[JobItem]) -> int:
    if not enabled:
        return 0
    if stage in {"full_json", "comments"}:
        return len(rows)
    if stage == "images":
        return sum(1 for item in rows if _normalize_media_type(item.media_type) in IMAGE_MEDIA_TYPES)
    if stage == "videos":
        return sum(1 for item in rows if _normalize_media_type(item.media_type) in VIDEO_MEDIA_TYPES)
    if stage == "zip":
        return 1
    return 0


def _refresh_media_stage_totals(stages: dict[str, dict[str, Any]], tasks: dict[str, bool], rows: list[JobItem]) -> None:
    for stage in ("images", "videos"):
        if not tasks.get(stage):
            continue
        stages[stage]["total"] = _stage_total(stage, True, rows)
        if stages[stage]["total"] == 0:
            stages[stage]["status"] = "done"


async def _update_enrichment_progress(
    db,
    job: Job,
    stage: str,
    current_item: str | None,
    stages: dict[str, dict[str, Any]],
    commit: bool = True,
) -> None:
    total = sum(max(0, int(payload.get("total") or 0)) for payload in stages.values())
    current = sum(max(0, int(payload.get("current") or 0)) for payload in stages.values())
    percent = int(round((current / total) * 100)) if total else 0
    job.stage = stage
    job.current_item = current_item
    job.progress_current = current
    job.progress_total = total
    job.progress_payload = {
        "tasks": _job_tasks(job),
        "overall": {"current": current, "total": total, "percent": percent},
        "stages": stages,
        "stage_label": ENRICHMENT_STAGE_LABELS.get(stage, stage),
    }
    if commit:
        await _refresh_job_counters(db, job)
        await db.commit()


async def _run_full_json_stage(
    db,
    job: Job,
    account: Account,
    workspace,
    rows: list[JobItem],
    cached_posts: dict[str, dict[str, Any]],
    tasks: dict[str, bool],
    stages: dict[str, dict[str, Any]],
) -> bool:
    if not tasks["full_json"]:
        return True
    stage = stages["full_json"]
    stage["status"] = "running"
    await _update_enrichment_progress(db, job, "full_json", None, stages)
    for item in rows:
        shortcode = _safe_shortcode(item.shortcode)
        item.status = "RUNNING"
        item.current_stage = "full_json"
        item.full_json_status = "running"
        _safe_timing_log("job_item_stage_start job_id=%s stage=full_json shortcode=%s", job.id, shortcode)
        started_at = monotonic()
        await _update_enrichment_progress(db, job, "full_json", shortcode, stages)
        try:
            metadata = await _fetch_post_metadata(account, job.username, shortcode)
            metadata = _complete_metadata(metadata, job.username, shortcode, item.media_type)
            item.media_type = metadata["type"]
            metadata_path = _write_item_metadata(workspace, job, item, metadata)
            item.metadata_done = True
            item.metadata_path = str(metadata_path)
            await _upsert_post_payload(db, job, shortcode, metadata)
            item.full_json_status = "done"
            _safe_timing_log(
                "job_item_stage_done job_id=%s stage=full_json shortcode=%s duration_ms=%.2f",
                job.id,
                shortcode,
                _duration_ms(started_at),
            )
        except ProviderError as exc:
            if _is_global_abort_error(exc.reason):
                await _abort_enrichment_job(db, job, item, exc, stages)
                return False
            _mark_item_stage_failed(item, "full_json_status", exc)
            _safe_timing_log(
                "job_item_stage_failed job_id=%s stage=full_json shortcode=%s error_code=%s duration_ms=%.2f",
                job.id,
                shortcode,
                exc.reason,
                _duration_ms(started_at),
            )
        except Exception as exc:
            _mark_item_stage_failed(
                item,
                "full_json_status",
                ProviderError("PROVIDER_ERROR", redact_diagnostic(str(exc))),
            )
        stage["current"] += 1
        await _update_enrichment_progress(db, job, "full_json", shortcode, stages)
    stage["status"] = "done"
    await _update_enrichment_progress(db, job, "full_json", None, stages)
    return True


async def _run_download_stage(
    db,
    job: Job,
    account: Account,
    workspace,
    rows: list[JobItem],
    cached_posts: dict[str, dict[str, Any]],
    tasks: dict[str, bool],
    stages: dict[str, dict[str, Any]],
    stage_name: str,
    status_attr: str,
    media_types: set[str],
    timeout_sec: int,
    cookie_file,
    retry_attempts: int,
) -> bool:
    if not tasks[stage_name]:
        return True
    stage = stages[stage_name]
    if stage["total"] <= 0:
        stage["status"] = "done"
        await _update_enrichment_progress(db, job, stage_name, None, stages)
        return True
    stage["status"] = "running"
    await _update_enrichment_progress(db, job, stage_name, None, stages)
    for item in rows:
        media_type = _normalize_media_type(item.media_type)
        if media_type not in media_types:
            setattr(item, status_attr, "skipped")
            continue
        shortcode = _safe_shortcode(item.shortcode)
        item.status = "RUNNING"
        item.current_stage = stage_name
        setattr(item, status_attr, "running")
        _safe_timing_log(
            "job_item_stage_start job_id=%s stage=%s shortcode=%s media_type=%s",
            job.id,
            stage_name,
            shortcode,
            media_type,
        )
        started_at = monotonic()
        await _update_enrichment_progress(db, job, stage_name, shortcode, stages)
        try:
            metadata = await _metadata_for_item(db, job, account, item, workspace, cached_posts)
            downloader = downloader_for_media_type(media_type)
            if downloader is None:
                raise ProviderError("MEDIA_TYPE_UNKNOWN", f"Нет downloader для типа публикации {media_type}")
            _safe_timing_log(
                "downloader_start job_id=%s downloader_name=%s shortcode=%s media_type=%s",
                job.id,
                downloader.name,
                shortcode,
                media_type,
            )
            result, attempts = await _download_with_retry(
                downloader,
                shortcode,
                workspace / "posts" / shortcode / "media",
                workspace,
                timeout_sec,
                cookie_file,
                retry_attempts,
            )
            metadata.update(
                {
                    "downloader": downloader.name,
                    "download_attempts": attempts,
                    "media_files": result.media_files,
                    "sidecar_files": result.sidecar_files,
                    "downloader_metadata_file": result.metadata_file,
                    "error_code": None,
                    "error_message": None,
                }
            )
            if not result.ok:
                code = result.error_code or "DOWNLOAD_FAILED"
                message = result.error_message or f"{downloader.name} failed"
                metadata["error_code"] = code
                metadata["error_message"] = redact_diagnostic(message)
                _write_item_metadata(workspace, job, item, metadata)
                _safe_timing_log(
                    "downloader_failed job_id=%s downloader_name=%s shortcode=%s media_type=%s duration_ms=%.2f attempts=%s error_code=%s",
                    job.id,
                    downloader.name,
                    shortcode,
                    media_type,
                    _duration_ms(started_at),
                    attempts,
                    code,
                )
                raise ProviderError(code, message)
            _write_item_metadata(workspace, job, item, metadata)
            await _upsert_post_payload(db, job, shortcode, metadata)
            setattr(item, status_attr, "done")
            item.media_done = True
            _safe_timing_log(
                "downloader_done job_id=%s downloader_name=%s shortcode=%s media_type=%s duration_ms=%.2f attempts=%s",
                job.id,
                downloader.name,
                shortcode,
                media_type,
                _duration_ms(started_at),
                attempts,
            )
        except ProviderError as exc:
            if _is_global_abort_error(exc.reason):
                await _abort_enrichment_job(db, job, item, exc, stages)
                return False
            _mark_item_stage_failed(item, status_attr, exc)
        except Exception as exc:
            _mark_item_stage_failed(item, status_attr, ProviderError("DOWNLOAD_ERROR", redact_diagnostic(str(exc))))
        stage["current"] += 1
        await _update_enrichment_progress(db, job, stage_name, shortcode, stages)
    stage["status"] = "done"
    await _update_enrichment_progress(db, job, stage_name, None, stages)
    return True


async def _run_comments_stage(
    db,
    job: Job,
    account: Account,
    workspace,
    rows: list[JobItem],
    tasks: dict[str, bool],
    stages: dict[str, dict[str, Any]],
    comments_limit: int,
) -> bool:
    if not tasks["comments"]:
        return True
    stage = stages["comments"]
    stage["status"] = "running"
    await _update_enrichment_progress(db, job, "comments", None, stages)
    for item in rows:
        shortcode = _safe_shortcode(item.shortcode)
        item.status = "RUNNING"
        item.current_stage = "comments"
        item.comments_status = "running"
        started_at = monotonic()
        _safe_timing_log("job_item_stage_start job_id=%s stage=comments shortcode=%s", job.id, shortcode)
        await _update_enrichment_progress(db, job, "comments", shortcode, stages)
        try:
            comments = await _fetch_post_comments(account, shortcode, comments_limit)
            post_dir = workspace / "posts" / shortcode
            post_dir.mkdir(parents=True, exist_ok=True)
            write_json(post_dir / "comments.json", comments, workspace)
            for comment in comments:
                db.add(Comment(post_shortcode=shortcode, job_id=job.id, payload=comment))
            item.comments_done = True
            item.comments_status = "done"
            _safe_timing_log(
                "job_item_stage_done job_id=%s stage=comments shortcode=%s duration_ms=%.2f",
                job.id,
                shortcode,
                _duration_ms(started_at),
            )
        except ProviderError as exc:
            if _is_global_abort_error(exc.reason):
                await _abort_enrichment_job(db, job, item, exc, stages)
                return False
            _mark_item_stage_failed(item, "comments_status", exc)
        except Exception as exc:
            _mark_item_stage_failed(item, "comments_status", ProviderError("PROVIDER_ERROR", redact_diagnostic(str(exc))))
        stage["current"] += 1
        await _update_enrichment_progress(db, job, "comments", shortcode, stages)
    stage["status"] = "done"
    await _update_enrichment_progress(db, job, "comments", None, stages)
    return True


async def _run_zip_stage(
    db,
    job: Job,
    workspace,
    tasks: dict[str, bool],
    stages: dict[str, dict[str, Any]],
) -> bool:
    if not tasks["zip"]:
        return True
    stage = stages["zip"]
    stage["status"] = "running"
    await _update_enrichment_progress(db, job, "zip", None, stages)
    started_at = monotonic()
    try:
        zip_path = build_zip(workspace, job.id)
        job.archive_path = str(zip_path)
        stage["current"] = 1
        stage["status"] = "done"
        _safe_timing_log("job_item_stage_done job_id=%s stage=zip duration_ms=%.2f", job.id, _duration_ms(started_at))
        await _update_enrichment_progress(db, job, "zip", None, stages)
        return True
    except Exception as exc:
        await _fail_job(db, job, "ARCHIVE_ERROR", redact_diagnostic(str(exc)), stage="failed")
        return False


async def _metadata_for_item(
    db,
    job: Job,
    account: Account,
    item: JobItem,
    workspace,
    cached_posts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    shortcode = _safe_shortcode(item.shortcode)
    existing = (
        await db.execute(select(Post).where(Post.job_id == job.id, Post.shortcode == shortcode).limit(1))
    ).scalar_one_or_none()
    if existing is not None and isinstance(existing.payload, dict):
        metadata = dict(existing.payload)
    else:
        metadata = _metadata_from_cached_post(cached_posts.get(shortcode), job.username, shortcode)
        if not metadata or _normalize_media_type(item.media_type or metadata.get("type")) == "unknown":
            metadata = await _fetch_post_metadata(account, job.username, shortcode)
    metadata = _complete_metadata(metadata, job.username, shortcode, item.media_type)
    item.media_type = metadata["type"]
    _write_item_metadata(workspace, job, item, metadata)
    return metadata


def _complete_metadata(
    metadata: dict[str, Any],
    username: str,
    shortcode: str,
    item_media_type: str | None,
) -> dict[str, Any]:
    media_type = _normalize_media_type(item_media_type or metadata.get("type"), metadata.get("is_video"))
    if media_type == "unknown":
        media_type = _normalize_media_type(metadata.get("type"), metadata.get("is_video"))
    payload = dict(metadata)
    payload.update(
        {
            "username": username,
            "shortcode": shortcode,
            "type": media_type,
            "media_files": payload.get("media_files") or [],
            "sidecar_files": payload.get("sidecar_files") or [],
            "downloader_metadata_file": payload.get("downloader_metadata_file"),
            "downloader": payload.get("downloader"),
            "download_attempts": int(payload.get("download_attempts") or 0),
            "error_code": payload.get("error_code"),
            "error_message": payload.get("error_message"),
        }
    )
    payload.setdefault("url", f"https://www.instagram.com/p/{shortcode}/")
    return payload


def _write_item_metadata(workspace, job: Job, item: JobItem, metadata: dict[str, Any]):
    shortcode = _safe_shortcode(item.shortcode)
    post_dir = workspace / "posts" / shortcode
    post_dir.mkdir(parents=True, exist_ok=True)
    metadata_path = post_dir / "metadata.json"
    write_json(metadata_path, metadata, workspace)
    item.result_path = str(post_dir)
    item.metadata_path = str(metadata_path)
    return metadata_path


async def _upsert_post_payload(db, job: Job, shortcode: str, metadata: dict[str, Any]) -> None:
    existing = (
        await db.execute(select(Post).where(Post.job_id == job.id, Post.shortcode == shortcode).limit(1))
    ).scalar_one_or_none()
    if existing is None:
        db.add(Post(username=job.username, job_id=job.id, shortcode=shortcode, payload=metadata))
    else:
        existing.payload = metadata


def _mark_item_stage_failed(item: JobItem, status_attr: str, exc: ProviderError) -> None:
    safe_message = redact_diagnostic(exc.message)
    setattr(item, status_attr, "failed")
    item.error_reason = exc.reason
    item.error_code = exc.reason
    item.error_message = safe_message


def _is_global_abort_error(reason: str | None) -> bool:
    return (reason or "") in GLOBAL_ABORT_ERRORS


async def _abort_enrichment_job(
    db,
    job: Job,
    item: JobItem,
    exc: ProviderError,
    stages: dict[str, dict[str, Any]],
) -> None:
    safe_message = redact_diagnostic(exc.message)
    item.status = "FAILED"
    item.error_reason = exc.reason
    item.error_code = exc.reason
    item.error_message = safe_message
    item.finished_at = utcnow()
    if item.current_stage:
        attr = {
            "full_json": "full_json_status",
            "images": "image_status",
            "videos": "video_status",
            "comments": "comments_status",
        }.get(item.current_stage)
        if attr:
            setattr(item, attr, "failed")
    if exc.reason == "RATE_LIMIT":
        settings = await get_settings_map(db)
        job.status = "WAITING"
        job.stage = "waiting"
        job.retry_after_at = utcnow() + timedelta(seconds=int(settings.get("rate_limit_wait_sec", 3600)))
    else:
        job.status = "FAILED"
        job.stage = "failed"
        job.finished_at = utcnow()
    job.failure_reason = exc.reason
    job.error_code = exc.reason
    job.error_message = safe_message
    for payload in stages.values():
        if payload.get("status") == "running":
            payload["status"] = "failed" if exc.reason != "RATE_LIMIT" else "waiting"
    await _refresh_job_counters(db, job)
    await _update_enrichment_progress(db, job, job.stage or "failed", item.shortcode, stages, commit=False)
    await db.commit()


def _finalize_enrichment_items(rows: list[JobItem]) -> None:
    for item in rows:
        statuses = [item.full_json_status, item.image_status, item.video_status, item.comments_status]
        if any(status == "failed" for status in statuses):
            item.status = "FAILED"
        else:
            item.status = "DONE"
        item.metadata_done = item.full_json_status == "done" or bool(item.metadata_path)
        item.media_done = item.image_status == "done" or item.video_status == "done"
        item.comments_done = item.comments_status == "done"
        item.current_stage = None
        item.finished_at = utcnow()


async def _downloader_cookies(account: Account) -> dict[str, str]:
    getter = getattr(instagram_provider, "downloader_cookies", None)
    if not callable(getter):
        return {}
    cookies = await getter(account)
    return cookies if isinstance(cookies, dict) else {}


async def _download_with_retry(
    downloader,
    shortcode: str,
    output_dir,
    workspace,
    timeout_sec: int,
    cookie_file,
    max_attempts: int,
) -> tuple[DownloadResult, int]:
    attempts = max(1, max_attempts)
    last_result = DownloadResult(ok=False, error_code="DOWNLOAD_FAILED", error_message="Download did not run")
    for attempt in range(1, attempts + 1):
        result = await downloader.download(shortcode, output_dir, workspace, timeout_sec, cookie_file)
        last_result = result
        if result.ok:
            return result, attempt
        if result.error_code not in RETRYABLE_DOWNLOAD_ERRORS:
            return result, attempt
    return last_result, attempts


async def _post_metadata_and_comments(
    account: Account,
    username: str,
    shortcode: str,
    item_media_type: str | None,
    cached_posts: dict[str, dict[str, Any]],
    include_comments: bool,
    comments_limit: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    metadata = _metadata_from_cached_post(cached_posts.get(shortcode), username, shortcode)
    media_type = _normalize_media_type(item_media_type or metadata.get("type"), metadata.get("is_video"))
    if not metadata or media_type == "unknown":
        metadata = await _fetch_post_metadata(account, username, shortcode)
        media_type = _normalize_media_type(item_media_type or metadata.get("type"), metadata.get("is_video"))
    metadata["type"] = media_type

    comments: list[dict[str, Any]] = []
    if include_comments:
        comments = await _fetch_post_comments(account, shortcode, comments_limit)
    return metadata, comments


async def _fetch_post_metadata(account: Account, username: str, shortcode: str) -> dict[str, Any]:
    fetcher = getattr(instagram_provider, "post_metadata", None)
    if not callable(fetcher):
        raise ProviderError("PROVIDER_ERROR", "Active Instagram provider cannot fetch post metadata")
    metadata = await fetcher(account, username, shortcode)
    if not isinstance(metadata, dict):
        raise ProviderError("PROVIDER_ERROR", "Instagram provider returned invalid post metadata")
    metadata.pop("_session_update", None)
    metadata.setdefault("shortcode", shortcode)
    metadata.setdefault("username", username)
    return metadata


async def _fetch_post_comments(account: Account, shortcode: str, comments_limit: int) -> list[dict[str, Any]]:
    fetcher = getattr(instagram_provider, "post_comments", None)
    if not callable(fetcher):
        raise ProviderError("PROVIDER_ERROR", "Active Instagram provider cannot fetch post comments")
    comments = await fetcher(account, shortcode, comments_limit)
    return comments if isinstance(comments, list) else []


def _cached_posts_by_shortcode(cache: ProfileCache | None) -> dict[str, dict[str, Any]]:
    if cache is None or not isinstance(cache.payload, dict):
        return {}
    posts = cache.payload.get("posts")
    if not isinstance(posts, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for post in posts:
        if not isinstance(post, dict) or not post.get("shortcode"):
            continue
        metadata = _metadata_from_cached_post(post, cache.username, post["shortcode"])
        result[post["shortcode"]] = metadata
    return result


def _metadata_from_cached_post(post: dict[str, Any] | None, username: str, shortcode: str) -> dict[str, Any]:
    if not isinstance(post, dict):
        return {}
    media_type = _normalize_media_type(post.get("type"), post.get("is_video"))
    return {
        "username": username,
        "shortcode": shortcode,
        "id": str(post.get("id") or post.get("mediaid") or shortcode),
        "type": media_type,
        "date": post.get("date") or None,
        "caption": post.get("caption") or None,
        "likes": _optional_int(post.get("likes")),
        "comments": _optional_int(post.get("comments")),
        "preview_url": post.get("preview_url") or post.get("url") or None,
        "location": post.get("location") or None,
        "carousel_count": _optional_int(post.get("carousel_count")),
        "is_video": bool(post.get("is_video") or media_type == "video"),
        "url": f"https://www.instagram.com/p/{shortcode}/",
    }


def _normalize_media_type(value: object, is_video: object = False) -> str:
    text = str(value or "").strip().lower()
    if text in {"image", "photo"}:
        return "photo"
    if text in {"sidecar", "carousel"}:
        return "carousel"
    if text in {"video", "reel", "clips"}:
        return "video"
    if bool(is_video):
        return "video"
    return "unknown"


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_shortcode(value: object) -> str:
    try:
        return normalize_instagram_shortcode(value)
    except ValueError as exc:
        raise ProviderError("VALIDATION_ERROR", "Некорректный shortcode Instagram") from exc


async def resume_scheduler() -> None:
    """Периодически возобновляет WAITING-задачи после retry_after_at."""
    while True:
        async with session_context() as db:
            settings = await get_settings_map(db)
            interval = int(settings.get("scheduler_interval_sec", 60))
            now = utcnow()
            waiting = (
                await db.execute(
                    select(Job).where(
                        Job.status.in_(WAITING_STATUSES),
                        Job.retry_after_at.is_not(None),
                        Job.retry_after_at <= now,
                    )
                )
            ).scalars().all()
            for job in waiting:
                job.status = "PENDING"
                job.retry_after_at = None
                schedule_job(job.id)
            await db.commit()
        await asyncio.sleep(max(5, interval))


async def _handle_provider_error(db, job: Job, item: JobItem, exc: ProviderError, settings: dict) -> None:
    safe_message = redact_diagnostic(exc.message)
    item.status = "FAILED"
    item.error_reason = exc.reason
    item.error_code = exc.reason
    item.error_message = safe_message
    item.finished_at = utcnow()
    if exc.reason == "RATE_LIMIT":
        job.status = "WAITING"
        job.retry_after_at = utcnow() + timedelta(seconds=int(settings.get("rate_limit_wait_sec", 3600)))
    else:
        job.status = "FAILED"
    job.finished_at = utcnow()
    job.failure_reason = exc.reason
    job.error_code = exc.reason
    job.error_message = safe_message
    await _refresh_job_counters(db, job)
    await db.commit()


async def _fail_job(db, job: Job, reason: str, message: str, stage: str | None = None) -> None:
    safe_message = redact_diagnostic(message)
    job.status = "FAILED"
    if stage is not None:
        job.stage = stage
    job.failure_reason = reason
    job.error_code = reason
    job.error_message = safe_message
    job.finished_at = utcnow()
    await _refresh_job_counters(db, job)
    await db.commit()


def can_resume(job: Job) -> bool:
    """Проверяет, можно ли вручную возобновить задачу."""
    return job.status in WAITING_STATUSES | FAILED_STATUSES and job.failure_reason in RESUMABLE_FAILURES


async def _refresh_job_counters(db, job: Job) -> None:
    """Синхронизирует counters job с фактическими статусами job_items."""
    done_count = (
        await db.execute(
            select(func.count(JobItem.id)).where(JobItem.job_id == job.id, JobItem.status.in_(DONE_STATUSES))
        )
    ).scalar_one()
    failed_count = (
        await db.execute(
            select(func.count(JobItem.id)).where(JobItem.job_id == job.id, JobItem.status.in_(FAILED_STATUSES))
        )
    ).scalar_one()
    job.items_done = int(done_count)
    job.completed_items = int(done_count)
    job.failed_items = int(failed_count)
