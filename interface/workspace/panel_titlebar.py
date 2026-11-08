"""Заголовок плавающей панели: индикатор, название, место для статусов, кнопки «свернуть» и «закрыть».

Заголовок только сообщает о намерениях пользователя (перетаскивание, клики). Перемещением занимается панель.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QAbstractButton, QApplication, QHBoxLayout, QLabel, QWidget

from interface.styles import CYAN, TEXT_SECONDARY, WHITE

TITLEBAR_HEIGHT = 34


class StatusDot(QWidget):
    """Небольшой светящийся индикатор состояния."""

    def __init__(self, color: str = CYAN, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(14, 14)

    def set_color(self, color: str) -> None:
        c = QColor(color)
        if c != self._color:
            self._color = c
            self.update()

    def color(self) -> QColor:
        return QColor(self._color)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(self.width() / 2, self.height() / 2)
        glow = QRadialGradient(c, 7)
        halo = QColor(self._color)
        halo.setAlpha(90)
        glow.setColorAt(0.0, halo)
        halo.setAlpha(0)
        glow.setColorAt(1.0, halo)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, 7, 7)
        p.setBrush(self._color)
        p.drawEllipse(c, 3, 3)


class TitleButton(QAbstractButton):
    """Кнопка заголовка с векторной иконкой: minimize, restore или close."""

    def __init__(self, kind: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.kind = kind
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(QSize(24, 22))
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def set_kind(self, kind: str) -> None:
        if kind != self.kind:
            self.kind = kind
            self.update()

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        hover = self.underMouse()
        if hover:
            bg = QColor(255, 85, 85, 60) if self.kind == "close" else QColor(54, 191, 255, 40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)
        color = QColor(WHITE if hover else TEXT_SECONDARY)
        p.setPen(QPen(color, 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = self.width() / 2, self.height() / 2
        if self.kind == "minimize":
            p.drawLine(QPointF(cx - 5, cy + 3), QPointF(cx + 5, cy + 3))
        elif self.kind == "restore":
            p.drawRoundedRect(QRectF(cx - 5, cy - 4, 10, 8), 2, 2)
        else:
            p.drawLine(QPointF(cx - 4, cy - 4), QPointF(cx + 4, cy + 4))
            p.drawLine(QPointF(cx + 4, cy - 4), QPointF(cx - 4, cy + 4))


class PanelTitleBar(QWidget):
    collapse_clicked = Signal()
    close_clicked = Signal()
    double_clicked = Signal()
    drag_started = Signal(QPoint)   # глобальная позиция курсора
    drag_moved = Signal(QPoint)
    drag_finished = Signal()

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(TITLEBAR_HEIGHT)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self._press: QPoint | None = None
        self._dragging = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 0, 2, 0)
        layout.setSpacing(6)
        self.dot = StatusDot(CYAN, self)
        layout.addWidget(self.dot)
        self.title = QLabel(title.upper(), self)
        self.title.setObjectName("panelTitle")
        layout.addWidget(self.title)
        self.extra = QHBoxLayout()  # место для индикаторов и кнопок конкретной панели
        self.extra.setSpacing(6)
        layout.addLayout(self.extra)
        layout.addStretch(1)
        self.collapse_btn = TitleButton("minimize", "Свернуть", self)
        self.collapse_btn.clicked.connect(self.collapse_clicked.emit)
        layout.addWidget(self.collapse_btn)
        self.close_btn = TitleButton("close", "Закрыть", self)
        self.close_btn.clicked.connect(self.close_clicked.emit)
        layout.addWidget(self.close_btn)

    def set_active(self, active: bool) -> None:
        self.title.setProperty("active", "true" if active else "false")
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)

    def set_collapsed(self, collapsed: bool) -> None:
        self.collapse_btn.set_kind("restore" if collapsed else "minimize")
        self.collapse_btn.setToolTip("Развернуть" if collapsed else "Свернуть")

    def add_widget(self, widget: QWidget) -> None:
        self.extra.addWidget(widget)

    # --- перетаскивание -----------------------------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._dragging = False
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._press is None:
            return super().mouseMoveEvent(event)
        pos = event.globalPosition().toPoint()
        if not self._dragging:
            # небольшой порог: случайное дрожание руки при клике не сдвигает панель
            if (pos - self._press).manhattanLength() < QApplication.startDragDistance():
                return
            self._dragging = True
            self.drag_started.emit(self._press)
        self.drag_moved.emit(pos)
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._press is not None:
            was_dragging = self._dragging
            self._press = None
            self._dragging = False
            if was_dragging:
                self.drag_finished.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)
