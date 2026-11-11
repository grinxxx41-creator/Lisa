"""Мелкие виджеты островка: значки, кнопки, шкалы, визуализатор звука, обложка.

Значки — системный шрифт Windows «Segoe Fluent Icons» (Windows 11) или «Segoe MDL2 Assets»
(Windows 10): чёткие при любом масштабе экрана и не требуют файлов изображений.
"""

from __future__ import annotations

import math
from collections import deque

from PySide6.QtCore import Property, QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton, QLabel, QSizePolicy, QWidget

from interface import styles as _styles
from interface.styles import CYAN, ERROR, SUCCESS, TEAL, TEXT_SECONDARY, VIOLET, WARNING, WHITE

GLYPHS = {
    "volume": "", "volume0": "", "volume1": "", "volume2": "", "volume3": "",
    "mute": "", "brightness": "", "play": "", "pause": "", "next": "",
    "prev": "", "pin": "", "pinned": "", "close": "", "bell": "",
    "music": "", "wifi": "", "bluetooth": "", "settings": "", "folder": "",
    "window": "", "chat": "", "chip": "", "bolt": "", "link": "", "app": "",
    "copy": "", "delete": "", "search": "", "clipboard": "", "shelf": "",
    "timer": "", "down": "", "up": "", "expand": "", "keyboard": "",
    "reset": "", "stop": "", "system": "", "tools": "", "warning": "",
    "info": "", "plug": "", "file": "", "lisa": "",
}


def glyph_font(pixel_size: int) -> QFont:
    font = QFont()
    font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
    font.setPixelSize(pixel_size)
    return font


def rgba(color: str, alpha: int = 255) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c


def level_color(percent: float | None, warn: float = 85.0) -> str:
    if percent is None:
        return TEXT_SECONDARY
    return ERROR if percent >= warn else WARNING if percent >= warn - 15 else SUCCESS


class _Hover(QAbstractButton):
    """Кнопка с плавной подсветкой при наведении."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._glow = 0.0
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(140)
        self._anim.valueChanged.connect(self._set_glow)

    def _set_glow(self, value) -> None:
        self._glow = float(value)
        self.update()

    def _run(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(float(self._glow))
        self._anim.setEndValue(float(target))
        self._anim.start()

    def enterEvent(self, event) -> None:
        self._run(1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._run(0.0)
        super().leaveEvent(event)


class IconButton(_Hover):
    """Круглая кнопка со значком. badge — число в углу (например, непрочитанные уведомления)."""

    def __init__(self, glyph: str, tooltip: str = "", size: int = 28, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._size = size
        self._color = WHITE
        self._badge = 0
        self.setFixedSize(size, size)
        self.setToolTip(tooltip)

    def set_glyph(self, glyph: str) -> None:
        if glyph != self._glyph:
            self._glyph = glyph
            self.update()

    def set_color(self, color: str) -> None:
        self._color = color
        self.update()

    def set_badge(self, count: int) -> None:
        if count != self._badge:
            self._badge = count
            self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        active = self.isChecked() or self.isDown()
        fill = 46 if active else int(34 * self._glow)
        if fill:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rgba(CYAN if active else WHITE, fill))
            p.drawEllipse(r)
        color = CYAN if self.isChecked() else self._color
        p.setPen(rgba(color, 255 if self.isEnabled() else 80))
        p.setFont(glyph_font(int(self._size * 0.5)))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, GLYPHS.get(self._glyph, self._glyph))
        if self._badge > 0:
            d = 13.0
            badge = QRectF(self.width() - d, 0, d, d)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(rgba(VIOLET))
            p.drawEllipse(badge)
            font = QFont(self.font())
            font.setPixelSize(8)
            font.setBold(True)
            p.setFont(font)
            p.setPen(rgba(WHITE))
            p.drawText(badge, Qt.AlignmentFlag.AlignCenter, str(self._badge) if self._badge < 10 else "9+")
        p.end()


class Chip(_Hover):
    """Плоская кнопка-ярлык с текстом и необязательным значком (навигация, вкладки, быстрые действия)."""

    def __init__(self, text: str, glyph: str = "", checkable: bool = False, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._text_px = 11
        self.setText(text)
        self.setCheckable(checkable)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_glyph(self, glyph: str) -> None:
        self._glyph = glyph
        self.updateGeometry()
        self.update()

    def _font(self) -> QFont:
        font = QFont(self.font())
        font.setPixelSize(self._text_px)
        font.setWeight(QFont.Weight.DemiBold)
        return font

    def sizeHint(self) -> QSize:
        width = QFontMetrics(self._font()).horizontalAdvance(self.text()) + 20
        if self._glyph:
            width += 18 if self.text() else 6
        return QSize(width, 24)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        checked = self.isChecked()
        p.setPen(QPen(rgba(CYAN, 120) if checked else rgba(WHITE, 26 + int(40 * self._glow)), 1))
        p.setBrush(rgba(CYAN, 34) if checked else rgba(WHITE, 10 + int(22 * self._glow)))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        color = rgba(CYAN if checked else WHITE, (235 if checked or self._glow > 0.3 else 190) if self.isEnabled() else 80)
        p.setPen(color)
        x = 10.0
        if self._glyph:
            p.setFont(glyph_font(12))
            p.drawText(QRectF(x - 1, 0, 14, self.height()), Qt.AlignmentFlag.AlignCenter, GLYPHS.get(self._glyph, ""))
            x += 18
        p.setFont(self._font())
        p.drawText(QRectF(x, 0, self.width() - x - 6, self.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self.text())
        p.end()


class ElidedLabel(QLabel):
    """Надпись в одну строку, которая обрезается многоточием и не растягивает островок."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full = text
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(20)

    def setText(self, text: str) -> None:  # noqa: N802 — имя Qt
        self._full = text
        self._refresh()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        line = " ".join(self._full.split())
        super().setText(self.fontMetrics().elidedText(line, Qt.TextElideMode.ElideRight, max(10, self.width())))


class SmoothBar(QWidget):
    """Шкала 0..1 с плавным изменением значения. Щелчок или протяжка сообщают новую позицию (sought)."""

    sought = Signal(float)

    def __init__(self, color: str = CYAN, color_to: str = VIOLET, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._color, self._color_to = color, color_to
        self._interactive = False
        self.duration_ms = 180
        self.setFixedHeight(14)
        self._anim = QPropertyAnimation(self, b"value", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get(self) -> float:
        return self._value

    def _set(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))
        self.update()

    value = Property(float, _get, _set)

    def set_value(self, value: float, animate: bool = True) -> None:
        value = max(0.0, min(1.0, float(value)))
        self._anim.stop()
        if not animate or self.duration_ms <= 0 or not self.isVisible():
            self._set(value)
            return
        self._anim.setDuration(self.duration_ms)
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(value)
        self._anim.start()

    def set_colors(self, color: str, color_to: str | None = None) -> None:
        self._color, self._color_to = color, color_to or color
        self.update()

    def set_interactive(self, enabled: bool) -> None:
        self._interactive = enabled
        self.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)

    def _seek(self, event) -> None:
        if self._interactive and self.width() > 0:
            pos = max(0.0, min(1.0, event.position().x() / self.width()))
            self._anim.stop()
            self._set(pos)
            self.sought.emit(pos)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._interactive:
            self._seek(event)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton and self._interactive:
            self._seek(event)

    def mouseReleaseEvent(self, event) -> None:
        if not self._interactive:
            super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        h = 4.0
        track = QRectF(0, (self.height() - h) / 2, self.width(), h)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rgba(WHITE, 34))
        p.drawRoundedRect(track, h / 2, h / 2)
        if self._value > 0.001:
            from PySide6.QtGui import QLinearGradient

            fill = QRectF(track.x(), track.y(), max(h, track.width() * self._value), h)
            grad = QLinearGradient(fill.topLeft(), fill.topRight())
            grad.setColorAt(0.0, rgba(self._color))
            grad.setColorAt(1.0, rgba(self._color_to))
            p.setBrush(grad)
            p.drawRoundedRect(fill, h / 2, h / 2)
            if self._interactive:
                p.setBrush(rgba(WHITE))
                p.drawEllipse(QPointF(fill.right(), track.center().y()), 4.5, 4.5)
        p.end()


class Gauge(QWidget):
    """Круговой индикатор загрузки с подписью (CPU, GPU, RAM, VRAM)."""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._value: float | None = None
        self._shown = 0.0
        self.setFixedSize(64, 76)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(400)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(self._on_step)

    def _on_step(self, value) -> None:
        self._shown = float(value)
        self.update()

    def set_value(self, percent: float | None) -> None:
        self._value = percent
        target = 0.0 if percent is None else float(max(0.0, min(100.0, percent)))
        self._anim.stop()
        if not self.isVisible():
            self._shown = target
            self.update()
            return
        self._anim.setStartValue(float(self._shown))
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        ring = QRectF(8, 4, 48, 48)
        p.setPen(QPen(rgba(WHITE, 30), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(ring, 225 * 16, -270 * 16)
        color = level_color(self._value)
        if self._value is not None and self._shown > 0.5:
            p.setPen(QPen(rgba(color), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawArc(ring, 225 * 16, int(-270 * 16 * self._shown / 100.0))
        font = QFont(self.font())
        font.setPixelSize(13)
        font.setBold(True)
        p.setFont(font)
        p.setPen(rgba(WHITE))
        p.drawText(ring, Qt.AlignmentFlag.AlignCenter, "—" if self._value is None else f"{self._shown:.0f}")
        font.setPixelSize(10)
        font.setBold(False)
        p.setFont(font)
        p.setPen(rgba(TEXT_SECONDARY))
        p.drawText(QRectF(0, 56, self.width(), 18), Qt.AlignmentFlag.AlignCenter, self._title)
        p.end()


class Visualizer(QWidget):
    """Визуализатор по настоящему уровню звука устройства вывода (пиковое значение Windows).

    Это уровень громкости сигнала во времени, а не спектр: частоты здесь не показываются.
    Стили: bars — столбики истории уровня, wave — зеркальная огибающая, pulse — пульс от центра.
    Данные подаются снаружи методом push(); без данных виджет ничего не рисует.
    """

    STYLES = ("bars", "wave", "pulse")

    def __init__(self, bars: int = 24, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._levels: deque[float] = deque([0.0] * bars, maxlen=bars)
        self._smooth = 0.0
        self.style_name = "bars"
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_style(self, name: str) -> None:
        self.style_name = name if name in self.STYLES else "bars"
        self.update()

    def push(self, level: float) -> None:
        """Новый уровень 0..1. Подъём мгновенный, спад плавный — как у индикаторов уровня."""
        level = max(0.0, min(1.0, level)) ** 0.6          # тихие звуки заметнее
        self._smooth = level if level > self._smooth else self._smooth * 0.78 + level * 0.22
        self._levels.append(self._smooth)
        self.update()

    def clear(self) -> None:
        self._smooth = 0.0
        self._levels.extend([0.0] * self._levels.maxlen)
        self.update()

    def is_silent(self) -> bool:
        return max(self._levels) < 0.004

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        n = len(self._levels)
        mid = h / 2
        p.setPen(Qt.PenStyle.NoPen)
        if self.style_name == "wave":
            path = QPainterPath()
            step = w / max(1, n - 1)
            top = [QPointF(i * step, mid - max(0.6, v * mid)) for i, v in enumerate(self._levels)]
            path.moveTo(top[0])
            for point in top[1:]:
                path.lineTo(point)
            for i in range(n - 1, -1, -1):
                path.lineTo(QPointF(i * step, 2 * mid - top[i].y()))
            path.closeSubpath()
            p.setBrush(rgba(CYAN, 110))
            p.setPen(QPen(rgba(TEAL, 220), 1.0))
            p.drawPath(path)
        elif self.style_name == "pulse":
            half = n // 2
            bar = w / (half * 2)
            recent = list(self._levels)[-half:][::-1]         # свежие значения — в центре
            for i, v in enumerate(recent):
                height = max(2.0, v * h)
                alpha = int(235 - 150 * i / max(1, half - 1))
                p.setBrush(rgba(VIOLET if i % 2 else CYAN, alpha))
                for x in (w / 2 + i * bar, w / 2 - (i + 1) * bar):
                    p.drawRoundedRect(QRectF(x + bar * 0.2, mid - height / 2, bar * 0.6, height), 1.2, 1.2)
        elif _styles.DOT_MATRIX:              # столбики из точек; негорящие точки едва видны
            bar = w / n
            rows = max(3, int(h // 5))
            pitch = h / rows
            r = min(bar, pitch) * 0.30
            centre = (rows - 1) / 2
            for i, v in enumerate(self._levels):
                lit = max(1.0, v * rows) / 2
                for k in range(rows):
                    on = abs(k - centre) < lit
                    p.setBrush(rgba(VIOLET if on and v >= 0.75 else CYAN if on else WHITE,
                                    int(110 + 145 * (i + 1) / n) if on else 18))
                    p.drawEllipse(QPointF(i * bar + bar / 2, (k + 0.5) * pitch), r, r)
        else:
            bar = w / n
            for i, v in enumerate(self._levels):
                height = max(2.0, v * h)
                p.setBrush(rgba(CYAN if v < 0.75 else VIOLET, int(110 + 145 * (i + 1) / n)))
                p.drawRoundedRect(QRectF(i * bar + bar * 0.2, mid - height / 2, bar * 0.6, height), 1.2, 1.2)
        p.end()


class Cover(QWidget):
    """Обложка альбома или значок приложения со скруглёнными углами; без картинки — значок-заглушка."""

    def __init__(self, size: int = 72, radius: float = 14.0, placeholder: str = "music",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pixmap: QPixmap | None = None
        self._radius = radius
        self._placeholder = placeholder
        self._key: int | None = None
        self.setFixedSize(size, size)

    def set_image(self, data: bytes | None) -> None:
        key = hash(data) if data else None
        if key == self._key:
            return
        self._key = key
        self._pixmap = None
        if data:
            image = QImage.fromData(data)
            if not image.isNull():
                side = min(image.width(), image.height())
                image = image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side)
                ratio = self.devicePixelRatioF()
                pixmap = QPixmap.fromImage(image.scaled(
                    int(self.width() * ratio), int(self.height() * ratio),
                    Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation))
                pixmap.setDevicePixelRatio(ratio)
                self._pixmap = pixmap
        self.update()

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._key = None
        self._pixmap = pixmap if pixmap is not None and not pixmap.isNull() else None
        self.update()

    def set_placeholder(self, glyph: str) -> None:
        self._placeholder = glyph
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect())
        path = QPainterPath()
        path.addRoundedRect(r, self._radius, self._radius)
        p.setClipPath(path)
        if self._pixmap is not None:
            p.drawPixmap(self.rect(), self._pixmap)
        else:
            p.fillRect(r, rgba(WHITE, 16))
            p.setPen(rgba(TEXT_SECONDARY, 200))
            p.setFont(glyph_font(int(self.width() * 0.42)))
            p.drawText(r, Qt.AlignmentFlag.AlignCenter, GLYPHS.get(self._placeholder, self._placeholder))
        p.setClipping(False)
        p.setPen(QPen(rgba(WHITE, 28), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(0.5, 0.5, -0.5, -0.5), self._radius, self._radius)
        p.end()


class BatteryIcon(QWidget):
    """Значок аккумулятора с заполнением по уровню заряда."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._percent: float | None = None
        self._charging = False
        self.setFixedSize(30, 18)

    def set_state(self, percent: float | None, charging: bool) -> None:
        self._percent, self._charging = percent, charging
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QRectF(1, 3, 24, 12)
        p.setPen(QPen(rgba(WHITE, 200), 1.2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(body, 3.5, 3.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rgba(WHITE, 200))
        p.drawRoundedRect(QRectF(26, 6.5, 2.5, 5), 1, 1)
        if self._percent is not None:
            color = SUCCESS if self._charging else ERROR if self._percent <= 15 else WARNING if self._percent <= 30 else WHITE
            p.setBrush(rgba(color))
            width = max(2.0, 20.0 * max(0.0, min(100.0, self._percent)) / 100.0)
            p.drawRoundedRect(QRectF(3, 5, width, 8), 2, 2)
        p.end()


def pulse(phase: float) -> float:
    """Плавная пульсация 0..1 для анимированных значков."""
    return 0.5 + 0.5 * math.sin(phase)
