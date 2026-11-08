"""Плавающая панель рабочего пространства: дочерний виджет WorkspaceCanvas, а не отдельное окно Windows.

Панель перемещается за заголовок, меняет размер за левый, правый и нижний края и углы,
сворачивается до заголовка и не может уйти за пределы рабочей области.
Решения о расположении (где панель стоит по умолчанию, что сохранять) принимает WorkspaceManager.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QLayout, QVBoxLayout, QWidget

from interface.workspace.panel_layout import COLLAPSED_HEIGHT, Rect, clamp_rect
from interface.workspace.panel_titlebar import PanelTitleBar

RESIZE_MARGIN = 6     # ширина зоны изменения размера у краёв
CORNER = 16           # размер угловой зоны
RADIUS = 12
SHADOW = 18           # насколько тень выходит за границы панели (рисует WorkspaceCanvas)
GLASS_ALPHA_TOP = 120     # прозрачность «стекла» панели поверх фона-города (0 — прозрачно, 255 — сплошное)
GLASS_ALPHA_BOTTOM = 150

_LEFT, _RIGHT, _BOTTOM = 1, 2, 4


class FloatingPanel(QFrame):
    activated = Signal(str)             # пользователь нажал на панель
    close_requested = Signal(str)
    collapse_requested = Signal(str)    # кнопка или двойной клик по заголовку
    geometry_committed = Signal(str)    # перемещение или изменение размера закончено

    def __init__(self, panel_id: str, title: str, min_size: tuple[int, int] = (320, 200),
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.panel_id = panel_id
        self.min_w, self.min_h = min_size
        self._active = False
        self._collapsed = False
        self._content: QWidget | None = None
        self._drag_origin: QPoint | None = None
        self._drag_press: QPoint | None = None
        self._resize_edges = 0
        self._resize_press: QPoint | None = None
        self._resize_start: QRect | None = None

        self.setObjectName("floatingPanel")
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, False)

        self._layout = QVBoxLayout(self)
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self._layout.setContentsMargins(RESIZE_MARGIN, 0, RESIZE_MARGIN, RESIZE_MARGIN)
        self._layout.setSpacing(4)
        self.titlebar = PanelTitleBar(title, self)
        self._layout.addWidget(self.titlebar)

        self.titlebar.drag_started.connect(self._on_drag_started)
        self.titlebar.drag_moved.connect(self._on_drag_moved)
        self.titlebar.drag_finished.connect(self._on_drag_finished)
        self.titlebar.collapse_clicked.connect(lambda: self.collapse_requested.emit(self.panel_id))
        self.titlebar.double_clicked.connect(lambda: self.collapse_requested.emit(self.panel_id))
        self.titlebar.close_clicked.connect(lambda: self.close_requested.emit(self.panel_id))
        self._watch(self.titlebar)

    # --- содержимое ---------------------------------------------------------

    def set_content(self, widget: QWidget) -> None:
        if self._content is not None:
            self._layout.removeWidget(self._content)
        self._content = widget
        widget.setParent(self)
        self._layout.addWidget(widget, 1)
        widget.setVisible(not self._collapsed)
        self._watch(widget)

    def content(self) -> QWidget | None:
        return self._content

    def _watch(self, widget: QWidget) -> None:
        """Нажатие в любом месте панели делает её активной: следим за всеми вложенными виджетами."""
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        etype = event.type()
        if etype == QEvent.Type.MouseButtonPress:
            self.activated.emit(self.panel_id)
        elif etype == QEvent.Type.ChildAdded:
            child = event.child()
            if isinstance(child, QWidget):
                self._watch(child)
        return False

    # --- состояние ----------------------------------------------------------

    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.titlebar.set_active(active)
            self.update()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_collapsed(self, collapsed: bool) -> None:
        """Сворачивает панель до заголовка. Высоту до сворачивания помнит WorkspaceManager."""
        self._collapsed = collapsed
        if self._content is not None:
            self._content.setVisible(not collapsed)
        self.titlebar.set_collapsed(collapsed)
        self.setMouseTracking(not collapsed)

    def set_status(self, color: str, tooltip: str = "") -> None:
        self.titlebar.dot.set_color(color)
        self.titlebar.dot.setToolTip(tooltip)

    # --- геометрия ----------------------------------------------------------

    def _area(self) -> tuple[int, int]:
        parent = self.parentWidget()
        if parent is None:
            return self.width(), self.height()
        return parent.width(), parent.height()

    def current_min_size(self) -> tuple[int, int]:
        return (self.min_w, COLLAPSED_HEIGHT) if self._collapsed else (self.min_w, self.min_h)

    def apply_rect(self, rect: Rect) -> Rect:
        """Ставит панель в прямоугольник, вписанный в рабочую область. Возвращает итоговый прямоугольник."""
        area_w, area_h = self._area()
        min_w, min_h = self.current_min_size()
        if self._collapsed:
            rect = Rect(rect.x, rect.y, rect.w, COLLAPSED_HEIGHT)
        fixed = clamp_rect(rect, area_w, area_h, min_w, min_h)
        self.setGeometry(fixed.x, fixed.y, fixed.w, fixed.h)
        return fixed

    def rect_now(self) -> Rect:
        g = self.geometry()
        return Rect(g.x(), g.y(), g.width(), g.height())

    def move_to(self, x: int, y: int) -> None:
        self.apply_rect(Rect(x, y, self.width(), self.height()))

    def resize_by_edges(self, edges: int, dx: int, dy: int, start: QRect | None = None) -> None:
        """Изменяет размер, двигая указанные края. Левый край сдвигает панель, правый остаётся на месте."""
        g = start or self.geometry()
        x, y, w, h = g.x(), g.y(), g.width(), g.height()
        right = x + w
        area_w, area_h = self._area()
        if edges & _RIGHT:
            w = min(g.width() + dx, area_w - x)
        if edges & _BOTTOM and not self._collapsed:
            h = min(g.height() + dy, area_h - y)
        if edges & _LEFT:
            x = max(0, min(x + dx, right - self.min_w))
            w = right - x
        w = max(w, self.min_w)
        if not self._collapsed:
            h = max(h, self.min_h)
        self.apply_rect(Rect(x, y, w, h))

    # --- перетаскивание за заголовок -----------------------------------------

    def _on_drag_started(self, global_pos: QPoint) -> None:
        self.activated.emit(self.panel_id)
        self._drag_press = global_pos
        self._drag_origin = self.pos()

    def _on_drag_moved(self, global_pos: QPoint) -> None:
        if self._drag_press is None or self._drag_origin is None:
            return
        target = self._drag_origin + (global_pos - self._drag_press)
        self.move_to(target.x(), target.y())

    def _on_drag_finished(self) -> None:
        self._drag_press = None
        self._drag_origin = None
        self.geometry_committed.emit(self.panel_id)

    # --- изменение размера за края --------------------------------------------

    def _edges_at(self, pos: QPoint) -> int:
        if self._collapsed:
            # у свёрнутой панели меняется только ширина
            edges = 0
        else:
            edges = _BOTTOM if pos.y() >= self.height() - RESIZE_MARGIN else 0
        near_bottom = pos.y() >= self.height() - CORNER and not self._collapsed
        if pos.x() <= RESIZE_MARGIN or (near_bottom and pos.x() <= CORNER):
            edges |= _LEFT
        elif pos.x() >= self.width() - RESIZE_MARGIN or (near_bottom and pos.x() >= self.width() - CORNER):
            edges |= _RIGHT
        if edges & (_LEFT | _RIGHT) and near_bottom:
            edges |= _BOTTOM
        return edges

    @staticmethod
    def _cursor_for(edges: int) -> Qt.CursorShape | None:
        if edges == _BOTTOM:
            return Qt.CursorShape.SizeVerCursor
        if edges in (_LEFT, _RIGHT):
            return Qt.CursorShape.SizeHorCursor
        if edges == _LEFT | _BOTTOM:
            return Qt.CursorShape.SizeBDiagCursor
        if edges == _RIGHT | _BOTTOM:
            return Qt.CursorShape.SizeFDiagCursor
        return None

    def mousePressEvent(self, event) -> None:
        self.activated.emit(self.panel_id)
        if event.button() == Qt.MouseButton.LeftButton:
            edges = self._edges_at(event.position().toPoint())
            if edges:
                self._resize_edges = edges
                self._resize_press = event.globalPosition().toPoint()
                self._resize_start = self.geometry()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resize_press is not None:
            delta = event.globalPosition().toPoint() - self._resize_press
            self.resize_by_edges(self._resize_edges, delta.x(), delta.y(), self._resize_start)
            event.accept()
            return
        cursor = self._cursor_for(self._edges_at(event.position().toPoint()))
        if cursor is None:
            self.unsetCursor()
        else:
            self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._resize_press is not None and event.button() == Qt.MouseButton.LeftButton:
            self._resize_press = None
            self._resize_start = None
            self._resize_edges = 0
            self.geometry_committed.emit(self.panel_id)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:
        if self._resize_press is None:
            self.unsetCursor()
        super().leaveEvent(event)

    # --- отрисовка ------------------------------------------------------------

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._invalidate_shadow(QRect(event.oldPos(), self.size()))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._invalidate_shadow(QRect(self.pos(), event.oldSize()))

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._invalidate_shadow(self.geometry())

    def _invalidate_shadow(self, old: QRect) -> None:
        """Тень рисует рабочая область под панелью: старое и новое место нужно перерисовать."""
        parent = self.parentWidget()
        if parent is None:
            return
        parent.update(old.adjusted(-SHADOW, -SHADOW, SHADOW, SHADOW))
        parent.update(self.geometry().adjusted(-SHADOW, -SHADOW, SHADOW, SHADOW))

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        path = QPainterPath()
        path.addRoundedRect(r, RADIUS, RADIUS)

        # участок фона окна (город) под панелью, затем прозрачное «стекло»:
        # город виден сквозь панель, а содержимое других панелей — нет
        parent = self.parentWidget()
        paint_background = getattr(parent, "paint_background", None)
        if callable(paint_background):
            p.save()
            p.setClipPath(path)
            paint_background(p, QRectF(self.rect()), QRectF(self.geometry()))
            p.restore()
            top, bottom = QColor(16, 24, 52, GLASS_ALPHA_TOP), QColor(8, 12, 30, GLASS_ALPHA_BOTTOM)
        else:
            top, bottom = QColor(18, 27, 48, 236), QColor(10, 15, 28, 232)
        fill = QLinearGradient(QPointF(0, 0), QPointF(0, r.height()))
        fill.setColorAt(0.0, top)
        fill.setColorAt(1.0, bottom)
        p.fillPath(path, fill)
        # лёгкий блик стекла сверху
        sheen = QLinearGradient(QPointF(0, 0), QPointF(0, min(r.height(), 90)))
        sheen.setColorAt(0.0, QColor(160, 190, 255, 22))
        sheen.setColorAt(1.0, QColor(160, 190, 255, 0))
        p.fillPath(path, sheen)

        border = QColor(54, 191, 255, 150) if self._active else QColor(170, 195, 255, 62)
        p.setPen(QPen(border, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(path)

        # тонкая светящаяся линия по верхнему краю
        line = QLinearGradient(QPointF(r.left(), 0), QPointF(r.right(), 0))
        edge = QColor(54, 191, 255, 0)
        line.setColorAt(0.0, edge)
        mid = QColor(54, 191, 255, 170 if self._active else 70)
        line.setColorAt(0.5, mid)
        line.setColorAt(1.0, edge)
        p.setPen(QPen(line, 1.2))
        p.drawLine(QPointF(r.left() + RADIUS, r.top() + 0.5), QPointF(r.right() - RADIUS, r.top() + 0.5))
