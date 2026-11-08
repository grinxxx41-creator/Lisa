"""Новый вид: LISA по изображению, фон-город, прозрачные панели."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import QVBoxLayout

from interface.avatar_widget import AvatarState, AvatarWidget
from interface.workspace.backdrop import WorkspaceBackdrop, render_city
from interface.workspace.floating_panel import GLASS_ALPHA_BOTTOM, GLASS_ALPHA_TOP
from interface.workspace.workspace_canvas import WorkspaceCanvas

LISA_PNG = Path(__file__).resolve().parent.parent / "resources" / "images" / "lisa.png"
needs_image = pytest.mark.skipif(not LISA_PNG.exists(), reason="нет resources/images/lisa.png")


@needs_image
def test_image_avatar_renders_every_state(qt_app):
    avatar = AvatarWidget(LISA_PNG)
    avatar.resize(420, 640)
    assert avatar.has_image
    images = {}
    for state in AvatarState:
        avatar.set_state(state)
        pix = QPixmap(avatar.size())
        pix.fill(QColor(0, 0, 0))
        avatar.render(pix)
        images[state] = pix.toImage()
    # состояния различаются: цвет пикселя в центре фигуры не одинаков для IDLE, THINKING и ERROR
    center = (210, 380)
    colors = {images[s].pixelColor(*center).name() for s in (AvatarState.IDLE, AvatarState.THINKING, AvatarState.ERROR)}
    assert len(colors) == 3


@needs_image
def test_image_keeps_aspect_and_stands_at_bottom(qt_app):
    avatar = AvatarWidget(LISA_PNG)
    source = QPixmap(str(LISA_PNG))
    for size in ((300, 700), (900, 500)):
        rect = avatar.image_rect(*size)
        assert rect.width() / rect.height() == pytest.approx(source.width() / source.height(), rel=0.01)
        assert rect.bottom() == pytest.approx(size[1], abs=1)
        assert rect.left() >= 0 and rect.right() <= size[0]


@needs_image
def test_image_avatar_frame_is_cheap(qt_app):
    avatar = AvatarWidget(LISA_PNG)
    avatar.resize(570, 910)
    avatar.set_state(AvatarState.SPEAKING)
    pix = QPixmap(avatar.size())
    avatar.render(pix)  # первый кадр готовит кэш
    started = time.perf_counter()
    for _ in range(20):
        avatar._phase += 0.1
        avatar.render(pix)
    assert (time.perf_counter() - started) / 20 < 0.015   # кадр дешевле 15 мс


def test_missing_image_falls_back_to_vector_hologram(qt_app, tmp_path):
    avatar = AvatarWidget(tmp_path / "nope.png")
    assert not avatar.has_image
    avatar.resize(300, 400)
    assert not avatar.grab().isNull()


def test_city_backdrop_is_deterministic_and_hidpi(qt_app):
    a = render_city(400, 300, 1.0).toImage()
    b = render_city(400, 300, 1.0).toImage()
    assert a == b
    hi = render_city(400, 300, 2.0)
    assert (hi.width(), hi.height()) == (800, 600)
    assert hi.devicePixelRatio() == 2.0
    # не чёрный прямоугольник: в небе есть цвет
    assert a.pixelColor(200, 120).blue() > 15


def test_panels_are_glass(qt_app):
    assert GLASS_ALPHA_TOP < 160 and GLASS_ALPHA_BOTTOM < 180


def test_canvas_takes_background_from_backdrop(qt_app):
    backdrop = WorkspaceBackdrop()
    layout = QVBoxLayout(backdrop)
    layout.setContentsMargins(0, 50, 0, 0)
    canvas = WorkspaceCanvas()
    layout.addWidget(canvas)
    canvas.set_backdrop(backdrop)
    backdrop.resize(500, 400)
    backdrop.show()
    qt_app.processEvents()
    out = QPixmap(100, 100)
    p = QPainter(out)
    canvas.paint_background(p, QRectF(0, 0, 100, 100), QRectF(10, 10, 100, 100))
    p.end()
    expected = backdrop.pixmap().toImage().pixelColor(60, 110)  # смещение области: 10 + 50 по вертикали
    got = out.toImage().pixelColor(50, 50)
    assert abs(got.blue() - expected.blue()) <= 3 and abs(got.red() - expected.red()) <= 3
    backdrop.close()


def test_window_uses_city_backdrop(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    try:
        assert isinstance(win.centralWidget(), WorkspaceBackdrop)
        assert win.canvas._backdrop is win.centralWidget()
    finally:
        win.close()
