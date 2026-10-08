# SGUGiT Student Service — Bothost deployment

## Важно
Этот проект использует `python-telegram-bot`, а НЕ `aiogram`.
Не добавляйте в Dockerfile или requirements.txt `aiogram==2.25.2`.
Именно из-за такого старого Dockerfile возникает ошибка сборки `aiohttp ... No such file or directory: gcc`.

## Как развернуть на Bothost

1. Загрузите содержимое этого архива в проект.
2. В Bothost выберите **Dockerfile / использовать собственный Dockerfile**.
3. Не используйте старый Dockerfile с командой:
   `uv pip install ... aiogram==2.25.2`
4. Задайте переменные окружения:

```text
BOT_TOKEN=ваш_новый_токен
OWNER_ID=1174432700
PUBLIC_BASE_URL=
DB_PATH=/app/data/sgugit.sqlite3
SCHEDULE_URL=https://sgugit.ru/raspisanie/
```

`SPONSOR_URL`, `SPONSOR_TRACKING_SECRET` и `LEADER_IDS` в env не нужны — они управляются владельцем из бота и сохраняются в SQLite.

5. Для SQLite нужен постоянный storage/volume для `/app/data`, если такой параметр доступен в вашем тарифе. Иначе база будет потеряна при пересоздании контейнера.
6. Запуск уже прописан в Dockerfile:

```text
python src/sgugit_bot/main.py
```

## Что не нужно устанавливать вручную

- aiogram
- aiohttp
- gcc
- uv
- отдельный web-сервер

`python-telegram-bot` ставится из готовых wheels, а FastAPI/uvicorn запускают встроенный `/health` сервер.

## Health

`GET /health` возвращает:

```json
{"status":"ok"}
```

Контейнер слушает `0.0.0.0:8080` по умолчанию. Если Bothost передаст свой `PORT`, приложение использует его.

## После деплоя

В логах должен появиться запуск Telegram polling. В логах НЕ должно быть:

- `aiogram==2.25.2`
- `building 'aiohttp...` 
- `gcc: No such file or directory`

Если эти строки снова появляются, Bothost собирает не этот Dockerfile.

## Безопасность

Не помещайте Telegram token в Dockerfile, Git и README. Если старый токен уже публиковался/попадал в логи, его нужно заменить через BotFather.


## Build dependency note
This release uses Python stdlib HTML parsing and does not require `beautifulsoup4`/`bs4`. The Dockerfile performs an import preflight during image build. Do not use any external/legacy Dockerfile that installs `aiogram==2.25.2`. If the hosting panel offers a build cache, rebuild without cache after replacing the project.
