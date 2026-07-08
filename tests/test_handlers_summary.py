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
