import asyncio
from types import SimpleNamespace

from telegram_summarizer import main


def test_ensure_event_loop_recovers_when_no_loop_set():
    # Simulate the state python-telegram-bot's run_polling() hits on Python 3.14,
    # where the main thread has no current event loop and get_event_loop() raises.
    asyncio.set_event_loop(None)
    loop = main._ensure_event_loop()
    try:
        assert isinstance(loop, asyncio.AbstractEventLoop)
        # After ensuring, get_event_loop() must succeed and return the same loop.
        assert asyncio.get_event_loop() is loop
    finally:
        loop.close()
        # Restore a fresh loop so we don't leave the thread without one for other tests.
        asyncio.set_event_loop(asyncio.new_event_loop())


def test_main_accepts_groq_key_without_gemini_key(monkeypatch, tmp_path):
    calls = {}

    monkeypatch.setattr(main.config, "TELEGRAM_TOKEN", "token")
    monkeypatch.setattr(main.config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(main.config, "GROQ_API_KEY", "groq-key")
    monkeypatch.setattr(main.config, "DB_PATH", str(tmp_path / "bot.db"))
    monkeypatch.setattr(main, "_ensure_event_loop", lambda: None)
    monkeypatch.setattr(main.storage, "connect", lambda path: "conn")

    def build_application(conn, data_dir):
        calls["conn"] = conn
        calls["data_dir"] = data_dir
        return SimpleNamespace(run_polling=lambda: calls.setdefault("run", True))

    monkeypatch.setattr(main.handlers, "build_application", build_application)

    main.main()

    assert calls["conn"] == "conn"
    assert calls["run"] is True
