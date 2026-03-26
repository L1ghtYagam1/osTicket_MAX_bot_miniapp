import contextlib
import asyncio
import json
import logging
import os
import re
from pathlib import Path
from time import time
from typing import Any, Optional

import aiohttp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


MAX_API_BASE_URL = os.getenv("MAX_API_BASE_URL", "https://platform-api.max.ru").strip()
MAX_BOT_TOKEN = os.getenv("MAX_BOT_TOKEN", "").strip()
MAX_POLL_TIMEOUT = int(os.getenv("MAX_POLL_TIMEOUT", "25"))

BACKEND_API_URL = os.getenv("BACKEND_API_URL", "http://backend:8000/api/v1").strip().rstrip("/")
BACKEND_TIMEOUT = int(os.getenv("BACKEND_TIMEOUT", "20"))
PUBLIC_WEBAPP_URL = os.getenv("PUBLIC_WEBAPP_URL", "").strip()
INTERNAL_API_TOKEN = os.getenv("INTERNAL_API_TOKEN", "").strip()
TICKET_STATUS_POLL_INTERVAL_SECONDS = int(os.getenv("TICKET_STATUS_POLL_INTERVAL_SECONDS", "60"))
ADMIN_IDS = {item.strip() for item in os.getenv("ADMIN_MAX_IDS", "").split(",") if item.strip()}

DATA_DIR = Path(__file__).resolve().parent / "data"
STATE_DATA_FILE = DATA_DIR / "conversation_state.json"
BOT_HEARTBEAT_FILE = DATA_DIR / "bot_heartbeat.json"

STATE_IDLE = "idle"
STATE_WAITING_EMAIL = "waiting_email"
STATE_WAITING_EMAIL_CODE = "waiting_email_code"
STATE_WAITING_HOTEL = "waiting_hotel"
STATE_WAITING_CATEGORY = "waiting_category"
STATE_WAITING_TOPIC = "waiting_topic"
STATE_WAITING_DESCRIPTION = "waiting_description"
STATE_WAITING_ADMIN_BROADCAST = "waiting_admin_broadcast"
STATE_WAITING_STATUS_TICKET_ID = "waiting_status_ticket_id"

ACTION_CREATE_TICKET = "create_ticket"
ACTION_ADMIN_BROADCAST = "admin_broadcast"
ACTION_NEW_REQUEST = "new_request"
ACTION_CANCEL_REQUEST = "cancel_request"
ACTION_BACK_HOTEL = "back_hotel"
ACTION_BACK_CATEGORY = "back_category"
ACTION_BACK_TOPIC = "back_topic"
ACTION_MY_TICKETS = "my_tickets"
ACTION_CHECK_STATUS = "check_status"
ACTION_OPEN_APP = "open_app"

CONVERSATION_STATE: dict[str, dict[str, Any]] = {}


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logging.exception("Не удалось прочитать %s", path)
        return default


def save_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_data_dir()
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def touch_heartbeat() -> None:
    save_json(
        BOT_HEARTBEAT_FILE,
        {
            "updated_at": int(time()),
            "status": "ok",
        },
    )


def load_state() -> None:
    global CONVERSATION_STATE
    CONVERSATION_STATE = load_json(STATE_DATA_FILE, {})


def save_state() -> None:
    save_json(STATE_DATA_FILE, CONVERSATION_STATE)


def get_session(user_id: str) -> dict[str, Any]:
    return CONVERSATION_STATE.setdefault(user_id, {"state": STATE_IDLE, "form": {}})


def set_state(user_id: str, state: str) -> None:
    get_session(user_id)["state"] = state
    save_state()


def reset_form(user_id: str) -> None:
    session = get_session(user_id)
    session["form"] = {}
    save_state()


def build_buttons(options: list[tuple[str, str]]) -> list[list[dict[str, str]]]:
    rows: list[list[dict[str, str]]] = []
    row: list[dict[str, str]] = []
    for index, (text, payload) in enumerate(options, start=1):
        row.append({"type": "callback", "text": text, "payload": payload})
        if index % 2 == 0:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def make_payload(action: str, value: Optional[str] = None) -> str:
    return json.dumps({"action": action, "value": value}, ensure_ascii=False)


def parse_payload(raw_payload: Any) -> dict[str, Any]:
    if isinstance(raw_payload, dict):
        return raw_payload
    if isinstance(raw_payload, str):
        try:
            return json.loads(raw_payload)
        except json.JSONDecodeError:
            return {"action": raw_payload}
    return {}


def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", email))


def extract_sender(update: dict[str, Any]) -> tuple[Optional[str], Optional[str], str]:
    message = update.get("message") or {}
    callback = update.get("callback") or {}
    source = callback or message or update
    sender = source.get("sender") or source.get("user") or {}
    recipient = source.get("recipient") or {}

    user_id = sender.get("user_id") or sender.get("id") or source.get("user_id") or update.get("user_id")
    chat_id = recipient.get("chat_id") or source.get("chat_id") or update.get("chat_id") or user_id
    full_name = sender.get("name") or sender.get("full_name") or source.get("user_name") or "Пользователь MAX"
    return str(user_id) if user_id is not None else None, str(chat_id) if chat_id is not None else None, str(full_name)


def extract_text(update: dict[str, Any]) -> str:
    message = update.get("message") or {}
    body = message.get("body")
    if isinstance(body, dict):
        return (body.get("text") or body.get("value") or "").strip()
    return (message.get("text") or update.get("text") or "").strip()


def extract_callback_data(update: dict[str, Any]) -> tuple[dict[str, Any], Optional[str]]:
    callback = update.get("callback") or {}
    payload = parse_payload(callback.get("payload"))
    callback_id = callback.get("callback_id") or update.get("callback_id")
    return payload, callback_id


def parse_int(value: Any) -> Optional[int]:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def find_catalog_item(items: list[dict[str, Any]], item_id: int) -> Optional[dict[str, Any]]:
    return next((item for item in items if item["id"] == item_id), None)


class BackendClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=BACKEND_TIMEOUT))

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> Any:
        if not self.session:
            raise RuntimeError("Backend session is not initialized")
        async with self.session.request(
            method,
            f"{self.base_url}{path}",
            params=params,
            json=json_body,
            headers=headers,
        ) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"Backend error {response.status}: {text}")
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}

    async def request_email_code(self, *, max_user_id: str, full_name: str, email: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/auth/request-email-code",
            json_body={"max_user_id": max_user_id, "full_name": full_name, "email": email},
        )

    async def verify_email_code(self, *, max_user_id: str, full_name: str, email: str, code: str) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/auth/verify-email-code",
            json_body={"max_user_id": max_user_id, "full_name": full_name, "email": email, "code": code},
        )

    async def get_user(self, max_user_id: str) -> Optional[dict[str, Any]]:
        try:
            return await self.request("GET", f"/users/by-max/{max_user_id}")
        except RuntimeError as exc:
            if "Backend error 404:" in str(exc):
                return None
            raise

    async def get_catalog(self) -> dict[str, Any]:
        return await self.request("GET", "/catalog")

    async def create_ticket(
        self,
        *,
        max_user_id: str,
        hotel_id: int,
        category_id: int,
        topic_id: int,
        description: str,
    ) -> dict[str, Any]:
        return await self.request(
            "POST",
            "/tickets",
            json_body={
                "max_user_id": max_user_id,
                "hotel_id": hotel_id,
                "category_id": category_id,
                "topic_id": topic_id,
                "description": description,
            },
        )

    async def list_tickets(self, max_user_id: str) -> list[dict[str, Any]]:
        return await self.request("GET", "/tickets", params={"max_user_id": max_user_id})

    async def get_ticket_status(self, max_user_id: str, external_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/tickets/{external_id}/status", params={"max_user_id": max_user_id})

    async def list_users(self, admin_max_user_id: str) -> list[dict[str, Any]]:
        return await self.request("GET", "/admin/users", headers={"X-Max-User-Id": admin_max_user_id})

    async def sync_status_notifications(self) -> list[dict[str, Any]]:
        if not INTERNAL_API_TOKEN:
            return []
        return await self.request(
            "POST",
            "/internal/ticket-status-sync",
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )

    async def mark_status_notification_sent(self, notification_id: int) -> None:
        if not INTERNAL_API_TOKEN:
            return
        await self.request(
            "POST",
            f"/internal/ticket-status-notifications/{notification_id}/sent",
            headers={"X-Internal-Token": INTERNAL_API_TOKEN},
        )


class MaxBotClient:
    def __init__(self, token: str, base_url: str) -> None:
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.session: Optional[aiohttp.ClientSession] = None
        self.marker: Optional[str] = None

    async def start(self) -> None:
        self.session = aiohttp.ClientSession(headers={"Authorization": self.token, "Content-Type": "application/json"})
        me = await self.request("GET", "/me")
        logging.info("MAX bot started: %s", me.get("name") or me.get("user_id") or "unknown")

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json_body: Optional[dict[str, Any]] = None,
    ) -> Any:
        if not self.session:
            raise RuntimeError("MAX session is not initialized")
        async with self.session.request(method, f"{self.base_url}{path}", params=params, json=json_body) as response:
            text = await response.text()
            if response.status >= 400:
                raise RuntimeError(f"MAX API error {response.status}: {text}")
            if not text:
                return {}
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}

    async def get_updates(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": MAX_POLL_TIMEOUT}
        if self.marker:
            params["marker"] = self.marker
        response = await self.request("GET", "/updates", params=params)
        self.marker = response.get("marker", self.marker)
        return response.get("updates", [])

    async def send_message(
        self,
        chat_id: Optional[str],
        text: str,
        *,
        buttons: Optional[list[list[dict[str, str]]]] = None,
        user_id: Optional[str] = None,
    ) -> None:
        payload: dict[str, Any] = {"text": text}
        params: dict[str, Any] = {}
        if user_id:
            params["user_id"] = user_id
        elif chat_id:
            params["chat_id"] = chat_id
        if buttons:
            payload["attachments"] = [{"type": "inline_keyboard", "payload": {"buttons": buttons}}]

        try:
            await self.request("POST", "/messages", params=params, json_body=payload)
        except RuntimeError as exc:
            if chat_id and user_id and "chat.not.found" in str(exc):
                await self.request("POST", "/messages", params={"user_id": user_id}, json_body=payload)
                return
            raise

    async def answer_callback(self, callback_id: Optional[str]) -> None:
        if not callback_id:
            return
        try:
            await self.request("POST", "/answers", params={"callback_id": callback_id}, json_body={"notification": "Принято"})
        except Exception:
            logging.exception("Не удалось подтвердить callback %s", callback_id)


async def show_main_menu(max_client: MaxBotClient, chat_id: str, user_id: str) -> None:
    options = [
        ("Создать заявку", make_payload(ACTION_CREATE_TICKET)),
        ("Мои заявки", make_payload(ACTION_MY_TICKETS)),
        ("Статус заявки", make_payload(ACTION_CHECK_STATUS)),
    ]
    if PUBLIC_WEBAPP_URL:
        options.append(("Открыть приложение", make_payload(ACTION_OPEN_APP)))
    if user_id in ADMIN_IDS:
        options.append(("Отправить сообщение всем", make_payload(ACTION_ADMIN_BROADCAST)))
    await max_client.send_message(chat_id, "Выберите действие:", buttons=build_buttons(options), user_id=user_id)


async def ask_for_email(max_client: MaxBotClient, chat_id: str, user_id: str) -> None:
    await max_client.send_message(chat_id, "Введите рабочую почту.", user_id=user_id)
    set_state(user_id, STATE_WAITING_EMAIL)


async def ask_for_email_code(max_client: MaxBotClient, chat_id: str, user_id: str) -> None:
    await max_client.send_message(chat_id, "Введите код из письма.", user_id=user_id)
    set_state(user_id, STATE_WAITING_EMAIL_CODE)


async def ask_for_hotel(max_client: MaxBotClient, backend: BackendClient, chat_id: str, user_id: str) -> None:
    reset_form(user_id)
    catalog = await backend.get_catalog()
    hotels = [hotel for hotel in catalog["hotels"] if hotel["is_active"]]
    buttons = build_buttons([(hotel["name"], make_payload("hotel", str(hotel["id"]))) for hotel in hotels])
    await max_client.send_message(chat_id, "Выберите отель:", buttons=buttons, user_id=user_id)
    set_state(user_id, STATE_WAITING_HOTEL)


async def ask_for_category(max_client: MaxBotClient, backend: BackendClient, chat_id: str, user_id: str) -> None:
    catalog = await backend.get_catalog()
    categories = [item for item in catalog["categories"] if item["is_active"]]
    buttons = build_buttons([(item["name"], make_payload("category", str(item["id"]))) for item in categories])
    buttons.append([{"type": "callback", "text": "Назад", "payload": make_payload(ACTION_BACK_HOTEL)}])
    await max_client.send_message(chat_id, "Выберите категорию:", buttons=buttons, user_id=user_id)
    set_state(user_id, STATE_WAITING_CATEGORY)


async def ask_for_topic(max_client: MaxBotClient, backend: BackendClient, chat_id: str, user_id: str) -> None:
    session = get_session(user_id)
    category_id = session["form"].get("category_id")
    catalog = await backend.get_catalog()
    category = find_catalog_item(catalog["categories"], category_id)
    if not category:
        await max_client.send_message(chat_id, "Категория не найдена. Начните заново.", user_id=user_id)
        await ask_for_hotel(max_client, backend, chat_id, user_id)
        return
    topics = [item for item in category["topics"] if item["is_active"]]
    buttons = build_buttons([(item["name"], make_payload("topic", str(item["id"]))) for item in topics])
    buttons.append([{"type": "callback", "text": "Назад", "payload": make_payload(ACTION_BACK_CATEGORY)}])
    await max_client.send_message(chat_id, "Выберите тему:", buttons=buttons, user_id=user_id)
    set_state(user_id, STATE_WAITING_TOPIC)


async def ask_for_description(max_client: MaxBotClient, chat_id: str, user_id: str) -> None:
    buttons = [[
        {"type": "callback", "text": "Назад", "payload": make_payload(ACTION_BACK_TOPIC)},
        {"type": "callback", "text": "Отмена", "payload": make_payload(ACTION_CANCEL_REQUEST)},
    ]]
    await max_client.send_message(chat_id, "Введите текст вашей заявки:", buttons=buttons, user_id=user_id)
    set_state(user_id, STATE_WAITING_DESCRIPTION)


async def ask_for_status_ticket(max_client: MaxBotClient, chat_id: str, user_id: str) -> None:
    await max_client.send_message(chat_id, "Введите ID заявки.", user_id=user_id)
    set_state(user_id, STATE_WAITING_STATUS_TICKET_ID)


async def show_user_tickets(max_client: MaxBotClient, backend: BackendClient, chat_id: str, user_id: str) -> None:
    try:
        tickets = await backend.list_tickets(user_id)
    except Exception as exc:
        await max_client.send_message(chat_id, f"Не удалось загрузить заявки: {exc}", user_id=user_id)
        await show_main_menu(max_client, chat_id, user_id)
        return
    if not tickets:
        await max_client.send_message(chat_id, "У вас пока нет заявок.", user_id=user_id)
        await show_main_menu(max_client, chat_id, user_id)
        return

    lines = ["Ваши заявки:"]
    for ticket in tickets:
        lines.append(f"#{ticket['external_id']} | {ticket.get('current_status') or ticket['status']} | {ticket['subject']}")
    await max_client.send_message(chat_id, "\n".join(lines), user_id=user_id)
    await show_main_menu(max_client, chat_id, user_id)


async def handle_start(max_client: MaxBotClient, backend: BackendClient, chat_id: str, user_id: str) -> None:
    user = await backend.get_user(user_id)
    if user:
        message = "Вы уже зарегистрированы."
        if PUBLIC_WEBAPP_URL:
            message += f"\nMini app: {PUBLIC_WEBAPP_URL}"
        await max_client.send_message(chat_id, message, user_id=user_id)
        await show_main_menu(max_client, chat_id, user_id)
        return

    welcome = "Введите рабочую почту для начала работы."
    if PUBLIC_WEBAPP_URL:
        welcome += f"\nИли откройте мини-приложение: {PUBLIC_WEBAPP_URL}"
    await max_client.send_message(chat_id, welcome, user_id=user_id)
    set_state(user_id, STATE_WAITING_EMAIL)


async def handle_email_input(
    max_client: MaxBotClient,
    backend: BackendClient,
    chat_id: str,
    user_id: str,
    full_name: str,
    text: str,
) -> None:
    if not is_valid_email(text):
        await max_client.send_message(chat_id, "Некорректный email. Попробуйте снова.", user_id=user_id)
        return

    session = get_session(user_id)
    session["form"]["pending_email"] = text
    session["form"]["pending_full_name"] = full_name
    save_state()
    try:
        await backend.request_email_code(max_user_id=user_id, full_name=full_name, email=text)
    except Exception as exc:
        await max_client.send_message(chat_id, f"Не удалось отправить код: {exc}", user_id=user_id)
        return
    await max_client.send_message(chat_id, "Код отправлен на рабочую почту.", user_id=user_id)
    await ask_for_email_code(max_client, chat_id, user_id)


async def handle_email_code_input(
    max_client: MaxBotClient,
    backend: BackendClient,
    chat_id: str,
    user_id: str,
    text: str,
) -> None:
    session = get_session(user_id)
    email = session["form"].get("pending_email", "")
    full_name = session["form"].get("pending_full_name", "")
    if not email:
        await max_client.send_message(chat_id, "Сначала введите рабочую почту.", user_id=user_id)
        await ask_for_email(max_client, chat_id, user_id)
        return
    try:
        await backend.verify_email_code(max_user_id=user_id, full_name=full_name, email=email, code=text.strip())
    except Exception as exc:
        await max_client.send_message(chat_id, f"Не удалось подтвердить почту: {exc}", user_id=user_id)
        return
    session["form"].pop("pending_email", None)
    session["form"].pop("pending_full_name", None)
    save_state()
    await ask_for_hotel(max_client, backend, chat_id, user_id)


async def handle_description_input(
    max_client: MaxBotClient,
    backend: BackendClient,
    chat_id: str,
    user_id: str,
    text: str,
) -> None:
    session = get_session(user_id)
    form = session["form"]
    try:
        ticket = await backend.create_ticket(
            max_user_id=user_id,
            hotel_id=form["hotel_id"],
            category_id=form["category_id"],
            topic_id=form["topic_id"],
            description=text,
        )
    except Exception as exc:
        set_state(user_id, STATE_IDLE)
        await max_client.send_message(chat_id, f"Не удалось отправить заявку: {exc}", user_id=user_id)
        await show_main_menu(max_client, chat_id, user_id)
        return

    set_state(user_id, STATE_IDLE)
    buttons = build_buttons([("Новая заявка", make_payload(ACTION_NEW_REQUEST))])
    await max_client.send_message(
        chat_id,
        f"Заявка отправлена. ID: {ticket['external_id']}. Статус: {ticket.get('current_status') or ticket['status']}",
        buttons=buttons,
        user_id=user_id,
    )


async def handle_status_ticket_input(
    max_client: MaxBotClient,
    backend: BackendClient,
    chat_id: str,
    user_id: str,
    text: str,
) -> None:
    ticket_id = text.strip()
    if not ticket_id:
        await max_client.send_message(chat_id, "Введите ID заявки.", user_id=user_id)
        return
    try:
        status_data = await backend.get_ticket_status(user_id, ticket_id)
        await max_client.send_message(chat_id, f"Статус заявки #{ticket_id}: {status_data['status']}", user_id=user_id)
    except Exception as exc:
        await max_client.send_message(chat_id, f"Не удалось получить статус заявки: {exc}", user_id=user_id)
    set_state(user_id, STATE_IDLE)
    await show_main_menu(max_client, chat_id, user_id)


async def handle_admin_broadcast_text(max_client: MaxBotClient, backend: BackendClient, sender_user_id: str, text: str) -> None:
    success = 0
    fail = 0
    try:
        users = await backend.list_users(sender_user_id)
        for user in users:
            target_id = str(user["max_user_id"])
            if target_id == str(sender_user_id):
                continue
            try:
                await max_client.send_message(target_id, f"Объявление:\n{text}", user_id=target_id)
                success += 1
            except Exception:
                logging.exception("Не удалось отправить рассылку пользователю %s", target_id)
                fail += 1
        await max_client.send_message(
            sender_user_id,
            f"Рассылка завершена.\nУспешно: {success}\nОшибок: {fail}",
            user_id=sender_user_id,
        )
    except Exception as exc:
        await max_client.send_message(sender_user_id, f"Не удалось выполнить рассылку: {exc}", user_id=sender_user_id)
    finally:
        set_state(sender_user_id, STATE_IDLE)
        await show_main_menu(max_client, sender_user_id, sender_user_id)


async def handle_callback(max_client: MaxBotClient, backend: BackendClient, update: dict[str, Any]) -> None:
    user_id, chat_id, _ = extract_sender(update)
    if not user_id or not chat_id:
        logging.warning("Не удалось определить пользователя для callback: %s", update)
        return

    payload, callback_id = extract_callback_data(update)
    action = payload.get("action")
    value = payload.get("value")
    session = get_session(user_id)
    state = session.get("state", STATE_IDLE)

    await max_client.answer_callback(callback_id)

    if action in {ACTION_CREATE_TICKET, ACTION_NEW_REQUEST}:
        await ask_for_hotel(max_client, backend, chat_id, user_id)
        return

    if action == ACTION_MY_TICKETS:
        await show_user_tickets(max_client, backend, chat_id, user_id)
        return

    if action == ACTION_CHECK_STATUS:
        await ask_for_status_ticket(max_client, chat_id, user_id)
        return

    if action == ACTION_OPEN_APP:
        if PUBLIC_WEBAPP_URL:
            await max_client.send_message(chat_id, f"Откройте мини-приложение: {PUBLIC_WEBAPP_URL}", user_id=user_id)
        else:
            await max_client.send_message(chat_id, "Ссылка на мини-приложение пока не настроена.", user_id=user_id)
        return

    if action == ACTION_ADMIN_BROADCAST:
        if user_id not in ADMIN_IDS:
            await max_client.send_message(chat_id, "Нет прав.", user_id=user_id)
            return
        await max_client.send_message(chat_id, "Введите текст сообщения для рассылки:", user_id=user_id)
        set_state(user_id, STATE_WAITING_ADMIN_BROADCAST)
        return

    if action == ACTION_CANCEL_REQUEST:
        reset_form(user_id)
        set_state(user_id, STATE_IDLE)
        await max_client.send_message(chat_id, "Заполнение заявки отменено.", user_id=user_id)
        await show_main_menu(max_client, chat_id, user_id)
        return

    if action == ACTION_BACK_HOTEL:
        await ask_for_hotel(max_client, backend, chat_id, user_id)
        return

    if action == ACTION_BACK_CATEGORY:
        await ask_for_category(max_client, backend, chat_id, user_id)
        return

    if action == ACTION_BACK_TOPIC:
        await ask_for_topic(max_client, backend, chat_id, user_id)
        return

    catalog = await backend.get_catalog()

    if action == "hotel" and state == STATE_WAITING_HOTEL:
        hotel_id = parse_int(value)
        if hotel_id is None:
            return
        hotel = find_catalog_item(catalog["hotels"], hotel_id)
        if hotel and hotel["is_active"]:
            session["form"]["hotel_id"] = hotel_id
            session["form"]["hotel_name"] = hotel["name"]
            save_state()
            await ask_for_category(max_client, backend, chat_id, user_id)
        return

    if action == "category" and state == STATE_WAITING_CATEGORY:
        category_id = parse_int(value)
        if category_id is None:
            return
        category = find_catalog_item(catalog["categories"], category_id)
        if category and category["is_active"]:
            session["form"]["category_id"] = category_id
            session["form"]["category_name"] = category["name"]
            save_state()
            await ask_for_topic(max_client, backend, chat_id, user_id)
        return

    if action == "topic" and state == STATE_WAITING_TOPIC:
        topic_id = parse_int(value)
        if topic_id is None:
            return
        category = find_catalog_item(catalog["categories"], session["form"].get("category_id"))
        if category:
            topic = next((item for item in category["topics"] if item["id"] == topic_id and item["is_active"]), None)
            if topic:
                session["form"]["topic_id"] = topic_id
                session["form"]["topic_name"] = topic["name"]
                save_state()
                await ask_for_description(max_client, chat_id, user_id)
        return

    logging.info("Необработанный callback: %s", payload)


async def handle_message(max_client: MaxBotClient, backend: BackendClient, update: dict[str, Any]) -> None:
    user_id, chat_id, full_name = extract_sender(update)
    if not user_id or not chat_id:
        logging.warning("Не удалось определить пользователя для сообщения: %s", update)
        return

    text = extract_text(update)
    state = get_session(user_id).get("state", STATE_IDLE)

    if text.lower() == "/start":
        await handle_start(max_client, backend, chat_id, user_id)
        return

    if state == STATE_WAITING_EMAIL:
        await handle_email_input(max_client, backend, chat_id, user_id, full_name, text)
        return

    if state == STATE_WAITING_EMAIL_CODE:
        await handle_email_code_input(max_client, backend, chat_id, user_id, text)
        return

    if state == STATE_WAITING_DESCRIPTION:
        await handle_description_input(max_client, backend, chat_id, user_id, text)
        return

    if state == STATE_WAITING_STATUS_TICKET_ID:
        await handle_status_ticket_input(max_client, backend, chat_id, user_id, text)
        return

    if state == STATE_WAITING_ADMIN_BROADCAST:
        if user_id not in ADMIN_IDS:
            set_state(user_id, STATE_IDLE)
            await max_client.send_message(chat_id, "Нет прав.", user_id=user_id)
            return
        await handle_admin_broadcast_text(max_client, backend, user_id, text)
        return

    user = await backend.get_user(user_id)
    if not user:
        await ask_for_email(max_client, chat_id, user_id)
        return

    await show_main_menu(max_client, chat_id, user_id)


async def dispatch_update(max_client: MaxBotClient, backend: BackendClient, update: dict[str, Any]) -> None:
    update_type = update.get("update_type") or update.get("type")
    if update_type == "message_callback" or update.get("callback"):
        await handle_callback(max_client, backend, update)
        return
    if update_type == "message_created" or update.get("message"):
        await handle_message(max_client, backend, update)
        return
    logging.info("Пропускаю неподдерживаемое обновление: %s", update_type)


async def process_status_notifications(max_client: MaxBotClient, backend: BackendClient) -> None:
    if not INTERNAL_API_TOKEN:
        return
    notifications = await backend.sync_status_notifications()
    for notification in notifications:
        try:
            message = (
                f"Статус заявки #{notification['external_id']} изменился:\n"
                f"{notification['previous_status']} -> {notification['new_status']}\n"
                f"Тема: {notification['subject']}"
            )
            await max_client.send_message(
                notification["max_user_id"],
                message,
                user_id=notification["max_user_id"],
            )
            await backend.mark_status_notification_sent(notification["id"])
        except Exception:
            logging.exception("Не удалось отправить уведомление о смене статуса: %s", notification)


async def notifications_loop(
    max_client: MaxBotClient,
    backend: BackendClient,
    stop_event: asyncio.Event,
) -> None:
    while not stop_event.is_set():
        try:
            await process_status_notifications(max_client, backend)
            touch_heartbeat()
        except Exception:
            logging.exception("Не удалось обработать уведомления о смене статусов")
            touch_heartbeat()

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=TICKET_STATUS_POLL_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            continue


async def run() -> None:
    if not MAX_BOT_TOKEN:
        raise RuntimeError("Не задан MAX_BOT_TOKEN")

    load_state()
    touch_heartbeat()
    max_client = MaxBotClient(MAX_BOT_TOKEN, MAX_API_BASE_URL)
    backend = BackendClient(BACKEND_API_URL)
    await max_client.start()
    await backend.start()
    stop_event = asyncio.Event()
    notifications_task = asyncio.create_task(notifications_loop(max_client, backend, stop_event))

    try:
        while True:
            try:
                updates = await max_client.get_updates()
                touch_heartbeat()
                for update in updates:
                    await dispatch_update(max_client, backend, update)
                    touch_heartbeat()
            except Exception:
                logging.exception("Ошибка в цикле обработки обновлений")
                touch_heartbeat()
    finally:
        stop_event.set()
        notifications_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await notifications_task
        await backend.close()
        await max_client.close()


if __name__ == "__main__":
    asyncio.run(run())
