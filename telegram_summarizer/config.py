import json
import os


_SECRET_CACHE = None


def _load_app_secret(secret_id=None, secrets_client=None):
    secret_id = secret_id if secret_id is not None else os.environ.get("APP_SECRET_ID", "")
    if not secret_id:
        return {}
    if secrets_client is None:
        import boto3

        secrets_client = boto3.client("secretsmanager")
    response = secrets_client.get_secret_value(SecretId=secret_id)
    raw_secret = response.get("SecretString") or "{}"
    try:
        secret = json.loads(raw_secret)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Secret {secret_id!r} must be a JSON object") from exc
    if not isinstance(secret, dict):
        raise ValueError(f"Secret {secret_id!r} must be a JSON object")
    return secret


def _app_secret():
    global _SECRET_CACHE
    if _SECRET_CACHE is None:
        _SECRET_CACHE = _load_app_secret()
    return _SECRET_CACHE


def _secret_or_env(name, default=""):
    value = os.environ.get(name)
    if value not in (None, ""):
        return value
    secret = _app_secret()
    return str(secret.get(name, default) or default)


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
APP_SECRET_ID = os.environ.get("APP_SECRET_ID", "")
TELEGRAM_TOKEN = _secret_or_env("TELEGRAM_TOKEN")
LLM_BACKEND = os.environ.get("LLM_BACKEND", "gemini")
GEMINI_API_KEY = _secret_or_env("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
TELEGRAM_WEBHOOK_SECRET = _secret_or_env("TELEGRAM_WEBHOOK_SECRET")
DDB_TABLE_NAME = os.environ.get("DDB_TABLE_NAME", "")
QUEUE_URL = os.environ.get("QUEUE_URL", "")
MESSAGE_TTL_DAYS = _int_env("MESSAGE_TTL_DAYS", 365)
BOT_OWNER_IDS = _int_set_env("BOT_OWNER_IDS")
MAX_INPUT_TOKENS = _int_env("MAX_INPUT_TOKENS", 25000)
SUMMARY_OUTPUT_TOKENS = _int_env("SUMMARY_OUTPUT_TOKENS", 1500)
SUMMARY_MAX_MESSAGES = _int_env("SUMMARY_MAX_MESSAGES", 5000)

DEFAULT_COUNT = 30
MAX_COUNT = SUMMARY_MAX_MESSAGES
DISK_HEADROOM = 0.10  # keep at least 10% of the volume free

DEFAULTS = {
    "style": "concise, neutral bullet points",
    "filter_level": "clean",
    "language": "auto",
}
