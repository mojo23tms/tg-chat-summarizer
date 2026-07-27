from telegram_summarizer import storage


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


def test_sqlite_message_pages_are_scoped_bounded_and_paginated():
    conn = storage.connect(":memory:")
    for ts in range(1, 7):
        storage.log_message(conn, 1, ts, 10, "alice", f"m{ts}", ts)
    storage.log_message(conn, 2, 99, 20, "other", "wrong chat", 4)
    adapter = storage.SQLiteMessagePageStorage(conn)

    first, cursor = adapter.message_page(
        1, start_ts=2, end_ts=5, limit=2, exclusive_start_key=None
    )
    second, next_cursor = adapter.message_page(
        1, start_ts=2, end_ts=5, limit=2, exclusive_start_key=cursor
    )

    assert [row["text"] for row in first] == ["m5", "m4"]
    assert [row["text"] for row in second] == ["m3", "m2"]
    assert cursor is not None
    assert next_cursor is None
    assert all(row["user_id"] == 10 for row in first + second)


def test_sqlite_chronological_pages_and_checkpoint_resume():
    conn = storage.connect(":memory:")
    for ts in range(1, 6):
        storage.log_message(conn, 1, ts, 10, "alice", f"m{ts}", ts)
    storage.log_message(conn, 2, 99, 20, "other", "wrong chat", 3)
    adapter = storage.SQLiteMessagePageStorage(conn)

    first, cursor = adapter.chronological_message_page(1, limit=3)
    second, final_cursor = adapter.chronological_message_page(
        1, limit=3, exclusive_start_key=cursor
    )
    checkpoint = {
        "status": "in_progress",
        "start_ts": 0,
        "end_ts": 100,
        "cursor": cursor,
        "processed_messages": 3,
        "processed_chunks": 1,
    }
    adapter.save_backfill_checkpoint(1, checkpoint)

    assert [row["text"] for row in first + second] == ["m1", "m2", "m3", "m4", "m5"]
    assert final_cursor is None
    assert adapter.get_backfill_checkpoint(1) == checkpoint
    assert adapter.get_backfill_checkpoint(2) is None
    adapter.clear_backfill_checkpoint(1)
    assert adapter.get_backfill_checkpoint(1) is None


def test_sqlite_memory_snapshots_are_idempotent_scoped_and_searchable():
    conn = storage.connect(":memory:")
    snapshot = {
        "version": 1,
        "created_at": 100,
        "start_ts": 10,
        "end_ts": 20,
        "message_count": 5,
        "summary": "The Ibiza hotel joke",
        "items": [
            {
                "kind": "running_joke",
                "title": "Ibiza",
                "details": "Alice started it",
                "people": ["Alice"],
                "keywords": ["ibiza"],
                "source_timestamps": [12],
            }
        ],
    }

    storage.save_memory_snapshot(conn, 1, snapshot)
    storage.save_memory_snapshot(conn, 1, {**snapshot, "summary": "Updated lore"})
    storage.save_memory_snapshot(conn, 2, {**snapshot, "summary": "Wrong chat"})

    rows = storage.search_memories(conn, 1, "ibiza alice", limit=5, scan_limit=10)
    assert conn.execute(
        "SELECT COUNT(*) FROM memory_snapshots WHERE chat_id = 1"
    ).fetchone()[0] == 1
    assert len(rows) == 1
    assert rows[0]["summary"] == "Updated lore"
    assert storage.search_memories(conn, 1, "missing", limit=5, scan_limit=10) == []
    assert storage.search_memories(
        conn, 1, "ibiza", start_ts=21, limit=5, scan_limit=10
    ) == []
    assert len(
        storage.search_memories(
            conn, 1, "ibiza", start_ts=15, end_ts=30, limit=5, scan_limit=10
        )
    ) == 1


def test_sqlite_memory_pages_are_chronological_paginated_and_scoped():
    conn = storage.connect(":memory:")
    adapter = storage.SQLiteMessagePageStorage(conn)
    for index in (3, 1, 2):
        adapter.save_memory_snapshot(
            1,
            {
                "version": 1,
                "created_at": index,
                "start_ts": index * 10,
                "end_ts": index * 10 + 9,
                "message_count": 1,
                "summary": f"chunk {index}",
                "items": [],
            },
        )
    adapter.save_memory_snapshot(
        2,
        {
            "version": 1,
            "created_at": 1,
            "start_ts": 10,
            "end_ts": 19,
            "message_count": 1,
            "summary": "wrong chat",
            "items": [],
        },
    )

    first, cursor = adapter.memory_page(1, limit=2)
    second, final_cursor = adapter.memory_page(
        1, limit=2, exclusive_start_key=cursor
    )

    assert [item["summary"] for item in first + second] == [
        "chunk 1",
        "chunk 2",
        "chunk 3",
    ]
    assert final_cursor is None
