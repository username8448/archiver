"""Instagram preview/download providers.

Основной рабочий provider сейчас основан на Instaloader. Контракт preview
специально держится стабильным для frontend Real API Mode: без fake media и
без случайно сгенерированных metadata.
"""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from datetime import timezone
from http.cookiejar import MozillaCookieJar
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from providers.base import BaseProvider, ProviderError
from vault import load_secret


class InstaloaderProvider(BaseProvider):
    """Реальный Instagram provider на Instaloader; секреты читает только из encrypted vault."""

    provider_name = "instaloader"

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
        return await asyncio.to_thread(self._validate_account_sync, account)

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

    async def login_with_password(
        self,
        username: str,
        password: str,
        two_factor_code: str | None = None,
    ) -> tuple[str, bytes]:
        return await asyncio.to_thread(
            self._login_with_password_sync,
            username,
            password,
            two_factor_code,
        )

    async def profile_preview(self, account, username: str, limit: int) -> dict[str, Any]:
        return await asyncio.to_thread(self._profile_preview_sync, account, username, limit)

    async def download_post(
        self,
        account,
        username: str,
        shortcode: str,
        target_dir: Path,
        include_media: bool,
        include_comments: bool,
        comments_limit: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        return await asyncio.to_thread(
            self._download_post_sync,
            account,
            username,
            shortcode,
            target_dir,
            include_media,
            include_comments,
            comments_limit,
        )

    def _import_instaloader(self):
        try:
            import instaloader
        except ImportError as exc:
            raise ProviderError("INSTALOADER_NOT_INSTALLED", "Instaloader не установлен") from exc
        return instaloader

    def _loader_from_account(self, account):
        raw_secret = load_secret(account.secret_id)
        return self._loader_from_raw_secret(account.secret_kind, raw_secret, account.username)

    def _new_loader(self, instaloader):
        return (
            instaloader.Instaloader(
                sleep=True,
                quiet=True,
                download_pictures=True,
                download_videos=True,
                download_video_thumbnails=False,
                save_metadata=False,
                compress_json=False,
                max_connection_attempts=1,
                request_timeout=30.0,
                iphone_support=False,
            ),
            instaloader,
        )

    def _loader_from_raw_secret(self, secret_kind: str, raw_secret: bytes, username: str):
        instaloader = self._import_instaloader()
        loader, instaloader = self._new_loader(instaloader)

        if secret_kind == "sessionid":
            secret_kind = "cookies"

        if secret_kind == "cookies":
            cookies = self._cookies_from_secret(raw_secret)
            loader.load_session(username, cookies)
            return loader, instaloader

        if secret_kind != "session":
            raise ProviderError("SESSION_FILE_REQUIRED", "Для Instaloader нужен session-файл")

        with tempfile.NamedTemporaryFile(prefix="archiver-session-", delete=True) as tmp:
            tmp.write(raw_secret)
            tmp.flush()
            loader.load_session_from_file(username, filename=tmp.name)
        return loader, instaloader

    def _infer_account_username_sync(
        self,
        secret_kind: str,
        raw_secret: bytes,
        fallback_username: str | None = None,
    ) -> str | None:
        try:
            username = fallback_username or "instagram"
            loader, _ = self._loader_from_raw_secret(secret_kind, raw_secret, username)
            logged_in_as = loader.test_login()
            if not logged_in_as:
                return None
            return self.normalize_target(logged_in_as)
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _login_with_password_sync(
        self,
        username: str,
        password: str,
        two_factor_code: str | None = None,
    ) -> tuple[str, bytes]:
        instaloader = self._import_instaloader()
        username = self.normalize_target(username)
        loader, _ = self._new_loader(instaloader)
        try:
            loader.login(username, password)
        except instaloader.TwoFactorAuthRequiredException as exc:
            if not two_factor_code:
                raise ProviderError("TWO_FACTOR_REQUIRED", "Введите 2FA-код Instagram и повторите вход") from exc
            try:
                loader.two_factor_login(two_factor_code.strip())
            except Exception as two_factor_exc:
                self._raise_mapped_error(two_factor_exc)
        except Exception as exc:
            self._raise_mapped_error(exc)

        cookies = loader.save_session()
        self._complete_instagram_cookies(cookies)
        if not cookies.get("sessionid"):
            raise ProviderError(
                "SESSION_COOKIE_MISSING",
                "Instagram принял запрос, но не выдал sessionid. Подтвердите вход в Instagram, подождите несколько минут и повторите.",
            )
        return username, json.dumps(cookies, ensure_ascii=False).encode("utf-8")

    def _validate_account_sync(self, account) -> tuple[bool, str | None]:
        try:
            loader, _ = self._loader_from_account(account)
            logged_in_as = loader.test_login()
            if not logged_in_as:
                return False, "LOGIN_REQUIRED"
            return True, None
        except ProviderError as exc:
            return False, exc.reason
        except Exception as exc:
            try:
                self._raise_mapped_error(exc)
            except ProviderError as mapped:
                return False, mapped.reason
            return False, "UNKNOWN_ERROR"

    def _profile_preview_sync(self, account, username: str, limit: int) -> dict[str, Any]:
        try:
            loader, instaloader = self._loader_from_account(account)
            profile = instaloader.Profile.from_username(loader.context, username)
            posts = []
            for index, post in enumerate(profile.get_posts()):
                if index >= limit:
                    break
                posts.append(self._post_preview(post))
            return {
                "username": profile.username,
                "full_name": profile.full_name or None,
                "bio": profile.biography or None,
                "followers_count": self._optional_int(getattr(profile, "followers", None)),
                "following_count": self._optional_int(getattr(profile, "followees", None)),
                "posts_count": self._optional_int(getattr(profile, "mediacount", None)) or 0,
                "is_private": bool(getattr(profile, "is_private", False)),
                "is_verified": bool(getattr(profile, "is_verified", False)),
                "profile_pic_url": getattr(profile, "profile_pic_url", None) or None,
                "external_url": getattr(profile, "external_url", None) or None,
                "posts": posts,
            }
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _download_post_sync(
        self,
        account,
        username: str,
        shortcode: str,
        target_dir: Path,
        include_media: bool,
        include_comments: bool,
        comments_limit: int,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        try:
            loader, instaloader = self._loader_from_account(account)
            post = instaloader.Post.from_shortcode(loader.context, shortcode)
            target_dir.mkdir(parents=True, exist_ok=True)
            metadata = self._post_metadata(post, username)

            if include_media:
                loader.download_post(post, target=str(target_dir))

            comments = []
            if include_comments:
                for index, comment in enumerate(post.get_comments()):
                    if index >= comments_limit:
                        break
                    comments.append(
                        {
                            "id": str(comment.id),
                            "owner": getattr(comment.owner, "username", None),
                            "text": comment.text,
                            "created_at": comment.created_at_utc.isoformat(),
                            "likes_count": comment.likes_count,
                        }
                    )

            (target_dir / "metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if include_comments:
                (target_dir / "comments.json").write_text(
                    json.dumps(comments, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            return metadata, comments
        except ProviderError:
            raise
        except Exception as exc:
            self._raise_mapped_error(exc)

    def _post_preview(self, post) -> dict[str, Any]:
        shortcode = getattr(post, "shortcode", None)
        date_utc = getattr(post, "date_utc", None) or getattr(post, "date", None)
        if date_utc is not None and getattr(date_utc, "tzinfo", None) is None:
            date_utc = date_utc.replace(tzinfo=timezone.utc)
        media_id = getattr(post, "mediaid", None) or getattr(post, "id", None)
        caption = getattr(post, "caption", None)
        return {
            "shortcode": shortcode,
            "id": str(media_id) if media_id is not None else shortcode,
            "type": self._post_type(post),
            "date": date_utc.isoformat() if date_utc is not None else None,
            "likes": self._optional_int(getattr(post, "likes", None)),
            "comments": self._optional_int(getattr(post, "comments", None)),
            "preview_url": getattr(post, "url", None),
            "caption": caption if caption else None,
            "is_video": bool(getattr(post, "is_video", False)),
        }

    def _post_metadata(self, post, username: str) -> dict[str, Any]:
        payload = self._post_preview(post)
        payload.update(
            {
                "username": username,
                "typename": getattr(post, "typename", None),
                "is_video": bool(getattr(post, "is_video", False)),
                "video_url": getattr(post, "video_url", None) if bool(getattr(post, "is_video", False)) else None,
                "url": getattr(post, "url", None),
                "caption": getattr(post, "caption", None),
                "location": getattr(getattr(post, "location", None), "name", None),
            }
        )
        return payload

    def _post_type(self, post) -> str:
        typename = getattr(post, "typename", None)
        if typename == "GraphSidecar":
            return "carousel"
        if bool(getattr(post, "is_video", False)):
            return "video"
        if typename == "GraphImage":
            return "image"
        return "unknown"

    def _optional_int(self, value: Any) -> int | None:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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
        mapping = {
            "BadCredentialsException": "BAD_CREDENTIALS",
            "InvalidArgumentException": "BAD_CREDENTIALS",
            "LoginException": "LOGIN_FAILED",
            "TwoFactorAuthRequiredException": "TWO_FACTOR_REQUIRED",
            "TooManyRequestsException": "RATE_LIMIT",
            "ConnectionException": "NETWORK_ERROR",
            "LoginRequiredException": "LOGIN_REQUIRED",
            "PrivateProfileNotFollowedException": "PRIVATE_PROFILE",
            "ProfileNotExistsException": "PROFILE_NOT_FOUND",
            "BadResponseException": "NETWORK_ERROR",
            "QueryReturnedBadRequestException": "NETWORK_ERROR",
        }
        reason = mapping.get(name, "UNKNOWN_ERROR")
        raise ProviderError(reason, text) from exc

    def _cookies_from_secret(self, raw_secret: bytes) -> dict[str, str]:
        text = raw_secret.decode("utf-8", errors="ignore").strip()
        cookies = (
            self._cookies_from_sessionid_label(text)
            or self._cookies_from_json(text)
            or self._cookies_from_netscape(text)
            or self._cookies_from_pairs(text)
        )
        if not cookies:
            raise ProviderError(
                "COOKIES_FORMAT_UNKNOWN",
                "Cookies-файл должен содержать sessionid. Лучше загрузить Instaloader session-файл.",
            )
        sessionid = cookies.get("sessionid")
        if not sessionid:
            raise ProviderError(
                "COOKIES_FORMAT_UNKNOWN",
                "Cookies-файл должен содержать sessionid. Лучше загрузить Instaloader session-файл.",
            )
        self._complete_instagram_cookies(cookies)
        cookies.setdefault("csrftoken", "")
        return cookies

    def _complete_instagram_cookies(self, cookies: dict[str, str]) -> None:
        sessionid = cookies.get("sessionid")
        if not sessionid:
            return

        decoded_sessionid = unquote(sessionid)
        user_id = decoded_sessionid.split(":", 1)[0]
        if user_id.isdigit():
            cookies.setdefault("ds_user_id", user_id)

        if cookies.get("csrftoken") and cookies.get("mid"):
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

    def _cookies_from_sessionid_label(self, text: str) -> dict[str, str] | None:
        match = re.search(r"sessionid\s*[:=]\s*[\"']?([^\"';\s]+)", text, flags=re.IGNORECASE)
        if not match:
            return None
        return {"sessionid": match.group(1).strip()}

    def _cookies_from_json(self, text: str) -> dict[str, str] | None:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        cookies: dict[str, str] = {}
        if isinstance(data, dict):
            if isinstance(data.get("cookies"), list):
                data = data["cookies"]
            else:
                for key, value in data.items():
                    if isinstance(value, str):
                        cookies[key] = value
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

    def _cookies_from_netscape(self, text: str) -> dict[str, str] | None:
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

    def _cookies_from_pairs(self, text: str) -> dict[str, str] | None:
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
        if cookies:
            return cookies
        if text and re.fullmatch(r"[A-Za-z0-9%:_\\-\\.]+", text):
            return {"sessionid": text}
        return None


class InstagrapiPreviewProvider(InstaloaderProvider):
    """Подготовленная точка расширения для будущего instagrapi preview provider.

    Массовую загрузку media и скрытые повторные авторизации этот этап не
    добавляет. Если provider выбран через env до реализации, API вернёт
    понятную ошибку вместо тихого fallback на mock/другой источник.
    """

    provider_name = "instagrapi"

    async def profile_preview(self, account, username: str, limit: int) -> dict[str, Any]:
        try:
            import instagrapi  # noqa: F401
        except ImportError as exc:
            raise ProviderError(
                "PROVIDER_ERROR",
                "Instagrapi preview provider подготовлен, но пакет instagrapi не установлен.",
            ) from exc
        raise ProviderError(
            "PROVIDER_ERROR",
            "Instagrapi preview provider подготовлен, но реализация будет добавлена на следующем этапе.",
        )


# Backward-compatible имя для существующих imports.
InstagramProvider = InstaloaderProvider
