import json
import shutil
import sqlite3
import time

from . import config
from .retrieval import rank_memory_snapshots

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

CREATE TABLE IF NOT EXISTS usage_records (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id        INTEGER NOT NULL,
    ts             INTEGER NOT NULL,
    messages_count INTEGER NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    total_tokens   INTEGER NOT NULL,
    estimated      INTEGER NOT NULL,
    provider       TEXT NOT NULL,
    model          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_chat_ts ON usage_records (chat_id, ts);

CREATE TABLE IF NOT EXISTS memory_snapshots (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id       INTEGER NOT NULL,
    start_ts      INTEGER NOT NULL,
    end_ts        INTEGER NOT NULL,
    created_at    INTEGER NOT NULL,
    message_count INTEGER NOT NULL,
    content_json  TEXT NOT NULL,
    UNIQUE (chat_id, start_ts, end_ts)
);
CREATE INDEX IF NOT EXISTS idx_memory_chat_created
ON memory_snapshots (chat_id, created_at);

CREATE TABLE IF NOT EXISTS backfill_checkpoints (
    chat_id         INTEGER NOT NULL,
    job_name        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (chat_id, job_name)
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


def message_page(
    conn,
    chat_id,
    *,
    start_ts=0,
    end_ts=99_999_999_999,
    limit=100,
    exclusive_start_key=None,
):
    start_ts = int(start_ts)
    end_ts = int(end_ts)
    limit = int(limit)
    if start_ts > end_ts:
        return [], None
    if limit < 1:
        raise ValueError("limit must be positive")

    sql = (
        "SELECT id, msg_id, user_id, user_name, text, ts FROM messages "
        "WHERE chat_id = ? AND ts BETWEEN ? AND ?"
    )
    params = [int(chat_id), start_ts, end_ts]
    if exclusive_start_key is not None:
        cursor_ts = int(exclusive_start_key["ts"])
        cursor_id = int(exclusive_start_key["id"])
        sql += " AND (ts < ? OR (ts = ? AND id < ?))"
        params.extend([cursor_ts, cursor_ts, cursor_id])
    sql += " ORDER BY ts DESC, id DESC LIMIT ?"
    params.append(limit + 1)

    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    has_more = len(rows) > limit
    page = rows[:limit]
    cursor = None
    if has_more:
        cursor = {"ts": int(page[-1]["ts"]), "id": int(page[-1]["id"])}
    for row in page:
        row.pop("id", None)
    return page, cursor


def chronological_message_page(
    conn,
    chat_id,
    *,
    start_ts=0,
    end_ts=99_999_999_999,
    limit=100,
    exclusive_start_key=None,
):
    start_ts = int(start_ts)
    end_ts = int(end_ts)
    limit = int(limit)
    if start_ts > end_ts:
        return [], None
    if limit < 1:
        raise ValueError("limit must be positive")
    sql = (
        "SELECT id, msg_id, user_id, user_name, text, ts FROM messages "
        "WHERE chat_id = ? AND ts BETWEEN ? AND ?"
    )
    params = [int(chat_id), start_ts, end_ts]
    if exclusive_start_key is not None:
        cursor_ts = int(exclusive_start_key["ts"])
        cursor_msg_id = int(exclusive_start_key["msg_id"])
        sql += " AND (ts > ? OR (ts = ? AND msg_id > ?))"
        params.extend([cursor_ts, cursor_ts, cursor_msg_id])
    sql += " ORDER BY ts ASC, msg_id ASC LIMIT ?"
    params.append(limit + 1)
    rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    has_more = len(rows) > limit
    page = rows[:limit]
    cursor = None
    if has_more:
        cursor = {
            "ts": int(page[-1]["ts"]),
            "msg_id": int(page[-1]["msg_id"]),
        }
    for row in page:
        row.pop("id", None)
    return page, cursor


class SQLiteMessagePageStorage:
    def __init__(self, conn):
        self.conn = conn

    def message_page(self, chat_id, **kwargs):
        return message_page(self.conn, chat_id, **kwargs)

    def recent_messages(self, chat_id, n):
        return recent_messages(self.conn, chat_id, n)

    def chronological_message_page(self, chat_id, **kwargs):
        return chronological_message_page(self.conn, chat_id, **kwargs)

    def message_cursor(self, chat_id, message):
        return {"ts": int(message["ts"]), "msg_id": int(message["msg_id"])}

    def save_memory_snapshot(self, chat_id, snapshot):
        return save_memory_snapshot(self.conn, chat_id, snapshot)

    def search_memories(
        self, chat_id, query="", limit=5, scan_limit=50, start_ts=None, end_ts=None
    ):
        return search_memories(
            self.conn,
            chat_id,
            query=query,
            limit=limit,
            scan_limit=scan_limit,
            start_ts=start_ts,
            end_ts=end_ts,
        )

    def get_backfill_checkpoint(self, chat_id, job_name="historical_memory"):
        return get_backfill_checkpoint(self.conn, chat_id, job_name=job_name)

    def save_backfill_checkpoint(
        self, chat_id, checkpoint, job_name="historical_memory"
    ):
        return save_backfill_checkpoint(
            self.conn, chat_id, checkpoint, job_name=job_name
        )

    def clear_backfill_checkpoint(self, chat_id, job_name="historical_memory"):
        return clear_backfill_checkpoint(self.conn, chat_id, job_name=job_name)

    def get_settings(self, chat_id):
        return get_settings(self.conn, chat_id)

    def log_usage(self, chat_id, usage, messages_count, ts=None):
        return log_usage(
            self.conn,
            chat_id,
            usage,
            messages_count,
            int(time.time()) if ts is None else ts,
        )

    def usage_totals(
        self, chat_id, since_ts=None, provider=None, model=None
    ):
        return usage_totals(
            self.conn,
            chat_id,
            since_ts=since_ts,
            provider=provider,
            model=model,
        )


def save_memory_snapshot(conn, chat_id, snapshot):
    content = {
        "version": int(snapshot.get("version", 1)),
        "created_at": int(snapshot["created_at"]),
        "start_ts": int(snapshot["start_ts"]),
        "end_ts": int(snapshot["end_ts"]),
        "message_count": int(snapshot["message_count"]),
        "summary": snapshot.get("summary", ""),
        "items": snapshot.get("items", []),
        "participants": snapshot.get("participants", []),
        "lexical_terms": snapshot.get("lexical_terms", []),
        "source_message_ids": snapshot.get("source_message_ids", []),
    }
    conn.execute(
        "INSERT INTO memory_snapshots "
        "(chat_id, start_ts, end_ts, created_at, message_count, content_json) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(chat_id, start_ts, end_ts) DO UPDATE SET "
        "created_at = excluded.created_at, "
        "message_count = excluded.message_count, "
        "content_json = excluded.content_json",
        (
            int(chat_id),
            content["start_ts"],
            content["end_ts"],
            content["created_at"],
            content["message_count"],
            json.dumps(content, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    conn.commit()


def search_memories(
    conn, chat_id, query="", limit=5, scan_limit=50, start_ts=None, end_ts=None
):
    limit = int(limit)
    scan_limit = int(scan_limit)
    if limit < 1 or scan_limit < 1:
        raise ValueError("memory limits must be positive")
    sql = "SELECT content_json FROM memory_snapshots WHERE chat_id = ?"
    params = [int(chat_id)]
    if start_ts is not None:
        sql += " AND end_ts >= ?"
        params.append(int(start_ts))
    if end_ts is not None:
        sql += " AND start_ts <= ?"
        params.append(int(end_ts))
    sql += " ORDER BY created_at DESC, id DESC LIMIT ?"
    params.append(scan_limit)
    rows = conn.execute(sql, params).fetchall()
    memories = [json.loads(row["content_json"]) for row in rows]
    return rank_memory_snapshots(memories, query, limit)


def get_backfill_checkpoint(conn, chat_id, job_name="historical_memory"):
    row = conn.execute(
        "SELECT checkpoint_json FROM backfill_checkpoints "
        "WHERE chat_id = ? AND job_name = ?",
        (int(chat_id), str(job_name)),
    ).fetchone()
    return json.loads(row["checkpoint_json"]) if row else None


def save_backfill_checkpoint(
    conn, chat_id, checkpoint, job_name="historical_memory"
):
    conn.execute(
        "INSERT INTO backfill_checkpoints (chat_id, job_name, checkpoint_json) "
        "VALUES (?, ?, ?) ON CONFLICT(chat_id, job_name) DO UPDATE SET "
        "checkpoint_json = excluded.checkpoint_json",
        (
            int(chat_id),
            str(job_name),
            json.dumps(checkpoint, ensure_ascii=False, separators=(",", ":")),
        ),
    )
    conn.commit()


def clear_backfill_checkpoint(conn, chat_id, job_name="historical_memory"):
    conn.execute(
        "DELETE FROM backfill_checkpoints WHERE chat_id = ? AND job_name = ?",
        (int(chat_id), str(job_name)),
    )
    conn.commit()


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


def log_usage(conn, chat_id, usage, messages_count, ts):
    if not usage:
        return
    conn.execute(
        "INSERT INTO usage_records "
        "(chat_id, ts, messages_count, input_tokens, output_tokens, total_tokens, "
        "estimated, provider, model) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            chat_id,
            int(ts),
            int(messages_count),
            int(usage.get("input_tokens", 0)),
            int(usage.get("output_tokens", 0)),
            int(usage.get("total_tokens", 0)),
            1 if usage.get("estimated", True) else 0,
            usage.get("provider", ""),
            usage.get("model", ""),
        ),
    )
    conn.commit()


def usage_totals(conn, chat_id, since_ts=None, provider=None, model=None):
    sql = (
        "SELECT COUNT(*) AS requests, COALESCE(SUM(messages_count), 0) AS messages_count, "
        "COALESCE(SUM(input_tokens), 0) AS input_tokens, "
        "COALESCE(SUM(output_tokens), 0) AS output_tokens, "
        "COALESCE(SUM(total_tokens), 0) AS total_tokens, "
        "COALESCE(SUM(estimated), 0) AS estimated_records "
        "FROM usage_records WHERE chat_id = ?"
    )
    params = [int(chat_id)]
    if since_ts is not None:
        sql += " AND ts >= ?"
        params.append(int(since_ts))
    if provider is not None:
        sql += " AND provider = ?"
        params.append(str(provider))
    if model is not None:
        sql += " AND model = ?"
        params.append(str(model))
    return dict(conn.execute(sql, params).fetchone())


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
