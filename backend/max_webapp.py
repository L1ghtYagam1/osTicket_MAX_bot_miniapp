import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time
from urllib.parse import unquote_plus

from .config import get_settings


settings = get_settings()


@dataclass
class MaxWebAppUser:
    max_user_id: str
    full_name: str
    raw_user: dict


def validate_init_data(init_data: str, *, bot_token: str) -> MaxWebAppUser:
    if not init_data:
        raise ValueError("Init data is empty")
    if not bot_token:
        raise ValueError("MAX_BOT_TOKEN is not configured")

    decoded = unquote_plus(init_data)
    pairs = []
    received_hash = ""

    for chunk in decoded.split("&"):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        if key == "hash":
            received_hash = value
            continue
        pairs.append((key, value))

    if not received_hash:
        raise ValueError("Init data hash is missing")

    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(pairs, key=lambda item: item[0]))
    secret_key = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calculated_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise ValueError("Init data signature is invalid")

    payload = dict(pairs)
    auth_date_raw = payload.get("auth_date", "")
    if auth_date_raw:
        try:
            auth_date = int(auth_date_raw)
        except ValueError as exc:
            raise ValueError("Init data auth_date is invalid") from exc
        if auth_date > 10_000_000_000:
            auth_date //= 1000
        now = int(time())
        if abs(now - auth_date) > settings.max_webapp_auth_max_age_seconds:
            raise ValueError("Init data is expired")

    raw_user = parse_user(payload.get("user", "{}"))
    user_id = raw_user.get("id")
    if user_id is None:
        raise ValueError("User id is missing in init data")

    first_name = str(raw_user.get("first_name") or "").strip()
    last_name = str(raw_user.get("last_name") or "").strip()
    username = str(raw_user.get("username") or "").strip()
    full_name = " ".join(part for part in (first_name, last_name) if part).strip() or username or f"MAX User {user_id}"

    return MaxWebAppUser(
        max_user_id=str(user_id),
        full_name=full_name,
        raw_user=raw_user,
    )


def parse_user(raw_value: str) -> dict:
    try:
        return json.loads(raw_value) if raw_value else {}
    except json.JSONDecodeError as exc:
        raise ValueError("User payload in init data is invalid") from exc
