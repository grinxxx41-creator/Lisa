"""Погода в островке: значок, вкладка с прогнозом и мини-капсула (время, градусы или эквалайзер)."""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from interface import styles
from interface.dotmatrix import DotLabel
from interface.island.views import label
from interface.island.widgets import Chip, IconButton, Visualizer, rgba
from interface.styles import WHITE
from monitoring.weather import describe, format_temp

MINI_HEIGHT = 34


class WeatherIcon(QWidget):
    """Значок погоды тонкими линиями: sun, partly, cloud, fog, rain, snow, storm."""

    def __init__(self, size: int = 40, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = ""
        self.setFixedSize(size, size)

    def kind(self) -> str:
        return self._kind

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self.update()

    @staticmethod
    def _cloud(s: float, dy: float = 0.0) -> QPainterPath:
        base = QPainterPath()
        base.addRoundedRect(QRectF(0.16 * s, (0.50 + dy) * s, 0.68 * s, 0.24 * s), 0.12 * s, 0.12 * s)
        for cx, cy, r in ((0.38, 0.50, 0.15), (0.57, 0.44, 0.20)):
            bump = QPainterPath()
            bump.addEllipse(QPointF(cx * s, (cy + dy) * s), r * s, r * s)
            base = base.united(bump)
        return base

    @staticmethod
    def _sun(p: QPainter, cx: float, cy: float, r: float) -> None:
        p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(8):
            a = math.pi / 4 * i
            p.drawLine(QPointF(cx + math.cos(a) * r * 1.5, cy + math.sin(a) * r * 1.5),
                       QPointF(cx + math.cos(a) * r * 2.05, cy + math.sin(a) * r * 2.05))

    def paintEvent(self, _event) -> None:   # noqa: N802
        if not self._kind:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = float(min(self.width(), self.height()))
        pen = QPen(rgba(WHITE, 235), max(1.2, s / 17), Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap,
                   Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        kind = self._kind
        if kind == "sun":
            self._sun(p, s / 2, s / 2, s * 0.19)
        elif kind == "fog":
            for i, (x0, x1) in enumerate(((0.2, 0.8), (0.12, 0.7), (0.3, 0.88), (0.2, 0.72))):
                y = (0.3 + 0.14 * i) * s
                p.drawLine(QPointF(x0 * s, y), QPointF(x1 * s, y))
        else:
            dy = 0.0 if kind in ("cloud", "partly") else -0.12
            cloud = self._cloud(s, dy)
            if kind == "partly":          # солнце выглядывает из-за облака
                whole = QPainterPath()
                whole.addRect(QRectF(0, 0, s, s))
                p.save()
                p.setClipPath(whole.subtracted(cloud))
                self._sun(p, s * 0.68, s * 0.32, s * 0.13)
                p.restore()
            p.drawPath(cloud)
            low = (0.74 + dy) * s
            if kind == "rain":
                for x in (0.34, 0.5, 0.66):
                    p.drawLine(QPointF(x * s, low + 0.07 * s), QPointF((x - 0.05) * s, low + 0.2 * s))
            elif kind == "snow":
                p.setBrush(rgba(WHITE, 235))
                for x, y in ((0.34, 0.1), (0.5, 0.17), (0.66, 0.1)):
                    p.drawEllipse(QPointF(x * s, low + y * s), s * 0.022, s * 0.022)
            elif kind == "storm":
                bolt = QPainterPath(QPointF(0.54 * s, low + 0.03 * s))
                for x, y in ((0.44, 0.15), (0.53, 0.15), (0.46, 0.27)):
                    bolt.lineTo(QPointF(x * s, low + y * s))
                p.drawPath(bolt)
        p.end()


def _big_temp() -> QWidget:
    if styles.DOT_MATRIX:
        return DotLabel("", dot=4.2, gap=1.9, color=styles.WHITE)
    widget = QLabel("")
    widget.setObjectName("isBig")
    return widget


class _DayColumn(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(74)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        self.name = label("", "isCaption")
        self.icon = WeatherIcon(26)
        self.temps = label("", "isMono")
        for widget in (self.name, self.icon, self.temps):
            lay.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)

    def set_day(self, day) -> None:
        self.name.setText(day.weekday)
        self.icon.set_kind(describe(day.code)[1])
        self.icon.setToolTip(describe(day.code)[0])
        self.temps.setText(f"{format_temp(day.t_max)} {format_temp(day.t_min)}")


class WeatherView(QWidget):
    """Вкладка «Погода»: сейчас и на три дня. Пока город не указан — поле, чтобы его ввести."""

    HEIGHT = 112
    DAYS = 3
    city_submitted = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._weather = None
        self._day_count = 0
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 2, 0, 0)
        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        # нет данных: подсказка и поле города
        self.setup = QWidget()
        setup = QVBoxLayout(self.setup)
        setup.setContentsMargins(0, 0, 0, 0)
        setup.setSpacing(8)
        setup.addStretch(1)
        self.hint = label("Укажите город, чтобы видеть погоду", "isTitle")
        self.note = label("Название города отправляется в сервис Open-Meteo. Больше ничего не передаётся.", "isSub")
        setup.addWidget(self.hint)
        setup.addWidget(self.note)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.city_edit = QLineEdit()
        self.city_edit.setObjectName("islandSearch")
        self.city_edit.setPlaceholderText("Город, например: Казань")
        self.city_edit.setMaxLength(80)
        self.city_edit.setFixedWidth(280)
        self.city_edit.returnPressed.connect(self._submit)
        self.save_btn = Chip("Показать погоду", "search")
        self.save_btn.clicked.connect(self._submit)
        row.addWidget(self.city_edit)
        row.addWidget(self.save_btn)
        row.addStretch(1)
        setup.addLayout(row)
        setup.addStretch(1)
        self.stack.addWidget(self.setup)

        # данные
        self.data = QWidget()
        data = QHBoxLayout(self.data)
        data.setContentsMargins(0, 0, 0, 0)
        data.setSpacing(16)
        self.icon = WeatherIcon(64)
        data.addWidget(self.icon)
        self.temp = _big_temp()
        data.addWidget(self.temp)
        middle = QVBoxLayout()
        middle.setSpacing(3)
        self.city = label("", "isTitle", elided=True)
        self.summary = label("", "isLine", elided=True)
        self.details = label("", "isSub", elided=True)
        self.updated = label("", "isSub", elided=True)
        middle.addStretch(1)
        for widget in (self.city, self.summary, self.details, self.updated):
            middle.addWidget(widget)
        middle.addStretch(1)
        data.addLayout(middle, 1)
        self.day_columns = [_DayColumn() for _ in range(self.DAYS)]
        for column in self.day_columns:
            data.addWidget(column)
        self.change_btn = IconButton("settings", "Указать другой город", 26)
        self.change_btn.clicked.connect(self._edit_city)
        data.addWidget(self.change_btn, 0, Qt.AlignmentFlag.AlignTop)
        self.stack.addWidget(self.data)

    def _submit(self) -> None:
        city = self.city_edit.text().strip()
        if city:
            self.hint.setText(f"Запрашиваю погоду: {city}…")
            self.city_submitted.emit(city)

    def _edit_city(self) -> None:
        self.hint.setText("Укажите город, чтобы видеть погоду")
        self.stack.setCurrentWidget(self.setup)
        self.city_edit.setFocus()
        self.city_edit.selectAll()

    def weather(self):
        return self._weather

    def set_weather(self, weather, hint: str = "", city: str = "") -> None:
        """weather: monitoring.weather.Weather или None; hint — почему данных нет."""
        self._weather = weather
        if weather is None:
            if city and not self.city_edit.hasFocus():
                self.city_edit.setText(city)
            self.hint.setText(hint or "Укажите город, чтобы видеть погоду")
            self.stack.setCurrentWidget(self.setup)
            return
        self.icon.set_kind(weather.icon)
        self.temp.setText(format_temp(weather.temp))
        self.city.setText(weather.city)
        self.summary.setText(weather.text)
        parts = []
        if weather.feels is not None:
            parts.append(f"ощущается {format_temp(weather.feels)}")
        if weather.wind is not None:
            parts.append(f"ветер {weather.wind:.0f} м/с")
        if weather.humidity is not None:
            parts.append(f"влажность {weather.humidity:.0f}%")
        self.details.setText(" · ".join(parts))
        self.updated.setText(hint or f"Обновлено в {time.strftime('%H:%M', time.localtime(weather.fetched))} · Open-Meteo")
        days = list(weather.days[1:1 + self.DAYS])          # первый день — сегодня
        for column, day in zip(self.day_columns, days):
            column.set_day(day)
        self._day_count = len(days)
        self._fit_days()
        self.stack.setCurrentWidget(self.data)

    def _fit_days(self) -> None:
        """Прогноз не теснит текст: на узкой капсуле дней показывается меньше."""
        fits = max(0, (self.width() - 500) // 90) if self.width() > 0 else self.DAYS
        for index, column in enumerate(self.day_columns):
            column.setVisible(index < min(self._day_count, fits))

    def resizeEvent(self, event) -> None:   # noqa: N802
        super().resizeEvent(event)
        self._fit_days()


class _UnreadDot(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(6, 6)

    def paintEvent(self, _event) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rgba(styles.ERROR if styles.VIOLET == styles.WHITE else styles.VIOLET))
        p.drawEllipse(self.rect())
        p.end()


class MiniView(QWidget):
    """Содержимое свёрнутой мини-капсулы: время и градусы, а пока играет музыка — время и эквалайзер.

    Щелчки не перехватывает: их обрабатывает окно островка.
    """

    HEIGHT = MINI_HEIGHT
    resized = Signal()          # набор показанного изменился — капсуле нужна другая ширина

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._playing = False
        self._eq_allowed = True
        self._has_weather = False
        self._unread = 0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 14, 0)
        lay.setSpacing(8)
        lay.addStretch(1)
        if styles.DOT_MATRIX:
            self.time = DotLabel("", dot=1.9, gap=0.9, color=styles.WHITE)
            self.temp = DotLabel("", dot=1.9, gap=0.9, color=styles.TEXT_SECONDARY)
        else:
            self.time = QLabel("")
            self.temp = QLabel("")
            family = styles.FONT if styles.ISLAND_IOS else styles.FONT_MONO
            self.time.setStyleSheet(f"font-family: {family}; font-size: 13px; font-weight: 600;")
            self.temp.setStyleSheet(f"font-family: {family}; font-size: 13px; font-weight: 600;"
                                    f" color: {styles.TEXT_SECONDARY};")
        self.icon = WeatherIcon(18)
        self.visualizer = Visualizer(9)
        self.visualizer.setFixedSize(44, 16)
        self.dot = _UnreadDot()
        for widget in (self.time, self.visualizer, self.icon, self.temp, self.dot):
            lay.addWidget(widget)
        lay.addStretch(1)
        self._clock = QTimer(self)
        self._clock.setInterval(1000)
        self._clock.timeout.connect(self._tick)
        self._tick()
        self._sync()

    def showEvent(self, event) -> None:   # noqa: N802
        super().showEvent(event)
        self._tick()
        self._clock.start()

    def hideEvent(self, event) -> None:   # noqa: N802
        super().hideEvent(event)
        self._clock.stop()

    def _tick(self) -> None:
        self.time.setText(time.strftime("%H:%M"))

    def shows_equalizer(self) -> bool:
        return self._playing and self._eq_allowed

    def _sync(self) -> None:
        eq = self.shows_equalizer()
        before = self.wanted_width()
        self.visualizer.setVisible(eq)
        self.icon.setVisible(not eq and self._has_weather)
        self.temp.setVisible(not eq and self._has_weather)
        self.dot.setVisible(self._unread > 0)
        if not eq:
            self.visualizer.clear()
        if self.wanted_width() != before:
            self.resized.emit()

    def set_weather(self, weather) -> None:
        self._has_weather = weather is not None
        if weather is not None:
            self.icon.set_kind(weather.icon)
            self.temp.setText(format_temp(weather.temp))
        self._sync()

    def set_playing(self, playing: bool, equalizer: bool = True) -> None:
        """Играет ли музыка и разрешён ли визуализатор в настройках."""
        self._playing, self._eq_allowed = bool(playing), bool(equalizer)
        self._sync()

    def set_unread(self, count: int) -> None:
        self._unread = count
        self._sync()

    def push_level(self, level: float) -> None:
        if self.shows_equalizer() and self.isVisible():
            self.visualizer.push(level)

    def wanted_width(self) -> int:
        """Ширина капсулы под то, что сейчас показано."""
        lay = self.layout()
        shown = [w for w in (self.visualizer, self.time, self.icon, self.temp, self.dot) if not w.isHidden()]
        widths = sum(max(w.minimumWidth(), w.sizeHint().width()) for w in shown)
        margins = lay.contentsMargins()
        return max(72, widths + lay.spacing() * max(0, len(shown) - 1) + margins.left() + margins.right())
