"""Тесты автоназвания диалогов и очистки пустых чатов."""

from __future__ import annotations

from core.title_generator import (
    DEFAULT_TITLE,
    MAX_TITLE_CHARS,
    clean_title,
    fallback_title,
    generate_title,
)
from storage.chat_storage import ChatStorage


class FakeEngine:
    def __init__(self, reply: str = "", fail: bool = False):
        self.reply = reply
        self.fail = fail
        self.calls = []

    def stream_reply(self, messages, cancel_event=None, max_tokens=None):
        self.calls.append((messages, max_tokens))
        if self.fail:
            raise RuntimeError("Ollama не отвечает")
        yield self.reply


def test_clean_title_strips_quotes_and_punctuation():
    assert clean_title('"Рецепт борща."') == "Рецепт борща"
    assert clean_title("  Вопросы о Марсе \n\nпояснение") == "Вопросы о Марсе"


def test_clean_title_limits_length_on_word_boundary():
    long_raw = "очень длинное название которое точно не влезет в одну строку меню"
    title = clean_title(long_raw)
    assert len(title) <= MAX_TITLE_CHARS
    assert not title.endswith(" ")


def test_clean_title_empty_for_blank_reply():
    assert clean_title("   \n  ") == ""


def test_fallback_title_uses_first_words():
    assert fallback_title("  Как   приготовить борщ  ") == "Как приготовить борщ"
    assert fallback_title("   ") == DEFAULT_TITLE
    assert fallback_title("а" * 100).endswith("…")


def test_generate_title_uses_model_reply_and_small_token_limit():
    engine = FakeEngine(reply="Рецепт борща")
    assert generate_title(engine, "как приготовить борщ") == "Рецепт борща"
    _, max_tokens = engine.calls[0]
    assert max_tokens is not None and max_tokens <= 32


def test_generate_title_falls_back_when_model_fails():
    engine = FakeEngine(fail=True)
    assert generate_title(engine, "почему небо голубое") == "почему небо голубое"


def test_delete_empty_chats_keeps_current_and_non_empty(tmp_path):
    storage = ChatStorage(tmp_path / "chats")
    empty = storage.create_chat()
    kept_empty = storage.create_chat()
    filled = storage.create_chat()
    storage.add_message(filled["file_id"], "user", "привет")

    removed = storage.delete_empty_chats(keep=kept_empty["file_id"])

    assert removed == 1
    assert storage.load_chat(empty["file_id"]) is None
    assert storage.load_chat(kept_empty["file_id"]) is not None
    assert storage.load_chat(filled["file_id"]) is not None
