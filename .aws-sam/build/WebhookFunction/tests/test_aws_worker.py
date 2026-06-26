import json

from telegram.constants import ParseMode

from telegram_summarizer import aws_worker
from telegram_summarizer import config
from telegram_summarizer.telegram_api import TelegramApiError


class FakeStorage:
    def __init__(self, messages=None, settings=None):
        self.logged = []
        self.messages = messages or []
        self.settings = settings or dict(config.DEFAULTS)
        self.setting_updates = []
        self.owner_active_chat = {}
        self.usage_logs = []
        self.chat_ids = [10]

    def log_message(self, *args):
        self.logged.append(args)

    def recent_messages(self, chat_id, n):
        return self.messages[-n:]

    def get_settings(self, chat_id):
        return dict(self.settings)

    def set_setting(self, chat_id, key, value):
        self.setting_updates.append((chat_id, key, value))
        self.settings[key] = value

    def list_chat_ids(self):
        return self.chat_ids

    def get_owner_active_chat(self, user_id):
        return self.owner_active_chat.get(user_id)

    def set_owner_active_chat(self, user_id, chat_id):
        self.owner_active_chat[user_id] = chat_id

    def log_usage(self, chat_id, usage, messages_count, ts=None):
        self.usage_logs.append((chat_id, usage, messages_count, ts))

    def usage_totals(self, chat_id, since_ts=None):
        return {
            "requests": 2,
            "messages_count": 30,
            "input_tokens": 1000,
            "output_tokens": 200,
            "total_tokens": 1200,
            "estimated_records": 1,
        }


class FakeTelegram:
    def __init__(self, status="member"):
        self.sent = []
        self.status = status

    def send_message(self, chat_id, text, parse_mode=None):
        self.sent.append({"chat_id": chat_id, "text": text, "parse_mode": parse_mode})

    def get_chat_member(self, chat_id, user_id):
        return {"status": self.status}


class FailingTelegram:
    def __init__(self, status_code):
        self.status_code = status_code

    def send_message(self, chat_id, text, parse_mode=None):
        raise TelegramApiError("telegram failed", status_code=self.status_code)


def update(text, chat_id=10, user_id=42, message_id=7, chat_type="group"):
    return {
        "message": {
            "message_id": message_id,
            "chat": {"id": chat_id, "type": chat_type},
            "from": {"id": user_id, "first_name": "Bob", "last_name": "<Admin>"},
            "text": text,
        }
    }


def test_non_command_text_logs_to_storage():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("hello"), storage, telegram, now_fn=lambda: 123)

    assert storage.logged == [(10, 7, 42, "Bob <Admin>", "hello", 123)]
    assert telegram.sent == []


def test_summarize_uses_injected_llm_escapes_html_and_sends_reply():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/summarize"),
        storage,
        telegram,
        summarize_fn=lambda messages, settings: "2 < 3 & ok",
        now_fn=lambda: 999,
    )

    assert telegram.sent == [
        {
            "chat_id": 10,
            "text": (
                '<a href="tg://user?id=42">Bob &lt;Admin&gt;</a>, here is your '
                "summary of the last 1 messages (requested):\n\n2 &lt; 3 &amp; ok"
            ),
            "parse_mode": ParseMode.HTML,
        }
    ]
    assert storage.usage_logs[0][0] == 10
    assert storage.usage_logs[0][2] == 1


def test_summarize_preserves_safe_telegram_html():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/summarize"),
        storage,
        telegram,
        summarize_fn=lambda messages, settings: "<b>Important</b> 2 < 3",
    )

    assert "<b>Important</b> 2 &lt; 3" in telegram.sent[0]["text"]


def test_summarize_empty_history_sends_current_no_messages_response():
    storage = FakeStorage(messages=[])
    telegram = FakeTelegram()

    aws_worker.process_update(update("/summarize"), storage, telegram)

    assert telegram.sent[0]["text"].startswith("I have no logged messages yet")


def test_setting_commands_reject_non_admin_users():
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")

    aws_worker.process_update(update("/setfilter strict"), storage, telegram)

    assert storage.setting_updates == []
    assert telegram.sent == [
        {"chat_id": 10, "text": "Only admins can change settings.", "parse_mode": None}
    ]


def test_setting_commands_are_allowed_in_private_chats():
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")

    aws_worker.process_update(
        update("/setfilter off", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )

    assert storage.setting_updates == [(42, "filter_level", "off")]
    assert telegram.sent == [
        {"chat_id": 42, "text": "Updated filter_level to: off", "parse_mode": None}
    ]


def test_owner_can_select_chat_and_change_settings_from_dm(monkeypatch):
    monkeypatch.setattr(config, "BOT_OWNER_IDS", {42})
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")

    aws_worker.process_update(
        update("/usechat -1001", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )
    aws_worker.process_update(
        update("/setfilter strict", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )

    assert storage.owner_active_chat[42] == -1001
    assert storage.setting_updates == [(-1001, "filter_level", "strict")]
    assert telegram.sent[-1] == {
        "chat_id": 42,
        "text": "Updated filter_level for -1001 to: strict",
        "parse_mode": None,
    }


def test_owner_can_list_chats_from_dm(monkeypatch):
    monkeypatch.setattr(config, "BOT_OWNER_IDS", {42})
    storage = FakeStorage()
    storage.chat_ids = [-1001, 42]
    storage.owner_active_chat[42] = -1001
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/chats", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )

    assert "Known chats:" in telegram.sent[0]["text"]
    assert "-1001 *" in telegram.sent[0]["text"]


def test_setting_commands_update_for_admin_users():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")

    aws_worker.process_update(update("/setfilter strict"), storage, telegram)

    assert storage.setting_updates == [(10, "filter_level", "strict")]
    assert telegram.sent == [
        {"chat_id": 10, "text": "Updated filter_level to: strict", "parse_mode": None}
    ]


def test_usage_command_reports_totals():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/usage today"), storage, telegram, now_fn=lambda: 1000)

    assert "requests: 2" in telegram.sent[0]["text"]
    assert "total tokens: 1200" in telegram.sent[0]["text"]


def test_whoami_reports_user_and_chat_ids():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/whoami"), storage, telegram)

    assert telegram.sent == [
        {
            "chat_id": 10,
            "text": "user_id: 42\nchat_id: 10\nchat_type: group",
            "parse_mode": None,
        }
    ]


def test_summarize_auto_selects_messages_by_token_budget(monkeypatch):
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 220)
    monkeypatch.setattr(config, "SUMMARY_OUTPUT_TOKENS", 80)
    messages = [
        {"user_name": "alice", "text": "x" * 120, "ts": ts}
        for ts in range(5)
    ]
    storage = FakeStorage(messages=messages)
    telegram = FakeTelegram()
    captured = {}

    def summarize_fn(selected, settings):
        captured["count"] = len(selected)
        return "summary"

    aws_worker.process_update(
        update("/summarize auto"),
        storage,
        telegram,
        summarize_fn=summarize_fn,
    )

    assert 0 < captured["count"] < len(messages)
    assert "(based on context budget)" in telegram.sent[0]["text"]


def test_handle_sqs_event_routes_records():
    storage = FakeStorage()
    telegram = FakeTelegram()
    event = {"Records": [{"body": json.dumps(update("hello"))}]}

    aws_worker.handle_sqs_event(event, storage, telegram, now_fn=lambda: 555)

    assert storage.logged[0][-1] == 555


def test_handle_sqs_event_acknowledges_permanent_telegram_4xx_failures():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    event = {"Records": [{"body": json.dumps(update("/summarize"))}]}

    aws_worker.handle_sqs_event(
        event,
        storage,
        FailingTelegram(status_code=400),
        summarize_fn=lambda messages, settings: "summary",
    )


def test_handle_sqs_event_retries_rate_limit_failures():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    event = {"Records": [{"body": json.dumps(update("/summarize"))}]}

    try:
        aws_worker.handle_sqs_event(
            event,
            storage,
            FailingTelegram(status_code=429),
            summarize_fn=lambda messages, settings: "summary",
        )
    except TelegramApiError as exc:
        assert exc.status_code == 429
    else:
        raise AssertionError("expected rate-limit TelegramApiError to be retried")
