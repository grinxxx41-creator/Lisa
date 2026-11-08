"""Система плавающих панелей: создание, повторное открытие, закрытие, перемещение, размеры, компоновка."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel, QWidget

from interface.workspace.floating_panel import FloatingPanel
from interface.workspace.panel_layout import COLLAPSED_HEIGHT, PANEL_IDS, Rect
from interface.workspace.panel_registry import PanelRegistry, PanelSpec
from interface.workspace.workspace_canvas import WorkspaceCanvas
from interface.workspace.workspace_manager import WorkspaceManager


class TrackedContent(QLabel):
    def __init__(self, text: str) -> None:
        super().__init__(text)
        self.events: list[str] = []

    def panel_shown(self) -> None:
        self.events.append("shown")

    def panel_hidden(self) -> None:
        self.events.append("hidden")


@pytest.fixture
def workspace(qt_app):
    canvas = WorkspaceCanvas()
    canvas.resize(1280, 640)
    canvas.show()  # скрытый виджет не получает resizeEvent
    registry = PanelRegistry()
    created: dict[str, list[QWidget]] = {}

    def factory(pid):
        def make():
            widget = TrackedContent(pid)
            created.setdefault(pid, []).append(widget)
            return widget
        return make

    for pid in PANEL_IDS:
        registry.register(PanelSpec(pid, pid.upper(), factory(pid), (320, 200)))
    manager = WorkspaceManager(canvas, registry)
    canvas.set_avatar(QWidget())
    yield canvas, manager, created
    canvas.deleteLater()


def _panels(canvas):
    return canvas.findChildren(FloatingPanel)


def test_open_creates_visible_panel(workspace):
    canvas, manager, created = workspace
    panel = manager.open("code")
    assert manager.is_open("code")
    assert panel.parentWidget() is canvas  # дочерний виджет, а не отдельное окно
    assert not panel.isWindow()
    assert manager.active_panel == "code"
    assert created["code"][0].events == ["shown"]


def test_reopen_does_not_create_copy(workspace):
    canvas, manager, created = workspace
    first = manager.open("logs")
    second = manager.open("logs")
    manager.toggle("logs")
    manager.toggle("logs")
    assert first is second
    assert len(created["logs"]) == 1
    assert len([p for p in _panels(canvas) if p.panel_id == "logs"]) == 1


def test_close_hides_and_reopen_restores_same_panel(workspace):
    canvas, manager, created = workspace
    panel = manager.open("terminal")
    manager.close("terminal")
    assert not manager.is_open("terminal")
    assert panel.isHidden()
    assert created["terminal"][0].events == ["shown", "hidden"]
    assert manager.open("terminal") is panel


def test_close_button_closes_panel(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("system")
    panel.titlebar.close_btn.click()
    assert not manager.is_open("system")


def test_drag_by_title_moves_panel(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("code")
    panel.apply_rect(Rect(100, 100, 400, 300))
    bar = panel.titlebar
    start = QPoint(60, 15)
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start)
    QTest.mouseMove(bar, start + QPoint(30, 20))
    # QTest задаёт точку в координатах заголовка, который уже сдвинулся на (30, 20):
    # курсор на экране в итоге смещён на (80, 50) от точки нажатия
    QTest.mouseMove(bar, start + QPoint(50, 30))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, start + QPoint(50, 30))
    assert (panel.x(), panel.y()) == (180, 150)
    assert (panel.width(), panel.height()) == (400, 300)


def test_tiny_mouse_jitter_does_not_move_panel(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("code")
    panel.apply_rect(Rect(100, 100, 400, 300))
    QTest.mousePress(panel.titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 15))
    QTest.mouseMove(panel.titlebar, QPoint(61, 16))
    QTest.mouseRelease(panel.titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(61, 16))
    assert (panel.x(), panel.y()) == (100, 100)


def test_move_outside_is_clamped(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("code")
    panel.apply_rect(Rect(100, 100, 400, 300))
    panel.move_to(-500, 5000)
    assert panel.x() == 0
    assert panel.geometry().bottom() + 1 == canvas.height()


def test_resize_respects_minimum_and_bounds(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("code")
    panel.apply_rect(Rect(100, 100, 400, 300))
    panel.resize_by_edges(2 | 4, -1000, -1000)       # правый и нижний края внутрь
    assert (panel.width(), panel.height()) == (320, 200)
    panel.resize_by_edges(2 | 4, 5000, 5000)         # наружу — до границы области
    assert panel.geometry().right() + 1 == canvas.width()
    assert panel.geometry().bottom() + 1 == canvas.height()
    panel.apply_rect(Rect(300, 100, 400, 300))
    panel.resize_by_edges(1, 1000, 0)                # левый край не переходит минимальную ширину
    assert panel.width() == 320 and panel.geometry().right() + 1 == 700


def test_resize_by_mouse_on_corner(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("code")
    panel.apply_rect(Rect(100, 100, 400, 300))
    corner = QPoint(398, 298)
    QTest.mousePress(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, corner)
    QTest.mouseMove(panel, corner + QPoint(50, 40))
    QTest.mouseRelease(panel, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, corner + QPoint(50, 40))
    assert (panel.width(), panel.height()) == (450, 340)


def test_collapse_and_restore(workspace):
    canvas, manager, created = workspace
    panel = manager.open("logs")
    height = panel.height()
    panel.titlebar.collapse_btn.click()
    assert manager.is_collapsed("logs")
    assert panel.height() == COLLAPSED_HEIGHT
    assert created["logs"][0].isHidden()
    assert created["logs"][0].events[-1] == "hidden"
    QTest.mouseDClick(panel.titlebar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(60, 15))
    assert not manager.is_collapsed("logs")
    assert panel.height() == height
    assert created["logs"][0].events[-1] == "shown"


def test_activation_changes_z_order(workspace):
    canvas, manager, _ = workspace
    manager.open("code")
    manager.open("logs")
    assert manager.z_order[-1] == "logs"
    manager.activate("code")
    assert manager.z_order[-1] == "code"
    assert manager.active_panel == "code"
    assert manager.panel("code").is_active() and not manager.panel("logs").is_active()


def test_click_inside_content_activates_panel(workspace):
    canvas, manager, created = workspace
    manager.open("code")
    manager.open("logs")
    QTest.mouseClick(created["code"][0], Qt.MouseButton.LeftButton)
    assert manager.active_panel == "code"


def test_reset_layout_opens_only_main_panels(workspace):
    canvas, manager, _ = workspace
    for pid in PANEL_IDS:
        manager.open(pid)
    manager.panel("code").move_to(0, 0)
    manager.reset_layout()
    assert manager.open_ids() == ["chat", "system"]
    chat = manager.panel("chat")
    assert chat.geometry().right() + 1 == canvas.width() - 14  # CHAT справа


def test_hide_all(workspace):
    canvas, manager, _ = workspace
    manager.reset_layout()
    manager.hide_all()
    assert manager.open_ids() == []


def test_window_shrink_and_grow_keeps_panel_size(workspace):
    canvas, manager, _ = workspace
    panel = manager.open("code")
    panel.apply_rect(Rect(100, 100, 500, 400))
    panel.geometry_committed.emit("code")
    canvas.resize(700, 420)
    assert panel.geometry().right() < 700 and panel.geometry().bottom() < 420
    canvas.resize(1280, 640)
    assert (panel.width(), panel.height()) == (500, 400)


def test_right_panel_follows_right_edge_on_resize(workspace):
    canvas, manager, _ = workspace
    manager.reset_layout()
    chat = manager.panel("chat")
    canvas.resize(1900, 1000)
    assert chat.geometry().right() + 1 == 1900 - 14


def test_state_roundtrip_restores_layout(workspace, qt_app):
    canvas, manager, _ = workspace
    manager.reset_layout()
    manager.open("logs")
    logs = manager.panel("logs")
    logs.apply_rect(Rect(200, 120, 420, 260))
    logs.geometry_committed.emit("logs")
    manager.set_collapsed("system", True)
    manager.activate("chat")
    saved = manager.state()

    canvas2 = WorkspaceCanvas()
    canvas2.resize(1280, 640)
    canvas2.show()
    registry = PanelRegistry()
    for pid in PANEL_IDS:
        registry.register(PanelSpec(pid, pid.upper(), lambda p=pid: QLabel(p), (320, 200)))
    manager2 = WorkspaceManager(canvas2, registry)
    manager2.restore(saved)
    assert set(manager2.open_ids()) == {"chat", "system", "logs"}
    assert manager2.panel("logs").rect_now() == Rect(200, 120, 420, 260)
    assert manager2.is_collapsed("system")
    assert manager2.active_panel == "chat"
    assert manager2.z_order[-1] == "chat"
    canvas2.deleteLater()


def test_restore_offscreen_coordinates_are_fixed(workspace):
    canvas, manager, _ = workspace
    saved = {"panels": {"code": {"rect": [5000, -300, 600, 400], "canvas": [6000, 3000], "visible": True}}}
    manager.restore(saved)
    rect = manager.panel("code").rect_now()
    assert rect.x >= 0 and rect.y >= 0
    assert rect.right <= canvas.width() and rect.bottom <= canvas.height()


def test_restore_garbage_falls_back_to_default(workspace):
    canvas, manager, _ = workspace
    manager.restore({"panels": "broken"})
    assert manager.open_ids() == ["chat", "system"]
