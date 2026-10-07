# SGUGiT Student Service — Production 2.1.1

Production Telegram-бот для студентов СГУГиТ: персональное расписание по группе, задания, приглашения, уведомления, кабинет старосты и owner-модерация.

## Архитектура

- `core.py` — конфигурация, SQLite, парсер расписания, форматирование и общие UI-инструменты.
- `services.py` — доменная логика профилей, групп, рефералов, заданий, спонсора, модерации и уведомлений.
- `handlers.py` — единственный набор Telegram handlers/callbacks.
- `web.py` — HTTPS sponsor redirect и health endpoint.
- `main.py` — единственная точка запуска.

Единая production-точка запуска и единый callback-диспетчер; дублирующие обработчики и старый router удалены.

## Критические сценарии

### Спонсор
1. Telegram открывает подписанный HTTPS `/sponsor/click`.
2. Сервер проверяет HMAC и срок действия.
3. Доступ `sponsor_ok=1` фиксируется атомарно.
4. Текущий UI-сообщение переключается на главное меню.
5. HTTP 302 открывает `SPONSOR_URL`.

### Приглашение
У каждого пользователя свой подписанный deep-link `?start=ref_<id>_<signature>`. Первоначальный inviter сохраняется один раз. Кнопка «Поделиться» использует официальный Telegram share URL.

### Задания
Состояние добавления хранится только в текущей Telegram-сессии и очищается при отмене/сохранении. Пользователь может менять статус и удалять только собственные задания. Групповые задания выдаются только при совпадении группы и `shared=1`.

## Запуск

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python src/sgugit_bot/main.py
```

Windows PowerShell: `py -3.12 src\sgugit_bot\main.py`.

Health: `/health`.

## Docker

```bash
docker build -t sgugit-student-service .
docker run --env-file .env -p 8080:8080 -v "$PWD/data:/app/data" sgugit-student-service
```

## Render

Загрузить репозиторий в GitHub и создать Blueprint из `render.yaml`. Для sponsor redirect нужен публичный HTTPS URL; на Render используется `RENDER_EXTERNAL_URL` автоматически, если `PUBLIC_BASE_URL` не задан.

Обязательные переменные: `BOT_TOKEN`, `OWNER_ID`.

`SPONSOR_URL`, `SPONSOR_TRACKING_SECRET` и `LEADER_IDS` в `.env` не нужны: владелец настраивает их из панели бота, а значения хранятся в SQLite.

## 2.1.1 — runtime hardening and release audit

- Owner panel is available through `/panel` and directly from the owner's main menu.
- Owner can broadcast to all active users or a selected group.
- Owner can mute/unmute users, move users between groups, remove group membership, appoint/revoke leaders, and open any group's leader cabinet.
- Leader cabinet buttons are fully wired: schedule, announcements, polls, students, invitations and schedule edits.
- Schedule edits support add/replace/delete and are stored **per group**, so one group's override cannot leak into another group.
- Weekly Excel report is sent to `OWNER_ID` automatically on Monday at/after 09:00 (restart-safe) and can also be generated manually.
- Added regression tests for the owner/leader control surface and group-scoped schedule overrides.



### Runtime hardening

- Direct `main.py` startup is supported on Windows and Linux.
- SQLite parent directories are created automatically.
- `.env` is loaded from the project root.
- Background workers are attached to the active event loop and cancelled cleanly on shutdown.
- The text router never recursively calls `/start`.
- Render and Docker start the same direct `main.py` entrypoint.
- Weekly Excel generation is smoke-tested against a fresh SQLite database.

## Bothost

Для Bothost используйте приложенный `Dockerfile`. Проект работает на `python-telegram-bot==21.10`; `aiogram` проекту не нужен.
Не используйте старый Dockerfile, который устанавливает `aiogram==2.25.2`.
Подробная инструкция: `BOTHOST.md`.
