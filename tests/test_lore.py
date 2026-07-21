import pytest

from telegram_summarizer import lore


def test_period_bounds_defaults_to_month_and_rejects_unknown_period():
    assert lore.period_bounds("", 4_000_000) == (
        "month",
        4_000_000 - 30 * 86400,
        4_000_000,
    )
    assert lore.period_bounds("all", 123) == ("all", None, 123)
    with pytest.raises(ValueError):
        lore.period_bounds("quarter", 123)


def test_recap_uses_bounded_period_retrieval(monkeypatch):
    captured = {}

    def ask_history(chat_id, question, storage, settings, **kwargs):
        captured.update(
            chat_id=chat_id,
            question=question,
            storage=storage,
            settings=settings,
            kwargs=kwargs,
        )
        return {"text": "recap"}

    monkeypatch.setattr(lore.history_qa, "ask_history", ask_history)
    result = lore.answer_lore(
        "recap", "week", 7, "storage", {"language": "auto"}, now_fn=lambda: 1_000_000
    )

    assert result == {"text": "recap"}
    assert captured["question"] == "Give a concise friend-chat recap for week."
    assert captured["kwargs"]["start_ts"] == 1_000_000 - 7 * 86400
    assert captured["kwargs"]["end_ts"] == 1_000_000
    assert captured["kwargs"]["evidence_limit"] == 30
    assert captured["kwargs"]["scan_limit"] == 500
    assert captured["kwargs"]["memory_limit"] == 8


def test_quotes_filters_raw_history_by_user(monkeypatch):
    captured = {}

    def ask_history(*args, **kwargs):
        captured.update(kwargs)
        return {"text": "quotes"}

    monkeypatch.setattr(lore.history_qa, "ask_history", ask_history)
    lore.answer_lore("quotes", "Alice", 7, object(), {}, now_fn=lambda: 1)

    assert captured["user"] == "Alice"
    assert captured["query"] == ""


def test_inside_joke_requires_a_search_value():
    with pytest.raises(ValueError):
        lore.answer_lore("insidejoke", "", 7, object(), {}, now_fn=lambda: 1)


def test_quotes_without_user_searches_for_group_quotes(monkeypatch):
    captured = {}

    def ask_history(_chat_id, question, _storage, _settings, **kwargs):
        captured.update(question=question, user=kwargs["user"])
        return {"text": "quotes"}

    monkeypatch.setattr(lore.history_qa, "ask_history", ask_history)
    lore.answer_lore("quotes", "", 7, object(), {}, now_fn=lambda: 1)

    assert captured == {
        "question": "Show the best evidence-backed memorable quotes from the group.",
        "user": None,
    }
