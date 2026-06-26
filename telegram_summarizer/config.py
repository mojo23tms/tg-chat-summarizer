import os


def _int_env(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc


def _int_set_env(name):
    values = os.environ.get(name, "").replace(" ", "").split(",")
    try:
        return {int(value) for value in values if value}
    except ValueError as exc:
        raise ValueError(f"{name} must be a comma-separated list of integers") from exc


DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TELEGRAM_WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
DDB_TABLE_NAME = os.environ.get("DDB_TABLE_NAME", "")
QUEUE_URL = os.environ.get("QUEUE_URL", "")
MESSAGE_TTL_DAYS = _int_env("MESSAGE_TTL_DAYS", 365)
BOT_OWNER_IDS = _int_set_env("BOT_OWNER_IDS")
MAX_INPUT_TOKENS = _int_env("MAX_INPUT_TOKENS", 25000)
SUMMARY_OUTPUT_TOKENS = _int_env("SUMMARY_OUTPUT_TOKENS", 1500)

DEFAULT_COUNT = 30
MAX_COUNT = 200
DISK_HEADROOM = 0.10  # keep at least 10% of the volume free

DEFAULTS = {
    "style": "concise, neutral bullet points",
    "filter_level": "clean",
    "language": "auto",
}
