import config

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
    model = genai.GenerativeModel("gemini-1.5-flash")
    resp = model.generate_content(prompt)
    return resp.text.strip()


def _default_backend():
    if config.LLM_BACKEND == "gemini":
        return _gemini_backend
    raise ValueError(
        f"Unsupported LLM_BACKEND: {config.LLM_BACKEND!r}. Only 'gemini' is wired."
    )


def summarize(messages, settings, backend_fn=None):
    if not messages:
        return "Nothing to summarize yet."
    if backend_fn is None:
        backend_fn = _default_backend()
    prompt = build_prompt(messages, settings)
    return backend_fn(prompt)
