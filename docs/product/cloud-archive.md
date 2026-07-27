# Personal Cloud Archive

Batch 12 implements a provider-neutral offline export. It creates useful local
files that can be uploaded manually to Google Drive, NordLocker, or S3 without
adding any of those providers to live Telegram handling.

The exporter makes no LLM calls, consumes no model quota, and never reads S3.
It reads one DynamoDB chat partition in pages of at most 500 records.

## Archive Contents

Each export directory contains:

- `result.json`: raw messages in a Telegram-export-compatible shape. The
  existing importer can use it for disaster recovery.
- `chat-history.md`: readable and searchable history with message content
  HTML-escaped so chat text cannot become active Markdown/HTML markup.
- `memory-snapshots.json`: portable structured lore and memory snapshots.
- `memory-snapshots.md`: a readable memory index for browsing and search.
- `manifest.json`: archive version, chat id, counts, timestamp range, file
  sizes, and SHA-256 checksums.

The directory is created atomically and an existing output directory is never
overwritten.

## Dry Run

Authenticate AWS locally and set the table name:

```bash
aws login
export DDB_TABLE_NAME="telegram-summarizer-bot-BotTable-..."
export AWS_REGION=eu-central-1
```

Count the selected messages and memories without creating files:

```bash
.venv/bin/python scripts/export_personal_archive.py \
  --chat-id -1002200584149 \
  --output-dir archives/friends-chat-2026-07 \
  --page-size 250 \
  --dry-run
```

Use `--start-ts` and `--end-ts` for a partial archive. `--max-messages 0`
exports the complete selected range; a positive value creates an explicitly
bounded partial export and reports `message_truncated` when more messages exist.

## Create The Archive

After reviewing the dry run:

```bash
.venv/bin/python scripts/export_personal_archive.py \
  --chat-id -1002200584149 \
  --archive-name "Friends chat" \
  --output-dir archives/friends-chat-2026-07 \
  --page-size 250 \
  --yes
```

Choose a new output directory for every archive. The command refuses to replace
an existing directory.

## Google Drive

Upload `chat-history.md`, `memory-snapshots.md`, and `manifest.json` for easy
manual browsing and search. Keep `result.json` and `memory-snapshots.json` in a
restricted backup folder if disaster recovery is desired.

No Drive API credentials belong in the bot or Lambda environment.

## NordLocker

Add the complete export directory to NordLocker using its desktop workflow.
This is the preferred option for an encrypted copy of raw messages and memory
snapshots. NordLocker is not required to restore or run the bot.

## S3 Disaster-Recovery Copy

S3 remains an offline AWS archive option. Upload the completed directory from
the operator machine; do not grant S3 access to either Lambda:

```bash
aws s3 cp archives/friends-chat-2026-07 \
  s3://private-chat-archive/friends-chat-2026-07/ \
  --recursive \
  --sse AES256 \
  --region eu-central-1
```

Use a private bucket, block public access, and apply an appropriate lifecycle
policy.

## Verify And Restore

Compare file SHA-256 values with `manifest.json` before relying on a backup.
For example:

```bash
shasum -a 256 archives/friends-chat-2026-07/result.json
```

Restore messages through the existing dry-run-first importer:

```bash
.venv/bin/python scripts/import_telegram_export.py \
  --file archives/friends-chat-2026-07/result.json \
  --chat-id -1002200584149 \
  --limit 0 \
  --dry-run
```

Then repeat with `--yes` after verifying the target table and chat id. Message
keys remain idempotent. Memory snapshots are exported for backup and inspection;
this batch does not add automatic memory restore.

## Privacy And Runtime Boundary

The files contain private chat messages, names, user ids, and generated lore.
Protect the local directory, restrict cloud sharing, and delete temporary local
copies when they are no longer needed.

Cloud archives are never used for `/ask`, `/chat`, summaries, lore commands, or
memory generation. Runtime remains API Gateway, Lambda, SQS, and DynamoDB.
