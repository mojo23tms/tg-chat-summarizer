import json
import urllib.parse
import urllib.request
from urllib.error import HTTPError

from . import config


class TelegramApiError(RuntimeError):
    def __init__(self, message, status_code=None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


class TelegramApi:
    def __init__(self, token=None, opener=None):
        self.token = token or config.TELEGRAM_TOKEN
        self.opener = opener or urllib.request.urlopen
        self.base_url = f"https://api.telegram.org/bot{self.token}"

    def _post(self, method, payload):
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=10) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            payload = _parse_json_body(body)
            raise TelegramApiError(
                f"Telegram {method} failed with HTTP {exc.code}: {payload or body}",
                status_code=exc.code,
                payload=payload,
            ) from exc
        parsed = json.loads(body)
        if not parsed.get("ok"):
            raise TelegramApiError(
                f"Telegram {method} failed: {parsed}",
                payload=parsed,
            )
        return parsed["result"]

    def send_message(self, chat_id, text, parse_mode=None):
        payload = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        return self._post("sendMessage", payload)

    def get_chat_member(self, chat_id, user_id):
        return self._post("getChatMember", {"chat_id": chat_id, "user_id": user_id})


def set_webhook(token, webhook_url, secret_token, opener=None):
    opener = opener or urllib.request.urlopen
    api_url = f"https://api.telegram.org/bot{token}/setWebhook"
    payload = urllib.parse.urlencode(
        {"url": webhook_url, "secret_token": secret_token}
    ).encode("utf-8")
    request = urllib.request.Request(api_url, data=payload, method="POST")
    with opener(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _parse_json_body(body):
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None
