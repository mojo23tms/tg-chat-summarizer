import asyncio
import os

from . import config
from . import handlers
from . import storage


def _ensure_event_loop():
    """Ensure the main thread has a current event loop.

    python-telegram-bot 21.x's Application.run_polling() calls
    asyncio.get_event_loop(), relying on it to auto-create a loop in the main
    thread. Python 3.14 removed that behavior — get_event_loop() now raises
    RuntimeError when no loop is set — so run_polling() crashes at startup.
    Creating a loop here keeps startup working across Python 3.11–3.14; on
    versions where a loop already exists this returns it unchanged.
    """
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop


def main():
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN is required (set it as an environment variable).")
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is required (set it as an environment variable).")
    _ensure_event_loop()
    data_dir = os.path.dirname(config.DB_PATH) or "."
    os.makedirs(data_dir, exist_ok=True)
    conn = storage.connect(config.DB_PATH)
    app = handlers.build_application(conn, data_dir)
    app.run_polling()


if __name__ == "__main__":
    main()
