"""Запуск: модель загружается в видеопамять при старте, выгружается при закрытии; экран загрузки."""

from __future__ import annotations

import threading
import time

import pytest
import requests

from core.ai_engine import KEEP_ALIVE
from core.model_manager import ModelManager, OllamaStatus, StatusInfo
from interface.workers import BOOT_STAGES, BootWorker, _run_cancellable


def _pump(qt_app, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


class FakeResponse:
    def raise_for_status(self):
        pass


@pytest.mark.model_memory
def test_preload_uses_same_context_and_keep_alive(monkeypatch):
    sent = {}
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: sent.update(url=url, **json) or FakeResponse())
    ModelManager("http://127.0.0.1:11434", "qwen3:8b-q4_K_M").preload(num_ctx=4096)
    assert sent["url"].endswith("/api/chat") and sent["messages"] == []
    assert sent["options"]["num_ctx"] == 4096 and sent["keep_alive"] == KEEP_ALIVE


@pytest.mark.model_memory
def test_unload_sets_keep_alive_zero_and_never_raises(monkeypatch):
    sent = {}
    monkeypatch.setattr(requests, "post", lambda url, json=None, timeout=None: sent.update(json) or FakeResponse())
    assert ModelManager("http://127.0.0.1:11434", "m").unload() is True
    assert sent["keep_alive"] == 0

    def boom(*a, **k):
        raise requests.ConnectionError("нет связи")

    monkeypatch.setattr(requests, "post", boom)
    assert ModelManager("http://127.0.0.1:11434", "m").unload() is False


def test_chat_requests_keep_model_loaded():
    from core.ai_engine import AIEngine
    import inspect

    assert "KEEP_ALIVE" in inspect.getsource(AIEngine.stream_reply)


def test_run_cancellable_stops_waiting():
    cancel = threading.Event()
    cancel.set()
    done, result, error = _run_cancellable(lambda: time.sleep(5), cancel)
    assert not done
    assert _run_cancellable(lambda: 7, threading.Event()) == (True, 7, None)


class FakeManager:
    model_name = "qwen-fake"

    def __init__(self, api=True, model=True, preload_error=None):
        self.api, self.model, self.preload_error = api, model, preload_error
        self.preloaded = []

    def is_api_available(self):
        return self.api

    def find_executable(self):
        return None

    def check_status(self):
        if not self.api:
            return StatusInfo(OllamaStatus.NOT_RUNNING, "Ollama не запущена")
        if not self.model:
            return StatusInfo(OllamaStatus.NO_MODEL, "нет модели")
        return StatusInfo(OllamaStatus.READY, "готова")

    def preload(self, num_ctx):
        if self.preload_error:
            raise self.preload_error
        self.preloaded.append(num_ctx)
        return 1.5


def _run_boot(qt_app, manager, voice=None):
    worker = BootWorker(manager, 4096, voice)
    stages, statuses = [], []
    worker.stage.connect(lambda k, s, d: stages.append((k, s, d)))
    worker.status.connect(statuses.append)
    worker.start()
    assert _pump(qt_app, lambda: statuses)
    worker.wait(3000)
    return dict((k, (s, d)) for k, s, d in stages), statuses[0]


def test_boot_loads_model_and_voice(qt_app):
    manager = FakeManager()
    final, info = _run_boot(qt_app, manager, voice=lambda: "Silero xenia")
    assert info.status == OllamaStatus.READY and manager.preloaded == [4096]
    assert final["ollama"][0] == "ok" and final["vram"] == ("ok", "1.5 с")
    assert final["voice"] == ("ok", "Silero xenia")


def test_boot_without_ollama_skips_model(qt_app):
    final, info = _run_boot(qt_app, FakeManager(api=False))
    assert info.status == OllamaStatus.NOT_INSTALLED
    assert final["ollama"][0] == "fail" and final["vram"][0] == "skip" and final["voice"][0] == "skip"


def test_boot_preload_failure_is_not_fatal(qt_app):
    from core.ai_engine import OllamaError

    final, info = _run_boot(qt_app, FakeManager(preload_error=OllamaError("мало памяти")))
    assert info.status == OllamaStatus.READY and final["vram"][0] == "fail"


def test_overlay_progress_and_dismiss(qt_app):
    from PySide6.QtWidgets import QWidget

    from interface.boot_overlay import BootOverlay

    host = QWidget()
    host.resize(1000, 700)
    host.show()
    overlay = BootOverlay(BOOT_STAGES, host)
    overlay.start()
    assert overlay.geometry() == host.rect() and overlay.progress() == 0
    overlay.set_stage("ollama", "ok")
    overlay.set_stage("model", "run")
    assert overlay.progress() == pytest.approx(1.5 / 4)
    overlay.grab()                         # отрисовка без ошибок
    closed = []
    overlay.finished.connect(lambda: closed.append(True))
    overlay.finish()
    assert overlay.stage_state("vram") == "skip"
    assert _pump(qt_app, lambda: closed, timeout=5)
    host.close()


def test_window_shows_overlay_and_unloads_on_close(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    unloaded = []
    monkeypatch.setattr(ModelManager, "unload", lambda self, timeout=3.0: unloaded.append(self.model_name) or True)
    win = MainWindow(tmp_path)
    win.show()
    assert win._boot_overlay is not None and win._boot_overlay.isVisible()
    assert _pump(qt_app, lambda: not win._boot_running(), timeout=30)
    assert _pump(qt_app, lambda: win._boot_overlay is None, timeout=10)
    win.close()
    assert unloaded == ["qwen3:8b-q4_K_M"]
