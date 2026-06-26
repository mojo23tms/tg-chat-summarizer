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
  calls Gemini for summaries
  stores usage records
  sends Telegram Bot API replies
DynamoDB
  stores messages, settings, owner state, usage
```

The webhook Lambda returns quickly so Telegram does not retry while Gemini is
working. Slow work happens asynchronously in the SQS worker.

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
telegram_summarizer/llm.py
```

Builds prompts, calls Gemini, extracts usage metadata when available, estimates
tokens otherwise, and auto-selects messages for context budget.

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

### Usage Records

```text
pk = CHAT#{chat_id}
sk = USAGE#{timestamp_padded}
```

Attributes:

```text
messages_count
input_tokens
output_tokens
total_tokens
estimated
model
```

Gemini usage metadata is used when available. Otherwise usage is estimated.

## Command Routing

Normal non-command text is logged as a message. Commands are not logged as chat
history.

`/summarize N`:

1. clamps `N` to `1..MAX_COUNT`
2. reads recent messages for the current chat
3. builds a Gemini prompt
4. sanitizes returned Telegram HTML
5. records usage
6. replies in the same chat

`/summarize auto`:

1. reads up to `MAX_COUNT` recent messages
2. estimates prompt tokens
3. selects newest messages fitting `MAX_INPUT_TOKENS - SUMMARY_OUTPUT_TOKENS`
4. summarizes selected messages

Settings commands:

- In groups, only Telegram admins/creators can update settings.
- In private DMs, users listed in `BOT_OWNER_IDS` can select a target chat with
  `/usechat` and update that chat's settings.

## Telegram HTML Safety

Gemini is asked to return Telegram-compatible HTML. The bot then sanitizes the
summary before sending it with `ParseMode.HTML`.

Allowed tags:

```text
<b>, <strong>, <i>, <em>, <u>, <s>, <code>, <pre>, <blockquote>
```

Unsupported tags and attributes are removed. Raw text is escaped. Markdown
bold markers are converted as a fallback.

## Reliability Boundaries

- Webhook acknowledgement is independent from Gemini latency.
- SQS FIFO preserves per-chat ordering by message group.
- Telegram permanent 4xx errors are acknowledged to avoid endless SQS retries.
- Rate limits and transient errors are allowed to retry.
- Tests block network access by default.
