# Operations Runbook

This is the day-to-day guide for launching, deploying, debugging, maintaining,
and rolling back the AWS bot.

## Prerequisites

- Python 3.11 or newer
- AWS CLI authenticated to the target account
- AWS SAM CLI
- Telegram bot token from BotFather
- Gemini API key
- Region: `eu-central-1`

On this machine, Homebrew Python/SAM may need:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib
```

Use it on SAM/AWS commands if `pyexpat` or `libexpat` errors appear.

## Initial Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
.venv/bin/python -m pip install -r requirements.txt
```

Create secrets:

```bash
export TELEGRAM_TOKEN="..."
export GEMINI_API_KEY="..."
export TELEGRAM_WEBHOOK_SECRET="$(openssl rand -hex 32)"
```

Check AWS identity:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws sts get-caller-identity \
  --region eu-central-1
```

## Validate Before Deploy

```bash
.venv/bin/python -m pytest -q
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam validate --lint
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam build
```

## First Deploy

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam deploy \
  --stack-name telegram-summarizer-bot \
  --region eu-central-1 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    TelegramToken="$TELEGRAM_TOKEN" \
    GeminiApiKey="$GEMINI_API_KEY" \
    TelegramWebhookSecret="$TELEGRAM_WEBHOOK_SECRET" \
    MessageTtlDays=365 \
    BotOwnerIds="" \
    MaxInputTokens=25000 \
    SummaryOutputTokens=1500
```

If SAM rejects `GeminiApiKey=` or another `Name=`, that shell variable is empty.
Check with:

```bash
echo "TELEGRAM_TOKEN set? ${TELEGRAM_TOKEN:+yes}"
echo "GEMINI_API_KEY set? ${GEMINI_API_KEY:+yes}"
echo "TELEGRAM_WEBHOOK_SECRET set? ${TELEGRAM_WEBHOOK_SECRET:+yes}"
```

## Register Webhook

Read the stack output:

```bash
export WEBHOOK_URL="$(DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws cloudformation describe-stacks \
  --stack-name telegram-summarizer-bot \
  --region eu-central-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`WebhookUrl`].OutputValue' \
  --output text)"
```

Register Telegram:

```bash
.venv/bin/python scripts/set_webhook.py "$WEBHOOK_URL"
```

Check Telegram:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/getWebhookInfo"
```

## Configure Owner Controls

Send this to the bot:

```text
/whoami
```

Copy `user_id`, then redeploy:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam deploy \
  --stack-name telegram-summarizer-bot \
  --region eu-central-1 \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides \
    TelegramToken="$TELEGRAM_TOKEN" \
    GeminiApiKey="$GEMINI_API_KEY" \
    TelegramWebhookSecret="$TELEGRAM_WEBHOOK_SECRET" \
    MessageTtlDays=365 \
    BotOwnerIds="YOUR_USER_ID" \
    MaxInputTokens=25000 \
    SummaryOutputTokens=1500
```

Then in a DM with the bot:

```text
/chats
/usechat -1002200584149
/settings
/setfilter clean
/setstyle concise bullet points
/setlang auto
```

## Deploy Updates

```bash
.venv/bin/python -m pytest -q
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam validate --lint
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam build
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam deploy --region eu-central-1
```

After deploy, verify:

```text
/help
/summarize
/summarize auto
/usage
```

## Logs

Webhook Lambda:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam logs \
  --stack-name telegram-summarizer-bot \
  --name WebhookFunction \
  --region eu-central-1 \
  --tail
```

Worker Lambda:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib sam logs \
  --stack-name telegram-summarizer-bot \
  --name WorkerFunction \
  --region eu-central-1 \
  --tail
```

## Queue Health

Get queue URL from outputs:

```bash
export QUEUE_URL="$(DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws cloudformation describe-stacks \
  --stack-name telegram-summarizer-bot \
  --region eu-central-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`QueueUrl`].OutputValue' \
  --output text)"
```

Check backlog:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws sqs get-queue-attributes \
  --queue-url "$QUEUE_URL" \
  --attribute-names ApproximateNumberOfMessages ApproximateNumberOfMessagesNotVisible \
  --region eu-central-1
```

## DynamoDB Checks

Get table name:

```bash
export DDB_TABLE_NAME="$(DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws cloudformation describe-stacks \
  --stack-name telegram-summarizer-bot \
  --region eu-central-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`TableName`].OutputValue' \
  --output text)"
```

Count messages for a chat:

```bash
export CHAT_ID=-1002200584149
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws dynamodb query \
  --table-name "$DDB_TABLE_NAME" \
  --key-condition-expression 'pk = :pk AND begins_with(sk, :prefix)' \
  --expression-attribute-values "{\":pk\":{\"S\":\"CHAT#$CHAT_ID\"},\":prefix\":{\"S\":\"MSG#\"}}" \
  --select COUNT \
  --region eu-central-1
```

List known chat partitions:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws dynamodb scan \
  --table-name "$DDB_TABLE_NAME" \
  --projection-expression "pk" \
  --region eu-central-1
```

## Troubleshooting

### Bot Does Not Reply

1. Check Telegram webhook:

   ```bash
   curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/getWebhookInfo"
   ```

2. Check `WebhookFunction` logs.
3. Check SQS backlog.
4. Check `WorkerFunction` logs.

### Webhook Returns 401

`TELEGRAM_WEBHOOK_SECRET` in Lambda does not match the secret registered with
Telegram. Redeploy with the correct secret and rerun `scripts/set_webhook.py`.

### Webhook Returns 400

The webhook Lambda could not parse or enqueue the update. Check webhook logs and
SQS permissions.

### Worker Logs Telegram 404

Usually means the deployed `TELEGRAM_TOKEN` is wrong or malformed. Verify:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/getMe"
```

Then redeploy with the correct token.

### `/summarize` Says No Logged Messages

- Send normal text messages after the bot is deployed.
- In groups, disable BotFather privacy mode or make the bot an admin.
- Confirm the imported history used the same `chat_id`.
- Confirm webhook mode and long polling are not both active.

### `NoRegionError`

Pass `--region eu-central-1` or set:

```bash
export AWS_REGION=eu-central-1
```

### `NoCredentialsError`

The AWS CLI may be authenticated while boto3 is not. The import script defaults
to `--writer aws-cli` for this reason. For SAM/AWS commands, verify:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib aws sts get-caller-identity \
  --region eu-central-1
```

### Homebrew `pyexpat` Error

Use:

```bash
DYLD_LIBRARY_PATH=/usr/local/opt/expat/lib <command>
```

For a longer-term fix, reinstall Homebrew Python, expat, AWS CLI, and SAM CLI.

## Rollback

Disable webhook delivery:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_TOKEN/deleteWebhook"
```

Run local polling:

```bash
export TELEGRAM_TOKEN="..."
export GEMINI_API_KEY="..."
export DB_PATH=data/bot.db
.venv/bin/python -m telegram_summarizer.main
```

For Fly.io rollback:

```bash
fly deploy
fly logs
```

Do not keep webhook and polling active for the same bot token.

## Maintenance Checklist

- Run tests before deploy.
- Validate SAM template before deploy.
- Keep secrets out of git.
- Rotate `TELEGRAM_WEBHOOK_SECRET` by redeploying and re-registering the webhook.
- Review DynamoDB item count and TTL settings periodically.
- Watch `/usage month` for token volume.
- Keep Telegram Desktop exports private; they contain chat history.
