import asyncio
from types import SimpleNamespace

from telegram.constants import ParseMode

from telegram_summarizer import handlers
from telegram_summarizer import storage


class FakeMessage:
    def __init__(self):
        self.replies = []

    async def reply_text(self, text, parse_mode=None):
        self.replies.append({"text": text, "parse_mode": parse_mode})


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
