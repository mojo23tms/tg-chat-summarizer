import pytest

from telegram_summarizer import llm
from telegram_summarizer import memory


SETTINGS = {
    "style": "concise",
    "filter_level": "clean",
    "language": "auto",
    "provider": "gemini",
    "model": "gemini-test",
}


class FakeStorage:
    def __init__(self, messages):
        self.messages = messages
        self.saved = []
        self.recent_requests = []

    def recent_messages(self, chat_id, limit):
        self.recent_requests.append((chat_id, limit))
        return self.messages[-limit:]

    def save_memory_snapshot(self, chat_id, snapshot):
        self.saved.append((chat_id, snapshot))


def test_parse_memory_content_normalizes_bounded_structured_json():
    parsed = memory.parse_memory_content(
        """```json
        {"summary":"Old Ibiza lore","items":[
          {"kind":"running_joke","title":"Ibiza","details":"The hotel joke",
           "people":["Alice","Alice"],"keywords":["ibiza"],
           "source_timestamps":[123,"bad",123]},
          {"kind":"unknown","title":"Other","details":"Still useful"},
          {"kind":"quote","title":"","details":"missing title"}
        ]}
        ```"""
    )

    assert parsed["summary"] == "Old Ibiza lore"
    assert len(parsed["items"]) == 2
    assert parsed["items"][0]["people"] == ["Alice"]
    assert parsed["items"][0]["source_timestamps"] == [123]
    assert parsed["items"][1]["kind"] == "other_lore"


def test_parse_memory_content_rejects_invalid_provider_json():
    with pytest.raises(ValueError, match="invalid JSON"):
        memory.parse_memory_content("not json")


def test_generate_snapshot_uses_bounded_messages_and_saves_metadata():
    messages = [
        {"user_name": "Alice", "text": f"message {ts}", "ts": ts}
        for ts in range(1, 7)
    ]
    storage = FakeStorage(messages)
    captured = {}

    def backend(prompt):
        captured["prompt"] = prompt
        return (
            '{"summary":"Ibiza lore","items":[{"kind":"running_joke",'
            '"title":"Ibiza","details":"A recurring hotel joke",'
            '"people":["Alice"],"keywords":["ibiza"],'
            '"source_timestamps":[4]}]}'
        )

    result = memory.generate_snapshot(
        10,
        storage,
        SETTINGS,
        message_limit=3,
        backend_fn=backend,
        now_fn=lambda: 999,
    )

    assert storage.recent_requests == [(10, 3)]
    assert llm.SHARED_SAFETY_INSTRUCTION in captured["prompt"]
    assert "message 4" in captured["prompt"]
    assert "message 1" not in captured["prompt"]
    snapshot = result["snapshot"]
    assert snapshot["created_at"] == 999
    assert snapshot["start_ts"] == 4
    assert snapshot["end_ts"] == 6
    assert snapshot["message_count"] == 3
    assert storage.saved == [(10, snapshot)]
    assert result["source_message_count"] == 3
    assert result["usage"] is not None


def test_generate_snapshot_skips_provider_and_write_without_messages():
    storage = FakeStorage([])
    called = {"count": 0}

    def backend(prompt):
        called["count"] += 1
        return "{}"

    result = memory.generate_snapshot(
        10,
        storage,
        SETTINGS,
        backend_fn=backend,
    )

    assert called["count"] == 0
    assert storage.saved == []
    assert result["snapshot"] is None
    assert result["usage"] is None


def test_generate_snapshot_reports_invalid_json_with_usage_without_writing():
    storage = FakeStorage(
        [{"user_name": "Alice", "text": "old lore", "ts": 1}]
    )

    result = memory.generate_snapshot(
        10,
        storage,
        SETTINGS,
        backend_fn=lambda prompt: "not json",
    )

    assert result["invalid_memory"] is True
    assert result["snapshot"] is None
    assert result["source_message_count"] == 1
    assert result["usage"] is not None
    assert storage.saved == []


def test_memory_token_selection_never_exceeds_input_budget():
    messages = [
        {"user_name": "Alice", "text": "x" * 500, "ts": ts}
        for ts in range(10)
    ]

    selected = llm.select_memory_messages_for_token_budget(
        messages,
        SETTINGS,
        max_input_tokens=900,
        output_tokens=100,
    )

    prompt = llm.build_memory_prompt(selected, SETTINGS)
    assert selected
    assert len(selected) < len(messages)
    assert selected[-1]["ts"] == 9
    assert llm.estimate_tokens(prompt) <= 800
