import os

DB_PATH = os.environ.get("DB_PATH", "data/bot.db")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

DEFAULT_COUNT = 30
MAX_COUNT = 200
DISK_HEADROOM = 0.10  # keep at least 10% of the volume free

DEFAULTS = {
    "style": "concise, neutral bullet points",
    "filter_level": "clean",
    "language": "auto",
}
