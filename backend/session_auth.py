import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from time import time

from .config import get_settings


settings = get_settings()


@dataclass
class SessionPrincipal:
    max_user_id: str
    full_name: str
    issued_at: int


def _secret() -> str:
    return settings.max_session_secret or settings.max_bot_token


def create_session_token(*, max_user_id: str, full_name: str) -> str:
    secret = _secret()
    if not secret:
        raise ValueError("Session secret is not configured")

    payload = {
        "max_user_id": max_user_id,
        "full_name": full_name,
        "iat": int(time()),
    }
    raw_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(raw_payload).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload_b64}.{signature}"


def verify_session_token(token: str) -> SessionPrincipal:
    secret = _secret()
    if not secret:
        raise ValueError("Session secret is not configured")

    try:
        payload_b64, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Session token format is invalid") from exc

    expected = hmac.new(secret.encode("utf-8"), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Session token signature is invalid")

    padded = payload_b64 + "=" * (-len(payload_b64) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except Exception as exc:
        raise ValueError("Session token payload is invalid") from exc

    max_user_id = str(payload.get("max_user_id") or "").strip()
    full_name = str(payload.get("full_name") or "").strip()
    issued_at = int(payload.get("iat") or 0)
    if not max_user_id or not issued_at:
        raise ValueError("Session token payload is incomplete")

    if int(time()) - issued_at > settings.max_webapp_auth_max_age_seconds:
        raise ValueError("Session token is expired")

    return SessionPrincipal(max_user_id=max_user_id, full_name=full_name, issued_at=issued_at)
