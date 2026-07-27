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
        self.quota_warnings = set()

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
        if not usage:
            return
        self.usage_logs.append((chat_id, usage, messages_count, ts))

    def usage_totals(self, chat_id, since_ts=None, provider=None, model=None):
        matching_usage = []
        for logged_chat_id, usage, _messages_count, ts in self.usage_logs:
            if logged_chat_id != chat_id:
                continue
            if since_ts is not None and ts is not None and ts < since_ts:
                continue
            if provider is not None and usage.get("provider") != provider:
                continue
            if model is not None and usage.get("model") != model:
                continue
            matching_usage.append(usage)
        if matching_usage:
            return {
                "requests": len(matching_usage),
                "messages_count": 0,
                "input_tokens": sum(item.get("input_tokens", 0) for item in matching_usage),
                "output_tokens": sum(item.get("output_tokens", 0) for item in matching_usage),
                "total_tokens": sum(item.get("total_tokens", 0) for item in matching_usage),
                "estimated_records": sum(1 for item in matching_usage if item.get("estimated", True)),
            }
        return {
            "requests": 2,
            "messages_count": 30,
            "input_tokens": 1000,
            "output_tokens": 200,
            "total_tokens": 1200,
            "estimated_records": 1,
        }

    def quota_warning_sent(self, chat_id, provider, day):
        return (chat_id, provider, day) in self.quota_warnings

    def mark_quota_warning_sent(self, chat_id, provider, day, ts=None):
        self.quota_warnings.add((chat_id, provider, day))

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


def test_summarize_warns_once_when_provider_quota_is_low(monkeypatch):
    monkeypatch.setattr(config, "DAILY_TOKEN_QUOTAS", {"gemini": 100, "groq": 0})
    monkeypatch.setattr(config, "QUOTA_WARNING_REMAINING_PERCENT", 10)
    usage = {
        "input_tokens": 80,
        "output_tokens": 10,
        "total_tokens": 90,
        "estimated": False,
        "provider": "gemini",
        "model": "m1",
    }
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "hi", "ts": 1}])
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/summarize"),
        storage,
        telegram,
        summarize_fn=lambda messages, settings: {
            "text": "summary",
            "usage": usage,
            "provider": "gemini",
            "model": "m1",
        },
        now_fn=lambda: 1735732800,
    )
    aws_worker.process_update(
        update("/summarize", message_id=8),
        storage,
        telegram,
        summarize_fn=lambda messages, settings: {
            "text": "summary",
            "usage": usage,
            "provider": "gemini",
            "model": "m1",
        },
        now_fn=lambda: 1735732801,
    )

    warnings = [item for item in telegram.sent if item["text"].startswith("Quota warning")]
    assert len(warnings) == 1
    assert "gemini" in warnings[0]["text"]
    assert "10 of 100" in warnings[0]["text"]


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


def test_chat_uses_injected_llm_sends_safe_html_and_logs_usage():
    storage = FakeStorage(messages=[{"user_name": "alice", "text": "secret history", "ts": 1}])
    telegram = FakeTelegram()
    captured = {}

    def chat_fn(question, settings):
        captured["question"] = question
        return {
            "text": "<b>Answer</b> 2 < 3",
            "usage": {
                "input_tokens": 10,
                "output_tokens": 3,
                "total_tokens": 13,
                "estimated": False,
                "provider": "gemini",
                "model": "m1",
            },
            "provider": "gemini",
            "model": "m1",
            "usage_estimated": False,
        }

    aws_worker.process_update(
        update("/chat explain this"),
        storage,
        telegram,
        chat_fn=chat_fn,
        now_fn=lambda: 123,
    )

    assert captured == {"question": "explain this"}
    assert storage.recent_requests == []
    assert telegram.sent[0] == {
        "chat_id": 10,
        "text": "<b>Answer</b> 2 &lt; 3",
        "parse_mode": ParseMode.HTML,
    }
    assert storage.usage_logs == [
        (
            10,
            {
                "input_tokens": 10,
                "output_tokens": 3,
                "total_tokens": 13,
                "estimated": False,
                "provider": "gemini",
                "model": "m1",
            },
            0,
            123,
        )
    ]


def test_chat_without_question_prompts_for_next_message():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/chat"), storage, telegram)

    assert telegram.sent == [{
        "chat_id": 10,
        "text": "Send your general question as your next message.",
        "parse_mode": None,
    }]
    assert storage.pending[42]["action"] == "run_chat"
    assert storage.usage_logs == []


def test_chat_splits_long_html_output():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/chat long"),
        storage,
        telegram,
        chat_fn=lambda question, settings: "<b>" + ("x" * 9000) + "</b>",
    )

    assert len(telegram.sent) > 1
    assert all(item["parse_mode"] == ParseMode.HTML for item in telegram.sent)
    assert all(len(item["text"]) <= 4096 for item in telegram.sent)
    assert telegram.sent[0].get("text", "").endswith("</b>")
    assert telegram.sent[1].get("text", "").startswith("<b>")


def test_ask_uses_current_chat_sends_progress_safe_html_and_logs_evidence_usage():
    storage = FakeStorage()
    telegram = FakeTelegram()
    captured = {}
    usage = {
        "input_tokens": 10,
        "output_tokens": 3,
        "total_tokens": 13,
        "estimated": False,
        "provider": "gemini",
        "model": "m1",
    }

    def ask_fn(question, chat_id, selected_storage, settings):
        captured.update(
            {
                "question": question,
                "chat_id": chat_id,
                "storage": selected_storage,
            }
        )
        return {
            "text": "<b>Alice</b> said 2 < 3",
            "usage": usage,
            "evidence_count": 4,
        }

    aws_worker.process_update(
        update("/ask who said it?", chat_id=-1001),
        storage,
        telegram,
        ask_fn=ask_fn,
        now_fn=lambda: 123,
    )

    assert captured == {
        "question": "who said it?",
        "chat_id": -1001,
        "storage": storage,
    }
    assert telegram.sent[:2] == [
        {
            "chat_id": -1001,
            "text": "Searching chat history…",
            "parse_mode": None,
        },
        {
            "chat_id": -1001,
            "text": "<b>Alice</b> said 2 &lt; 3",
            "parse_mode": ParseMode.HTML,
        },
    ]
    assert storage.usage_logs == [(-1001, usage, 4, 123)]


def test_ask_without_question_prompts_for_next_message():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/ask"), storage, telegram)

    assert telegram.sent == [{
        "chat_id": 10,
        "text": "Send your chat-history question as your next message.",
        "parse_mode": None,
    }]
    assert storage.pending[42]["action"] == "run_ask"
    assert storage.usage_logs == []


def test_ask_no_evidence_reply_does_not_log_usage():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/ask Atlantis"),
        storage,
        telegram,
        ask_fn=lambda question, chat_id, selected_storage, settings: {
            "text": "I couldn't find relevant messages in the bounded history search.",
            "usage": None,
            "evidence_count": 0,
        },
        now_fn=lambda: 123,
    )

    assert "find relevant messages" in telegram.sent[1]["text"]
    assert storage.usage_logs == []


def test_ask_failure_sends_progress_then_retryable_error():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/ask broken"),
        storage,
        telegram,
        ask_fn=lambda *args: (_ for _ in ()).throw(RuntimeError("provider down")),
    )

    assert telegram.sent[0]["text"] == "Searching chat history…"
    assert "history search is unavailable" in telegram.sent[1]["text"]
    assert storage.usage_logs == []


def test_ask_blocked_response_has_specific_message():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/ask blocked"),
        storage,
        telegram,
        ask_fn=lambda *args: (_ for _ in ()).throw(
            aws_worker.llm.LLMBlockedError("blocked")
        ),
    )

    assert telegram.sent[0]["text"] == "Searching chat history…"
    assert "blocked this history question" in telegram.sent[1]["text"]
    assert storage.usage_logs == []


def test_ask_splits_long_html_output():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(
        update("/ask long"),
        storage,
        telegram,
        ask_fn=lambda *args: {
            "text": "<b>" + ("x" * 9000) + "</b>",
            "usage": None,
            "evidence_count": 1,
        },
    )

    answers = telegram.sent[1:]
    assert len(answers) > 1
    assert all(item["parse_mode"] == ParseMode.HTML for item in answers)
    assert all(len(item["text"]) <= 4096 for item in answers)


def test_remember_admin_builds_snapshot_and_logs_usage(monkeypatch):
    monkeypatch.setattr(config, "MEMORY_MAX_MESSAGES", 500)
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")
    captured = {}
    usage = {
        "input_tokens": 20,
        "output_tokens": 5,
        "total_tokens": 25,
        "estimated": False,
        "provider": "gemini",
        "model": "m1",
    }

    def remember_fn(chat_id, selected_storage, settings, message_limit):
        captured.update({"chat_id": chat_id, "limit": message_limit})
        return {
            "snapshot": {"message_count": 123, "items": [{"kind": "running_joke"}]},
            "source_message_count": 123,
            "usage": usage,
        }

    aws_worker.process_update(
        update("/remember 999"),
        storage,
        telegram,
        remember_fn=remember_fn,
        now_fn=lambda: 456,
    )

    assert captured == {"chat_id": 10, "limit": 500}
    assert telegram.sent[0]["text"] == "Building a memory snapshot…"
    assert telegram.sent[1]["text"] == (
        "Saved a memory snapshot from 123 messages with 1 lore items."
    )
    assert storage.usage_logs == [(10, usage, 123, 456)]


def test_remember_rejects_non_admin_without_calling_provider():
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")
    called = {"count": 0}

    aws_worker.process_update(
        update("/remember"),
        storage,
        telegram,
        remember_fn=lambda *args: called.update(count=called["count"] + 1),
    )

    assert called["count"] == 0
    assert telegram.sent[0]["text"] == "Only admins can build memory snapshots."


def test_remember_reports_invalid_provider_snapshot():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")

    aws_worker.process_update(
        update("/remember auto"),
        storage,
        telegram,
        remember_fn=lambda *args: (_ for _ in ()).throw(ValueError("bad json")),
    )

    assert telegram.sent[0]["text"] == "Building a memory snapshot…"
    assert "invalid memory snapshot" in telegram.sent[1]["text"]
    assert storage.usage_logs == []


def test_remember_logs_usage_when_provider_returns_invalid_json():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")
    usage = {
        "input_tokens": 10,
        "output_tokens": 2,
        "total_tokens": 12,
        "estimated": False,
        "provider": "gemini",
        "model": "m1",
    }

    aws_worker.process_update(
        update("/remember"),
        storage,
        telegram,
        remember_fn=lambda *args: {
            "snapshot": None,
            "source_message_count": 5,
            "invalid_memory": True,
            "usage": usage,
        },
        now_fn=lambda: 123,
    )

    assert "invalid memory snapshot" in telegram.sent[1]["text"]
    assert storage.usage_logs == [(10, usage, 5, 123)]


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


def test_settings_command_reports_provider_and_model():
    storage = FakeStorage(settings={**config.DEFAULTS, "provider": "groq", "model": "m1"})
    telegram = FakeTelegram()

    aws_worker.process_update(update("/settings"), storage, telegram)

    assert "provider: groq" in telegram.sent[0]["text"]
    assert "model: m1" in telegram.sent[0]["text"]


def test_models_command_lists_current_provider_model():
    storage = FakeStorage(settings={**config.DEFAULTS, "provider": "groq", "model": "m1"})
    telegram = FakeTelegram()

    aws_worker.process_update(update("/models"), storage, telegram)

    assert "gemini" in telegram.sent[0]["text"]
    assert "groq" in telegram.sent[0]["text"]
    assert "Current: groq:m1" in telegram.sent[0]["text"]


def test_setprovider_updates_provider_and_resets_model_for_admin():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")

    aws_worker.process_update(update("/setprovider groq"), storage, telegram)

    assert storage.setting_updates == [(10, "provider", "groq"), (10, "model", "")]
    assert "Updated provider to: groq" in telegram.sent[0]["text"]
    assert "Using default model" in telegram.sent[0]["text"]


def test_setprovider_rejects_non_admin_users():
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")

    aws_worker.process_update(update("/setprovider groq"), storage, telegram)

    assert storage.setting_updates == []
    assert telegram.sent == [
        {"chat_id": 10, "text": "Only admins can change settings.", "parse_mode": None}
    ]


def test_setmodel_updates_provider_when_prefix_is_supplied():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")

    aws_worker.process_update(update("/setmodel groq:llama-test"), storage, telegram)

    assert storage.setting_updates == [
        (10, "provider", "groq"),
        (10, "model", "llama-test"),
    ]
    assert "Updated model to: groq:llama-test" in telegram.sent[0]["text"]


def test_usage_command_reports_totals():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/usage today"), storage, telegram, now_fn=lambda: 1000)

    assert "requests: 2" in telegram.sent[0]["text"]
    assert "total tokens: 1200" in telegram.sent[0]["text"]


def test_usage_command_lists_all_supported_periods_on_invalid_input():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/usage week"), storage, telegram)

    assert telegram.sent[0]["text"] == "Usage: /usage [today|month|all]"


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


def test_menu_command_sends_compact_launcher_and_inline_home():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(update("/menu"), storage, telegram)

    assert telegram.sent[0]["chat_id"] == 10
    assert telegram.sent[0]["reply_markup"]["keyboard"] == [[{"text": "☰ Menu"}]]
    assert telegram.sent[0]["reply_markup"]["is_persistent"] is True
    assert telegram.sent[1]["text"].startswith("Menu")
    assert telegram.sent[1]["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "💬 Conversation",
        "callback_data": "menu:conversation",
    }


def test_callback_query_home_edits_menu_and_answers_spinner():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(callback("menu:home"), storage, telegram)

    assert telegram.sent[0]["method"] == "answer_callback_query"
    assert telegram.sent[1]["method"] == "edit"
    assert telegram.sent[1]["message_id"] == 99
    assert (
        telegram.sent[1]["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        == "menu:conversation"
    )


def test_inline_conversation_menu_prompts_for_ask_input():
    storage = FakeStorage()
    telegram = FakeTelegram()

    aws_worker.process_update(callback("menu:conversation"), storage, telegram)
    aws_worker.process_update(
        callback("action:ask"), storage, telegram, now_fn=lambda: 100
    )

    assert telegram.sent[1]["reply_markup"]["inline_keyboard"][0][0] == {
        "text": "🧠 Ask history",
        "callback_data": "action:ask",
    }
    assert storage.pending[42]["action"] == "run_ask"
    assert telegram.sent[-1]["text"] == "Send your chat-history question as your next message."


def test_inline_remember_action_preserves_admin_permission_check():
    storage = FakeStorage()
    telegram = FakeTelegram(status="member")

    aws_worker.process_update(callback("action:remember"), storage, telegram)

    assert telegram.sent[-1]["text"] == "Only admins can build memory snapshots."


def test_help_command_reports_actual_commands_and_current_model():
    storage = FakeStorage(settings={**config.DEFAULTS, "provider": "groq", "model": "m1"})
    telegram = FakeTelegram()

    aws_worker.process_update(update("/help"), storage, telegram)

    assert "/chat &lt;question&gt;" in telegram.sent[0]["text"]
    assert "/ask &lt;question&gt;" in telegram.sent[0]["text"]
    assert "/remember [N|auto]" in telegram.sent[0]["text"]
    assert "/summarize [N|auto]" in telegram.sent[0]["text"]
    assert "/setprovider gemini|groq" in telegram.sent[0]["text"]
    assert "Current LLM: <code>groq:m1</code>" in telegram.sent[0]["text"]
    assert telegram.sent[0]["parse_mode"] == ParseMode.HTML
    assert telegram.sent[0]["reply_markup"]["keyboard"] == [[{"text": "☰ Menu"}]]


def test_lore_command_uses_shared_handler_and_logs_usage():
    storage = FakeStorage()
    telegram = FakeTelegram()
    captured = {}

    def lore_fn(command, argument, chat_id, passed_storage, settings):
        captured.update(command=command, argument=argument, chat_id=chat_id)
        return {
            "text": "<b>Lore</b> 2 < 3",
            "evidence_count": 4,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 2,
                "total_tokens": 7,
                "provider": "gemini",
                "model": "m1",
            },
        }

    aws_worker.process_update(
        update("/recap week"),
        storage,
        telegram,
        lore_fn=lore_fn,
        now_fn=lambda: 500,
    )

    assert captured == {"command": "recap", "argument": "week", "chat_id": 10}
    assert telegram.sent[0]["text"] == "Searching chat lore…"
    assert telegram.sent[1]["text"] == "<b>Lore</b> 2 &lt; 3"
    assert telegram.sent[1]["parse_mode"] == ParseMode.HTML
    assert storage.usage_logs[0][2] == 4


def test_inside_joke_button_collects_next_message_as_search_term():
    storage = FakeStorage()
    telegram = FakeTelegram()
    calls = []

    def lore_fn(command, argument, *_args):
        calls.append((command, argument))
        return {"text": "found", "evidence_count": 1, "usage": None}

    aws_worker.process_update(
        update("😂 Inside joke"), storage, telegram, lore_fn=lore_fn, now_fn=lambda: 100
    )
    aws_worker.process_update(
        update("Ibiza hotel"), storage, telegram, lore_fn=lore_fn, now_fn=lambda: 101
    )

    assert "next message" in telegram.sent[0]["text"]
    assert calls == [("insidejoke", "Ibiza hotel")]
    assert storage.logged == []


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
        "text": "🔒 Strict",
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
    assert "(reduced after model safety block)" in telegram.sent[0]["text"]
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

    assert "The selected model blocked this summary request" in telegram.sent[0]["text"]
    assert storage.usage_logs == []


def test_handle_sqs_event_routes_records():
    storage = FakeStorage()
    telegram = FakeTelegram()
    event = {"Records": [{"body": json.dumps(update("hello"))}]}

    aws_worker.handle_sqs_event(event, storage, telegram, now_fn=lambda: 555)

    assert storage.logged[0][-1] == 555


def test_handle_sqs_event_passes_ask_dependency():
    storage = FakeStorage()
    telegram = FakeTelegram()
    calls = []
    event = {"Records": [{"body": json.dumps(update("/ask old joke"))}]}

    aws_worker.handle_sqs_event(
        event,
        storage,
        telegram,
        ask_fn=lambda question, chat_id, selected_storage, settings: (
            calls.append((question, chat_id))
            or {"text": "answer", "usage": None, "evidence_count": 1}
        ),
    )

    assert calls == [("old joke", 10)]
    assert telegram.sent[1]["text"] == "answer"


def test_handle_sqs_event_passes_remember_dependency():
    storage = FakeStorage()
    telegram = FakeTelegram(status="administrator")
    calls = []
    event = {"Records": [{"body": json.dumps(update("/remember 20"))}]}

    aws_worker.handle_sqs_event(
        event,
        storage,
        telegram,
        remember_fn=lambda chat_id, selected_storage, settings, limit: (
            calls.append((chat_id, limit))
            or {
                "snapshot": {"message_count": 20, "items": []},
                "source_message_count": 20,
                "usage": None,
            }
        ),
    )

    assert calls == [(10, 20)]
    assert telegram.sent[1]["text"] == (
        "Saved a memory snapshot from 20 messages with 0 lore items."
    )


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
