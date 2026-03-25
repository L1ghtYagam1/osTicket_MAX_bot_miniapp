import asyncio
import json
import re
from typing import Any

import aiohttp

from .config import get_settings


settings = get_settings()


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


class OsTicketClient:
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
        timeout = aiohttp.ClientTimeout(total=settings.osticket_request_timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(settings.osticket_api_url, headers=headers, json=payload) as response:
                    body = await response.text()
                    if response.status != 201:
                        raise RuntimeError(f"osTicket error {response.status}: {body}")
                    return extract_ticket_id(body, dict(response.headers))
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while connecting to osTicket") from exc

    async def get_ticket_status(self, external_ticket_id: str) -> str:
        if not settings.osticket_status_api_url:
            raise RuntimeError("OSTICKET_STATUS_API_URL is not configured")
        if not settings.osticket_api_key:
            raise RuntimeError("OSTICKET_API_KEY is not configured")

        url = settings.osticket_status_api_url.format(ticket_id=external_ticket_id)
        headers = {
            "X-API-Key": settings.osticket_api_key,
            "Content-Type": "application/json",
        }
        timeout = aiohttp.ClientTimeout(total=settings.osticket_request_timeout)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, headers=headers) as response:
                    body = await response.text()
                    if response.status >= 400:
                        raise RuntimeError(f"osTicket status error {response.status}: {body}")
                    return extract_status(body)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Timeout while reading ticket status from osTicket") from exc


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
