"""Регрессия: при конкурентных повторных отправках заявка создаётся один раз.

Раньше несколько параллельных запросов одного пользователя проходили проверку
дедупликации одновременно (первый тикет ещё не закоммичен) и создавали дубли в
osTicket. Теперь создание сериализуется блокировкой на пользователя.
"""
import asyncio

import pytest
from sqlalchemy import func, select

from backend import models, services
from backend.database import SessionLocal


@pytest.mark.asyncio
async def test_concurrent_submissions_create_single_ticket(user_factory, catalog, monkeypatch):
    user = user_factory(max_user_id="100", email="user@example.com")
    hotel_id = catalog["hotel"].id
    category_id = catalog["category"].id
    topic_id = catalog["topic"].id

    call_count = 0

    async def fake_create_ticket(**kwargs):
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)  # имитируем задержку osTicket, провоцируя гонку
        return f"T{call_count}"

    monkeypatch.setattr(services.osticket_client, "create_ticket", fake_create_ticket)
    services._ticket_locks.clear()

    async def submit():
        with SessionLocal() as db:
            ticket = await services.create_ticket(
                db,
                max_user_id=user.max_user_id,
                hotel_id=hotel_id,
                category_id=category_id,
                topic_id=topic_id,
                description="одинаковое описание",
            )
            return ticket.external_id

    results = await asyncio.gather(*[submit() for _ in range(5)])

    assert call_count == 1, "osTicket должен вызываться один раз"
    assert set(results) == {"T1"}, "все запросы должны вернуть один и тот же тикет"

    with SessionLocal() as db:
        total = db.scalar(select(func.count()).select_from(models.Ticket))
        assert total == 1
