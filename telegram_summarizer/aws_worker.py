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
    return {"text": result, "usage": llm._estimated_usage(prompt, result)}


def _handle_summarize(storage, telegram, message, args, summarize_fn, now_fn):
    chat_id = _reply_target(message)
    settings = storage.get_settings(chat_id)
    if args and args[0].lower() == "auto":
        candidate_messages = storage.recent_messages(chat_id, config.MAX_COUNT)
        msgs = llm.select_messages_for_token_budget(candidate_messages, settings)
    else:
        n = helpers.parse_count(args[0] if args else None)
        msgs = storage.recent_messages(chat_id, n)
    if not msgs:
        _send_no_history(telegram, chat_id)
        return
    try:
        result = _summary_result(msgs, settings, summarize_fn)
        summary = result["text"]
    except Exception:
        logger.exception("summarize failed")
        telegram.send_message(
            chat_id, "Sorry, the summarizer is unavailable right now. Please try again."
        )
        return
    storage.log_usage(chat_id, result.get("usage"), len(msgs), ts=int(now_fn()))
    summary = helpers.scrub(summary, settings["filter_level"], PROFANITY_WORDLIST)
    summary = helpers.render_summary_html(summary)
    user = _user(message)
    mention = helpers.format_mention(user.get("id"), _user_name(user) or "you")
    source = "based on context budget" if args and args[0].lower() == "auto" else "requested"
    telegram.send_message(
        chat_id,
        f"{mention}, here is your summary of the last {len(msgs)} messages "
        f"({source}):\n\n{summary}",
        parse_mode=ParseMode.HTML,
    )


def _handle_settings(storage, telegram, message):
    chat_id = _chat_id(message)
    target_chat_id = _control_target_chat(storage, message)
    settings = storage.get_settings(target_chat_id)
    prefix = f"chat: {target_chat_id}\n" if target_chat_id != chat_id else ""
    telegram.send_message(
        chat_id,
        f"{prefix}"
        f"style: {settings['style']}\n"
        f"filter: {settings['filter_level']}\n"
        f"language: {settings['language']}",
    )


def _handle_help(telegram, message):
    telegram.send_message(
        _reply_target(message),
        "/summarize [N|auto] — summarize messages (default "
        f"{config.DEFAULT_COUNT}, max {config.MAX_COUNT}).\n"
        "/setstyle <text>, /setfilter off|clean|strict, /setlang <code|auto> — "
        "admins only.\n/settings — show current settings.\n"
        "/usage [today|month] — show token usage.",
    )


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
    target_chat_id = _control_target_chat(storage, message)
    period = (args[0] if args else "all").lower()
    since_ts = None
    if period == "today":
        since_ts = int(now_fn()) - 86400
    elif period == "month":
        since_ts = int(now_fn()) - 30 * 86400
    elif period != "all":
        telegram.send_message(chat_id, "Usage: /usage [today|month]")
        return
    totals = storage.usage_totals(target_chat_id, since_ts=since_ts)
    estimated_note = (
        f"\nestimated records: {totals['estimated_records']}"
        if totals["estimated_records"]
        else ""
    )
    telegram.send_message(
        chat_id,
        f"chat: {target_chat_id}\n"
        f"period: {period}\n"
        f"requests: {totals['requests']}\n"
        f"messages summarized: {totals['messages_count']}\n"
        f"input tokens: {totals['input_tokens']}\n"
        f"output tokens: {totals['output_tokens']}\n"
        f"total tokens: {totals['total_tokens']}\n"
        f"auto budget: {config.MAX_INPUT_TOKENS - config.SUMMARY_OUTPUT_TOKENS} "
        f"input tokens{estimated_note}",
    )


def _handle_whoami(telegram, message):
    user = _user(message)
    telegram.send_message(
        _chat_id(message),
        f"user_id: {user.get('id')}\n"
        f"chat_id: {_chat_id(message)}\n"
        f"chat_type: {_chat_type(message)}",
    )


def process_update(update, storage, telegram, summarize_fn=None, now_fn=None):
    now_fn = now_fn or time.time
    message = _message(update)
    text = message.get("text")
    chat_id = _chat_id(message)
    user = _user(message)
    if not text or chat_id is None:
        return

    command, args = _command_parts(text)
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
    elif command in {"help", "start"}:
        _handle_help(telegram, message)
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
