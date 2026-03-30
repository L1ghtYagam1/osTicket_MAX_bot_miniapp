# MAX Support Bot + Mini App for osTicket 1.18.1

Публичный проект для поддержки пользователей через:

- бот в MAX
- mini app / web interface
- backend API
- интеграцию с osTicket `1.18.1`

Проект рассчитан на сценарий, где:

- пользователь авторизуется по рабочей почте
- подтверждает почту кодом
- создаёт заявку
- видит свои заявки и их статусы
- администратор управляет пользователями и справочниками

## Возможности

### Пользователь

- подтверждение рабочей почты кодом
- создание заявки
- просмотр своих заявок
- просмотр статуса заявки

### Администратор

- просмотр пользователей
- выдача и снятие прав администратора
- отключение пользователей
- управление отелями
- управление категориями
- управление темами

### Система

- бот MAX работает через backend API
- web UI работает через backend API
- backend создаёт заявки в osTicket
- backend получает статусы заявок из тикета через отдельный endpoint

## Архитектура

```text
MAX Bot
   -> Backend API
      -> osTicket 1.18.1

Web App / Mini App
   -> Backend API
      -> osTicket 1.18.1

Admin Panel
   -> Backend API
      -> database + osTicket adapter
```

## Структура проекта

```text
backend/         FastAPI backend
webapp/          web UI / mini app
main.py          MAX bot
docker-compose.yml
Dockerfile.backend
Dockerfile.bot
requirements.txt
```

## Требования

- Python `3.12+`
- Docker и Docker Compose, если запускать в контейнерах
- osTicket `1.18.1`
- бот в MAX
- `https` для подключения mini app в MAX

## Важный момент по osTicket

Официальная документация osTicket `1.18.1` хорошо покрывает создание заявки через:

- `POST /api/tickets.json`

Для чтения актуального статуса заявки проект использует отдельный configurable endpoint:

- `OSTICKET_STATUS_API_URL`

Пример:

```env
OSTICKET_STATUS_API_URL=https://help.example.com/api/tickets/{ticket_id}.json
```

Если ваша установка osTicket возвращает другой JSON, возможно потребуется адаптировать парсер в [backend/osticket.py](/C:/Users/132/Desktop/bot/backend/osticket.py).

## Настройка `.env`

Скопируйте пример:

```bash
cp .env.example .env
```

Пример с комментариями:

```env
# =========================
# MAX BOT
# =========================

MAX_BOT_TOKEN=
MAX_API_BASE_URL=https://platform-api.max.ru
MAX_POLL_TIMEOUT=25
BACKEND_API_URL=http://backend:8000/api/v1
BACKEND_TIMEOUT=20
PUBLIC_DOMAIN=supbot.ukprovence.ru
PUBLIC_WEBAPP_URL=https://supbot.ukprovence.ru/app
PUBLIC_API_BASE_URL=https://supbot.ukprovence.ru/api/v1
MAX_WEBAPP_AUTH_MAX_AGE_SECONDS=86400
MAX_SESSION_SECRET=CHANGE_ME_TO_A_LONG_RANDOM_SECRET
MAX_SESSION_TTL_SECONDS=0


# =========================
# OSTICKET
# =========================

OSTICKET_API_URL=https://osticket.ukprovence.ru/api/tickets.json
OSTICKET_API_KEY=
OSTICKET_REQUEST_TIMEOUT=20
OSTICKET_STATUS_API_URL=https://osticket.ukprovence.ru/api/tickets/{ticket_id}.json


# =========================
# DATABASE
# =========================

DATABASE_URL=sqlite:///./data/app.db


# =========================
# ADMINS
# =========================

ADMIN_MAX_IDS=


# =========================
# CORS
# =========================

CORS_ORIGINS_RAW=*


# =========================
# EMAIL VERIFICATION
# =========================

EMAIL_VERIFICATION_TTL_MINUTES=10


# =========================
# SMTP
# =========================

SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_SENDER=
SMTP_USE_TLS=true
ALLOWED_EMAIL_DOMAINS=ukprovence.ru,hotel-a.ru,hotel-b.ru
```

## Установка через Docker

### 1. Установить Docker и Docker Compose

Linux Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y docker.io docker-compose || sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

Проверка:

```bash
docker --version
docker-compose --version || docker compose version
```

Windows:

- установите [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- после установки убедитесь, что команды `docker --version` и `docker compose version` работают в новом терминале

### 2. Установить Git

Если `git` ещё не установлен:

Linux Debian/Ubuntu:

```bash
sudo apt update
sudo apt install -y git
```

Windows:

- установите [Git for Windows](https://git-scm.com/download/win)
- после установки откройте новый терминал

### 3. Скачать репозиторий

```bash
git clone https://github.com/L1ghtYagam1/osTicket_MAX_bot_miniapp.git
cd osTicket_MAX_bot_miniapp
```

### 4. Подготовить и отредактировать `.env`

Скопируйте пример и сразу откройте файл для редактирования:

```bash
cp .env.example .env
nano .env
```

Для production с PostgreSQL можно взять за основу:

```bash
cp .env.production.example .env
nano .env
```

Windows PowerShell:

```powershell
notepad .env
```

Заполните минимум такие переменные:

```env
MAX_BOT_TOKEN=
PUBLIC_DOMAIN=supbot.ukprovence.ru
OSTICKET_API_URL=https://osticket.ukprovence.ru/api/tickets.json
OSTICKET_API_KEY=
OSTICKET_STATUS_API_URL=https://osticket.ukprovence.ru/api/tickets/{ticket_id}.json
INTERNAL_API_TOKEN=CHANGE_ME_TO_A_LONG_RANDOM_INTERNAL_TOKEN
ADMIN_MAX_IDS=
```

`MAX_BOT_TOKEN` используется не только ботом, но и backend для серверной валидации запуска mini app из MAX.
`MAX_SESSION_SECRET` используется backend для подписи web session token. В production задайте своё длинное случайное секретное значение.
`MAX_SESSION_TTL_SECONDS=0` означает бессрочную web-сессию: пользователь подтверждает рабочую почту один раз и потом не входит повторно, пока не очищен браузер, не сменён `MAX_SESSION_SECRET` или доступ не отозван вручную.
`INTERNAL_API_TOKEN` используется ботом и backend для доставки уведомлений о смене статусов. Тоже задайте длинным случайным значением.
`ALLOWED_EMAIL_DOMAINS` ограничивает подтверждение только рабочими почтами компании. Укажите один или несколько доменов через запятую, например `ukprovence.ru,hotel-a.ru,hotel-b.ru`.

Если проект запускается локально без отдельного reverse proxy, значения по умолчанию для `BACKEND_API_URL` и `DATABASE_URL` можно не менять.

### 5. Запустить проект

```bash
docker-compose up -d --build || docker compose up -d --build
```

### 6. Проверить контейнеры

```bash
docker-compose ps || docker compose ps
docker-compose logs -f || docker compose logs -f
```

У бота теперь есть собственный healthcheck по heartbeat-файлу, поэтому в `docker compose ps` контейнер `bot` тоже должен быть в состоянии `healthy`.

### 7. Открыть web UI

Если настроен домен и DNS уже указывает на сервер, Caddy сам поднимет HTTPS и web UI будет доступен по адресу:

```text
https://your-domain/app
```

Если домен ещё не настроен, можно временно проверить backend напрямую на сервере:

```text
http://YOUR_SERVER_IP:8000/api/v1/health
```

### 8. Остановить проект

```bash
docker-compose down || docker compose down
```

## Отдельный домен для mini app в MAX

Рекомендуемая схема доменов:

- `https://supbot.ukprovence.ru/app` — mini app для MAX
- `https://supbot.ukprovence.ru/api/v1` — backend API
- `https://osticket.ukprovence.ru` — отдельный домен osTicket

Минимальный пример `.env` для такой схемы:

```env
BACKEND_API_URL=http://backend:8000/api/v1
PUBLIC_DOMAIN=supbot.ukprovence.ru
PUBLIC_WEBAPP_URL=https://supbot.ukprovence.ru/app
PUBLIC_API_BASE_URL=https://supbot.ukprovence.ru/api/v1
CORS_ORIGINS_RAW=https://supbot.ukprovence.ru
OSTICKET_API_URL=https://osticket.ukprovence.ru/api/tickets.json
OSTICKET_STATUS_API_URL=https://osticket.ukprovence.ru/api/tickets/{ticket_id}.json
```

Проект уже подготовлен под Caddy. Рабочий конфиг лежит в [deploy/Caddyfile](/C:/Users/132/Desktop/bot/deploy/Caddyfile).

Как это работает:

- Caddy принимает запросы на `80/443`
- автоматически выпускает и продлевает TLS-сертификат
- проксирует весь трафик на `backend:8000`
- backend отдаёт `/app` и `/api/v1/...`

Что уже реализовано в web app:

- mini app можно отдавать с отдельного домена
- frontend работает через относительные `/api/v1/...`, поэтому домен `app` и `api` может быть один и тот же
- при открытии из MAX web app пытается подхватить пользователя из `window.WebApp`
- backend умеет валидировать `initData` mini app на стороне сервера через `MAX_BOT_TOKEN`
- после валидации backend выдаёт подписанный session token, и admin/web запросы идут уже через `Authorization: Bearer ...`

Что нужно сделать на стороне MAX:

1. Направить DNS домена на сервер.
2. Запустить проект с Caddy.
3. Убедиться, что открывается `https://ваш-домен/app`.
4. Подключить этот URL в кабинете MAX как mini app.
5. Проверить открытие `https://ваш-домен/app` внутри клиента MAX.

## Проверка после запуска

### Healthcheck backend

Откройте:

```text
https://your-domain/api/v1/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

### Backup SQLite базы

Если используется SQLite, резервную копию можно сделать так:

```bash
python scripts/backup_db.py
```

Файл будет сохранён в `data/backups/`.

### Проверка подтверждения почты

1. Откройте `http://localhost:8000/app`
2. Укажите `MAX User ID`
3. Укажите имя
4. Укажите рабочую почту
5. Нажмите `Отправить код`
6. Получите код:
   - из письма, если SMTP настроен
   - из логов backend, если SMTP не настроен
7. Подтвердите код

### Проверка создания заявки

1. Выберите отель
2. Выберите категорию
3. Выберите тему
4. Введите описание
5. Отправьте заявку

Ожидаемый результат:

- создаётся локальная запись в backend
- создаётся тикет в osTicket
- возвращается `external_id`

### Проверка статусов

Проверьте:

- список заявок в web UI
- или сценарий статуса в боте

Если статус не читается:

1. Проверьте `OSTICKET_STATUS_API_URL`
2. Проверьте raw-ответ вашего osTicket
3. При необходимости адаптируйте разбор в [backend/osticket.py](/C:/Users/132/Desktop/bot/backend/osticket.py)

## Подключение mini app в MAX

Для подключения mini app потребуется:

- опубликовать backend/web app по `https`
- создать/настроить бота в MAX
- указать URL mini app в настройках платформы MAX

Полезные ссылки:

- [MAX Bot API](https://dev.max.ru/docs-api)
- [MAX Web Apps](https://dev.max.ru/docs/webapps/introduction)

## API backend

### Auth

- `POST /api/v1/auth/request-email-code`
- `POST /api/v1/auth/verify-email-code`
- `POST /api/v1/auth/webapp-session`
- `GET /api/v1/auth/me`
- `GET /api/v1/users/by-max/{max_user_id}`

### Catalog

- `GET /api/v1/catalog`

### Tickets

- `POST /api/v1/tickets`
- `GET /api/v1/tickets?max_user_id=...`
- `GET /api/v1/tickets/{external_id}/status?max_user_id=...`

### Admin

- `GET /api/v1/admin/users`
- `PUT /api/v1/admin/users/{user_id}`
- `GET /api/v1/admin/hotels`
- `POST /api/v1/admin/hotels`
- `PUT /api/v1/admin/hotels/{hotel_id}`
- `GET /api/v1/admin/categories`
- `POST /api/v1/admin/categories`
- `PUT /api/v1/admin/categories/{category_id}`
- `GET /api/v1/admin/topics`
- `POST /api/v1/admin/topics`
- `PUT /api/v1/admin/topics/{topic_id}`
- `GET /api/v1/admin/audit-logs`

Для admin routes теперь используется:

```text
Authorization: Bearer <access_token>
```

### Internal

- `POST /api/v1/internal/ticket-status-sync`
- `POST /api/v1/internal/ticket-status-notifications/{notification_id}/sent`

Для internal routes используется header:

```text
X-Internal-Token: <INTERNAL_API_TOKEN>
```

## PostgreSQL для production

В `docker-compose.yml` уже добавлен сервис `postgres`.

Рекомендуемая production-конфигурация лежит в файле [\.env.production.example](/C:/Users/132/Desktop/bot/.env.production.example).

Ключевая строка подключения:

```env
DATABASE_URL=postgresql+psycopg://maxsupport:maxsupport@postgres:5432/maxsupport
```

## Автоуведомления о смене статуса

Если заданы:

- `OSTICKET_STATUS_API_URL`
- `INTERNAL_API_TOKEN`

то backend отслеживает изменения статусов, а бот отправляет уведомления пользователям в MAX.

Интервал задаётся переменной:

```env
TICKET_STATUS_POLL_INTERVAL_SECONDS=60
```

## Ограничения текущей версии

- статусы зависят от доступности `OSTICKET_STATUS_API_URL`
- вложения в заявки пока не реализованы
- ответы/переписка по тикету пока не реализованы в UI
- админ-аутентификация пока базовая
- mini app integration с реальными launch-данными MAX ещё нужно донастроить на стороне платформы

## Что можно улучшать дальше

- вложения
- ответы в карточке заявки
- аудит действий администратора
- более строгую авторизацию админов
- синхронизацию статусов и событий из osTicket
- адаптер под будущий osTicket `2.0`

## Источники

- [MAX Bot API](https://dev.max.ru/docs-api)
- [MAX Web Apps](https://dev.max.ru/docs/webapps/introduction)
- [osTicket API Docs](https://docs.osticket.com/en/latest/Developer%20Documentation/API%20Docs.html)
- [osTicket Tickets API](https://docs.osticket.com/en/latest/Developer%20Documentation/API/Tickets.html)
