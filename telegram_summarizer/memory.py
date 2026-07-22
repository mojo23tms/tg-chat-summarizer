import json
import re
import time

from . import config
from . import llm


MEMORY_KINDS = {
    "running_joke",
    "nickname",
    "incident",
    "quote",
    "recurring_topic",
    "people_lore",
    "unresolved_story",
    "roast_or_conflict",
    "canon_event",
    "other_lore",
}


def _clean_text(value, limit):
    return str(value or "").strip()[:limit]


def _clean_string_list(values, *, item_limit=100, count_limit=20):
    if not isinstance(values, list):
        return []
    cleaned = []
    for value in values[:count_limit]:
        text = _clean_text(value, item_limit)
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _clean_timestamps(values):
    if not isinstance(values, list):
        return []
    timestamps = []
    for value in values[:20]:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp >= 0 and timestamp not in timestamps:
            timestamps.append(timestamp)
    return timestamps


def _clean_ids(values):
    if not isinstance(values, list):
        return []
    identifiers = []
    for value in values[:50]:
        try:
            identifier = int(value)
        except (TypeError, ValueError):
            continue
        if identifier >= 0 and identifier not in identifiers:
            identifiers.append(identifier)
    return identifiers


def _lexical_terms(summary, items, participants, limit=200):
    source = " ".join(
        [summary, *participants]
        + [
            " ".join(
                [
                    item.get("title", ""),
                    item.get("details", ""),
                    *item.get("people", []),
                    *item.get("keywords", []),
                ]
            )
            for item in items
        ]
    )
    return list(
        dict.fromkeys(
            word for word in re.findall(r"\w+", source.casefold()) if len(word) >= 3
        )
    )[:limit]


def parse_memory_content(text):
    raw = str(text or "").strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", raw, flags=re.DOTALL | re.I)
    if fenced:
        raw = fenced.group(1)
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Memory provider returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("Memory provider output must be a JSON object")

    summary = _clean_text(payload.get("summary"), 2000)
    raw_items = payload.get("items") or []
    if not isinstance(raw_items, list):
        raise ValueError("Memory provider output items must be a JSON array")
    items = []
    for raw_item in raw_items[:50]:
        if not isinstance(raw_item, dict):
            continue
        kind = _clean_text(raw_item.get("kind"), 50)
        if kind not in MEMORY_KINDS:
            kind = "other_lore"
        title = _clean_text(raw_item.get("title"), 200)
        details = _clean_text(raw_item.get("details"), 1000)
        if not title or not details:
            continue
        items.append(
            {
                "kind": kind,
                "title": title,
                "details": details,
                "people": _clean_string_list(raw_item.get("people")),
                "keywords": _clean_string_list(raw_item.get("keywords")),
                "source_timestamps": _clean_timestamps(
                    raw_item.get("source_timestamps")
                ),
                "source_message_ids": _clean_ids(
                    raw_item.get("source_message_ids")
                ),
            }
        )
    if not summary and not items:
        return None
    return {"summary": summary, "items": items}


def generate_snapshot(
    chat_id,
    storage,
    settings,
    *,
    message_limit=None,
    backend_fn=None,
    now_fn=None,
):
    message_limit = int(message_limit or config.MEMORY_MAX_MESSAGES)
    if message_limit < 1:
        raise ValueError("message_limit must be positive")
    messages = storage.recent_messages(chat_id, message_limit)
    return generate_snapshot_from_messages(
        chat_id,
        storage,
        settings,
        messages,
        backend_fn=backend_fn,
        now_fn=now_fn,
    )


def generate_snapshot_from_messages(
    chat_id,
    storage,
    settings,
    messages,
    *,
    backend_fn=None,
    now_fn=None,
    max_input_tokens=None,
    output_tokens=None,
):
    messages = list(messages)
    selected = llm.select_memory_messages_for_token_budget(
        messages,
        settings,
        max_input_tokens=max_input_tokens,
        output_tokens=output_tokens,
    )
    if not selected:
        result = llm.empty_result("Nothing to remember yet.", settings)
        result.update({"snapshot": None, "source_message_count": 0})
        return result

    result = llm.memory_with_usage(
        selected,
        settings,
        backend_fn=backend_fn,
        max_output_tokens=output_tokens,
    )
    try:
        content = parse_memory_content(result["text"])
    except ValueError:
        result.update(
            {
                "snapshot": None,
                "source_message_count": len(selected),
                "invalid_memory": True,
            }
        )
        return result
    if content is None:
        result.update(
            {
                "snapshot": None,
                "source_message_count": len(selected),
                "invalid_memory": False,
            }
        )
        return result

    now_fn = now_fn or time.time
    participants = list(
        dict.fromkeys(
            str(message.get("user_name", "unknown")) for message in selected
        )
    )[:100]
    source_message_ids = list(
        dict.fromkeys(
            int(message["msg_id"])
            for message in selected
            if message.get("msg_id") is not None
        )
    )
    snapshot = {
        "version": 1,
        "created_at": int(now_fn()),
        "start_ts": min(int(message.get("ts", 0)) for message in selected),
        "end_ts": max(int(message.get("ts", 0)) for message in selected),
        "message_count": len(selected),
        "participants": participants,
        "source_message_ids": source_message_ids,
        **content,
    }
    snapshot["lexical_terms"] = _lexical_terms(
        snapshot["summary"], snapshot["items"], participants
    )
    storage.save_memory_snapshot(chat_id, snapshot)
    result.update(
        {
            "snapshot": snapshot,
            "source_message_count": len(selected),
            "invalid_memory": False,
        }
    )
    return result
