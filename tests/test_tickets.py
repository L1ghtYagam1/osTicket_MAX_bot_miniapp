"""Создание заявок, дедупликация, доступы и синхронизация статусов."""
import asyncio

import pytest
from sqlalchemy import select

from backend import services
from backend.models import Ticket, TicketStatusNotification, UserTicketViewPermission


class FakeOsTicket:
    """Подменяет сетевой клиент: считает вызовы и отдаёт заранее заданные статусы."""

    def __init__(self, *, ticket_id="555", statuses=None, fail_status=False):
        self.ticket_id = ticket_id
        self.statuses = statuses or {}
        self.fail_status = fail_status
        self.created = []
        self.status_calls = []
        self.max_parallel = 0
        self._active = 0

    async def create_ticket(self, **kwargs):
        self.created.append(kwargs)
        if self.ticket_id is None:
            raise RuntimeError("osTicket не вернул номер заявки")
        return self.ticket_id

    async def get_ticket_status(self, external_id, *, use_extended_api=False):
        self._active += 1
        self.max_parallel = max(self.max_parallel, self._active)
        try:
            # Даём планировщику шанс запустить соседние запросы — так видно,
            # выполняется опрос параллельно или строго по очереди.
            await asyncio.sleep(0.01)
            self.status_calls.append(external_id)
            if self.fail_status:
                raise RuntimeError("osTicket недоступен")
            return self.statuses.get(external_id, "open")
        finally:
            self._active -= 1


@pytest.fixture
def fake_osticket(monkeypatch):
    def _install(**kwargs):
        client = FakeOsTicket(**kwargs)
        monkeypatch.setattr(services, "osticket_client", client)
        return client

    return _install


def make_ticket(db, user, catalog, *, external_id="555", status="created") -> Ticket:
    ticket = Ticket(
        external_id=external_id,
        user_id=user.id,
        hotel_id=catalog["hotel"].id,
        category_id=catalog["category"].id,
        topic_id=catalog["topic"].id,
        subject=catalog["topic"].name,
        description="Описание",
        status=status,
    )
    db.add(ticket)
    db.commit()
    db.refresh(ticket)
    return ticket


class TestCreateTicket:
    async def test_creates_ticket_and_stores_external_id(self, db, user_factory, catalog, fake_osticket):
        client = fake_osticket(ticket_id="777")
        user = user_factory()
        ticket = await services.create_ticket(
            db,
            max_user_id=user.max_user_id,
            hotel_id=catalog["hotel"].id,
            category_id=catalog["category"].id,
            topic_id=catalog["topic"].id,
            description="Не работает принтер",
        )
        assert ticket.external_id == "777"
        assert client.created[0]["email"] == user.work_email
        assert client.created[0]["osticket_topic_id"] == catalog["category"].osticket_topic_id
        assert "Тестовый отель" in client.created[0]["hotel_name"]

    async def test_duplicate_submission_is_deduplicated(self, db, user_factory, catalog, fake_osticket):
        client = fake_osticket(ticket_id="777")
        user = user_factory()
        payload = dict(
            max_user_id=user.max_user_id,
            hotel_id=catalog["hotel"].id,
            category_id=catalog["category"].id,
            topic_id=catalog["topic"].id,
            description="Дубль",
        )
        first = await services.create_ticket(db, **payload)
        second = await services.create_ticket(db, **payload)
        assert first.id == second.id
        # Повторное нажатие не должно порождать второй тикет в osTicket.
        assert len(client.created) == 1

    async def test_missing_ticket_number_does_not_create_local_record(
        self, db, user_factory, catalog, fake_osticket
    ):
        fake_osticket(ticket_id=None)
        user = user_factory()
        with pytest.raises(RuntimeError):
            await services.create_ticket(
                db,
                max_user_id=user.max_user_id,
                hotel_id=catalog["hotel"].id,
                category_id=catalog["category"].id,
                topic_id=catalog["topic"].id,
                description="Без номера",
            )
        assert db.scalars(select(Ticket)).all() == []

    async def test_inactive_user_cannot_create_ticket(self, db, user_factory, catalog, fake_osticket):
        fake_osticket()
        user = user_factory(is_active=False)
        with pytest.raises(ValueError, match="Пользователь отключен"):
            await services.create_ticket(
                db,
                max_user_id=user.max_user_id,
                hotel_id=catalog["hotel"].id,
                category_id=catalog["category"].id,
                topic_id=catalog["topic"].id,
                description="Текст",
            )

    async def test_topic_must_belong_to_category(self, db, user_factory, catalog, fake_osticket):
        fake_osticket()
        user = user_factory()
        from backend.models import Category, Topic

        other = Category(name="Другая", osticket_topic_id=9)
        db.add(other)
        db.commit()
        db.refresh(other)
        foreign_topic = Topic(category_id=other.id, name="Чужая тема")
        db.add(foreign_topic)
        db.commit()
        db.refresh(foreign_topic)

        with pytest.raises(ValueError, match="не принадлежит выбранной категории"):
            await services.create_ticket(
                db,
                max_user_id=user.max_user_id,
                hotel_id=catalog["hotel"].id,
                category_id=catalog["category"].id,
                topic_id=foreign_topic.id,
                description="Текст",
            )


class TestTicketVisibility:
    def test_user_sees_only_own_tickets(self, db, user_factory, catalog):
        owner = user_factory(max_user_id="100", email="owner@example.com")
        other = user_factory(max_user_id="200", email="other@example.com")
        make_ticket(db, owner, catalog, external_id="1")
        make_ticket(db, other, catalog, external_id="2")

        tickets = services.list_user_tickets(db, "100")
        assert [item.external_id for item in tickets] == ["1"]
        assert tickets[0].is_shared is False

    def test_granted_permission_exposes_other_users_tickets(self, db, user_factory, catalog):
        owner = user_factory(max_user_id="100", email="owner@example.com")
        viewer = user_factory(max_user_id="200", email="viewer@example.com")
        make_ticket(db, owner, catalog, external_id="1")
        db.add(UserTicketViewPermission(viewer_user_id=viewer.id, owner_user_id=owner.id))
        db.commit()

        tickets = services.list_user_tickets(db, "200")
        assert [item.external_id for item in tickets] == ["1"]
        assert tickets[0].is_shared is True
        assert tickets[0].owner_work_email == "owner@example.com"

    def test_disabled_user_gets_empty_list(self, db, user_factory, catalog):
        user = user_factory(is_active=False)
        make_ticket(db, user, catalog)
        assert services.list_user_tickets(db, user.max_user_id) == []


class TestStatusEnrichment:
    async def test_statuses_are_fetched_in_parallel(self, db, user_factory, catalog, fake_osticket):
        client = fake_osticket(statuses={})
        user = user_factory()
        tickets = [make_ticket(db, user, catalog, external_id=str(i)) for i in range(6)]

        await services.enrich_tickets_status(db, tickets)

        assert len(client.status_calls) == 6
        # Последовательный обход дал бы max_parallel == 1 — ровно та проблема,
        # из-за которой список заявок упирался в таймаут.
        assert client.max_parallel > 1

    async def test_status_change_is_persisted_and_normalized(self, db, user_factory, catalog, fake_osticket):
        fake_osticket(statuses={"555": "Closed"})
        user = user_factory()
        ticket = make_ticket(db, user, catalog, external_id="555", status="open")

        enriched = await services.enrich_ticket_status(db, ticket)
        assert enriched.current_status == "closed"
        db.refresh(ticket)
        assert ticket.status == "closed"

    async def test_unavailable_osticket_keeps_last_known_status(
        self, db, user_factory, catalog, fake_osticket
    ):
        fake_osticket(fail_status=True)
        user = user_factory()
        ticket = make_ticket(db, user, catalog, status="open")

        enriched = await services.enrich_ticket_status(db, ticket)
        assert enriched.current_status == "open"


class TestStatusSync:
    async def test_notification_created_on_status_change(self, db, user_factory, catalog, fake_osticket):
        fake_osticket(statuses={"555": "Resolved"})
        user = user_factory()
        make_ticket(db, user, catalog, external_id="555", status="open")

        notifications = await services.sync_ticket_statuses(db)
        assert len(notifications) == 1
        assert notifications[0].previous_status == "open"
        assert notifications[0].new_status == "resolved"

    async def test_closed_tickets_are_not_polled_again(self, db, user_factory, catalog, fake_osticket):
        client = fake_osticket(statuses={})
        user = user_factory()
        make_ticket(db, user, catalog, external_id="1", status="closed")
        make_ticket(db, user, catalog, external_id="2", status="Closed")
        make_ticket(db, user, catalog, external_id="3", status="open")

        await services.sync_ticket_statuses(db)
        # Раньше «Closed» с заглавной не попадал в терминальный набор и опрашивался вечно.
        assert client.status_calls == ["3"]

    async def test_pending_notification_is_not_duplicated(self, db, user_factory, catalog, fake_osticket):
        fake_osticket(statuses={"555": "Resolved"})
        user = user_factory()
        ticket = make_ticket(db, user, catalog, external_id="555", status="open")

        await services.sync_ticket_statuses(db)
        ticket.status = "open"
        db.commit()
        await services.sync_ticket_statuses(db)

        pending = db.scalars(select(TicketStatusNotification)).all()
        assert len(pending) == 1

    async def test_reopened_ticket_notifies_again_after_delivery(
        self, db, user_factory, catalog, fake_osticket
    ):
        fake_osticket(statuses={"555": "Resolved"})
        user = user_factory()
        ticket = make_ticket(db, user, catalog, external_id="555", status="open")

        first = await services.sync_ticket_statuses(db)
        services.mark_notification_sent(db, first[0].id)

        # Заявку переоткрыли и снова решили: пользователь обязан узнать об этом.
        ticket.status = "open"
        db.commit()
        second = await services.sync_ticket_statuses(db)

        assert len(second) == 1
        assert db.scalars(select(TicketStatusNotification)).all().__len__() == 2

    async def test_sync_survives_unavailable_osticket(self, db, user_factory, catalog, fake_osticket):
        fake_osticket(fail_status=True)
        user = user_factory()
        make_ticket(db, user, catalog, status="open")

        assert await services.sync_ticket_statuses(db) == []
