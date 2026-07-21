import asyncio
from types import SimpleNamespace

from telegram.constants import ParseMode

from telegram_summarizer import handlers
from telegram_summarizer import storage


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, parse_mode=None, reply_markup=None):
        reply = {"text": text, "parse_mode": parse_mode}
        if reply_markup is not None:
            reply["reply_markup"] = reply_markup
        self.replies.append(reply)


class FakeBot:
    def __init__(self, status="administrator"):
        self.status = status

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.status)


def test_summary_reply_escapes_llm_text_for_html_parse_mode(monkeypatch):
    conn = storage.connect(":memory:")
    storage.log_message(conn, 1, 1, 10, "alice", "hello", 100)

    monkeypatch.setattr(handlers.llm, "summarize", lambda msgs, settings: "2 < 3 & ok")

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42, full_name="Bob <admin>"),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=[])

    asyncio.run(handlers.summarize_handler(update, context))

    assert message.replies == [
        {
            "text": (
                '<a href="tg://user?id=42">Bob &lt;admin&gt;</a>, here is your '
                "summary of the last 1 messages:\n\n2 &lt; 3 &amp; ok"
            ),
            "parse_mode": ParseMode.HTML,
        }
    ]


def test_summary_reply_splits_long_html_output(monkeypatch):
    conn = storage.connect(":memory:")
    storage.log_message(conn, 1, 1, 10, "alice", "hello", 100)

    monkeypatch.setattr(
        handlers.llm, "summarize", lambda msgs, settings: "<b>" + ("x" * 9000) + "</b>"
    )

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42, full_name="Bob <admin>"),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=[])

    asyncio.run(handlers.summarize_handler(update, context))

    assert len(message.replies) > 1
    assert all(reply["parse_mode"] == ParseMode.HTML for reply in message.replies)
    assert all(len(reply["text"]) <= 4096 for reply in message.replies)
    assert message.replies[0]["text"].startswith('<a href="tg://user?id=42">')
    assert message.replies[0]["text"].endswith("</b>")
    assert message.replies[1]["text"].startswith("<b>")


def test_summary_auto_uses_summary_max_before_token_selection(monkeypatch):
    monkeypatch.setattr(handlers.config, "SUMMARY_MAX_MESSAGES", 4)
    conn = storage.connect(":memory:")
    for ts in range(6):
        storage.log_message(conn, 1, ts, 10, "alice", f"message {ts}", ts)

    captured = {}

    def select_messages(candidate_messages, settings):
        captured["candidate_count"] = len(candidate_messages)
        captured["first_ts"] = candidate_messages[0]["ts"]
        return candidate_messages[-2:]

    def summarize(selected, settings):
        captured["selected_count"] = len(selected)
        return "summary"

    monkeypatch.setattr(handlers.llm, "select_messages_for_token_budget", select_messages)
    monkeypatch.setattr(handlers.llm, "summarize", summarize)

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42, full_name="Bob <admin>"),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=["auto"])

    asyncio.run(handlers.summarize_handler(update, context))

    assert captured == {
        "candidate_count": 4,
        "first_ts": 2,
        "selected_count": 2,
    }
    assert "last 2 messages" in message.replies[0]["text"]


def test_chat_handler_sends_safe_html_and_logs_usage(monkeypatch):
    conn = storage.connect(":memory:")
    storage.log_message(conn, 1, 1, 10, "alice", "history should not be read", 100)
    captured = {}

    def chat_with_usage(question, settings):
        captured["question"] = question
        return {
            "text": "<b>Answer</b> 2 < 3",
            "usage": {
                "input_tokens": 4,
                "output_tokens": 2,
                "total_tokens": 6,
                "estimated": True,
                "provider": "gemini",
                "model": "m1",
            },
        }

    monkeypatch.setattr(handlers.llm, "chat_with_usage", chat_with_usage)
    monkeypatch.setattr(handlers.time, "time", lambda: 123)

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=["tell", "me"])

    asyncio.run(handlers.chat_handler(update, context))

    assert captured == {"question": "tell me"}
    assert message.replies == [
        {"text": "<b>Answer</b> 2 &lt; 3", "parse_mode": ParseMode.HTML}
    ]
    rows = conn.execute("SELECT * FROM usage_records").fetchall()
    assert len(rows) == 1
    assert rows[0]["chat_id"] == 1
    assert rows[0]["messages_count"] == 0
    assert rows[0]["total_tokens"] == 6


def test_chat_handler_prompts_for_question():
    conn = storage.connect(":memory:")
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=[])

    asyncio.run(handlers.chat_handler(update, context))

    assert message.replies == [{
        "text": "Send your general question as your next message.",
        "parse_mode": None,
    }]
    assert context.bot_data["pending_commands"][(1, 0)] == "chat"


def test_ask_handler_sends_progress_safe_answer_and_logs_evidence_usage(monkeypatch):
    conn = storage.connect(":memory:")
    storage.log_message(conn, 1, 1, 10, "alice", "history evidence", 100)
    captured = {}

    def ask_history(chat_id, question, page_storage, settings):
        captured["chat_id"] = chat_id
        captured["question"] = question
        first, _cursor = page_storage.message_page(
            chat_id,
            start_ts=0,
            end_ts=200,
            limit=10,
            exclusive_start_key=None,
        )
        captured["evidence"] = first[0]["text"]
        return {
            "text": "<b>Alice</b> said 2 < 3",
            "usage": {
                "input_tokens": 5,
                "output_tokens": 2,
                "total_tokens": 7,
                "estimated": True,
                "provider": "gemini",
                "model": "m1",
            },
            "evidence_count": 1,
        }

    monkeypatch.setattr(handlers.history_qa, "ask_history", ask_history)
    monkeypatch.setattr(handlers.time, "time", lambda: 123)
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=["who", "said", "it?"])

    asyncio.run(handlers.ask_handler(update, context))

    assert captured == {
        "chat_id": 1,
        "question": "who said it?",
        "evidence": "history evidence",
    }
    assert message.replies == [
        {"text": "Searching chat history…", "parse_mode": None},
        {"text": "<b>Alice</b> said 2 &lt; 3", "parse_mode": ParseMode.HTML},
    ]
    usage = conn.execute("SELECT * FROM usage_records").fetchone()
    assert usage["messages_count"] == 1
    assert usage["total_tokens"] == 7


def test_ask_handler_prompts_for_question():
    conn = storage.connect(":memory:")
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=[])

    asyncio.run(handlers.ask_handler(update, context))

    assert message.replies == [{
        "text": "Send your chat-history question as your next message.",
        "parse_mode": None,
    }]
    assert context.bot_data["pending_commands"][(1, 0)] == "ask"


def test_ask_handler_no_evidence_uses_no_quota_record(monkeypatch):
    conn = storage.connect(":memory:")
    monkeypatch.setattr(
        handlers.history_qa,
        "ask_history",
        lambda *args: {
            "text": "I couldn't find relevant messages in the bounded history search.",
            "usage": None,
            "evidence_count": 0,
        },
    )
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=["Atlantis"])

    asyncio.run(handlers.ask_handler(update, context))

    assert "find relevant messages" in message.replies[1]["text"]
    assert conn.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0] == 0


def test_ask_handler_provider_failure_sends_progress_then_error(monkeypatch):
    conn = storage.connect(":memory:")

    def fail(*args):
        raise RuntimeError("provider down")

    monkeypatch.setattr(handlers.history_qa, "ask_history", fail)
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=["broken"])

    asyncio.run(handlers.ask_handler(update, context))

    assert message.replies[0]["text"] == "Searching chat history…"
    assert "history search is unavailable" in message.replies[1]["text"]
    assert conn.execute("SELECT COUNT(*) FROM usage_records").fetchone()[0] == 0


def test_remember_handler_admin_saves_snapshot_and_logs_usage(monkeypatch):
    conn = storage.connect(":memory:")
    storage.log_message(conn, 1, 1, 10, "Alice", "Ibiza joke", 100)
    captured = {}

    def generate_snapshot(chat_id, adapter, settings, message_limit):
        captured.update({"chat_id": chat_id, "limit": message_limit})
        snapshot = {
            "version": 1,
            "created_at": 123,
            "start_ts": 100,
            "end_ts": 100,
            "message_count": 1,
            "summary": "Ibiza lore",
            "items": [{"kind": "running_joke"}],
        }
        adapter.save_memory_snapshot(chat_id, snapshot)
        return {
            "snapshot": snapshot,
            "source_message_count": 1,
            "usage": {
                "input_tokens": 5,
                "output_tokens": 2,
                "total_tokens": 7,
                "estimated": True,
                "provider": "gemini",
                "model": "m1",
            },
        }

    monkeypatch.setattr(handlers.memory, "generate_snapshot", generate_snapshot)
    monkeypatch.setattr(handlers.time, "time", lambda: 456)
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42),
        effective_message=message,
    )
    context = SimpleNamespace(
        bot_data={"conn": conn}, args=["20"], bot=FakeBot("administrator")
    )

    asyncio.run(handlers.remember_handler(update, context))

    assert captured == {"chat_id": 1, "limit": 20}
    assert message.replies[0]["text"] == "Building a memory snapshot…"
    assert message.replies[1]["text"] == (
        "Saved a memory snapshot from 1 messages with 1 lore items."
    )
    assert conn.execute("SELECT COUNT(*) FROM memory_snapshots").fetchone()[0] == 1
    usage = conn.execute("SELECT * FROM usage_records").fetchone()
    assert usage["messages_count"] == 1
    assert usage["total_tokens"] == 7


def test_remember_handler_rejects_non_admin_without_provider_call(monkeypatch):
    conn = storage.connect(":memory:")
    called = {"count": 0}
    monkeypatch.setattr(
        handlers.memory,
        "generate_snapshot",
        lambda *args, **kwargs: called.update(count=called["count"] + 1),
    )
    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42),
        effective_message=message,
    )
    context = SimpleNamespace(
        bot_data={"conn": conn}, args=[], bot=FakeBot("member")
    )

    asyncio.run(handlers.remember_handler(update, context))

    assert called["count"] == 0
    assert message.replies == [
        {"text": "Only admins can build memory snapshots.", "parse_mode": None}
    ]


def test_models_handler_reports_current_provider_model():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "provider", "groq")
    storage.set_setting(conn, 1, "model", "llama-test")

    message = FakeMessage()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_message=message)
    context = SimpleNamespace(bot_data={"conn": conn})

    asyncio.run(handlers.models_handler(update, context))

    assert "Current: groq:llama-test" in message.replies[0]["text"]


def test_setprovider_handler_updates_provider_and_resets_model():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "model", "old-model")

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42),
        effective_message=message,
    )
    context = SimpleNamespace(bot_data={"conn": conn}, args=["groq"], bot=FakeBot())

    asyncio.run(handlers.setprovider_handler(update, context))

    settings = storage.get_settings(conn, 1)
    assert settings["provider"] == "groq"
    assert settings["model"] == ""
    assert "Updated provider to: groq" in message.replies[0]["text"]


def test_setmodel_handler_accepts_provider_prefix():
    conn = storage.connect(":memory:")

    message = FakeMessage()
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=1),
        effective_user=SimpleNamespace(id=42),
        effective_message=message,
    )
    context = SimpleNamespace(
        bot_data={"conn": conn}, args=["groq:llama-test"], bot=FakeBot()
    )

    asyncio.run(handlers.setmodel_handler(update, context))

    settings = storage.get_settings(conn, 1)
    assert settings["provider"] == "groq"
    assert settings["model"] == "llama-test"
    assert "Updated model to: groq:llama-test" in message.replies[0]["text"]


def test_help_handler_reports_current_commands_and_model():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "provider", "groq")
    storage.set_setting(conn, 1, "model", "llama-test")

    message = FakeMessage()
    update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_message=message)
    context = SimpleNamespace(bot_data={"conn": conn})

    asyncio.run(handlers.help_handler(update, context))

    assert "/chat &lt;question&gt;" in message.replies[0]["text"]
    assert "/ask &lt;question&gt;" in message.replies[0]["text"]
    assert "/remember [N|auto]" in message.replies[0]["text"]
    assert "/summarize [N|auto]" in message.replies[0]["text"]
    assert "/setprovider gemini|groq" in message.replies[0]["text"]
    assert "Current LLM: <code>groq:llama-test</code>" in message.replies[0]["text"]
    assert message.replies[0]["parse_mode"] == ParseMode.HTML
    assert message.replies[0]["reply_markup"].is_persistent is True
