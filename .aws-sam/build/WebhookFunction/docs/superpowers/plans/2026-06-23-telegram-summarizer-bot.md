# Telegram Summarizer Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A free-to-run Telegram bot that logs incoming chat messages and, on `/summarize [N]`, posts an AI summary of the last N messages while mentioning the caller.

**Architecture:** Single async Python process using `python-telegram-bot` (long polling). Incoming messages are logged into SQLite on a persistent volume. `/summarize` reads the recent log, builds a style/profanity-aware prompt, calls a free-tier LLM (Gemini Flash; Groq fallback behind one interface), and replies mentioning the caller. A disk janitor evicts oldest rows (FIFO) to keep ≥10% free.

**Tech Stack:** Python 3.11+, `python-telegram-bot` v21+, `google-generativeai` (Gemini), SQLite (stdlib `sqlite3`), `pytest`, Fly.io + Docker for deploy.

## Global Constraints

- Python **3.11+**.
- **Do NOT** use the ChatGPT subscription or any reverse-engineered OpenAI endpoint. LLM access is via official free-tier APIs only (Gemini primary, Groq fallback).
- LLM access MUST sit behind a single `summarize(messages, settings)` interface so the backend is swappable by the `LLM_BACKEND` env var.
- Secrets (`TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY`) come from environment only — never hard-coded or committed.
- SQLite lives at `DB_PATH` (default `data/bot.db`); the data dir is a mounted volume in production.
- Disk headroom target: keep **≥10%** of the volume free (`DISK_HEADROOM = 0.10`).
- Default summary count **30**, hard cap **200**.
- Permissions: anyone may `/summarize`; only group admins may change settings.
- All summary replies use Telegram **HTML** parse mode for the caller mention.

---

### Task 1: Project scaffold and config

**Files:**
- Create: `requirements.txt`
- Create: `config.py`
- Create: `tests/test_config.py`
- Create: `.gitignore`
- Create: `data/.gitkeep`

**Interfaces:**
- Consumes: nothing.
- Produces: `config` module exposing `DB_PATH: str`, `TELEGRAM_TOKEN: str`, `LLM_BACKEND: str`, `GEMINI_API_KEY: str`, `GROQ_API_KEY: str`, `DEFAULT_COUNT: int = 30`, `MAX_COUNT: int = 200`, `DISK_HEADROOM: float = 0.10`, and `DEFAULTS: dict` with keys `style`, `filter_level`, `language`.

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.venv/
data/*.db
.env
```

- [ ] **Step 2: Create `requirements.txt`**

```
python-telegram-bot==21.6
google-generativeai==0.8.3
pytest==8.3.3
```

- [ ] **Step 3: Create `data/.gitkeep`** (empty file so the data dir exists in git)

- [ ] **Step 4: Write the failing test**

`tests/test_config.py`:
```python
import config


def test_defaults_present():
    assert config.DEFAULT_COUNT == 30
    assert config.MAX_COUNT == 200
    assert config.DISK_HEADROOM == 0.10
    assert set(config.DEFAULTS) == {"style", "filter_level", "language"}
    assert config.DEFAULTS["filter_level"] == "clean"
    assert config.DEFAULTS["language"] == "auto"
```

- [ ] **Step 5: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 6: Create `config.py`**

```python
import os

DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

DEFAULT_COUNT = 30
MAX_COUNT = 200
DISK_HEADROOM = 0.10  # keep at least 10% of the volume free

DEFAULTS = {
    "style": "concise, neutral bullet points",
    "filter_level": "clean",
    "language": "auto",
}
```

- [ ] **Step 7: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add requirements.txt config.py tests/test_config.py .gitignore data/.gitkeep
git commit -m "chore: scaffold project and config"
```

---

### Task 2: SQLite layer — schema, log_message, recent_messages

**Files:**
- Create: `storage.py`
- Create: `tests/test_storage_messages.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `connect(path: str) -> sqlite3.Connection` — opens DB, runs `init_db`, returns connection with `row_factory = sqlite3.Row`.
  - `init_db(conn)` — creates `messages` and `chat_settings` tables (idempotent).
  - `log_message(conn, chat_id: int, msg_id: int, user_id: int, user_name: str, text: str, ts: int) -> None`.
  - `recent_messages(conn, chat_id: int, n: int) -> list[dict]` — chronological (oldest→newest), each dict has keys `user_name`, `text`, `ts`.

- [ ] **Step 1: Write the failing test**

`tests/test_storage_messages.py`:
```python
import storage


def test_log_and_recent_messages_chronological():
    conn = storage.connect(":memory:")
    for i in range(5):
        storage.log_message(conn, chat_id=1, msg_id=i, user_id=10 + i,
                            user_name=f"u{i}", text=f"hello {i}", ts=100 + i)
    rows = storage.recent_messages(conn, chat_id=1, n=3)
    assert [r["text"] for r in rows] == ["hello 2", "hello 3", "hello 4"]
    assert rows[0]["user_name"] == "u2"


def test_recent_messages_scoped_per_chat():
    conn = storage.connect(":memory:")
    storage.log_message(conn, 1, 0, 10, "a", "chat one", 100)
    storage.log_message(conn, 2, 0, 11, "b", "chat two", 100)
    rows = storage.recent_messages(conn, chat_id=1, n=10)
    assert [r["text"] for r in rows] == ["chat one"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_messages.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'storage'`

- [ ] **Step 3: Create `storage.py`**

```python
import sqlite3

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id   INTEGER NOT NULL,
    msg_id    INTEGER NOT NULL,
    user_id   INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    text      TEXT NOT NULL,
    ts        INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages (chat_id, ts);

CREATE TABLE IF NOT EXISTS chat_settings (
    chat_id      INTEGER NOT NULL,
    key          TEXT NOT NULL,
    value        TEXT NOT NULL,
    PRIMARY KEY (chat_id, key)
);
"""


def init_db(conn):
    conn.executescript(_SCHEMA)
    conn.commit()


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    init_db(conn)
    return conn


def log_message(conn, chat_id, msg_id, user_id, user_name, text, ts):
    conn.execute(
        "INSERT INTO messages (chat_id, msg_id, user_id, user_name, text, ts) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (chat_id, msg_id, user_id, user_name, text, ts),
    )
    conn.commit()


def recent_messages(conn, chat_id, n):
    cur = conn.execute(
        "SELECT user_name, text, ts FROM messages WHERE chat_id = ? "
        "ORDER BY ts DESC, id DESC LIMIT ?",
        (chat_id, n),
    )
    rows = [dict(r) for r in cur.fetchall()]
    rows.reverse()  # chronological oldest -> newest
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_messages.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_messages.py
git commit -m "feat: sqlite message log with recent_messages"
```

---

### Task 3: SQLite layer — per-chat settings

**Files:**
- Modify: `storage.py`
- Create: `tests/test_storage_settings.py`

**Interfaces:**
- Consumes: `config.DEFAULTS` (Task 1), `storage.connect` (Task 2).
- Produces:
  - `get_settings(conn, chat_id: int) -> dict` — returns `config.DEFAULTS` merged with any stored overrides (stored values win).
  - `set_setting(conn, chat_id: int, key: str, value: str) -> None` — upsert.

- [ ] **Step 1: Write the failing test**

`tests/test_storage_settings.py`:
```python
import config
import storage


def test_get_settings_returns_defaults_when_empty():
    conn = storage.connect(":memory:")
    assert storage.get_settings(conn, 1) == config.DEFAULTS


def test_set_and_get_setting_override():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "filter_level", "strict")
    storage.set_setting(conn, 1, "style", "formal paragraphs")
    s = storage.get_settings(conn, 1)
    assert s["filter_level"] == "strict"
    assert s["style"] == "formal paragraphs"
    assert s["language"] == config.DEFAULTS["language"]  # untouched default


def test_set_setting_is_upsert():
    conn = storage.connect(":memory:")
    storage.set_setting(conn, 1, "filter_level", "off")
    storage.set_setting(conn, 1, "filter_level", "strict")
    assert storage.get_settings(conn, 1)["filter_level"] == "strict"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_settings.py -v`
Expected: FAIL with `AttributeError: module 'storage' has no attribute 'get_settings'`

- [ ] **Step 3: Add settings functions to `storage.py`**

Add at top: `import config`. Append:
```python
def get_settings(conn, chat_id):
    settings = dict(config.DEFAULTS)
    cur = conn.execute(
        "SELECT key, value FROM chat_settings WHERE chat_id = ?", (chat_id,)
    )
    for row in cur.fetchall():
        settings[row["key"]] = row["value"]
    return settings


def set_setting(conn, chat_id, key, value):
    conn.execute(
        "INSERT INTO chat_settings (chat_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT(chat_id, key) DO UPDATE SET value = excluded.value",
        (chat_id, key, value),
    )
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_settings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_settings.py
git commit -m "feat: per-chat settings storage"
```

---

### Task 4: SQLite layer — disk-aware FIFO eviction

**Files:**
- Modify: `storage.py`
- Create: `tests/test_storage_eviction.py`

**Interfaces:**
- Consumes: `config.DISK_HEADROOM` (Task 1), `storage` message functions (Task 2).
- Produces:
  - `enforce_disk_headroom(conn, free_ratio_fn, headroom: float, batch: int = 200) -> int` — while `free_ratio_fn()` (a callable returning current free-space ratio 0..1) is below `headroom`, delete the oldest `batch` messages; returns total rows deleted. `free_ratio_fn` is injected so it is testable without touching a real disk.
  - `disk_free_ratio(path: str) -> float` — real implementation using `shutil.disk_usage`.

- [ ] **Step 1: Write the failing test**

`tests/test_storage_eviction.py`:
```python
import storage


def test_eviction_deletes_oldest_until_headroom_met():
    conn = storage.connect(":memory:")
    for i in range(1000):
        storage.log_message(conn, 1, i, 1, "u", f"m{i}", ts=i)

    # Simulate disk that frees up as rows are deleted: starts at 5% free,
    # crosses the 10% threshold after ~600 rows are removed.
    state = {"deleted": 0}
    original_delete = conn.execute

    def free_ratio_fn():
        remaining = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        deleted = 1000 - remaining
        return 0.05 + (deleted / 1000) * 0.20  # 0.05 -> 0.25 as rows drop

    removed = storage.enforce_disk_headroom(conn, free_ratio_fn, headroom=0.10, batch=200)
    remaining = conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
    assert removed > 0
    assert free_ratio_fn() >= 0.10
    # oldest deleted first: lowest surviving ts should be > 0
    oldest = conn.execute("SELECT MIN(ts) AS t FROM messages").fetchone()["t"]
    assert oldest is not None and oldest > 0


def test_eviction_noop_when_enough_free():
    conn = storage.connect(":memory:")
    for i in range(10):
        storage.log_message(conn, 1, i, 1, "u", f"m{i}", ts=i)
    removed = storage.enforce_disk_headroom(conn, lambda: 0.50, headroom=0.10)
    assert removed == 0
    assert conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"] == 10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage_eviction.py -v`
Expected: FAIL with `AttributeError: module 'storage' has no attribute 'enforce_disk_headroom'`

- [ ] **Step 3: Add eviction functions to `storage.py`**

Add at top: `import shutil`. Append:
```python
def disk_free_ratio(path):
    usage = shutil.disk_usage(path)
    return usage.free / usage.total


def enforce_disk_headroom(conn, free_ratio_fn, headroom, batch=200):
    deleted_total = 0
    while free_ratio_fn() < headroom:
        cur = conn.execute(
            "DELETE FROM messages WHERE id IN ("
            "SELECT id FROM messages ORDER BY ts ASC, id ASC LIMIT ?)",
            (batch,),
        )
        conn.commit()
        if cur.rowcount == 0:  # nothing left to delete; avoid infinite loop
            break
        deleted_total += cur.rowcount
    return deleted_total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage_eviction.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add storage.py tests/test_storage_eviction.py
git commit -m "feat: disk-aware FIFO message eviction"
```

---

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

### Task 7: Handler helpers — count parsing, mention, profanity post-filter

**Files:**
- Create: `helpers.py`
- Create: `tests/test_helpers.py`

**Interfaces:**
- Consumes: `config.DEFAULT_COUNT`, `config.MAX_COUNT` (Task 1).
- Produces:
  - `parse_count(arg: str | None) -> int` — parses the `/summarize` argument; missing/invalid → `config.DEFAULT_COUNT`; clamps to `[1, config.MAX_COUNT]`.
  - `format_mention(user_id: int, name: str) -> str` — returns an HTML mention `<a href="tg://user?id=ID">escaped name</a>`.
  - `scrub(text: str, filter_level: str, wordlist: set[str]) -> str` — safety-net post-filter; when `filter_level != "off"`, masks any whole word in `wordlist` (case-insensitive) with asterisks.

- [ ] **Step 1: Write the failing test**

`tests/test_helpers.py`:
```python
import config
import helpers


def test_parse_count_default_and_clamp():
    assert helpers.parse_count(None) == config.DEFAULT_COUNT
    assert helpers.parse_count("abc") == config.DEFAULT_COUNT
    assert helpers.parse_count("0") == 1
    assert helpers.parse_count("5") == 5
    assert helpers.parse_count(str(config.MAX_COUNT + 50)) == config.MAX_COUNT


def test_format_mention_escapes_html():
    out = helpers.format_mention(42, "A&B <x>")
    assert out == '<a href="tg://user?id=42">A&amp;B &lt;x&gt;</a>'


def test_scrub_masks_only_when_filtering():
    wl = {"darn"}
    assert helpers.scrub("oh darn", "off", wl) == "oh darn"
    assert helpers.scrub("oh DARN it", "clean", wl) == "oh **** it"
    assert helpers.scrub("darning socks", "strict", wl) == "darning socks"  # whole word only
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_helpers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'helpers'`

- [ ] **Step 3: Create `helpers.py`**

```python
import html
import re

import config


def parse_count(arg):
    try:
        n = int(arg)
    except (TypeError, ValueError):
        return config.DEFAULT_COUNT
    return max(1, min(n, config.MAX_COUNT))


def format_mention(user_id, name):
    return f'<a href="tg://user?id={user_id}">{html.escape(name)}</a>'


def scrub(text, filter_level, wordlist):
    if filter_level == "off" or not wordlist:
        return text

    def mask(match):
        return "*" * len(match.group(0))

    pattern = r"\b(" + "|".join(re.escape(w) for w in wordlist) + r")\b"
    return re.sub(pattern, mask, text, flags=re.IGNORECASE)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_helpers.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add helpers.py tests/test_helpers.py
git commit -m "feat: handler helpers (count, mention, profanity scrub)"
```

---

### Task 8: Telegram handlers and wiring

**Files:**
- Create: `handlers.py`
- Create: `main.py`
- Create: `tests/test_handlers_admin.py`

**Interfaces:**
- Consumes: `storage` (Tasks 2–4), `llm.summarize` (Task 6), `helpers` (Task 7), `config` (Task 1).
- Produces:
  - `is_setting_change_allowed(member_status: str) -> bool` — True for `"administrator"`/`"creator"`. (Pure, unit-tested; handlers call `get_chat_member` to obtain the status.)
  - Async handlers: `log_handler`, `summarize_handler`, `setstyle_handler`, `setfilter_handler`, `setlang_handler`, `settings_handler`, `help_handler` (manually verified, not unit-tested).
  - `build_application(conn, data_dir: str) -> Application` — registers all handlers; stores `conn` and `data_dir` in `bot_data`.
  - `main.py` entrypoint that connects storage and runs polling.

- [ ] **Step 1: Write the failing test (the only unit-testable piece here)**

`tests/test_handlers_admin.py`:
```python
import handlers


def test_only_admins_may_change_settings():
    assert handlers.is_setting_change_allowed("creator") is True
    assert handlers.is_setting_change_allowed("administrator") is True
    assert handlers.is_setting_change_allowed("member") is False
    assert handlers.is_setting_change_allowed("left") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_handlers_admin.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'handlers'`

- [ ] **Step 3: Create `handlers.py`**

```python
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CommandHandler, ContextTypes,
                          MessageHandler, filters)

import config
import helpers
import llm
import storage

PROFANITY_WORDLIST = {"fuck", "shit", "bitch", "asshole"}  # safety-net only

ADMIN_STATUSES = {"administrator", "creator"}
VALID_FILTERS = {"off", "clean", "strict"}


def is_setting_change_allowed(member_status):
    return member_status in ADMIN_STATUSES


async def _is_admin(update, context):
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    return is_setting_change_allowed(member.status)


async def log_handler(update, context):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    user = update.effective_user
    storage.log_message(
        context.bot_data["conn"], update.effective_chat.id, msg.message_id,
        user.id, user.full_name or user.username or str(user.id),
        msg.text, int(time.time()),
    )
    storage.enforce_disk_headroom(
        context.bot_data["conn"],
        lambda: storage.disk_free_ratio(context.bot_data["data_dir"]),
        config.DISK_HEADROOM,
    )


async def summarize_handler(update, context):
    conn = context.bot_data["conn"]
    chat_id = update.effective_chat.id
    n = helpers.parse_count(context.args[0] if context.args else None)
    msgs = storage.recent_messages(conn, chat_id, n)
    if not msgs:
        await update.effective_message.reply_text(
            "I have no logged messages yet — I can only summarize messages "
            "sent after I joined this chat."
        )
        return
    settings = storage.get_settings(conn, chat_id)
    try:
        summary = llm.summarize(msgs, settings)
    except Exception:
        await update.effective_message.reply_text(
            "Sorry, the summarizer is unavailable right now. Please try again."
        )
        return
    summary = helpers.scrub(summary, settings["filter_level"], PROFANITY_WORDLIST)
    user = update.effective_user
    mention = helpers.format_mention(user.id, user.full_name or "you")
    await update.effective_message.reply_text(
        f"{mention}, here is your summary of the last {len(msgs)} messages:\n\n{summary}",
        parse_mode=ParseMode.HTML,
    )


async def _change_setting(update, context, key, value):
    if not await _is_admin(update, context):
        await update.effective_message.reply_text("Only admins can change settings.")
        return False
    storage.set_setting(context.bot_data["conn"], update.effective_chat.id, key, value)
    await update.effective_message.reply_text(f"Updated {key} to: {value}")
    return True


async def setstyle_handler(update, context):
    value = " ".join(context.args).strip()
    if not value:
        await update.effective_message.reply_text("Usage: /setstyle <description>")
        return
    await _change_setting(update, context, "style", value)


async def setfilter_handler(update, context):
    value = (context.args[0] if context.args else "").lower()
    if value not in VALID_FILTERS:
        await update.effective_message.reply_text("Usage: /setfilter off|clean|strict")
        return
    await _change_setting(update, context, "filter_level", value)


async def setlang_handler(update, context):
    value = (context.args[0] if context.args else "").strip()
    if not value:
        await update.effective_message.reply_text("Usage: /setlang <code|auto>")
        return
    await _change_setting(update, context, "language", value)


async def settings_handler(update, context):
    s = storage.get_settings(context.bot_data["conn"], update.effective_chat.id)
    await update.effective_message.reply_text(
        f"style: {s['style']}\nfilter: {s['filter_level']}\nlanguage: {s['language']}"
    )


async def help_handler(update, context):
    await update.effective_message.reply_text(
        "/summarize [N] — summarize the last N messages (default "
        f"{config.DEFAULT_COUNT}, max {config.MAX_COUNT}).\n"
        "/setstyle <text>, /setfilter off|clean|strict, /setlang <code|auto> — "
        "admins only.\n/settings — show current settings."
    )


def build_application(conn, data_dir):
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.bot_data["conn"] = conn
    app.bot_data["data_dir"] = data_dir
    app.add_handler(CommandHandler("summarize", summarize_handler))
    app.add_handler(CommandHandler("setstyle", setstyle_handler))
    app.add_handler(CommandHandler("setfilter", setfilter_handler))
    app.add_handler(CommandHandler("setlang", setlang_handler))
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CommandHandler(["help", "start"], help_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_handler))
    return app
```

- [ ] **Step 4: Create `main.py`**

```python
import os

import config
import handlers
import storage


def main():
    data_dir = os.path.dirname(config.DB_PATH) or "."
    os.makedirs(data_dir, exist_ok=True)
    conn = storage.connect(config.DB_PATH)
    app = handlers.build_application(conn, data_dir)
    app.run_polling()


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_handlers_admin.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `python -m pytest -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add handlers.py main.py tests/test_handlers_admin.py
git commit -m "feat: telegram handlers and polling entrypoint"
```

---

### Task 9: Deployment files and README

**Files:**
- Create: `Dockerfile`
- Create: `fly.toml`
- Create: `README.md`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: the full app (Tasks 1–8).
- Produces: a deployable image and documented setup. No automated tests; verified by deploy.

- [ ] **Step 1: Create `.dockerignore`**

```
.venv/
__pycache__/
data/*.db
.git/
tests/
```

- [ ] **Step 2: Create `Dockerfile`**

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV DB_PATH=/data/bot.db
CMD ["python", "main.py"]
```

- [ ] **Step 3: Create `fly.toml`** (replace `app` name on first deploy)

```toml
app = "telegram-summarizer-bot"
primary_region = "fra"

[build]

[mounts]
  source = "bot_data"
  destination = "/data"

[[vm]]
  size = "shared-cpu-1x"
  memory = "256mb"
```

- [ ] **Step 4: Create `README.md`**

```markdown
# Telegram Summarizer Bot

Logs chat messages and summarizes the last N on `/summarize`, mentioning the caller.
Free to run: Telegram Bot API + Gemini free tier + Fly.io free allowance.

## Setup
1. Create a bot with @BotFather; copy the token. Run `/setprivacy` → **Disable**
   (or add the bot as a group admin) so it can log group messages.
2. Get a free Gemini API key at https://aistudio.google.com/apikey.
3. Local run:
   ```bash
   python -m venv .venv && source .venv/bin/activate
   pip install -r requirements.txt
   export TELEGRAM_TOKEN=... GEMINI_API_KEY=...
   python main.py
   ```
4. Deploy to Fly.io:
   ```bash
   fly launch --no-deploy        # accept generated app name / region
   fly volumes create bot_data --size 1
   fly secrets set TELEGRAM_TOKEN=... GEMINI_API_KEY=...
   fly deploy
   ```

## Commands
- `/summarize [N]` — summarize last N messages (default 30, max 200).
- `/setstyle <text>` · `/setfilter off|clean|strict` · `/setlang <code|auto>` — admins only.
- `/settings` — show current config. `/help` — usage.
```

- [ ] **Step 5: Verify the image builds**

Run: `docker build -t summarizer-bot .`
Expected: build succeeds.

- [ ] **Step 6: Commit**

```bash
git add Dockerfile fly.toml README.md .dockerignore
git commit -m "chore: docker + fly deployment and README"
```

---

## Manual Verification (end-to-end)

After Task 8, run locally against a real test bot and group:

1. **Logging + summarize**: `export TELEGRAM_TOKEN=... GEMINI_API_KEY=...; python main.py`.
   Send several messages in the test group, then `/summarize 10`. Confirm a summary
   posts and it **mentions you** (tappable name).
2. **No-history case**: in a fresh chat, `/summarize` → confirm the "no logged messages"
   reply.
3. **Settings + permissions**: as admin `/setstyle formal paragraphs` and
   `/setfilter strict`; re-run `/summarize` and confirm the output style/cleanliness
   changes. As a non-admin member, attempt `/setfilter off` → confirm denial.
4. **Profanity safety net**: post messages containing wordlist terms, `/setfilter clean`,
   confirm masked output even if the model echoes them.
5. **Retention**: temporarily lower `DISK_HEADROOM` (or point `disk_free_ratio` at a small
   tmpfs), flood messages, and confirm oldest rows are evicted while free space holds.
6. **Deploy**: `fly deploy`, restart the machine (`fly machine restart`), confirm the bot
   reconnects and resumes logging.
