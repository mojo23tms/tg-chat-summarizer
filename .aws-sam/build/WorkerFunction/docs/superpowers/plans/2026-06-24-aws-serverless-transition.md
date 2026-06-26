# AWS Serverless Rewrite Plan

## Summary
Transition the bot from a Fly.io long-polling process with SQLite to an AWS serverless webhook architecture using **API Gateway HTTP API + Lambda + SQS FIFO + DynamoDB**, deployed with **AWS SAM**.

Chosen defaults:
- Use AWS-native webhook/serverless, not EC2/ECS polling.
- Use AWS SAM.
- Start fresh on DynamoDB; do not migrate SQLite data.
- Use region `eu-central-1`.
- Use SQS async processing so Telegram receives fast webhook acknowledgements and slow Gemini calls do not cause webhook retries.

## Key Changes
- Add a webhook Lambda behind `POST /telegram`.
  - Validate `X-Telegram-Bot-Api-Secret-Token` against `TELEGRAM_WEBHOOK_SECRET`.
  - Parse `update_id` and chat id from the Telegram update.
  - Enqueue the raw update to SQS FIFO with `MessageDeduplicationId=update_id` and `MessageGroupId=chat_id` or `global`.
  - Return `200` immediately.
- Add a worker Lambda consuming SQS.
  - Route text messages and commands without using `Application.run_polling()`.
  - Preserve current bot behavior for logging, `/summarize [N]`, `/settings`, `/help`, `/setstyle`, `/setfilter`, and `/setlang`.
  - Use Telegram Bot API `sendMessage` for replies and `getChatMember` for admin checks.
- Replace SQLite with DynamoDB for AWS runtime.
  - Single table with `pk` and `sk`.
  - Messages: `pk=CHAT#{chat_id}`, `sk=MSG#{ts_padded}#{msg_id_padded}`, with `user_name`, `text`, `ts`, and `expires_at`.
  - Settings: `pk=CHAT#{chat_id}`, `sk=SETTINGS`, with `style`, `filter_level`, `language`.
  - Query recent messages with descending sort, limit `N`, then reverse to chronological order.
  - Use TTL for message retention instead of disk-headroom eviction; default `MESSAGE_TTL_DAYS=365`.
- Keep current local/Fly polling path intact until AWS is verified.
  - Existing `main.py`, `storage.py`, `Dockerfile`, and `fly.toml` remain usable.
  - Shared `helpers.py` and `llm.py` stay reusable.
  - AWS code gets separate modules: `aws_webhook.py`, `aws_worker.py`, `dynamodb_storage.py`, and `telegram_api.py`.

## Interfaces And Deployment
- Add `template.yaml` for SAM resources:
  - HTTP API route `POST /telegram`
  - Webhook Lambda
  - Worker Lambda
  - SQS FIFO queue
  - DynamoDB table with TTL enabled
  - IAM permissions for SQS, DynamoDB, and logs
  - Stack outputs for webhook URL and table name
- Add `scripts/set_webhook.py`.
  - Calls Telegram `setWebhook` with deployed API URL.
  - Passes `secret_token=TELEGRAM_WEBHOOK_SECRET`.
- Required AWS Lambda environment:
  - `TELEGRAM_TOKEN`
  - `GEMINI_API_KEY`
  - `TELEGRAM_WEBHOOK_SECRET`
  - `DDB_TABLE_NAME`
  - `QUEUE_URL`
  - `MESSAGE_TTL_DAYS=365`
  - `LLM_BACKEND=gemini`

## Test Plan
- Keep existing tests passing.
- Add webhook tests:
  - Missing or invalid secret returns unauthorized.
  - Valid Telegram update enqueues to SQS and returns `200`.
  - Webhook Lambda does not call Gemini or Telegram directly.
- Add worker tests:
  - Non-command text logs to DynamoDB.
  - `/summarize` reads recent messages, calls injected LLM backend, escapes HTML, and sends reply.
  - Empty history sends the current "no logged messages" response.
  - Settings commands reject non-admin users and update settings for admins.
- Add DynamoDB adapter tests with mocked boto3 client/resource:
  - Message writes are scoped by chat.
  - Recent message reads preserve chronological output.
  - Settings defaults merge with stored overrides.
  - TTL is attached to message items.
- Add deployment validation:
  - `python -m pytest -q`
  - `sam validate --lint`
  - optional fixture-based local Lambda invocation for a sample Telegram update

## Assumptions And Notes
- Telegram webhook mode replaces long polling; do not run Fly polling and AWS webhook simultaneously after cutover.
- SQS makes replies asynchronous: users may see summaries a few seconds after issuing `/summarize`.
- No SQLite migration is included. Local historical data remains in `data/bot.db`.
- AWS costs should remain near zero for 15-30 summaries/month plus normal message logging.
- The current uncommitted repo changes should be preserved before implementation starts; do not overwrite the existing local fixes or the untracked `package-lock.json`.
