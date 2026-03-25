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


# =========================
# OSTICKET
# =========================

OSTICKET_API_URL=https://your-osticket.example/api/tickets.json
OSTICKET_API_KEY=
OSTICKET_REQUEST_TIMEOUT=20
OSTICKET_STATUS_API_URL=


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
```

## Быстрый запуск через Docker

```bash
docker compose up -d --build
```

Логи:

```bash
docker compose logs -f
```

Остановка:

```bash
docker compose down
```

После запуска web UI будет доступен по адресу:

```text
http://localhost:8000/app
```

## Локальный запуск без Docker

### 1. Создать виртуальное окружение

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 2. Установить зависимости

```bash
pip install -r requirements.txt
```

### 3. Запустить backend

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Запустить бота

В отдельном окне:

```bash
python3 main.py
```

## Установка на Linux

Ниже пример для Debian/Ubuntu.

### 1. Установить системные пакеты

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
```

### 2. Клонировать репозиторий

```bash
git clone https://github.com/L1ghtYagam1/osTicket_MAX_bot_miniapp.git
cd osTicket_MAX_bot_miniapp
```

### 3. Создать виртуальное окружение

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Установить зависимости

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Подготовить `.env`

```bash
cp .env.example .env
nano .env
```

Минимально заполните:

```env
MAX_BOT_TOKEN=
BACKEND_API_URL=http://127.0.0.1:8000/api/v1

OSTICKET_API_URL=https://your-osticket.example/api/tickets.json
OSTICKET_API_KEY=
OSTICKET_STATUS_API_URL=

DATABASE_URL=sqlite:///./data/app.db
ADMIN_MAX_IDS=
```

### 6. Запустить backend

```bash
source .venv/bin/activate
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

### 7. Запустить бота

В отдельной сессии:

```bash
cd /path/to/osTicket_MAX_bot_miniapp
source .venv/bin/activate
python3 main.py
```

### 8. Проверить backend

```bash
curl http://127.0.0.1:8000/api/v1/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

### 9. Открыть web UI

Если сервер доступен по IP или домену:

```text
http://YOUR_SERVER_IP:8000/app
```

## Запуск через systemd на Linux

Если хотите, чтобы backend и бот стартовали автоматически после перезагрузки, можно сделать два systemd unit.

### Пример unit для backend

```ini
[Unit]
Description=MAX Support Backend
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/osTicket_MAX_bot_miniapp
EnvironmentFile=/opt/osTicket_MAX_bot_miniapp/.env
ExecStart=/opt/osTicket_MAX_bot_miniapp/.venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

### Пример unit для бота

```ini
[Unit]
Description=MAX Support Bot
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/osTicket_MAX_bot_miniapp
EnvironmentFile=/opt/osTicket_MAX_bot_miniapp/.env
ExecStart=/opt/osTicket_MAX_bot_miniapp/.venv/bin/python main.py
Restart=always

[Install]
WantedBy=multi-user.target
```

После сохранения unit-файлов:

```bash
sudo systemctl daemon-reload
sudo systemctl enable max-support-backend
sudo systemctl enable max-support-bot
sudo systemctl start max-support-backend
sudo systemctl start max-support-bot
```

Проверка:

```bash
sudo systemctl status max-support-backend
sudo systemctl status max-support-bot
```

## Проверка после запуска

### Healthcheck backend

Откройте:

```text
http://localhost:8000/api/v1/health
```

Ожидаемый ответ:

```json
{"status":"ok"}
```

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

Для admin routes используется header:

```text
X-Max-User-Id
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
