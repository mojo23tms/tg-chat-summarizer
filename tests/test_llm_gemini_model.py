import sys
import types

import llm


def test_gemini_backend_uses_current_model_not_retired(monkeypatch):
    # Regression: gemini-1.5-flash was retired and returns 404 on generateContent.
    # _gemini_backend must request a currently-served model. We fake the SDK so
    # this stays network-free and just asserts the wiring/model name.
    captured = {}

    fake = types.ModuleType("google.generativeai")

    def configure(api_key=None):
        captured["key"] = api_key

    class FakeModel:
        def __init__(self, name):
            captured["model"] = name

        def generate_content(self, prompt):
            captured["prompt"] = prompt
            return types.SimpleNamespace(text="  a summary  ")

    fake.configure = configure
    fake.GenerativeModel = FakeModel

    monkeypatch.setitem(sys.modules, "google", types.ModuleType("google"))
    monkeypatch.setitem(sys.modules, "google.generativeai", fake)

    out = llm._gemini_backend("hello")

    assert captured["model"] == llm.GEMINI_MODEL
    assert captured["model"] != "gemini-1.5-flash"
    assert out == "a summary"  # response text is stripped
