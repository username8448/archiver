"""Фоновый менеджер задач архивации."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select

from archive import build_zip, workspace_for_job, write_json
from config import RESUMABLE_FAILURES
from database import session_context
from downloaders.common import DownloadResult
from downloaders.cookies import downloader_cookie_file
from downloaders.providers import downloader_for_media_type
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
_scheduled: set[str] = set()


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
    """Обрабатывает PENDING job_items и собирает ZIP."""
    async with session_context() as db:
        job = await db.get(Job, job_id)
        if job is None or job.status in DONE_STATUSES | CANCELLED_STATUSES:
            return
        account = await db.get(Account, job.account_id) if job.account_id else None
        if account is None:
            await _fail_job(db, job, "LOGIN_REQUIRED", "Не выбран аккаунт Instagram")
            return

        settings = await get_settings_map(db)
        workspace = workspace_for_job(settings.get("archive_dir"), job.id)
        job.status = "RUNNING"
        job.result_dir = str(workspace)
        if job.started_at is None:
            job.started_at = utcnow()
        job.finished_at = None
        job.failure_reason = None
        job.error_code = None
        job.error_message = None
        job.retry_after_at = None
        await db.commit()

        cache = await db.get(ProfileCache, job.username)
        cached_posts = _cached_posts_by_shortcode(cache)
        if cache:
            write_json(workspace / "profile.json", cache.payload)
        write_json(
            workspace / "README.txt",
            {
                "job_id": job.id,
                "username": job.username,
                "created_at": job.created_at.isoformat(),
                "note": "Архив создан локально Instagram Archiver.",
            },
        )

        rows = (
            await db.execute(
                select(JobItem)
                .where(JobItem.job_id == job.id, ~JobItem.status.in_(DONE_STATUSES))
                .order_by(JobItem.id.asc())
            )
        ).scalars().all()

        include_media = bool(job.options.get("media", True)) and job.mode != "meta-only"
        include_comments = bool(job.options.get("comments", False))
        comments_limit = int(settings.get("comments_limit", 500))
        download_timeout_sec = int(settings.get("download_timeout_sec", 300))
        download_retry_attempts = max(1, int(settings.get("download_retry_attempts", 2)))

        with ExitStack() as stack:
            cookie_file = None
            if include_media:
                try:
                    cookies = await _downloader_cookies(account)
                    cookie_file = stack.enter_context(downloader_cookie_file(cookies))
                except ProviderError as exc:
                    await _fail_job(db, job, exc.reason, exc.message)
                    return
                except Exception as exc:
                    await _fail_job(db, job, "DOWNLOAD_ERROR", str(exc))
                    return

            for item in rows:
                item.status = "RUNNING"
                item.target = job.username
                item.started_at = utcnow()
                item.finished_at = None
                item.error_reason = None
                item.error_code = None
                item.error_message = None
                item.media_done = False
                item.metadata_done = False
                item.comments_done = False
                await _refresh_job_counters(db, job)
                await db.commit()
                try:
                    post_dir = workspace / "posts" / item.shortcode
                    post_dir.mkdir(parents=True, exist_ok=True)
                    item.result_path = str(post_dir)
                    metadata, comments = await _post_metadata_and_comments(
                        account,
                        job.username,
                        item.shortcode,
                        item.media_type,
                        cached_posts,
                        include_comments,
                        comments_limit,
                    )
                    media_type = _normalize_media_type(item.media_type or metadata.get("type"), metadata.get("is_video"))
                    if media_type == "unknown":
                        media_type = _normalize_media_type(metadata.get("type"), metadata.get("is_video"))
                    if include_media and media_type == "unknown":
                        raise ProviderError("MEDIA_TYPE_UNKNOWN", "Не удалось определить тип публикации для скачивания")

                    item.media_type = media_type
                    metadata.update(
                        {
                            "username": job.username,
                            "shortcode": item.shortcode,
                            "type": media_type,
                            "media_files": [],
                            "sidecar_files": [],
                            "downloader_metadata_file": None,
                            "downloader": None,
                            "download_attempts": 0,
                            "error_code": None,
                            "error_message": None,
                        }
                    )
                    metadata_path = post_dir / "metadata.json"
                    write_json(metadata_path, metadata)
                    item.metadata_done = True
                    item.metadata_path = str(metadata_path)
                    if include_comments:
                        write_json(post_dir / "comments.json", comments)
                        item.comments_done = True
                    await db.commit()

                    if include_media:
                        downloader = downloader_for_media_type(media_type)
                        if downloader is None:
                            raise ProviderError(
                                "MEDIA_TYPE_UNKNOWN",
                                f"Нет downloader для типа публикации {media_type}",
                            )
                        metadata["downloader"] = downloader.name
                        result, attempts = await _download_with_retry(
                            downloader,
                            item.shortcode,
                            post_dir / "media",
                            workspace,
                            download_timeout_sec,
                            cookie_file,
                            download_retry_attempts,
                        )
                        metadata["download_attempts"] = attempts
                        metadata["media_files"] = result.media_files
                        metadata["sidecar_files"] = result.sidecar_files
                        metadata["downloader_metadata_file"] = result.metadata_file
                        if not result.ok:
                            metadata["error_code"] = result.error_code or "DOWNLOAD_FAILED"
                            metadata["error_message"] = result.error_message or f"{downloader.name} failed"
                            write_json(metadata_path, metadata)
                            raise ProviderError(
                                result.error_code or "DOWNLOAD_FAILED",
                                result.error_message or f"{downloader.name} failed",
                            )
                        write_json(metadata_path, metadata)

                    db.add(Post(username=job.username, job_id=job.id, shortcode=item.shortcode, payload=metadata))
                    for comment in comments:
                        db.add(Comment(post_shortcode=item.shortcode, job_id=job.id, payload=comment))

                    item.media_done = bool(include_media)
                    item.comments_done = include_comments
                    item.status = "DONE"
                    item.error_reason = None
                    item.error_code = None
                    item.error_message = None
                    item.result_path = str(post_dir)
                    item.metadata_path = str(metadata_path)
                    item.finished_at = utcnow()
                    job.items_done += 1
                    await _refresh_job_counters(db, job)
                    await db.commit()
                except ProviderError as exc:
                    await _handle_provider_error(db, job, item, exc, settings)
                    return
                except Exception as exc:
                    await _handle_provider_error(
                        db,
                        job,
                        item,
                        ProviderError("DOWNLOAD_ERROR", str(exc)),
                        settings,
                    )
                    return

        try:
            zip_path = build_zip(workspace, job.id)
            job.archive_path = str(zip_path)
            job.status = "DONE"
            job.failure_reason = None
            job.error_code = None
            job.error_message = None
            job.finished_at = utcnow()
            await _refresh_job_counters(db, job)
            await db.commit()
        except Exception as exc:
            await _fail_job(db, job, "ARCHIVE_ERROR", str(exc))


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
    item.status = "FAILED"
    item.error_reason = exc.reason
    item.error_code = exc.reason
    item.error_message = exc.message
    item.finished_at = utcnow()
    if exc.reason == "RATE_LIMIT":
        job.status = "WAITING"
        job.retry_after_at = utcnow() + timedelta(seconds=int(settings.get("rate_limit_wait_sec", 3600)))
    else:
        job.status = "FAILED"
        job.finished_at = utcnow()
    job.failure_reason = exc.reason
    job.error_code = exc.reason
    job.error_message = exc.message
    await _refresh_job_counters(db, job)
    await db.commit()


async def _fail_job(db, job: Job, reason: str, message: str) -> None:
    job.status = "FAILED"
    job.failure_reason = reason
    job.error_code = reason
    job.error_message = message
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
