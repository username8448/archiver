"""Фоновый менеджер задач архивации."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select

from archive import build_zip, workspace_for_job, write_json
from config import RESUMABLE_FAILURES
from database import session_context
from models import Account, Comment, Job, JobItem, Post, ProfileCache, utcnow
from providers.base import ProviderError
from scraper import instagram_provider
from settings_service import get_settings_map

ACTIVE_STATUSES = {"PENDING", "RUNNING", "WAITING"}
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
        if job is None or job.status in {"DONE", "CANCELLED"}:
            return
        account = await db.get(Account, job.account_id) if job.account_id else None
        if account is None:
            await _fail_job(db, job, "LOGIN_REQUIRED", "Не выбран аккаунт Instagram")
            return

        settings = await get_settings_map(db)
        workspace = workspace_for_job(settings.get("archive_dir"), job.id)
        job.status = "RUNNING"
        job.failure_reason = None
        job.error_message = None
        job.retry_after_at = None
        await db.commit()

        cache = await db.get(ProfileCache, job.username)
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
                .where(JobItem.job_id == job.id, JobItem.status != "DONE")
                .order_by(JobItem.id.asc())
            )
        ).scalars().all()

        include_media = bool(job.options.get("media", True)) and job.mode != "meta-only"
        include_comments = bool(job.options.get("comments", False))
        comments_limit = int(settings.get("comments_limit", 500))

        for item in rows:
            item.status = "RUNNING"
            await db.commit()
            try:
                post_dir = workspace / "posts" / item.shortcode
                metadata, comments = await instagram_provider.download_post(
                    account,
                    job.username,
                    item.shortcode,
                    post_dir,
                    include_media=include_media,
                    include_comments=include_comments,
                    comments_limit=comments_limit,
                )
                write_json(post_dir / "metadata.json", metadata)
                if include_comments:
                    write_json(post_dir / "comments.json", comments)

                db.add(Post(username=job.username, job_id=job.id, shortcode=item.shortcode, payload=metadata))
                for comment in comments:
                    db.add(Comment(post_shortcode=item.shortcode, job_id=job.id, payload=comment))

                item.metadata_done = True
                item.media_done = include_media
                item.comments_done = include_comments
                item.status = "DONE"
                item.error_reason = None
                job.items_done += 1
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
            job.error_message = None
            await db.commit()
        except Exception as exc:
            await _fail_job(db, job, "ARCHIVE_ERROR", str(exc))


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
                        Job.status == "WAITING",
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
    if exc.reason == "RATE_LIMIT":
        job.status = "WAITING"
        job.retry_after_at = utcnow() + timedelta(seconds=int(settings.get("rate_limit_wait_sec", 3600)))
    else:
        job.status = "FAILED"
    job.failure_reason = exc.reason
    job.error_message = exc.message
    await db.commit()


async def _fail_job(db, job: Job, reason: str, message: str) -> None:
    job.status = "FAILED"
    job.failure_reason = reason
    job.error_message = message
    await db.commit()


def can_resume(job: Job) -> bool:
    """Проверяет, можно ли вручную возобновить задачу."""
    return job.status in {"WAITING", "FAILED"} and job.failure_reason in RESUMABLE_FAILURES
