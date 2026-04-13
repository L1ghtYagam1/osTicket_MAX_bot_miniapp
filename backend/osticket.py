import asyncio
import json
import re
from typing import Any

import aiohttp

from .config import get_settings


settings = get_settings()

EXTENDED_STATUS_NAMES = {
    1: "open",
    2: "resolved",
    3: "closed",
    4: "archived",
    5: "deleted",
    6: "in_progress",
    7: "pending",
}


def extract_ticket_id(response_text: str, response_headers: dict[str, str]) -> str:
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

    return "не указан"


def extract_status(body: str) -> str:
    try:
        payload: Any = json.loads(body) if body else {}
    except json.JSONDecodeError:
        payload = {}

    status = extract_status_from_payload(payload)
    if status:
        return status

    match = re.search(r'"(?:status|state|ticket_status|ticketState)"\s*:\s*"([^"]+)"', body, re.IGNORECASE)
    if match:
        return match.group(1)

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
        for key in ("body", "message", "text", "response", "content"):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                body = value.strip()
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
    return thread


def normalize_extended_status(ticket_payload: dict[str, Any]) -> str:
    for key in ("status", "state", "ticket_status", "ticketState"):
        value = ticket_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().lower()

    for key in ("status_id", "statusId"):
        value = ticket_payload.get(key)
        try:
            status_id = int(value)
        except (TypeError, ValueError):
            status_id = None
        if status_id is not None:
            return EXTENDED_STATUS_NAMES.get(status_id, str(status_id))

    for key in ("closed", "is_closed"):
        value = ticket_payload.get(key)
        if value in (1, "1", True, "true", "True"):
            return "closed"

    return "created"


class OsTicketClient:
    def __init__(self) -> None:
        self.timeout = aiohttp.ClientTimeout(total=settings.osticket_request_timeout)

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
        headers = {
            "X-API-Key": settings.osticket_api_key,
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.post(settings.osticket_api_url, headers=headers, json=payload) as response:
                    body = await response.text()
                    if response.status != 201:
                        raise RuntimeError(f"osTicket error {response.status}: {body}")
                    return extract_ticket_id(body, dict(response.headers))
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while connecting to osTicket") from exc

    async def get_ticket_status(self, external_ticket_id: str, *, use_extended_api: bool = False) -> str:
        if use_extended_api and settings.osticket_extended_api_url:
            details = await self.get_extended_ticket_details(external_ticket_id)
            return normalize_extended_status(details)

        if not settings.osticket_status_api_url:
            raise RuntimeError("OSTICKET_STATUS_API_URL is not configured")
        if not settings.osticket_api_key:
            raise RuntimeError("OSTICKET_API_KEY is not configured")

        url = settings.osticket_status_api_url.format(ticket_id=external_ticket_id)
        headers = {
            "X-API-Key": settings.osticket_api_key,
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
                async with session.get(url, headers=headers) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(f"osTicket status error {response.status}: {body}")
                    return extract_status(body)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while reading ticket status from osTicket") from exc

    async def get_extended_ticket_details(self, external_ticket_id: str) -> dict[str, Any]:
        candidate_errors: list[str] = []

        # Variant 1: plugins that expect /tickets-get.php/<ticket_id>.
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

        # Variant 2: plugins that expect /tickets-get.php?number=<ticket_number>.
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

        # Variant 3: fallback through search endpoint.
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
        headers = {
            "X-API-Key": settings.osticket_api_key,
            "apikey": settings.osticket_api_key,
            "Content-Type": "application/json",
        }

        try:
            async with aiohttp.ClientSession(timeout=self.timeout) as session:
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
