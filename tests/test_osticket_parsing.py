"""Разбор ответов osTicket: номера заявок и статусы."""
import pytest

from backend.osticket import (
    extract_extended_thread_entries,
    extract_status,
    extract_ticket_id,
    is_terminal_status,
    normalize_extended_status,
    normalize_status,
    status_label,
)


class TestNormalizeStatus:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("Closed", "closed"),
            ("closed", "closed"),
            ("CLOSED", "closed"),
            ("Закрыта", "closed"),
            ("Open", "open"),
            ("Reopened", "open"),
            ("In Progress", "in_progress"),
            ("in-progress", "in_progress"),
            ("В работе", "in_progress"),
            ("On Hold", "pending"),
            ("Resolved", "resolved"),
            ("Archived", "archived"),
        ],
    )
    def test_known_statuses_collapse_to_canonical_form(self, raw, expected):
        assert normalize_status(raw) == expected

    def test_numeric_status_id_maps_through_extended_table(self):
        assert normalize_status(3) == "closed"
        assert normalize_status("3") == "closed"
        assert normalize_status(6) == "in_progress"

    def test_unknown_status_is_kept_as_slug(self):
        assert normalize_status("Waiting for parts") == "waiting_for_parts"

    def test_empty_values(self):
        assert normalize_status(None) == ""
        assert normalize_status("   ") == ""

    def test_terminal_detection_is_case_insensitive(self):
        # Ровно эта проверка раньше не срабатывала: сравнение шло с сырой строкой,
        # и «Closed» не попадал в набор терминальных статусов.
        assert is_terminal_status("Closed") is True
        assert is_terminal_status("Закрыта") is True
        assert is_terminal_status("Open") is False

    def test_status_label_is_human_readable(self):
        assert status_label("Closed") == "Закрыта"
        assert status_label("in_progress") == "В работе"
        assert status_label("") == "неизвестен"


class TestExtractTicketId:
    def test_reads_ticket_id_from_json(self):
        assert extract_ticket_id('{"ticket_id": 123}', {}) == "123"

    def test_reads_plain_number_response(self):
        assert extract_ticket_id("987654", {}) == "987654"

    def test_reads_location_header(self):
        assert extract_ticket_id("", {"Location": "https://osticket.test/tickets/4242"}) == "4242"

    def test_returns_none_when_nothing_parsable(self):
        # Раньше здесь возвращалась строка-заглушка, которая писалась в уникальное
        # поле external_id и роняла вторую такую заявку с IntegrityError.
        assert extract_ticket_id("", {}) is None
        assert extract_ticket_id("no digits here", {}) is None


class TestExtractStatus:
    def test_normalizes_status_from_json(self):
        assert extract_status('{"status": "Closed"}') == "closed"

    def test_reads_nested_ticket_object(self):
        assert extract_status('{"ticket": {"status": "In Progress"}}') == "in_progress"

    def test_falls_back_to_regex_and_normalizes(self):
        assert extract_status('not json but "status": "Resolved" inside') == "resolved"

    def test_raises_when_status_absent(self):
        with pytest.raises(RuntimeError):
            extract_status('{"subject": "нет статуса"}')


class TestExtendedPayloads:
    def test_status_object_with_name(self):
        assert normalize_extended_status({"status": {"name": "Closed"}}) == "closed"

    def test_status_id_fallback(self):
        assert normalize_extended_status({"status_id": 2}) == "resolved"

    def test_closed_flag_fallback(self):
        assert normalize_extended_status({"closed": 1}) == "closed"

    def test_default_is_created(self):
        assert normalize_extended_status({"subject": "без статуса"}) == "created"

    def test_thread_entries_are_extracted(self):
        payload = {
            "thread": [
                {"body": "Первое сообщение", "author": "Иван", "created_at": "2026-01-01"},
                {"body": "  ", "author": "Пусто"},
            ]
        }
        entries = extract_extended_thread_entries(payload)
        assert len(entries) == 1
        assert entries[0]["body"] == "Первое сообщение"
        assert entries[0]["author"] == "Иван"

    def test_thread_falls_back_to_last_response(self):
        entries = extract_extended_thread_entries({"last_response": "Ответ сотрудника"})
        assert len(entries) == 1
        assert entries[0]["body"] == "Ответ сотрудника"
