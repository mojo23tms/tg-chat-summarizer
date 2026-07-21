# History Import And Offline S3 Backfill

Telegram bots cannot fetch old chat history through the Bot API. To seed the
summarizer with past messages, export the chat from Telegram Desktop as JSON and
import that file into DynamoDB. The importer can read a local file or an S3
object, but S3 access is an offline operator action and never part of a live
Telegram request.

## Export From Telegram Desktop

Use the cross-platform Telegram Desktop app, not the macOS App Store client if
the export option is missing.

1. Open the target chat.
2. Use chat menu -> export chat history.
3. Choose JSON.
4. Export messages only if possible. Media is not used by the current bot.
5. Keep the resulting `result.json` private.

## Find The Correct Chat ID

Send `/whoami` in the target chat. Use the returned `chat_id`.

You can also inspect the DynamoDB chat index:

```bash
export DDB_TABLE_NAME="telegram-summarizer-bot-BotTable-..."

DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws dynamodb query \
  --table-name "$DDB_TABLE_NAME" \
  --key-condition-expression 'pk = :pk' \
  --expression-attribute-values '{":pk":{"S":"CHATS"}}' \
  --region eu-central-1
```

Use the `chat_id` value, or the number after `CHAT#` in `sk`, for example:

```text
CHAT#-1002200584149 -> -1002200584149
```

## Dry Run

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib .venv/bin/python scripts/import_telegram_export.py \
  --file "/path/to/Telegram Desktop/ChatExport/result.json" \
  --chat-id -1002200584149 \
  --table-name "$DDB_TABLE_NAME" \
  --region eu-central-1 \
  --writer aws-cli \
  --limit 5000 \
  --dry-run
```

The dry run prints:

```text
importable text messages
skipped latest messages
selected for import
oldest selected ts
newest selected ts
```

## Dry Run From S3

Upload the private Telegram export to an access-controlled bucket, then point
the same importer at it:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib .venv/bin/python scripts/import_telegram_export.py \
  --s3-uri "s3://private-chat-archive/result.json" \
  --chat-id -1002200584149 \
  --table-name "$DDB_TABLE_NAME" \
  --region eu-central-1 \
  --writer aws-cli \
  --limit 5000 \
  --dry-run
```

The importer uses `aws s3 cp <uri> -` so it reuses the authenticated AWS CLI
session. Replace `--dry-run` with `--yes` only after checking the reported
selection. Re-running the same import is idempotent at the message-key level:
the original timestamp and Telegram message id produce the same DynamoDB key.

## Import Latest Messages

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib .venv/bin/python scripts/import_telegram_export.py \
  --file "/path/to/Telegram Desktop/ChatExport/result.json" \
  --chat-id -1002200584149 \
  --table-name "$DDB_TABLE_NAME" \
  --region eu-central-1 \
  --writer aws-cli \
  --limit 5000 \
  --yes
```

## Import Older Messages Without Rewriting Latest

If the latest 5,000 were already imported:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib .venv/bin/python scripts/import_telegram_export.py \
  --file "/path/to/Telegram Desktop/ChatExport/result.json" \
  --chat-id -1002200584149 \
  --table-name "$DDB_TABLE_NAME" \
  --region eu-central-1 \
  --writer aws-cli \
  --skip-latest 5000 \
  --limit 0 \
  --dry-run
```

Replace `--dry-run` with `--yes` after confirming the selected count.

## Import Everything

This rewrites messages that were already imported if keys match, but DynamoDB
will store one item per message key.

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib .venv/bin/python scripts/import_telegram_export.py \
  --file "/path/to/result.json" \
  --chat-id -1002200584149 \
  --table-name "$DDB_TABLE_NAME" \
  --region eu-central-1 \
  --writer aws-cli \
  --limit 0 \
  --yes
```

## What Gets Imported

The importer:

- accepts exactly one source: `--file` or `--s3-uri`
- reads Telegram Desktop `result.json`
- skips service events
- skips empty/media-only messages
- preserves original message timestamps for ordering
- stores text in the same DynamoDB schema used by live messages
- upserts the `CHATS` index used by `/chats`
- sets TTL from import time, so old exported messages do not expire immediately

S3 credentials and bucket permissions are needed only by the machine running
the import. Neither Lambda function receives S3 permissions for retrieval.

## Verify Import

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws dynamodb query \
  --table-name "$DDB_TABLE_NAME" \
  --key-condition-expression 'pk = :pk AND begins_with(sk, :prefix)' \
  --expression-attribute-values '{":pk":{"S":"CHAT#-1002200584149"},":prefix":{"S":"MSG#"}}' \
  --select COUNT \
  --region eu-central-1
```

Then test in Telegram:

```text
/summarize
/summarize 100
/summarize auto
```

## Cost And Quota Notes

- DynamoDB batch write limit is 25 items per request; the script batches for you
  and retries unprocessed items with backoff.
- Rewriting already-imported items wastes writes but does not duplicate records.
- `/summarize` still only sends selected recent messages to Gemini.
- Importing more history increases DynamoDB storage, not per-summary LLM usage.
- Future history-aware commands retrieve bounded DynamoDB pages; they do not
  download the S3 export at request time.
