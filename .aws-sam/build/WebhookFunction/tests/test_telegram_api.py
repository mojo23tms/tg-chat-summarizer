import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from telegram_summarizer.telegram_api import TelegramApi, TelegramApiError, set_webhook


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class FakeOpener:
    def __init__(self, payload):
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append({"request": request, "timeout": timeout})
        return FakeResponse(self.payload)


class FailingOpener:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self.payload = payload

    def __call__(self, request, timeout):
        body = json.dumps(self.payload).encode("utf-8")
        raise HTTPError(
            request.full_url,
            self.status_code,
            "Bad Request",
            hdrs={},
            fp=BytesIO(body),
        )


def test_send_message_uses_injected_opener_without_network():
    opener = FakeOpener({"ok": True, "result": {"message_id": 1}})
    api = TelegramApi(token="token", opener=opener)

    result = api.send_message(123, "hello", parse_mode="HTML")

    assert result == {"message_id": 1}
    request = opener.requests[0]["request"]
    assert request.full_url == "https://api.telegram.org/bottoken/sendMessage"
    assert json.loads(request.data.decode("utf-8")) == {
        "chat_id": 123,
        "text": "hello",
        "parse_mode": "HTML",
    }


def test_telegram_api_raises_on_api_error_without_retrying_network():
    opener = FakeOpener({"ok": False, "description": "bad token"})
    api = TelegramApi(token="token", opener=opener)

    with pytest.raises(TelegramApiError):
        api.get_chat_member(123, 456)

    assert len(opener.requests) == 1


def test_telegram_api_includes_http_error_body():
    opener = FailingOpener(
        400,
        {
            "ok": False,
            "error_code": 400,
            "description": "Bad Request: chat not found",
        },
    )
    api = TelegramApi(token="token", opener=opener)

    with pytest.raises(TelegramApiError) as exc_info:
        api.send_message(123, "hello")

    assert exc_info.value.status_code == 400
    assert exc_info.value.payload["description"] == "Bad Request: chat not found"
    assert "Telegram sendMessage failed with HTTP 400" in str(exc_info.value)


def test_set_webhook_uses_injected_opener_without_network():
    opener = FakeOpener({"ok": True, "result": True})

    result = set_webhook("token", "https://example.test/telegram", "secret", opener)

    assert result == {"ok": True, "result": True}
    request = opener.requests[0]["request"]
    assert request.full_url == "https://api.telegram.org/bottoken/setWebhook"
    body = request.data.decode("utf-8")
    assert "url=https%3A%2F%2Fexample.test%2Ftelegram" in body
    assert "secret_token=secret" in body
