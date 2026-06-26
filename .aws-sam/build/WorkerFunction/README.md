# Telegram Summarizer Bot

Logs Telegram chat messages and summarizes the last N messages on `/summarize`,
mentioning the caller in the reply.

The recommended production launch is AWS serverless:

- API Gateway HTTP API receives Telegram webhooks.
- A webhook Lambda validates Telegram's secret header and queues updates.
- SQS FIFO buffers updates so Telegram gets fast acknowledgements.
- A worker Lambda logs messages, handles commands, calls Gemini, and replies.
- DynamoDB stores chat messages and settings.

The older local/Fly.io path still works through Telegram long polling and
SQLite. Use it for local development, legacy deployment, or rollback.

Do not run Telegram webhook mode and long polling against the same bot token at
the same time. Telegram supports only one active delivery mode per bot.

## Project Structure

```text
telegram_summarizer/        Python application package
  aws_webhook.py            API Gateway webhook Lambda
  aws_worker.py             SQS worker Lambda and command routing
  config.py                 Environment-driven configuration
  dynamodb_storage.py       AWS DynamoDB adapter
  handlers.py               Local/Fly long-polling Telegram handlers
  helpers.py                Formatting, HTML safety, and parsing helpers
  llm.py                    Gemini prompting, token estimates, usage metadata
  main.py                   Local/Fly polling entrypoint
  storage.py                SQLite adapter for local/Fly mode
  telegram_api.py           Minimal Telegram Bot API client
scripts/                    Operational scripts
tests/                      Offline pytest suite
docs/                       Historical implementation plans
template.yaml               AWS SAM infrastructure
Dockerfile / fly.toml       Legacy Fly.io deployment
```

## Prerequisites

- Python 3.11+.
- A Telegram bot token from BotFather.
- A Gemini API key from <https://aistudio.google.com/apikey>.
- For AWS production: AWS CLI credentials and AWS SAM CLI.
- For Fly.io legacy deployment or rollback: Fly CLI.

For group chats, open BotFather and run `/setprivacy` -> `Disable` for this bot,
or add the bot as a group admin. Without that, Telegram may not deliver normal
group messages to the bot, so `/summarize` will have no history to summarize.

## Runtime Configuration

Shared variables:

```bash
TELEGRAM_TOKEN=...
GEMINI_API_KEY=...
LLM_BACKEND=gemini
```

Local/Fly long polling:

```bash
DB_PATH=data/bot.db
```

AWS serverless:

```bash
TELEGRAM_WEBHOOK_SECRET=...
DDB_TABLE_NAME=...
QUEUE_URL=...
MESSAGE_TTL_DAYS=365
BOT_OWNER_IDS=123456789
MAX_INPUT_TOKENS=25000
SUMMARY_OUTPUT_TOKENS=1500
```

In AWS, `DDB_TABLE_NAME` and `QUEUE_URL` are set by `template.yaml`. You provide
`TelegramToken`, `GeminiApiKey`, `TelegramWebhookSecret`, and optionally
`MessageTtlDays`, `BotOwnerIds`, `MaxInputTokens`, and `SummaryOutputTokens`
during `sam deploy --guided`.

## Local Launch And Debugging

Use local mode to verify the bot logic before deploying. Local mode uses
`telegram_summarizer.main`, Telegram long polling, and SQLite at `DB_PATH`.

1. Create the virtual environment and install dependencies:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Export required secrets:

   ```bash
   export TELEGRAM_TOKEN=...
   export GEMINI_API_KEY=...
   export LLM_BACKEND=gemini
   export DB_PATH=data/bot.db
   ```

3. Run tests:

   ```bash
   .venv/bin/python -m pytest -q
   ```

   Tests intentionally block external network calls. Use fake clients, fake
   openers, or injected LLM backends instead of hitting Telegram, Gemini, AWS, or
   other paid/free-tier APIs.

4. Start the bot:

   ```bash
   .venv/bin/python -m telegram_summarizer.main
   ```

5. In Telegram, send:

   ```text
   /help
   hello from local mode
   /summarize
   ```

If startup exits with `TELEGRAM_TOKEN is required` or `GEMINI_API_KEY is
required`, the environment variable is missing in the shell that runs
`telegram_summarizer.main`.

If the bot starts but does not see group messages, check BotFather privacy mode
and whether the bot is present in the group. If `/summarize` says there are no
logged messages yet, send a few normal text messages after the bot has joined
and then retry.

### macOS Homebrew Python Note

If `python3 -m venv .venv` or `pip install` fails with a `pyexpat` or `libexpat`
symbol error, reinstall Homebrew Python/expat and retry:

```bash
brew reinstall expat python@3.14
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib python3 -m venv .venv
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib .venv/bin/python -m pip install -r requirements.txt
```

## AWS Production Deploy

Use AWS for production unless you intentionally want the Fly.io long-polling
deployment.

1. Configure AWS credentials and choose the production region:

   ```bash
   aws sts get-caller-identity
   export AWS_REGION=eu-central-1
   ```

2. Build and validate the SAM app:

   ```bash
   sam build
   sam validate --lint
   ```

3. Deploy:

   ```bash
   sam deploy --guided --region eu-central-1
   ```

   Suggested guided deploy choices:

   - Stack name: `telegram-summarizer-bot`
   - AWS Region: `eu-central-1`
   - `TelegramToken`: your BotFather token
   - `GeminiApiKey`: your Gemini key
   - `TelegramWebhookSecret`: a strong random secret
   - `MessageTtlDays`: `365`
   - `BotOwnerIds`: comma-separated Telegram user ids allowed to control group
     settings from DM, for example `123456789`
   - `MaxInputTokens`: `25000`
   - `SummaryOutputTokens`: `1500`
   - Save arguments to configuration file: yes

4. Copy the `WebhookUrl` output from the deploy result.

5. Register the Telegram webhook:

   ```bash
   export TELEGRAM_TOKEN=...
   export TELEGRAM_WEBHOOK_SECRET=...
   export WEBHOOK_URL=https://your-api-id.execute-api.eu-central-1.amazonaws.com/telegram
   .venv/bin/python scripts/set_webhook.py "$WEBHOOK_URL"
   ```

6. Verify from Telegram:

   ```text
   /help
   one normal message
   another normal message
   /summarize
   /summarize auto
   /settings
   /usage
   /whoami
   ```

AWS replies are asynchronous. Telegram gets an immediate webhook
acknowledgement, while the worker Lambda sends the actual bot reply after it
processes the SQS message.

## Deploying Updates

Before every deploy:

```bash
.venv/bin/python -m pytest -q
sam validate --lint
```

Then deploy:

```bash
sam build
sam deploy --region eu-central-1
```

After deploy, send `/help` and `/summarize` in Telegram and check Lambda logs if
the bot does not respond.

## AWS Debugging Runbook

Start by identifying where the update stops.

### Telegram Does Not Reach AWS

Check the registered webhook:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/getWebhookInfo"
```

Expected:

- `url` matches the SAM `WebhookUrl` ending in `/telegram`.
- `last_error_message` is empty or old.

Common fixes:

- Register the webhook again with `scripts/set_webhook.py`.
- Confirm the URL uses the deployed API Gateway URL, not the stack output name.
- Confirm `TELEGRAM_WEBHOOK_SECRET` matches the secret used during deploy.

### API Gateway Or Webhook Lambda Returns 401 Or 400

401 means Telegram's `X-Telegram-Bot-Api-Secret-Token` did not match
`TELEGRAM_WEBHOOK_SECRET`, or the Lambda secret is empty.

400 means the webhook Lambda could not parse or enqueue the update.

Check webhook Lambda logs:

```bash
sam logs --stack-name telegram-summarizer-bot --name WebhookFunction --region eu-central-1 --tail
```

Common fixes:

- Re-run `sam deploy --guided` and set the expected webhook secret.
- Re-register the webhook with the same `TELEGRAM_WEBHOOK_SECRET`.
- Confirm the SQS queue exists and the webhook Lambda has send permissions.

### Updates Reach SQS But The Bot Does Not Reply

Check worker Lambda logs:

```bash
sam logs --stack-name telegram-summarizer-bot --name WorkerFunction --region eu-central-1 --tail
```

Check whether the SQS queue is backing up:

```bash
aws sqs list-queues --queue-name-prefix telegram-summarizer-bot --region eu-central-1
aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --region eu-central-1
```

Common fixes:

- If messages are visible and not being consumed, inspect the worker event source
  mapping and IAM policy from the CloudFormation stack.
- If worker logs show Gemini errors, verify `GEMINI_API_KEY` and retry later.
- If worker logs show Telegram API errors, verify the bot token and that the bot
  is still in the chat.

### Messages Log But Summaries Are Empty

`/summarize` only sees messages logged after this runtime started receiving
updates. There is no SQLite-to-DynamoDB migration.

Check DynamoDB for the chat partition:

```bash
export TABLE_NAME=telegram-summarizer-bot-BotTableExample
export CHAT_ID=-1001234567890
aws dynamodb query \
  --table-name "$TABLE_NAME" \
  --key-condition-expression "pk = :pk" \
  --expression-attribute-values "{\":pk\":{\"S\":\"CHAT#$CHAT_ID\"}}" \
  --region eu-central-1
```

Common fixes:

- Send normal text messages after the bot joins the chat, then retry
  `/summarize`.
- Check BotFather privacy mode for groups.
- Confirm updates are not still going to Fly.io long polling.

## Import Telegram Desktop History

Telegram cannot send old chat history to the bot through the Bot API. To seed
history, export the chat from Telegram Desktop as JSON and import text messages
into the same DynamoDB table used by AWS.

Dry-run first:

```bash
export DDB_TABLE_NAME=telegram-summarizer-bot-BotTableExample
.venv/bin/python scripts/import_telegram_export.py \
  --file "/Users/maksym.kirichenko/Downloads/Telegram Desktop/ChatExport_2026-06-26/result.json" \
  --chat-id -1001234567890 \
  --region eu-central-1 \
  --writer aws-cli \
  --limit 5000 \
  --dry-run
```

Then write the selected messages:

```bash
.venv/bin/python scripts/import_telegram_export.py \
  --file "/Users/maksym.kirichenko/Downloads/Telegram Desktop/ChatExport_2026-06-26/result.json" \
  --chat-id -1001234567890 \
  --region eu-central-1 \
  --writer aws-cli \
  --limit 5000 \
  --yes
```

Use the real Telegram chat id that the bot sees. The importer skips service
events and media-only messages, writes text messages with the normal DynamoDB
schema, and applies the current `MESSAGE_TTL_DAYS` retention. Use `--limit 0`
only if you intentionally want to import every importable text message.

To import older history after already importing the latest messages, skip the
latest imported slice first. For example, after importing the latest 5,000:

```bash
.venv/bin/python scripts/import_telegram_export.py \
  --file "/Users/maksym.kirichenko/Downloads/Telegram Desktop/ChatExport_2026-06-26/result.json" \
  --chat-id -1001234567890 \
  --region eu-central-1 \
  --writer aws-cli \
  --skip-latest 5000 \
  --limit 0 \
  --dry-run
```

Replace `--dry-run` with `--yes` after confirming the selected count.

## Fly.io Legacy Deploy And Rollback

Fly.io runs `telegram_summarizer.main` with Telegram long polling and SQLite.
Use this only if you are not using the AWS webhook, or as a rollback target.

Initial Fly setup:

```bash
fly launch --no-deploy
fly volumes create bot_data --size 1
fly secrets set TELEGRAM_TOKEN=... GEMINI_API_KEY=...
fly deploy
```

Rollback from AWS webhook to Fly polling:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/deleteWebhook"
fly deploy
```

Then check logs:

```bash
fly logs
```

If Fly starts but has no history, confirm the volume is mounted at `/data` and
`DB_PATH=/data/bot.db` is set by the Docker image.

## Maintenance

- Run `.venv/bin/python -m pytest -q` before deploying.
- Run `sam validate --lint` when SAM is installed.
- Keep secrets in environment variables, SAM parameters, or Fly secrets. Do not
  commit real tokens or API keys.
- Rotate `TELEGRAM_WEBHOOK_SECRET` by redeploying the stack and re-registering
  the webhook with the new secret.
- AWS message retention is controlled by DynamoDB TTL through
  `MESSAGE_TTL_DAYS`. The default is 365 days.
- Owner DM controls are enabled by `BOT_OWNER_IDS` / `BotOwnerIds`.
- `/summarize auto` uses `MAX_INPUT_TOKENS - SUMMARY_OUTPUT_TOKENS` as its input
  budget and selects the newest messages that fit.
- Local/Fly message retention is controlled by SQLite storage and disk headroom
  eviction.
- If changing command behavior, verify `/summarize` still works for non-admin
  users and settings commands still require admin status.

## Bot Commands

- `/summarize [N|auto]`: summarize the last N logged messages, or auto-select
  messages based on context budget. Default is 30, manual maximum is 200.
- `/settings`: show current chat settings. In owner DMs, shows the selected
  target chat settings.
- `/usage [today|month]`: show recorded LLM token usage for the current or
  selected chat.
- `/whoami`: show your Telegram user id and the current chat id.
- `/help` or `/start`: show usage.
- `/setstyle <text>`: set summary style. Admins only.
- `/setfilter off|clean|strict`: set profanity filtering. Admins only.
- `/setlang <code|auto>`: set summary language. Admins only.
- `/chats`: owner-only DM command listing known chat ids.
- `/usechat <chat_id>`: owner-only DM command selecting the target chat for
  `/settings`, `/setstyle`, `/setfilter`, `/setlang`, and `/usage`.

## Quick Symptom Index

- `TELEGRAM_TOKEN is required`: export `TELEGRAM_TOKEN` in the current shell or
  set it as a deploy secret/parameter.
- `GEMINI_API_KEY is required`: export or deploy the Gemini key.
- `/summarize` says no logged messages: send normal messages after the bot joins;
  check group privacy mode.
- Webhook returns 401: secret mismatch between SAM deploy and Telegram
  `setWebhook`.
- Webhook returns 400: invalid update body or SQS enqueue failure.
- SQS backlog grows: inspect worker Lambda logs and event source mapping.
- Bot replies slowly on AWS: normal if Gemini is slow; SQS processing is
  asynchronous.
- Local tests fail because `pytest` is missing: use `.venv/bin/python -m pytest`
  after installing `requirements.txt`.
