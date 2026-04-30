"""FastAPI-приложение Instagram Archiver v4."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import mimetypes
import os
from collections import defaultdict, deque
from datetime import timedelta
from pathlib import Path
from time import monotonic
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request as UrlRequest, urlopen

from alembic import command
from alembic.config import Config as AlembicConfig
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
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
    JobItemResponse,
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
from vault import delete_secret, ensure_master_key, replace_secret, save_secret

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("instagram_archiver")

app = FastAPI(title="Instagram Archiver", version="1.0.0")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_scheduler_task: asyncio.Task | None = None
_auth_attempts: dict[tuple[str, str], deque[float]] = defaultdict(deque)
AUTH_RATE_LIMIT_WINDOW_SEC = 60
AUTH_RATE_LIMIT_MAX_ATTEMPTS = 8
MEDIA_PROXY_ALLOWED_HOST_SUFFIXES = ("instagram.com", "cdninstagram.com", "fbcdn.net")
MEDIA_PROXY_TIMEOUT_SEC = 15
MEDIA_PROXY_MAX_BYTES = 15 * 1024 * 1024
TRANSIENT_ACCOUNT_FAILURES = {"NETWORK_ERROR", "RATE_LIMIT", "SESSION_COOKIE_MISSING", "TIMEOUT", "UPSTREAM_502"}
AUTH_ACCOUNT_FAILURES = {
    "BAD_CREDENTIALS",
    "LOGIN_FAILED",
    "LOGIN_REQUIRED",
    "INVALID_SESSION",
    "CHECKPOINT_REQUIRED",
    "COOKIES_FORMAT_UNKNOWN",
    "UNSUPPORTED_LEGACY_SESSION",
}
PROVIDER_ERROR_HTTP_STATUS = {
    "VALIDATION_ERROR": 422,
    "BAD_CREDENTIALS": 401,
    "LOGIN_FAILED": 401,
    "TWO_FACTOR_REQUIRED": 409,
    "COOKIES_FORMAT_UNKNOWN": 400,
    "SESSION_COOKIE_MISSING": 401,
    "LOGIN_REQUIRED": 401,
    "INVALID_SESSION": 401,
    "UNSUPPORTED_LEGACY_SESSION": 400,
    "CHECKPOINT_REQUIRED": 401,
    "PRIVATE_PROFILE": 403,
    "PROFILE_NOT_FOUND": 404,
    "RATE_LIMIT": 429,
    "NETWORK_ERROR": 502,
    "TIMEOUT": 504,
    "UPSTREAM_502": 502,
    "PROVIDER_ERROR": 502,
    "UNKNOWN_ERROR": 502,
    "UNKNOWN": 502,
}
PROVIDER_ERROR_MESSAGES = {
    "ADMIN_UNAUTHORIZED": "Нужен вход администратора",
    "PROFILE_NOT_FOUND": "Профиль Instagram не найден",
    "LOGIN_REQUIRED": "Instagram-сессия недействительна, обновите cookies/settings",
    "INVALID_SESSION": "Instagram-сессия недействительна, обновите cookies/settings",
    "CHECKPOINT_REQUIRED": "Instagram требует подтверждения входа",
    "COOKIES_FORMAT_UNKNOWN": "Cookies/settings не распознаны, обновите account",
    "UNSUPPORTED_LEGACY_SESSION": "Старый формат сессии больше не поддерживается, загрузите cookies/settings",
    "BAD_CREDENTIALS": "Instagram не принял логин или пароль",
    "SESSION_COOKIE_MISSING": "Instagram не выдал sessionid, подтвердите вход и повторите",
    "RATE_LIMIT": "Временный rate limit Instagram. Повторите позже",
    "NETWORK_ERROR": "Instagram временно недоступен или отклонил запрос",
    "TIMEOUT": "Instagram не ответил вовремя",
    "PROVIDER_ERROR": "Instagram provider вернул ошибку",
    "UNKNOWN_ERROR": "Неизвестная ошибка Instagram provider",
}
PROVIDER_REASON_ALIASES = {
    "LOGIN_FAILED": "BAD_CREDENTIALS",
    "UNKNOWN": "UNKNOWN_ERROR",
}


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
        _raise_admin_unauthorized()
    session = (
        await db.execute(
            select(AdminSession).where(
                AdminSession.token_hash == token_hash(token),
                AdminSession.expires_at > utcnow(),
            )
        )
    ).scalar_one_or_none()
    if session is None:
        _raise_admin_unauthorized()
    user = await db.get(AdminUser, session.user_id)
    if user is None:
        _raise_admin_unauthorized()
    return user


@app.get("/api/auth/me")
async def auth_me(user: AdminUser = Depends(current_admin)):
    """Возвращает текущего admin-пользователя."""
    return {"username": user.username}


@app.get("/api/media/proxy")
async def media_proxy(url: str, user: AdminUser = Depends(current_admin)):
    """Безопасно проксирует preview images Instagram/CDN для авторизованного admin."""
    media_url = unquote(url).strip()
    parsed = urlparse(media_url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="Media proxy accepts only https URLs")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not _is_allowed_media_proxy_host(host):
        raise HTTPException(status_code=400, detail="Media proxy host is not allowed")

    try:
        content, content_type = await asyncio.to_thread(_fetch_media_proxy_bytes, media_url)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        logger.info("Media proxy upstream failed for allowed host %s: %s", host, type(exc).__name__)
        raise HTTPException(status_code=502, detail="Не удалось загрузить preview image") from exc
    return Response(content=content, media_type=content_type)


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
    secret_kind: str = Form("cookies"),
    secret_value: str | None = Form(None),
    secret_file: UploadFile | None = File(None),
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Загружает cookies/settings, шифрует и сохраняет только metadata в Postgres."""
    has_secret_value = bool(secret_value and secret_value.strip())
    if secret_kind not in {"cookies", "settings", "instagrapi_settings"}:
        raise HTTPException(status_code=400, detail="secret_kind must be cookies, settings or instagrapi_settings")

    if has_secret_value:
        raw = secret_value.strip().encode("utf-8")
    elif secret_file is not None:
        raw = await secret_file.read()
    else:
        raise HTTPException(status_code=400, detail="Secret file or cookies/settings string is required")

    if not raw:
        raise HTTPException(status_code=400, detail="Secret value is empty")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Secret file is too large")

    try:
        session_kind = _detect_session_kind(secret_kind, raw, has_secret_value)
        stored_secret_kind = _stored_secret_kind(secret_kind)
        user_agent = _extract_session_user_agent(raw)
    except ProviderError as exc:
        _raise_provider_http(exc)

    normalized_username: str | None = None
    username_input = (username or "").strip()
    if username_input:
        try:
            normalized_username = instagram_provider.normalize_target(username_input)
        except ProviderError as exc:
            _raise_provider_http(exc)

    inferred_username: str | None = None
    try:
        inferred_username = await instagram_provider.infer_account_username(stored_secret_kind, raw, normalized_username)
    except ProviderError as exc:
        if normalized_username is None:
            raise HTTPException(
                status_code=400,
                detail="Не удалось автоматически определить username. Введите username вручную или проверьте cookies/settings.",
            ) from exc
        logger.info("Could not infer Instagram account username from secret: %s", exc.reason)

    username = inferred_username or normalized_username
    if username is None:
        raise HTTPException(
            status_code=400,
            detail="Не удалось автоматически определить username. Введите username вручную или проверьте cookies/settings.",
        )

    return await _store_account_secret(
        db,
        username,
        stored_secret_kind,
        raw,
        session_kind=session_kind,
        user_agent=user_agent,
        assume_valid=False,
    )
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
    ok, reason = await _validate_account_with_session_update(account)
    _apply_account_validation_result(account, ok, reason)
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
    delete_secret(account.settings_secret_id)
    await db.delete(account)
    await db.commit()
    return {"ok": True}


@app.post("/api/profile/preview", response_model=ProfilePreviewResponse)
async def profile_preview(
    payload: ProfilePreviewRequest,
    user: AdminUser = Depends(current_admin),
    db=Depends(get_session),
):
    """Возвращает preview профиля из кэша или через выбранный Instagram provider."""
    settings = await get_settings_map(db)
    try:
        username = instagram_provider.normalize_target(payload.target)
    except ProviderError as exc:
        _raise_provider_http(exc)
    limit = payload.limit or int(settings.get("default_preview_posts", DEFAULT_SETTINGS["default_preview_posts"]))
    now = utcnow()

    cache = await db.get(ProfileCache, username)
    if cache and cache.expires_at > now and not payload.force_refresh and _preview_cache_is_usable(cache, limit):
        cached_profile = _normalize_preview_payload(cache.payload)
        logger.info("profile_preview_success provider=%s target=%s source=cache", _provider_name(), username)
        return ProfilePreviewResponse(
            ok=True,
            source="cache",
            from_cache=True,
            cached_until=cache.expires_at,
            profile=cached_profile,
            error=None,
        )

    if await find_active_job(db):
        if cache and cache.expires_at > now and _preview_cache_is_usable(cache, limit):
            cached_profile = _normalize_preview_payload(cache.payload)
            logger.info("profile_preview_success provider=%s target=%s source=cache", _provider_name(), username)
            return ProfilePreviewResponse(
                ok=True,
                source="cache",
                from_cache=True,
                cached_until=cache.expires_at,
                profile=cached_profile,
                error=None,
            )
        raise HTTPException(status_code=409, detail="Активная задача выполняется; превью доступно только из кэша")

    account = await _default_account(db)
    try:
        preview = await instagram_provider.profile_preview(account, username, limit)
        _apply_account_session_update(account, _pop_provider_session_update(preview))
        preview = _normalize_preview_payload(preview)
        _apply_account_validation_result(account, True, None)
    except ProviderError as exc:
        await _mark_account_failed(db, account, exc)
        error_code = _normalize_provider_error_code(exc)
        logger.info(
            "profile_preview_failed provider=%s target=%s error_code=%s",
            _provider_name(),
            username,
            error_code,
        )
        return _provider_error_json_response(exc)
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
    logger.info("profile_preview_success provider=%s target=%s source=fresh", _provider_name(), username)
    return ProfilePreviewResponse(
        ok=True,
        source="fresh",
        from_cache=False,
        cached_until=expires_at,
        profile=preview,
        error=None,
    )


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
    cache = await db.get(ProfileCache, username)
    preview_posts_by_shortcode: dict[str, dict] = {}
    if cache is not None:
        cached_profile = _normalize_preview_payload(cache.payload)
        preview_posts_by_shortcode = {
            post["shortcode"]: post
            for post in cached_profile.get("posts", [])
            if post.get("shortcode")
        }

    if payload.mode != "selected":
        limit = payload.limit or int(settings.get("default_preview_posts", DEFAULT_SETTINGS["default_preview_posts"]))
        if cache is None or not _preview_cache_is_usable(cache, limit):
            try:
                preview = await instagram_provider.profile_preview(account, username, limit)
                _apply_account_session_update(account, _pop_provider_session_update(preview))
                preview = _normalize_preview_payload(preview)
                _apply_account_validation_result(account, True, None)
            except ProviderError as exc:
                await _mark_account_failed(db, account, exc)
                _raise_provider_http(exc)
            if cache is None:
                cache = ProfileCache(
                    username=username,
                    payload=preview,
                    fetched_at=utcnow(),
                    expires_at=utcnow(),
                    account_id=account.id,
                )
                db.add(cache)
                await db.flush()
            else:
                cache.payload = preview
                cache.fetched_at = utcnow()
                cache.account_id = account.id
            preview_posts_by_shortcode = {
                post["shortcode"]: post
                for post in preview.get("posts", [])
                if post.get("shortcode")
            }
        else:
            cached_profile = _normalize_preview_payload(cache.payload)
            preview_posts_by_shortcode = {
                post["shortcode"]: post
                for post in cached_profile.get("posts", [])
                if post.get("shortcode")
            }
        posts = list(preview_posts_by_shortcode.values())
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
        db.add(
            JobItem(
                job_id=job.id,
                shortcode=shortcode,
                media_type=preview_posts_by_shortcode.get(shortcode, {}).get("type") or "unknown",
            )
        )
    await db.commit()
    await db.refresh(job)
    schedule_job(job.id)
    return await _job_response(db, job)


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
    return [await _job_response(db, job) for job in rows]


@app.get("/api/jobs/{job_id}/status", response_model=JobStatusResponse)
async def job_status(job_id: str, user: AdminUser = Depends(current_admin), db=Depends(get_session)):
    """Возвращает состояние job."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return await _job_response(db, job)


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
    return await _job_response(db, job)


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
    session_kind: str,
    user_agent: str | None = None,
    assume_valid: bool = False,
) -> AccountResponse:
    """Сохраняет encrypted Instagram secret и account metadata без раскрытия секрета."""
    secret_id = save_secret(raw)
    existing = (await db.execute(select(Account).where(Account.username == username))).scalar_one_or_none()
    if existing:
        delete_secret(existing.secret_id)
        delete_secret(existing.settings_secret_id)
        account = existing
        account.secret_id = secret_id
        account.secret_kind = secret_kind
        account.settings_secret_id = None
        account.provider = "instagram"
        account.session_kind = session_kind
        account.user_agent = user_agent
        account.status = "NEW"
        account.failure_reason = None
        account.last_error_reason = None
        account.last_error_at = None
    else:
        has_accounts = (await db.execute(select(func.count(Account.id)))).scalar_one() > 0
        account = Account(
            username=username,
            provider="instagram",
            secret_id=secret_id,
            secret_kind=secret_kind,
            session_kind=session_kind,
            user_agent=user_agent,
            is_default=not has_accounts,
        )
        db.add(account)
    await db.flush()

    if assume_valid:
        if session_kind == "instagrapi_settings":
            account.settings_secret_id = save_secret(raw)
        _apply_account_validation_result(account, True, None)
    else:
        ok, reason = await _validate_account_with_session_update(account)
        _apply_account_validation_result(account, ok, reason)
    await db.commit()
    await db.refresh(account)
    return AccountResponse.model_validate(account, from_attributes=True)


async def _validate_account_with_session_update(account: Account) -> tuple[bool, str | None]:
    """Validates an account and persists provider-returned settings on the async side."""
    validator = getattr(instagram_provider, "validate_account_with_session_update", None)
    if callable(validator):
        ok, reason, session_update = await validator(account)
        if ok:
            try:
                _apply_account_session_update(account, session_update)
            except ProviderError as exc:
                return False, exc.reason
        return ok, reason
    return await instagram_provider.validate_account(account)


def _pop_provider_session_update(payload: dict) -> object | None:
    """Removes non-JSON provider session data before normalizing/caching preview."""
    if not isinstance(payload, dict):
        return None
    return payload.pop("_session_update", None)


def _apply_account_session_update(account: Account, session_update: object | None) -> None:
    """Persists refreshed instagrapi settings without mutating SQLAlchemy objects in worker threads."""
    if session_update is None:
        return

    raw_settings = getattr(session_update, "raw_settings", None)
    if not isinstance(raw_settings, bytes) or not raw_settings:
        raise ProviderError("PROVIDER_ERROR", "Instagram provider вернул пустые session settings")

    try:
        if account.settings_secret_id:
            replace_secret(account.settings_secret_id, raw_settings)
        else:
            account.settings_secret_id = save_secret(raw_settings)
    except Exception as exc:
        raise ProviderError("PROVIDER_ERROR", "Не удалось сохранить Instagram session settings") from exc

    account.provider = "instagram"
    account.user_agent = getattr(session_update, "user_agent", None)


def _detect_session_kind(secret_kind: str, raw: bytes, has_secret_value: bool = False) -> str:
    detector = getattr(instagram_provider, "detect_session_kind", None)
    if callable(detector):
        try:
            return detector(secret_kind, raw, has_secret_value)
        except ProviderError:
            raise
        except Exception:
            logger.info("Could not classify Instagram session kind", exc_info=True)
    if secret_kind in {"settings", "instagrapi_settings"}:
        return "instagrapi_settings"
    if secret_kind == "cookies":
        return "browser_cookies"
    return "unsupported_legacy"


def _stored_secret_kind(secret_kind: str) -> str:
    normalizer = getattr(instagram_provider, "stored_secret_kind", None)
    if callable(normalizer):
        return normalizer(secret_kind)
    return "cookies" if secret_kind in {"cookies", "settings", "instagrapi_settings"} else secret_kind


def _extract_session_user_agent(raw: bytes) -> str | None:
    extractor = getattr(instagram_provider, "extract_user_agent", None)
    if callable(extractor):
        try:
            return extractor(raw)
        except Exception:
            return None
    return None


def _apply_account_validation_result(account: Account, ok: bool, reason: str | None) -> None:
    now = utcnow()
    account.last_validated_at = now
    if ok:
        account.status = "OK"
        account.failure_reason = None
        account.last_ok_at = now
        account.last_error_at = None
        account.last_error_reason = None
        return

    account.failure_reason = reason
    account.last_error_at = now
    account.last_error_reason = reason
    if reason not in TRANSIENT_ACCOUNT_FAILURES:
        account.status = "INVALID_SESSION"


async def _mark_account_failed(db, account: Account, exc: ProviderError) -> None:
    """Помечает текущий Instagram account невалидным при ошибке auth/secret."""
    account.last_error_at = utcnow()
    account.last_error_reason = exc.reason
    account.failure_reason = exc.reason
    if exc.reason in AUTH_ACCOUNT_FAILURES:
        account.status = "INVALID_SESSION"
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


async def _job_response(db, job: Job) -> JobStatusResponse:
    archive_path = Path(job.archive_path) if job.archive_path else None
    archive_exists = archive_path.exists() if archive_path else False
    archive_ready = job.status == "DONE" and archive_exists
    items_done = int(getattr(job, "items_done", 0) or 0)
    completed_items = int(getattr(job, "completed_items", 0) or 0)
    return JobStatusResponse(
        id=job.id,
        job_id=job.id,
        target=job.username,
        username=job.username,
        mode=job.mode,
        status=job.status,
        items_done=items_done,
        items_total=job.items_total,
        completed_items=completed_items or items_done,
        failed_items=int(getattr(job, "failed_items", 0) or 0),
        retry_after_at=job.retry_after_at,
        failure_reason=job.failure_reason,
        error_code=job.error_code,
        error_message=job.error_message,
        archive_ready=archive_ready,
        can_resume=can_resume(job),
        download_url=f"/api/jobs/{job.id}/download" if archive_ready else None,
        result_dir=job.result_dir,
        archive_filename=archive_path.name if archive_ready and archive_path else None,
        archive_size_bytes=archive_path.stat().st_size if archive_ready and archive_path else None,
        items=await _job_item_responses(db, job.id),
        created_at=job.created_at,
        updated_at=job.updated_at,
        started_at=job.started_at,
        finished_at=job.finished_at,
    )


async def _job_item_responses(db, job_id: str) -> list[JobItemResponse]:
    rows = (
        await db.execute(
            select(JobItem)
            .where(JobItem.job_id == job_id)
            .order_by(JobItem.id.asc())
        )
    ).scalars().all()
    return [JobItemResponse.model_validate(row, from_attributes=True) for row in rows]


def _is_allowed_media_proxy_host(host: str) -> bool:
    """Проверяет allowlist host без превращения proxy в открытый SSRF endpoint."""
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    except ValueError:
        pass
    return any(host == suffix or host.endswith(f".{suffix}") for suffix in MEDIA_PROXY_ALLOWED_HOST_SUFFIXES)


def _fetch_media_proxy_bytes(media_url: str) -> tuple[bytes, str]:
    """Синхронная загрузка media bytes для запуска через asyncio.to_thread."""
    request = UrlRequest(
        media_url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
            ),
            "Referer": "https://www.instagram.com/",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urlopen(request, timeout=MEDIA_PROXY_TIMEOUT_SEC) as upstream:
        final_url = urlparse(upstream.geturl())
        final_host = (final_url.hostname or "").lower().rstrip(".")
        if final_url.scheme != "https" or not _is_allowed_media_proxy_host(final_host):
            raise ValueError("Media proxy upstream redirect is not allowed")
        content_type = upstream.headers.get("content-type")
        if not content_type:
            guessed, _ = mimetypes.guess_type(urlparse(media_url).path)
            content_type = guessed or "application/octet-stream"
        content_type = content_type.split(";", 1)[0].strip().lower()
        if not content_type.startswith("image/"):
            raise ValueError("Upstream media is not an image")

        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = upstream.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MEDIA_PROXY_MAX_BYTES:
                raise ValueError("Media proxy response is too large")
            chunks.append(chunk)
    return b"".join(chunks), content_type


def _normalize_preview_payload(payload: dict) -> dict:
    """Приводит fresh/legacy cache payload к frontend Real API contract без fake data."""
    source = payload if isinstance(payload, dict) else {}
    profile = dict(source)

    if "full_name" not in profile and "fullname" in profile:
        profile["full_name"] = profile.get("fullname")
    if "bio" not in profile and "biography" in profile:
        profile["bio"] = profile.get("biography")
    if "followers_count" not in profile and "followers" in profile:
        profile["followers_count"] = _optional_int(profile.get("followers"))
    if "following_count" not in profile and "following" in profile:
        profile["following_count"] = _optional_int(profile.get("following"))

    raw_posts = profile.get("posts")
    posts = raw_posts if isinstance(raw_posts, list) else []
    normalized_posts = [_normalize_preview_post(post) for post in posts if isinstance(post, dict)]
    profile["posts"] = [post for post in normalized_posts if post.get("shortcode")]
    profile["posts_count"] = _optional_int(profile.get("posts_count")) or len(profile["posts"])
    profile["profile_pic_url"] = profile.get("profile_pic_url") or None
    profile["external_url"] = profile.get("external_url") or None
    profile["is_private"] = bool(profile.get("is_private", False))
    profile["is_verified"] = bool(profile.get("is_verified", False))
    profile.setdefault("bio", None)
    profile.setdefault("full_name", None)
    profile.setdefault("followers_count", None)
    profile.setdefault("following_count", None)
    return profile


def _normalize_preview_post(post: dict) -> dict:
    """Нормализует post preview, сохраняя только реальные provider поля."""
    shortcode = post.get("shortcode")
    post_type = post.get("type")
    if post_type == "image":
        post_type = "photo"
    if post_type not in {"photo", "video", "carousel", "unknown"}:
        post_type = "video" if post.get("is_video") else "unknown"
    return {
        "shortcode": shortcode,
        "id": str(post.get("id") or post.get("mediaid") or shortcode) if (post.get("id") or post.get("mediaid") or shortcode) else None,
        "type": post_type,
        "preview_url": post.get("preview_url") or post.get("url") or None,
        "caption": post.get("caption") or None,
        "date": post.get("date") or None,
        "likes": _optional_int(post.get("likes")),
        "comments": _optional_int(post.get("comments")),
        "location": post.get("location") or None,
        "carousel_count": _optional_int(post.get("carousel_count")),
        "is_video": bool(post.get("is_video") or post_type == "video"),
    }


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _preview_cache_is_usable(cache: ProfileCache, requested_limit: int) -> bool:
    """Не отдаёт пустой/битый preview cache как успешную загрузку профиля."""
    payload = cache.payload if isinstance(cache.payload, dict) else {}
    posts = payload.get("posts")
    if not isinstance(posts, list):
        posts = []
    try:
        posts_count = int(payload.get("posts_count") or 0)
    except (TypeError, ValueError):
        posts_count = 0
    if posts_count == 0:
        return True
    expected = max(1, min(int(requested_limit or 1), posts_count))
    return len(posts) >= expected


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


def _provider_name() -> str:
    """Возвращает безопасное имя активного preview provider для логов."""
    return getattr(instagram_provider, "provider_name", type(instagram_provider).__name__)


def _normalize_provider_error_code(exc: ProviderError) -> str:
    """Преобразует внутренние provider reasons в публичные error_code."""
    return PROVIDER_REASON_ALIASES.get(exc.reason, exc.reason if exc.reason in PROVIDER_ERROR_HTTP_STATUS else "UNKNOWN_ERROR")


def _provider_error_payload(exc: ProviderError) -> dict[str, object]:
    """Единый JSON-контракт ошибок Instagram provider без raw traceback/secret values."""
    error_code = _normalize_provider_error_code(exc)
    message = PROVIDER_ERROR_MESSAGES.get(error_code) or exc.message or error_code
    return {
        "ok": False,
        "error_code": error_code,
        "message": message,
        "retry_after": None,
    }


def _provider_error_json_response(exc: ProviderError) -> JSONResponse:
    """Возвращает structured error response для preview endpoint."""
    status_code = PROVIDER_ERROR_HTTP_STATUS.get(exc.reason)
    if status_code is None:
        status_code = PROVIDER_ERROR_HTTP_STATUS.get(_normalize_provider_error_code(exc), 502)
    return JSONResponse(status_code=status_code, content=_provider_error_payload(exc))


def _raise_admin_unauthorized() -> None:
    """Возвращает структурированную auth-ошибку без раскрытия деталей session cookie."""
    raise HTTPException(
        status_code=401,
        detail={
            "error_code": "ADMIN_UNAUTHORIZED",
            "message": PROVIDER_ERROR_MESSAGES["ADMIN_UNAUTHORIZED"],
            "retry_after": None,
        },
    )


def _raise_provider_http(exc: ProviderError) -> None:
    """Преобразует ошибки Instagram provider в понятные HTTP-ответы."""
    status_code = PROVIDER_ERROR_HTTP_STATUS.get(exc.reason)
    if status_code is None:
        status_code = PROVIDER_ERROR_HTTP_STATUS.get(_normalize_provider_error_code(exc), 502)
    raise HTTPException(status_code=status_code, detail=_provider_error_payload(exc))


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        max_age=SESSION_TTL_SECONDS,
        httponly=True,
        samesite="lax",
        secure=COOKIE_SECURE,
    )
