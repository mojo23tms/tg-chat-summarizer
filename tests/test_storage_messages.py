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
