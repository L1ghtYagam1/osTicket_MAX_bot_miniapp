"""Доставка ответов оператора из osTicket в MAX (без плагина, через extended API)."""
import pytest

from backend import models, services
from backend.database import SessionLocal


def _make_ticket(db, user, catalog):
    ticket = models.Ticket(
        external_id="555001",
        user_id=user.id,
        hotel_id=catalog["hotel"].id,
        category_id=catalog["category"].id,
        topic_id=catalog["topic"].id,
        subject="Тестовая тема",
        description="Описание",
        status="open",
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


def _thread(entries):
    async def _fake(external_id):
        return {"number": external_id, "thread": entries}
    return _fake


@pytest.mark.asyncio
async def test_staff_reply_forwarded_after_first_scan(user_factory, catalog, monkeypatch):
    user = user_factory(max_user_id="100")
    with SessionLocal() as db:
        ticket = _make_ticket(db, user, catalog)
        ticket_id = ticket.id

    monkeypatch.setattr(services, "is_extended_api_enabled", lambda db: True)

    # Первый проход: в ветке уже есть старый ответ оператора и сообщение клиента.
    old = [
        {"type": "M", "body": "Моя заявка", "poster": "Клиент", "created": "2026-01-01"},
        {"type": "R", "body": "Приняли в работу", "poster": "Оператор", "created": "2026-01-02"},
    ]
    monkeypatch.setattr(services.osticket_client, "get_extended_ticket_details", _thread(old))
    with SessionLocal() as db:
        created = await services.sync_ticket_replies(db)
    assert created == [], "старую переписку при первом сканировании не шлём"

    # Второй проход: появился НОВЫЙ ответ оператора.
    new = old + [{"type": "R", "body": "Готово, закрываем", "poster": "Оператор", "created": "2026-01-03"}]
    monkeypatch.setattr(services.osticket_client, "get_extended_ticket_details", _thread(new))
    with SessionLocal() as db:
        created = await services.sync_ticket_replies(db)
    assert len(created) == 1
    assert created[0].body == "Готово, закрываем"

    # В очереди на отправку — ровно один, и его можно пометить отправленным.
    with SessionLocal() as db:
        pending = services.list_pending_reply_notifications(db)
        assert len(pending) == 1
        nid = pending[0].id
        services.mark_reply_notification_sent(db, nid)
        assert services.list_pending_reply_notifications(db) == []


@pytest.mark.asyncio
async def test_client_and_note_entries_ignored(user_factory, catalog, monkeypatch):
    user = user_factory(max_user_id="101", email="u101@example.com")
    with SessionLocal() as db:
        _make_ticket(db, user, catalog)

    monkeypatch.setattr(services, "is_extended_api_enabled", lambda db: True)
    entries = [
        {"type": "M", "body": "сообщение клиента", "poster": "Клиент"},
        {"type": "N", "body": "внутренняя заметка", "poster": "Система"},
    ]
    monkeypatch.setattr(services.osticket_client, "get_extended_ticket_details", _thread(entries))
    # Первый проход сидит всё как отправленное; второй — ничего нового (нет R).
    with SessionLocal() as db:
        await services.sync_ticket_replies(db)
    with SessionLocal() as db:
        created = await services.sync_ticket_replies(db)
    assert created == []
    with SessionLocal() as db:
        assert services.list_pending_reply_notifications(db) == []


@pytest.mark.asyncio
async def test_disabled_when_extended_api_off(user_factory, catalog, monkeypatch):
    user_factory(max_user_id="102", email="u102@example.com")
    monkeypatch.setattr(services, "is_extended_api_enabled", lambda db: False)
    with SessionLocal() as db:
        assert await services.sync_ticket_replies(db) == []
