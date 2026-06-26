# Task 5: LLM Layer — Prompt Builder (Pure Function)

## Status
COMPLETED

## Implementation

### TDD Process
1. **RED**: Created test file `tests/test_llm_prompt.py` with all 3 test cases; ran `.venv/bin/python -m pytest tests/test_llm_prompt.py -v` → FAILED with `ModuleNotFoundError: No module named 'llm'` ✓
2. **GREEN**: Created `llm.py` with `FILTER_INSTRUCTIONS` dict and `build_prompt()` function; re-ran tests → 3 PASSED ✓
3. **VERIFY**: Ran full suite `.venv/bin/python -m pytest tests/ -v` → 11 PASSED (3 new + 8 existing) ✓

### Files Created
- **`llm.py`** (26 lines)
  - `FILTER_INSTRUCTIONS`: dict mapping "off"/"clean"/"strict" to instruction strings
  - `_language_instruction(language)`: helper that returns "auto" → "dominant language" or explicit language instruction
  - `build_prompt(messages, settings)`: pure function assembles prompt string with system instruction, style, language, filter level, formatted transcript, and summary placeholder
  
- **`tests/test_llm_prompt.py`** (29 lines)
  - `test_prompt_includes_transcript_and_style()`: verifies transcript lines and style are in output
  - `test_prompt_filter_levels_differ()`: verifies each filter level instruction is present and prompts differ
  - `test_prompt_language_explicit()`: verifies explicit language code ("uk") appears in prompt

## Test Results

### Individual Test Run
```
tests/test_llm_prompt.py::test_prompt_includes_transcript_and_style PASSED
tests/test_llm_prompt.py::test_prompt_filter_levels_differ PASSED
tests/test_llm_prompt.py::test_prompt_language_explicit PASSED
```

### Full Suite (all 11 tests)
```
tests/test_config.py::test_defaults_present PASSED
tests/test_llm_prompt.py::test_prompt_includes_transcript_and_style PASSED
tests/test_llm_prompt.py::test_prompt_filter_levels_differ PASSED
tests/test_llm_prompt.py::test_prompt_language_explicit PASSED
tests/test_storage_eviction.py::test_eviction_deletes_oldest_until_headroom_met PASSED
tests/test_storage_eviction.py::test_eviction_noop_when_enough_free PASSED
tests/test_storage_messages.py::test_log_and_recent_messages_chronological PASSED
tests/test_storage_messages.py::test_recent_messages_scoped_per_chat PASSED
tests/test_storage_settings.py::test_get_settings_returns_defaults_when_empty PASSED
tests/test_storage_settings.py::test_set_and_get_setting_override PASSED
tests/test_storage_settings.py::test_set_setting_is_upsert PASSED
```
**11/11 PASSED**

## Commit
```
c7e76d9 feat: llm prompt builder with style/filter/language
```

## Self-Review

### Completeness
- ✓ All brief requirements implemented: FILTER_INSTRUCTIONS dict, build_prompt function with correct signature
- ✓ Transcript formatted as "user_name: text" per line
- ✓ Style, language, filter_level, and conversation all included in prompt
- ✓ Pure function (no I/O, no side effects, no module imports)
- ✓ Tests verify key behaviors: transcript presence, style inclusion, filter differences, language instruction

### Code Quality
- **DRY**: Helper function `_language_instruction()` avoids duplication
- **Robust**: Defensive access with `.get()` for optional settings; default filter_level fallback
- **Simple**: Straightforward string building, no premature optimization
- **Readable**: Clear variable names, f-strings for interpolation

### YAGNI
- No unnecessary abstractions or features beyond brief specification
- No over-testing (3 focused tests, each testing one axis of variation)

### Test Hygiene
- Tests are independent (no shared state)
- Clear assertions focusing on key behaviors
- Good coverage: transcript inclusion, filter level variation, language instruction behavior

### Concerns
- None identified. Implementation matches brief exactly, all tests pass, no regressions.

## Files Modified
- Created: `/Users/maksym.kirichenko/telegram-summarizer-bot/llm.py`
- Created: `/Users/maksym.kirichenko/telegram-summarizer-bot/tests/test_llm_prompt.py`
