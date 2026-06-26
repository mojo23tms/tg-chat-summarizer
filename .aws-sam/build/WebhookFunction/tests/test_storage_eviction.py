from telegram_summarizer import storage


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
