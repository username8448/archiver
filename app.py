"""FastAPI-приложение Instagram Archiver v4."""

from __future__ import annotations

import asyncio
import logging
import os
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from time import monotonic

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import delete, func, select, text

from bootstrap import is_configured
from config import (
    APP_VERSION,
    COOKIE_SECURE,
    DEFAULT_SETTINGS,
    MASTER_KEY_FILE,
    MAX_UPLOAD_BYTES,
    PROJECT_ROOT,
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    STATIC_DIR,
    VAULT_DIR,
    ensure_state_dirs,
)
from database import close_engine, get_session, init_engine
from jobs import can_resume, find_active_job, resume_scheduler, schedule_job
from models import Account, AdminSession, AdminUser, Job, JobItem, ProfileCache, utcnow
from providers.base import ProviderError
from schemas import (
    AccountResponse,
    HealthResponse,
    JobCreateRequest,
    JobStatusResponse,
    LoginRequest,
    ProfilePreviewRequest,
    ProfilePreviewResponse,
    RegisterRequest,
    SettingsUpdateRequest,
    SetupInitializeRequest,
    SetupStatusResponse,
)
from scraper import instagram_provider
from security import hash_password, new_session_token, session_expires, token_hash, verify_password
from settings_service import get_settings_map, seed_default_settings, update_settings_map
from vault import delete_secret, ensure_master_key, save_secret

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("instagram_archiver")

app = FastAPI(title="Instagram Archiver", version="1.0.0")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_scheduler_task: asyncio.Task | None = None
_auth_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
AUTH_RATE_LIMIT_WINDOW_SEC = 60
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 8


@app.on_event("startup")
async def startup() -> None:
    """Готовит скрытые каталоги, Postgres schema, defaults и scheduler."""
    global _scheduler_task
    ensure_state_dirs()
    if is_configured():
        await initialize_database_with_retry()


@app.on_event("shutdown")
async def shutdown() -> None:
    """Аккуратно закрывает фоновые ресурсы."""
    global _scheduler_task
    if _scheduler_task:
        _scheduler_task.cancel()
    await close_engine()


@app.get("/")
async def index() -> RedirectResponse:
    """Перенаправляет на static UI, чтобы относительные CSS/JS работали корректно."""
    return RedirectResponse(url="/static/index.html")


@app.get("/api/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    """Публичный healthcheck без раскрытия секретов."""
    vault_ready = VAULT_DIR.exists() and MASTER_KEY_FILE.exists()
    if not is_configured():
        return HealthResponse(
            status="not_configured",
            database_connected=False,
            vault_ready=vault_ready,
            version=APP_VERSION,
            admins_initialized=False,
            error="DATABASE_URL is not configured. Use docker compose or set DATABASE_URL.",
        )
    try:
        engine = await init_engine()
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        admin_count = 0
        async for db in get_session():
            admin_count = (await db.execute(select(func.count(AdminUser.id)))).scalar_one()
            break
        return HealthResponse(
            status="ok" if vault_ready else "degraded",
            database_connected=True,
            vault_ready=vault_ready,
            version=APP_VERSION,
            admins_initialized=admin_count > 0,
        )
    except Exception as exc:
        return HealthResponse(
            status="degraded",
            database_connected=False,
            vault_ready=vault_ready,
            version=APP_VERSION,
            admins_initialized=False,
            error=str(exc),
        )


@app.get("/api/setup/status", response_model=SetupStatusResponse)
async def setup_status() -> SetupStatusResponse:
    """Проверяет, пройден ли первый запуск и доступен ли Postgres."""
    if not is_configured():
        return SetupStatusResponse(
            configured=False,
            error="DATABASE_URL не настроен. Запустите через docker compose или задайте DATABASE_URL вручную.",
        )
    try:
        engine = await init_engine()
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        admin_count = 0
        async for db in get_session():
            admin_count = (await db.execute(select(func.count(AdminUser.id)))).scalar_one()
            break
        return SetupStatusResponse(configured=True, database_connected=True, needs_login=admin_count > 0)
    except Exception as exc:
        return SetupStatusResponse(configured=True, database_connected=False, error=str(exc))


@app.post("/api/setup/initialize")
async def setup_initialize(
    payload: SetupInitializeRequest,
    request: Request,
    response: Response,
    db=Depends(get_session),
):
    """Совместимый endpoint: инициализирует нового локального admin."""
    return await _register_admin(
        RegisterRequest(username=payload.admin_username, password=payload.admin_password),
        request,
        response,
        db,
    )


@app.post("/api/auth/register")
async def register(payload: RegisterRequest, request: Request, response: Response, db=Depends(get_session)):
    """Создаёт нового локального администратора и сразу авторизует его."""
    return await _register_admin(payload, request, response, db)


async def _register_admin(payload: RegisterRequest, request: Request, response: Response, db):
    """Общая реализация регистрации local admin."""
    _check_auth_rate_limit(request, "register")
    username = payload.username.strip()
    if len(username) < 3:
        raise HTTPException(status_code=422, detail="Username должен быть не короче 3 символов")
    existing = (await db.execute(select(AdminUser).where(AdminUser.username == username))).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Администратор с таким username уже существует")
    user = AdminUser(username=username, password_hash=hash_password(payload.password))
    db.add(user)
    await db.flush()
    await create_admin_session(db, user, response)
    await db.commit()
    return {"ok": True, "username": user.username}


@app.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response, db=Depends(get_session)):
    """Создаёт admin-сессию."""
    _check_auth_rate_limit(request, "login")
    user = (await db.execute(select(AdminUser).where(AdminUser.username == payload.username))).scalar_one_or_none()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный username или пароль")
    await create_admin_session(db, user, response)
    await db.commit()
    return {"ok": True}


@app.post("/api/auth/logout")
async def logout(request: Request, response: Response, db=Depends(get_session)):
    """Удаляет текущую admin-сессию."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        await db.execute(delete(AdminSession).where(AdminSession.token_hash == token_hash(token)))
        await db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, secure=COOKIE_SECURE, samesite="lax")
    return {"ok": True}


async def current_admin(request: Request, db=Depends(get_session)) -> AdminUser:
    """FastAPI dependency: требует активную admin cookie-сессию."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Нужен вход администратора")
    session = (
        await db.execute(
            select(AdminSession).where(
                AdminSession.token_hash == token_hash(token),
                AdminSession.expires_at > utcnow(),
            )
        )
    ).scalar_one_or_none()
    if session is None:
        raise HTTPException(status_code=401, detail="Нужен вход администратора")
    user = await db.get(AdminUser, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Нужен вход администратора")
    return user


@app.get("/api/auth/me")
async def auth_me(user: AdminUser = Depends(current_admin)):
    """Возвращает текущего admin-пользователя."""
    return {"username": user.username}


@app.get("/api/settings")
async def get_settings(user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Возвращает runtime-настройки из Postgres."""
    return {"settings": await get_settings_map(db)}


@app.put("/api/settings")
async def put_settings(
    payload: SettingsUpdateRequest,
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Обновляет runtime-настройки через UI/API."""
    return {"settings": await update_settings_map(db, payload.settings)}


@app.get("/api/accounts", response_model=list[AccountResponse])
async def list_accounts(user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Возвращает аккаунты без secret_id и путей к vault."""
    rows = (await db.execute(select(Account).order_by(Account.created_at.asc()))).scalars().all()
    return [AccountResponse.model_validate(row, from_attributes=True) for row in rows]


@app.post("/api/accounts", response_model=AccountResponse)
async def create_account(
    username: str | None = Form(None),
    secret_kind: str = Form("session"),
    secret_value: str | None = Form(None),
    secret_file: UploadFile | None = File(None),
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Загружает session/cookies, шифрует и сохраняет только metadata в Postgres."""
    has_secret_value = bool(secret_value and secret_value.strip())
    if has_secret_value and secret_kind == "session":
        secret_kind = "sessionid"
    if secret_kind == "sessionid":
        secret_kind = "cookies"
    if secret_kind not in {"session", "cookies"}:
        raise HTTPException(status_code=400, detail="secret_kind must be session, sessionid or cookies")

    if has_secret_value:
        raw = secret_value.strip().encode("utf-8")
    elif secret_file is not None:
        raw = await secret_file.read()
    else:
        raise HTTPException(status_code=400, detail="Secret file or sessionid string is required")

    if not raw:
        raise HTTPException(status_code=400, detail="Secret value is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Secret file is too large")

    normalized_username: str | None = None
    username_input = (username or "").strip()
    if username_input:
        try:
            normalized_username = instagram_provider.normalize_target(username_input)
        except ProviderError as exc:
            _raise_provider_http(exc)

    inferred_username: str | None = None
    try:
        inferred_username = await instagram_provider.infer_account_username(secret_kind, raw, normalized_username)
    except ProviderError as exc:
        if normalized_username is None:
            raise HTTPException(
                status_code=400,
                detail="Не удалось автоматически определить username. Введите username вручную или проверьте sessionid.",
            ) from exc
        logger.info("Could not infer Instagram account username from secret: %s", exc.reason)

    username = inferred_username or normalized_username
    if username is None:
        raise HTTPException(
            status_code=400,
            detail="Не удалось автоматически определить username. Введите username вручную или проверьте sessionid.",
        )

    return await _store_account_secret(db, username, secret_kind, raw, assume_valid=bool(inferred_username))


@app.post("/api/accounts/login", response_model=AccountResponse)
async def login_instagram_account(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    two_factor_code: str | None = Form(None),
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Создаёт полноценную Instaloader session по логину/паролю без сохранения пароля."""
    _check_auth_rate_limit(request, "instagram_login")
    if not password:
        raise HTTPException(status_code=400, detail="Instagram password is required")
    try:
        account_username, raw = await instagram_provider.login_with_password(username, password, two_factor_code)
    except ProviderError as exc:
        _raise_provider_http(exc)
    return await _store_account_secret(db, account_username, "cookies", raw, assume_valid=True)


@app.post("/api/accounts/{account_id}/default")
async def set_default_account(account_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Выбирает аккаунт по умолчанию для сетевых запросов."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    rows = (await db.execute(select(Account))).scalars().all()
    for row in rows:
        row.is_default = row.id == account_id
    await db.commit()
    return {"ok": True}


@app.post("/api/accounts/{account_id}/validate", response_model=AccountResponse)
async def validate_account(account_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Проверяет сохранённый encrypted secret без раскрытия его наружу."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    ok, reason = await instagram_provider.validate_account(account)
    account.status = "OK" if ok else "INVALID_SESSION"
    account.failure_reason = reason
    account.last_validated_at = utcnow()
    await db.commit()
    await db.refresh(account)
    return AccountResponse.model_validate(account, from_attributes=True)


@app.delete("/api/accounts/{account_id}")
async def delete_account(account_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Удаляет account metadata и encrypted secret из vault."""
    account = await db.get(Account, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    delete_secret(account.secret_id)
    await db.delete(account)
    await db.commit()
    return {"ok": True}


@app.post("/api/profile/preview", response_model=ProfilePreviewResponse)
async def profile_preview(
    payload: ProfilePreviewRequest,
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Возвращает preview профиля из кэша или через Instaloader."""
    settings = await get_settings_map(db)
    try:
        username = instagram_provider.normalize_target(payload.target)
    except ProviderError as exc:
        _raise_provider_http(exc)
    limit = payload.limit or int(settings.get("default_preview_posts", DEFAULT_SETTINGS["default_preview_posts"]))
    now = utcnow()

    cache = await db.get(ProfileCache, username)
    if cache and cache.expires_at > now and not payload.force_refresh:
        return ProfilePreviewResponse(from_cache=True, cached_until=cache.expires_at, profile=cache.payload)

    if await find_active_job(db):
        if cache:
            return ProfilePreviewResponse(from_cache=True, cached_until=cache.expires_at, profile=cache.payload)
        raise HTTPException(status_code=409, detail="Активная задача выполняется; превью доступно только из кэша")

    account = await _default_account(db)
    try:
        preview = await instagram_provider.profile_preview(account, username, limit)
    except ProviderError as exc:
        await _mark_account_failed(db, account, exc)
        _raise_provider_http(exc)
    ttl = int(settings.get("preview_cache_ttl_sec", DEFAULT_SETTINGS["preview_cache_ttl_sec"]))
    expires_at = now + timedelta(seconds=ttl)

    if cache is None:
        cache = ProfileCache(username=username, payload=preview, fetched_at=now, expires_at=expires_at, account_id=account.id)
        db.add(cache)
    else:
        cache.payload = preview
        cache.fetched_at = now
        cache.expires_at = expires_at
        cache.account_id = account.id
    await db.commit()
    return ProfilePreviewResponse(from_cache=False, cached_until=expires_at, profile=preview)


@app.post("/api/jobs/create", response_model=JobStatusResponse)
async def create_job(
    payload: JobCreateRequest,
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Создаёт одну архивную job и запускает её в фоне."""
    if await find_active_job(db):
        raise HTTPException(status_code=409, detail="Допускается только одна активная задача")

    try:
        username = instagram_provider.normalize_target(payload.target)
    except ProviderError as exc:
        _raise_provider_http(exc)
    settings = await get_settings_map(db)
    account = await _default_account(db)
    shortcodes = list(dict.fromkeys(payload.shortcodes))

    if payload.mode != "selected":
        limit = payload.limit or int(settings.get("default_preview_posts", DEFAULT_SETTINGS["default_preview_posts"]))
        cache = await db.get(ProfileCache, username)
        if cache is None:
            try:
                preview = await instagram_provider.profile_preview(account, username, limit)
            except ProviderError as exc:
                await _mark_account_failed(db, account, exc)
                _raise_provider_http(exc)
            cache = ProfileCache(
                username=username,
                payload=preview,
                fetched_at=utcnow(),
                expires_at=utcnow(),
                account_id=account.id,
            )
            db.add(cache)
            await db.flush()
        posts = cache.payload.get("posts", [])
        shortcodes = [post["shortcode"] for post in posts[:limit]]

    if not shortcodes:
        raise HTTPException(status_code=400, detail="Нет публикаций для архивации")

    options = {
        "media": payload.options.get("media", payload.mode != "meta-only"),
        "comments": payload.options.get("comments", False),
        "zip": payload.options.get("zip", True),
    }
    job = Job(
        username=username,
        account_id=account.id,
        status="PENDING",
        mode=payload.mode,
        options=options,
        shortcodes=shortcodes,
        items_total=len(shortcodes),
    )
    db.add(job)
    await db.flush()
    for shortcode in shortcodes:
        db.add(JobItem(job_id=job.id, shortcode=shortcode))
    await db.commit()
    await db.refresh(job)
    schedule_job(job.id)
    return _job_response(job)


@app.get("/api/jobs", response_model=list[JobStatusResponse])
async def list_jobs(user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Возвращает последние задачи для UI."""
    rows = (
        await db.execute(
            select(Job)
            .order_by(Job.created_at.desc())
            .limit(50)
        )
    ).scalars().all()
    return [_job_response(job) for job in rows]


@app.get("/api/jobs/{job_id}/status", response_model=JobStatusResponse)
async def job_status(job_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Возвращает состояние job."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_response(job)


@app.post("/api/jobs/{job_id}/resume", response_model=JobStatusResponse)
async def job_resume(job_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Ручное возобновление WAITING/FAILED задачи с устранимой причиной."""
    if await find_active_job(db):
        raise HTTPException(status_code=409, detail="Другая активная задача уже выполняется")
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if not can_resume(job):
        raise HTTPException(status_code=400, detail="Эту задачу нельзя возобновить")
    job.status = "PENDING"
    job.retry_after_at = None
    await db.commit()
    await db.refresh(job)
    schedule_job(job.id)
    return _job_response(job)


@app.get("/api/jobs/{job_id}/download")
async def job_download(job_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Отдаёт ZIP только для DONE job."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "DONE" or not job.archive_path:
        raise HTTPException(status_code=409, detail="Архив ещё не готов")
    path = Path(job.archive_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Archive file not found")
    return FileResponse(path, media_type="application/zip", filename=path.name)


async def _default_account(db) -> Account:
    account = (
        await db.execute(
            select(Account)
            .where(Account.is_default.is_(True), Account.status == "OK")
            .limit(1)
        )
    ).scalar_one_or_none()
    if account is None:
        account = (
            await db.execute(select(Account).where(Account.status == "OK").order_by(Account.created_at.asc()).limit(1))
        ).scalar_one_or_none()
    if account is None:
        raise HTTPException(status_code=400, detail="Добавьте и проверьте Instagram account в UI")
    return account


async def _store_account_secret(
    db,
    username: str,
    secret_kind: str,
    raw: bytes,
    assume_valid: bool = False,
) -> AccountResponse:
    """Сохраняет encrypted Instagram secret и account metadata без раскрытия секрета."""
    secret_id = save_secret(raw)
    existing = (await db.execute(select(Account).where(Account.username == username))).scalar_one_or_none()
    if existing:
        delete_secret(existing.secret_id)
        account = existing
        account.secret_id = secret_id
        account.secret_kind = secret_kind
        account.status = "NEW"
        account.failure_reason = None
    else:
        has_accounts = (await db.execute(select(func.count(Account.id)))).scalar_one() > 0
        account = Account(username=username, secret_id=secret_id, secret_kind=secret_kind, is_default=not has_accounts)
        db.add(account)
    await db.flush()

    if assume_valid:
        ok, reason = True, None
    else:
        ok, reason = await instagram_provider.validate_account(account)
    account.status = "OK" if ok else "INVALID_SESSION"
    account.failure_reason = reason
    account.last_validated_at = utcnow()
    await db.commit()
    await db.refresh(account)
    return AccountResponse.model_validate(account, from_attributes=True)


async def _mark_account_failed(db, account: Account, exc: ProviderError) -> None:
    """Помечает текущий Instagram account невалидным при ошибке auth/secret."""
    if exc.reason in {"LOGIN_REQUIRED", "CHECKPOINT_REQUIRED", "SESSION_FILE_REQUIRED", "COOKIES_FORMAT_UNKNOWN"}:
        account.status = "INVALID_SESSION"
        account.failure_reason = exc.reason
        account.last_validated_at = utcnow()
        await db.commit()


async def initialize_database_with_retry(retries: int = 30, delay_sec: float = 2.0) -> None:
    """Ждёт PostgreSQL, применяет migrations/default settings/vault и запускает scheduler."""
    global _scheduler_task
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            await asyncio.to_thread(_run_alembic_upgrade)
            await init_engine()
            async for db in get_session():
                await seed_default_settings(db)
                break
            ensure_master_key()
            if _scheduler_task is None:
                _scheduler_task = asyncio.create_task(resume_scheduler())
            logger.info("PostgreSQL, migrations and encrypted vault are ready")
            return
        except Exception as exc:
            last_error = exc
            logger.info("Waiting for PostgreSQL (%s/%s): %s", attempt, retries, exc)
            await close_engine()
            await asyncio.sleep(delay_sec)
    logger.error("PostgreSQL is not ready: %s", last_error)


def _run_alembic_upgrade() -> None:
    """Применяет Alembic migrations из async startup через отдельный thread."""
    cfg = AlembicConfig(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    command.upgrade(cfg, "head")


async def create_admin_session(db, user: AdminUser, response: Response) -> None:
    """Создаёт cookie-сессию для локального администратора."""
    token = new_session_token()
    db.add(AdminSession(token_hash=token_hash(token), user_id=user.id, expires_at=session_expires(SESSION_TTL_SECONDS)))
    _set_session_cookie(response, token)


def _job_response(job: Job) -> JobStatusResponse:
    archive_path = Path(job.archive_path) if job.archive_path else None
    archive_exists = archive_path.exists() if archive_path else False
    archive_ready = job.status == "DONE" and archive_exists
    return JobStatusResponse(
        id=job.id,
        username=job.username,
        status=job.status,
        items_done=job.items_done,
        items_total=job.items_total,
        retry_after_at=job.retry_after_at,
        failure_reason=job.failure_reason,
        error_message=job.error_message,
        archive_ready=archive_ready,
        can_resume=can_resume(job),
        download_url=f"/api/jobs/{job.id}/download" if archive_ready else None,
        archive_filename=archive_path.name if archive_ready and archive_path else None,
        archive_size_bytes=archive_path.stat().st_size if archive_ready and archive_path else None,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _check_auth_rate_limit(request: Request, action: str) -> None:
    """Простой in-memory rate limit для локальных auth endpoints."""
    now = monotonic()
    ip = request.headers.get("x-forwarded-for", "").split(",", 1)[0].strip()
    if not ip and request.client:
        ip = request.client.host
    key = (ip or "local", action)
    attempts = _auth_attempts[key]
    while attempts and now - attempts[0] > AUTH_RATE_LIMIT_WINDOW_SEC:
        attempts.popleft()
    if len(attempts) >= AUTH_RATE_LIMIT_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="Слишком много попыток. Подождите минуту и попробуйте снова.")
    attempts.append(now)


def _raise_provider_http(exc: ProviderError) -> None:
    """Преобразует ошибки Instagram provider в понятные HTTP-ответы."""
    status_map = {
        "VALIDATION_ERROR": 422,
        "BAD_CREDENTIALS": 401,
        "LOGIN_FAILED": 401,
        "TWO_FACTOR_REQUIRED": 409,
        "SESSION_FILE_REQUIRED": 400,
        "COOKIES_FORMAT_UNKNOWN": 400,
        "LOGIN_REQUIRED": 401,
        "CHECKPOINT_REQUIRED": 401,
        "PRIVATE_PROFILE": 403,
        "PROFILE_NOT_FOUND": 404,
        "RATE_LIMIT": 429,
        "NETWORK_ERROR": 502,
        "INSTALOADER_NOT_INSTALLED": 503,
    }
    status_code = status_map.get(exc.reason, 502)
    message = exc.message or exc.reason
    raise HTTPException(status_code=status_code, detail=f"{exc.reason}: {message}")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
