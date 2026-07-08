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
        self.pending = {}
        self.recent_requests = []

    def log_message(self, *args):
        self.logged.append(args)

    def recent_messages(self, chat_id, n):
        self.recent_requests.append((chat_id, n))
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

    def set_pending_input(self, user_id, action, target_chat_id, now=None, ttl_seconds=600):
        self.pending[user_id] = {
            "action": action,
            "target_chat_id": target_chat_id,
            "created_at": now,
            "expires_at": now + ttl_seconds,
        }

    def get_pending_input(self, user_id, now=None):
        pending = self.pending.get(user_id)
        if pending and pending["expires_at"] > now:
            return dict(pending)
        return None

    def delete_pending_input(self, user_id):
        self.pending.pop(user_id, None)


class FakeTelegram:
    def __init__(self, status="member"):
        self.sent = []
        self.status = status

    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
        item = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup is not None:
            item["reply_markup"] = reply_markup
        self.sent.append(item)

    def edit_message_text(self, chat_id, message_id, text, parse_mode=None, reply_markup=None):
        self.sent.append(
            {
                "method": "edit",
                "chat_id": chat_id,
                "message_id": message_id,
                "text": text,
                "parse_mode": parse_mode,
                "reply_markup": reply_markup,
            }
        )

    def answer_callback_query(self, callback_query_id, text=None, show_alert=False):
        self.sent.append(
            {
                "method": "answer_callback_query",
                "callback_query_id": callback_query_id,
                "text": text,
                "show_alert": show_alert,
            }
        )

    def get_chat_member(self, chat_id, user_id):
        return {"status": self.status}


class FailingTelegram:
    def __init__(self, status_code):
        self.status_code = status_code

    def send_message(self, chat_id, text, parse_mode=None, reply_markup=None):
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


def callback(data, chat_id=10, user_id=42, message_id=99, chat_type="group"):
    return {
        "callback_query": {
            "id": "cb-1",
            "from": {"id": user_id, "first_name": "Bob", "last_name": "<Admin>"},
            "message": {
                "message_id": message_id,
                "chat": {"id": chat_id, "type": chat_type},
            },
            "data": data,
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


def test_summarize_splits_long_summary_into_html_chunks():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/summarize"),
        storage,
        telegram,
        summarize_fn=lambda messages, settings: "<b>" + ("x" * 9000) + "</b>",
    )

    assert len(telegram.sent) > 1
    assert all(item["parse_mode"] == ParseMode.HTML for item in telegram.sent)
    assert all(len(item["text"]) <= 4096 for item in telegram.sent)
    assert telegram.sent[0]["text"].startswith('<a href="tg://user?id=42">')
    assert telegram.sent[0]["text"].endswith("</b>")
    assert telegram.sent[1]["text"].startswith("<b>")


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


def test_menu_command_sends_inline_main_menu():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/menu"), storage, telegram)

    assert telegram.sent[0]["chat_id"] == 10
    assert telegram.sent[0]["text"].startswith("Menu")
    assert telegram.sent[0]["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "Summarize",
        "callback_data": "menu:summarize",
    }


def test_callback_query_home_edits_menu_and_answers_spinner():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(callback("menu:home"), storage, telegram)

    assert telegram.sent[0]["method"] == "answer_callback_query"
    assert telegram.sent[1]["method"] == "edit"
    assert telegram.sent[1]["message_id"] == 99
    assert telegram.sent[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"] == (
        "menu:summarize"
    )


def test_summary_button_calls_existing_summary_behavior_with_count():
    storage = FakeStorage(
        messages=[{"user_name": "alice", "text": f"m{i}", "ts": i} for i in range(150)]
    )
    telegram = FakeTelegram()
    captured = {}

    def summarize_fn(messages, settings):
        captured["count"] = len(messages)
        return "summary"

    aws_worker.process_update(
        callback("sum:100"),
        storage,
        telegram,
        summarize_fn=summarize_fn,
        now_fn=lambda: 500,
    )

    assert telegram.sent[0]["method"] == "answer_callback_query"
    assert captured["count"] == 100
    assert "last 100 messages" in telegram.sent[1]["text"]


def test_settings_button_rejects_non_admin_group_users():
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")

    aws_worker.process_update(callback("settings:filter:strict"), storage, telegram)

    assert storage.setting_updates == []
    assert telegram.sent[1]["method"] == "edit"
    assert telegram.sent[1]["text"] == "Only admins can change settings."


def test_admin_setting_button_updates_and_refreshes_settings_menu():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")

    aws_worker.process_update(callback("settings:filter:strict"), storage, telegram)

    assert storage.setting_updates == [(10, "filter_level", "strict")]
    assert telegram.sent[1]["method"] == "edit"
    assert "filter: strict" in telegram.sent[1]["text"]
    assert telegram.sent[1]["reply_markup"]["inline_keyboard"][0][2] == {
        "text": "Strict",
        "callback_data": "settings:filter:strict",
    }


def test_owner_dm_chat_picker_sets_active_chat_and_applies_setting(monkeypatch):
    monkeypatch.setattr(config, "BOT_OWNER_IDS", {42})
    storage = FakeStorage()
    storage.chat_ids = [-1001, -1002]
    telegram = FakeTelegram()

    aws_worker.process_update(
        callback("owner:chats", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )
    aws_worker.process_update(
        callback("owner:chat:-1001", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )
    aws_worker.process_update(
        callback("settings:lang:en", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
    )

    assert storage.owner_active_chat[42] == -1001
    assert storage.setting_updates[-1] == (-1001, "language", "English")
    assert any(item.get("reply_markup") for item in telegram.sent if item.get("method") == "edit")


def test_custom_style_pending_input_is_consumed_without_logging(monkeypatch):
    monkeypatch.setattr(config, "BOT_OWNER_IDS", {42})
    storage = FakeStorage()
    storage.owner_active_chat[42] = -1001
    telegram = FakeTelegram()

    aws_worker.process_update(
        callback("settings:style:custom", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
        now_fn=lambda: 100,
    )
    aws_worker.process_update(
        update("write in haiku", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
        now_fn=lambda: 120,
    )

    assert storage.setting_updates == [(-1001, "style", "write in haiku")]
    assert storage.logged == []
    assert storage.pending == {}


def test_expired_pending_state_leaves_text_logging_unchanged(monkeypatch):
    monkeypatch.setattr(config, "BOT_OWNER_IDS", {42})
    storage = FakeStorage()
    storage.pending[42] = {
        "action": "set_lang_custom",
        "target_chat_id": -1001,
        "created_at": 100,
        "expires_at": 200,
    }
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("hello", chat_id=42, user_id=42, chat_type="private"),
        storage,
        telegram,
        now_fn=lambda: 201,
    )

    assert storage.setting_updates == []
    assert storage.logged[0][4] == "hello"


def test_summarize_auto_selects_messages_by_token_budget(monkeypatch):
    monkeypatch.setattr(config, "MAX_INPUT_TOKENS", 220)
    monkeypatch.setattr(config, "SUMMARY_OUTPUT_TOKENS", 80)
    monkeypatch.setattr(config, "SUMMARY_MAX_MESSAGES", 5000)
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
    assert storage.recent_requests == [(10, 5000)]
    assert "(based on context budget)" in telegram.sent[0]["text"]


def test_summarize_manual_count_clamps_to_summary_max_messages(monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_MAX_MESSAGES", 5000)
    messages = [
        {"user_name": "alice", "text": f"message {ts}", "ts": ts}
        for ts in range(6000)
    ]
    storage = FakeStorage(messages=messages)
    telegram = FakeTelegram()
    captured = {}

    def summarize_fn(selected, settings):
        captured["count"] = len(selected)
        return "summary"

    aws_worker.process_update(
        update("/summarize 999999"),
        storage,
        telegram,
        summarize_fn=summarize_fn,
    )

    assert storage.recent_requests == [(10, 5000)]
    assert captured["count"] == 5000
    assert "last 5000 messages" in telegram.sent[0]["text"]


def test_summarize_auto_uses_summary_max_before_token_selection(monkeypatch):
    monkeypatch.setattr(config, "SUMMARY_MAX_MESSAGES", 7)
    messages = [
        {"user_name": "alice", "text": f"message {ts}", "ts": ts}
        for ts in range(10)
    ]
    storage = FakeStorage(messages=messages)
    telegram = FakeTelegram()
    captured = {}

    def select_messages(candidate_messages, settings):
        captured["candidate_count"] = len(candidate_messages)
        captured["first_ts"] = candidate_messages[0]["ts"]
        return candidate_messages[-3:]

    monkeypatch.setattr(
        aws_worker.llm, "select_messages_for_token_budget", select_messages
    )

    aws_worker.process_update(
        update("/summarize auto"),
        storage,
        telegram,
        summarize_fn=lambda selected, settings: "summary",
    )

    assert storage.recent_requests == [(10, 7)]
    assert captured == {"candidate_count": 7, "first_ts": 3}
    assert "last 3 messages" in telegram.sent[0]["text"]
    assert "(based on context budget)" in telegram.sent[0]["text"]


def test_summarize_retries_smaller_window_when_provider_blocks_large_prompt():
    messages = [
        {"user_name": "alice", "text": f"message {ts}", "ts": ts}
        for ts in range(config.DEFAULT_COUNT + 5)
    ]
    storage = FakeStorage(messages=messages)
    telegram = FakeTelegram()
    calls = []

    def summarize_fn(selected, settings):
        calls.append(len(selected))
        if len(selected) > config.DEFAULT_COUNT:
            raise aws_worker.llm.LLMBlockedError("blocked")
        return "fallback summary"

    aws_worker.process_update(
        update("/summarize 200"),
        storage,
        telegram,
        summarize_fn=summarize_fn,
        now_fn=lambda: 1234,
    )

    assert calls == [config.DEFAULT_COUNT + 5, config.DEFAULT_COUNT]
    assert "fallback summary" in telegram.sent[0]["text"]
    assert "(reduced after Gemini safety block)" in telegram.sent[0]["text"]
    assert storage.usage_logs[0][2] == config.DEFAULT_COUNT


def test_summarize_reports_blocked_prompt_when_no_smaller_fallback_exists():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/summarize"),
        storage,
        telegram,
        summarize_fn=lambda messages, settings: (_ for _ in ()).throw(
            aws_worker.llm.LLMBlockedError("blocked")
        ),
    )

    assert "Gemini blocked this summary request" in telegram.sent[0]["text"]
    assert storage.usage_logs == []


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
