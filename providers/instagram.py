"""Instagram preview, metadata and session helpers powered by instagrapi."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import tempfile
from dataclasses import dataclass
from datetime import timezone
from http.cookiejar import MozillaCookieJar
from time import monotonic
from typing import Any
from urllib.parse import unquote

from providers.base import BaseProvider, ProviderError
from vault import load_secret

logger = logging.getLogger("uvicorn.error")


def _duration_ms(started_at: float) -> float:
    return round((monotonic() - started_at) * 1000, 2)


def _safe_timing_log(message: str, *args: object) -> None:
    """Emits provider timing logs without session/cookie values."""
    logger.info(message, *args)
    try:
        print(message % args, flush=True)
    except Exception:
        pass


@dataclass(frozen=True, slots=True)
class AccountSessionRef:
    """Immutable account session data safe to pass into worker threads."""

    username: str
    secret_id: str
    secret_kind: str
    settings_secret_id: str | None


@dataclass(frozen=True, slots=True)
class SessionSettingsUpdate:
    """Updated instagrapi settings returned to the async persistence layer."""

    raw_settings: bytes
    user_agent: str | None


class SessionStore:
    """Parses stored Instagram cookies/settings and prepares downloader cookies."""

    def detect_session_kind(self, secret_kind: str, raw_secret: bytes, has_secret_value: bool = False) -> str:
        if self.settings_from_secret(raw_secret) is not None:
            return "instagrapi_settings"
        if secret_kind in {"settings", "instagrapi_settings"}:
            return "instagrapi_settings"
        if secret_kind in {"cookies"}:
            self.cookies_from_secret(raw_secret)
            return "browser_cookies"
        raise ProviderError(
            "UNSUPPORTED_LEGACY_SESSION",
            "Этот тип Instagram-сессии больше не поддерживается. Загрузите browser cookies или instagrapi settings.",
        )

    def stored_secret_kind(self, secret_kind: str) -> str:
        if secret_kind in {"settings", "instagrapi_settings"}:
            return "cookies"
        if secret_kind == "cookies":
            return "cookies"
        raise ProviderError(
            "UNSUPPORTED_LEGACY_SESSION",
            "Этот тип Instagram-сессии больше не поддерживается. Загрузите browser cookies или instagrapi settings.",
        )

    def extract_user_agent(self, raw_secret: bytes) -> str | None:
        settings = self.settings_json_payload(raw_secret)
        if isinstance(settings, dict):
            user_agent = settings.get("user_agent")
            if isinstance(user_agent, str) and user_agent:
                return user_agent
        return None

    def settings_from_secret(self, raw_secret: bytes, allow_network: bool = True) -> dict[str, Any] | None:
        data = self.settings_json_payload(raw_secret)
        if data is None or not self.looks_like_settings(data):
            return None

        settings = dict(data)
        cookies = self.cookies_from_settings(settings)
        self.complete_instagram_cookies(cookies, allow_network=allow_network)
        settings["cookies"] = cookies
        settings["authorization_data"] = self.authorization_data_from_cookies(
            cookies,
            settings.get("authorization_data"),
        )
        return settings

    def settings_json_payload(self, raw_secret: bytes) -> Any | None:
        text = raw_secret.decode("utf-8", errors="ignore").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None

    def looks_like_settings(self, value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        markers = {
            "uuids",
            "device_settings",
            "authorization_data",
            "last_login",
            "user_agent",
            "timezone_offset",
        }
        return any(key in value for key in markers) and "cookies" in value

    def cookies_from_settings(self, settings: dict[str, Any]) -> dict[str, str]:
        cookies: dict[str, str] = {}
        raw_cookies = settings.get("cookies")
        if isinstance(raw_cookies, dict):
            for key, value in raw_cookies.items():
                if isinstance(key, str) and value is not None:
                    cookies[key] = str(value)

        auth = settings.get("authorization_data")
        if isinstance(auth, dict):
            for key in ("sessionid", "ds_user_id"):
                value = auth.get(key)
                if isinstance(value, str) and value:
                    cookies.setdefault(key, value)

        if not cookies.get("sessionid"):
            raise ProviderError("COOKIES_FORMAT_UNKNOWN", "Instagrapi settings не содержат sessionid")
        return cookies

    def settings_from_cookies(self, client, cookies: dict[str, str], allow_network: bool = True) -> dict[str, Any]:
        self.complete_instagram_cookies(cookies, allow_network=allow_network)
        if not cookies.get("sessionid"):
            raise ProviderError("COOKIES_FORMAT_UNKNOWN", "Cookies-файл должен содержать sessionid")
        settings = client.get_settings()
        settings["cookies"] = cookies
        settings["authorization_data"] = self.authorization_data_from_cookies(cookies)
        settings["request_timeout"] = 30
        return settings

    def authorization_data_from_cookies(
        self,
        cookies: dict[str, str],
        existing: Any | None = None,
    ) -> dict[str, Any]:
        sessionid = cookies.get("sessionid")
        if not sessionid:
            raise ProviderError("COOKIES_FORMAT_UNKNOWN", "Cookies-файл должен содержать sessionid")

        auth = dict(existing) if isinstance(existing, dict) else {}
        auth["sessionid"] = sessionid
        auth.setdefault("should_use_header_over_cookies", True)

        user_id = cookies.get("ds_user_id")
        if not user_id:
            decoded_sessionid = unquote(sessionid)
            prefix = decoded_sessionid.split(":", 1)[0]
            if prefix.isdigit():
                user_id = prefix
        if user_id:
            auth["ds_user_id"] = str(user_id)
            cookies.setdefault("ds_user_id", str(user_id))
        return auth

    def cookies_from_secret(self, raw_secret: bytes, allow_network: bool = True) -> dict[str, str]:
        text = raw_secret.decode("utf-8", errors="ignore").strip()
        cookies = (
            self.cookies_from_sessionid_label(text)
            or self.cookies_from_json(text)
            or self.cookies_from_netscape(text)
            or self.cookies_from_pairs(text)
        )
        if not cookies or not cookies.get("sessionid"):
            raise ProviderError(
                "COOKIES_FORMAT_UNKNOWN",
                "Cookies/settings должны содержать sessionid.",
            )
        self.complete_instagram_cookies(cookies, allow_network=allow_network)
        cookies.setdefault("csrftoken", "")
        return cookies

    def cookies_from_sessionid_label(self, text: str) -> dict[str, str] | None:
        match = re.search(r"sessionid\s*[:=]\s*[\"']?([^\"';\s]+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return {"sessionid": match.group(1).strip()}

    def cookies_from_json(self, text: str) -> dict[str, str] | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        cookies: dict[str, str] = {}
        if isinstance(data, dict):
            raw_cookies = data.get("cookies")
            if isinstance(raw_cookies, dict):
                for key, value in raw_cookies.items():
                    if isinstance(key, str) and value is not None:
                        cookies[key] = str(value)
                auth = data.get("authorization_data")
                if isinstance(auth, dict):
                    for key in ("sessionid", "ds_user_id"):
                        value = auth.get(key)
                        if isinstance(value, str) and value:
                            cookies.setdefault(key, value)
                return cookies or None
            if isinstance(raw_cookies, list):
                data = raw_cookies
            else:
                for key, value in data.items():
                    if isinstance(value, str):
                        cookies[key] = value
                auth = data.get("authorization_data")
                if isinstance(auth, dict):
                    for key in ("sessionid", "ds_user_id"):
                        value = auth.get(key)
                        if isinstance(value, str) and value:
                            cookies.setdefault(key, value)
                return cookies or None

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue
                name = item.get("name") or item.get("Name")
                value = item.get("value") or item.get("Value")
                if isinstance(name, str) and isinstance(value, str):
                    cookies[name] = value
        return cookies or None

    def cookies_from_netscape(self, text: str) -> dict[str, str] | None:
        if "\t" not in text:
            return None
        with tempfile.NamedTemporaryFile("w+", prefix="archiver-cookies-", delete=True) as tmp:
            tmp.write(text)
            tmp.flush()
            jar = MozillaCookieJar(tmp.name)
            try:
                jar.load(ignore_discard=True, ignore_expires=True)
            except Exception:
                return None
        cookies = {cookie.name: cookie.value for cookie in jar}
        return cookies or None

    def cookies_from_pairs(self, text: str) -> dict[str, str] | None:
        cookies: dict[str, str] = {}
        normalized = text.replace("\n", ";")
        for part in normalized.split(";"):
            if "=" not in part:
                continue
            name, value = part.split("=", 1)
            name = name.strip()
            value = value.strip()
            if name and value:
                cookies[name] = value
        return cookies or None

    def complete_instagram_cookies(self, cookies: dict[str, str], allow_network: bool = True) -> None:
        sessionid = cookies.get("sessionid")
        if not sessionid:
            return

        decoded_sessionid = unquote(sessionid)
        user_id = decoded_sessionid.split(":", 1)[0]
        if user_id.isdigit():
            cookies.setdefault("ds_user_id", user_id)

        if cookies.get("csrftoken") and cookies.get("mid"):
            return

        if not allow_network:
            return

        try:
            import requests
        except ImportError:
            return

        session = requests.Session()
        for name, value in cookies.items():
            if value:
                session.cookies.set(name, value, domain=".instagram.com")
        headers = {
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/121.0 Safari/537.36"
            ),
        }

        try:
            session.get("https://www.instagram.com/", headers=headers, timeout=20)
        except Exception:
            return

        for name in ("csrftoken", "mid", "ig_did", "rur", "datr", "ds_user_id"):
            value = session.cookies.get(name)
            if value:
                cookies[name] = value


class InstagramPreviewProvider(BaseProvider):
    """Instagram provider on instagrapi for preview, metadata, comments and session state."""

    provider_name = "instagrapi"

    def __init__(self, session_store: SessionStore | None = None):
        self.session_store = session_store or SessionStore()

    def normalize_target(self, value: str) -> str:
        raw = value.strip().lower()
        if raw.startswith("@"):
            raw = raw[1:]
        match = re.search(r"instagram\.com/([^/?#\s]+)", raw)
        if match:
            raw = match.group(1)
        raw = raw.strip("/")
        if not re.fullmatch(r"[a-z0-9._]{1,30}", raw):
            raise ProviderError("VALIDATION_ERROR", "Некорректный username Instagram")
        return raw

    async def validate_account(self, account) -> tuple[bool, str | None]:
        ok, reason, _ = await self.validate_account_with_session_update(account)
        return ok, reason

    async def validate_account_with_session_update(
        self,
        account,
    ) -> tuple[bool, str | None, SessionSettingsUpdate | None]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._validate_account_sync, session_ref)

    async def infer_account_username(
        self,
        secret_kind: str,
        raw_secret: bytes,
        fallback_username: str | None = None,
    ) -> str | None:
        return await asyncio.to_thread(
            self._infer_account_username_sync,
            secret_kind,
            raw_secret,
            fallback_username,
        )

    async def profile_preview(self, account, username: str, limit: int, force_refresh: bool = False) -> dict[str, Any]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._profile_preview_sync, session_ref, username, limit, force_refresh)

    async def profile_info(self, account, username: str, force_refresh: bool = False) -> dict[str, Any]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._profile_info_sync, session_ref, username, force_refresh)

    async def profile_medias_index(self, account, profile_pk: str, limit: int) -> list[dict[str, Any]]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._profile_medias_index_sync, session_ref, profile_pk, limit)

    async def post_metadata(self, account, username: str, shortcode: str) -> dict[str, Any]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._post_metadata_sync, session_ref, username, shortcode)

    async def post_comments(
        self,
        account,
        shortcode: str,
        comments_limit: int,
    ) -> list[dict[str, Any]]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._post_comments_sync, session_ref, shortcode, comments_limit)

    async def downloader_cookies(self, account) -> dict[str, str]:
        session_ref = self._account_session_ref(account)
        return await asyncio.to_thread(self._downloader_cookies_sync, session_ref)

    def detect_session_kind(self, secret_kind: str, raw_secret: bytes, has_secret_value: bool = False) -> str:
        return self.session_store.detect_session_kind(secret_kind, raw_secret, has_secret_value)

    def stored_secret_kind(self, secret_kind: str) -> str:
        return self.session_store.stored_secret_kind(secret_kind)

    def extract_user_agent(self, raw_secret: bytes) -> str | None:
        return self.session_store.extract_user_agent(raw_secret)

    def _import_instagrapi_client(self):
        try:
            from instagrapi import Client
        except ImportError as exc:
            raise ProviderError(
                "PROVIDER_ERROR",
                "Instagrapi preview provider выбран, но пакет instagrapi не установлен.",
            ) from exc
        return Client

    def _new_client(self):
        Client = self._import_instagrapi_client()
        return Client()

    def _account_session_ref(self, account) -> AccountSessionRef:
        return AccountSessionRef(
            username=account.username,
            secret_id=account.secret_id,
            secret_kind=account.secret_kind,
            settings_secret_id=getattr(account, "settings_secret_id", None),
        )

    def _client_from_session_ref(self, session_ref: AccountSessionRef, allow_network: bool = True):
        if session_ref.secret_kind != "cookies":
            raise ProviderError(
                "UNSUPPORTED_LEGACY_SESSION",
                "Этот тип Instagram-сессии больше не поддерживается. Загрузите browser cookies или instagrapi settings.",
            )

        if session_ref.settings_secret_id:
            try:
                raw_settings = load_secret(session_ref.settings_secret_id)
                return self._client_from_raw_secret(
                    "instagrapi_settings",
                    raw_settings,
                    session_ref.username,
                    allow_network=allow_network,
                )
            except ProviderError:
                pass
            except Exception:
                pass

        raw_secret = load_secret(session_ref.secret_id)
        return self._client_from_raw_secret(
            session_ref.secret_kind,
            raw_secret,
            session_ref.username,
            allow_network=allow_network,
        )

    def _client_from_raw_secret(
        self,
        secret_kind: str,
        raw_secret: bytes,
        username: str | None = None,
        allow_network: bool = True,
    ):
        client = self._new_client()
        settings = self._settings_from_raw_secret(client, secret_kind, raw_secret, username, allow_network)
        client.set_settings(settings)
        return client

    def _settings_from_raw_secret(
        self,
        client,
        secret_kind: str,
        raw_secret: bytes,
        username: str | None = None,
        allow_network: bool = True,
    ) -> dict[str, Any]:
        settings = self.session_store.settings_from_secret(raw_secret, allow_network=allow_network)
        if settings is not None:
            return settings

        if secret_kind in {"settings", "instagrapi_settings"}:
            raise ProviderError("COOKIES_FORMAT_UNKNOWN", "Instagrapi settings не содержат sessionid")
        if secret_kind != "cookies":
            raise ProviderError(
                "UNSUPPORTED_LEGACY_SESSION",
                "Этот тип Instagram-сессии больше не поддерживается. Загрузите browser cookies или instagrapi settings.",
            )

        return self.session_store.settings_from_cookies(
            client,
            self.session_store.cookies_from_secret(raw_secret, allow_network=allow_network),
            allow_network=allow_network,
        )

    def _downloader_cookies_sync(self, session_ref: AccountSessionRef) -> dict[str, str]:
        if session_ref.settings_secret_id:
            try:
                raw_settings = load_secret(session_ref.settings_secret_id)
                settings = self.session_store.settings_from_secret(raw_settings, allow_network=False)
                if settings is not None:
                    return self.session_store.cookies_from_settings(settings)
            except ProviderError:
                pass
            except Exception:
                pass

        if session_ref.secret_kind != "cookies":
            raise ProviderError(
                "UNSUPPORTED_LEGACY_SESSION",
                "Этот тип Instagram-сессии больше не поддерживается. Загрузите browser cookies или instagrapi settings.",
            )
        raw_secret = load_secret(session_ref.secret_id)
        settings = self.session_store.settings_from_secret(raw_secret, allow_network=False)
        if settings is not None:
            return self.session_store.cookies_from_settings(settings)
        return self.session_store.cookies_from_secret(raw_secret, allow_network=False)

    def _client_settings_update(self, client) -> SessionSettingsUpdate:
        try:
            settings = client.get_settings()
            cookies = self.session_store.cookies_from_settings(settings)
            settings["cookies"] = cookies
            settings["authorization_data"] = self.session_store.authorization_data_from_cookies(
                cookies,
                settings.get("authorization_data"),
            )
            raw_settings = json.dumps(settings, ensure_ascii=False).encode("utf-8")
            return SessionSettingsUpdate(
                raw_settings=raw_settings,
                user_agent=self._url_value(settings.get("user_agent")),
            )
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError("PROVIDER_ERROR", "Не удалось подготовить Instagram session settings") from exc

    def _infer_account_username_sync(
        self,
        secret_kind: str,
        raw_secret: bytes,
        fallback_username: str | None = None,
    ) -> str | None:
        try:
            client = self._client_from_raw_secret(secret_kind, raw_secret, fallback_username)
            account = client.account_info()
            username = getattr(account, "username", None)
            if not username:
                return None
            return self.normalize_target(username)
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _validate_account_sync(
        self,
        session_ref: AccountSessionRef,
    ) -> tuple[bool, str | None, SessionSettingsUpdate | None]:
        try:
            client = self._client_from_session_ref(session_ref)
            client.account_info()
            return True, None, self._client_settings_update(client)
        except ProviderError as exc:
            return False, exc.reason, None
        except Exception as exc:
            try:
                self._raise_mapped_error(exc)
            except ProviderError as mapped:
                return False, mapped.reason, None
            return False, "UNKNOWN_ERROR", None

    def _profile_preview_sync(
        self,
        session_ref: AccountSessionRef,
        username: str,
        limit: int,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        started_at = monotonic()
        timings = {
            "client_from_session_ms": 0.0,
            "user_info_ms": 0.0,
            "user_medias_ms": 0.0,
            "settings_update_ms": 0.0,
        }
        media_count: int | None = None
        requested_limit = max(0, int(limit or 0))
        media_limit = 0
        try:
            step_started_at = monotonic()
            try:
                client = self._client_from_session_ref(session_ref, allow_network=False)
            finally:
                timings["client_from_session_ms"] = _duration_ms(step_started_at)

            step_started_at = monotonic()
            try:
                profile = client.user_info_by_username(username, use_cache=not force_refresh)
            finally:
                timings["user_info_ms"] = _duration_ms(step_started_at)

            media_count = self._optional_int(getattr(profile, "media_count", None)) or 0
            medias = []
            if media_count > 0 and requested_limit > 0:
                media_limit = min(requested_limit, media_count)
                step_started_at = monotonic()
                try:
                    medias = client.user_medias(str(profile.pk), amount=media_limit)
                finally:
                    timings["user_medias_ms"] = _duration_ms(step_started_at)

            payload = {
                "username": profile.username,
                "full_name": profile.full_name or None,
                "bio": profile.biography or None,
                "followers_count": self._optional_int(getattr(profile, "follower_count", None)),
                "following_count": self._optional_int(getattr(profile, "following_count", None)),
                "posts_count": media_count,
                "is_private": bool(getattr(profile, "is_private", False)),
                "is_verified": bool(getattr(profile, "is_verified", False)),
                "profile_pic_url": self._url_value(
                    getattr(profile, "profile_pic_url_hd", None)
                    or getattr(profile, "profile_pic_url", None)
                ),
                "external_url": self._url_value(getattr(profile, "external_url", None)),
                "posts": [self._media_preview(media) for media in list(medias)[:media_limit]],
            }
            self._log_profile_preview_timing(
                username,
                timings,
                started_at,
                media_count=media_count,
                requested_limit=requested_limit,
                media_limit=media_limit,
                force_refresh=force_refresh,
            )
            return payload
        except ProviderError as exc:
            self._log_profile_preview_timing(
                username,
                timings,
                started_at,
                media_count=media_count,
                requested_limit=requested_limit,
                media_limit=media_limit,
                force_refresh=force_refresh,
                error_code=exc.reason,
            )
            raise
        except Exception as exc:
            try:
                self._raise_mapped_error(exc)
            except ProviderError as mapped:
                self._log_profile_preview_timing(
                    username,
                    timings,
                    started_at,
                    media_count=media_count,
                    requested_limit=requested_limit,
                    media_limit=media_limit,
                    force_refresh=force_refresh,
                    error_code=mapped.reason,
                )
                raise

    def _profile_info_sync(
        self,
        session_ref: AccountSessionRef,
        username: str,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        try:
            client = self._client_from_session_ref(session_ref, allow_network=False)
            profile = client.user_info_by_username(username, use_cache=not force_refresh)
            media_count = self._optional_int(getattr(profile, "media_count", None)) or 0
            profile_pk = getattr(profile, "pk", None)
            if profile_pk is None:
                raise ProviderError("PROVIDER_ERROR", "Instagram provider не вернул id профиля")
            return {
                "_pk": str(profile_pk),
                "username": profile.username,
                "full_name": profile.full_name or None,
                "bio": profile.biography or None,
                "followers_count": self._optional_int(getattr(profile, "follower_count", None)),
                "following_count": self._optional_int(getattr(profile, "following_count", None)),
                "posts_count": media_count,
                "is_private": bool(getattr(profile, "is_private", False)),
                "is_verified": bool(getattr(profile, "is_verified", False)),
                "profile_pic_url": self._url_value(
                    getattr(profile, "profile_pic_url_hd", None)
                    or getattr(profile, "profile_pic_url", None)
                ),
                "external_url": self._url_value(getattr(profile, "external_url", None)),
            }
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _profile_medias_index_sync(
        self,
        session_ref: AccountSessionRef,
        profile_pk: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        try:
            amount = max(0, int(limit or 0))
            if amount <= 0:
                return []
            client = self._client_from_session_ref(session_ref, allow_network=False)
            medias = client.user_medias(str(profile_pk), amount=amount)
            return [self._media_preview(media) for media in list(medias)[:amount]]
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _log_profile_preview_timing(
        self,
        username: str,
        timings: dict[str, float],
        started_at: float,
        media_count: int | None,
        requested_limit: int,
        media_limit: int,
        force_refresh: bool,
        error_code: str | None = None,
    ) -> None:
        _safe_timing_log(
            (
                "profile_preview_provider_timing provider=%s target=%s "
                "client_from_session_ms=%.2f user_info_ms=%.2f user_medias_ms=%.2f "
                "settings_update_ms=%.2f total_ms=%.2f media_count=%s requested_limit=%s "
                "media_limit=%s force_refresh=%s error_code=%s"
            ),
            self.provider_name,
            username,
            timings["client_from_session_ms"],
            timings["user_info_ms"],
            timings["user_medias_ms"],
            timings["settings_update_ms"],
            _duration_ms(started_at),
            media_count,
            requested_limit,
            media_limit,
            bool(force_refresh),
            error_code,
        )

    def _post_metadata_sync(self, session_ref: AccountSessionRef, username: str, shortcode: str) -> dict[str, Any]:
        try:
            client = self._client_from_session_ref(session_ref, allow_network=False)
            media = client.media_info(self._media_pk_from_shortcode(client, shortcode))
            payload = self._media_preview(media)
            payload["username"] = username
            payload["url"] = f"https://www.instagram.com/p/{shortcode}/"
            return payload
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _post_comments_sync(
        self,
        session_ref: AccountSessionRef,
        shortcode: str,
        comments_limit: int,
    ) -> list[dict[str, Any]]:
        try:
            client = self._client_from_session_ref(session_ref, allow_network=False)
            comments = client.media_comments(
                self._media_pk_from_shortcode(client, shortcode),
                amount=comments_limit,
            )
            return [self._comment_payload(comment) for comment in list(comments)[:comments_limit]]
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _media_pk_from_shortcode(self, client, shortcode: str):
        try:
            return client.media_pk_from_code(shortcode)
        except AttributeError as exc:
            raise ProviderError("PROVIDER_ERROR", "Instagrapi не поддерживает media_pk_from_code") from exc

    def _comment_payload(self, comment) -> dict[str, Any]:
        created_at = getattr(comment, "created_at_utc", None) or getattr(comment, "created_at", None)
        owner = getattr(comment, "user", None) or getattr(comment, "owner", None)
        return {
            "id": str(getattr(comment, "pk", None) or getattr(comment, "id", None) or ""),
            "owner": getattr(owner, "username", None),
            "text": getattr(comment, "text", None),
            "created_at": created_at.isoformat() if created_at is not None else None,
            "likes_count": self._optional_int(getattr(comment, "like_count", None)),
        }

    def _media_preview(self, media) -> dict[str, Any]:
        media_type = self._media_type(media)
        taken_at = getattr(media, "taken_at", None)
        if taken_at is not None and getattr(taken_at, "tzinfo", None) is None:
            taken_at = taken_at.replace(tzinfo=timezone.utc)
        resources = getattr(media, "resources", None) or []
        location = getattr(media, "location", None)
        caption = getattr(media, "caption_text", None)
        shortcode = getattr(media, "code", None)
        media_id = getattr(media, "id", None) or getattr(media, "pk", None)
        product_type = getattr(media, "product_type", None)
        return {
            "shortcode": shortcode,
            "id": str(media_id) if media_id is not None else shortcode,
            "type": media_type,
            "product_type": product_type if product_type else None,
            "date": taken_at.isoformat() if taken_at is not None else None,
            "likes": self._optional_int(getattr(media, "like_count", None)),
            "comments": self._optional_int(getattr(media, "comment_count", None)),
            "preview_url": self._media_thumbnail_url(media),
            "caption": caption if caption else None,
            "location": getattr(location, "name", None) if location is not None else None,
            "carousel_count": len(resources) if media_type == "carousel" else None,
            "is_video": media_type == "video",
        }

    def _media_type(self, media) -> str:
        media_type = self._optional_int(getattr(media, "media_type", None))
        if media_type == 1:
            return "photo"
        if media_type == 2:
            return "video"
        if media_type == 8:
            return "carousel"
        return "unknown"

    def _media_thumbnail_url(self, media) -> str | None:
        thumbnail = self._url_value(getattr(media, "thumbnail_url", None))
        if thumbnail:
            return thumbnail
        for resource in getattr(media, "resources", None) or []:
            thumbnail = self._url_value(getattr(resource, "thumbnail_url", None))
            if thumbnail:
                return thumbnail
        return None

    def _optional_int(self, value: Any) -> int | None:
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _url_value(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        return text or None

    def _raise_mapped_error(self, exc: Exception):
        name = type(exc).__name__
        text = str(exc)
        lower_text = text.lower()
        if "checkpoint" in lower_text or "challenge_required" in lower_text:
            raise ProviderError("CHECKPOINT_REQUIRED", "Instagram требует подтверждения входа") from exc
        if "login required" in lower_text or "not logged in" in lower_text:
            raise ProviderError("LOGIN_REQUIRED", "Instagram-сессия недействительна") from exc
        if "too many requests" in lower_text or "please wait" in lower_text or "429" in lower_text:
            raise ProviderError("RATE_LIMIT", "Временный rate limit Instagram") from exc
        if "timed out" in lower_text or "timeout" in lower_text:
            raise ProviderError("TIMEOUT", "Instagram не ответил вовремя") from exc
        if "invalid sessionid" in lower_text:
            raise ProviderError("INVALID_SESSION", "Instagram-сессия недействительна") from exc
        mapping = {
            "BadCredentials": "BAD_CREDENTIALS",
            "BadPassword": "BAD_CREDENTIALS",
            "TwoFactorRequired": "TWO_FACTOR_REQUIRED",
            "LoginRequired": "LOGIN_REQUIRED",
            "ClientLoginRequired": "LOGIN_REQUIRED",
            "ClientUnauthorizedError": "LOGIN_REQUIRED",
            "ChallengeRequired": "CHECKPOINT_REQUIRED",
            "ChallengeError": "CHECKPOINT_REQUIRED",
            "CaptchaChallengeRequired": "CHECKPOINT_REQUIRED",
            "ChallengeRedirection": "CHECKPOINT_REQUIRED",
            "ChallengeSelfieCaptcha": "CHECKPOINT_REQUIRED",
            "ChallengeUnknownStep": "CHECKPOINT_REQUIRED",
            "UserNotFound": "PROFILE_NOT_FOUND",
            "ClientNotFoundError": "PROFILE_NOT_FOUND",
            "NotFoundError": "PROFILE_NOT_FOUND",
            "PrivateAccount": "PRIVATE_PROFILE",
            "PrivateError": "PRIVATE_PROFILE",
            "PleaseWaitFewMinutes": "RATE_LIMIT",
            "RateLimitError": "RATE_LIMIT",
            "ClientThrottledError": "RATE_LIMIT",
            "ClientConnectionError": "NETWORK_ERROR",
            "ClientGraphqlError": "NETWORK_ERROR",
            "ClientJSONDecodeError": "NETWORK_ERROR",
            "ClientIncompleteReadError": "NETWORK_ERROR",
            "ClientBadRequestError": "NETWORK_ERROR",
            "ClientForbiddenError": "NETWORK_ERROR",
            "ClientUnknownError": "NETWORK_ERROR",
            "GenericRequestError": "NETWORK_ERROR",
            "ConnectionError": "NETWORK_ERROR",
            "Timeout": "TIMEOUT",
            "ReadTimeout": "TIMEOUT",
        }
        reason = mapping.get(name, "UNKNOWN_ERROR")
        raise ProviderError(reason, text) from exc


# Backward-compatible name for older internal imports.
InstagramProvider = InstagramPreviewProvider
