"""Подтверждение рабочей почты: домены, троттлинг отправки, перебор кода."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from backend import services
from backend.models import EmailVerification, User


@pytest.fixture(autouse=True)
def _no_smtp(monkeypatch):
    """SMTP в тестах не трогаем — код читаем прямо из БД."""
    monkeypatch.setattr(services, "send_verification_email", lambda recipient, code: None)


def latest_code(db, max_user_id: str = "100") -> EmailVerification:
    return db.scalar(
        select(EmailVerification)
        .where(EmailVerification.max_user_id == max_user_id)
        .order_by(EmailVerification.created_at.desc())
    )


def shift_created_at(db, verification: EmailVerification, seconds: int) -> None:
    """Сдвигает запись в прошлое, чтобы не ждать реального времени в тесте."""
    verification.created_at = datetime.now(timezone.utc) - timedelta(seconds=seconds)
    db.commit()


class TestEmailValidation:
    @pytest.mark.parametrize("email", ["user@example.com", "first.last+tag@hotel.test"])
    def test_valid_emails(self, email):
        assert services.validate_email(email) is True

    @pytest.mark.parametrize("email", ["no-at-sign", "user@", "@example.com", "user@host"])
    def test_invalid_emails(self, email):
        assert services.validate_email(email) is False

    def test_domain_outside_allowlist_is_rejected(self, db):
        with pytest.raises(ValueError, match="Разрешены только рабочие почты"):
            services.request_email_code(db, "100", "Тест", "user@gmail.com")

    def test_domain_check_is_case_insensitive(self, db):
        services.request_email_code(db, "100", "Тест", "user@EXAMPLE.com")
        assert latest_code(db) is not None


class TestSendThrottling:
    def test_second_request_within_interval_is_rejected(self, db):
        services.request_email_code(db, "100", "Тест", "user@example.com")
        with pytest.raises(ValueError, match="Новый код можно запросить через"):
            services.request_email_code(db, "100", "Тест", "user@example.com")

    def test_request_allowed_after_interval(self, db):
        services.request_email_code(db, "100", "Тест", "user@example.com")
        shift_created_at(db, latest_code(db), seconds=120)
        services.request_email_code(db, "100", "Тест", "user@example.com")
        codes = db.scalars(select(EmailVerification)).all()
        assert len(codes) == 2

    def test_hourly_cap_blocks_mail_flooding(self, db):
        # Пять разрешённых отправок подряд, каждая «час назад минус чуть-чуть».
        for _ in range(5):
            services.request_email_code(db, "100", "Тест", "user@example.com")
            shift_created_at(db, latest_code(db), seconds=90)

        with pytest.raises(ValueError, match="Слишком много запросов кода"):
            services.request_email_code(db, "100", "Тест", "user@example.com")

    def test_throttling_is_per_user_and_email(self, db):
        services.request_email_code(db, "100", "Тест", "user@example.com")
        # Другой пользователь не должен упираться в чужой лимит.
        services.request_email_code(db, "200", "Второй", "second@example.com")
        assert latest_code(db, "200") is not None


class TestCodeVerification:
    def _request(self, db, max_user_id="100", email="user@example.com"):
        services.request_email_code(db, max_user_id, "Тест", email)
        return latest_code(db, max_user_id).code

    def test_correct_code_creates_user(self, db):
        code = self._request(db)
        user = services.verify_email_code(db, "100", "Тест", "user@example.com", code)
        assert user.work_email == "user@example.com"
        assert user.max_user_id == "100"

    def test_code_is_single_use(self, db):
        code = self._request(db)
        services.verify_email_code(db, "100", "Тест", "user@example.com", code)
        with pytest.raises(ValueError, match="Код не найден или уже использован"):
            services.verify_email_code(db, "100", "Тест", "user@example.com", code)

    def test_wrong_code_reports_remaining_attempts(self, db):
        self._request(db)
        with pytest.raises(ValueError, match="Осталось попыток: 4"):
            services.verify_email_code(db, "100", "Тест", "user@example.com", "000000")

    def test_code_burns_after_attempt_limit(self, db):
        correct = self._request(db)
        for _ in range(4):
            with pytest.raises(ValueError, match="Неверный код"):
                services.verify_email_code(db, "100", "Тест", "user@example.com", "000000")

        with pytest.raises(ValueError, match="Слишком много неверных попыток"):
            services.verify_email_code(db, "100", "Тест", "user@example.com", "000000")

        # Ключевая проверка: после исчерпания попыток даже верный код не проходит,
        # то есть перебор шестизначного кода становится невозможным.
        with pytest.raises(ValueError, match="Код не найден или уже использован"):
            services.verify_email_code(db, "100", "Тест", "user@example.com", correct)

    def test_expired_code_is_rejected(self, db):
        code = self._request(db)
        verification = latest_code(db)
        verification.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        with pytest.raises(ValueError, match="Срок действия кода истек"):
            services.verify_email_code(db, "100", "Тест", "user@example.com", code)


class TestEmailBinding:
    def test_email_cannot_be_taken_by_another_max_account(self, db, user_factory):
        user_factory(max_user_id="100", email="shared@example.com")
        # Раньше здесь вылетал IntegrityError и превращался в HTTP 500.
        with pytest.raises(ValueError, match="уже привязана к другому аккаунту"):
            services.bind_user_email(db, "200", "Второй", "shared@example.com")

    def test_same_user_can_rebind_own_email(self, db, user_factory):
        user_factory(max_user_id="100", email="user@example.com")
        user = services.bind_user_email(db, "100", "Новое Имя", "user@example.com")
        assert user.full_name == "Новое Имя"

    def test_admin_flag_comes_from_settings(self, db):
        user = services.bind_user_email(db, "999", "Админ", "admin@example.com")
        assert user.is_admin is True

    def test_user_can_switch_to_free_email(self, db, user_factory):
        user_factory(max_user_id="100", email="old@example.com")
        user = services.bind_user_email(db, "100", "Тест", "new@example.com")
        assert user.work_email == "new@example.com"
        assert db.scalars(select(User)).all().__len__() == 1
