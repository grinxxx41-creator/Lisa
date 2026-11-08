"""Проверка ответов реальной модели. Пропускается, если Ollama недоступна."""

from __future__ import annotations

import pytest

from core.ai_engine import AIEngine
from core.context_manager import build_messages
from core.model_manager import ModelManager
from storage.settings_storage import DEFAULT_SETTINGS

URL = DEFAULT_SETTINGS["ollama_url"]
MODEL = DEFAULT_SETTINGS["model_name"]
GREETINGS = ("привет", "здравствуй", "добрый", "хай")

requires_ollama = pytest.mark.skipif(
    not ModelManager(URL, MODEL).is_api_available(),
    reason="Ollama не запущена на localhost:11434",
)


def ask(question: str) -> str:
    engine = AIEngine(URL, MODEL)
    # build_messages принимает историю в формате хранилища: {"role", "text"}
    return "".join(engine.stream_reply(build_messages([{"role": "user", "text": question}]))).strip()


def _not_greeting(answer: str) -> bool:
    return not answer.lower().startswith(GREETINGS)


@requires_ollama
def test_capital_question_gets_direct_answer():
    answer = ask("Как называется столица Италии?")
    assert "Рим" in answer
    assert _not_greeting(answer)


@requires_ollama
def test_arithmetic_question_gets_direct_answer():
    answer = ask("Сколько будет 25 * 4?")
    assert "100" in answer
    assert _not_greeting(answer)


@requires_ollama
def test_python_explanation_mentions_python_without_greeting():
    answer = ask("Объясни, что такое Python.")
    assert "Python" in answer
    assert _not_greeting(answer)


@requires_ollama
def test_simple_python_request_returns_code():
    answer = ask("Напиши простой код на Python.")
    assert "print(" in answer or "def " in answer
    assert _not_greeting(answer)


@requires_ollama
def test_identity_question_names_the_model():
    answer = ask("На какой модели ты работаешь?")
    assert "Qwen" in answer
