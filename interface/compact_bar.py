"""Компактный режим SIRIUS (v0.3): полоска у верхнего края экрана поверх других окон.

Мини-LISA (цвет состояния и настроения, щелчок останавливает речь), поле ввода, последняя фраза
ответа, мини-метрики CPU/GPU/RAM/VRAM и температура, переключатель голоса, возврат в полное окно.
Логики нет: окно только отправляет сигналы главному окну и показывает переданные данные.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeySequence, QPainter, QPen, QRadialGradient, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from interface.avatar_widget import AvatarState
from interface.styles import BG, CYAN, ERROR, SUCCESS, TEXT_SECONDARY, VIOLET, WARNING, WHITE

BAR_W, BAR_H = 900, 52
_STATE_COLORS = {
    AvatarState.IDLE: CYAN, AvatarState.THINKING: VIOLET, AvatarState.SPEAKING: CYAN,
    AvatarState.STOPPED: TEXT_SECONDARY, AvatarState.ERROR: ERROR, AvatarState.OFFLINE: "#6F7D99",
}
_MOOD_COLORS = {"busy": WARNING, "hot": ERROR}


def _c(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


class MiniLisa(QWidget):
    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("LISA — щелчок останавливает речь")
        self.state = AvatarState.IDLE
        self.mood = "normal"
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(50)
        self._timer.timeout.connect(self._tick)

    def showEvent(self, event) -> None:
        self._timer.start()
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self) -> None:
        speed = {AvatarState.THINKING: 0.16, AvatarState.SPEAKING: 0.25}.get(self.state, 0.05)
        self._phase += speed
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def color(self) -> str:
        if self.state in (AvatarState.IDLE, AvatarState.THINKING, AvatarState.SPEAKING) and self.mood in _MOOD_COLORS:
            return _MOOD_COLORS[self.mood]
        return _STATE_COLORS[self.state]

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = QPointF(20, 20)
        pulse = 0.5 + 0.5 * math.sin(self._phase * 6)
        color = self.color()
        glow = QRadialGradient(c, 20)
        glow.setColorAt(0.0, _c(color, int(120 + 80 * pulse)))
        glow.setColorAt(0.55, _c(color, 40))
        glow.setColorAt(1.0, _c(color, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(c, 20, 20)
        p.setPen(QPen(_c(color, 220), 1.6))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawArc(QRectF(5, 5, 30, 30), int(self._phase * 300) % 5760, 1700)
        p.drawArc(QRectF(5, 5, 30, 30), (int(self._phase * 300) + 2880) % 5760, 1700)
        p.setPen(_c(WHITE))
        f = p.font()
        f.setBold(True)
        f.setPointSizeF(9)
        p.setFont(f)
        p.drawText(QRectF(0, 0, 40, 40), Qt.AlignmentFlag.AlignCenter, "L")
        p.end()


class CompactBar(QWidget):
    send_requested = Signal(str)
    expand_requested = Signal()
    voice_toggled = Signal(bool)
    avatar_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("SIRIUS — компактный режим")
        self.resize(BAR_W, BAR_H)
        self._drag_from: QPointF | None = None
        self._reply = ""

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)
        self.lisa = MiniLisa()
        self.lisa.clicked.connect(self.avatar_clicked)
        lay.addWidget(self.lisa)

        self.input = QLineEdit()
        self.input.setPlaceholderText("Спросите LISA…")
        self.input.setMinimumWidth(220)
        self.input.returnPressed.connect(self._send)
        lay.addWidget(self.input, 3)

        self.reply = QLabel("")
        self.reply.setObjectName("secondary")
        self.reply.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.reply.setMinimumWidth(120)
        lay.addWidget(self.reply, 4)

        self.metrics = QLabel("")
        self.metrics.setTextFormat(Qt.TextFormat.RichText)
        self.metrics.setStyleSheet("font-family: Consolas; font-size: 11px;")
        lay.addWidget(self.metrics)

        self.voice_btn = QPushButton("VOICE")
        self.voice_btn.setCheckable(True)
        self.voice_btn.setObjectName("barButton")
        self.voice_btn.setToolTip("Голос LISA (Ctrl+Shift+V)")
        self.voice_btn.toggled.connect(self.voice_toggled)
        lay.addWidget(self.voice_btn)

        self.expand_btn = QPushButton("⤢")
        self.expand_btn.setObjectName("barButton")
        self.expand_btn.setToolTip("Вернуться в полное окно (Ctrl+M или Esc)")
        self.expand_btn.setStyleSheet("font-size: 17px; padding: 2px 10px;")
        self.expand_btn.clicked.connect(self.expand_requested)
        lay.addWidget(self.expand_btn)

        for keys in ("Esc", "Ctrl+M"):
            QShortcut(QKeySequence(keys), self, activated=self.expand_requested.emit)

    # --- данные ---------------------------------------------------------------------

    def set_state(self, state: AvatarState) -> None:
        self.lisa.state = state

    def set_mood(self, mood: str) -> None:
        self.lisa.mood = mood

    def set_voice(self, enabled: bool) -> None:
        self.voice_btn.blockSignals(True)
        self.voice_btn.setChecked(enabled)
        self.voice_btn.setText("VOICE ON" if enabled else "VOICE OFF")
        self.voice_btn.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        self.input.setEnabled(not busy)
        self.input.setPlaceholderText("LISA отвечает…" if busy else "Спросите LISA…")
        if not busy:
            self.input.setFocus()

    def begin_reply(self) -> None:
        self._reply = ""
        self.reply.setText("")

    def append_reply(self, delta: str) -> None:
        self._reply += delta
        self._show_reply()

    def set_reply(self, text: str) -> None:
        self._reply = text
        self._show_reply()

    def reply_text(self) -> str:
        return self._reply

    def _show_reply(self) -> None:
        text = " ".join(self._reply.split())
        metrics = self.reply.fontMetrics()
        # видна последняя часть ответа — она обновляется по мере генерации
        width = max(60, self.reply.width())
        if metrics.horizontalAdvance(text) > width:
            text = "…" + metrics.elidedText(text[::-1], Qt.TextElideMode.ElideRight, width)[::-1].lstrip("…")
        self.reply.setText(text)
        self.reply.setToolTip(self._reply[-1500:])

    def set_metrics(self, values: dict[str, float | None]) -> None:
        def part(name: str, key: str, unit: str = "%", warn: float = 85.0) -> str:
            v = values.get(key)
            if v is None:
                return f'<span style="color:{TEXT_SECONDARY}">{name} —</span>'
            color = ERROR if v >= warn else WARNING if v >= warn - 15 else SUCCESS if unit == "%" else WHITE
            return f'<span style="color:{TEXT_SECONDARY}">{name}</span> <span style="color:{color}">{v:.0f}{unit}</span>'

        self.metrics.setText("&nbsp; ".join((
            part("CPU", "cpu"), part("GPU", "gpu"), part("RAM", "ram"), part("VRAM", "vram"),
            part("", "gpu_temp", "°C", warn=85.0),
        )))

    # --- окно -----------------------------------------------------------------------

    def place_on_screen(self, screen=None) -> None:
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        w = min(BAR_W, area.width() - 20)
        self.resize(w, BAR_H)
        self.move(area.x() + (area.width() - w) // 2, area.y() + 6)

    def _send(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self.send_requested.emit(text)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(_c(CYAN, 110), 1.2))
        p.setBrush(_c(BG, 225))
        p.drawRoundedRect(r, 14, 14)
        p.setPen(QPen(_c(CYAN, 40), 4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), 13, 13)
        p.end()

    # перетаскивание за свободное место полоски
    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition() - QPointF(self.pos())

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is not None:
            pos = event.globalPosition() - self._drag_from
            self.move(int(pos.x()), int(pos.y()))

    def mouseReleaseEvent(self, event) -> None:
        self._drag_from = None
