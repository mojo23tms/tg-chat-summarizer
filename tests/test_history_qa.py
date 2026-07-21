from telegram_summarizer import history_qa
from telegram_summarizer.retrieval import RetrievalResult


SETTINGS = {
    "style": "concise",
    "filter_level": "clean",
    "language": "auto",
    "provider": "gemini",
    "model": "gemini-test",
}


class FakeRetriever:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def retrieve(self, chat_id, request):
        self.calls.append((chat_id, request))
        return self.result


class FakeMemoryStorage:
    def __init__(self, memories):
        self.memories = memories
        self.calls = []

    def search_memories(self, chat_id, **kwargs):
        self.calls.append((chat_id, kwargs))
        return self.memories


def test_search_query_removes_question_filler_and_preserves_lore_terms():
    assert history_qa.search_query("Who said the Ibiza hotel joke in our chat?") == (
        "ibiza hotel joke"
    )
    assert history_qa.search_query("Хто розказав про легендарний шашлик?") == (
        "розказав легендарний шашлик"
    )


def test_ask_history_uses_bounded_current_chat_retrieval_and_evidence():
    retriever = FakeRetriever(
        RetrievalResult(
            messages=[
                {
                    "msg_id": 7,
                    "user_id": 10,
                    "user_name": "Alice",
                    "text": "Ibiza started here",
                    "ts": 1710000000,
                }
            ],
            scanned_count=50,
            truncated=True,
        )
    )
    captured = {}

    def backend(prompt):
        captured["prompt"] = prompt
        return "Alice started it."

    result = history_qa.ask_history(
        -1001,
        "Who started the Ibiza joke?",
        storage=object(),
        settings=SETTINGS,
        retriever=retriever,
        backend_fn=backend,
        evidence_limit=12,
        scan_limit=345,
    )

    chat_id, request = retriever.calls[0]
    assert chat_id == -1001
    assert request.query == "started ibiza joke"
    assert request.limit == 12
    assert request.scan_limit == 345
    assert "user=Alice" in captured["prompt"]
    assert "bounded retrieval scan was truncated" in captured["prompt"]
    assert result["text"] == "Alice started it."
    assert result["evidence_count"] == 1
    assert result["retrieved_count"] == 1
    assert result["scanned_count"] == 50
    assert result["retrieval_truncated"] is True


def test_ask_history_skips_llm_when_no_evidence_is_found():
    retriever = FakeRetriever(
        RetrievalResult(messages=[], scanned_count=100, truncated=False)
    )
    called = {"count": 0}

    def backend(prompt):
        called["count"] += 1
        return "should not run"

    result = history_qa.ask_history(
        10,
        "What happened in Atlantis?",
        storage=object(),
        settings=SETTINGS,
        retriever=retriever,
        backend_fn=backend,
    )

    assert called["count"] == 0
    assert "couldn't find relevant messages" in result["text"]
    assert result["usage"] is None
    assert result["evidence_count"] == 0
    assert result["retrieved_count"] == 0
    assert result["scanned_count"] == 100


def test_ask_history_uses_relevant_memory_when_raw_messages_are_missing():
    retriever = FakeRetriever(
        RetrievalResult(messages=[], scanned_count=100, truncated=False)
    )
    storage = FakeMemoryStorage(
        [
            {
                "created_at": 200,
                "summary": "Ibiza lore",
                "items": [
                    {
                        "kind": "running_joke",
                        "title": "Ibiza",
                        "details": "Alice started the hotel joke",
                        "people": ["Alice"],
                        "keywords": ["ibiza"],
                        "source_timestamps": [123],
                    }
                ],
            }
        ]
    )
    captured = {}

    def backend(prompt):
        captured["prompt"] = prompt
        return "The memory says Alice started it, but raw evidence is unavailable."

    result = history_qa.ask_history(
        10,
        "Who started the Ibiza joke?",
        storage,
        SETTINGS,
        retriever=retriever,
        backend_fn=backend,
    )

    assert storage.calls == [
        (10, {"query": "started ibiza joke", "limit": 5, "scan_limit": 50})
    ]
    assert "<retrieved_memory_snapshots>" in captured["prompt"]
    assert "Alice started the hotel joke" in captured["prompt"]
    assert "prefer raw messages if they conflict" in captured["prompt"]
    assert result["evidence_count"] == 0
    assert result["memory_count"] == 1
    assert result["usage"] is not None


def test_all_filler_question_falls_back_to_recent_context():
    retriever = FakeRetriever(RetrievalResult())

    history_qa.ask_history(
        10,
        "What did we say in the chat?",
        storage=object(),
        settings=SETTINGS,
        retriever=retriever,
    )

    assert retriever.calls[0][1].query == ""
