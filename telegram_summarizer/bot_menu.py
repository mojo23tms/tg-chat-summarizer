import html

from . import config
from . import llm


BUTTON_COMMANDS = {
    "📝 Summarize": "summarize",
    "🧠 Ask history": "ask",
    "💬 Chat": "chat",
    "📚 Lore": "lore",
    "😂 Inside joke": "insidejoke",
    "🏆 Best of": "bestof",
    "💬 Quotes": "quotes",
    "🗓 Recap": "recap",
    "🧠 Remember": "remember",
    "⚙️ Settings": "settings",
    "📊 Usage": "usage",
    "🤖 Models": "models",
    "❓ Help": "help",
    "🆔 Who am I": "whoami",
    "💬 Chats": "chats",
}

MENU_ROWS = [
    ["📝 Summarize", "🧠 Ask history"],
    ["💬 Chat", "📚 Lore"],
    ["😂 Inside joke", "🏆 Best of"],
    ["💬 Quotes", "🗓 Recap"],
    ["🧠 Remember", "⚙️ Settings"],
    ["📊 Usage", "🤖 Models"],
    ["❓ Help", "🆔 Who am I"],
]


def rows(is_owner_dm=False):
    result = [list(row) for row in MENU_ROWS]
    if is_owner_dm:
        result.append(["💬 Chats"])
    return result


def reply_markup(is_owner_dm=False):
    return {
        "keyboard": [[{"text": label} for label in row] for row in rows(is_owner_dm)],
        "resize_keyboard": True,
        "is_persistent": True,
        "input_field_placeholder": "Choose what the bot should do",
    }


def manual(settings, *, active_chat_id=None):
    provider, model = llm.resolve_provider_model(settings)
    active = f"Active chat: {active_chat_id}\n" if active_chat_id is not None else ""
    return (
        "<b>Bot manual</b>\n"
        f"{active}Use the persistent buttons below the text field, or the matching "
        "slash commands.\n\n"
        "<b>Navigation</b>\n"
        "• <code>/menu</code> — show or restore the persistent button menu.\n"
        "• <code>/help</code> — open this manual.\n\n"
        "<b>Conversation</b>\n"
        "• <code>/chat &lt;question&gt;</code> — general assistant; never searches history.\n"
        "• <code>/ask &lt;question&gt;</code> — answer from bounded raw history and memories.\n\n"
        "<b>History and lore</b>\n"
        f"• <code>/summarize [N|auto]</code> — recent summary, max {config.SUMMARY_MAX_MESSAGES}.\n"
        "• <code>/lore</code> — established jokes, nicknames, incidents, and canon.\n"
        "• <code>/insidejoke &lt;term&gt;</code> — explain a recurring reference.\n"
        "• <code>/bestof [today|week|month|year|all]</code> — memorable moments.\n"
        "• <code>/quotes [name]</code> — evidence-backed group or person quotes.\n"
        "• <code>/recap [today|week|month|year|all]</code> — period recap.\n"
        f"• <code>/remember [N|auto]</code> — admin-only memory snapshot, max {config.MEMORY_MAX_MESSAGES}.\n\n"
        "<b>Settings and diagnostics</b>\n"
        "• <code>/settings</code>, <code>/models</code>, <code>/usage [today|month]</code>.\n"
        "• Admin-only: <code>/setprovider gemini|groq</code>, "
        "<code>/setmodel &lt;model|provider:model&gt;</code>, "
        "<code>/setstyle &lt;text&gt;</code>, <code>/setfilter off|clean|strict</code>, "
        "and <code>/setlang &lt;code|auto&gt;</code>.\n"
        "• <code>/whoami</code> shows IDs. Bot owners can use <code>/chats</code> "
        "and <code>/usechat</code> in DM.\n\n"
        "<b>How it behaves</b>\n"
        "History and memory reads stay inside the current chat and are bounded; "
        "the bot never sends the entire archive blindly. Memory generation and AI "
        "answers consume provider quota. Telegram history is treated as untrusted "
        "data, outputs are sanitized, and S3/personal cloud storage is never read "
        "during a live command. Weak evidence is reported instead of invented.\n\n"
        f"Current LLM: <code>{html.escape(provider)}:{html.escape(model)}</code>"
    )
