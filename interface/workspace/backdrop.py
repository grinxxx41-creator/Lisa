"""Фон окна SIRIUS: ночной город за LISA, как на референсе пользователя.

Фон рисуется программно (без картинки), поэтому чёткий на любом разрешении. Он строится один раз
для текущего размера окна и кэшируется. Во время изменения размера окна показывается
растянутая прежняя версия, а новая строится после паузы: окно не подтормаживает.
Высотки по краям выше, в центре ниже: место за LISA остаётся спокойным.
"""

from __future__ import annotations

import random

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import QWidget

SEED = 20261107
_WINDOW_COLORS = ((86, 150, 255), (150, 112, 255), (96, 206, 255), (196, 120, 255), (255, 196, 120))
_NEON = ((121, 91, 255), (54, 191, 255), (230, 90, 220), (61, 220, 200))


def _rgba(rgb: tuple[int, int, int], alpha: int) -> QColor:
    return QColor(rgb[0], rgb[1], rgb[2], max(0, min(255, alpha)))


def _buildings(p: QPainter, rnd: random.Random, w: float, h: float, base_y: float, color: QColor,
               min_w: float, max_w: float, height_at, light_chance: float, light_alpha: tuple[int, int],
               neon_chance: float) -> None:
    x = -rnd.uniform(0, max_w)
    while x < w:
        bw = rnd.uniform(min_w, max_w)
        bh = height_at((x + bw / 2) / max(w, 1)) * h * rnd.uniform(0.75, 1.15)
        top = base_y - bh
        p.setPen(Qt.PenStyle.NoPen)
        # подсветка верха здания заревом города
        body = QLinearGradient(QPointF(0, top), QPointF(0, base_y))
        body.setColorAt(0.0, color.lighter(165))
        body.setColorAt(0.25, color)
        body.setColorAt(1.0, color.darker(140))
        p.setBrush(body)
        p.drawRect(QRectF(x, top, bw, bh + 2))
        p.setBrush(_rgba((150, 140, 255), 40))
        p.drawRect(QRectF(x, top, bw, 1.2))
        p.setBrush(color)
        if rnd.random() < 0.35:  # надстройка или шпиль
            sw = bw * rnd.uniform(0.2, 0.5)
            p.drawRect(QRectF(x + (bw - sw) / 2, top - bh * 0.08, sw, bh * 0.08 + 1))
        # окна
        cell_w, cell_h = 5.0, 7.0
        cols = int((bw - 4) // cell_w)
        rows = int((bh - 6) // cell_h)
        lit = light_chance * rnd.uniform(0.4, 1.6)
        tint = rnd.choice(_WINDOW_COLORS)
        for r in range(rows):
            y = top + 4 + r * cell_h
            for c in range(cols):
                if rnd.random() < lit:
                    col = tint if rnd.random() < 0.8 else rnd.choice(_WINDOW_COLORS)
                    p.setBrush(_rgba(col, rnd.randint(*light_alpha)))
                    p.drawRect(QRectF(x + 3 + c * cell_w, y, 2.2, 3.2))
        if rnd.random() < neon_chance:  # вертикальная неоновая полоса
            neon = rnd.choice(_NEON)
            nx = x + rnd.choice((1.5, bw - 3.5))
            grad = QLinearGradient(QPointF(0, top), QPointF(0, base_y))
            grad.setColorAt(0.0, _rgba(neon, 200))
            grad.setColorAt(1.0, _rgba(neon, 20))
            p.setBrush(grad)
            p.drawRect(QRectF(nx, top + 6, 2, bh * rnd.uniform(0.3, 0.8)))
        x += bw + rnd.uniform(0, max_w * 0.25)


def render_city(width: int, height: int, dpr: float = 1.0, seed: int = SEED) -> QPixmap:
    w, h = max(width, 1), max(height, 1)
    pix = QPixmap(int(w * dpr), int(h * dpr))
    pix.setDevicePixelRatio(dpr)
    rnd = random.Random(seed)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    sky = QLinearGradient(QPointF(0, 0), QPointF(0, h))
    sky.setColorAt(0.0, QColor(4, 6, 14))
    sky.setColorAt(0.45, QColor(10, 15, 44))
    sky.setColorAt(0.70, QColor(20, 15, 56))
    sky.setColorAt(0.86, QColor(8, 9, 22))
    sky.setColorAt(1.0, QColor(4, 5, 10))
    p.fillRect(QRectF(0, 0, w, h), sky)

    # свечение города у горизонта
    for cx, cy, rad, col in ((0.5, 0.66, 0.65, (121, 91, 255, 70)), (0.5, 0.6, 0.38, (54, 191, 255, 34)),
                              (0.82, 0.55, 0.3, (200, 80, 230, 26)), (0.15, 0.58, 0.3, (54, 120, 255, 28))):
        g = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * rad)
        g.setColorAt(0.0, QColor(*col))
        g.setColorAt(1.0, QColor(col[0], col[1], col[2], 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawRect(QRectF(0, 0, w, h))

    horizon = h * 0.80

    def far(t: float) -> float:
        return 0.12 + 0.22 * abs(t - 0.5) * 2

    def mid(t: float) -> float:
        return 0.16 + 0.48 * (abs(t - 0.5) * 2) ** 1.4

    _buildings(p, rnd, w, h, horizon, QColor(16, 22, 58), 14, 38, far, 0.16, (40, 120), 0.05)
    # дымка между слоями
    haze = QLinearGradient(QPointF(0, horizon - h * 0.3), QPointF(0, horizon))
    haze.setColorAt(0.0, QColor(30, 30, 90, 0))
    haze.setColorAt(1.0, QColor(40, 34, 110, 60))
    p.setBrush(haze)
    p.drawRect(QRectF(0, horizon - h * 0.3, w, h * 0.3))
    _buildings(p, rnd, w, h, horizon + 4, QColor(10, 13, 38), 34, 96, mid, 0.13, (70, 180), 0.22)

    # боке: размытые огни
    for _ in range(int(48 * w / 1600) + 10):
        x = rnd.uniform(0, w)
        y = rnd.uniform(h * 0.12, h * 0.82)
        if abs(x - w / 2) < w * 0.14 and rnd.random() < 0.7:
            continue  # за LISA огней меньше
        rad = rnd.uniform(5, 30) * (w / 1600) ** 0.5
        col = rnd.choice(_WINDOW_COLORS[:4] + ((230, 90, 200),))
        g = QRadialGradient(QPointF(x, y), rad)
        g.setColorAt(0.0, _rgba(col, rnd.randint(30, 85)))
        g.setColorAt(0.7, _rgba(col, rnd.randint(10, 30)))
        g.setColorAt(1.0, _rgba(col, 0))
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), rad, rad)

    # тёмные близкие башни по краям
    for side in (0, 1):
        x = 0.0 if side == 0 else w * 0.9
        while (side == 0 and x < w * 0.1) or (side == 1 and x < w):
            bw = rnd.uniform(w * 0.03, w * 0.06)
            top = rnd.uniform(-h * 0.05, h * 0.25)
            p.setBrush(QColor(5, 7, 18))
            p.drawRect(QRectF(x, top, bw, h))
            for _ in range(int(h * 0.02)):
                if rnd.random() < 0.5:
                    p.setBrush(_rgba(rnd.choice(_WINDOW_COLORS), rnd.randint(40, 120)))
                    p.drawRect(QRectF(x + rnd.uniform(3, bw - 6), rnd.uniform(top, h * 0.8), 2.5, 3.5))
            x += bw + rnd.uniform(2, 12)

    # стол на переднем плане
    desk_top = h * 0.86
    desk = QLinearGradient(QPointF(0, desk_top), QPointF(0, h))
    desk.setColorAt(0.0, QColor(10, 12, 26))
    desk.setColorAt(1.0, QColor(3, 4, 9))
    p.setBrush(desk)
    p.drawRect(QRectF(0, desk_top, w, h - desk_top))
    edge = QLinearGradient(QPointF(0, 0), QPointF(w, 0))
    edge.setColorAt(0.0, QColor(54, 191, 255, 0))
    edge.setColorAt(0.5, QColor(140, 120, 255, 70))
    edge.setColorAt(1.0, QColor(54, 191, 255, 0))
    p.setBrush(edge)
    p.drawRect(QRectF(0, desk_top, w, 1.2))
    reflect = QRadialGradient(QPointF(w / 2, desk_top + h * 0.03), w * 0.22)
    reflect.setColorAt(0.0, QColor(110, 110, 255, 60))
    reflect.setColorAt(1.0, QColor(110, 110, 255, 0))
    p.setBrush(reflect)
    p.drawRect(QRectF(0, desk_top, w, h - desk_top))

    # виньетка
    vignette = QRadialGradient(QPointF(w / 2, h * 0.5), max(w, h) * 0.75)
    vignette.setColorAt(0.55, QColor(0, 0, 0, 0))
    vignette.setColorAt(1.0, QColor(0, 0, 0, 150))
    p.setBrush(vignette)
    p.drawRect(QRectF(0, 0, w, h))
    p.end()
    return pix


class WorkspaceBackdrop(QWidget):
    """Центральный виджет окна: рисует фон-город под панелью управления и рабочей областью."""

    REBUILD_DELAY_MS = 180

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceBackdrop")
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._pixmap: QPixmap | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(self.REBUILD_DELAY_MS)
        self._timer.timeout.connect(self._rebuild)

    def _dpr(self) -> float:
        return float(self.devicePixelRatioF()) or 1.0

    def _rebuild(self) -> None:
        self._pixmap = render_city(self.width(), self.height(), self._dpr())
        self.update()

    def pixmap(self) -> QPixmap:
        if self._pixmap is None:
            self._rebuild()
        return self._pixmap

    def is_exact(self) -> bool:
        pix = self._pixmap
        return pix is not None and pix.deviceIndependentSize().toSize() == self.size()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._pixmap is None:
            self._rebuild()
        else:
            self._timer.start()  # пока окно тянут, рисуется растянутая прежняя версия

    def paint_region(self, p: QPainter, target: QRectF, source: QRectF) -> None:
        """Рисует участок фона source (координаты этого виджета) в прямоугольник target."""
        pix = self.pixmap()
        sx = pix.width() / max(self.width(), 1)
        sy = pix.height() / max(self.height(), 1)
        p.drawPixmap(target, pix, QRectF(source.x() * sx, source.y() * sy, source.width() * sx,
                                         source.height() * sy))

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        rect = QRectF(event.rect())
        self.paint_region(p, rect, rect)
        p.end()
