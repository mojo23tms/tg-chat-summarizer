import logging
import time

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from . import config
from . import helpers
from . import llm
from . import storage

logger = logging.getLogger(__name__)

PROFANITY_WORDLIST = {"fuck", "shit", "bitch", "asshole"}  # safety-net only

ADMIN_STATUSES = {"administrator", "creator"}
VALID_FILTERS = {"off", "clean", "strict"}


def is_setting_change_allowed(member_status):
    return member_status in ADMIN_STATUSES


async def _is_admin(update, context):
    member = await context.bot.get_chat_member(
        update.effective_chat.id, update.effective_user.id
    )
    return is_setting_change_allowed(member.status)


async def log_handler(update, context):
    msg = update.effective_message
    if not msg or not msg.text:
        return
    user = update.effective_user
    storage.log_message(
        context.bot_data["conn"], update.effective_chat.id, msg.message_id,
        user.id, user.full_name or user.username or str(user.id),
        msg.text, int(time.time()),
    )
    storage.enforce_disk_headroom(
        context.bot_data["conn"],
        lambda: storage.disk_free_ratio(context.bot_data["data_dir"]),
        config.DISK_HEADROOM,
    )


async def summarize_handler(update, context):
    conn = context.bot_data["conn"]
    chat_id = update.effective_chat.id
    n = helpers.parse_count(context.args[0] if context.args else None)
    msgs = storage.recent_messages(conn, chat_id, n)
    if not msgs:
        await update.effective_message.reply_text(
            "I have no logged messages yet — I can only summarize messages "
            "sent after I joined this chat."
        )
        return
    settings = storage.get_settings(conn, chat_id)
    try:
        summary = llm.summarize(msgs, settings)
    except Exception:
        logger.exception("summarize failed")
        await update.effective_message.reply_text(
            "Sorry, the summarizer is unavailable right now. Please try again."
        )
        return
    summary = helpers.scrub(summary, settings["filter_level"], PROFANITY_WORDLIST)
    summary = helpers.render_summary_html(summary)
    user = update.effective_user
    mention = helpers.format_mention(user.id, user.full_name or "you")
    await update.effective_message.reply_text(
        f"{mention}, here is your summary of the last {len(msgs)} messages:\n\n{summary}",
        parse_mode=ParseMode.HTML,
    )


async def _change_setting(update, context, key, value):
    if not await _is_admin(update, context):
        await update.effective_message.reply_text("Only admins can change settings.")
        return False
    storage.set_setting(context.bot_data["conn"], update.effective_chat.id, key, value)
    await update.effective_message.reply_text(f"Updated {key} to: {value}")
    return True


async def setstyle_handler(update, context):
    value = " ".join(context.args).strip()
    if not value:
        await update.effective_message.reply_text("Usage: /setstyle <description>")
        return
    await _change_setting(update, context, "style", value)


async def setfilter_handler(update, context):
    value = (context.args[0] if context.args else "").lower()
    if value not in VALID_FILTERS:
        await update.effective_message.reply_text("Usage: /setfilter off|clean|strict")
        return
    await _change_setting(update, context, "filter_level", value)


async def setlang_handler(update, context):
    value = (context.args[0] if context.args else "").strip()
    if not value:
        await update.effective_message.reply_text("Usage: /setlang <code|auto>")
        return
    await _change_setting(update, context, "language", value)


async def settings_handler(update, context):
    s = storage.get_settings(context.bot_data["conn"], update.effective_chat.id)
    await update.effective_message.reply_text(
        f"style: {s['style']}\nfilter: {s['filter_level']}\nlanguage: {s['language']}"
    )


async def help_handler(update, context):
    await update.effective_message.reply_text(
        "/summarize [N] — summarize the last N messages (default "
        f"{config.DEFAULT_COUNT}, max {config.MAX_COUNT}).\n"
        "/setstyle <text>, /setfilter off|clean|strict, /setlang <code|auto> — "
        "admins only.\n/settings — show current settings."
    )


def build_application(conn, data_dir):
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.bot_data["conn"] = conn
    app.bot_data["data_dir"] = data_dir
    app.add_handler(CommandHandler("summarize", summarize_handler))
    app.add_handler(CommandHandler("setstyle", setstyle_handler))
    app.add_handler(CommandHandler("setfilter", setfilter_handler))
    app.add_handler(CommandHandler("setlang", setlang_handler))
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CommandHandler(["help", "start"], help_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_handler))
    return app
