"""Общие настройки тестов: путь к проекту и одно Qt-приложение на сессию (без окна)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Окна и мультимедиа в тестах работают без экрана
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


@pytest.fixture(scope="session")
def qt_app():
    """Одно Qt-приложение на сессию тестов: нужно для сигналов и виджетов."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def pytest_configure(config):
    config.addinivalue_line("markers", "model_memory: тест сам проверяет загрузку и выгрузку модели")


@pytest.fixture(autouse=True)
def _no_real_model_loading(request, monkeypatch):
    """Окно при запуске загружает Qwen в видеопамять, а при закрытии выгружает её.

    В тестах это заглушено: иначе каждый тест окна грузил бы настоящую модель (секунды и гигабайты)
    и выгружал модель, которой пользователь пользуется прямо сейчас.
    """
    if request.node.get_closest_marker("model_memory"):
        return
    from core.model_manager import ModelManager

    monkeypatch.setattr(ModelManager, "preload", lambda self, num_ctx, timeout=180.0: 0.0)
    monkeypatch.setattr(ModelManager, "unload", lambda self, timeout=3.0: True)


@pytest.fixture(autouse=True)
def _no_real_autostart(monkeypatch):
    """Тесты не меняют автозапуск Windows (реестр пользователя)."""
    from core.autostart import Autostart

    monkeypatch.setattr(Autostart, "is_enabled", lambda self: False)
    monkeypatch.setattr(Autostart, "set_enabled", lambda self, enabled: True)
