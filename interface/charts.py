"""Графики мониторинга в стиле SIRIUS: линия со свечением и заливкой, загрузка по ядрам.

Рисуются через QPainter, без сторонних библиотек. Данные — список (время, значение)
из monitoring.history.MetricsHistory.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from interface.styles import BG_ALT, ERROR, TEXT_SECONDARY, WARNING, WHITE

HIGH = 85.0


def _c(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


def format_rate(bps: float | None) -> str:
    if bps is None:
        return "—"
    if bps >= 1024 ** 2:
        return f"{bps / 1024 ** 2:.1f} МБ/с"
    return f"{bps / 1024:.0f} КБ/с"


class LineChart(QWidget):
    """Линейный график за окно времени. max_value=None — масштаб по максимуму данных (скорости)."""

    def __init__(self, title: str, color: str, unit: str = "%", max_value: float | None = 100.0,
                 window: float = 300.0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.title = title
        self.color = color
        self.unit = unit
        self.max_value = max_value
        self.window = window
        self._points: list[tuple[float, float]] = []
        self._now = 0.0
        self.setMinimumSize(120, 64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_series(self, points: list[tuple[float, float]], now: float) -> None:
        self._points = points
        self._now = now
        self.update()

    def latest(self) -> float | None:
        return self._points[-1][1] if self._points else None

    def _label(self, value: float | None) -> str:
        if value is None:
            return "Unavailable"
        if self.unit == "rate":
            return format_rate(value)
        return f"{value:.0f}{self.unit}"

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_c(self.color, 50), 1))
        p.setBrush(_c(BG_ALT, 90))
        p.drawRoundedRect(r, 6, 6)

        head = 16
        plot = r.adjusted(6, head + 4, -6, -5)
        # сетка: 25 / 50 / 75 %
        p.setPen(QPen(_c(TEXT_SECONDARY, 22), 1, Qt.PenStyle.DotLine))
        for k in (0.25, 0.5, 0.75):
            y = plot.bottom() - plot.height() * k
            p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))

        value = self.latest()
        top = self.max_value
        if top is None:
            top = max([v for _, v in self._points] + [1.0]) * 1.15
        if len(self._points) >= 2 and plot.width() > 2:
            # пока не накопилось окно целиком, шкала растягивается на уже собранные данные (минимум 20 с)
            span = min(self.window, max(20.0, self._now - self._points[0][0]))
            start = self._now - span
            path = QPainterPath()
            first = True
            for t, v in self._points:
                x = plot.left() + max(0.0, (t - start) / span) * plot.width()
                y = plot.bottom() - max(0.0, min(v / top, 1.0)) * plot.height()
                if first:
                    path.moveTo(x, y)
                    first_x = x
                    first = False
                else:
                    path.lineTo(x, y)
            last_x = x
            area = QPainterPath(path)
            area.lineTo(last_x, plot.bottom())
            area.lineTo(first_x, plot.bottom())
            area.closeSubpath()
            fill = QLinearGradient(0, plot.top(), 0, plot.bottom())
            fill.setColorAt(0.0, _c(self.color, 90))
            fill.setColorAt(1.0, _c(self.color, 5))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(area)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_c(self.color, 60), 4))
            p.drawPath(path)
            p.setPen(QPen(_c(self.color, 230), 1.6))
            p.drawPath(path)

        font = QFont(self.font())
        font.setPointSizeF(max(7.5, font.pointSizeF() - 1))
        p.setFont(font)
        p.setPen(_c(TEXT_SECONDARY))
        p.drawText(QRectF(r.left() + 7, r.top() + 2, r.width() / 2, head), Qt.AlignmentFlag.AlignVCenter, self.title)
        high = value is not None and self.unit == "%" and value >= HIGH
        p.setPen(_c(ERROR if high else WHITE))
        p.drawText(QRectF(r.left(), r.top() + 2, r.width() - 7, head),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight, self._label(value))
        p.end()


class CoreBars(QWidget):
    """Загрузка каждого логического ядра процессора — вертикальные столбики."""

    def __init__(self, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.color = color
        self._values: tuple[float, ...] = ()
        self.setMinimumHeight(40)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(46)

    def set_values(self, values: tuple[float, ...] | None) -> None:
        self._values = tuple(values or ())
        self.setToolTip("\n".join(f"Ядро {i + 1}: {v:.0f}%" for i, v in enumerate(self._values)))
        self.update()

    def values(self) -> tuple[float, ...]:
        return self._values

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        n = len(self._values)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(_c(self.color, 50), 1))
        p.setBrush(_c(BG_ALT, 90))
        p.drawRoundedRect(r, 6, 6)
        if not n:
            p.setPen(_c(TEXT_SECONDARY))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, "Ядра: Unavailable")
            p.end()
            return
        inner = r.adjusted(6, 5, -6, -5)
        gap = 3.0
        w = max(2.0, (inner.width() - gap * (n - 1)) / n)
        for i, v in enumerate(self._values):
            x = inner.left() + i * (w + gap)
            h = max(1.5, inner.height() * min(v, 100.0) / 100.0)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(TEXT_SECONDARY, 25))
            p.drawRoundedRect(QRectF(x, inner.top(), w, inner.height()), 2, 2)
            color = ERROR if v >= HIGH else WARNING if v >= 60 else self.color
            p.setBrush(_c(color, 210))
            p.drawRoundedRect(QRectF(x, inner.bottom() - h, w, h), 2, 2)
        p.end()
