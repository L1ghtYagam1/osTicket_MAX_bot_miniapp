"""Разграничение доступа на уровне HTTP API."""
import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.session_auth import create_session_token

INTERNAL_TOKEN = "test-internal-token"


@pytest.fixture
def client():
    # lifespan прогоняет миграции — заодно проверяем, что приложение стартует.
    with TestClient(app) as test_client:
        yield test_client


def auth_header(max_user_id: str, full_name: str = "Тест") -> dict[str, str]:
    token = create_session_token(max_user_id=max_user_id, full_name=full_name)
    return {"Authorization": f"Bearer {token}"}


class TestPublicEndpoints:
    def test_health(self, client):
        assert client.get("/api/v1/health").json() == {"status": "ok"}

    def test_catalog_is_public(self, client):
        response = client.get("/api/v1/catalog")
        assert response.status_code == 200
        assert "hotels" in response.json()

    def test_request_code_rejects_foreign_domain(self, client):
        response = client.post(
            "/api/v1/auth/request-email-code",
            json={"max_user_id": "100", "full_name": "Тест", "email": "user@gmail.com"},
        )
        assert response.status_code == 400
        assert "Разрешены только рабочие почты" in response.json()["detail"]


class TestAdminAccess:
    def test_admin_endpoint_requires_token(self, client):
        assert client.get("/api/v1/admin/users").status_code == 401

    def test_garbage_token_is_rejected(self, client):
        response = client.get("/api/v1/admin/users", headers={"Authorization": "Bearer not-a-real-token"})
        assert response.status_code == 401

    def test_token_without_bearer_prefix_is_rejected(self, client):
        response = client.get("/api/v1/admin/users", headers={"Authorization": "some-raw-token"})
        assert response.status_code == 401

    def test_regular_user_cannot_reach_admin(self, client, user_factory):
        user_factory(max_user_id="100", email="user@example.com", is_admin=False)
        response = client.get("/api/v1/admin/users", headers=auth_header("100"))
        assert response.status_code == 403

    def test_admin_user_can_reach_admin(self, client, user_factory):
        user_factory(max_user_id="100", email="admin@example.com", is_admin=True)
        response = client.get("/api/v1/admin/users", headers=auth_header("100"))
        assert response.status_code == 200

    def test_disabled_admin_loses_access(self, client, user_factory):
        user_factory(max_user_id="100", email="admin@example.com", is_admin=True, is_active=False)
        response = client.get("/api/v1/admin/users", headers=auth_header("100"))
        assert response.status_code == 403

    def test_internal_token_does_not_unlock_admin(self, client, user_factory):
        user_factory(max_user_id="100", email="user@example.com")
        response = client.get("/api/v1/admin/users", headers={"X-Internal-Token": INTERNAL_TOKEN})
        assert response.status_code == 401


class TestCrossUserAccess:
    def test_user_cannot_read_another_users_tickets(self, client, user_factory):
        user_factory(max_user_id="100", email="first@example.com")
        user_factory(max_user_id="200", email="second@example.com")
        response = client.get("/api/v1/tickets?max_user_id=200", headers=auth_header("100"))
        assert response.status_code == 403

    def test_user_reads_own_tickets(self, client, user_factory):
        user_factory(max_user_id="100", email="first@example.com")
        response = client.get("/api/v1/tickets?max_user_id=100", headers=auth_header("100"))
        assert response.status_code == 200
        assert response.json() == []

    def test_user_cannot_create_ticket_for_another_user(self, client, user_factory):
        user_factory(max_user_id="100", email="first@example.com")
        user_factory(max_user_id="200", email="second@example.com")
        response = client.post(
            "/api/v1/tickets",
            headers=auth_header("100"),
            json={
                "max_user_id": "200",
                "hotel_id": 1,
                "category_id": 1,
                "topic_id": 1,
                "description": "Чужая заявка",
            },
        )
        assert response.status_code == 403

    def test_bot_may_act_on_behalf_of_any_user(self, client, user_factory):
        user_factory(max_user_id="200", email="second@example.com")
        response = client.get(
            "/api/v1/tickets?max_user_id=200", headers={"X-Internal-Token": INTERNAL_TOKEN}
        )
        assert response.status_code == 200

    def test_profile_of_another_user_is_forbidden(self, client, user_factory):
        user_factory(max_user_id="100", email="first@example.com")
        user_factory(max_user_id="200", email="second@example.com")
        response = client.get("/api/v1/users/by-max/200", headers=auth_header("100"))
        assert response.status_code == 403


class TestInternalEndpoints:
    def test_internal_users_requires_token(self, client):
        assert client.get("/api/v1/internal/users").status_code == 403

    def test_internal_users_rejects_wrong_token(self, client):
        response = client.get("/api/v1/internal/users", headers={"X-Internal-Token": "wrong-internal-token"})
        assert response.status_code == 403

    def test_internal_users_accepts_correct_token(self, client, user_factory):
        user_factory(max_user_id="100", email="first@example.com")
        response = client.get("/api/v1/internal/users", headers={"X-Internal-Token": INTERNAL_TOKEN})
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_session_token_does_not_unlock_internal(self, client, user_factory):
        user_factory(max_user_id="100", email="first@example.com", is_admin=True)
        response = client.get("/api/v1/internal/users", headers=auth_header("100"))
        assert response.status_code == 403


class TestIconUpload:
    def test_svg_upload_is_rejected(self, client, user_factory):
        user_factory(max_user_id="100", email="admin@example.com", is_admin=True)
        response = client.post(
            "/api/v1/admin/upload-icon",
            headers=auth_header("100"),
            files={"file": ("icon.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")},
        )
        # SVG отдавался бы с того же origin, что и mini app, — это хранимая XSS.
        assert response.status_code == 400

    def test_png_upload_is_accepted(self, client, user_factory):
        user_factory(max_user_id="100", email="admin@example.com", is_admin=True)
        response = client.post(
            "/api/v1/admin/upload-icon",
            headers=auth_header("100"),
            files={"file": ("icon.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["url"].startswith("/uploads/")

    def test_empty_file_is_rejected(self, client, user_factory):
        user_factory(max_user_id="100", email="admin@example.com", is_admin=True)
        response = client.post(
            "/api/v1/admin/upload-icon",
            headers=auth_header("100"),
            files={"file": ("icon.png", b"", "image/png")},
        )
        assert response.status_code == 400
