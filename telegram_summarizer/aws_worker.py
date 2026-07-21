import json
import logging
import time
from datetime import datetime, timezone

from telegram.constants import ParseMode

from . import bot_menu
from . import config
from . import helpers
from . import history_qa
from . import llm
from . import lore
from . import memory
from .dynamodb_storage import DynamoDBStorage
from .handlers import PROFANITY_WORDLIST, VALID_FILTERS, is_setting_change_allowed
from .telegram_api import TelegramApi, TelegramApiError

logger = logging.getLogger(__name__)

STYLE_PRESETS = {
    "brief": "very brief, 3-5 bullet points",
    "concise": config.DEFAULTS["style"],
    "detailed": "detailed bullet points with decisions and action items",
}

LANGUAGE_PRESETS = {
    "auto": "auto",
    "en": "English",
    "uk": "Ukrainian",
}


def _message(update):
    return update.get("message") or update.get("edited_message") or {}


def _chat_id(message):
    return (message.get("chat") or {}).get("id")


def _chat_type(message):
    return (message.get("chat") or {}).get("type")


def _user(message):
    return message.get("from") or {}


def _user_name(user):
    parts = [user.get("first_name"), user.get("last_name")]
    full_name = " ".join(part for part in parts if part).strip()
    return full_name or user.get("username") or str(user.get("id", "unknown"))


def _command_parts(text):
    if not text.startswith("/"):
        return None, []
    first, *rest = text.split()
    command = first[1:].split("@", 1)[0].lower()
    return command, rest


def _button(text, callback_data):
    return {"text": text, "callback_data": callback_data}


def _keyboard(rows):
    return {"inline_keyboard": rows}


def _main_menu_markup(is_owner_dm=False):
    rows = [
        [_button("📝 Summarize", "menu:summarize"), _button("⚙️ Settings", "settings:view")],
        [_button("📊 Usage", "usage:all"), _button("❓ Help", "menu:help")],
    ]
    if is_owner_dm:
        rows.append([_button("💬 Chats", "owner:chats")])
    return _keyboard(rows)


def _summarize_menu_markup():
    return _keyboard(
        [
            [_button("🕘 Last 30", "sum:30"), _button("📚 Last 100", "sum:100")],
            [_button("🧾 Last 200", "sum:200"), _button("🎯 Auto", "sum:auto")],
            [_button("⬅️ Back", "menu:home")],
        ]
    )


def _settings_menu_markup():
    return _keyboard(
        [
            [
                _button("🚫 Filter off", "settings:filter:off"),
                _button("🧼 Clean", "settings:filter:clean"),
                _button("🔒 Strict", "settings:filter:strict"),
            ],
            [
                _button("⚡ Brief", "settings:style:brief"),
                _button("✅ Concise", "settings:style:concise"),
                _button("🔍 Detailed", "settings:style:detailed"),
            ],
            [_button("✍️ Custom style", "settings:style:custom")],
            [
                _button("🌐 Auto lang", "settings:lang:auto"),
                _button("🇬🇧 English", "settings:lang:en"),
                _button("🇺🇦 Ukrainian", "settings:lang:uk"),
            ],
            [_button("🗣️ Custom language", "settings:lang:custom")],
            [_button("⬅️ Back", "menu:home")],
        ]
    )


def _usage_menu_markup():
    return _keyboard(
        [
            [
                _button("📅 Today", "usage:today"),
                _button("🗓️ Month", "usage:month"),
                _button("♾️ All", "usage:all"),
            ],
            [_button("⬅️ Back", "menu:home")],
        ]
    )


def _owner_chats_markup(chat_ids):
    rows = [[_button(str(chat_id), f"owner:chat:{chat_id}")] for chat_id in chat_ids]
    rows.append([_button("⬅️ Back", "menu:home")])
    return _keyboard(rows)


def _send_menu(telegram, chat_id, text, reply_markup, message_id=None):
    if message_id:
        telegram.edit_message_text(chat_id, message_id, text, reply_markup=reply_markup)
    else:
        telegram.send_message(chat_id, text, reply_markup=reply_markup)


def _is_owner_dm(message):
    return _chat_type(message) == "private" and _is_owner(_user(message).get("id"))


def _menu_target_chat(storage, message):
    chat_id = _chat_id(message)
    user_id = _user(message).get("id")
    if _chat_type(message) == "private" and _is_owner(user_id):
        return storage.get_owner_active_chat(user_id)
    return chat_id


def _render_home(storage, telegram, message, message_id=None):
    text = "Menu"
    if _is_owner_dm(message):
        active = storage.get_owner_active_chat(_user(message).get("id"))
        if active is not None:
            text = f"Menu\nactive chat: {active}"
    if message_id:
        _send_menu(
            telegram,
            _chat_id(message),
            text,
            _main_menu_markup(is_owner_dm=_is_owner_dm(message)),
            message_id=message_id,
        )
    else:
        telegram.send_message(
            _chat_id(message),
            text,
            reply_markup=bot_menu.reply_markup(is_owner_dm=_is_owner_dm(message)),
        )


def _render_summarize_menu(telegram, message, message_id=None):
    _send_menu(
        telegram,
        _chat_id(message),
        "Summarize",
        _summarize_menu_markup(),
        message_id=message_id,
    )


def _settings_text(storage, message):
    chat_id = _chat_id(message)
    target_chat_id = _control_target_chat(storage, message)
    settings = storage.get_settings(target_chat_id)
    provider, model = llm.resolve_provider_model(settings)
    prefix = f"chat: {target_chat_id}\n" if target_chat_id != chat_id else ""
    return (
        f"{prefix}"
        f"style: {settings['style']}\n"
        f"filter: {settings['filter_level']}\n"
        f"language: {settings['language']}\n"
        f"provider: {provider}\n"
        f"model: {model}"
    )


def _render_settings_menu(storage, telegram, message, message_id=None):
    target_chat_id = _menu_target_chat(storage, message)
    if target_chat_id is None:
        _render_owner_chats(storage, telegram, message, message_id=message_id)
        return
    _send_menu(
        telegram,
        _chat_id(message),
        _settings_text(storage, message),
        _settings_menu_markup(),
        message_id=message_id,
    )


def _usage_text(storage, message, period, now_fn):
    target_chat_id = _control_target_chat(storage, message)
    since_ts = None
    if period == "today":
        since_ts = int(now_fn()) - 86400
    elif period == "month":
        since_ts = int(now_fn()) - 30 * 86400
    totals = storage.usage_totals(target_chat_id, since_ts=since_ts)
    estimated_note = (
        f"\nestimated records: {totals['estimated_records']}"
        if totals["estimated_records"]
        else ""
    )
    return (
        f"chat: {target_chat_id}\n"
        f"period: {period}\n"
        f"requests: {totals['requests']}\n"
        f"source messages processed: {totals['messages_count']}\n"
        f"input tokens: {totals['input_tokens']}\n"
        f"output tokens: {totals['output_tokens']}\n"
        f"total tokens: {totals['total_tokens']}\n"
        f"auto budget: {config.MAX_INPUT_TOKENS - config.SUMMARY_OUTPUT_TOKENS} "
        f"input tokens{estimated_note}"
    )


def _help_text(storage, message):
    target_chat_id = _control_target_chat(storage, message)
    settings = storage.get_settings(target_chat_id)
    active_chat_id = target_chat_id if target_chat_id != _chat_id(message) else None
    return bot_menu.manual(settings, active_chat_id=active_chat_id)


def _render_usage_menu(storage, telegram, message, period, now_fn, message_id=None):
    _send_menu(
        telegram,
        _chat_id(message),
        _usage_text(storage, message, period, now_fn),
        _usage_menu_markup(),
        message_id=message_id,
    )


def _render_help_menu(storage, telegram, message, message_id=None):
    if message_id:
        telegram.edit_message_text(
            _chat_id(message),
            message_id,
            _help_text(storage, message),
            parse_mode=ParseMode.HTML,
            reply_markup=_main_menu_markup(is_owner_dm=_is_owner_dm(message)),
        )
    else:
        telegram.send_message(
            _chat_id(message),
            _help_text(storage, message),
            parse_mode=ParseMode.HTML,
            reply_markup=bot_menu.reply_markup(is_owner_dm=_is_owner_dm(message)),
        )


def _render_owner_chats(storage, telegram, message, message_id=None):
    chat_id = _chat_id(message)
    user_id = _user(message).get("id")
    if _chat_type(message) != "private" or not _is_owner(user_id):
        _send_menu(
            telegram,
            chat_id,
            "Only bot owners can select chats in DM.",
            _main_menu_markup(),
            message_id=message_id,
        )
        return
    chat_ids = storage.list_chat_ids()
    if not chat_ids:
        _send_menu(
            telegram,
            chat_id,
            "No chats found yet.",
            _main_menu_markup(is_owner_dm=True),
            message_id=message_id,
        )
        return
    active = storage.get_owner_active_chat(user_id)
    text = "Choose a chat"
    if active is not None:
        text = f"Choose a chat\nactive chat: {active}"
    _send_menu(telegram, chat_id, text, _owner_chats_markup(chat_ids), message_id=message_id)


def _reply_target(message):
    return _chat_id(message)


def _is_owner(user_id):
    return user_id in config.BOT_OWNER_IDS


def _control_target_chat(storage, message):
    chat_id = _chat_id(message)
    user_id = _user(message).get("id")
    if _chat_type(message) == "private" and _is_owner(user_id):
        return storage.get_owner_active_chat(user_id) or chat_id
    return chat_id


def _send_no_history(telegram, chat_id):
    telegram.send_message(
        chat_id,
        "I have no logged messages yet — I can only summarize messages "
        "sent after I joined this chat.",
    )


def _send_ai_html_response(telegram, chat_id, text):
    for chunk in helpers.split_telegram_html(text):
        telegram.send_message(chat_id, chunk, parse_mode=ParseMode.HTML)


def _utc_day(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")


def _day_start_ts(ts):
    dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return int(datetime(dt.year, dt.month, dt.day, tzinfo=timezone.utc).timestamp())


def _maybe_send_quota_warning(storage, telegram, chat_id, usage, now):
    if not usage:
        return
    provider = usage.get("provider") or ""
    quota = config.DAILY_TOKEN_QUOTAS.get(provider, 0)
    if quota <= 0:
        return
    day = _utc_day(now)
    if hasattr(storage, "quota_warning_sent") and storage.quota_warning_sent(
        chat_id, provider, day
    ):
        return
    totals = storage.usage_totals(
        chat_id,
        since_ts=_day_start_ts(now),
        provider=provider,
        model=usage.get("model") or None,
    )
    used = int(totals["total_tokens"])
    remaining = max(0, quota - used)
    threshold = max(1, int(quota * config.QUOTA_WARNING_REMAINING_PERCENT / 100))
    if remaining > threshold:
        return
    if hasattr(storage, "mark_quota_warning_sent"):
        storage.mark_quota_warning_sent(chat_id, provider, day, ts=int(now))
    telegram.send_message(
        chat_id,
        f"Quota warning: {provider} has about {remaining} of {quota} daily "
        f"tokens remaining for {usage.get('model') or 'the selected model'}.",
    )


def _is_admin(telegram, message, user_id):
    if _chat_type(message) == "private":
        return True
    chat_id = _chat_id(message)
    member = telegram.get_chat_member(chat_id, user_id)
    return is_setting_change_allowed(member.get("status"))


def _change_setting(storage, telegram, message, key, value):
    chat_id = _chat_id(message)
    target_chat_id = _control_target_chat(storage, message)
    user_id = _user(message).get("id")
    if not _is_admin(telegram, message, user_id):
        telegram.send_message(chat_id, "Only admins can change settings.")
        return
    storage.set_setting(target_chat_id, key, value)
    suffix = f" for {target_chat_id}" if target_chat_id != chat_id else ""
    telegram.send_message(chat_id, f"Updated {key}{suffix} to: {value}")


def _summary_result(messages, settings, summarize_fn):
    if summarize_fn is None:
        return llm.summarize_with_usage(messages, settings)
    result = summarize_fn(messages, settings)
    if isinstance(result, dict):
        return result
    prompt = llm.build_prompt(messages, settings)
    provider, model = llm.resolve_provider_model(settings)
    return {
        "text": result,
        "provider": provider,
        "model": model,
        "usage": llm.estimate_usage(prompt, result, provider, model),
        "usage_estimated": True,
        "finish_reason": None,
    }


def _chat_result(question, settings, chat_fn):
    if chat_fn is None:
        return llm.chat_with_usage(question, settings)
    result = chat_fn(question, settings)
    if isinstance(result, dict):
        return result
    prompt = llm.build_chat_prompt(question, settings)
    provider, model = llm.resolve_provider_model(settings)
    return {
        "text": result,
        "provider": provider,
        "model": model,
        "usage": llm.estimate_usage(prompt, result, provider, model),
        "usage_estimated": True,
        "finish_reason": None,
    }


def _summarize_with_block_fallback(msgs, settings, summarize_fn):
    try:
        return _summary_result(msgs, settings, summarize_fn), msgs, False
    except llm.LLMBlockedError:
        if len(msgs) <= config.DEFAULT_COUNT:
            raise
        fallback_msgs = msgs[-config.DEFAULT_COUNT:]
        logger.warning(
            "summary prompt blocked; retrying with %s of %s messages",
            len(fallback_msgs),
            len(msgs),
        )
        return _summary_result(fallback_msgs, settings, summarize_fn), fallback_msgs, True


def _handle_summarize(storage, telegram, message, args, summarize_fn, now_fn):
    chat_id = _reply_target(message)
    settings = storage.get_settings(chat_id)
    if args and args[0].lower() == "auto":
        candidate_messages = storage.recent_messages(
            chat_id, config.SUMMARY_MAX_MESSAGES
        )
        msgs = llm.select_messages_for_token_budget(candidate_messages, settings)
    else:
        n = helpers.parse_count(args[0] if args else None)
        msgs = storage.recent_messages(chat_id, n)
    if not msgs:
        _send_no_history(telegram, chat_id)
        return
    try:
        result, msgs, reduced_after_block = _summarize_with_block_fallback(
            msgs, settings, summarize_fn
        )
        summary = result["text"]
    except llm.LLMBlockedError:
        logger.warning("summary prompt blocked and no smaller fallback is available")
        telegram.send_message(
            chat_id,
            "The selected model blocked this summary request because the messages "
            "triggered safety filters. Try /summarize with fewer messages.",
        )
        return
    except Exception:
        logger.exception("summarize failed")
        telegram.send_message(
            chat_id, "Sorry, the summarizer is unavailable right now. Please try again."
        )
        return
    now = int(now_fn())
    usage = result.get("usage")
    storage.log_usage(chat_id, usage, len(msgs), ts=now)
    summary = helpers.scrub(summary, settings["filter_level"], PROFANITY_WORDLIST)
    summary = helpers.render_telegram_html(summary)
    user = _user(message)
    mention = helpers.format_mention(user.get("id"), _user_name(user) or "you")
    if reduced_after_block:
        source = "reduced after model safety block"
    elif args and args[0].lower() == "auto":
        source = "based on context budget"
    else:
        source = "requested"
    _send_ai_html_response(
        telegram,
        chat_id,
        f"{mention}, here is your summary of the last {len(msgs)} messages "
        f"({source}):\n\n{summary}",
    )
    _maybe_send_quota_warning(storage, telegram, chat_id, usage, now)


def _handle_chat(storage, telegram, message, args, chat_fn, now_fn):
    chat_id = _reply_target(message)
    question = " ".join(args).strip()
    if not question:
        _start_command_input(
            storage,
            telegram,
            message,
            "run_chat",
            "Send your general question as your next message.",
            now_fn,
        )
        return
    settings = storage.get_settings(chat_id)
    try:
        result = _chat_result(question, settings, chat_fn)
    except llm.LLMBlockedError:
        logger.warning("chat prompt blocked")
        telegram.send_message(
            chat_id,
            "The selected model blocked this chat request. Try rephrasing it.",
        )
        return
    except Exception:
        logger.exception("chat failed")
        telegram.send_message(
            chat_id, "Sorry, the chat assistant is unavailable right now. Please try again."
        )
        return

    now = int(now_fn())
    usage = result.get("usage")
    storage.log_usage(chat_id, usage, 0, ts=now)
    text = helpers.render_telegram_html(result["text"])
    _send_ai_html_response(telegram, chat_id, text)
    _maybe_send_quota_warning(storage, telegram, chat_id, usage, now)


def _start_command_input(storage, telegram, message, action, prompt, now_fn):
    user_id = _user(message).get("id")
    if user_id is None or not hasattr(storage, "set_pending_input"):
        telegram.send_message(_chat_id(message), prompt)
        return
    storage.set_pending_input(
        user_id,
        action,
        _reply_target(message),
        now=int(now_fn()),
    )
    telegram.send_message(_chat_id(message), prompt)


def _handle_ask(storage, telegram, message, args, ask_fn, now_fn):
    chat_id = _reply_target(message)
    question = " ".join(args).strip()
    if not question:
        _start_command_input(
            storage,
            telegram,
            message,
            "run_ask",
            "Send your chat-history question as your next message.",
            now_fn,
        )
        return

    telegram.send_message(chat_id, "Searching chat history…")
    settings = storage.get_settings(chat_id)
    try:
        if ask_fn is None:
            result = history_qa.ask_history(chat_id, question, storage, settings)
        else:
            result = ask_fn(question, chat_id, storage, settings)
    except llm.LLMBlockedError:
        logger.warning("ask prompt blocked")
        telegram.send_message(
            chat_id,
            "The selected model blocked this history question. Try rephrasing it.",
        )
        return
    except Exception:
        logger.exception("ask failed")
        telegram.send_message(
            chat_id,
            "Sorry, history search is unavailable right now. Please try again.",
        )
        return

    now = int(now_fn())
    usage = result.get("usage")
    evidence_count = int(result.get("evidence_count", 0))
    storage.log_usage(chat_id, usage, evidence_count, ts=now)
    text = helpers.scrub(
        result["text"], settings["filter_level"], PROFANITY_WORDLIST
    )
    text = helpers.render_telegram_html(text)
    _send_ai_html_response(telegram, chat_id, text)
    _maybe_send_quota_warning(storage, telegram, chat_id, usage, now)


def _handle_lore(storage, telegram, message, command, args, lore_fn, now_fn):
    chat_id = _reply_target(message)
    argument = " ".join(args).strip()
    if not argument and command == "insidejoke":
        _start_command_input(
            storage,
            telegram,
            message,
            "run_insidejoke",
            "Send the inside joke or recurring reference to search for as your next message.",
            now_fn,
        )
        return

    telegram.send_message(chat_id, "Searching chat lore…")
    settings = storage.get_settings(chat_id)
    try:
        if lore_fn is None:
            result = lore.answer_lore(
                command,
                argument,
                chat_id,
                storage,
                settings,
                now_fn=now_fn,
            )
        else:
            result = lore_fn(command, argument, chat_id, storage, settings)
    except ValueError:
        telegram.send_message(
            chat_id,
            f"Usage: /{command} "
            + ("<term>" if command == "insidejoke" else "<name>" if command == "quotes" else "[today|week|month|year|all]"),
        )
        return
    except llm.LLMBlockedError:
        logger.warning("lore prompt blocked")
        telegram.send_message(
            chat_id,
            "The selected model blocked this lore request. Try rephrasing it.",
        )
        return
    except Exception:
        logger.exception("lore search failed")
        telegram.send_message(
            chat_id,
            "Sorry, lore search is unavailable right now. Please try again.",
        )
        return

    now = int(now_fn())
    usage = result.get("usage")
    evidence_count = int(result.get("evidence_count", 0))
    storage.log_usage(chat_id, usage, evidence_count, ts=now)
    text = helpers.scrub(result["text"], settings["filter_level"], PROFANITY_WORDLIST)
    text = helpers.render_telegram_html(text)
    _send_ai_html_response(telegram, chat_id, text)
    _maybe_send_quota_warning(storage, telegram, chat_id, usage, now)


def _handle_remember(storage, telegram, message, args, remember_fn, now_fn):
    chat_id = _reply_target(message)
    user_id = _user(message).get("id")
    if not _is_admin(telegram, message, user_id):
        telegram.send_message(chat_id, "Only admins can build memory snapshots.")
        return
    value = args[0].lower() if args else "auto"
    if value == "auto":
        message_limit = config.MEMORY_MAX_MESSAGES
    else:
        try:
            message_limit = int(value)
        except ValueError:
            telegram.send_message(chat_id, "Usage: /remember [N|auto]")
            return
        message_limit = max(1, min(message_limit, config.MEMORY_MAX_MESSAGES))

    telegram.send_message(chat_id, "Building a memory snapshot…")
    settings = storage.get_settings(chat_id)
    try:
        if remember_fn is None:
            result = memory.generate_snapshot(
                chat_id,
                storage,
                settings,
                message_limit=message_limit,
                now_fn=now_fn,
            )
        else:
            result = remember_fn(chat_id, storage, settings, message_limit)
    except llm.LLMBlockedError:
        logger.warning("memory prompt blocked")
        telegram.send_message(
            chat_id,
            "The selected model blocked this memory snapshot. Try a smaller range.",
        )
        return
    except (ValueError, TypeError):
        logger.exception("memory response invalid")
        telegram.send_message(
            chat_id,
            "The model returned an invalid memory snapshot. Please try again.",
        )
        return
    except Exception:
        logger.exception("memory generation failed")
        telegram.send_message(
            chat_id,
            "Sorry, memory generation is unavailable right now. Please try again.",
        )
        return

    now = int(now_fn())
    usage = result.get("usage")
    source_count = int(result.get("source_message_count", 0))
    storage.log_usage(chat_id, usage, source_count, ts=now)
    if result.get("invalid_memory"):
        telegram.send_message(
            chat_id,
            "The model returned an invalid memory snapshot. Please try again.",
        )
        _maybe_send_quota_warning(storage, telegram, chat_id, usage, now)
        return
    snapshot = result.get("snapshot")
    if snapshot is None:
        if source_count:
            telegram.send_message(chat_id, "No durable chat lore was found in that range.")
        else:
            _send_no_history(telegram, chat_id)
    else:
        telegram.send_message(
            chat_id,
            f"Saved a memory snapshot from {snapshot['message_count']} messages "
            f"with {len(snapshot['items'])} lore items.",
        )
    _maybe_send_quota_warning(storage, telegram, chat_id, usage, now)


def _handle_settings(storage, telegram, message):
    chat_id = _chat_id(message)
    telegram.send_message(chat_id, _settings_text(storage, message))


def _handle_models(storage, telegram, message):
    target_chat_id = _control_target_chat(storage, message)
    settings = storage.get_settings(target_chat_id)
    telegram.send_message(_chat_id(message), llm.models_text(settings))


def _handle_setprovider(storage, telegram, message, args):
    chat_id = _chat_id(message)
    target_chat_id = _control_target_chat(storage, message)
    user_id = _user(message).get("id")
    if not _is_admin(telegram, message, user_id):
        telegram.send_message(chat_id, "Only admins can change settings.")
        return
    try:
        provider = llm.normalize_provider(args[0] if args else "")
    except ValueError:
        telegram.send_message(chat_id, "Usage: /setprovider gemini|groq")
        return
    storage.set_setting(target_chat_id, "provider", provider)
    storage.set_setting(target_chat_id, "model", "")
    suffix = f" for {target_chat_id}" if target_chat_id != chat_id else ""
    model = llm.DEFAULT_MODELS[provider]
    telegram.send_message(
        chat_id,
        f"Updated provider{suffix} to: {provider}\nUsing default model: {model}",
    )


def _handle_setmodel(storage, telegram, message, args):
    chat_id = _chat_id(message)
    target_chat_id = _control_target_chat(storage, message)
    user_id = _user(message).get("id")
    if not _is_admin(telegram, message, user_id):
        telegram.send_message(chat_id, "Only admins can change settings.")
        return
    value = " ".join(args).strip()
    settings = storage.get_settings(target_chat_id)
    try:
        provider, model = llm.parse_model_selection(
            value, settings.get("provider", config.DEFAULT_LLM_PROVIDER)
        )
    except ValueError:
        telegram.send_message(chat_id, "Usage: /setmodel <model|provider:model>")
        return
    storage.set_setting(target_chat_id, "provider", provider)
    storage.set_setting(target_chat_id, "model", model)
    suffix = f" for {target_chat_id}" if target_chat_id != chat_id else ""
    telegram.send_message(chat_id, f"Updated model{suffix} to: {provider}:{model}")


def _handle_help(storage, telegram, message):
    _render_help_menu(storage, telegram, message)


def _handle_chats(storage, telegram, message):
    chat_id = _chat_id(message)
    user_id = _user(message).get("id")
    if _chat_type(message) != "private" or not _is_owner(user_id):
        telegram.send_message(chat_id, "Only bot owners can list chats in DM.")
        return
    chat_ids = storage.list_chat_ids()
    if not chat_ids:
        telegram.send_message(chat_id, "No chats found yet.")
        return
    active = storage.get_owner_active_chat(user_id)
    lines = []
    for item in chat_ids:
        marker = " *" if item == active else ""
        lines.append(f"{item}{marker}")
    telegram.send_message(chat_id, "Known chats:\n" + "\n".join(lines))


def _handle_usechat(storage, telegram, message, args):
    chat_id = _chat_id(message)
    user_id = _user(message).get("id")
    if _chat_type(message) != "private" or not _is_owner(user_id):
        telegram.send_message(chat_id, "Only bot owners can select chats in DM.")
        return
    try:
        target_chat_id = int(args[0])
    except (IndexError, ValueError):
        telegram.send_message(chat_id, "Usage: /usechat <chat_id>")
        return
    storage.set_owner_active_chat(user_id, target_chat_id)
    telegram.send_message(chat_id, f"Active chat set to: {target_chat_id}")


def _handle_usage(storage, telegram, message, args, now_fn):
    chat_id = _chat_id(message)
    period = (args[0] if args else "all").lower()
    if period not in {"today", "month", "all"}:
        telegram.send_message(chat_id, "Usage: /usage [today|month]")
        return
    telegram.send_message(chat_id, _usage_text(storage, message, period, now_fn))


def _handle_whoami(telegram, message):
    user = _user(message)
    telegram.send_message(
        _chat_id(message),
        f"user_id: {user.get('id')}\n"
        f"chat_id: {_chat_id(message)}\n"
        f"chat_type: {_chat_type(message)}",
    )


def _callback_message(callback_query):
    message = dict(callback_query.get("message") or {})
    message["from"] = callback_query.get("from") or {}
    return message


def _callback_message_id(callback_query):
    return (callback_query.get("message") or {}).get("message_id")


def _change_allowed_for_target(storage, telegram, message, target_chat_id):
    user_id = _user(message).get("id")
    if _chat_type(message) == "private":
        return _is_owner(user_id) and target_chat_id is not None
    if target_chat_id != _chat_id(message):
        return False
    return _is_admin(telegram, message, user_id)


def _start_custom_setting(storage, telegram, message, action, message_id, now_fn):
    target_chat_id = _menu_target_chat(storage, message)
    if not _change_allowed_for_target(storage, telegram, message, target_chat_id):
        _send_menu(
            telegram,
            _chat_id(message),
            "Only admins can change settings.",
            _main_menu_markup(is_owner_dm=_is_owner_dm(message)),
            message_id=message_id,
        )
        return
    storage.set_pending_input(
        _user(message).get("id"),
        action,
        target_chat_id,
        now=int(now_fn()),
    )
    label = "style" if action == "set_style_custom" else "language"
    _send_menu(
        telegram,
        _chat_id(message),
        f"Send the custom {label} as your next message.",
        _keyboard([[_button("Cancel", "settings:view")]]),
        message_id=message_id,
    )


def _apply_callback_setting(storage, telegram, message, key, value, message_id):
    target_chat_id = _menu_target_chat(storage, message)
    if not _change_allowed_for_target(storage, telegram, message, target_chat_id):
        _send_menu(
            telegram,
            _chat_id(message),
            "Only admins can change settings.",
            _main_menu_markup(is_owner_dm=_is_owner_dm(message)),
            message_id=message_id,
        )
        return
    storage.set_setting(target_chat_id, key, value)
    _render_settings_menu(storage, telegram, message, message_id=message_id)


def _handle_callback(update, storage, telegram, summarize_fn, now_fn):
    callback_query = update.get("callback_query") or {}
    callback_id = callback_query.get("id")
    if callback_id:
        telegram.answer_callback_query(callback_id)
    data = callback_query.get("data") or ""
    message = _callback_message(callback_query)
    message_id = _callback_message_id(callback_query)
    if not data or _chat_id(message) is None:
        return

    if data == "menu:home":
        _render_home(storage, telegram, message, message_id=message_id)
    elif data == "menu:summarize":
        _render_summarize_menu(telegram, message, message_id=message_id)
    elif data == "menu:help":
        _render_help_menu(storage, telegram, message, message_id=message_id)
    elif data.startswith("sum:"):
        mode = data.split(":", 1)[1]
        args = ["auto"] if mode == "auto" else [mode]
        _handle_summarize(storage, telegram, message, args, summarize_fn, now_fn)
    elif data == "settings:view":
        _render_settings_menu(storage, telegram, message, message_id=message_id)
    elif data.startswith("settings:filter:"):
        value = data.rsplit(":", 1)[1]
        if value in VALID_FILTERS:
            _apply_callback_setting(
                storage, telegram, message, "filter_level", value, message_id
            )
    elif data.startswith("settings:style:"):
        preset = data.rsplit(":", 1)[1]
        if preset == "custom":
            _start_custom_setting(
                storage, telegram, message, "set_style_custom", message_id, now_fn
            )
        elif preset in STYLE_PRESETS:
            _apply_callback_setting(
                storage, telegram, message, "style", STYLE_PRESETS[preset], message_id
            )
    elif data.startswith("settings:lang:"):
        preset = data.rsplit(":", 1)[1]
        if preset == "custom":
            _start_custom_setting(
                storage, telegram, message, "set_lang_custom", message_id, now_fn
            )
        elif preset in LANGUAGE_PRESETS:
            _apply_callback_setting(
                storage, telegram, message, "language", LANGUAGE_PRESETS[preset], message_id
            )
    elif data.startswith("usage:"):
        period = data.split(":", 1)[1]
        if period in {"today", "month", "all"}:
            _render_usage_menu(
                storage, telegram, message, period, now_fn, message_id=message_id
            )
    elif data == "owner:chats":
        _render_owner_chats(storage, telegram, message, message_id=message_id)
    elif data.startswith("owner:chat:"):
        user_id = _user(message).get("id")
        if _chat_type(message) == "private" and _is_owner(user_id):
            target_chat_id = int(data.removeprefix("owner:chat:"))
            storage.set_owner_active_chat(user_id, target_chat_id)
            _render_settings_menu(storage, telegram, message, message_id=message_id)


def _consume_pending_input(
    storage, telegram, message, text, now_fn, chat_fn=None, ask_fn=None, lore_fn=None
):
    user_id = _user(message).get("id")
    if user_id is None or not hasattr(storage, "get_pending_input"):
        return False
    pending = storage.get_pending_input(user_id, now=int(now_fn()))
    if not pending:
        return False
    if hasattr(storage, "delete_pending_input"):
        storage.delete_pending_input(user_id)

    value = text.strip()
    if not value:
        telegram.send_message(_chat_id(message), "Nothing was entered.")
        return True
    action = pending.get("action")
    if action in {"run_ask", "run_chat", "run_insidejoke"}:
        if pending["target_chat_id"] != _reply_target(message):
            telegram.send_message(
                _chat_id(message), "That request belonged to a different chat. Start it again here."
            )
            return True
        if action == "run_ask":
            _handle_ask(storage, telegram, message, [value], ask_fn, now_fn)
        elif action == "run_chat":
            _handle_chat(storage, telegram, message, [value], chat_fn, now_fn)
        else:
            _handle_lore(
                storage,
                telegram,
                message,
                action.removeprefix("run_"),
                [value],
                lore_fn,
                now_fn,
            )
        return True

    target_chat_id = pending["target_chat_id"]
    if not _change_allowed_for_target(storage, telegram, message, target_chat_id):
        telegram.send_message(_chat_id(message), "Only admins can change settings.")
        return True
    if action == "set_style_custom":
        storage.set_setting(target_chat_id, "style", value)
        telegram.send_message(_chat_id(message), f"Updated style to: {value}")
    elif action == "set_lang_custom":
        storage.set_setting(target_chat_id, "language", value)
        telegram.send_message(_chat_id(message), f"Updated language to: {value}")
    return True


def process_update(
    update,
    storage,
    telegram,
    summarize_fn=None,
    chat_fn=None,
    now_fn=None,
    ask_fn=None,
    remember_fn=None,
    lore_fn=None,
):
    now_fn = now_fn or time.time
    if update.get("callback_query"):
        _handle_callback(update, storage, telegram, summarize_fn, now_fn)
        return

    message = _message(update)
    text = message.get("text")
    chat_id = _chat_id(message)
    user = _user(message)
    if not text or chat_id is None:
        return

    command, args = _command_parts(text)
    button_command = bot_menu.BUTTON_COMMANDS.get(text)
    if button_command:
        command, args = button_command, []
        if hasattr(storage, "delete_pending_input") and user.get("id") is not None:
            storage.delete_pending_input(user["id"])
    if command is None and _consume_pending_input(
        storage,
        telegram,
        message,
        text,
        now_fn,
        chat_fn=chat_fn,
        ask_fn=ask_fn,
        lore_fn=lore_fn,
    ):
        return

    if command == "summarize":
        _handle_summarize(storage, telegram, message, args, summarize_fn, now_fn)
    elif command == "ask":
        _handle_ask(storage, telegram, message, args, ask_fn, now_fn)
    elif command == "remember":
        _handle_remember(storage, telegram, message, args, remember_fn, now_fn)
    elif command == "chat":
        _handle_chat(storage, telegram, message, args, chat_fn, now_fn)
    elif command in {"lore", "insidejoke", "bestof", "quotes", "recap"}:
        _handle_lore(storage, telegram, message, command, args, lore_fn, now_fn)
    elif command == "models":
        _handle_models(storage, telegram, message)
    elif command == "settings":
        _handle_settings(storage, telegram, message)
    elif command == "chats":
        _handle_chats(storage, telegram, message)
    elif command == "usechat":
        _handle_usechat(storage, telegram, message, args)
    elif command == "usage":
        _handle_usage(storage, telegram, message, args, now_fn)
    elif command == "whoami":
        _handle_whoami(telegram, message)
    elif command == "menu":
        _render_home(storage, telegram, message)
    elif command in {"help", "start"}:
        _handle_help(storage, telegram, message)
    elif command == "setstyle":
        value = " ".join(args).strip()
        if not value:
            telegram.send_message(chat_id, "Usage: /setstyle <description>")
        else:
            _change_setting(storage, telegram, message, "style", value)
    elif command == "setfilter":
        value = (args[0] if args else "").lower()
        if value not in VALID_FILTERS:
            telegram.send_message(chat_id, "Usage: /setfilter off|clean|strict")
        else:
            _change_setting(storage, telegram, message, "filter_level", value)
    elif command == "setlang":
        value = (args[0] if args else "").strip()
        if not value:
            telegram.send_message(chat_id, "Usage: /setlang <code|auto>")
        else:
            _change_setting(storage, telegram, message, "language", value)
    elif command == "setprovider":
        _handle_setprovider(storage, telegram, message, args)
    elif command == "setmodel":
        _handle_setmodel(storage, telegram, message, args)
    elif command is None:
        storage.log_message(
            chat_id,
            message.get("message_id", 0),
            user.get("id", 0),
            _user_name(user),
            text,
            int(now_fn()),
        )


def handle_sqs_event(
    event,
    storage,
    telegram,
    summarize_fn=None,
    chat_fn=None,
    now_fn=None,
    ask_fn=None,
    remember_fn=None,
    lore_fn=None,
):
    for record in event.get("Records", []):
        try:
            process_update(
                json.loads(record["body"]),
                storage,
                telegram,
                summarize_fn=summarize_fn,
                chat_fn=chat_fn,
                now_fn=now_fn,
                ask_fn=ask_fn,
                remember_fn=remember_fn,
                lore_fn=lore_fn,
            )
        except TelegramApiError as exc:
            if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code != 429:
                logger.warning("telegram api permanent failure: %s", exc)
                continue
            raise


def lambda_handler(event, context):
    handle_sqs_event(event, DynamoDBStorage(), TelegramApi())
    return {"batchItemFailures": []}
