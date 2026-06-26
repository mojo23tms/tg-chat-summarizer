import math

from . import config

# Use the moving "latest flash" alias rather than a pinned version: pinned
# models (e.g. gemini-1.5-flash) get retired and then return 404 on
# generateContent. The alias always points at a currently-served flash model.
GEMINI_MODEL = "gemini-flash-latest"

FILTER_INSTRUCTIONS = {
    "off": "Do not filter language; reproduce tone faithfully.",
    "clean": "Avoid profanity; mask any strong language with asterisks.",
    "strict": "Use no profanity, slurs, or harassing language whatsoever; "
              "rephrase such content neutrally.",
}


def _language_instruction(language):
    if language == "auto":
        return "Write the summary in the dominant language of the conversation."
    return f"Write the summary in this language: {language}."


def build_prompt(messages, settings):
    filter_level = settings.get("filter_level", "clean")
    transcript = "\n".join(f"{m['user_name']}: {m['text']}" for m in messages)
    return (
        "You are a chat summarizer. Summarize the conversation below.\n"
        "Format the answer as Telegram-compatible HTML. Use only these tags: "
        "<b>, <i>, <u>, <s>, <code>, <pre>, <blockquote>. "
        "Do not use Markdown syntax such as **bold**.\n"
        f"Style: {settings['style']}.\n"
        f"{_language_instruction(settings.get('language', 'auto'))}\n"
        f"{FILTER_INSTRUCTIONS.get(filter_level, FILTER_INSTRUCTIONS['clean'])}\n\n"
        "Conversation:\n"
        f"{transcript}\n\n"
        "Summary:"
    )


def _gemini_backend(prompt):
    import google.generativeai as genai
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    resp = model.generate_content(prompt)
    return resp.text.strip()


def _usage_metadata(response):
    metadata = getattr(response, "usage_metadata", None)
    if not metadata:
        return None

    def get(name):
        if isinstance(metadata, dict):
            return metadata.get(name)
        return getattr(metadata, name, None)

    input_tokens = get("prompt_token_count")
    output_tokens = get("candidates_token_count")
    total_tokens = get("total_token_count")
    if input_tokens is None and output_tokens is None and total_tokens is None:
        return None
    return {
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "total_tokens": int(total_tokens or (input_tokens or 0) + (output_tokens or 0)),
        "estimated": False,
        "model": GEMINI_MODEL,
    }


def _gemini_backend_with_usage(prompt):
    import google.generativeai as genai
    genai.configure(api_key=config.GEMINI_API_KEY)
    model = genai.GenerativeModel(GEMINI_MODEL)
    resp = model.generate_content(prompt)
    return {"text": resp.text.strip(), "usage": _usage_metadata(resp)}


def _default_backend():
    if config.LLM_BACKEND == "gemini":
        return _gemini_backend
    raise ValueError(
        f"Unsupported LLM_BACKEND: {config.LLM_BACKEND!r}. Only 'gemini' is wired."
    )


def _default_backend_with_usage():
    if config.LLM_BACKEND == "gemini":
        return _gemini_backend_with_usage
    raise ValueError(
        f"Unsupported LLM_BACKEND: {config.LLM_BACKEND!r}. Only 'gemini' is wired."
    )


def estimate_tokens(text):
    if not text:
        return 0
    return max(1, math.ceil(len(text) / 4))


def estimate_prompt_tokens(messages, settings):
    return estimate_tokens(build_prompt(messages, settings))


def select_messages_for_token_budget(
    messages, settings, max_input_tokens=None, output_tokens=None
):
    if not messages:
        return []
    max_input_tokens = config.MAX_INPUT_TOKENS if max_input_tokens is None else max_input_tokens
    output_tokens = (
        config.SUMMARY_OUTPUT_TOKENS if output_tokens is None else output_tokens
    )
    budget = max(1, int(max_input_tokens) - int(output_tokens))
    selected = []
    for message in reversed(messages):
        candidate = [message] + selected
        if estimate_prompt_tokens(candidate, settings) > budget:
            break
        selected = candidate
    return selected or [messages[-1]]


def estimate_usage(prompt, text):
    input_tokens = estimate_tokens(prompt)
    output_tokens = estimate_tokens(text)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "estimated": True,
        "model": GEMINI_MODEL,
    }


_estimated_usage = estimate_usage


def summarize_with_usage(messages, settings, backend_fn=None):
    if not messages:
        return {"text": "Nothing to summarize yet.", "usage": None}
    prompt = build_prompt(messages, settings)
    if backend_fn is None:
        backend_fn = _default_backend_with_usage()
    result = backend_fn(prompt)
    if isinstance(result, dict):
        text = result["text"]
        usage = result.get("usage") or estimate_usage(prompt, text)
    else:
        text = result
        usage = estimate_usage(prompt, text)
    return {"text": text, "usage": usage}


def summarize(messages, settings, backend_fn=None):
    if not messages:
        return "Nothing to summarize yet."
    return summarize_with_usage(
        messages, settings, backend_fn=backend_fn or _default_backend()
    )["text"]
