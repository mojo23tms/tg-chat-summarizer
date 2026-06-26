# Task 4: SQLite layer — disk-aware FIFO eviction

## Status: COMPLETED

## Implementation

### Files Changed
- **storage.py**: Added `import shutil` at top; appended `disk_free_ratio(path)` and `enforce_disk_headroom(conn, free_ratio_fn, headroom, batch=200)` functions.
- **tests/test_storage_eviction.py**: Created new test file with two test cases.

### Code Added

#### disk_free_ratio(path: str) -> float
Real implementation using `shutil.disk_usage()`. Returns the ratio of free space to total disk space (0..1).

#### enforce_disk_headroom(conn, free_ratio_fn, headroom: float, batch: int = 200) -> int
FIFO eviction loop:
- While `free_ratio_fn()` returns a value below `headroom`, deletes oldest `batch` messages by timestamp (ts ASC, id ASC)
- Commits after each batch
- Returns total rows deleted
- Safety break if no rows are deleted (prevents infinite loop when table is empty)

## Test-Driven Development Results

### RED Phase (Step 1-2)
Ran: `.venv/bin/python -m pytest tests/test_storage_eviction.py -v`

**Result**: 2 FAILED (AttributeError: module 'storage' has no attribute 'enforce_disk_headroom')

### GREEN Phase (Step 3-4)
Implemented the two functions in storage.py.

Ran: `.venv/bin/python -m pytest tests/test_storage_eviction.py -v`

**Result**: 2 PASSED

### Full Suite Verification
Ran: `.venv/bin/python -m pytest tests/ -v`

**Result**: 8 PASSED (all existing tests + 2 new tests)
- test_config.py::test_defaults_present
- test_storage_eviction.py::test_eviction_deletes_oldest_until_headroom_met
- test_storage_eviction.py::test_eviction_noop_when_enough_free
- test_storage_messages.py::test_log_and_recent_messages_chronological
- test_storage_messages.py::test_recent_messages_scoped_per_chat
- test_storage_settings.py::test_get_settings_returns_defaults_when_empty
- test_storage_settings.py::test_set_and_get_setting_override
- test_storage_settings.py::test_set_setting_is_upsert

## Git Commit

Commit SHA: `ef0a1c7`
Message: `feat: disk-aware FIFO message eviction`

Command used:
```bash
git -c user.name='Maksym' -c user.email='maksym.kirichenko@creatoriq.com' commit -m "feat: disk-aware FIFO message eviction"
```

## Self-Review

### Completeness
- ✅ Both required functions implemented with exact signatures from brief
- ✅ `import shutil` added at module top
- ✅ Two test cases transcribed exactly from brief
- ✅ FIFO deletion by oldest timestamp (ORDER BY ts ASC, id ASC)
- ✅ Batch processing (default 200)
- ✅ Safety break on rowcount == 0
- ✅ commit() after each deletion batch
- ✅ Injected free_ratio_fn for testability (no disk dependency in tests)

### Quality
- ✅ Code matches brief's implementation exactly
- ✅ No unnecessary refactoring or "fixes"
- ✅ Proper error handling with safety break for empty table
- ✅ Functions integrate cleanly with existing storage.py API
- ✅ All tests pass (8/8)

### Test Hygiene
- ✅ Tests use in-memory SQLite for isolation (no disk/file dependencies)
- ✅ Unused local `original_delete = conn.execute` kept as-is per brief instruction
- ✅ Mock free_ratio_fn demonstrates proper injection pattern
- ✅ Covers success case (eviction occurs, headroom met) and noop case (already enough free space)
- ✅ Validates FIFO property (oldest deleted first, surviving oldest ts > 0)

### YAGNI
- ✅ Only the two functions required by interface added
- ✅ No extra utilities, helpers, or convenience functions
- ✅ No over-engineering (batch parameter, safety break are minimal necessary features)

## Concerns

**None.** The implementation follows the brief exactly. The unused `original_delete` local variable in the test is retained as instructed, even though it appears unused — this is intentional per the brief's "transcribe exactly" note.

## Files

- `/Users/maksym.kirichenko/telegram-summarizer-bot/storage.py` — Modified (added 2 functions, 1 import)
- `/Users/maksym.kirichenko/telegram-summarizer-bot/tests/test_storage_eviction.py` — Created
