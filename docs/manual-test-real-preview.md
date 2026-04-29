# Manual Test: Real Preview Mode

## Backend

1. Start the stack with `docker compose up --build`.
2. Open `http://127.0.0.1:8000/api/health` and confirm `status` is `ok`.
3. Log in as local admin in the UI.
4. Add a valid Instagram account in the Accounts drawer.
5. Call `POST /api/profile/preview` from the UI and confirm the response has real `profile.posts[].shortcode` values and `preview_url` fields when Instagram provides them.
6. Confirm `/api/media/proxy?url=<encoded Instagram CDN URL>` returns image bytes for allowed Instagram/CDN URLs while rejecting `http://`, `localhost`, `127.0.0.1`, private/internal hosts, and non-allowlisted hosts.

## Frontend

1. Enter a username or Instagram profile URL and click `Загрузить профиль`.
2. In DevTools Network, confirm the page sends `POST /api/profile/preview`.
3. Confirm the grid uses real backend shortcodes and preview images through `/api/media/proxy`.
4. Disable or stop the backend and confirm the UI shows an error instead of generating a fake profile.
5. Open a post modal and confirm caption, date, shortcode, likes, comments, and type come from the backend response.
6. Switch tabs and filters; no new fake posts should appear.
7. Click `Загрузить ещё`; it should request a larger real preview limit.
8. Click `Загрузить ещё`; it must call `/api/profile/preview` with a larger limit and `force_refresh: true`.
9. Select posts and create a job; `mode: "selected"` must send real shortcodes.
10. Test `last-n` and `meta-only`; requests must send real target/mode/limit/options, and `meta-only` must send `media: false`.
11. Test invalid session, profile not found, rate limit, backend unavailable, and admin logout; the UI should show clear toast messages and no fake profile.
