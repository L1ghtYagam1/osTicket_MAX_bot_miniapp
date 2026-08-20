"""Бот MAX: разбор обновлений, маркер long-polling, устойчивость обработки."""
import json
from typing import Any

import pytest

import main as bot


@pytest.fixture(autouse=True)
def bot_data_dir(tmp_path, monkeypatch):
    """Уводит файлы состояния бота во временный каталог."""
    monkeypatch.setattr(bot, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bot, "STATE_DATA_FILE", tmp_path / "conversation_state.json")
    monkeypatch.setattr(bot, "BOT_HEARTBEAT_FILE", tmp_path / "bot_heartbeat.json")
    monkeypatch.setattr(bot, "UPDATES_MARKER_FILE", tmp_path / "updates_marker.json")
    monkeypatch.setattr(bot, "CONVERSATION_STATE", {})
    return tmp_path


class TestPayloadHelpers:
    def test_payload_roundtrip(self):
        payload = bot.make_payload("hotel", "12")
        assert bot.parse_payload(payload) == {"action": "hotel", "value": "12"}

    def test_parse_payload_accepts_plain_string(self):
        assert bot.parse_payload("create_ticket") == {"action": "create_ticket"}

    def test_parse_payload_survives_garbage(self):
        assert bot.parse_payload(None) == {}
        assert bot.parse_payload("{битый json") == {"action": "{битый json"}

    def test_buttons_are_laid_out_two_per_row(self):
        rows = bot.build_buttons([("a", "1"), ("b", "2"), ("c", "3")])
        assert [len(row) for row in rows] == [2, 1]

    @pytest.mark.parametrize(
        "email, expected",
        [("user@example.com", True), ("bad-email", False), ("user@host", False)],
    )
    def test_email_validation(self, email, expected):
        assert bot.is_valid_email(email) is expected

    def test_status_label_translates_backend_status(self):
        assert bot.status_label("closed") == "Закрыта"
        assert bot.status_label("Closed") == "Закрыта"
        assert bot.status_label("unknown_state") == "unknown_state"


class TestUpdateParsing:
    def test_sender_from_message(self):
        update = {
            "message": {
                "sender": {"user_id": 42, "name": "Иван"},
                "recipient": {"chat_id": 77},
                "body": {"text": "привет"},
            }
        }
        user_id, chat_id, full_name = bot.extract_sender(update)
        assert (user_id, chat_id, full_name) == ("42", "77", "Иван")
        assert bot.extract_text(update) == "привет"

    def test_sender_from_callback(self):
        update = {"callback": {"sender": {"user_id": 7}, "callback_id": "cb-1", "payload": '{"action":"x"}'}}
        user_id, chat_id, _ = bot.extract_sender(update)
        assert user_id == "7"
        # chat_id отсутствует — подставляется user_id, иначе ответить некуда.
        assert chat_id == "7"
        payload, callback_id = bot.extract_callback_data(update)
        assert payload == {"action": "x"}
        assert callback_id == "cb-1"

    def test_missing_user_is_reported_as_none(self):
        assert bot.extract_sender({})[0] is None


class TestStatePersistence:
    def test_save_json_is_atomic(self, bot_data_dir):
        target = bot_data_dir / "state.json"
        bot.save_json(target, {"a": 1})
        assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
        # Временный файл не должен оставаться рядом с целевым.
        assert list(bot_data_dir.glob("*.tmp")) == []

    def test_corrupted_state_falls_back_to_default(self, bot_data_dir):
        target = bot_data_dir / "state.json"
        target.write_text("{не json", encoding="utf-8")
        assert bot.load_json(target, {"default": True}) == {"default": True}

    def test_marker_survives_restart(self, bot_data_dir):
        bot.save_updates_marker("marker-123")
        assert bot.load_updates_marker() == "marker-123"

    def test_missing_marker_file_returns_none(self, bot_data_dir):
        assert bot.load_updates_marker() is None

    def test_empty_marker_is_not_written(self, bot_data_dir):
        bot.save_updates_marker(None)
        assert bot.load_updates_marker() is None


class FakeMaxClient(bot.MaxBotClient):
    """Клиент MAX без сети: отдаёт заранее заданные ответы /updates."""

    def __init__(self, responses):
        super().__init__("token", "https://max.test")
        self.responses = list(responses)
        self.sent: list[tuple[Any, str]] = []

    async def request(self, method, path, *, params=None, json_body=None):
        return self.responses.pop(0)

    async def send_message(self, chat_id, text, *, buttons=None, user_id=None):
        self.sent.append((user_id or chat_id, text))

    async def answer_callback(self, callback_id):
        return None


class TestUpdatesMarker:
    async def test_marker_advances_on_new_value(self):
        client = FakeMaxClient([{"updates": [], "marker": 100}])
        await client.get_updates()
        assert client.marker == "100"

    async def test_null_marker_does_not_reset_progress(self):
        # Ровно этот случай приводил к повторной обработке всех обновлений
        # и дублирующимся заявкам: marker: null затирал накопленное значение.
        client = FakeMaxClient([{"updates": [], "marker": 100}, {"updates": [], "marker": None}])
        await client.get_updates()
        await client.get_updates()
        assert client.marker == "100"

    async def test_missing_marker_key_keeps_previous(self):
        client = FakeMaxClient([{"updates": [], "marker": 100}, {"updates": []}])
        await client.get_updates()
        await client.get_updates()
        assert client.marker == "100"


class TestDispatchBatch:
    async def test_failing_update_does_not_stop_the_batch(self, monkeypatch):
        handled: list[str] = []

        async def fake_dispatch(max_client, backend, update):
            marker = update["id"]
            if marker == "boom":
                raise RuntimeError("сломалось")
            handled.append(marker)

        monkeypatch.setattr(bot, "dispatch_update", fake_dispatch)
        updates = [
            {"id": "a", "message": {"sender": {"user_id": 1}}},
            {"id": "boom", "message": {"sender": {"user_id": 2}}},
            {"id": "c", "message": {"sender": {"user_id": 3}}},
        ]
        await bot.dispatch_updates(FakeMaxClient([]), None, updates)
        assert sorted(handled) == ["a", "c"]

    async def test_updates_of_one_user_keep_their_order(self, monkeypatch):
        order: list[str] = []

        async def fake_dispatch(max_client, backend, update):
            order.append(update["id"])

        monkeypatch.setattr(bot, "dispatch_update", fake_dispatch)
        updates = [
            {"id": "first", "message": {"sender": {"user_id": 1}}},
            {"id": "second", "message": {"sender": {"user_id": 1}}},
        ]
        await bot.dispatch_updates(FakeMaxClient([]), None, updates)
        # Диалог — конечный автомат, порядок внутри одного пользователя обязателен.
        assert order == ["first", "second"]
