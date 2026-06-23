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
