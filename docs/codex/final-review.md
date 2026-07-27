# Final Roadmap Review

Review date: 2026-07-27

This review closes the implementation roadmap after the personal archive and
compact Telegram menu batches. It records the evidence behind the final
checklist without replacing the per-feature product and operations docs.

## Result

No release-blocking issue was found.

- Production remains AWS-first: API Gateway -> webhook Lambda -> SQS FIFO ->
  worker Lambda -> DynamoDB/Telegram.
- Legacy local polling remains available with SQLite.
- Gemini remains the default provider; Groq is selected through the same
  provider-neutral LLM interface.
- Live commands do not import the personal archive exporter or read S3,
  Google Drive, or NordLocker.
- The production stack successfully reached `UPDATE_COMPLETE` for commit
  `1501b5a`.

## Checklist Evidence

### Secrets And Privacy

- Production tokens and provider keys come from environment variables or the
  configured Secrets Manager object.
- `.env.example` contains names and empty placeholders only.
- The SAM template passes only the secret identifier to Lambda.
- Repository secret-pattern checks found no committed credential material.
- Chat-history prompts treat retrieved messages as untrusted data and explicitly
  delimit them from instructions.

### Commands And Output

- `/summarize` remains available to ordinary chat members.
- Settings mutations and `/remember` remain admin-only; owner-DM targeting is
  restricted to configured bot owners.
- Reads, writes, memories, settings, and usage records are scoped by `chat_id`.
- AI output uses the shared Telegram HTML sanitizer and splitter.
- `/chat` does not retrieve history; `/ask` and lore commands use bounded
  retrieval and evidence budgets.

### Cost And Providers

- Summary, Q&A, lore, and memory inputs have explicit message/token caps.
- Historical backfill requires explicit operator limits and supports dry-run
  cost estimates.
- Provider usage is recorded when reported and estimated otherwise.
- Optional daily quotas warn at most once per chat/provider/day.
- Automated tests block external networking and consume no provider quota.

### Storage And Compatibility

- Existing DynamoDB message, settings, usage, owner, and memory key families are
  preserved.
- Historical import/backfill and archive export are idempotent or refuse unsafe
  replacement as appropriate.
- SQLite writes commit and chronological reads, checkpointing, and FIFO eviction
  have focused regression coverage.
- Personal cloud archives remain an offline operator workflow.

### Deployment And Reliability

- The SAM template validates and builds with the supported Python runtime.
- Webhook work is limited to secret validation and SQS enqueueing.
- SQS FIFO preserves per-chat ordering and uses one update per worker batch.
- Provider timeouts, blocked responses, transient failures, Telegram permanent
  failures, and long output have offline regression coverage.

## Residual Risks

- `aws_worker.py` and `llm.py` are large modules. Their behavior is well covered,
  but future feature batches should extract cohesive routing/provider components
  instead of extending them indefinitely.
- No real-provider smoke test was run during final review because offline tests
  cover the adapters and the roadmap requires quota-safe verification.
- The reviewed production stack overrides the template defaults with
  `MaxInputTokens=10000` and `SummaryOutputTokens=5000`. Telegram splitting
  keeps that output safe, but the larger output allowance can consume more
  provider quota than the documented 1,500-token default.
- Telegram mobile rendering and provider availability remain external runtime
  concerns; verify `/menu`, `/chat`, `/summarize`, and `/usage` after deployment.
- Production deployment should use a scoped IAM or SSO role, never the AWS root
  identity.

## Verification Commands

```bash
.venv/bin/python -m pytest -q
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam validate --lint
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam build
git diff --check
```
