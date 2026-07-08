import json

from telegram_summarizer import aws_webhook


class FakeSqs:
    def __init__(self):
        self.messages = []

    def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return {"MessageId": "1"}


def test_missing_or_invalid_webhook_secret_is_unauthorized(monkeypatch):
    monkeypatch.setattr(aws_webhook.config, "TELEGRAM_WEBHOOK_SECRET", "expected")

    missing = aws_webhook.lambda_handler({"headers": {}, "body": "{}"}, None)
    invalid = aws_webhook.lambda_handler(
        {
            "headers": {"X-Telegram-Bot-Api-Secret-Token": "wrong"},
            "body": "{}",
        },
        None,
    )

    assert missing["statusCode"] == 401
    assert invalid["statusCode"] == 401


def test_valid_update_enqueues_fifo_message_and_returns_ok(monkeypatch):
    monkeypatch.setattr(aws_webhook.config, "TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(aws_webhook.config, "QUEUE_URL", "queue-url")
    sqs = FakeSqs()
    update = {
        "update_id": 123,
        "message": {"chat": {"id": -100}, "text": "hello"},
    }

    response = aws_webhook.lambda_handler(
        {
            "headers": {"x-telegram-bot-api-secret-token": "secret"},
            "body": json.dumps(update),
        },
        None,
        sqs_client=sqs,
    )

    assert response["statusCode"] == 200
    assert sqs.messages == [
        {
            "QueueUrl": "queue-url",
            "MessageBody": json.dumps(update),
            "MessageGroupId": "-100",
            "MessageDeduplicationId": "123",
        }
    ]


def test_callback_query_update_groups_by_callback_message_chat(monkeypatch):
    monkeypatch.setattr(aws_webhook.config, "TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(aws_webhook.config, "QUEUE_URL", "queue-url")
    sqs = FakeSqs()
    update = {
        "update_id": 124,
        "callback_query": {
            "id": "cb-1",
            "message": {"chat": {"id": -200}},
            "data": "menu:home",
        },
    }

    response = aws_webhook.lambda_handler(
        {
            "headers": {"x-telegram-bot-api-secret-token": "secret"},
            "body": json.dumps(update),
        },
        None,
        sqs_client=sqs,
    )

    assert response["statusCode"] == 200
    assert sqs.messages[0]["MessageGroupId"] == "-200"


def test_valid_update_without_queue_url_returns_bad_request(monkeypatch):
    monkeypatch.setattr(aws_webhook.config, "TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(aws_webhook.config, "QUEUE_URL", "")
    monkeypatch.delenv("QUEUE_URL", raising=False)

    response = aws_webhook.lambda_handler(
        {
            "headers": {"x-telegram-bot-api-secret-token": "secret"},
            "body": json.dumps({"update_id": 123}),
        },
        None,
        sqs_client=FakeSqs(),
    )

    assert response["statusCode"] == 400


def test_webhook_does_not_call_telegram_or_gemini(monkeypatch):
    monkeypatch.setattr(aws_webhook.config, "TELEGRAM_WEBHOOK_SECRET", "secret")
    monkeypatch.setattr(aws_webhook.config, "QUEUE_URL", "queue-url")
    sqs = FakeSqs()

    response = aws_webhook.lambda_handler(
        {
            "headers": {"x-telegram-bot-api-secret-token": "secret"},
            "body": json.dumps({"update_id": 1}),
        },
        None,
        sqs_client=sqs,
    )

    assert response["statusCode"] == 200
    assert len(sqs.messages) == 1
