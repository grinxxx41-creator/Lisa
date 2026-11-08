"""Поведение окна: остановка ответа не сохраняет его, закрытие завершает фоновые задачи."""

from __future__ import annotations

import time

import pytest
from PySide6.QtWidgets import QMessageBox


class SlowEngine:
    """Заглушка модели: медленно выдаёт много фрагментов и уважает остановку."""

    model_name = "slow-fake"
    base_url = "http://localhost:11434"

    def stream_reply(self, messages, cancel_event=None, max_tokens=None, on_response=None):
        for i in range(400):
            if cancel_event is not None and cancel_event.is_set():
                return
            time.sleep(0.05)
            yield f"слово{i} "


def _pump(qt_app, predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from interface.main_window import MainWindow

    # модальные окна не должны ждать ответа пользователя в тестах
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    win.engine = SlowEngine()
    yield win
    if win.isVisible():
        win.close()


def _partial_text_visible(win) -> bool:
    return win._assistant_card is not None and win._assistant_card.text.strip() != ""


def test_startup_opens_new_empty_chat(window):
    assert window._current_chat_id is not None
    chat = window.chats.load_chat(window._current_chat_id)
    assert chat is not None and chat["messages"] == []
    window.close()


def test_stopped_reply_is_not_saved(window, qt_app):
    window._on_send("Расскажи длинную историю")
    assert _pump(qt_app, lambda: _partial_text_visible(window))
    window._on_stop_generation()
    assert _pump(qt_app, lambda: not window._generating)
    chat = window.chats.load_chat(window._current_chat_id)
    assert [m["role"] for m in chat["messages"]] == ["user"]
    window.close()


def test_close_during_generation_stops_worker_quickly(window, qt_app):
    window._on_send("Расскажи длинную историю")
    assert _pump(qt_app, lambda: _partial_text_visible(window))
    worker = window._worker
    started = time.monotonic()
    window.close()
    assert worker is not None
    assert not worker.isRunning()
    assert time.monotonic() - started < 3
    chat = window.chats.load_chat(window._current_chat_id)
    assert [m["role"] for m in chat["messages"]] == ["user"]
