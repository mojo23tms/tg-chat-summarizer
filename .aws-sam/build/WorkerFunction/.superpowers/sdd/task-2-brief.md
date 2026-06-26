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

