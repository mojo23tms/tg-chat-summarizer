### Task 6: LLM layer — summarize with swappable backend

**Files:**
- Modify: `llm.py`
- Create: `tests/test_llm_summarize.py`

**Interfaces:**
- Consumes: `build_prompt` (Task 5), `config.LLM_BACKEND`/`config.GEMINI_API_KEY` (Task 1).
- Produces:
  - `summarize(messages: list[dict], settings: dict, backend_fn=None) -> str` — builds the prompt, calls `backend_fn(prompt)` (defaults to the configured real backend), returns the text. On empty `messages` returns the literal string `"Nothing to summarize yet."` without calling the backend.
  - `_gemini_backend(prompt: str) -> str` — real Gemini call (not unit-tested; covered by manual verification).

- [ ] **Step 1: Write the failing test**

`tests/test_llm_summarize.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_summarize.py -v`
Expected: FAIL with `AttributeError: module 'llm' has no attribute 'summarize'`

- [ ] **Step 3: Add `summarize` and the Gemini backend to `llm.py`**

Add at top: `import config`. Append:
```python
def _gemini_backend(prompt):
    import google.generativeai as genai
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    resp = model.generate_content(prompt)
    return resp.text.strip()


def _default_backend():
    # Only gemini is wired now; groq can be added here behind LLM_BACKEND.
    return _gemini_backend


def summarize(messages, settings, backend_fn=None):
    if not messages:
        return "Nothing to summarize yet."
    if backend_fn is None:
        backend_fn = _default_backend()
    prompt = build_prompt(messages, settings)
    return backend_fn(prompt)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_summarize.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm.py tests/test_llm_summarize.py
git commit -m "feat: summarize() with injectable swappable backend"
```

---

