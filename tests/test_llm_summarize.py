import pytest

import llm


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


def test_summarize_empty_messages_short_circuits():
    called = {"n": 0}

    def fake_backend(prompt):
        called["n"] += 1
        return "x"

    out = llm.summarize([], {"style": "s", "filter_level": "off", "language": "auto"},
                        backend_fn=fake_backend)
    assert out == "Nothing to summarize yet."
    assert called["n"] == 0


def test_default_backend_honors_llm_backend(monkeypatch):
    import config
    monkeypatch.setattr(config, "LLM_BACKEND", "gemini")
    assert llm._default_backend() is llm._gemini_backend
    monkeypatch.setattr(config, "LLM_BACKEND", "groq")
    with pytest.raises(ValueError):
        llm._default_backend()
