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

