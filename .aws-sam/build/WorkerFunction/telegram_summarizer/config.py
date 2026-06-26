import os

DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
DDB_TABLE_NAME = os.environ.get("DDB_TABLE_NAME", "")
QUEUE_URL = os.environ.get("QUEUE_URL", "")
MESSAGE_TTL_DAYS = int(os.environ.get("MESSAGE_TTL_DAYS", "365"))
BOT_OWNER_IDS = {
    int(value)
    for value in os.environ.get("BOT_OWNER_IDS", "").replace(" ", "").split(",")
    if value
}
MAX_INPUT_TOKENS = int(os.environ.get("MAX_INPUT_TOKENS", "25000"))
SUMMARY_OUTPUT_TOKENS = int(os.environ.get("SUMMARY_OUTPUT_TOKENS", "1500"))

DEFAULT_COUNT = 30
MAX_COUNT = 200
DISK_HEADROOM = 0.10  # keep at least 10% of the volume free

DEFAULTS = {
    "style": "concise, neutral bullet points",
    "filter_level": "clean",
    "language": "auto",
}
