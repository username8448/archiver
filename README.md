# Instagram Archiver v4

Локальный FastAPI-сервис для архивирования Instagram-профилей.

## Что реализовано

- FastAPI backend + web UI в `static/`.
- PostgreSQL вместо SQLite: профили, кэш, настройки, аккаунты, задачи и прогресс хранятся в Postgres.
- Docker Compose поднимает PostgreSQL автоматически; строку подключения в UI вводить не нужно.
- Несколько локальных администраторов: регистрация через кнопку `Инициализировать`, вход по логину/паролю, выход и вход другим admin.
- Session/cookies Instagram не хранятся в коде, `.env` или JS. Они шифруются Fernet и лежат в encrypted vault.
- `instagrapi` используется для preview/profile metadata по умолчанию; `gallery-dl`/`yt-dlp` используются для media download.

## Первый запуск

1. При необходимости создайте локальный `.env`:

```bash
cp .env.example .env
```

2. Запустите сервис:

```bash
make up
```

или напрямую:

```bash
docker compose up --build
```

3. Откройте:

```text
http://127.0.0.1:8000
```

4. В форме первого входа создайте локального администратора кнопкой `Инициализировать`.

Compose создаёт PostgreSQL database/user автоматически и хранит данные в Docker volumes:

- `postgres_data` для PostgreSQL;
- `archiver_state` для encrypted vault и архивов.

## Docker на Arch/EndeavourOS

Если Docker ещё не установлен:

```bash
sudo pacman -Syu --needed docker docker-compose docker-buildx
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

После добавления в группу `docker` нужно открыть новый терминал, выполнить `newgrp docker` или перезайти в систему.

Проверка:

```bash
docker run --rm hello-world
docker compose version
```

## Команды обслуживания

```bash
make up          # foreground запуск с build
make up-d        # background запуск с build
make down        # остановить контейнеры без удаления volumes
make restart     # пересобрать и перезапустить
make logs        # смотреть логи app и postgres
make ps          # статус контейнеров
make health      # проверить /api/health
make backup      # pg_dump в backups/
make restore RESTORE_FILE=backups/file.sql
make reset       # удалить контейнеры и volumes после ввода RESET
```

`make reset` удаляет PostgreSQL volume и encrypted vault volume. Используйте только когда действительно хотите сбросить локальные данные.

## Настройки `.env`

См. `.env.example`:

```text
POSTGRES_USER=archiver
POSTGRES_PASSWORD=archiver_pass
POSTGRES_DB=archiver
APP_PORT=8000
COOKIE_SECURE=false
INSTAGRAM_PREVIEW_PROVIDER=instagrapi
```

Для локального HTTP оставьте `COOKIE_SECURE=false`. Для HTTPS/reverse proxy можно поставить `COOKIE_SECURE=true`.
`INSTAGRAM_PREVIEW_PROVIDER=instagrapi` — основной режим preview; `instaloader` остаётся только временным legacy fallback.

## Авторизация и регистрация

На первом открытии создайте локального администратора через `Инициализировать`.

Можно создать несколько локальных администраторов через ту же форму. Переключателя между ними нет: нажмите `Выйти`, затем войдите другим логином.

Вход и регистрация имеют простой rate-limit: при частых ошибках API вернёт `429`, нужно подождать около минуты.

## Секреты аккаунтов Instagram

Через UI загрузите полный browser cookie jar или instagrapi settings JSON. Содержимое шифруется и сохраняется в Docker volume:

```text
archiver_state -> /home/app/.instagram_archiver
```

API не возвращает содержимое секрета, `secret_id`, `settings_secret_id` или реальный путь. В Postgres хранятся только username, тип session, user-agent, статус и служебные даты.

Legacy Instaloader session всё ещё можно загрузить как fallback:

```bash
instaloader --login=YOUR_USERNAME
```

Затем загрузите session-файл через drawer `Аккаунты` в web UI. При успешной проверке приложение конвертирует его в instagrapi settings в encrypted vault.

Одиночный `sessionid` можно вставить как legacy-вариант, но он менее стабилен, чем полный cookie jar:

```text
sessionid:"ВАШ_SESSIONID"
```

В этом случае выберите тип `Legacy sessionid`. Если sessionid валиден, username аккаунта определяется автоматически, поэтому поле username можно оставить пустым. Приложение не хранит пароль Instagram и не выполняет автоматический relogin по паролю.

## Healthcheck

Публичный endpoint:

```bash
curl http://127.0.0.1:8000/api/health
```

Ответ показывает только техническое состояние без секретов:

- `status`;
- `database_connected`;
- `vault_ready`;
- `version`;
- `admins_initialized`.

## Backup/restore

Создать backup PostgreSQL:

```bash
make backup
```

Восстановить backup:

```bash
make restore RESTORE_FILE=backups/archiver-YYYYMMDD-HHMMSS.sql
```

Encrypted vault хранится отдельно в Docker volume `archiver_state`. Для полного переноса окружения сохраняйте и PostgreSQL backup, и volume `archiver_state`.

## Запуск без Docker

Можно запускать приложение вручную, если PostgreSQL уже доступен:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
DATABASE_URL=postgresql://user:password@localhost:5432/archiver uvicorn app:app --reload --port 8000
```

При startup приложение применяет Alembic migrations, создаёт default settings и encrypted vault.

## Основные API

- `GET /api/health`
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/me`
- `POST /api/profile/preview`
- `POST /api/jobs/create`
- `GET /api/jobs`
- `GET /api/jobs/{job_id}/status`
- `POST /api/jobs/{job_id}/resume`
- `GET /api/jobs/{job_id}/download`
- `GET/PUT /api/settings`
- `GET /api/accounts`
- `POST /api/accounts`
- `POST /api/accounts/{id}/default`
- `POST /api/accounts/{id}/validate`
- `DELETE /api/accounts/{id}`
- `GET /api/setup/status`

## Troubleshooting

- `docker: command not found`: установите Docker по инструкции для Arch/EndeavourOS выше.
- `permission denied while trying to connect to Docker`: примените группу через `newgrp docker` или перезайдите в систему.
- `PostgreSQL ещё не готов`: дождитесь healthcheck контейнера или посмотрите `make logs`.
- `порт 8000 занят`: задайте другой порт в `.env`, например `APP_PORT=8010`.
- `Нужен вход администратора`: выйдите на экран логина, войдите или создайте admin через `Инициализировать`.

## Важные ограничения

- Одновременно разрешена только одна активная сетевая задача.
- При активной задаче новое preview разрешено только из кэша.
- Preview-запросы выполняются через instagrapi; media download в default pipeline выполняется через `gallery-dl` для фото/каруселей и `yt-dlp` для видео.
- Video/reel downloads retry transient `yt-dlp` failures up to `download_retry_attempts` total attempts; default is `2`.
- API preview нормализует `profile.posts[].type` в `photo`, `video`, `carousel` или `unknown`.
- Instagram-сессии основаны на cookie jar/settings; автоматический relogin по паролю не используется.
- Instaloader остаётся только legacy fallback для старых session-файлов и не используется default media download path.
