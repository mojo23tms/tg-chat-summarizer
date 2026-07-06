# Working With Codex

Use short prompts once these instructions are present.

Recommended prompt:

```text
Read AGENTS.md, CODEX.md, and docs/codex/implementation-roadmap.md.
Continue from the next incomplete batch.
Before changing code, inspect the current implementation, explain the smallest safe plan, then implement only that batch with tests and docs.
Stop after the batch is complete.
```

## Branch Strategy

Use one branch or pull request per batch when possible.

Good branch names:

- `batch-01-telegram-output-pipeline`
- `batch-02-summary-scope`
- `batch-03-prompt-hardening`

## Review Strategy

For every batch, review:

- files changed;
- test coverage;
- command behavior;
- cost impact;
- DynamoDB compatibility;
- Telegram output safety;
- docs updated.

## Do Not Ask Codex For Everything At Once

Avoid prompts like:

```text
Implement the whole roadmap.
```

That increases risk of messy architecture, missed tests, and expensive accidental design choices.

## Better Prompt Pattern

```text
Start Batch N only. First inspect the relevant files and tests. Then propose the smallest safe implementation plan. After that, implement, test, update docs, and stop.
```
