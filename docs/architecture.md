# Architecture

This project is now AWS-first. Local/Fly long polling is retained as a legacy
development and rollback path, but the canonical production runtime is the
serverless webhook pipeline.

## Runtime Flow

```text
Telegram
  POST /telegram
API Gateway HTTP API
  invokes
WebhookFunction: telegram_summarizer.aws_webhook.lambda_handler
  validates X-Telegram-Bot-Api-Secret-Token
  enqueues raw update
SQS FIFO queue
  deduplicates by update_id
  groups by chat_id
WorkerFunction: telegram_summarizer.aws_worker.lambda_handler
  logs text messages
  routes commands
  calls the selected LLM provider for summaries, Q&A, and memory snapshots
  stores usage records and compact memories
  sends Telegram Bot API replies
DynamoDB
  stores messages, memories, chat index, settings, owner state, usage
Secrets Manager
  stores Telegram token, provider API keys, and webhook secret
```

The webhook Lambda returns quickly so Telegram does not retry while LLM work is
working. Slow work happens asynchronously in the SQS worker.

Both Lambda functions receive `APP_SECRET_ID` and read
`TELEGRAM_TOKEN`, `GEMINI_API_KEY`, `GROQ_API_KEY`, and
`TELEGRAM_WEBHOOK_SECRET` from AWS Secrets Manager during cold start. Raw
production secrets are not passed as SAM parameters or stored in Lambda
environment variables.

## Package Layout

```text
telegram_summarizer/aws_webhook.py
```

Receives API Gateway events, validates Telegram's secret header, extracts
dedupe/group identifiers, and sends updates to SQS FIFO.

```text
telegram_summarizer/aws_worker.py
```

Processes SQS records, logs messages, handles commands, performs admin/owner
checks, calls the LLM layer, records token usage, and sends replies.

```text
telegram_summarizer/dynamodb_storage.py
```

DynamoDB adapter. Owns table key shapes and record formats.

```text
telegram_summarizer/retrieval.py
```

Reusable bounded history retrieval. It accepts provider-independent keyword,
user, date, result-limit, and scan-limit inputs, paginates chat-scoped DynamoDB
message reads, and returns chronological evidence plus truncation metadata.

```text
telegram_summarizer/history_qa.py
```

Shared `/ask` orchestration for AWS and legacy local mode. It extracts useful
search terms, invokes bounded retrieval, applies the LLM input-token budget,
short-circuits without a provider call when evidence is absent, and returns
retrieval metadata with the structured LLM result. It combines relevant compact
memory snapshots with selected raw messages under one token budget.

```text
telegram_summarizer/memory.py
```

Validates structured provider JSON, attaches source-range metadata, and stores
bounded friend-chat memory snapshots without exposing provider details.

```text
telegram_summarizer/historical_backfill.py
scripts/backfill_historical_memory.py
```

Offline chronological archive processing with per-chat checkpoints, explicit
token/cost guards, idempotent snapshot ranges, dry-run estimates, and safe
failure resume. It reads DynamoDB only; S3 remains an earlier import source.

```text
telegram_summarizer/lore.py
```

Shared thin orchestration for `/lore`, `/insidejoke`, `/bestof`, `/quotes`, and
`/recap`. Every command delegates to the retrieval/memory Q&A path with at most
500 scanned raw messages, 30 selected evidence messages, and 8 memory snapshots.

```text
telegram_summarizer/bot_menu.py
```

Defines the shared full manual and persistent Telegram reply-keyboard layout
used by AWS webhook mode and legacy local polling mode.

```text
telegram_summarizer/llm.py
```

Builds prompts, routes calls through provider adapters, extracts usage metadata
when available, estimates tokens otherwise, and auto-selects messages for
context budget. Gemini is the default provider; Groq is supported through its
OpenAI-compatible chat completions API.

```text
telegram_summarizer/helpers.py
```

Shared parsing, Telegram mention formatting, profanity safety-net filtering, and
Telegram HTML sanitization.

```text
telegram_summarizer/telegram_api.py
```

Small `urllib` Telegram Bot API client used by Lambda and webhook setup.

```text
telegram_summarizer/handlers.py
telegram_summarizer/main.py
telegram_summarizer/storage.py
```

Legacy local/Fly long-polling path using SQLite.

## DynamoDB Table

Single table with:

```text
pk  string partition key
sk  string sort key
```

### Messages

```text
pk = CHAT#{chat_id}
sk = MSG#{ts_padded}#{msg_id_padded}
```

Attributes:

```text
msg_id
user_id
user_name
text
ts
expires_at
```

`expires_at` is used by DynamoDB TTL. The default retention is 365 days.

Every live message write also upserts a lightweight chat index item:

```text
pk = CHATS
sk = CHAT#{chat_id}
```

Attributes:

```text
chat_id
last_seen_at
```

Owner DM commands use this index for `/chats`. If the index is empty, the
storage adapter can still scan old `CHAT#...` partitions as a compatibility
fallback.

### Settings

```text
pk = CHAT#{chat_id}
sk = SETTINGS
```

Attributes:

```text
style
filter_level
language
```

Defaults come from `telegram_summarizer.config.DEFAULTS`.

### Owner Active Chat

```text
pk = OWNER#{user_id}
sk = ACTIVE_CHAT
```

Attributes:

```text
chat_id
```

Used so a bot owner can DM the bot and change settings for a selected group.
Selecting a chat with `/usechat` also upserts the `CHATS` index entry, so owner
controls can work even before the next live message arrives.

### Usage Records

```text
pk = CHAT#{chat_id}
sk = USAGE#{timestamp_padded}#{nanosecond_suffix}
```

Attributes:

```text
messages_count
input_tokens
output_tokens
total_tokens
estimated
provider
model
```

Provider usage metadata is used when available. Otherwise usage is estimated.
The suffix prevents multiple summaries in the same second from overwriting each
other.

Optional daily token quota warnings are computed from usage records per
chat/provider/model for the current UTC day. If a provider quota is configured
and remaining tokens are at or below the warning threshold, the worker sends one
warning per chat/provider/day and stores a short-lived marker item:

```text
pk = CHAT#<chat_id>
sk = QUOTA_WARN#<provider>#<YYYY-MM-DD>
```

### Memory Snapshots

```text
pk = CHAT#{chat_id}
sk = MEMORY#{start_timestamp_padded}#{end_timestamp_padded}
```

Snapshots store version, creation/source timestamps, source message count, a
compact summary, structured lore items, participants, lexical terms, and source
message IDs. Rebuilding the same source range overwrites it rather than creating
a duplicate. Reads are bounded and scoped to one chat partition.

Historical progress uses `CHAT#{chat_id}` / `BACKFILL#HISTORICAL_MEMORY`. The
opaque chronological cursor advances only after a successful chunk, so failures
resume without gaps and completed jobs can later process newly arrived messages.

## Command Routing

Normal non-command text is logged as a message. Commands are not logged as chat
history.

`/summarize N`:

1. clamps `N` to `1..SUMMARY_MAX_MESSAGES`
2. reads recent messages for the current chat
3. builds a provider-independent summary prompt
4. sanitizes returned Telegram HTML
5. records usage
6. replies in the same chat

`/summarize auto`:

1. reads up to `SUMMARY_MAX_MESSAGES` recent messages
2. estimates prompt tokens
3. selects newest messages fitting `MAX_INPUT_TOKENS - SUMMARY_OUTPUT_TOKENS`
4. summarizes selected messages

`/chat <question>`:

1. does not read stored chat messages or search history
2. builds a provider-independent direct-answer prompt with the shared safety rules
3. sanitizes returned Telegram HTML
4. records usage with `messages_count = 0`
5. replies in the same chat

`/ask <question>`:

1. immediately acknowledges that history search started
2. extracts useful terms from the question
3. retrieves bounded raw evidence and relevant memory snapshots from the
   current chat partition only
4. trims the combined context to `MAX_INPUT_TOKENS - ASK_OUTPUT_TOKENS`
5. skips the LLM and admits missing evidence when both sources are empty
6. asks the selected provider for an evidence-grounded answer capped by
   `ASK_OUTPUT_TOKENS`
7. sanitizes/splits Telegram HTML and records usage against the evidence count

`/remember [N|auto]` is admin-only and explicitly generates a structured memory
snapshot from at most `MEMORY_MAX_MESSAGES`, bounded by
`MAX_INPUT_TOKENS - MEMORY_OUTPUT_TOKENS`. It records provider usage and does
not run automatically, so LLM spend remains predictable.

Lore commands reuse `/ask`'s safe output and evidence rules. Period commands
apply timestamp bounds before retrieval; `/quotes` applies a user-name filter;
all lore scans are capped below the general `/ask` ceiling.

`/menu`, `/help`, and `/start` attach a persistent reply keyboard below the
Telegram input field. Free-text buttons store one short-lived pending action and
consume only that user's next message in the same chat. Slash commands remain
compatible, and old AWS inline callbacks still work.

`/chat` continues to avoid history reads.

## Retrieval And Historical Backfill

Historical Telegram Desktop JSON exports can be imported from a local file or
read offline from an S3 URI. Both paths normalize messages into the existing
`CHAT#{chat_id}` / `MSG#...` item family, so repeated imports overwrite the same
keys rather than creating duplicates.

Live retrieval:

1. receives a chat id and bounded retrieval request
2. queries only that chat partition and optional timestamp range
3. follows pagination up to the configured scan limit
4. filters keyword/user matches and ranks the newest strongest matches
5. returns selected messages chronologically with scan/truncation metadata

S3 is never called by the webhook or worker Lambda. It is an offline backfill
source only, and the SAM template intentionally grants no S3 runtime access.

Settings commands:

- In groups, only Telegram admins/creators can update settings.
- In private DMs, users listed in `BOT_OWNER_IDS` can select a target chat with
  `/usechat` and update that chat's settings.
- `/models` lists supported providers and starter models.
- `/setprovider <provider>` sets a chat's provider and resets the model to that
  provider default.
- `/setmodel <model|provider:model>` sets a custom model, optionally changing
  provider at the same time.

## Telegram HTML Safety

The selected provider is given a shared safety instruction that treats Telegram
history as data, not instructions. Prompt text explicitly says not to reveal
secrets, not to follow instructions embedded in chat-history data, and to return
concise Telegram-compatible HTML without Markdown.

Chat-history messages are wrapped in explicit start/end delimiters before they
are sent to the model. The bot then sanitizes the summary before sending it with
`ParseMode.HTML`.

Allowed tags:

```text
<b>, <strong>, <i>, <em>, <u>, <s>, <code>, <pre>, <blockquote>
```

Unsupported tags and attributes are removed. Raw text is escaped. Markdown
bold markers are converted as a fallback.

## Reliability Boundaries

- Webhook acknowledgement is independent from LLM provider latency.
- Provider requests use `LLM_REQUEST_TIMEOUT_SECONDS` so the worker can send a
  failure reply before the Lambda timeout.
- SQS FIFO preserves per-chat ordering by message group.
- Telegram permanent 4xx errors are acknowledged to avoid endless SQS retries.
- Rate limits and transient errors are allowed to retry.
- Tests block network access by default.
