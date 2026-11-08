"""Состояния аватара LISA: OFFLINE, приоритет состояний, частота кадров, тихая проверка Ollama."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from core.model_manager import OllamaStatus, StatusInfo
from interface.avatar_widget import AvatarState, AvatarWidget


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from interface.main_window import MainWindow

    asked: list[str] = []

    def fake_question(*args, **kwargs):
        asked.append(args[1] if len(args) > 1 else "")
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(QMessageBox, "question", staticmethod(fake_question))
    win = MainWindow(tmp_path)
    win.asked = asked
    yield win
    win.close()


def test_all_states_render(qt_app):
    avatar = AvatarWidget()
    avatar.resize(360, 420)
    for state in AvatarState:
        avatar.set_state(state)
        image = avatar.grab()
        assert not image.isNull()
    assert AvatarState.OFFLINE.value == "OFFLINE"


def test_calm_states_redraw_less_often(qt_app):
    avatar = AvatarWidget()
    avatar.set_state(AvatarState.SPEAKING)
    speaking = avatar.frame_interval()
    avatar.set_state(AvatarState.IDLE)
    idle = avatar.frame_interval()
    avatar.set_state(AvatarState.OFFLINE)
    offline = avatar.frame_interval()
    assert speaking < idle < offline


def test_offline_status_sets_offline_avatar(window):
    window._on_status(StatusInfo(OllamaStatus.NOT_RUNNING, "Ollama не запущена"))
    assert window.avatar.state == AvatarState.OFFLINE
    window._on_status(StatusInfo(OllamaStatus.READY, "Модель готова"))
    assert window.avatar.state == AvatarState.IDLE


def test_state_priority(window):
    window._offline = True
    window._generating = True
    window._refresh_avatar()
    assert window.avatar.state == AvatarState.THINKING
    window._speaking = True
    window._refresh_avatar()
    assert window.avatar.state == AvatarState.SPEAKING
    window._error_flag = True
    window._refresh_avatar()
    assert window.avatar.state == AvatarState.ERROR
    window._error_flag = window._speaking = window._generating = False
    window._user_stopped_voice = True
    window._refresh_avatar()
    assert window.avatar.state == AvatarState.OFFLINE


def test_quiet_check_never_asks_to_download_model(window):
    window._on_status(StatusInfo(OllamaStatus.NO_MODEL, "Модель не загружена"), quiet=True)
    assert window.asked == []
    window._on_status(StatusInfo(OllamaStatus.NO_MODEL, "Модель не загружена"), quiet=False)
    assert window.asked == ["Модель не найдена"]


def test_chat_panel_status_indicator_follows_ollama(window):
    from interface.styles import ERROR, SUCCESS

    window._on_status(StatusInfo(OllamaStatus.NOT_RUNNING, "Ollama не запущена"))
    assert window.workspace.panel("chat").titlebar.dot.color().name().upper() == ERROR.upper()
    window._on_status(StatusInfo(OllamaStatus.READY, "Модель готова"))
    assert window.workspace.panel("chat").titlebar.dot.color().name().upper() == SUCCESS.upper()
