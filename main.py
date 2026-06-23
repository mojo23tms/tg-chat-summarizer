import os

import config
import handlers
import storage


def main():
    if not config.TELEGRAM_TOKEN:
        raise SystemExit("TELEGRAM_TOKEN is required (set it as an environment variable).")
    if not config.GEMINI_API_KEY:
        raise SystemExit("GEMINI_API_KEY is required (set it as an environment variable).")
    data_dir = os.path.dirname(config.DB_PATH) or "."
    os.makedirs(data_dir, exist_ok=True)
    conn = storage.connect(config.DB_PATH)
    app = handlers.build_application(conn, data_dir)
    app.run_polling()


if __name__ == "__main__":
    main()
