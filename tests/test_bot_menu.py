from telegram_summarizer import bot_menu
from telegram_summarizer import config


def test_reply_keyboard_is_persistent_and_contains_every_public_command():
    markup = bot_menu.reply_markup()
    labels = [button["text"] for row in markup["keyboard"] for button in row]

    assert markup["is_persistent"] is True
    assert markup["resize_keyboard"] is True
    assert set(labels) == set(bot_menu.BUTTON_COMMANDS) - {"💬 Chats"}


def test_manual_documents_lore_permissions_privacy_and_current_model():
    manual = bot_menu.manual(
        {**config.DEFAULTS, "provider": "groq", "model": "model-x"}
    )

    assert "/help" in manual
    assert "/insidejoke &lt;term&gt;" in manual
    assert "/recap [today|week|month|year|all]" in manual
    assert "admin-only" in manual
    assert "never sends the entire archive blindly" in manual
    assert "Current LLM: <code>groq:model-x</code>" in manual
    assert len(manual) <= 4096
