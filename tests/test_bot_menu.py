from telegram_summarizer import bot_menu
from telegram_summarizer import config


def test_reply_keyboard_is_one_compact_persistent_launcher_row():
    markup = bot_menu.reply_markup()

    assert markup["is_persistent"] is True
    assert markup["resize_keyboard"] is True
    assert markup["keyboard"] == [[{"text": "☰ Menu"}]]


def test_inline_menus_keep_every_button_command_reachable():
    callbacks = {
        button["callback_data"]
        for menu in bot_menu.INLINE_MENUS
        for row in bot_menu.inline_rows(menu, is_owner_dm=True)
        for button in row
    }
    reachable = {"menu"}
    reachable.update(
        callback.split(":", 1)[1]
        for callback in callbacks
        if callback.startswith("action:")
    )
    if any(callback.startswith("sum:") for callback in callbacks):
        reachable.add("summarize")
    if "settings:view" in callbacks:
        reachable.add("settings")
    if any(callback.startswith("usage:") for callback in callbacks):
        reachable.add("usage")
    if "menu:help" in callbacks:
        reachable.add("help")
    if "owner:chats" in callbacks:
        reachable.add("chats")

    assert reachable == set(bot_menu.BUTTON_COMMANDS.values())
    assert all(len(bot_menu.inline_rows(menu)) <= 4 for menu in bot_menu.INLINE_MENUS)


def test_owner_chat_picker_is_inline_not_an_extra_persistent_row():
    assert bot_menu.rows(is_owner_dm=True) == [["☰ Menu"]]
    assert bot_menu.inline_rows("home", is_owner_dm=True)[-1] == [
        {"text": "💬 Chats", "callback_data": "owner:chats"}
    ]


def test_manual_documents_lore_permissions_privacy_and_current_model():
    manual = bot_menu.manual(
        {**config.DEFAULTS, "provider": "groq", "model": "model-x"}
    )

    assert "/help" in manual
    assert "compact <b>☰ Menu</b>" in manual
    assert "/insidejoke &lt;term&gt;" in manual
    assert "/recap [today|week|month|year|all]" in manual
    assert "/usage [today|month|all]" in manual
    assert "admin-only" in manual
    assert "never sends the entire archive blindly" in manual
    assert "Current LLM: <code>groq:model-x</code>" in manual
    assert len(manual) <= 4096
