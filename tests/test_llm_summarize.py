import pytest

from telegram_summarizer import llm


def test_summarize_uses_injected_backend():
    msgs = [{"user_name": "a", "text": "hello world"}]
    settings = {"style": "s", "filter_level": "off", "language": "auto"}
    captured = {}

    def fake_backend(prompt):
        captured["prompt"] = prompt
        return "SUMMARY TEXT"

    out = llm.summarize(msgs, settings, backend_fn=fake_backend)
    assert out == "SUMMARY TEXT"
    assert "hello world" in captured["prompt"]
    assert "Telegram-compatible HTML" in captured["prompt"]


def test_summarize_empty_messages_short_circuits():
    called = {"n": 0}

    def fake_backend(prompt):
        called["n"] += 1
        return "x"

    out = llm.summarize([], {"style": "s", "filter_level": "off", "language": "auto"},
                        backend_fn=fake_backend)
    assert out == "Nothing to summarize yet."
    assert called["n"] == 0


def test_summarize_with_usage_estimates_for_injected_backend():
    msgs = [{"user_name": "a", "text": "hello world"}]
    settings = {"style": "s", "filter_level": "off", "language": "auto"}

    result = llm.summarize_with_usage(msgs, settings, backend_fn=lambda prompt: "ok")

    assert result["text"] == "ok"
    assert result["usage"]["estimated"] is True
    assert result["usage"]["total_tokens"] > 0


def test_response_text_raises_blocked_error_for_empty_candidates():
    class BlockedResponse:
        prompt_feedback = "block_reason: PROHIBITED_CONTENT"

        @property
        def text(self):
            raise ValueError("response.candidates is empty")

    with pytest.raises(llm.LLMBlockedError, match="PROHIBITED_CONTENT"):
        llm._response_text(BlockedResponse())


def test_select_messages_for_token_budget_keeps_recent_messages():
    settings = {"style": "s", "filter_level": "off", "language": "auto"}
    msgs = [{"user_name": "a", "text": "x" * 80, "ts": ts} for ts in range(5)]

    selected = llm.select_messages_for_token_budget(
        msgs, settings, max_input_tokens=180, output_tokens=50
    )

    assert selected
    assert selected[-1]["ts"] == 4
    assert len(selected) < len(msgs)


def test_default_backend_honors_llm_backend(monkeypatch):
    from telegram_summarizer import config
    monkeypatch.setattr(config, "LLM_BACKEND", "gemini")
    assert llm._default_backend() is llm._gemini_backend
    monkeypatch.setattr(config, "LLM_BACKEND", "groq")
    with pytest.raises(ValueError):
        llm._default_backend()
