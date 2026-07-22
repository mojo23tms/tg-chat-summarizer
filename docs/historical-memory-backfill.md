# Historical Memory Backfill

This offline operator job turns messages already imported into DynamoDB into
compact, searchable historical memory snapshots. It is designed for archives of
roughly 50,000 messages without loading the archive into memory or sending it to
an LLM in one prompt.

The job never reads S3. Run the existing Telegram export importer first so the
runtime DynamoDB table contains the raw messages.

## Safety And Cost Model

- Messages are read chronologically in chunks of at most 500.
- The default run processes at most 5,000 messages and then stops safely.
- Each completed chunk advances a chat-scoped checkpoint.
- A failed provider call leaves the failed chunk uncheckpointed for safe retry.
- Snapshot keys use their source time range, so reruns overwrite rather than
  duplicate the same completed range.
- Input and output token budgets are explicit.
- Dry runs perform no provider calls and no writes.
- Live Telegram commands continue to read DynamoDB only and make one bounded
  answer-generation call.

Memory snapshots contain compact summaries, structured lore, participants,
deterministic lexical terms, source timestamps, and source Telegram message IDs.
No embeddings are generated in this batch.

## Prerequisites

Authenticate AWS and expose the production secret to the local process:

```bash
aws login
export APP_SECRET_ID=telegram-summarizer/prod
export DDB_TABLE_NAME="telegram-summarizer-bot-BotTable-..."
export AWS_REGION=eu-central-1
```

Use `/whoami` in Telegram to obtain the target chat ID.

## Dry Run

Provide current provider prices explicitly; the script does not hardcode prices
that may become stale:

```bash
.venv/bin/python scripts/backfill_historical_memory.py \
  --chat-id -1002200584149 \
  --chunk-size 250 \
  --max-messages 5000 \
  --max-input-tokens 12000 \
  --output-tokens 800 \
  --provider gemini \
  --model gemini-2.5-flash-lite \
  --input-cost-per-million 0.10 \
  --output-cost-per-million 0.40 \
  --max-estimated-cost 1.00 \
  --dry-run
```

The JSON report includes remaining messages examined in this run, projected
chunks, estimated input/output tokens, estimated cost, and any chunk that would
exceed the configured input budget. Verify current provider pricing before
using the estimate.

If `oversized_chunks` is non-zero, lower `--chunk-size` before the real run.

## Run And Resume

After reviewing the dry run:

```bash
.venv/bin/python scripts/backfill_historical_memory.py \
  --chat-id -1002200584149 \
  --chunk-size 250 \
  --max-messages 5000 \
  --max-input-tokens 12000 \
  --output-tokens 800 \
  --provider gemini \
  --model gemini-2.5-flash-lite \
  --input-cost-per-million 0.10 \
  --output-cost-per-million 0.40 \
  --max-estimated-cost 1.00 \
  --yes
```

Run the same command again until `status` is `complete`. Each run resumes after
the last successful chunk. Running it later processes messages added since
completion instead of rebuilding the archive.

The cost cap is checked before each provider call. The report includes actual
provider tokens and a quota warning when configured daily quota usage reaches
the repository's warning threshold.

Use `--start-ts` and `--end-ts` to constrain the initial job to a Unix timestamp
range. A checkpoint is tied to that range.

## Failure And Recovery

Provider, validation, or network failures stop immediately. Fix the cause and
run the same command again; the failed chunk is retried and earlier chunks are
not charged again.

If a chunk exceeds the token budget, lower `--chunk-size`. Do not increase the
budget blindly.

## Reset And Rollback

Reset only when intentionally rebuilding with a different timestamp range:

```bash
.venv/bin/python scripts/backfill_historical_memory.py \
  --chat-id -1002200584149 \
  --reset-checkpoint \
  --yes
```

The reset command exits after clearing the checkpoint. Run a new dry run before
starting the replacement range.

Resetting the checkpoint does not delete snapshots. Existing time-range keys
remain idempotent, but rerunning them still consumes provider quota. To disable
historical enrichment without deleting data, stop running the operator job;
live retrieval remains bounded and compatible with ordinary raw history.

## Privacy

Historical chunk contents are sent to the explicitly selected LLM provider.
Treat the chat export, DynamoDB table, generated memories, credentials, and dry
run reports as private. S3, Google Drive, and NordLocker are never contacted by
the backfill or live retrieval path.
