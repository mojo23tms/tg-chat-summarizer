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

