### Task 5: LLM layer — prompt builder (pure function)

**Files:**
- Create: `llm.py`
- Create: `tests/test_llm_prompt.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `build_prompt(messages: list[dict], settings: dict) -> str` — pure function. Embeds a style instruction, a profanity instruction derived from `settings["filter_level"]` (`off`/`clean`/`strict`), a language instruction from `settings["language"]`, and the formatted transcript (`user_name: text` per line).
  - `FILTER_INSTRUCTIONS: dict` mapping each filter level to its instruction string.

- [ ] **Step 1: Write the failing test**

`tests/test_llm_prompt.py`:
```python
import llm


def test_prompt_includes_transcript_and_style():
    msgs = [{"user_name": "alice", "text": "ship it"},
            {"user_name": "bob", "text": "lgtm"}]
    settings = {"style": "one short paragraph", "filter_level": "off", "language": "auto"}
    p = llm.build_prompt(msgs, settings)
    assert "alice: ship it" in p
    assert "bob: lgtm" in p
    assert "one short paragraph" in p


def test_prompt_filter_levels_differ():
    msgs = [{"user_name": "a", "text": "x"}]
    base = {"style": "s", "language": "auto"}
    clean = llm.build_prompt(msgs, {**base, "filter_level": "clean"})
    strict = llm.build_prompt(msgs, {**base, "filter_level": "strict"})
    off = llm.build_prompt(msgs, {**base, "filter_level": "off"})
    assert llm.FILTER_INSTRUCTIONS["clean"] in clean
    assert llm.FILTER_INSTRUCTIONS["strict"] in strict
    assert llm.FILTER_INSTRUCTIONS["off"] in off
    assert clean != strict


def test_prompt_language_explicit():
    msgs = [{"user_name": "a", "text": "x"}]
    p = llm.build_prompt(msgs, {"style": "s", "filter_level": "off", "language": "uk"})
    assert "uk" in p
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_prompt.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm'`

- [ ] **Step 3: Create `llm.py`**

```python
FILTER_INSTRUCTIONS = {
    "off": "Do not filter language; reproduce tone faithfully.",
    "clean": "Avoid profanity; mask any strong language with asterisks.",
    "strict": "Use no profanity, slurs, or harassing language whatsoever; "
              "rephrase such content neutrally.",
}


def _language_instruction(language):
    if language == "auto":
        return "Write the summary in the dominant language of the conversation."
    return f"Write the summary in this language: {language}."


def build_prompt(messages, settings):
    filter_level = settings.get("filter_level", "clean")
    transcript = "\n".join(f"{m['user_name']}: {m['text']}" for m in messages)
    return (
        "You are a chat summarizer. Summarize the conversation below.\n"
        f"Style: {settings['style']}.\n"
        f"{_language_instruction(settings.get('language', 'auto'))}\n"
        f"{FILTER_INSTRUCTIONS.get(filter_level, FILTER_INSTRUCTIONS['clean'])}\n\n"
        "Conversation:\n"
        f"{transcript}\n\n"
        "Summary:"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add llm.py tests/test_llm_prompt.py
git commit -m "feat: llm prompt builder with style/filter/language"
```

---

