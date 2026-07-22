import logging
import re
import time

from . import llm
from .retrieval import ChatHistoryRetriever, RetrievalRequest


DEFAULT_EVIDENCE_LIMIT = 20
DEFAULT_SCAN_LIMIT = 1000
DEFAULT_MEMORY_LIMIT = 5
DEFAULT_MEMORY_SCAN_LIMIT = 500
DEFAULT_MEMORY_SUPPORT_LIMIT = 3
DEFAULT_MEMORY_SUPPORT_SCAN_LIMIT = 50

logger = logging.getLogger(__name__)

_QUESTION_STOPWORDS = {
    "a",
    "about",
    "an",
    "and",
    "are",
    "chat",
    "did",
    "do",
    "does",
    "for",
    "from",
    "history",
    "how",
    "in",
    "is",
    "me",
    "of",
    "on",
    "or",
    "our",
    "said",
    "say",
    "tell",
    "the",
    "to",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "who",
    "why",
    "with",
    "було",
    "була",
    "були",
    "де",
    "історії",
    "коли",
    "мені",
    "наш",
    "наша",
    "наше",
    "про",
    "розкажи",
    "хто",
    "чаті",
    "чому",
    "що",
    "як",
}


def search_query(question):
    words = re.findall(r"\w+", str(question).casefold())
    useful = [
        word
        for word in words
        if len(word) >= 3 and word not in _QUESTION_STOPWORDS
    ]
    return " ".join(dict.fromkeys(useful))


def ask_history(
    chat_id,
    question,
    storage,
    settings,
    *,
    retriever=None,
    backend_fn=None,
    evidence_limit=DEFAULT_EVIDENCE_LIMIT,
    scan_limit=DEFAULT_SCAN_LIMIT,
    memory_limit=DEFAULT_MEMORY_LIMIT,
    memory_scan_limit=DEFAULT_MEMORY_SCAN_LIMIT,
    query=None,
    user=None,
    start_ts=None,
    end_ts=None,
    memory_support_limit=DEFAULT_MEMORY_SUPPORT_LIMIT,
    memory_support_scan_limit=DEFAULT_MEMORY_SUPPORT_SCAN_LIMIT,
):
    started_at = time.monotonic()
    query = search_query(question) if query is None else str(query)
    retriever = retriever or ChatHistoryRetriever(storage)
    retrieval = retriever.retrieve(
        chat_id,
        RetrievalRequest(
            query=query,
            user=user,
            start_ts=start_ts,
            end_ts=end_ts,
            limit=evidence_limit,
            scan_limit=scan_limit,
        ),
    )
    memory_kwargs = {
        "query": query,
        "limit": memory_limit,
        "scan_limit": memory_scan_limit,
    }
    if start_ts is not None:
        memory_kwargs["start_ts"] = start_ts
    if end_ts is not None:
        memory_kwargs["end_ts"] = end_ts
    memories = (
        storage.search_memories(chat_id, **memory_kwargs)
        if hasattr(storage, "search_memories")
        else []
    )
    support_messages = []
    support_scanned = 0
    support_truncated = False
    if memories and hasattr(storage, "message_page"):
        support_retriever = ChatHistoryRetriever(
            storage, page_size=max(1, min(50, int(memory_support_scan_limit)))
        )
        for remembered in memories:
            remembered_start = int(remembered.get("start_ts", 0))
            remembered_end = int(remembered.get("end_ts", 99_999_999_999))
            range_start = max(
                remembered_start, 0 if start_ts is None else int(start_ts)
            )
            range_end = min(
                remembered_end,
                99_999_999_999 if end_ts is None else int(end_ts),
            )
            if range_start > range_end:
                continue
            support = support_retriever.retrieve(
                chat_id,
                RetrievalRequest(
                    query=query,
                    user=user,
                    start_ts=range_start,
                    end_ts=range_end,
                    limit=memory_support_limit,
                    scan_limit=memory_support_scan_limit,
                ),
            )
            support_messages.extend(support.messages)
            support_scanned += support.scanned_count
            support_truncated = support_truncated or support.truncated
    merged_messages = []
    seen_messages = set()
    for message in [*retrieval.messages, *support_messages]:
        identity = (int(message.get("ts", 0)), int(message.get("msg_id", 0)))
        if identity in seen_messages:
            continue
        seen_messages.add(identity)
        merged_messages.append(message)
    merged_messages.sort(
        key=lambda message: (
            int(message.get("ts", 0)), int(message.get("msg_id", 0))
        )
    )
    retrieval_seconds = time.monotonic() - started_at
    evidence, selected_memories = llm.select_ask_context_for_token_budget(
        question,
        merged_messages,
        memories,
        settings,
        retrieval_truncated=retrieval.truncated or support_truncated,
    )
    model_started_at = time.monotonic()
    result = llm.ask_with_usage(
        question,
        evidence,
        settings,
        retrieval_truncated=retrieval.truncated or support_truncated,
        backend_fn=backend_fn,
        memories=selected_memories,
    )
    model_seconds = time.monotonic() - model_started_at
    result.update(
        {
            "evidence_count": len(evidence),
            "retrieved_count": len(merged_messages),
            "scanned_count": retrieval.scanned_count + support_scanned,
            "retrieval_truncated": retrieval.truncated or support_truncated,
            "memory_count": len(selected_memories),
        }
    )
    logger.info(
        "ask completed chat_id=%s scanned=%s retrieved=%s evidence=%s "
        "memories=%s truncated=%s retrieval_seconds=%.3f model_seconds=%.3f",
        chat_id,
        retrieval.scanned_count + support_scanned,
        len(merged_messages),
        len(evidence),
        len(selected_memories),
        retrieval.truncated or support_truncated,
        retrieval_seconds,
        model_seconds,
    )
    return result
