# Manual Test: Instagram Provider Preview

## Setup

1. Start the stack with `docker compose up --build`.
2. Open `http://127.0.0.1:8000/api/health` and confirm `status` is `ok`.
3. Create or log in as a local admin.
4. Add a valid browser cookie jar or instagrapi settings JSON in the Accounts drawer.
5. Keep `INSTAGRAM_PREVIEW_PROVIDER=instagrapi` unless explicitly testing rollback provider selection.

## Provider Selection

1. Default mode should use `instagrapi`.
2. Set `INSTAGRAM_PREVIEW_PROVIDER=instaloader` only to confirm the legacy rollback path still starts.
3. Unknown provider names should fail startup with a clear configuration error.

## Profile Preview

1. Call `POST /api/profile/preview` with:

   ```json
   {
     "target": "public_username",
     "limit": 12,
     "force_refresh": true
   }
   ```

2. Confirm success response includes:
   - `ok: true`
   - `source: "fresh"`
   - `profile.username`
   - `profile.full_name`
   - `profile.bio`
   - `profile.followers_count`
   - `profile.following_count`
   - `profile.posts_count`
   - `profile.profile_pic_url`
   - `profile.posts[].shortcode`
   - `profile.posts[].type` as `photo`, `video`, `carousel`, or `unknown`
   - `profile.posts[].preview_url` or `null`

3. Confirm unavailable fields are `null`, not fake generated values.
4. Test a public profile with `posts_count: 0` and confirm the response contains `posts: []`.
5. Confirm app logs show `user_info_ms` but `user_medias_ms=0.00` for that empty profile.
6. Test a profile with 1-3 posts and confirm logs show `media_limit` no larger than `media_count`.
7. Test a larger profile with `limit: 12` and confirm logs show `media_limit=12` when `media_count >= 12`.

## Cache

1. Repeat the same request with `force_refresh: false`.
2. Confirm response may use `source: "cache"`.
3. Send `force_refresh: true` and confirm it bypasses app cache and provider logs include `force_refresh=True`.
4. Confirm an empty cache is not returned as success when `posts_count > 0`.
5. Confirm a truly empty profile is represented as `posts_count: 0` and `posts: []`.

## Errors

1. Use a missing profile and confirm `PROFILE_NOT_FOUND`.
2. Use an expired or removed Instagram session and confirm `LOGIN_REQUIRED` or `INVALID_SESSION`.
3. Trigger an Instagram checkpoint case and confirm `CHECKPOINT_REQUIRED`.
4. Use malformed cookies and confirm `COOKIES_FORMAT_UNKNOWN`.
5. During temporary upstream failures, confirm `NETWORK_ERROR`, `TIMEOUT`, or `RATE_LIMIT` is returned and the account is not permanently invalidated.
6. Import settings/cookies without a usable `sessionid` and confirm `COOKIES_FORMAT_UNKNOWN` or `SESSION_COOKIE_MISSING`.

## Logging

1. Check app logs for lines like:

   ```text
   profile_preview_start provider=instagrapi target=username limit=12 force_refresh=True
   profile_preview_provider_timing provider=instagrapi target=username client_from_session_ms=... user_info_ms=... user_medias_ms=... settings_update_ms=0.00 total_ms=...
   profile_preview_success provider=instagrapi target=username source=fresh vault_save_ms=0.00 total_ms=...
   profile_preview_failed provider=instagrapi target=username error_code=RATE_LIMIT
   ```

2. Confirm logs do not contain passwords, cookies, sessionid, encrypted secret ids, or full private media URLs.
3. Confirm repeat preview with saved `settings_secret_id` does not trigger a cookie-completion `GET https://www.instagram.com/` during preview.

## Frontend Compatibility

1. Load a profile from the UI and confirm `state.posts` contains backend shortcodes.
2. Confirm grid and modal read `preview_url`, `caption`, `date`, `likes`, `comments`, and `type` from the backend response.
3. Confirm invalid session, rate limit, admin unauthorized, and profile not found show clear UI messages.

## Download Pipeline

1. Create a selected-photo job and confirm `metadata.json` has `downloader: "gallery-dl"` and at least one `media_files` entry.
2. Create a selected-carousel job and confirm `metadata.json` has `downloader: "gallery-dl"` and multiple carousel media files when Instagram exposes them.
3. Create a selected-video or reel job and confirm `metadata.json` has `downloader: "yt-dlp"`, `download_attempts`, and at least one video file in `media_files`.
4. Create a `meta-only` job and confirm `downloader` is `null` and `media_files` is empty.
5. Force a transient yt-dlp failure if possible and confirm retry stops after the configured `download_retry_attempts`.
6. Confirm failed video downloads still expose `result_path` and `metadata_path` in job status.
7. Confirm the generated ZIP does not contain cookie files, sessionid strings, encrypted secret ids, or temporary downloader files.

## Current Limits

- This stage does not implement aggressive scraping or rate-limit bypass.
- This stage does not access private content without valid account access.
- Instaloader remains only as legacy fallback code, not the default media download path.
