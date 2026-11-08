"""Тесты AI Engine и Model Manager на mock-ответах Ollama (без реального запуска модели)."""

from __future__ import annotations

import json
import threading
from unittest import mock

import pytest
import requests

from core.ai_engine import AIEngine, OllamaError, OllamaUnavailable
from core.context_manager import SYSTEM_PROMPT, build_messages
from core.model_manager import ModelManager, OllamaStatus


class FakeResponse:
    def __init__(self, lines=None, status=200):
        self._lines = lines or []
        self.status_code = status
        self.closed = False

    def iter_lines(self, decode_unicode=True):
        yield from self._lines

    def close(self):
        self.closed = True


def _chunk(text: str, done: bool = False) -> str:
    return json.dumps({"message": {"role": "assistant", "content": text}, "done": done})


def test_stream_reply_yields_tokens_in_order():
    response = FakeResponse([_chunk("При"), _chunk("вет"), _chunk("", done=True)])
    with mock.patch("core.ai_engine.requests.post", return_value=response) as post:
        tokens = list(AIEngine("http://localhost:11434", "qwen3:8b-q4_K_M").stream_reply([]))
    assert tokens == ["При", "вет"]
    payload = post.call_args.kwargs["json"]
    assert payload["model"] == "qwen3:8b-q4_K_M"
    assert payload["stream"] is True
    assert response.closed


def test_stream_reply_stops_when_cancelled():
    cancel = threading.Event()
    lines = [_chunk("один "), _chunk("два "), _chunk("три ")]
    response = FakeResponse(lines)

    engine = AIEngine("http://localhost:11434", "qwen3:8b-q4_K_M")
    with mock.patch("core.ai_engine.requests.post", return_value=response):
        gen = engine.stream_reply([], cancel)
        assert next(gen) == "один "
        cancel.set()
        rest = list(gen)
    assert rest == []


def test_connection_error_is_reported_as_unavailable():
    engine = AIEngine("http://localhost:11434", "qwen3:8b-q4_K_M")
    with mock.patch("core.ai_engine.requests.post", side_effect=requests.ConnectionError()):
        with pytest.raises(OllamaUnavailable):
            list(engine.stream_reply([]))


def test_missing_model_gives_clear_error():
    engine = AIEngine("http://localhost:11434", "qwen3:8b-q4_K_M")
    with mock.patch("core.ai_engine.requests.post", return_value=FakeResponse(status=404)):
        with pytest.raises(OllamaError, match="не найдена"):
            list(engine.stream_reply([]))


def test_error_inside_stream_is_raised():
    response = FakeResponse([json.dumps({"error": "out of memory"})])
    engine = AIEngine("http://localhost:11434", "qwen3:8b-q4_K_M")
    with mock.patch("core.ai_engine.requests.post", return_value=response):
        with pytest.raises(OllamaError, match="out of memory"):
            list(engine.stream_reply([]))


def test_build_messages_adds_system_prompt_and_keeps_last_user_message():
    history = [{"role": "user", "text": "старое " * 1000}, {"role": "user", "text": "вопрос"}]
    messages = build_messages(history, max_chars=50)
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert messages[-1] == {"role": "user", "content": "вопрос"}


def test_build_messages_drops_old_messages_over_limit():
    history = [
        {"role": "user", "text": "a" * 100},
        {"role": "assistant", "text": "b" * 100},
        {"role": "user", "text": "c" * 10},
    ]
    messages = build_messages(history, max_chars=120)
    contents = [m["content"] for m in messages[1:]]
    assert contents == ["b" * 100, "c" * 10]


def test_check_status_not_installed(monkeypatch):
    manager = ModelManager("http://localhost:11434", "qwen3:8b-q4_K_M")
    monkeypatch.setattr(manager, "is_api_available", lambda: False)
    monkeypatch.setattr(ModelManager, "find_executable", staticmethod(lambda: None))
    assert manager.check_status().status is OllamaStatus.NOT_INSTALLED


def test_check_status_not_running(monkeypatch):
    manager = ModelManager("http://localhost:11434", "qwen3:8b-q4_K_M")
    monkeypatch.setattr(manager, "is_api_available", lambda: False)
    monkeypatch.setattr(ModelManager, "find_executable", staticmethod(lambda: "ollama.exe"))
    assert manager.check_status().status is OllamaStatus.NOT_RUNNING


def test_check_status_no_model_and_ready(monkeypatch):
    manager = ModelManager("http://localhost:11434", "qwen3:8b-q4_K_M")
    monkeypatch.setattr(manager, "is_api_available", lambda: True)

    monkeypatch.setattr(manager, "list_models", lambda: ["llama3:8b"])
    assert manager.check_status().status is OllamaStatus.NO_MODEL

    monkeypatch.setattr(manager, "list_models", lambda: ["qwen3:8b-q4_K_M"])
    assert manager.check_status().status is OllamaStatus.READY


@pytest.mark.skipif(
    not ModelManager("http://localhost:11434", "qwen3:8b-q4_K_M").is_api_available(),
    reason="Ollama не запущена на localhost:11434",
)
def test_real_ollama_answers_in_russian():
    """Единственная проверка с реальной моделью. Пропускается, если Ollama недоступна."""
    engine = AIEngine("http://localhost:11434", "qwen3:8b-q4_K_M")
    messages = build_messages([{"role": "user", "text": "Ответь одним словом: какой цвет неба днём?"}])
    text = "".join(engine.stream_reply(messages))
    assert text.strip(), "модель вернула пустой ответ"
