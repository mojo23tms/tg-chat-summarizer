import asyncio

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
