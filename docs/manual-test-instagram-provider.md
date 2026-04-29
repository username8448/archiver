# Manual Test: Instagram Provider Preview

## Setup

1. Start the stack with `docker compose up --build`.
2. Open `http://127.0.0.1:8000/api/health` and confirm `status` is `ok`.
3. Create or log in as a local admin.
4. Add a valid Instagram account in the Accounts drawer.
5. Keep `INSTAGRAM_PREVIEW_PROVIDER=instaloader` unless explicitly testing provider selection.

## Provider Selection

1. Default mode should use `instaloader`.
2. Set `INSTAGRAM_PREVIEW_PROVIDER=instagrapi` only to confirm the prepared optional provider fails with a clear `PROVIDER_ERROR`; full instagrapi preview is a later stage.
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
   - `profile.posts[].type`
   - `profile.posts[].preview_url` or `null`

3. Confirm unavailable fields are `null`, not fake generated values.

## Cache

1. Repeat the same request with `force_refresh: false`.
2. Confirm response may use `source: "cache"`.
3. Send `force_refresh: true` and confirm it bypasses cache.
4. Confirm an empty cache is not returned as success when `posts_count > 0`.
5. Confirm a truly empty profile is represented as `posts_count: 0` and `posts: []`.

## Errors

1. Use a missing profile and confirm `PROFILE_NOT_FOUND`.
2. Use an expired or removed Instagram session and confirm `LOGIN_REQUIRED` or `INVALID_SESSION`.
3. Trigger an Instagram checkpoint case and confirm `CHECKPOINT_REQUIRED`.
4. Use malformed cookies and confirm `COOKIES_FORMAT_UNKNOWN`.
5. During temporary upstream failures, confirm `NETWORK_ERROR`, `TIMEOUT`, or `RATE_LIMIT` is returned and the account is not permanently invalidated.
6. Confirm `SESSION_COOKIE_MISSING` is returned when login/password flow succeeds without a usable `sessionid`.

## Logging

1. Check app logs for lines like:

   ```text
   profile_preview_failed provider=instaloader target=username error_code=RATE_LIMIT
   ```

2. Confirm logs do not contain password, cookies, sessionid, encrypted secret ids, or full private media URLs.

## Frontend Compatibility

1. Load a profile from the UI and confirm `state.posts` contains backend shortcodes.
2. Confirm grid and modal read `preview_url`, `caption`, `date`, `likes`, `comments`, and `type` from the backend response.
3. Confirm invalid session, rate limit, admin unauthorized, and profile not found show clear UI messages.

## Current Limits

- This stage does not implement aggressive scraping or rate-limit bypass.
- This stage does not download all media files.
- This stage does not access private content without valid account access.
- Full `instagrapi` preview, `gallery-dl` media downloader, and `yt-dlp` video fallback are next-stage work.
