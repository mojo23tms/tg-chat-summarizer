# Memory System

The memory system is the low-cost alternative to repeatedly sending huge message ranges to an LLM.

## Goal

Turn raw chat history into compact, reusable memory objects that preserve friend-group culture.

## Memory Snapshot Contents

A snapshot may contain:

- running jokes;
- nicknames and aliases;
- canon events;
- funny quotes;
- recurring topics;
- people lore;
- unresolved stories;
- notable roasts or conflicts;
- questions the group keeps returning to;
- terms that need explanation later.

## Storage

Runtime memory snapshots should live in DynamoDB. Use explicit key patterns and keep compatibility with existing message/settings/usage records.

Cloud archive copies may later be exported to Google Drive or NordLocker, but those copies must not be needed for live bot replies.

## Cost Strategy

Admins explicitly generate snapshots with `/remember [N|auto]`. The command
reads at most `MEMORY_MAX_MESSAGES`, applies the shared input-token budget,
requires structured JSON, and records provider usage. Explicit generation is
the configured low-cost mode for this batch; no background provider calls occur.

`/ask` keyword-ranks up to five snapshots from a bounded recent-memory scan and
budgets them together with selected raw messages. Raw evidence takes precedence
if a compressed snapshot conflicts with it.

Repeated generation over the same source timestamp range overwrites the prior
snapshot. Runtime snapshots are chat-scoped and never read from S3 or personal
cloud storage.

## Future Extension

Embeddings may be added later for memory snapshots first. Do not embed every raw Telegram message unless there is a clear cost and value justification.

## Historical Backfill

`scripts/backfill_historical_memory.py` processes messages already present in
DynamoDB from oldest to newest. It uses bounded explicit chunks, persists a
chat-scoped checkpoint only after a successful provider response, and resumes
after failure without regenerating completed ranges. Completed jobs can be run
again to process only newly arrived messages.

Historical snapshots add deterministic lexical terms, participants, source
timestamps, and Telegram message IDs. Dry-run mode estimates calls, tokens, and
operator-supplied pricing without calling an LLM or writing state. See
`docs/historical-memory-backfill.md` for operations and recovery.
