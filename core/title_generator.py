"""Автоматическое название диалога по его первому сообщению. Не зависит от GUI."""

from __future__ import annotations

import logging

from core.ai_engine import AIEngine

log = logging.getLogger("sirius.title")

DEFAULT_TITLE = "Новый диалог"
MAX_TITLE_CHARS = 40
TITLE_MAX_TOKENS = 16

TITLE_PROMPT = (
    "Придумай короткое название диалога по сообщению пользователя: 2–4 слова на русском языке, "
    "отражающие тему. Ответь только названием, без кавычек, точек и пояснений."
)


def clean_title(raw: str) -> str:
    """Приводит ответ модели к короткому названию. Пустая строка, если ничего полезного нет."""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if not lines:
        return ""
    title = lines[0].strip(" \t\"'«»“”.:;!?—-")
    if len(title) > MAX_TITLE_CHARS:
        title = title[:MAX_TITLE_CHARS].rsplit(" ", 1)[0] or title[:MAX_TITLE_CHARS]
    return title.strip()


def fallback_title(first_message: str) -> str:
    """Название из первых слов сообщения, если модель не ответила."""
    text = " ".join(first_message.split())
    if not text:
        return DEFAULT_TITLE
    if len(text) > MAX_TITLE_CHARS:
        text = text[:MAX_TITLE_CHARS].rsplit(" ", 1)[0] or text[:MAX_TITLE_CHARS]
        text += "…"
    return text


def generate_title(engine: AIEngine, first_message: str) -> str:
    """Просит модель придумать название. При любой ошибке возвращает запасной вариант."""
    messages = [
        {"role": "system", "content": TITLE_PROMPT},
        {"role": "user", "content": first_message},
    ]
    try:
        raw = "".join(engine.stream_reply(messages, max_tokens=TITLE_MAX_TOKENS))
    except Exception as exc:  # название не должно ломать работу чата
        log.warning("Не удалось придумать название: %s", exc)
        return fallback_title(first_message)
    return clean_title(raw) or fallback_title(first_message)
