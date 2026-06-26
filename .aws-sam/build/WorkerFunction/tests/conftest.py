import socket
import urllib.request

import pytest


@pytest.fixture(autouse=True)
def no_external_network(monkeypatch):
    """Keep tests offline so they cannot spend Telegram, Gemini, or AWS quota."""

    def blocked(*args, **kwargs):
        raise AssertionError(
            "External network calls are disabled in tests. Use a fake client, "
            "fake opener, or injected backend instead."
        )

    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)


@pytest.fixture(autouse=True)
def fake_service_secrets(monkeypatch):
    """Use harmless defaults if code reads config during tests."""
    monkeypatch.setenv("TELEGRAM_TOKEN", "test-telegram-token")
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", "test-webhook-secret")
