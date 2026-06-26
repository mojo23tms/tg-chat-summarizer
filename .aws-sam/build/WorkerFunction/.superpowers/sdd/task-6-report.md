# Task 6: LLM Layer — Summarize with Swappable Backend

## Status
COMPLETE — Implementation and tests passing. Awaiting git classifier recovery for commit.

### Summary
- Task 6 implementation: DONE
- Tests written: DONE
- Tests passing: YES (both tests passed at 17:14)
- Files ready for commit: llm.py (modified), tests/test_llm_summarize.py (new)
- Commit message ready: "feat: summarize() with injectable swappable backend"

## Implementation Summary

### Files Changed
1. **llm.py** — Modified
   - Added `import config` at the top
   - Added `_gemini_backend(prompt)` — calls official google-generativeai SDK with config.GEMINI_API_KEY
   - Added `_default_backend()` — returns _gemini_backend (extensible for groq via LLM_BACKEND)
   - Added `summarize(messages, settings, backend_fn=None)` — main interface:
     - Returns "Nothing to summarize yet." for empty messages (no backend call)
     - Uses injected backend_fn if provided, else defaults via _default_backend()
     - Builds prompt via existing build_prompt() and returns backend result

2. **tests/test_llm_summarize.py** — Created
   - test_summarize_uses_injected_backend: verifies injected backend is called with correct prompt
   - test_summarize_empty_messages_short_circuits: verifies empty messages return literal string without backend invocation

## Test-Driven Development

### RED Phase
```
$ .venv/bin/python -m pytest tests/test_llm_summarize.py -v
FAILED tests/test_llm_summarize.py::test_summarize_uses_injected_backend - AttributeError: module 'llm' has no attribute 'summarize'
FAILED tests/test_llm_summarize.py::test_summarize_empty_messages_short_circuits - AttributeError: module 'llm' has no attribute 'summarize'
```

### GREEN Phase
```
$ .venv/bin/python -m pytest tests/test_llm_summarize.py -v
tests/test_llm_summarize.py::test_summarize_uses_injected_backend PASSED [ 50%]
tests/test_llm_summarize.py::test_summarize_empty_messages_short_circuits PASSED [100%]

============================== 2 passed in 0.02s =======================================
```

## Test Coverage
- Empty messages path: verified to short-circuit and return literal string without calling backend
- Backend injection: verified fake backend receives correct prompt and return value is passed through
- Integration with existing build_prompt: verified by checking "hello world" in captured prompt
- No real google-generativeai calls in tests: uses injectable fake backends

## Code Quality Review

### Completeness
- Follows exact specification from brief
- All three new functions implemented
- import config added
- Empty messages early-return prevents unnecessary backend work
- Lazy import of google.generativeai inside _gemini_backend avoids requiring it for tests

### Design
- Backend injection pattern enables testing without real API
- _default_backend() separation allows future LLM_BACKEND env var logic
- Prompt building delegated to existing build_prompt() (separation of concerns)
- _gemini_backend uses official SDK with proper API key configuration

### Test Hygiene
- Both test cases use dict-based message format matching expected signature
- Fake backends use closure-captured dicts to verify invocation
- Settings dict uses all required keys
- No fixture overhead (inline, minimal setup)

### YAGNI
- No over-engineering: only what the brief specifies
- No unused imports or dead code
- Comment hints at future groq support (educational, not code bloat)

## Concerns
None identified. Implementation matches brief exactly. Tests pass. Ready for commit and integration.

## Files
- /Users/maksym.kirichenko/telegram-summarizer-bot/llm.py
- /Users/maksym.kirichenko/telegram-summarizer-bot/tests/test_llm_summarize.py

## Next Step
Commit pending git service recovery.
