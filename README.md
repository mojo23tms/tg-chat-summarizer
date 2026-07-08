# Telegram Summarizer Bot

AWS-first Telegram bot that records chat messages and summarizes recent history
with Gemini. Production runs on API Gateway, Lambda, SQS FIFO, and DynamoDB
through AWS SAM. A legacy local/Fly.io long-polling mode is still available for
development and rollback.

## What It Does

- Receives Telegram updates through a secure webhook.
- Stores normal text messages per chat in DynamoDB.
- Summarizes recent chat history from inline buttons, with `/summarize`,
  `/summarize N`, and `/summarize auto` kept as fallbacks.
- Replies with Telegram HTML formatting.
- Tracks estimated or provider-reported token usage.
- Lets configured bot owners manage group settings from direct messages.
- Imports Telegram Desktop JSON history into DynamoDB.

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
- LLM: Gemini via `google-generativeai`
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
  llm.py                Gemini prompting, token estimates, usage metadata
  main.py               legacy local/Fly polling entrypoint
  storage.py            SQLite adapter for legacy local/Fly mode
  telegram_api.py       small Telegram Bot API client

scripts/
  set_webhook.py            register Telegram webhook
  import_telegram_export.py import Telegram Desktop JSON history

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
LLM_BACKEND=gemini
```

`APP_SECRET_ID` must point to a JSON secret containing:

```json
{
  "TELEGRAM_TOKEN": "...",
  "GEMINI_API_KEY": "...",
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
   export TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)"

   DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws secretsmanager put-secret-value \
     --secret-id telegram-summarizer/prod \
     --secret-string "{\"TELEGRAM_TOKEN\":\"$TELEGRAM_TOKEN\",\"GEMINI_API_KEY\":\"$GEMINI_API_KEY\",\"TELEGRAM_WEBHOOK_SECRET\":\"$TELEGRAM_WEBHOOK_SECRET\"}" \
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
       SummaryOutputTokens=1500
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
       SummaryOutputTokens=1500
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

In AWS production, `/start`, `/help`, and `/menu` open the inline button menu.
Use the menu to summarize, inspect usage, view settings, and change settings.
Slash commands remain available as a fallback:

```text
/menu                    open the inline button menu
/summarize [N|auto]       summarize latest messages; manual max is 200
/settings                 show settings for current or selected chat
/setstyle <text>          set summary style; admins or owner DM
/setfilter off|clean|strict
/setlang <code|auto>
/usage [today|month]      show token usage records
/whoami                   show your user id and chat id
/chats                    owner DM: list known chat ids
/usechat <chat_id>        owner DM: select target chat
/help or /start           open the inline button menu
```

## Important Operational Rules

- Do not run Telegram webhook mode and long polling against the same bot token at
  the same time.
- For group chats, disable BotFather privacy mode or make the bot a group admin,
  otherwise normal messages may not reach the bot.
- Telegram cannot provide old history through the Bot API. Use Telegram Desktop
  JSON export plus `scripts/import_telegram_export.py`.
- DynamoDB TTL is eventual. `MESSAGE_TTL_DAYS=365` controls expiration metadata,
  not exact deletion time.
- The bot maintains a lightweight DynamoDB `CHATS` index for owner chat
  discovery. Imported history also updates this index.
- Tests intentionally block external network calls to protect Telegram, Gemini,
  AWS, and free-tier quota.

## Local Legacy Mode

Use local long polling only for development or rollback:

```bash
export TELEGRAM_TOKEN="..."
export GEMINI_API_KEY="..."
export DB_PATH=data/bot.db
.venv/bin/python -m telegram_summarizer.main
```

Rollback from AWS webhook to polling:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/deleteWebhook"
.venv/bin/python -m telegram_summarizer.main
```

Full operational details are in [docs/operations.md](docs/operations.md).
