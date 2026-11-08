"""Сохранение компоновки рабочего пространства в settings.json и совместимость со старыми настройками."""

from __future__ import annotations

import json

import pytest
from PySide6.QtWidgets import QMessageBox

from interface.workspace.panel_layout import Rect
from storage.settings_storage import DEFAULT_SETTINGS, SettingsStorage

OLD_V011_SETTINGS = {
    "ollama_url": "http://localhost:11434",
    "model_name": "qwen3:8b-q4_K_M",
    "voice_enabled": False,
    "voice_model_path": "resources/voices/ru_RU-irina-medium.onnx",
    "voice_volume": 70,
    "voice_speed": 1.1,
    "window_width": 1280,
    "window_height": 730,
}


def test_old_settings_file_gets_workspace_default(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps(OLD_V011_SETTINGS), encoding="utf-8")
    settings = SettingsStorage(path).load()
    assert settings["voice_volume"] == 70             # старые значения сохранены
    assert settings["workspace"] == {}                 # новое значение — по умолчанию


def test_broken_workspace_value_falls_back(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({**OLD_V011_SETTINGS, "workspace": "broken"}), encoding="utf-8")
    assert SettingsStorage(path).load()["workspace"] == {}


def test_defaults_are_not_shared_between_loads(tmp_path):
    store = SettingsStorage(tmp_path / "settings.json")
    first = store.load()
    first["workspace"]["panels"] = {"chat": {}}
    assert store.load()["workspace"] == {}
    assert DEFAULT_SETTINGS["workspace"] == {}


def _window(tmp_path, monkeypatch):
    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    win.canvas.resize(1200, 640)   # окно в тестах не показывается: задаём размер области явно
    return win


@pytest.fixture
def settings_path(tmp_path):
    return tmp_path / "storage" / "settings.json"


def test_first_start_uses_default_layout(qt_app, tmp_path, monkeypatch):
    win = _window(tmp_path, monkeypatch)
    try:
        assert win.workspace.open_ids() == ["chat", "system"]
    finally:
        win.close()


def test_layout_survives_restart(qt_app, tmp_path, monkeypatch, settings_path):
    win = _window(tmp_path, monkeypatch)
    win.workspace.open("logs")
    logs = win.workspace.panel("logs")
    logs.apply_rect(Rect(200, 100, 420, 260))
    logs.geometry_committed.emit("logs")
    win.workspace.close("system")
    win.workspace.set_collapsed("chat", True)
    win.workspace.activate("logs")
    win.close()

    saved = json.loads(settings_path.read_text(encoding="utf-8"))["workspace"]
    assert saved["panels"]["logs"]["visible"] is True
    assert saved["panels"]["logs"]["rect"] == [200, 100, 420, 260]
    assert saved["panels"]["system"]["visible"] is False
    assert saved["panels"]["chat"]["collapsed"] is True
    assert saved["active"] == "logs"
    assert saved["z_order"][-1] == "logs"

    win2 = _window(tmp_path, monkeypatch)
    try:
        assert set(win2.workspace.open_ids()) == {"chat", "logs"}
        assert win2.workspace.panel("logs").rect_now() == Rect(200, 100, 420, 260)
        assert win2.workspace.is_collapsed("chat")
        assert win2.workspace.active_panel == "logs"
    finally:
        win2.close()


def test_offscreen_saved_layout_is_fixed(qt_app, tmp_path, monkeypatch, settings_path):
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(json.dumps({**OLD_V011_SETTINGS, "workspace": {
        "panels": {"code": {"rect": [9000, 9000, 500, 400], "canvas": [10000, 10000], "visible": True}},
    }}), encoding="utf-8")
    win = _window(tmp_path, monkeypatch)
    try:
        rect = win.workspace.panel("code").rect_now()
        assert 0 <= rect.x and rect.right <= win.canvas.width()
        assert 0 <= rect.y and rect.bottom <= win.canvas.height()
    finally:
        win.close()


def test_settings_dialog_does_not_overwrite_layout(qt_app, tmp_path, monkeypatch, settings_path):
    """Окно настроек держит копию настроек; её сохранение не должно затирать новое расположение панелей."""
    win = _window(tmp_path, monkeypatch)
    try:
        stale = dict(win.settings)              # как SettingsDialog.values(): снимок до изменений
        win.workspace.open("terminal")
        win._apply_settings(stale)
        saved = json.loads(settings_path.read_text(encoding="utf-8"))["workspace"]
        assert saved["panels"]["terminal"]["visible"] is True
    finally:
        win.close()


def test_layout_change_is_saved_without_closing(qt_app, tmp_path, monkeypatch, settings_path):
    import time

    win = _window(tmp_path, monkeypatch)
    win._layout_save_timer.setInterval(50)
    try:
        win.workspace.open("code")
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            qt_app.processEvents()
            if settings_path.exists():
                data = json.loads(settings_path.read_text(encoding="utf-8"))
                if data.get("workspace", {}).get("panels", {}).get("code", {}).get("visible"):
                    break
            time.sleep(0.02)
        else:
            pytest.fail("компоновка не сохранена после изменения")
    finally:
        win.close()


def test_reset_from_settings_dialog(qt_app, tmp_path, monkeypatch):
    from interface.settings_panel import SettingsDialog

    win = _window(tmp_path, monkeypatch)
    try:
        win.workspace.open("logs")
        win.workspace.close("chat")
        monkeypatch.setattr(SettingsDialog, "exec", lambda self: (self._reset_interface(),
                                                                  SettingsDialog.DialogCode.Accepted)[1])
        win._open_settings()
        assert win.workspace.open_ids() == ["chat", "system"]
    finally:
        win.close()
