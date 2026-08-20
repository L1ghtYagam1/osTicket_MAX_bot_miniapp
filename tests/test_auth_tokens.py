"""Подписанные сессии backend и валидация launch-данных mini app."""
import hashlib
import hmac
import json
import time
from urllib.parse import quote

import pytest

from backend import session_auth
from backend.max_webapp import validate_init_data

BOT_TOKEN = "test-bot-token"


def build_init_data(user: dict | None = None, *, auth_date: int | None = None, token=BOT_TOKEN) -> str:
    """Собирает и подписывает init_data так же, как это делает клиент MAX."""
    payload = {
        "user": json.dumps(user or {"id": 42, "first_name": "Иван", "last_name": "Петров"}),
        "auth_date": str(auth_date if auth_date is not None else int(time.time())),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(payload.items()))
    secret_key = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    signature = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    parts = [f"{key}={quote(value)}" for key, value in payload.items()]
    parts.append(f"hash={signature}")
    return "&".join(parts)


class TestSessionToken:
    def test_roundtrip(self):
        token = session_auth.create_session_token(max_user_id="100", full_name="Иван")
        principal = session_auth.verify_session_token(token)
        assert principal.max_user_id == "100"
        assert principal.full_name == "Иван"

    def test_tampered_payload_is_rejected(self):
        token = session_auth.create_session_token(max_user_id="100", full_name="Иван")
        payload_b64, signature = token.split(".", 1)
        forged = session_auth.base64.urlsafe_b64encode(
            json.dumps({"max_user_id": "999", "full_name": "Взлом", "iat": int(time.time())}).encode()
        ).decode().rstrip("=")
        with pytest.raises(ValueError, match="signature is invalid"):
            session_auth.verify_session_token(f"{forged}.{signature}")

    def test_malformed_token_is_rejected(self):
        with pytest.raises(ValueError):
            session_auth.verify_session_token("не-токен")

    def test_expired_token_is_rejected(self, monkeypatch):
        monkeypatch.setattr(session_auth.settings, "max_session_ttl_seconds", 60)
        token = session_auth.create_session_token(max_user_id="100", full_name="Иван")
        monkeypatch.setattr(session_auth, "time", lambda: time.time() + 3600)
        with pytest.raises(ValueError, match="expired"):
            session_auth.verify_session_token(token)

    def test_zero_ttl_means_no_expiry(self, monkeypatch):
        monkeypatch.setattr(session_auth.settings, "max_session_ttl_seconds", 0)
        token = session_auth.create_session_token(max_user_id="100", full_name="Иван")
        monkeypatch.setattr(session_auth, "time", lambda: time.time() + 10 * 365 * 24 * 3600)
        assert session_auth.verify_session_token(token).max_user_id == "100"


class TestInitDataValidation:
    def test_valid_init_data_returns_user(self):
        user = validate_init_data(build_init_data(), bot_token=BOT_TOKEN)
        assert user.max_user_id == "42"
        assert user.full_name == "Иван Петров"

    def test_signature_from_another_bot_is_rejected(self):
        init_data = build_init_data(token="чужой-токен")
        with pytest.raises(ValueError, match="signature is invalid"):
            validate_init_data(init_data, bot_token=BOT_TOKEN)

    def test_missing_hash_is_rejected(self):
        with pytest.raises(ValueError, match="hash is missing"):
            validate_init_data("user=%7B%22id%22%3A1%7D&auth_date=1", bot_token=BOT_TOKEN)

    def test_stale_init_data_is_rejected(self):
        old = int(time.time()) - 10 * 24 * 3600
        with pytest.raises(ValueError, match="expired"):
            validate_init_data(build_init_data(auth_date=old), bot_token=BOT_TOKEN)

    def test_username_is_used_when_names_absent(self):
        user = validate_init_data(
            build_init_data({"id": 7, "username": "ivan"}), bot_token=BOT_TOKEN
        )
        assert user.full_name == "ivan"

    def test_missing_user_id_is_rejected(self):
        with pytest.raises(ValueError, match="User id is missing"):
            validate_init_data(build_init_data({"first_name": "Без ID"}), bot_token=BOT_TOKEN)

    def test_empty_init_data_is_rejected(self):
        with pytest.raises(ValueError, match="Init data is empty"):
            validate_init_data("", bot_token=BOT_TOKEN)
