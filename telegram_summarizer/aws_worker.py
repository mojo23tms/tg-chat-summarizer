import json
import logging
import time

from telegram.constants import ParseMode

from . import config
from . import helpers
from . import llm
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
        [_button("Summarize", "menu:summarize"), _button("Settings", "settings:view")],
        [_button("Usage", "usage:all"), _button("Help", "menu:help")],
    ]
    if is_owner_dm:
        rows.append([_button("Chats", "owner:chats")])
    return _keyboard(rows)


def _summarize_menu_markup():
    return _keyboard(
        [
            [_button("Last 30", "sum:30"), _button("Last 100", "sum:100")],
            [_button("Last 200", "sum:200"), _button("Auto", "sum:auto")],
            [_button("Back", "menu:home")],
        ]
    )


def _settings_menu_markup():
    return _keyboard(
        [
            [
                _button("Filter off", "settings:filter:off"),
                _button("Clean", "settings:filter:clean"),
                _button("Strict", "settings:filter:strict"),
            ],
            [
                _button("Brief", "settings:style:brief"),
                _button("Concise", "settings:style:concise"),
                _button("Detailed", "settings:style:detailed"),
            ],
            [_button("Custom style", "settings:style:custom")],
            [
                _button("Auto lang", "settings:lang:auto"),
                _button("English", "settings:lang:en"),
                _button("Ukrainian", "settings:lang:uk"),
            ],
            [_button("Custom language", "settings:lang:custom")],
            [_button("Back", "menu:home")],
        ]
    )


def _usage_menu_markup():
    return _keyboard(
        [
            [
                _button("Today", "usage:today"),
                _button("Month", "usage:month"),
                _button("All", "usage:all"),
            ],
            [_button("Back", "menu:home")],
        ]
    )


def _owner_chats_markup(chat_ids):
    rows = [[_button(str(chat_id), f"owner:chat:{chat_id}")] for chat_id in chat_ids]
    rows.append([_button("Back", "menu:home")])
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
    _send_menu(
        telegram,
        _chat_id(message),
        text,
        _main_menu_markup(is_owner_dm=_is_owner_dm(message)),
        message_id=message_id,
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
    prefix = f"chat: {target_chat_id}\n" if target_chat_id != chat_id else ""
    return (
        f"{prefix}"
        f"style: {settings['style']}\n"
        f"filter: {settings['filter_level']}\n"
        f"language: {settings['language']}"
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
        f"messages summarized: {totals['messages_count']}\n"
        f"input tokens: {totals['input_tokens']}\n"
        f"output tokens: {totals['output_tokens']}\n"
        f"total tokens: {totals['total_tokens']}\n"
        f"auto budget: {config.MAX_INPUT_TOKENS - config.SUMMARY_OUTPUT_TOKENS} "
        f"input tokens{estimated_note}"
    )


def _render_usage_menu(storage, telegram, message, period, now_fn, message_id=None):
    _send_menu(
        telegram,
        _chat_id(message),
        _usage_text(storage, message, period, now_fn),
        _usage_menu_markup(),
        message_id=message_id,
    )


def _render_help_menu(storage, telegram, message, message_id=None):
    _send_menu(
        telegram,
        _chat_id(message),
        "Use the buttons below, or keep using slash commands as a fallback.",
        _main_menu_markup(is_owner_dm=_is_owner_dm(message)),
        message_id=message_id,
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
    return {"text": result, "usage": llm.estimate_usage(prompt, result)}


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
            "Gemini blocked this summary request because the selected messages "
            "triggered safety filters. Try /summarize with fewer messages.",
        )
        return
    except Exception:
        logger.exception("summarize failed")
        telegram.send_message(
            chat_id, "Sorry, the summarizer is unavailable right now. Please try again."
        )
        return
    storage.log_usage(chat_id, result.get("usage"), len(msgs), ts=int(now_fn()))
    summary = helpers.scrub(summary, settings["filter_level"], PROFANITY_WORDLIST)
    summary = helpers.render_telegram_html(summary)
    user = _user(message)
    mention = helpers.format_mention(user.get("id"), _user_name(user) or "you")
    if reduced_after_block:
        source = "reduced after Gemini safety block"
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


def _handle_settings(storage, telegram, message):
    chat_id = _chat_id(message)
    telegram.send_message(chat_id, _settings_text(storage, message))


def _handle_help(storage, telegram, message):
    _render_home(storage, telegram, message)


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


def _consume_pending_input(storage, telegram, message, text, now_fn):
    user_id = _user(message).get("id")
    if user_id is None or not hasattr(storage, "get_pending_input"):
        return False
    pending = storage.get_pending_input(user_id, now=int(now_fn()))
    if not pending:
        return False
    if hasattr(storage, "delete_pending_input"):
        storage.delete_pending_input(user_id)

    target_chat_id = pending["target_chat_id"]
    if not _change_allowed_for_target(storage, telegram, message, target_chat_id):
        telegram.send_message(_chat_id(message), "Only admins can change settings.")
        return True
    value = text.strip()
    if not value:
        telegram.send_message(_chat_id(message), "Setting was not changed.")
        return True
    action = pending.get("action")
    if action == "set_style_custom":
        storage.set_setting(target_chat_id, "style", value)
        telegram.send_message(_chat_id(message), f"Updated style to: {value}")
    elif action == "set_lang_custom":
        storage.set_setting(target_chat_id, "language", value)
        telegram.send_message(_chat_id(message), f"Updated language to: {value}")
    return True


def process_update(update, storage, telegram, summarize_fn=None, now_fn=None):
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
    if command is None and _consume_pending_input(storage, telegram, message, text, now_fn):
        return

    if command == "summarize":
        _handle_summarize(storage, telegram, message, args, summarize_fn, now_fn)
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
    elif command in {"help", "start", "menu"}:
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
    elif command is None:
        storage.log_message(
            chat_id,
            message.get("message_id", 0),
            user.get("id", 0),
            _user_name(user),
            text,
            int(now_fn()),
        )


def handle_sqs_event(event, storage, telegram, summarize_fn=None, now_fn=None):
    for record in event.get("Records", []):
        try:
            process_update(
                json.loads(record["body"]),
                storage,
                telegram,
                summarize_fn=summarize_fn,
                now_fn=now_fn,
            )
        except TelegramApiError as exc:
            if exc.status_code and 400 <= exc.status_code < 500 and exc.status_code != 429:
                logger.warning("telegram api permanent failure: %s", exc)
                continue
            raise


def lambda_handler(event, context):
    handle_sqs_event(event, DynamoDBStorage(), TelegramApi())
    return {"batchItemFailures": []}
