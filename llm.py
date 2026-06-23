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
