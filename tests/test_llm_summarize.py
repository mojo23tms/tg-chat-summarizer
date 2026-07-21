import json
import sys
import types

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
    assert "Telegram-compatible HTML only" in captured["prompt"]


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
    assert result["provider"] == "gemini"
    assert result["model"] == llm.GEMINI_MODEL
    assert result["usage"]["estimated"] is True
    assert result["usage"]["provider"] == "gemini"
    assert result["usage"]["total_tokens"] > 0


def test_summarize_with_usage_preserves_structured_provider_result():
    msgs = [{"user_name": "a", "text": "hello world"}]
    settings = {
        "style": "s",
        "filter_level": "off",
        "language": "auto",
        "provider": "groq",
        "model": "llama-test",
    }

    result = llm.summarize_with_usage(
        msgs,
        settings,
        backend_fn=lambda prompt: llm.LLMResult(
            text="ok",
            provider="groq",
            model="llama-test",
            usage={
                "input_tokens": 1,
                "output_tokens": 2,
                "total_tokens": 3,
                "estimated": False,
            },
            usage_estimated=False,
            finish_reason="stop",
        ),
    )

    assert result["provider"] == "groq"
    assert result["model"] == "llama-test"
    assert result["finish_reason"] == "stop"
    assert result["usage_estimated"] is False
    assert result["usage"]["provider"] == "groq"
    assert result["usage"]["model"] == "llama-test"


def test_summarize_routes_through_selected_provider(monkeypatch):
    msgs = [{"user_name": "a", "text": "hello world"}]
    settings = {
        "style": "s",
        "filter_level": "off",
        "language": "auto",
        "provider": "groq",
        "model": "llama-test",
    }
    captured = {}

    def fake_generate(prompt, selected_settings):
        captured["settings"] = selected_settings
        return llm.LLMResult("ok", "groq", "llama-test")

    monkeypatch.setattr(llm, "generate", fake_generate)

    assert llm.summarize(msgs, settings) == "ok"
    assert captured["settings"] is settings


def test_chat_with_usage_routes_through_selected_provider(monkeypatch):
    settings = {
        "style": "s",
        "filter_level": "off",
        "language": "auto",
        "provider": "groq",
        "model": "llama-test",
    }
    captured = {}

    def fake_generate(prompt, selected_settings):
        captured["prompt"] = prompt
        captured["settings"] = selected_settings
        return llm.LLMResult(
            "answer",
            "groq",
            "llama-test",
            usage={
                "input_tokens": 5,
                "output_tokens": 2,
                "total_tokens": 7,
                "estimated": False,
            },
            usage_estimated=False,
        )

    monkeypatch.setattr(llm, "generate", fake_generate)

    result = llm.chat_with_usage("help me", settings)

    assert result["text"] == "answer"
    assert result["provider"] == "groq"
    assert result["model"] == "llama-test"
    assert result["usage"]["provider"] == "groq"
    assert result["usage"]["model"] == "llama-test"
    assert result["usage_estimated"] is False
    assert "<user_question>\nhelp me\n</user_question>" in captured["prompt"]
    assert captured["settings"] is settings


def test_chat_empty_question_short_circuits():
    called = {"n": 0}

    def fake_backend(prompt):
        called["n"] += 1
        return "x"

    result = llm.chat_with_usage(
        "",
        {"style": "s", "filter_level": "off", "language": "auto"},
        backend_fn=fake_backend,
    )

    assert result["text"] == "Ask me something after /chat."
    assert result["usage"] is None
    assert called["n"] == 0


def test_ask_with_usage_uses_selected_provider_and_retrieved_messages(monkeypatch):
    settings = {
        "style": "s",
        "filter_level": "clean",
        "language": "auto",
        "provider": "groq",
        "model": "llama-test",
    }
    messages = [{"user_name": "Alice", "text": "the evidence", "ts": 123}]
    captured = {}

    def fake_generate(prompt, selected_settings, max_output_tokens=None):
        captured["prompt"] = prompt
        captured["settings"] = selected_settings
        captured["max_output_tokens"] = max_output_tokens
        return llm.LLMResult(
            "grounded answer",
            "groq",
            "llama-test",
            usage={
                "input_tokens": 9,
                "output_tokens": 3,
                "total_tokens": 12,
                "estimated": False,
            },
            usage_estimated=False,
        )

    monkeypatch.setattr(llm, "generate", fake_generate)

    result = llm.ask_with_usage(
        "What happened?",
        messages,
        settings,
        retrieval_truncated=False,
    )

    assert result["text"] == "grounded answer"
    assert result["provider"] == "groq"
    assert result["model"] == "llama-test"
    assert result["usage"]["total_tokens"] == 12
    assert "the evidence" in captured["prompt"]
    assert captured["settings"] is settings
    assert captured["max_output_tokens"] == llm.config.ASK_OUTPUT_TOKENS


def test_ask_without_evidence_short_circuits_without_provider_call():
    called = {"n": 0}

    def backend(prompt):
        called["n"] += 1
        return "x"

    result = llm.ask_with_usage(
        "What happened?",
        [],
        {"style": "s", "filter_level": "off", "language": "auto"},
        backend_fn=backend,
    )

    assert "couldn't find relevant messages" in result["text"]
    assert result["usage"] is None
    assert called["n"] == 0


def test_ask_evidence_selection_respects_input_token_budget():
    settings = {"style": "s", "filter_level": "clean", "language": "auto"}
    messages = [
        {"user_name": "Alice", "text": "x" * 600, "ts": ts}
        for ts in range(8)
    ]

    selected = llm.select_ask_evidence_for_token_budget(
        "What happened?",
        messages,
        settings,
        max_input_tokens=900,
        output_tokens=100,
    )

    prompt = llm.build_ask_prompt("What happened?", selected, settings)
    assert selected
    assert len(selected) < len(messages)
    assert llm.estimate_tokens(prompt) <= 800
    assert selected[-1]["ts"] == 7


def test_ask_caps_provider_output_tokens(monkeypatch):
    settings = {
        "style": "s",
        "filter_level": "off",
        "language": "auto",
        "provider": "gemini",
        "model": "gemini-test",
    }
    messages = [{"user_name": "Alice", "text": "It happened.", "ts": 1}]
    captured = {}

    def fake_generate(prompt, selected_settings, max_output_tokens=None):
        captured["max_output_tokens"] = max_output_tokens
        return llm.LLMResult("answer", "gemini", "gemini-test")

    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(llm.config, "ASK_OUTPUT_TOKENS", 321)

    result = llm.ask_with_usage("What happened?", messages, settings)

    assert result["text"] == "answer"
    assert captured["max_output_tokens"] == 321


def test_memory_generation_caps_provider_output_tokens(monkeypatch):
    settings = {
        "style": "s",
        "filter_level": "off",
        "language": "auto",
        "provider": "gemini",
        "model": "gemini-test",
    }
    messages = [{"user_name": "Alice", "text": "old lore", "ts": 1}]
    captured = {}

    def fake_generate(prompt, selected_settings, max_output_tokens=None):
        captured["max_output_tokens"] = max_output_tokens
        return llm.LLMResult('{"summary":"lore","items":[]}', "gemini", "gemini-test")

    monkeypatch.setattr(llm, "generate", fake_generate)
    monkeypatch.setattr(llm.config, "MEMORY_OUTPUT_TOKENS", 654)

    result = llm.memory_with_usage(messages, settings)

    assert result["text"].startswith("{")
    assert captured["max_output_tokens"] == 654


def test_ask_context_budget_accounts_for_memories_and_raw_messages():
    settings = {"style": "s", "filter_level": "clean", "language": "auto"}
    messages = [
        {"user_name": "Alice", "text": "raw " + ("x" * 300), "ts": ts}
        for ts in range(5)
    ]
    memories = [
        {"created_at": ts, "summary": "memory " + ("y" * 300), "items": []}
        for ts in range(5)
    ]

    selected_messages, selected_memories = llm.select_ask_context_for_token_budget(
        "What happened?",
        messages,
        memories,
        settings,
        max_input_tokens=1200,
        output_tokens=100,
    )

    prompt = llm.build_ask_prompt(
        "What happened?",
        selected_messages,
        settings,
        memories=selected_memories,
    )
    assert selected_messages
    assert selected_memories
    assert len(selected_messages) + len(selected_memories) < 10
    assert llm.estimate_tokens(prompt) <= 1100


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


def test_default_backend_honors_default_provider(monkeypatch):
    from telegram_summarizer import config
    monkeypatch.setattr(config, "DEFAULT_LLM_PROVIDER", "gemini")
    assert llm._default_backend() is llm._gemini_backend
    monkeypatch.setattr(config, "DEFAULT_LLM_PROVIDER", "bogus")
    with pytest.raises(ValueError):
        llm._default_backend()


def test_provider_model_selection_accepts_provider_prefix():
    provider, model = llm.parse_model_selection("groq:llama-test", "gemini")

    assert provider == "groq"
    assert model == "llama-test"


def test_gemini_generate_uses_configured_request_timeout(monkeypatch):
    captured = {}
    fake = types.ModuleType("google.generativeai")

    def configure(api_key=None):
        captured["key"] = api_key

    class FakeModel:
        def __init__(self, name):
            captured["model"] = name

        def generate_content(self, prompt, request_options=None):
            captured["prompt"] = prompt
            captured["request_options"] = request_options
            return types.SimpleNamespace(text="  hello  ", candidates=[])

    fake.configure = configure
    fake.GenerativeModel = FakeModel
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)
    monkeypatch.setattr(llm.config, "LLM_REQUEST_TIMEOUT_SECONDS", 12)

    result = llm._gemini_generate("prompt", model="gemini-test")

    assert captured["model"] == "gemini-test"
    assert captured["request_options"] == {"timeout": 12}
    assert result.text == "hello"


def test_gemini_generate_passes_optional_output_limit(monkeypatch):
    captured = {}
    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda api_key=None: None

    class FakeModel:
        def __init__(self, name):
            pass

        def generate_content(
            self, prompt, request_options=None, generation_config=None
        ):
            captured["generation_config"] = generation_config
            return types.SimpleNamespace(text="answer", candidates=[])

    fake.GenerativeModel = FakeModel
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)

    llm._gemini_generate("prompt", max_output_tokens=321)

    assert captured["generation_config"] == {"max_output_tokens": 321}


def test_gemini_generate_wraps_transient_cancellation_without_retry(monkeypatch):
    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda api_key=None: None
    calls = []

    class Cancelled(Exception):
        pass

    class FakeModel:
        def __init__(self, name):
            pass

        def generate_content(self, prompt, **kwargs):
            calls.append(prompt)
            raise Cancelled("operation cancelled")

    fake.GenerativeModel = FakeModel
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)

    with pytest.raises(llm.LLMTransientError, match="transient provider error"):
        llm._gemini_generate("prompt")

    assert calls == ["prompt"]


def test_gemini_generate_does_not_retry_non_transient_errors(monkeypatch):
    fake = types.ModuleType("google.generativeai")
    fake.configure = lambda api_key=None: None
    calls = []

    class FakeModel:
        def __init__(self, name):
            pass

        def generate_content(self, prompt, **kwargs):
            calls.append(prompt)
            raise ValueError("bad request")

    fake.GenerativeModel = FakeModel
    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)

    with pytest.raises(ValueError, match="bad request"):
        llm._gemini_generate("prompt")

    assert calls == ["prompt"]


def test_groq_generate_posts_chat_completion_and_parses_usage(monkeypatch):
    monkeypatch.setattr("telegram_summarizer.config.GROQ_API_KEY", "secret")
    monkeypatch.setattr("telegram_summarizer.config.LLM_REQUEST_TIMEOUT_SECONDS", 12)
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps(
                {
                    "model": "llama-test",
                    "choices": [
                        {
                            "message": {"content": "  hello  "},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 3,
                        "total_tokens": 13,
                    },
                }
            ).encode("utf-8")

    def fake_urlopen(req, timeout):
        captured["timeout"] = timeout
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    result = llm._groq_generate(
        "prompt",
        model="llama-test",
        urlopen_fn=fake_urlopen,
        max_output_tokens=321,
    )

    assert captured["timeout"] == 12
    assert captured["url"] == llm.GROQ_CHAT_COMPLETIONS_URL
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["body"]["messages"] == [{"role": "user", "content": "prompt"}]
    assert captured["body"]["max_completion_tokens"] == 321
    assert result.text == "hello"
    assert result.provider == "groq"
    assert result.model == "llama-test"
    assert result.finish_reason == "stop"
    assert result.usage["input_tokens"] == 10
    assert result.usage["output_tokens"] == 3
    assert result.usage["total_tokens"] == 13
