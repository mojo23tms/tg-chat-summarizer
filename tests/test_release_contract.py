import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

DOCUMENTED_COMMANDS = {
    "ask",
    "bestof",
    "chat",
    "chats",
    "help",
    "insidejoke",
    "lore",
    "menu",
    "models",
    "quotes",
    "recap",
    "remember",
    "setfilter",
    "setlang",
    "setmodel",
    "setprovider",
    "setstyle",
    "settings",
    "start",
    "summarize",
    "usage",
    "usechat",
    "whoami",
}

SAM_RUNTIME_SETTINGS = {
    "APP_SECRET_ID",
    "DDB_TABLE_NAME",
    "QUEUE_URL",
    "MESSAGE_TTL_DAYS",
    "BOT_OWNER_IDS",
    "MAX_INPUT_TOKENS",
    "SUMMARY_OUTPUT_TOKENS",
    "ASK_OUTPUT_TOKENS",
    "MEMORY_OUTPUT_TOKENS",
    "MEMORY_MAX_MESSAGES",
    "SUMMARY_MAX_MESSAGES",
    "LLM_REQUEST_TIMEOUT_SECONDS",
    "GEMINI_DAILY_TOKEN_QUOTA",
    "GROQ_DAILY_TOKEN_QUOTA",
    "QUOTA_WARNING_REMAINING_PERCENT",
    "LLM_BACKEND",
}


def _imports(path):
    tree = ast.parse(path.read_text())
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_public_commands_are_documented_in_readme_and_command_spec():
    readme = (ROOT / "README.md").read_text()
    command_spec = (ROOT / "specs/commands.md").read_text()

    for command in DOCUMENTED_COMMANDS:
        assert f"/{command}" in readme
        assert f"/{command}" in command_spec


def test_sam_template_exposes_every_runtime_budget_and_quota_setting():
    template = (ROOT / "template.yaml").read_text()

    for setting in SAM_RUNTIME_SETTINGS:
        assert f"{setting}:" in template


def test_example_environment_contains_no_secret_values():
    values = {}
    for line in (ROOT / ".env.example").read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value

    for secret_name in (
        "TELEGRAM_TOKEN",
        "GEMINI_API_KEY",
        "GROQ_API_KEY",
        "TELEGRAM_WEBHOOK_SECRET",
    ):
        assert values[secret_name] == ""


def test_live_lambda_modules_do_not_import_archive_or_cloud_clients():
    live_imports = set()
    for module in ("aws_webhook.py", "aws_worker.py"):
        live_imports.update(_imports(ROOT / "telegram_summarizer" / module))

    assert not any("archive_export" in module for module in live_imports)
    assert not any("googleapiclient" in module for module in live_imports)
    template = (ROOT / "template.yaml").read_text()
    assert "S3ReadPolicy" not in template
    assert "S3CrudPolicy" not in template
