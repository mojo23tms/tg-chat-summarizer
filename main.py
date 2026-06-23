import os

import config
import handlers
import storage


def main():
    data_dir = os.path.dirname(config.DB_PATH) or "."
    os.makedirs(data_dir, exist_ok=True)
    conn = storage.connect(config.DB_PATH)
    app = handlers.build_application(conn, data_dir)
    app.run_polling()


if __name__ == "__main__":
    main()
