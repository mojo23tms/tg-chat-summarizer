# Telegram Summarizer Bot

AWS-first Telegram bot that records chat messages and summarizes recent history
with Gemini or Groq. Production runs on API Gateway, Lambda, SQS FIFO, and DynamoDB
through AWS SAM. A legacy local/Fly.io long-polling mode is still available for
development and rollback.

## What It Does

- Receives Telegram updates through a secure webhook.
- Stores normal text messages per chat in DynamoDB.
- Summarizes recent chat history from inline buttons, with `/summarize`,
  `/summarize N`, and `/summarize auto` kept as fallbacks.
- Answers evidence-grounded questions about bounded chat history with `/ask`.
- Stores compact friend-chat lore snapshots with admin-only `/remember` and
  uses relevant memories in `/ask`.
- Answers direct non-history questions with `/chat`.
- Replies with Telegram HTML formatting.
- Tracks estimated or provider-reported token usage.
- Lets configured bot owners manage group settings from direct messages.
- Imports Telegram Desktop JSON history from a local file or offline S3 source
  into DynamoDB.
- Provides bounded chat-scoped retrieval primitives for future history-aware
  commands.

## Documentation Map

- [Architecture](docs/architecture.md): runtime flow, package layout, data model,
  and command behavior.
- [Operations Runbook](docs/operations.md): setup, deploy, update, debugging,
  maintenance, and rollback.
- [History Import](docs/history-import.md): export Telegram history and import it
  into DynamoDB safely.

## Current Tech Stack

- Python package: `telegram_summarizer`
- Infrastructure: AWS SAM
- Production entrypoints:
  - `telegram_summarizer.aws_webhook.lambda_handler`
  - `telegram_summarizer.aws_worker.lambda_handler`
- Production services:
  - API Gateway HTTP API
  - Lambda
  - SQS FIFO
  - DynamoDB on-demand with TTL
  - Secrets Manager
  - CloudWatch Logs
- LLM: Gemini via `google-generativeai`; Groq via its OpenAI-compatible Chat
  Completions API
- Telegram API:
  - webhook ingestion from Telegram
  - direct Bot API calls for replies/admin checks
- Tests: offline `pytest`

## Repository Layout

```text
telegram_summarizer/
  aws_webhook.py        API Gateway webhook Lambda
  aws_worker.py         SQS worker Lambda and command routing
  config.py             environment-driven configuration
  dynamodb_storage.py   DynamoDB adapter
  handlers.py           legacy local/Fly long-polling handlers
  helpers.py            parsing, escaping, Telegram HTML sanitizer
  history_qa.py         shared bounded history Q&A orchestration
  llm.py                LLM prompting, provider adapters, usage metadata
  memory.py             structured low-cost memory generation
  main.py               legacy local/Fly polling entrypoint
  storage.py            SQLite adapter for legacy local/Fly mode
  telegram_api.py       small Telegram Bot API client

scripts/
  set_webhook.py            register Telegram webhook
  import_telegram_export.py import local/S3 Telegram Desktop JSON history

tests/                  offline pytest suite
docs/                   current project documentation
template.yaml           AWS SAM infrastructure
samconfig.toml          saved SAM deploy settings
Dockerfile / fly.toml   legacy Fly.io deployment path
```

## Required Configuration

Production SAM parameters:

```text
AppSecretId              Secrets Manager secret name
MessageTtlDays           default 365
BotOwnerIds              comma-separated Telegram user ids, optional
MaxInputTokens           default 25000
SummaryOutputTokens      default 1500
AskOutputTokens          default 500
MemoryOutputTokens       default 1000
MemoryMaxMessages        default 500
SummaryMaxMessages       default 5000
LlmRequestTimeoutSeconds default 45
GeminiDailyTokenQuota    default 0, disabled
GroqDailyTokenQuota      default 0, disabled
QuotaWarningRemainingPercent default 10
```

Runtime environment variables used by Lambda:

```text
APP_SECRET_ID=telegram-summarizer/prod
DDB_TABLE_NAME
QUEUE_URL
MESSAGE_TTL_DAYS=365
BOT_OWNER_IDS=
MAX_INPUT_TOKENS=25000
SUMMARY_OUTPUT_TOKENS=1500
ASK_OUTPUT_TOKENS=500
MEMORY_OUTPUT_TOKENS=1000
MEMORY_MAX_MESSAGES=500
SUMMARY_MAX_MESSAGES=5000
LLM_REQUEST_TIMEOUT_SECONDS=45
GEMINI_DAILY_TOKEN_QUOTA=0
GROQ_DAILY_TOKEN_QUOTA=0
QUOTA_WARNING_REMAINING_PERCENT=10
LLM_BACKEND=gemini
DEFAULT_LLM_PROVIDER=gemini
DEFAULT_LLM_MODEL=
GEMINI_MODEL=gemini-2.5-flash-lite
GROQ_MODEL=llama-3.3-70b-versatile
```

`APP_SECRET_ID` must point to a JSON secret containing:

```json
{
  "TELEGRAM_TOKEN": "...",
  "GEMINI_API_KEY": "...",
  "GROQ_API_KEY": "...",
  "TELEGRAM_WEBHOOK_SECRET": "..."
}
```

## Fresh Launch

1. Install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   .venv/bin/python -m pip install -r requirements.txt
   ```

2. Create or update the production secret:

   ```bash
   export TELEGRAM_TOKEN="..."
   export GEMINI_API_KEY="..."
   export GROQ_API_KEY="..."
   export TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)"

   DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws secretsmanager put-secret-value \
     --secret-id telegram-summarizer/prod \
     --secret-string "{\"TELEGRAM_TOKEN\":\"$TELEGRAM_TOKEN\",\"GEMINI_API_KEY\":\"$GEMINI_API_KEY\",\"GROQ_API_KEY\":\"$GROQ_API_KEY\",\"TELEGRAM_WEBHOOK_SECRET\":\"$TELEGRAM_WEBHOOK_SECRET\"}" \
     --region eu-central-1
   ```

   If the secret does not exist yet, use `aws secretsmanager create-secret`
   with the same `--name`, `--secret-string`, and `--region`.

3. Validate locally:

   ```bash
   .venv/bin/python -m pytest -q
   DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam validate --lint
   ```

4. Deploy AWS:

   ```bash
   DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam build

   DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam deploy \
     --stack-name telegram-summarizer-bot \
     --region eu-central-1 \
     --capabilities CAPABILITY_IAM \
     --parameter-overrides \
       AppSecretId=telegram-summarizer/prod \
       MessageTtlDays=365 \
       BotOwnerIds="" \
       MaxInputTokens=25000 \
       SummaryOutputTokens=1500 \
       SummaryMaxMessages=5000 \
       LlmRequestTimeoutSeconds=45
   ```

5. Register Telegram webhook:

   ```bash
   export WEBHOOK_URL="$(DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws cloudformation describe-stacks \
     --stack-name telegram-summarizer-bot \
     --region eu-central-1 \
     --query 'Stacks[0].Outputs[?OutputKey==`WebhookUrl`].OutputValue' \
     --output text)"

   .venv/bin/python scripts/set_webhook.py "$WEBHOOK_URL" \
     --secret-id telegram-summarizer/prod \
     --region eu-central-1
   ```

6. Verify in Telegram:

   ```text
   /menu
   /whoami
   normal test message
   /chat write a one-line roast about slow deploys
   tap Summarize
   tap Usage
   ```

7. Redeploy with `BotOwnerIds` after `/whoami` returns your `user_id`:

   ```bash
   DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam deploy \
     --stack-name telegram-summarizer-bot \
     --region eu-central-1 \
     --capabilities CAPABILITY_IAM \
     --parameter-overrides \
       AppSecretId=telegram-summarizer/prod \
       MessageTtlDays=365 \
       BotOwnerIds="YOUR_TELEGRAM_USER_ID" \
       MaxInputTokens=25000 \
       SummaryOutputTokens=1500 \
       SummaryMaxMessages=5000 \
       LlmRequestTimeoutSeconds=45
   ```

## Daily Workflow

Development:

```bash
.venv/bin/python -m pytest -q
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam validate --lint
```

Deploy update:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam build
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam deploy --region eu-central-1
```

Watch logs:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam logs \
  --stack-name telegram-summarizer-bot \
  --name WorkerFunction \
  --region eu-central-1 \
  --tail
```

## Bot Menu And Commands

`/start`, `/help`, and `/menu` install a persistent reply keyboard below the
Telegram text field. Commands that need free text ask for it in the next
message. The older AWS inline settings callbacks remain compatible. Slash
commands remain available as a fallback:

```text
/menu                    show or restore the persistent button menu
/ask <question>          answer from bounded current-chat history evidence
/remember [N|auto]       admin: store compact lore, max 500 source messages
/chat <question>         ask a general question; does not search chat history
/summarize [N|auto]       summarize latest messages; manual max is 5000
/lore                    established lore and canon
/insidejoke <term>       explain a recurring reference
/bestof [period]         memorable moments; defaults to month
/quotes [user]           evidence-backed group or person quotes
/recap [period]          recap today/week/month/year/all; defaults to month
/help or /start           show current commands and buttons
/settings                 show settings for current or selected chat
/setstyle <text>          set summary style; admins or owner DM
/setfilter off|clean|strict
/setlang <code|auto>
/models                  list available LLM providers and starter models
/setprovider gemini|groq set provider; admins or owner DM
/setmodel <model|provider:model>
/usage [today|month]      show token usage records
/whoami                   show your user id and chat id
/chats                    owner DM: list known chat ids
/usechat <chat_id>        owner DM: select target chat
```

Daily provider token quotas are optional. Set `GEMINI_DAILY_TOKEN_QUOTA` and/or
`GROQ_DAILY_TOKEN_QUOTA` to a positive value to warn each chat once per provider
per UTC day when remaining tokens are at or below
`QUOTA_WARNING_REMAINING_PERCENT`.

## Important Operational Rules

- Do not run Telegram webhook mode and long polling against the same bot token at
  the same time.
- For group chats, disable BotFather privacy mode or make the bot a group admin,
  otherwise normal messages may not reach the bot.
- Telegram cannot provide old history through the Bot API. Use Telegram Desktop
  JSON export plus `scripts/import_telegram_export.py`; `--s3-uri` is supported
  for offline backfill.
- Runtime history retrieval reads bounded DynamoDB pages. Lambda never reads S3
  in the Telegram request path.
- `/ask` searches only the current chat, combines bounded raw evidence with
  relevant compact memory snapshots, and reports when evidence is missing.
- `/remember` is an explicit admin-only LLM operation; snapshots are not
  generated silently, keeping quota spend predictable.
- DynamoDB TTL is eventual. `MESSAGE_TTL_DAYS=365` controls expiration metadata,
  not exact deletion time.
- The bot maintains a lightweight DynamoDB `CHATS` index for owner chat
  discovery. Imported history also updates this index.
- Tests intentionally block external network calls to protect Telegram, LLM
  providers, AWS, and free-tier quota.

## Local Legacy Mode

Use local long polling only for development or rollback:

```bash
export TELEGRAM_TOKEN="..."
export GEMINI_API_KEY="..."
export GROQ_API_KEY="..."
export DB_PATH=data/bot.db
.venv/bin/python -m telegram_summarizer.main
```

Rollback from AWS webhook to polling:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/deleteWebhook"
.venv/bin/python -m telegram_summarizer.main
```

Full operational details are in [docs/operations.md](docs/operations.md).
