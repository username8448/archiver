"""InstagramProvider на базе Instaloader."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from datetime import timezone
from pathlib import Path
from typing import Any

from providers.base import BaseProvider, ProviderError
from vault import load_secret


class InstagramProvider(BaseProvider):
    """Реальный Instagram provider; секреты читает только из encrypted vault."""

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
        instaloader = self._import_instaloader()
        if account.secret_kind != "session":
            raise ProviderError("SESSION_FILE_REQUIRED", "Для Instaloader нужен session-файл")

        raw_secret = load_secret(account.secret_id)
        loader = instaloader.Instaloader(
            sleep=True,
            download_pictures=True,
            download_videos=True,
            download_video_thumbnails=False,
            save_metadata=False,
            compress_json=False,
        )
        with tempfile.NamedTemporaryFile(prefix="archiver-session-", delete=True) as tmp:
            tmp.write(raw_secret)
            tmp.flush()
            loader.load_session_from_file(account.username, filename=tmp.name)
        return loader, instaloader

    def _validate_account_sync(self, account) -> tuple[bool, str | None]:
        if account.secret_kind == "cookies":
            raw = load_secret(account.secret_id)
            if b"sessionid" in raw or b"instagram.com" in raw:
                return True, None
            return False, "COOKIES_FORMAT_UNKNOWN"
        try:
            loader, _ = self._loader_from_account(account)
            logged_in_as = loader.test_login()
            if not logged_in_as:
                return False, "LOGIN_REQUIRED"
            return True, None
        except ProviderError as exc:
            return False, exc.reason
        except Exception as exc:
            return False, type(exc).__name__

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
                "fullname": profile.full_name,
                "biography": profile.biography,
                "followers": profile.followers,
                "following": profile.followees,
                "posts_count": profile.mediacount,
                "is_private": profile.is_private,
                "is_verified": profile.is_verified,
                "profile_pic_url": profile.profile_pic_url,
                "external_url": profile.external_url,
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
        return {
            "shortcode": post.shortcode,
            "type": self._post_type(post),
            "date": post.date_utc.replace(tzinfo=timezone.utc).isoformat(),
            "likes": post.likes,
            "comments": post.comments,
            "preview_url": post.url,
            "caption": post.caption or "",
        }

    def _post_metadata(self, post, username: str) -> dict[str, Any]:
        payload = self._post_preview(post)
        payload.update(
            {
                "username": username,
                "typename": post.typename,
                "is_video": post.is_video,
                "video_url": getattr(post, "video_url", None) if post.is_video else None,
                "url": post.url,
                "caption": post.caption or "",
                "location": getattr(getattr(post, "location", None), "name", None),
            }
        )
        return payload

    def _post_type(self, post) -> str:
        if post.typename == "GraphSidecar":
            return "carousel"
        if post.is_video:
            return "video"
        return "photo"

    def _raise_mapped_error(self, exc: Exception):
        name = type(exc).__name__
        mapping = {
            "TooManyRequestsException": "RATE_LIMIT",
            "ConnectionException": "NETWORK_ERROR",
            "LoginRequiredException": "LOGIN_REQUIRED",
            "PrivateProfileNotFollowedException": "PRIVATE_PROFILE",
            "ProfileNotExistsException": "PROFILE_NOT_FOUND",
            "BadResponseException": "NETWORK_ERROR",
        }
        reason = mapping.get(name, "UNKNOWN")
        raise ProviderError(reason, str(exc)) from exc
