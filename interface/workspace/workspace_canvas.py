"""Рабочая область: аватар LISA в центре и тени плавающих панелей.

Сама область прозрачна: фон-город рисует WorkspaceBackdrop (центральный виджет окна), поэтому
город виден и под панелью управления. Панели рисуют под собой участок этого фона
(paint_background) и полупрозрачную заливку: они выглядят стеклянными, но не просвечивают
друг через друга. Без фона (например, в тестах) область заливается цветом BG.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from interface.styles import BG
from interface.workspace.floating_panel import RADIUS, SHADOW, FloatingPanel
from interface.workspace.panel_layout import avatar_rect


class WorkspaceCanvas(QWidget):
    resized = Signal(int, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceCanvas")
        self.setMinimumSize(560, 360)
        self._avatar: QWidget | None = None
        self._backdrop = None   # WorkspaceBackdrop: предок, который рисует фон окна

    def set_backdrop(self, backdrop) -> None:
        self._backdrop = backdrop
        self.update()

    def set_avatar(self, avatar: QWidget, visible: bool = True) -> None:
        """visible=False — тема без аватара в центре: виджет остаётся (состояния LISA), но скрыт."""
        self._avatar = avatar
        avatar.setParent(self)
        avatar.lower()
        self._place_avatar()
        avatar.setVisible(visible)

    def avatar(self) -> QWidget | None:
        return self._avatar

    def panels(self) -> list[FloatingPanel]:
        return [w for w in self.children() if isinstance(w, FloatingPanel)]

    def _place_avatar(self) -> None:
        if self._avatar is None:
            return
        r = avatar_rect(self.width(), self.height())
        self._avatar.setGeometry(r.x, r.y, r.w, r.h)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._place_avatar()
        self.resized.emit(self.width(), self.height())

    def paint_background(self, p: QPainter, target: QRectF, area: QRectF) -> None:
        """Рисует фон окна, который находится под прямоугольником area этой области."""
        backdrop = self._backdrop
        if backdrop is None or not backdrop.isAncestorOf(self):
            p.fillRect(target, QColor(BG))
            return
        offset = self.mapTo(backdrop, QPoint(0, 0))
        backdrop.paint_region(p, target, area.translated(offset.x(), offset.y()))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        clip = QRectF(event.rect())
        if self._backdrop is None:
            p.fillRect(clip, QColor(BG))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for panel in self.panels():
            if panel.isHidden():
                continue
            g = QRectF(panel.geometry())
            if not g.adjusted(-SHADOW, -SHADOW, SHADOW, SHADOW).intersects(clip):
                continue
            # мягкая тень из нескольких полупрозрачных слоёв (дешевле QGraphicsDropShadowEffect)
            for k, alpha in ((14, 12), (9, 18), (5, 26), (2, 36)):
                p.setBrush(QColor(0, 0, 0, alpha))
                p.drawRoundedRect(g.adjusted(-k, -k + 4, k, k + 4), RADIUS + k, RADIUS + k)
        p.end()
