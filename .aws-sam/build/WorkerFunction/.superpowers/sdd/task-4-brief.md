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

