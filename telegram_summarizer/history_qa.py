import logging
import re
import time

from . import llm
from .retrieval import ChatHistoryRetriever, RetrievalRequest


DEFAULT_EVIDENCE_LIMIT = 20
DEFAULT_SCAN_LIMIT = 1000
DEFAULT_MEMORY_LIMIT = 5
DEFAULT_MEMORY_SCAN_LIMIT = 50

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
    retrieval_seconds = time.monotonic() - started_at
    evidence, selected_memories = llm.select_ask_context_for_token_budget(
        question,
        retrieval.messages,
        memories,
        settings,
        retrieval_truncated=retrieval.truncated,
    )
    model_started_at = time.monotonic()
    result = llm.ask_with_usage(
        question,
        evidence,
        settings,
        retrieval_truncated=retrieval.truncated,
        backend_fn=backend_fn,
        memories=selected_memories,
    )
    model_seconds = time.monotonic() - model_started_at
    result.update(
        {
            "evidence_count": len(evidence),
            "retrieved_count": len(retrieval.messages),
            "scanned_count": retrieval.scanned_count,
            "retrieval_truncated": retrieval.truncated,
            "memory_count": len(selected_memories),
        }
    )
    logger.info(
        "ask completed chat_id=%s scanned=%s retrieved=%s evidence=%s "
        "memories=%s truncated=%s retrieval_seconds=%.3f model_seconds=%.3f",
        chat_id,
        retrieval.scanned_count,
        len(retrieval.messages),
        len(evidence),
        len(selected_memories),
        retrieval.truncated,
        retrieval_seconds,
        model_seconds,
    )
    return result
