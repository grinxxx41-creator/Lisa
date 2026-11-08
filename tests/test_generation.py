"""Остановка генерации: закрытие HTTP-потока, сигнал stopped, отсутствие ошибок при остановке."""

from __future__ import annotations

import json
import threading
import time

import pytest
import requests

from core.ai_engine import AIEngine
from core.model_manager import ModelManager
from interface.workers import GenerationWorker
from storage.settings_storage import DEFAULT_SETTINGS


class FakeResponse:
    """Ответ Ollama: отдаёт первую строку, дальше «блокирует» чтение, как сеть."""

    def __init__(self, first_line: str) -> None:
        self.status_code = 200
        self._first = first_line
        self._closed = threading.Event()
        self.close_calls = 0

    def iter_lines(self, decode_unicode=True):
        yield self._first
        self._closed.wait(5)
        raise requests.exceptions.ChunkedEncodingError("соединение закрыто")

    def close(self) -> None:
        self.close_calls += 1
        self._closed.set()


def _chunk(text: str, done: bool = False) -> str:
    return json.dumps({"message": {"role": "assistant", "content": text}, "done": done})


def test_cancel_during_stream_ends_quickly_without_error(monkeypatch):
    response = FakeResponse(_chunk("Первый "))
    monkeypatch.setattr(requests, "post", lambda *a, **k: response)
    engine = AIEngine("http://localhost:11434", "fake-model")
    cancel = threading.Event()
    got: list[str] = []
    errors: list[BaseException] = []

    def consume() -> None:
        try:
            for piece in engine.stream_reply([], cancel, on_response=lambda r: None):
                got.append(piece)
                cancel.set()        # остановка сразу после первого фрагмента
                response.close()
        except BaseException as exc:  # noqa: BLE001 — проверяем, что исключения нет
            errors.append(exc)

    thread = threading.Thread(target=consume)
    started = time.monotonic()
    thread.start()
    thread.join(3)
    assert not thread.is_alive()
    assert time.monotonic() - started < 2
    assert got == ["Первый "]
    assert errors == []


def test_worker_emits_stopped_with_partial_text_and_not_finished(qt_app):
    class Engine:
        def stream_reply(self, messages, cancel_event=None, max_tokens=None, on_response=None):
            for i, piece in enumerate(["Один ", "два ", "три"]):
                if cancel_event is not None and cancel_event.is_set():
                    return
                yield piece
                if i == 1:
                    worker.stop()  # пользователь нажал «Стоп» во время ответа

    engine = Engine()
    worker = GenerationWorker(engine, [], None)
    finished: list[str] = []
    stopped: list[str] = []
    failed: list[str] = []
    worker.finished_ok.connect(finished.append)
    worker.stopped.connect(stopped.append)
    worker.failed.connect(failed.append)
    worker.run()
    assert stopped == ["Один два "]
    assert finished == []
    assert failed == []


def test_response_received_after_stop_is_closed_immediately(qt_app):
    response = FakeResponse(_chunk("x"))

    class Engine:
        def stream_reply(self, messages, cancel_event=None, max_tokens=None, on_response=None):
            worker.stop()        # остановка пришла раньше, чем открылся поток
            on_response(response)
            return iter(())

    worker = GenerationWorker(Engine(), [], None)
    worker.run()
    assert response.close_calls >= 1


def test_normal_completion_emits_finished_ok(qt_app):
    class Engine:
        def stream_reply(self, messages, cancel_event=None, max_tokens=None, on_response=None):
            yield from ["Готово", "."]

    worker = GenerationWorker(Engine(), [], None)
    finished: list[str] = []
    stopped: list[str] = []
    worker.finished_ok.connect(finished.append)
    worker.stopped.connect(stopped.append)
    worker.run()
    assert finished == ["Готово."]
    assert stopped == []


@pytest.mark.skipif(
    not ModelManager(DEFAULT_SETTINGS["ollama_url"], DEFAULT_SETTINGS["model_name"]).is_api_available(),
    reason="Ollama не запущена на localhost:11434",
)
def test_real_model_stops_within_two_seconds_after_first_token():
    engine = AIEngine(DEFAULT_SETTINGS["ollama_url"], DEFAULT_SETTINGS["model_name"])
    cancel = threading.Event()
    holder: dict = {}
    tokens: list[str] = []

    def on_response(response) -> None:
        holder["response"] = response

    def run() -> None:
        try:
            for piece in engine.stream_reply(
                [{"role": "user", "content": "Напиши подробный рассказ о Марсе, не менее трёхсот слов."}],
                cancel,
                on_response=on_response,
            ):
                tokens.append(piece)
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc
        holder["ended"] = time.monotonic()

    thread = threading.Thread(target=run)
    thread.start()
    deadline = time.monotonic() + 60
    while not tokens and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert tokens, "модель не вернула ни одного фрагмента"
    cancelled_at = time.monotonic()
    cancel.set()
    holder["response"].close()
    thread.join(10)
    assert not thread.is_alive()
    assert "error" not in holder
    assert holder["ended"] - cancelled_at < 2


def test_pull_cancel_closes_stream_and_reports_no_error(qt_app):
    from interface.workers import PullWorker

    response = FakeResponse(json.dumps({"status": "pulling manifest"}))

    class Manager:
        def pull_model(self, progress=None, cancel_event=None, on_response=None):
            on_response(response)
            try:
                for _line in response.iter_lines():
                    pass
            except requests.RequestException:
                if cancel_event is not None and cancel_event.is_set():
                    return  # загрузка отменена пользователем: это не ошибка
                raise

    worker = PullWorker(Manager(), None)
    failed: list[str] = []
    finished: list[int] = []
    worker.failed.connect(failed.append)
    worker.finished_ok.connect(lambda: finished.append(1))
    thread = threading.Thread(target=worker.run)
    thread.start()
    time.sleep(0.1)
    started = time.monotonic()
    worker.cancel()
    thread.join(3)
    assert not thread.is_alive()
    assert time.monotonic() - started < 2
    assert response.close_calls >= 1
    assert failed == []
    assert finished == []
