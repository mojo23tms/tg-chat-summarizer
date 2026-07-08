import json
import logging
import os

from . import config

logger = logging.getLogger(__name__)


def _headers(event):
    return {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}


def _response(status_code, body):
    return {"statusCode": status_code, "body": json.dumps(body)}


def _chat_id(update):
    for key in ("message", "edited_message", "channel_post", "edited_channel_post"):
        chat = (update.get(key) or {}).get("chat") or {}
        if "id" in chat:
            return chat["id"]
    callback_message = ((update.get("callback_query") or {}).get("message") or {})
    chat = callback_message.get("chat") or {}
    if "id" in chat:
        return chat["id"]
    return "global"


def enqueue_update(update, queue_url, sqs_client):
    update_id = update.get("update_id")
    if update_id is None:
        raise ValueError("Telegram update is missing update_id")
    chat_id = _chat_id(update)
    sqs_client.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps(update),
        MessageGroupId=str(chat_id),
        MessageDeduplicationId=str(update_id),
    )


def lambda_handler(event, context, sqs_client=None):
    expected_secret = config.TELEGRAM_WEBHOOK_SECRET
    actual_secret = _headers(event).get("x-telegram-bot-api-secret-token")
    if not expected_secret or actual_secret != expected_secret:
        logger.warning("telegram webhook rejected: invalid secret")
        return _response(401, {"ok": False})

    try:
        update = json.loads(event.get("body") or "{}")
        queue_url = os.environ.get("QUEUE_URL") or config.QUEUE_URL
        if not queue_url:
            raise ValueError("QUEUE_URL is required")
        if sqs_client is None:
            import boto3

            sqs_client = boto3.client("sqs")
        enqueue_update(update, queue_url, sqs_client)
    except Exception:
        logger.exception("telegram webhook failed")
        return _response(400, {"ok": False})
    return _response(200, {"ok": True})
