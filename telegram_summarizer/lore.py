import time

from . import history_qa


PERIOD_SECONDS = {
    "today": 86400,
    "week": 7 * 86400,
    "month": 30 * 86400,
    "year": 365 * 86400,
}


def period_bounds(value, now):
    period = (value or "month").strip().casefold()
    if period == "all":
        return period, None, int(now)
    if period not in PERIOD_SECONDS:
        raise ValueError("period must be today, week, month, year, or all")
    end_ts = int(now)
    return period, end_ts - PERIOD_SECONDS[period], end_ts


def answer_lore(
    command,
    argument,
    chat_id,
    storage,
    settings,
    *,
    backend_fn=None,
    now_fn=None,
):
    command = str(command).casefold()
    argument = str(argument or "").strip()
    now = int((now_fn or time.time)())
    query = ""
    user = None
    start_ts = None
    end_ts = None

    if command == "lore":
        question = "Give a concise overview of the group's established lore and canon."
    elif command == "insidejoke":
        if not argument:
            raise ValueError("insidejoke requires a term")
        query = argument
        question = f"Explain the inside joke or recurring reference: {argument}"
    elif command == "quotes":
        if argument:
            user = argument
            query = argument
            question = f"Show the best evidence-backed memorable quotes from {argument}."
        else:
            question = "Show the best evidence-backed memorable quotes from the group."
    elif command in {"bestof", "recap"}:
        period, start_ts, end_ts = period_bounds(argument, now)
        if command == "bestof":
            question = (
                f"Give the funniest or most memorable evidence-backed moments for {period}."
            )
        else:
            question = f"Give a concise friend-chat recap for {period}."
    else:
        raise ValueError(f"Unsupported lore command: {command}")

    return history_qa.ask_history(
        chat_id,
        question,
        storage,
        settings,
        backend_fn=backend_fn,
        evidence_limit=30,
        scan_limit=500,
        memory_limit=8,
        memory_scan_limit=500,
        query=query,
        user=user,
        start_ts=start_ts,
        end_ts=end_ts,
    )
