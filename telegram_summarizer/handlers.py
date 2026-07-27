import logging
import time

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from . import bot_menu
from . import config
from . import helpers
from . import history_qa
from . import llm
from . import lore
from . import memory
from . import storage

logger = logging.getLogger(__name__)

PROFANITY_WORDLIST = {"fuck", "shit", "bitch", "asshole"}  # safety-net only

ADMIN_STATUSES = {"administrator", "creator"}
VALID_FILTERS = {"off", "clean", "strict"}


def _menu_markup():
    return ReplyKeyboardMarkup(
        bot_menu.rows(),
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Choose what the bot should do",
    )


def _inline_menu_markup(menu="home"):
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(**button) for button in row]
            for row in bot_menu.inline_rows(menu)
        ]
    )


def _pending_key(update):
    user = getattr(update, "effective_user", None)
    return (update.effective_chat.id, getattr(user, "id", 0))


async def _request_next_message(update, context, action, prompt):
    context.bot_data.setdefault("pending_commands", {})[_pending_key(update)] = action
    await update.effective_message.reply_text(prompt)


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
    settings = storage.get_settings(conn, chat_id)
    if context.args and context.args[0].lower() == "auto":
        candidate_messages = storage.recent_messages(
            conn, chat_id, config.SUMMARY_MAX_MESSAGES
        )
        msgs = llm.select_messages_for_token_budget(candidate_messages, settings)
    else:
        n = helpers.parse_count(context.args[0] if context.args else None)
        msgs = storage.recent_messages(conn, chat_id, n)
    if not msgs:
        await update.effective_message.reply_text(
            "I have no logged messages yet — I can only summarize messages "
            "sent after I joined this chat."
        )
        return
    try:
        summary = llm.summarize(msgs, settings)
    except Exception:
        logger.exception("summarize failed")
        await update.effective_message.reply_text(
            "Sorry, the summarizer is unavailable right now. Please try again."
        )
        return
    summary = helpers.scrub(summary, settings["filter_level"], PROFANITY_WORDLIST)
    summary = helpers.render_telegram_html(summary)
    user = update.effective_user
    mention = helpers.format_mention(user.id, user.full_name or "you")
    text = f"{mention}, here is your summary of the last {len(msgs)} messages:\n\n{summary}"
    for chunk in helpers.split_telegram_html(text):
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def chat_handler(update, context):
    question = " ".join(context.args).strip()
    if not question:
        await _request_next_message(
            update, context, "chat", "Send your general question as your next message."
        )
        return
    conn = context.bot_data["conn"]
    chat_id = update.effective_chat.id
    settings = storage.get_settings(conn, chat_id)
    try:
        result = llm.chat_with_usage(question, settings)
    except Exception:
        logger.exception("chat failed")
        await update.effective_message.reply_text(
            "Sorry, the chat assistant is unavailable right now. Please try again."
        )
        return
    storage.log_usage(conn, chat_id, result.get("usage"), 0, int(time.time()))
    text = helpers.render_telegram_html(result["text"])
    for chunk in helpers.split_telegram_html(text):
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def ask_handler(update, context):
    question = " ".join(context.args).strip()
    if not question:
        await _request_next_message(
            update,
            context,
            "ask",
            "Send your chat-history question as your next message.",
        )
        return

    await update.effective_message.reply_text("Searching chat history…")
    conn = context.bot_data["conn"]
    chat_id = update.effective_chat.id
    settings = storage.get_settings(conn, chat_id)
    try:
        result = history_qa.ask_history(
            chat_id,
            question,
            storage.SQLiteMessagePageStorage(conn),
            settings,
        )
    except llm.LLMBlockedError:
        logger.warning("ask prompt blocked")
        await update.effective_message.reply_text(
            "The selected model blocked this history question. Try rephrasing it."
        )
        return
    except Exception:
        logger.exception("ask failed")
        await update.effective_message.reply_text(
            "Sorry, history search is unavailable right now. Please try again."
        )
        return

    evidence_count = int(result.get("evidence_count", 0))
    storage.log_usage(
        conn,
        chat_id,
        result.get("usage"),
        evidence_count,
        int(time.time()),
    )
    text = helpers.scrub(
        result["text"], settings["filter_level"], PROFANITY_WORDLIST
    )
    text = helpers.render_telegram_html(text)
    for chunk in helpers.split_telegram_html(text):
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def _lore_handler(update, context, command):
    argument = " ".join(context.args).strip()
    if not argument and command == "insidejoke":
        await _request_next_message(
            update,
            context,
            command,
            "Send the inside joke or recurring reference to search for as your next message.",
        )
        return

    await update.effective_message.reply_text("Searching chat lore…")
    conn = context.bot_data["conn"]
    chat_id = update.effective_chat.id
    settings = storage.get_settings(conn, chat_id)
    try:
        result = lore.answer_lore(
            command,
            argument,
            chat_id,
            storage.SQLiteMessagePageStorage(conn),
            settings,
        )
    except ValueError:
        suffix = (
            "<term>"
            if command == "insidejoke"
            else "<name>"
            if command == "quotes"
            else "[today|week|month|year|all]"
        )
        await update.effective_message.reply_text(f"Usage: /{command} {suffix}")
        return
    except llm.LLMBlockedError:
        logger.warning("lore prompt blocked")
        await update.effective_message.reply_text(
            "The selected model blocked this lore request. Try rephrasing it."
        )
        return
    except Exception:
        logger.exception("lore search failed")
        await update.effective_message.reply_text(
            "Sorry, lore search is unavailable right now. Please try again."
        )
        return

    evidence_count = int(result.get("evidence_count", 0))
    storage.log_usage(
        conn, chat_id, result.get("usage"), evidence_count, int(time.time())
    )
    text = helpers.scrub(result["text"], settings["filter_level"], PROFANITY_WORDLIST)
    text = helpers.render_telegram_html(text)
    for chunk in helpers.split_telegram_html(text):
        await update.effective_message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def lore_handler(update, context):
    await _lore_handler(update, context, "lore")


async def insidejoke_handler(update, context):
    await _lore_handler(update, context, "insidejoke")


async def bestof_handler(update, context):
    await _lore_handler(update, context, "bestof")


async def quotes_handler(update, context):
    await _lore_handler(update, context, "quotes")


async def recap_handler(update, context):
    await _lore_handler(update, context, "recap")


async def remember_handler(update, context):
    if not await _is_admin(update, context):
        await update.effective_message.reply_text(
            "Only admins can build memory snapshots."
        )
        return
    value = context.args[0].lower() if context.args else "auto"
    if value == "auto":
        message_limit = config.MEMORY_MAX_MESSAGES
    else:
        try:
            message_limit = int(value)
        except ValueError:
            await update.effective_message.reply_text("Usage: /remember [N|auto]")
            return
        message_limit = max(1, min(message_limit, config.MEMORY_MAX_MESSAGES))

    await update.effective_message.reply_text("Building a memory snapshot…")
    conn = context.bot_data["conn"]
    chat_id = update.effective_chat.id
    settings = storage.get_settings(conn, chat_id)
    adapter = storage.SQLiteMessagePageStorage(conn)
    try:
        result = memory.generate_snapshot(
            chat_id,
            adapter,
            settings,
            message_limit=message_limit,
        )
    except llm.LLMBlockedError:
        logger.warning("memory prompt blocked")
        await update.effective_message.reply_text(
            "The selected model blocked this memory snapshot. Try a smaller range."
        )
        return
    except (ValueError, TypeError):
        logger.exception("memory response invalid")
        await update.effective_message.reply_text(
            "The model returned an invalid memory snapshot. Please try again."
        )
        return
    except Exception:
        logger.exception("memory generation failed")
        await update.effective_message.reply_text(
            "Sorry, memory generation is unavailable right now. Please try again."
        )
        return

    source_count = int(result.get("source_message_count", 0))
    storage.log_usage(
        conn,
        chat_id,
        result.get("usage"),
        source_count,
        int(time.time()),
    )
    if result.get("invalid_memory"):
        await update.effective_message.reply_text(
            "The model returned an invalid memory snapshot. Please try again."
        )
        return
    snapshot = result.get("snapshot")
    if snapshot is None:
        text = (
            "No durable chat lore was found in that range."
            if source_count
            else "I have no logged messages yet — I can only remember messages sent "
            "after I joined this chat."
        )
    else:
        text = (
            f"Saved a memory snapshot from {snapshot['message_count']} messages "
            f"with {len(snapshot['items'])} lore items."
        )
    await update.effective_message.reply_text(text)


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


async def models_handler(update, context):
    settings = storage.get_settings(context.bot_data["conn"], update.effective_chat.id)
    await update.effective_message.reply_text(llm.models_text(settings))


async def setprovider_handler(update, context):
    try:
        provider = llm.normalize_provider(context.args[0] if context.args else "")
    except ValueError:
        await update.effective_message.reply_text("Usage: /setprovider gemini|groq")
        return
    if not await _is_admin(update, context):
        await update.effective_message.reply_text("Only admins can change settings.")
        return
    conn = context.bot_data["conn"]
    storage.set_setting(conn, update.effective_chat.id, "provider", provider)
    storage.set_setting(conn, update.effective_chat.id, "model", "")
    await update.effective_message.reply_text(
        f"Updated provider to: {provider}\nUsing default model: {llm.DEFAULT_MODELS[provider]}"
    )


async def setmodel_handler(update, context):
    value = " ".join(context.args).strip()
    settings = storage.get_settings(context.bot_data["conn"], update.effective_chat.id)
    try:
        provider, model = llm.parse_model_selection(
            value, settings.get("provider", config.DEFAULT_LLM_PROVIDER)
        )
    except ValueError:
        await update.effective_message.reply_text("Usage: /setmodel <model|provider:model>")
        return
    if not await _is_admin(update, context):
        await update.effective_message.reply_text("Only admins can change settings.")
        return
    conn = context.bot_data["conn"]
    storage.set_setting(conn, update.effective_chat.id, "provider", provider)
    storage.set_setting(conn, update.effective_chat.id, "model", model)
    await update.effective_message.reply_text(f"Updated model to: {provider}:{model}")


async def settings_handler(update, context):
    s = storage.get_settings(context.bot_data["conn"], update.effective_chat.id)
    provider, model = llm.resolve_provider_model(s)
    await update.effective_message.reply_text(
        f"style: {s['style']}\n"
        f"filter: {s['filter_level']}\n"
        f"language: {s['language']}\n"
        f"provider: {provider}\n"
        f"model: {model}"
    )


async def usage_handler(update, context):
    period = (context.args[0] if context.args else "all").lower()
    if period not in {"today", "month", "all"}:
        await update.effective_message.reply_text("Usage: /usage [today|month]")
        return
    since_ts = None
    if period == "today":
        since_ts = int(time.time()) - 86400
    elif period == "month":
        since_ts = int(time.time()) - 30 * 86400
    totals = storage.usage_totals(
        context.bot_data["conn"], update.effective_chat.id, since_ts=since_ts
    )
    await update.effective_message.reply_text(
        f"period: {period}\n"
        f"requests: {totals['requests']}\n"
        f"source messages processed: {totals['messages_count']}\n"
        f"input tokens: {totals['input_tokens']}\n"
        f"output tokens: {totals['output_tokens']}\n"
        f"total tokens: {totals['total_tokens']}\n"
        f"estimated records: {totals['estimated_records']}"
    )


async def whoami_handler(update, context):
    await update.effective_message.reply_text(
        f"user_id: {update.effective_user.id}\n"
        f"chat_id: {update.effective_chat.id}\n"
        f"chat_type: {update.effective_chat.type}"
    )


async def menu_handler(update, context):
    await update.effective_message.reply_text(
        "Compact menu ready below.", reply_markup=_menu_markup()
    )
    await update.effective_message.reply_text(
        "Menu", reply_markup=_inline_menu_markup()
    )


async def help_handler(update, context):
    settings = storage.get_settings(context.bot_data["conn"], update.effective_chat.id)
    await update.effective_message.reply_text(
        bot_menu.manual(settings),
        parse_mode=ParseMode.HTML,
        reply_markup=_menu_markup(),
    )


MENU_HANDLERS = {
    "summarize": summarize_handler,
    "ask": ask_handler,
    "chat": chat_handler,
    "lore": lore_handler,
    "insidejoke": insidejoke_handler,
    "bestof": bestof_handler,
    "quotes": quotes_handler,
    "recap": recap_handler,
    "remember": remember_handler,
    "settings": settings_handler,
    "usage": usage_handler,
    "models": models_handler,
    "help": help_handler,
    "whoami": whoami_handler,
}


async def menu_callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    navigation = {
        "menu:home": ("home", "Menu"),
        "menu:conversation": ("conversation", "Conversation"),
        "menu:summarize": ("summarize", "Summaries"),
        "menu:lore": ("lore", "Lore"),
        "menu:usage": ("usage", "Usage"),
    }
    if data in navigation:
        menu, title = navigation[data]
        await query.edit_message_text(title, reply_markup=_inline_menu_markup(menu))
        return
    if data == "menu:help":
        context.args = []
        await help_handler(update, context)
        return
    if data == "settings:view":
        context.args = []
        await settings_handler(update, context)
        return
    if data.startswith("sum:"):
        value = data.split(":", 1)[1]
        context.args = ["auto" if value == "auto" else value]
        await summarize_handler(update, context)
        return
    if data.startswith("usage:"):
        context.args = [data.split(":", 1)[1]]
        await usage_handler(update, context)
        return
    if data.startswith("action:"):
        command = data.split(":", 1)[1]
        handler = MENU_HANDLERS.get(command)
        if handler is not None:
            context.args = []
            await handler(update, context)


async def text_handler(update, context):
    text = update.effective_message.text
    command = bot_menu.BUTTON_COMMANDS.get(text)
    pending = context.bot_data.setdefault("pending_commands", {})
    key = _pending_key(update)
    if command in MENU_HANDLERS:
        pending.pop(key, None)
        context.args = []
        await MENU_HANDLERS[command](update, context)
        return
    action = pending.pop(key, None)
    if action in MENU_HANDLERS:
        context.args = [text]
        await MENU_HANDLERS[action](update, context)
        return
    await log_handler(update, context)


def build_application(conn, data_dir):
    app = Application.builder().token(config.TELEGRAM_TOKEN).build()
    app.bot_data["conn"] = conn
    app.bot_data["data_dir"] = data_dir
    app.add_handler(
        CallbackQueryHandler(
            menu_callback_handler,
            pattern=r"^(menu:|sum:|usage:|settings:view$|action:)",
        )
    )
    app.add_handler(CommandHandler("menu", menu_handler))
    app.add_handler(CommandHandler("ask", ask_handler))
    app.add_handler(CommandHandler("remember", remember_handler))
    app.add_handler(CommandHandler("chat", chat_handler))
    app.add_handler(CommandHandler("lore", lore_handler))
    app.add_handler(CommandHandler("insidejoke", insidejoke_handler))
    app.add_handler(CommandHandler("bestof", bestof_handler))
    app.add_handler(CommandHandler("quotes", quotes_handler))
    app.add_handler(CommandHandler("recap", recap_handler))
    app.add_handler(CommandHandler("summarize", summarize_handler))
    app.add_handler(CommandHandler("setstyle", setstyle_handler))
    app.add_handler(CommandHandler("setfilter", setfilter_handler))
    app.add_handler(CommandHandler("setlang", setlang_handler))
    app.add_handler(CommandHandler("models", models_handler))
    app.add_handler(CommandHandler("setprovider", setprovider_handler))
    app.add_handler(CommandHandler("setmodel", setmodel_handler))
    app.add_handler(CommandHandler("settings", settings_handler))
    app.add_handler(CommandHandler("usage", usage_handler))
    app.add_handler(CommandHandler("whoami", whoami_handler))
    app.add_handler(CommandHandler(["help", "start"], help_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    return app
