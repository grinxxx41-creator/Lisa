"""Аватар LISA с состояниями IDLE/THINKING/SPEAKING/STOPPED/ERROR/OFFLINE.

Основной вид — голографическая LISA из resources/images/lisa.png (подготовлен из референса
пользователя скриптом tools/prepare_lisa_avatar.py). Поверх изображения рисуются свечение, световой
луч от подставки, орбиты с точками, линии развёртки и сканирующий луч по фигуре, свечение губ
во время речи и окраска по состоянию.

Если файла нет, рисуется прежний векторный голографический силуэт.
"""

from __future__ import annotations

import math
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from interface.styles import CYAN, ERROR, TEXT_SECONDARY, VIOLET, WARNING


class AvatarState(Enum):
    IDLE = "IDLE"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    STOPPED = "STOPPED"
    ERROR = "ERROR"
    OFFLINE = "OFFLINE"   # Ollama недоступна


OFFLINE_COLOR = "#6F7D99"

_COLORS = {
    AvatarState.IDLE: CYAN,
    AvatarState.THINKING: VIOLET,
    AvatarState.SPEAKING: CYAN,
    AvatarState.STOPPED: TEXT_SECONDARY,
    AvatarState.ERROR: ERROR,
    AvatarState.OFFLINE: OFFLINE_COLOR,
}
_SPEED = {
    AvatarState.IDLE: 0.05,
    AvatarState.THINKING: 0.16,
    AvatarState.SPEAKING: 0.22,
    AvatarState.STOPPED: 0.012,
    AvatarState.ERROR: 0.03,
    AvatarState.OFFLINE: 0.01,
}
# Интервал кадров по состояниям: спокойные состояния рисуются реже, анимация идёт с той же скоростью.
BASE_INTERVAL_MS = 33
_INTERVAL_MS = {
    AvatarState.IDLE: 50,
    AvatarState.THINKING: 33,
    AvatarState.SPEAKING: 33,
    AvatarState.STOPPED: 100,
    AvatarState.ERROR: 50,
    AvatarState.OFFLINE: 120,
}
_DIM = {AvatarState.STOPPED: 0.45, AvatarState.OFFLINE: 0.5}

# Точки на изображении lisa.png (доли ширины и высоты)
_HEAD = (0.503, 0.239)       # центр головы
_MOUTH = (0.500, 0.338)      # губы
_PLATFORM = (0.500, 0.885)   # центр подставки
# окраска изображения по состоянию: цвет и сила
_IMAGE_TINTS = {
    "think": (VIOLET, 85),
    "error": (ERROR, 125),
    "offline": (OFFLINE_COLOR, 165),
    "stopped": (TEXT_SECONDARY, 120),
}
_STATE_VARIANT = {
    AvatarState.THINKING: "think",
    AvatarState.ERROR: "error",
    AvatarState.OFFLINE: "offline",
    AvatarState.STOPPED: "stopped",
}
_IMAGE_OPACITY = {AvatarState.STOPPED: 0.6, AvatarState.OFFLINE: 0.7}

# v0.3: настроение по состоянию компьютера — свечение LISA смешивается с цветом тревоги
MOODS = ("normal", "busy", "hot")
_MOOD_MIX = {"busy": (WARNING, 0.5), "hot": (ERROR, 0.7)}
_MOOD_STATES = (AvatarState.IDLE, AvatarState.THINKING, AvatarState.SPEAKING)


class AvatarWidget(QWidget):
    clicked = Signal()  # нажатие на аватар (остановка речи обрабатывается снаружи)

    def __init__(self, image_path: Path | None = None, parent=None) -> None:
        super().__init__(parent)
        self._state = AvatarState.IDLE
        self._mood = "normal"
        self._phase = 0.0
        self._image: QPixmap | None = None
        self._cache_key: tuple | None = None
        self._variants: dict[str, QPixmap] = {}
        self._highlights: dict[str, QPixmap] = {}
        self._auras: dict = {}
        self._base_pixmap: QPixmap | None = None
        if image_path and Path(image_path).exists():
            pix = QPixmap(str(image_path))
            self._image = pix if not pix.isNull() else None
        self.setMinimumSize(220, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Нажмите, чтобы остановить речь")
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(_INTERVAL_MS[self._state])

    @property
    def state(self) -> AvatarState:
        return self._state

    def set_state(self, state: AvatarState) -> None:
        if state != self._state:
            self._state = state
            self._timer.setInterval(_INTERVAL_MS[state])
            self.update()

    def set_system_mood(self, mood: str) -> None:
        """normal — обычное свечение, busy — высокая нагрузка (янтарный), hot — перегрев (красный)."""
        if mood in MOODS and mood != self._mood:
            self._mood = mood
            self.update()

    @property
    def mood(self) -> str:
        return self._mood

    def _base_color(self) -> QColor:
        base = QColor(_COLORS[self._state])
        mix = _MOOD_MIX.get(self._mood)
        if mix is None or self._state not in _MOOD_STATES:
            return base
        other, k = QColor(mix[0]), mix[1]
        return QColor(round(base.red() * (1 - k) + other.red() * k), round(base.green() * (1 - k) + other.green() * k),
                      round(base.blue() * (1 - k) + other.blue() * k))

    @property
    def has_image(self) -> bool:
        """True — LISA рисуется по изображению lisa.png, False — векторный силуэт."""
        return self._image is not None

    def frame_interval(self) -> int:
        return self._timer.interval()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def _tick(self) -> None:
        # скрытый аватар или свёрнутое окно не перерисовываются
        if not self.isVisible() or self.window().isMinimized():
            return
        speed = _SPEED[self._state] * (1.6 if self._mood == "hot" and self._state in _MOOD_STATES else 1.0)
        self._phase += speed * self._timer.interval() / BASE_INTERVAL_MS
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = min(w, h * 0.9) * 0.38
        cx, cy = w / 2, h * 0.46
        base = self._base_color()
        pulse = 0.5 + 0.5 * math.sin(self._phase * 6)
        dim = _DIM.get(self._state, 1.0)

        # мягкое свечение за фигурой; радиус не выходит за границы виджета, чтобы не было резкого края
        glow_r = min(r * 1.7, w / 2, cy, h - cy)
        glow = QRadialGradient(QPointF(cx, cy), glow_r)
        glow.setColorAt(0.0, _with_alpha(base, int((70 + 60 * pulse) * dim)))
        glow.setColorAt(1.0, _with_alpha(base, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        if self._image is not None:
            self._paint_image_avatar(p, w, h, base, pulse, dim)
            p.end()
            return

        self._draw_hologram(p, cx, cy, r, h, base, pulse, dim)
        if self._state == AvatarState.THINKING:
            self._draw_thinking_ring(p, cx, cy, r, base)
        elif self._state == AvatarState.SPEAKING:
            self._draw_speech_bars(p, cx, h, base)
        elif self._state == AvatarState.OFFLINE:
            self._draw_caption(p, w, h, "OLLAMA OFFLINE", base)
        p.end()

    # --- аватар по изображению (resources/images/lisa.png) ---------------------------

    def image_rect(self, w: float | None = None, h: float | None = None) -> QRectF:
        """Где рисуется изображение: пропорции сохранены, фигура стоит внизу виджета."""
        w = self.width() if w is None else w
        h = self.height() if h is None else h
        aspect = self._image.width() / max(self._image.height(), 1)
        th = h * 0.99
        tw = th * aspect
        if tw > w * 0.96:
            tw = w * 0.96
            th = tw / aspect
        return QRectF((w - tw) / 2, h - th, tw, th)

    def _prepare_image_cache(self, rect: QRectF) -> None:
        """Готовит изображения для текущего размера: варианты по состояниям с линиями развёртки,
        подсвеченные копии для сканирующего луча и слой свечения. В кадре они только копируются."""
        dpr = float(self.devicePixelRatioF()) or 1.0
        key = (int(rect.width()), int(rect.height()), self.width(), self.height(), dpr)
        if key == self._cache_key:
            return
        self._cache_key = key
        self._variants = {}
        self._highlights = {}
        self._auras = {}
        normal = self._image.scaled(max(1, int(rect.width() * dpr)), max(1, int(rect.height() * dpr)),
                                    Qt.AspectRatioMode.IgnoreAspectRatio,
                                    Qt.TransformationMode.SmoothTransformation)
        normal.setDevicePixelRatio(dpr)
        self._base_pixmap = normal
        for name in ("normal", *_IMAGE_TINTS):
            tint = _IMAGE_TINTS.get(name)
            self._variants[name] = self._layer(normal, tint, scanlines=True)

    def _layer(self, source: QPixmap, tint: tuple[str, int] | None, scanlines: bool) -> QPixmap:
        """Копия фигуры: окраска и линии развёртки только там, где есть фигура."""
        out = QPixmap(source.size())
        out.setDevicePixelRatio(source.devicePixelRatio())
        out.fill(Qt.GlobalColor.transparent)
        p = QPainter(out)
        p.drawPixmap(0, 0, source)
        p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceAtop)
        if tint is not None:
            p.fillRect(QRectF(0, 0, out.width(), out.height()), _with_alpha(QColor(tint[0]), tint[1]))
        if scanlines:
            p.setPen(QPen(QColor(0, 0, 0, 34), 1))
            logical_h = out.height() / out.devicePixelRatio()
            logical_w = out.width() / out.devicePixelRatio()
            y = 0.0
            while y < logical_h:
                p.drawLine(QPointF(0, y), QPointF(logical_w, y))
                y += 3.0
        p.end()
        return out

    def _highlight(self, base: QColor) -> QPixmap:
        key = base.name()
        if key not in self._highlights:
            self._highlights[key] = self._layer(self._base_pixmap, (key, 170), scanlines=False)
        return self._highlights[key]

    def _aura(self, base: QColor, rect: QRectF) -> QPixmap:
        """Свечение за фигурой, световой луч и свечение подставки — один раз на цвет и размер."""
        key = base.name()
        if key in self._auras:
            return self._auras[key]
        dpr = float(self.devicePixelRatioF()) or 1.0
        w, h = self.width(), self.height()
        pix = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
        pix.setDevicePixelRatio(dpr)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        x0, y0, tw, th = rect.x(), rect.y(), rect.width(), rect.height()
        center = QPointF(x0 + tw * 0.5, y0 + th * 0.42)
        glow_r = min(tw * 0.8, w / 2, center.y(), h - center.y())
        glow = QRadialGradient(center, glow_r)
        glow.setColorAt(0.0, _with_alpha(base, 105))
        glow.setColorAt(1.0, _with_alpha(base, 0))
        p.setBrush(glow)
        p.drawEllipse(center, glow_r, glow_r)

        platform = QPointF(x0 + tw * _PLATFORM[0], y0 + th * _PLATFORM[1])
        beam = QPainterPath()
        beam.moveTo(platform.x() - tw * 0.16, platform.y())
        beam.lineTo(platform.x() + tw * 0.16, platform.y())
        beam.lineTo(platform.x() + tw * 0.42, y0 + th * 0.35)
        beam.lineTo(platform.x() - tw * 0.42, y0 + th * 0.35)
        beam.closeSubpath()
        ray = QLinearGradient(QPointF(0, platform.y()), QPointF(0, y0 + th * 0.35))
        ray.setColorAt(0.0, _with_alpha(base, 90))
        ray.setColorAt(1.0, _with_alpha(base, 0))
        p.setBrush(ray)
        p.drawPath(beam)
        p.end()
        self._auras[key] = pix
        return pix

    def _pad_glow(self, base: QColor, tw: float, th: float) -> QPixmap:
        key = ("pad", base.name())
        if key not in self._auras:
            dpr = float(self.devicePixelRatioF()) or 1.0
            pw, ph = tw * 0.6, th * 0.06
            pix = QPixmap(max(1, int(pw * dpr)), max(1, int(ph * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(Qt.GlobalColor.transparent)
            p = QPainter(pix)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            pad = QRadialGradient(QPointF(pw / 2, ph / 2), pw / 2)
            pad.setColorAt(0.0, _with_alpha(base, 200))
            pad.setColorAt(1.0, _with_alpha(base, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(pad)
            p.drawEllipse(QRectF(0, 0, pw, ph))
            p.end()
            self._auras[key] = pix
        return self._auras[key]

    def _paint_image_avatar(self, p: QPainter, w, h, base: QColor, pulse: float, dim: float) -> None:
        rect = self.image_rect(w, h)
        self._prepare_image_cache(rect)
        x0, y0, tw, th = round(rect.x()), round(rect.y()), rect.width(), rect.height()
        head = QPointF(x0 + tw * _HEAD[0], y0 + th * _HEAD[1])
        platform = QPointF(x0 + tw * _PLATFORM[0], y0 + th * _PLATFORM[1])

        # свечение и луч: готовый слой, пульсирует только прозрачность
        p.setOpacity((0.55 + 0.45 * pulse) * dim)
        p.drawPixmap(0, 0, self._aura(base, QRectF(x0, y0, tw, th)))

        # LISA в цвете состояния
        pix = self._variants[_STATE_VARIANT.get(self._state, "normal")]
        if self._state == AvatarState.ERROR and int(self._phase * 10) % 7 == 0:
            p.setOpacity(0.35)  # сбой: смещённые копии
            for dx in (-5, 4):
                p.drawPixmap(x0 + dx, y0, pix)
        p.setOpacity(_IMAGE_OPACITY.get(self._state, 1.0))
        p.drawPixmap(x0, y0, pix)

        # сканирующий луч: полоса подсвеченной копии фигуры (повторяет её контур)
        band_h = max(4.0, th * 0.05)
        scan_y = ((self._phase * 0.35) % 1.0) * th
        light = self._highlight(base)
        dpr = light.devicePixelRatio()
        for k, alpha in ((0.0, 0.55), (-0.33, 0.25), (0.33, 0.25)):
            sy = scan_y + k * band_h - band_h / 6
            if sy < 0 or sy >= th:
                continue
            sh = min(band_h / 3, th - sy)
            p.setOpacity(alpha * dim)
            p.drawPixmap(QRectF(x0, y0 + sy, tw, sh), light, QRectF(0, sy * dpr, light.width(), sh * dpr))
        p.setOpacity(1.0)

        # пульсирующее свечение подставки
        pad = self._pad_glow(base, tw, th)
        p.setOpacity((0.5 + 0.5 * pulse) * dim)
        p.drawPixmap(QPointF(platform.x() - tw * 0.3, platform.y() - th * 0.03), pad)
        p.setOpacity(1.0)

        self._draw_orbits(p, head, tw * 0.33, base, dim)

        if self._state == AvatarState.SPEAKING:
            amp = 0.5 + 0.5 * math.sin(self._phase * 9)
            mouth = QPointF(x0 + tw * _MOUTH[0], y0 + th * _MOUTH[1])
            lips = QRadialGradient(mouth, tw * 0.05)
            lips.setColorAt(0.0, _with_alpha(base, int(25 + 55 * amp)))
            lips.setColorAt(1.0, _with_alpha(base, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(lips)
            p.drawEllipse(mouth, tw * 0.05, tw * 0.025 * (0.7 + 0.6 * amp))
            self._draw_speech_bars(p, x0 + tw / 2, h, base)
        elif self._state == AvatarState.THINKING:
            self._draw_thinking_ring(p, head.x(), head.y(), tw * 0.3, base)
        elif self._state == AvatarState.OFFLINE:
            self._draw_caption(p, w, h, "OLLAMA OFFLINE", base)

    def _draw_hologram(self, p: QPainter, cx, cy, r, h, base, pulse, dim) -> None:
        head_c = QPointF(cx, cy - r * 0.25)
        figure = QPainterPath()
        figure.addEllipse(head_c, r * 0.42, r * 0.52)                       # голова
        figure.addRoundedRect(QRectF(cx - r * 0.16, cy + r * 0.2, r * 0.32, r * 0.35), 6, 6)  # шея
        figure.moveTo(cx - r * 0.95, h * 0.98)                              # плечи
        figure.cubicTo(cx - r * 0.9, cy + r * 0.55, cx - r * 0.45, cy + r * 0.45, cx - r * 0.2, cy + r * 0.5)
        figure.lineTo(cx + r * 0.2, cy + r * 0.5)
        figure.cubicTo(cx + r * 0.45, cy + r * 0.45, cx + r * 0.9, cy + r * 0.55, cx + r * 0.95, h * 0.98)
        figure.closeSubpath()

        hair = QPainterPath()                                               # волосы
        hair.addEllipse(QPointF(cx, cy - r * 0.3), r * 0.52, r * 0.66)
        hair.addRect(QRectF(cx - r * 0.52, cy - r * 0.3, r * 1.04, r * 0.9))
        silhouette = hair.united(figure)

        self._draw_platform(p, cx, h, r, base, pulse, dim)
        self._draw_orbits(p, QPointF(cx, cy - r * 0.2), r, base, dim)
        if self._state == AvatarState.ERROR:
            self._draw_glitch(p, silhouette)

        fill = QLinearGradient(QPointF(cx, cy - r), QPointF(cx, h))
        fill.setColorAt(0.0, _with_alpha(base, int(150 * dim)))
        fill.setColorAt(0.6, _with_alpha(QColor(base).lighter(130), int(90 * dim)))
        fill.setColorAt(1.0, _with_alpha(QColor(VIOLET), int(50 * dim)))
        p.setBrush(fill)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(silhouette)

        p.save()
        p.setClipPath(silhouette)
        # сканлинии и вертикальные линии корпуса
        scan = _with_alpha(QColor(255, 255, 255), int(26 * dim))
        p.setPen(QPen(scan, 1))
        offset = int(self._phase * 40) % 6
        for y in range(int(cy - r), int(h), 6):
            p.drawLine(int(cx - r * 1.2), y + offset, int(cx + r * 1.2), y + offset)
        p.setPen(QPen(_with_alpha(base, int(70 * dim)), 1))
        for k in range(3):
            x = cx + (k - 1) * r * 0.42
            p.drawLine(QPointF(x, cy + r * 0.6), QPointF(x, h))
        self._draw_scan_beam(p, cx, cy, r, h, base, dim)
        p.restore()

        self._draw_strands(p, cx, cy, r, base, dim)
        self._draw_face(p, cx, cy, r, base, pulse, dim)

        # контур с мягким свечением
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(base, int(60 * dim)), 6))
        p.drawPath(silhouette)
        p.setPen(QPen(_with_alpha(base, int((180 + 60 * pulse) * dim)), 1.4))
        p.drawPath(silhouette)

    def _draw_platform(self, p: QPainter, cx, h, r, base, pulse, dim) -> None:
        """Голографическая подставка под фигурой."""
        y = h * 0.955
        glow = QRadialGradient(QPointF(cx, y), r * 1.25)
        glow.setColorAt(0.0, _with_alpha(base, int((90 + 50 * pulse) * dim)))
        glow.setColorAt(1.0, _with_alpha(base, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(cx - r * 1.25, y - r * 0.2, r * 2.5, r * 0.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(_with_alpha(base, int(110 * dim)), 1.2))
        p.drawEllipse(QRectF(cx - r * 0.95, y - r * 0.14, r * 1.9, r * 0.28))

    def _draw_orbits(self, p: QPainter, center: QPointF, r, base, dim) -> None:
        """Два наклонных кольца с движущимися точками вокруг головы."""
        # (наклон в градусах, скорость, радиус X, радиус Y в долях r)
        specs = ((-16, 1.0, 0.95, 0.28), (24, -0.7, 1.15, 0.36))
        for tilt, speed, rx_k, ry_k in specs:
            p.save()
            p.translate(center)
            p.rotate(tilt)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(_with_alpha(base, int(70 * dim)), 1, Qt.PenStyle.DashLine))
            rx, ry = r * rx_k, r * ry_k
            p.drawEllipse(QPointF(0, 0), rx, ry)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_with_alpha(base, int(220 * dim)))
            for k in range(3):
                t = self._phase * 2.2 * speed + k * (2 * math.pi / 3)
                p.drawEllipse(QPointF(rx * math.cos(t), ry * math.sin(t)), 2.2, 2.2)
            p.restore()

    def _draw_scan_beam(self, p: QPainter, cx, cy, r, h, base, dim) -> None:
        """Горизонтальный луч, медленно проходящий по фигуре сверху вниз."""
        top, bottom = cy - r, h
        y = top + ((self._phase * 0.35) % 1.0) * (bottom - top)
        band = QLinearGradient(QPointF(0, y - r * 0.08), QPointF(0, y + r * 0.08))
        band.setColorAt(0.0, _with_alpha(base, 0))
        band.setColorAt(0.5, _with_alpha(base, int(60 * dim)))
        band.setColorAt(1.0, _with_alpha(base, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(band)
        p.drawRect(QRectF(cx - r * 1.3, y - r * 0.08, r * 2.6, r * 0.16))
        p.setPen(QPen(_with_alpha(QColor(255, 255, 255), int(120 * dim)), 1))
        p.drawLine(QPointF(cx - r * 1.1, y), QPointF(cx + r * 1.1, y))

    def _draw_strands(self, p: QPainter, cx, cy, r, base, dim) -> None:
        """Пряди волос, которые слегка колышутся."""
        sway = math.sin(self._phase * 2) * r * 0.03
        p.setBrush(Qt.BrushStyle.NoBrush)
        for side in (-1, 1):
            path = QPainterPath()
            path.moveTo(cx + side * r * 0.5, cy - r * 0.5)
            path.cubicTo(cx + side * r * 0.72, cy - r * 0.1 + sway,
                         cx + side * r * 0.78, cy + r * 0.35 - sway,
                         cx + side * r * 0.62, cy + r * 0.78)
            p.setPen(QPen(_with_alpha(base, int(90 * dim)), 1.1))
            p.drawPath(path)

    def _draw_face(self, p: QPainter, cx, cy, r, base, pulse, dim) -> None:
        """Глаза, брови, губы и мягкое свечение щёк."""
        eye_y = cy - r * 0.22
        eye_dx, eye_w, eye_h = r * 0.17, r * 0.12, r * 0.05
        eye_alpha = 200 if self._state != AvatarState.SPEAKING else int(170 + 80 * pulse)
        for side in (-1, 1):
            x = cx + side * eye_dx
            almond = QPainterPath()
            almond.moveTo(x - eye_w, eye_y)
            almond.quadTo(x, eye_y - eye_h * 2.4, x + eye_w, eye_y)
            almond.quadTo(x, eye_y + eye_h * 2.4, x - eye_w, eye_y)
            p.setPen(QPen(_with_alpha(base, int(70 * dim)), 4))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(almond)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_with_alpha(base, int(eye_alpha * dim)))
            p.drawPath(almond)
            p.setBrush(_with_alpha(QColor(255, 255, 255), int(230 * dim)))
            p.drawEllipse(QPointF(x, eye_y), eye_h * 0.9, eye_h * 0.9)
            p.setPen(QPen(_with_alpha(base, int(110 * dim)), 1.1))
            p.drawLine(QPointF(x - eye_w, eye_y - r * 0.12), QPointF(x + eye_w, eye_y - r * 0.13))
        # губы
        lips = QPainterPath()
        lips.moveTo(cx - r * 0.1, cy + r * 0.07)
        lips.quadTo(cx, cy + r * 0.11, cx + r * 0.1, cy + r * 0.07)
        p.setPen(QPen(_with_alpha(base, int(160 * dim)), 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(lips)
        # щёки
        for side in (-1, 1):
            center = QPointF(cx + side * r * 0.26, cy + r * 0.04)
            cheek = QRadialGradient(center, r * 0.13)
            cheek.setColorAt(0.0, _with_alpha(base, int(45 * dim)))
            cheek.setColorAt(1.0, _with_alpha(base, 0))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(cheek)
            p.drawEllipse(center, r * 0.13, r * 0.13)

    def _draw_glitch(self, p: QPainter, silhouette: QPainterPath) -> None:
        """Ошибка: короткие смещённые копии контура через редкие промежутки."""
        if int(self._phase * 10) % 7 != 0:
            return
        p.setBrush(_with_alpha(QColor(ERROR), 70))
        p.setPen(Qt.PenStyle.NoPen)
        for dx in (-4, 3):
            p.save()
            p.translate(dx, 0)
            p.drawPath(silhouette)
            p.restore()

    def _draw_thinking_ring(self, p: QPainter, cx, cy, r, base) -> None:
        p.save()
        p.translate(cx, cy)
        p.rotate(self._phase * 200)
        pen = QPen(_with_alpha(base, 200), 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        ring = max(r, min(r * 1.45, self.width() / 2 - 3, cy - 3))  # кольцо не обрезается краями виджета
        p.drawEllipse(QPointF(0, 0), ring, ring)
        p.restore()

    def _draw_caption(self, p: QPainter, w, h, text: str, base) -> None:
        font = QFont(p.font())
        font.setPointSizeF(8.5)
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 2.5)
        p.setFont(font)
        p.setPen(_with_alpha(base, 200))
        p.drawText(QRectF(0, h - 30, w, 20), Qt.AlignmentFlag.AlignCenter, text)

    def _draw_speech_bars(self, p: QPainter, cx, h, base) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_with_alpha(base, 220))
        bars = 9
        spacing = 9
        x0 = cx - (bars - 1) * spacing / 2
        for i in range(bars):
            amp = 0.5 + 0.5 * math.sin(self._phase * 9 + i * 0.9)
            bar_h = 6 + 22 * amp
            p.drawRoundedRect(QRectF(x0 + i * spacing - 2.5, h - 22 - bar_h / 2, 5, bar_h), 2.5, 2.5)


def _with_alpha(color: QColor, alpha: int) -> QColor:
    c = QColor(color)
    c.setAlpha(max(0, min(255, alpha)))
    return c
