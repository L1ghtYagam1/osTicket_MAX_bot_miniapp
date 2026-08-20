import asyncio
import json
import logging
import re
from typing import Any

import aiohttp

from .config import get_settings


logger = logging.getLogger(__name__)
settings = get_settings()

# Ограничение на одновременные соединения к osTicket, чтобы массовый опрос статусов
# не превращался в мини-DDoS собственного helpdesk.
OSTICKET_CONNECTION_LIMIT = 10

EXTENDED_STATUS_NAMES = {
    1: "open",
    2: "resolved",
    3: "closed",
    4: "archived",
    5: "deleted",
    6: "in_progress",
    7: "pending",
}

# Канонические статусы, которыми оперирует backend. Всё, что приходит из osTicket,
# приводится к ним, иначе сравнения вроде "заявка закрыта" ломаются на регистре
# и локализации ("Closed", "closed", "Закрыта" — это один и тот же статус).
STATUS_ALIASES = {
    "created": "created",
    "создана": "created",
    "новая": "open",
    "new": "open",
    "open": "open",
    "opened": "open",
    "reopened": "open",
    "открыта": "open",
    "открыт": "open",
    "in progress": "in_progress",
    "in_progress": "in_progress",
    "inprogress": "in_progress",
    "processing": "in_progress",
    "в работе": "in_progress",
    "pending": "pending",
    "on hold": "pending",
    "onhold": "pending",
    "hold": "pending",
    "waiting": "pending",
    "ожидание": "pending",
    "resolved": "resolved",
    "solved": "resolved",
    "решена": "resolved",
    "решён": "resolved",
    "решен": "resolved",
    "closed": "closed",
    "close": "closed",
    "completed": "closed",
    "complete": "closed",
    "закрыта": "closed",
    "закрыт": "closed",
    "archived": "archived",
    "archive": "archived",
    "архив": "archived",
    "deleted": "deleted",
    "удалена": "deleted",
    "удалён": "deleted",
    "удален": "deleted",
}

# Статусы, после которых заявка уже не меняется — их не нужно переспрашивать у osTicket.
TERMINAL_STATUSES = frozenset({"closed", "archived", "deleted"})

STATUS_LABELS = {
    "created": "Создана",
    "open": "Открыта",
    "in_progress": "В работе",
    "pending": "Ожидание",
    "resolved": "Решена",
    "closed": "Закрыта",
    "archived": "В архиве",
    "deleted": "Удалена",
}


def normalize_status(value: Any) -> str:
    """Приводит статус из любого формата osTicket к каноническому виду."""
    if value is None:
        return ""

    if isinstance(value, bool):
        return "closed" if value else "open"

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return EXTENDED_STATUS_NAMES.get(int(value), str(int(value)))

    text = str(value).strip()
    if not text:
        return ""

    # Числовой status_id, пришедший строкой.
    if text.isdigit():
        return EXTENDED_STATUS_NAMES.get(int(text), text)

    key = re.sub(r"[\s\-]+", " ", text.lower()).strip()
    if key in STATUS_ALIASES:
        return STATUS_ALIASES[key]
    return key.replace(" ", "_")


def status_label(value: str) -> str:
    """Человекочитаемое название статуса для бота и mini app."""
    normalized = normalize_status(value)
    return STATUS_LABELS.get(normalized, normalized or "неизвестен")


def is_terminal_status(value: str) -> bool:
    return normalize_status(value) in TERMINAL_STATUSES


def extract_ticket_id(response_text: str, response_headers: dict[str, str]) -> str | None:
    """Возвращает номер заявки из ответа osTicket либо None.

    Раньше здесь возвращалась строка-заглушка, которая затем писалась в уникальное
    поле tickets.external_id — вторая такая заявка падала с IntegrityError, а тикет
    в osTicket оставался «сиротой». Теперь неудача разбора видна вызывающему коду.
    """
    location_header = response_headers.get("Location", "")
    try:
        response_json: Any = json.loads(response_text) if response_text else {}
    except json.JSONDecodeError:
        response_json = {}

    if isinstance(response_json, dict):
        for candidate in (
            response_json.get("ticket_id"),
            response_json.get("id"),
            response_json.get("number"),
            response_json.get("ticketNumber"),
        ):
            if candidate:
                return str(candidate)
    elif isinstance(response_json, (int, float)):
        return str(int(response_json))
    elif isinstance(response_json, str) and response_json.strip():
        return response_json.strip()

    if location_header:
        match = re.search(r"(\d+)(?:/)?$", location_header)
        if match:
            return match.group(1)

    if response_text:
        match = re.search(r"\d+", response_text)
        if match:
            return match.group(0)

    return None


def extract_status(body: str) -> str:
    try:
        payload: Any = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}

    status = extract_status_from_payload(payload)
    if status:
        return normalize_status(status)

    match = re.search(r'"(?:status|state|ticket_status|ticketState)"\s*:\s*"([^"]+)"', body, re.IGNORECASE)
    if match:
        return normalize_status(match.group(1))

    raise RuntimeError("Ticket status not found in osTicket response")


def extract_status_from_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ("status", "state", "ticket_status", "ticketState"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for key in ("ticket", "data", "result"):
            nested = payload.get(key)
            nested_status = extract_status_from_payload(nested)
            if nested_status:
                return nested_status
    if isinstance(payload, list):
        for item in payload:
            nested_status = extract_status_from_payload(item)
            if nested_status:
                return nested_status
    return None


def extract_extended_ticket(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        if isinstance(payload.get("ticket"), dict):
            return payload["ticket"]
        if isinstance(payload.get("data"), dict):
            nested = extract_extended_ticket(payload["data"])
            if nested:
                return nested
        if isinstance(payload.get("tickets"), list) and payload["tickets"]:
            first = payload["tickets"][0]
            if isinstance(first, dict):
                return first
        if "status_id" in payload or "number" in payload or "ticket_id" in payload:
            return payload
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            return first
    return {}


def extract_extended_thread_entries(ticket_payload: dict[str, Any]) -> list[dict[str, str]]:
    candidates = (
        ticket_payload.get("thread"),
        ticket_payload.get("entries"),
        ticket_payload.get("messages"),
        ticket_payload.get("responses"),
        ticket_payload.get("history"),
        ticket_payload.get("activity"),
        ticket_payload.get("events"),
        ticket_payload.get("conversation"),
        ticket_payload.get("ticket_thread"),
        ticket_payload.get("thread_entries"),
    )
    raw_entries: list[Any] = []
    for candidate in candidates:
        if isinstance(candidate, list):
            raw_entries = candidate
            break

    thread: list[dict[str, str]] = []
    for item in raw_entries:
        if not isinstance(item, dict):
            continue
        body = ""
        for key in ("body", "message", "text", "response", "content", "note", "comment"):
            value = item.get(key)
            text_value = _extract_text_value(value)
            if text_value:
                body = text_value
                break
        if not body:
            continue

        title = ""
        for key in ("title", "subject", "header"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                title = value.strip()
                break

        author = ""
        for key in ("author", "name", "poster", "staff", "user"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                author = value.strip()
                break
            if isinstance(value, dict):
                nested = value.get("name") or value.get("full_name") or value.get("email")
                if isinstance(nested, str) and nested.strip():
                    author = nested.strip()
                    break

        created_at = ""
        for key in ("created_at", "created", "timestamp", "date", "updated_at"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                created_at = value.strip()
                break

        entry_type = ""
        for key in ("type", "entry_type", "kind"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                entry_type = value.strip()
                break

        thread.append(
            {
                "title": title,
                "body": body,
                "author": author,
                "created_at": created_at,
                "entry_type": entry_type,
            }
        )
    if thread:
        return thread

    # Fallback: some plugins don't return full thread arrays, only latest message/response fields.
    fallback_keys = (
        ("last_response", "Ответ сотрудника"),
        ("lastresponse", "Ответ сотрудника"),
        ("response", "Ответ сотрудника"),
        ("last_message", "Последнее сообщение"),
        ("lastmessage", "Последнее сообщение"),
        ("message", "Сообщение"),
    )
    for key, title in fallback_keys:
        text_value = _extract_text_value(ticket_payload.get(key))
        if text_value:
            return [
                {
                    "title": title,
                    "body": text_value,
                    "author": str(ticket_payload.get("last_replier") or ticket_payload.get("staff") or "").strip(),
                    "created_at": str(ticket_payload.get("updated") or ticket_payload.get("lastupdate") or "").strip(),
                    "entry_type": "fallback",
                }
            ]

    return []


def _extract_text_value(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(value, dict):
        for key in ("body", "text", "message", "content", "note", "response", "value"):
            nested = value.get(key)
            if isinstance(nested, str) and nested.strip():
                return nested.strip()
    return ""


def normalize_extended_status(ticket_payload: dict[str, Any]) -> str:
    for key in ("status", "state", "ticket_status", "ticketState"):
        value = ticket_payload.get(key)
        if isinstance(value, dict):
            value = value.get("name") or value.get("title") or value.get("id")
        if isinstance(value, str) and value.strip():
            return normalize_status(value)

    for key in ("status_id", "statusId"):
        value = ticket_payload.get(key)
        try:
            status_id = int(value)
        except (TypeError, ValueError):
            continue
        return EXTENDED_STATUS_NAMES.get(status_id, str(status_id))

    for key in ("closed", "is_closed"):
        value = ticket_payload.get(key)
        if value in (1, "1", True, "true", "True"):
            return "closed"

    return "created"


class OsTicketClient:
    """Клиент osTicket с одной переиспользуемой HTTP-сессией.

    Раньше на каждый вызов создавался новый aiohttp.ClientSession: пул соединений и
    TLS-handshake заново, что при опросе статусов десятков заявок стоило дороже
    самих запросов.
    """

    def __init__(self) -> None:
        self.timeout = aiohttp.ClientTimeout(total=settings.osticket_request_timeout)
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    self._session = aiohttp.ClientSession(
                        timeout=self.timeout,
                        connector=aiohttp.TCPConnector(limit=OSTICKET_CONNECTION_LIMIT),
                    )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    def _headers(self) -> dict[str, str]:
        return {
            "X-API-Key": settings.osticket_api_key,
            "Content-Type": "application/json",
        }

    async def create_ticket(
        self,
        *,
        full_name: str,
        email: str,
        subject: str,
        description: str,
        hotel_name: str,
        osticket_topic_id: int,
    ) -> str:
        if not settings.osticket_api_url:
            raise RuntimeError("OSTICKET_API_URL is not configured")
        if not settings.osticket_api_key:
            raise RuntimeError("OSTICKET_API_KEY is not configured")

        payload = {
            "alert": True,
            "autorespond": True,
            "source": "API",
            "name": full_name,
            "email": email,
            "subject": subject,
            "message": f"Отель: {hotel_name}\nОписание заявки:\n{description}",
            "topicId": osticket_topic_id,
        }

        try:
            session = await self.session()
            async with session.post(settings.osticket_api_url, headers=self._headers(), json=payload) as response:
                body = await response.text()
                if response.status != 201:
                    raise RuntimeError(f"osTicket error {response.status}: {body}")
                ticket_id = extract_ticket_id(body, dict(response.headers))
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while connecting to osTicket") from exc

        if not ticket_id:
            # Тикет мог создаться, но номер не разобрался — писать заглушку в БД нельзя.
            logger.error("osTicket не вернул номер заявки. Ответ: %s", body[:500])
            raise RuntimeError("osTicket не вернул номер заявки")
        return ticket_id

    async def get_ticket_status(self, external_ticket_id: str, *, use_extended_api: bool = False) -> str:
        if use_extended_api and settings.osticket_extended_api_url:
            details = await self.get_extended_ticket_details(external_ticket_id)
            return normalize_extended_status(details)

        if not settings.osticket_status_api_url:
            raise RuntimeError("OSTICKET_STATUS_API_URL is not configured")
        if not settings.osticket_api_key:
            raise RuntimeError("OSTICKET_API_KEY is not configured")

        url = settings.osticket_status_api_url.format(ticket_id=external_ticket_id)

        try:
            session = await self.session()
            async with session.get(url, headers=self._headers()) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"osTicket status error {response.status}: {body}")
                return extract_status(body)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while reading ticket status from osTicket") from exc

    async def get_extended_ticket_details(self, external_ticket_id: str) -> dict[str, Any]:
        candidate_errors: list[str] = []

        # Variant 1: plugins that expect /tickets-get.php/{ticket_number}.json.
        try:
            data = await self._call_extended_api(
                "GET",
                f"/tickets-get.php/{str(external_ticket_id)}.json",
            )
            ticket = extract_extended_ticket(data)
            if ticket:
                return ticket
        except Exception as exc:
            candidate_errors.append(str(exc))

        # Variant 2: plugins that expect /tickets-get.php/<ticket_id>.
        try:
            data = await self._call_extended_api(
                "GET",
                f"/tickets-get.php/{self._numeric_ticket_id(external_ticket_id)}",
            )
            ticket = extract_extended_ticket(data)
            if ticket:
                return ticket
        except Exception as exc:
            candidate_errors.append(str(exc))

        # Variant 3: plugins that expect /tickets-get.php?number=<ticket_number>.
        try:
            data = await self._call_extended_api(
                "GET",
                "/tickets-get.php",
                params={"number": str(external_ticket_id)},
            )
            ticket = extract_extended_ticket(data)
            if ticket:
                return ticket
        except Exception as exc:
            candidate_errors.append(str(exc))

        # Variant 4: fallback through search endpoint.
        try:
            data = await self._call_extended_api(
                "GET",
                "/tickets-search.php",
                params={"query": str(external_ticket_id)},
            )
            ticket = extract_extended_ticket(data)
            if ticket:
                return ticket
        except Exception as exc:
            candidate_errors.append(str(exc))

        details = " | ".join(candidate_errors) if candidate_errors else "no response from extended API"
        raise RuntimeError(f"Extended API ticket details not found for {external_ticket_id}: {details}")

    async def reply_to_ticket(self, external_ticket_id: str, *, message: str) -> dict[str, Any]:
        return await self._call_extended_api(
            "PATCH",
            f"/tickets/{self._numeric_ticket_id(external_ticket_id)}",
            payload={
                "reply": message,
                "message": message,
            },
        )

    async def change_ticket_status(self, external_ticket_id: str, *, status_id: int, body: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status_id": status_id,
            "status": status_id,
        }
        if body:
            payload["reply"] = body
            payload["message"] = body
        return await self._call_extended_api(
            "PATCH",
            f"/tickets/{self._numeric_ticket_id(external_ticket_id)}",
            payload=payload,
        )

    async def search_tickets(self, *, email: str | None = None, status: str | None = None, query: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if email:
            params["email"] = email
        if status:
            params["status"] = status
        if query:
            params["query"] = query
        return await self._call_extended_api("GET", "/tickets-search.php", params=params)

    async def _call_extended_api(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not settings.osticket_extended_api_url:
            raise RuntimeError("OSTICKET_EXTENDED_API_URL is not configured")
        if not settings.osticket_api_key:
            raise RuntimeError("OSTICKET_API_KEY is not configured")

        base_url = settings.osticket_extended_api_url.rstrip("/")
        url = f"{base_url}{path}"
        headers = {**self._headers(), "apikey": settings.osticket_api_key}

        try:
            session = await self.session()
            async with session.request(method, url, headers=headers, json=payload, params=params) as response:
                body = await response.text()
                if response.status >= 400:
                    raise RuntimeError(f"Extended osTicket API error {response.status}: {body}")
                if not body:
                    return {}
                try:
                    data = json.loads(body)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"Extended osTicket API returned invalid JSON: {body}") from exc
                if isinstance(data, dict) and data.get("success") is False:
                    raise RuntimeError(data.get("message") or "Extended osTicket API request failed")
                return data if isinstance(data, dict) else {"data": data}
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while calling extended osTicket API") from exc

    @staticmethod
    def _numeric_ticket_id(external_ticket_id: str) -> int:
        try:
            return int(str(external_ticket_id))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Extended osTicket API expects a numeric ticket id") from exc
