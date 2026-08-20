"""Общие фикстуры тестов.

Переменные окружения выставляются до импорта пакета backend: движок БД и настройки
создаются на уровне модуля, поэтому позже подменить их уже нельзя.
"""
import os
import tempfile
from pathlib import Path

import pytest

TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="osticket-bot-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_DB_DIR / 'test.db').as_posix()}"
os.environ["ALLOWED_EMAIL_DOMAINS"] = "example.com,hotel.test"
os.environ["ADMIN_MAX_IDS"] = "999"
os.environ["MAX_BOT_TOKEN"] = "test-bot-token"
os.environ["MAX_SESSION_SECRET"] = "test-session-secret"
os.environ["INTERNAL_API_TOKEN"] = "test-internal-token"
os.environ["EMAIL_CODE_RESEND_INTERVAL_SECONDS"] = "60"
os.environ["EMAIL_CODE_MAX_PER_HOUR"] = "5"
os.environ["EMAIL_CODE_MAX_ATTEMPTS"] = "5"
os.environ["OSTICKET_API_URL"] = "https://osticket.test/api/tickets.json"
os.environ["OSTICKET_API_KEY"] = "test-key"
os.environ["OSTICKET_STATUS_API_URL"] = "https://osticket.test/api/tickets/{ticket_id}.json"
# Фоновая синхронизация статусов не должна стартовать внутри тестов.
os.environ["TICKET_STATUS_POLL_INTERVAL_SECONDS"] = "0"
os.environ["TICKET_STATUS_CACHE_TTL_SECONDS"] = "0"

from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend import models  # noqa: E402,F401
from backend import services  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_tables(_create_schema):
    """Каждый тест начинается с пустых таблиц и пустого кэша статусов."""
    services.invalidate_status_cache()
    with SessionLocal() as db:
        for table in reversed(Base.metadata.sorted_tables):
            db.execute(table.delete())
        db.commit()
    yield


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def user_factory(db):
    def _create(
        max_user_id: str = "100",
        email: str = "user@example.com",
        full_name: str = "Тестовый Пользователь",
        is_admin: bool = False,
        is_active: bool = True,
    ) -> models.User:
        user = models.User(
            max_user_id=max_user_id,
            full_name=full_name,
            work_email=email,
            is_admin=is_admin,
            is_active=is_active,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    return _create


@pytest.fixture
def catalog(db):
    """Минимальный справочник: отель, категория и тема внутри неё."""
    hotel = models.Hotel(name="Тестовый отель")
    category = models.Category(name="Тестовая категория", osticket_topic_id=7)
    db.add_all([hotel, category])
    db.commit()
    db.refresh(hotel)
    db.refresh(category)
    topic = models.Topic(category_id=category.id, name="Тестовая тема")
    db.add(topic)
    db.commit()
    db.refresh(topic)
    return {"hotel": hotel, "category": category, "topic": topic}
