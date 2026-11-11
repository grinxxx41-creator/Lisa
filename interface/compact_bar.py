"""Островок SIRIUS (Living Island) — развитие компактного режима v0.3.

Капсула у края экрана поверх других окон. В обычном состоянии это прежняя компактная полоска:
мини-LISA (цвет состояния и настроения, щелчок останавливает речь), поле ввода, последняя фраза
ответа, мини-метрики, переключатель голоса и возврат в полное окно. По событию или действию
пользователя капсула плавно раскрывается вниз и показывает один из режимов: LISA, медиа,
система, уведомления, инструменты, а также короткие индикаторы громкости, яркости и питания.

Логики нет: окно показывает переданные данные и отправляет сигналы. Что именно видно, решает
диспетчер состояний (interface/island/state_manager.py); данные приносит контроллер
(interface/island/controller.py). Без контроллера окно остаётся рабочей компактной полоской.
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (QBrush, QColor, QGuiApplication, QKeySequence, QLinearGradient, QPainter, QPainterPath,
                           QPen, QPixmap, QRadialGradient, QRegion, QShortcut)
from PySide6.QtWidgets import (QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QSizePolicy, QStackedWidget, QVBoxLayout, QWidget)

from interface.avatar_widget import AvatarState
from interface.island.animator import IslandAnimator
from interface.island.state_manager import IslandStateManager
from interface.island.tools_views import ToolsView
from interface.island.views import HubView, IndicatorView, MediaView, NavBar, NoteList, NoteToast, SystemView
from interface.island.widgets import ElidedLabel, GLYPHS, IconButton, Visualizer, glyph_font
from interface import styles
from interface.styles import rgb as _rgb
from interface.styles import BG, BG_ALT, CYAN, ERROR, SUCCESS, TEXT_SECONDARY, VIOLET, WARNING, WHITE
from island.settings import ISLAND_DEFAULTS, normalize
from island.states import CRITICAL_PRIORITY, USER_STATES, IslandState

BAR_W, BAR_H = ISLAND_DEFAULTS["width"], ISLAND_DEFAULTS["height"]
MARGIN = 4            # поле окна вокруг капсулы — под мягкое свечение
PAD = 18              # отступ содержимого раскрытой капсулы от краёв
BODY_BOTTOM = 12
EDGE_GAP = 6          # расстояние от края экрана
EXPANDED_RADIUS = 24.0
DRAG_THRESHOLD = 4

_STATE_COLORS = {
    AvatarState.IDLE: CYAN, AvatarState.THINKING: VIOLET, AvatarState.SPEAKING: CYAN,
    AvatarState.STOPPED: TEXT_SECONDARY, AvatarState.ERROR: ERROR, AvatarState.OFFLINE: "#6F7D99",
}
_MOOD_COLORS = {"busy": WARNING, "hot": ERROR}
_ACTIVE_STATES = (AvatarState.THINKING, AvatarState.SPEAKING)

# фон капсулы (верх, низ), цвет границы и её прозрачность
THEMES = {
    "graphite": ("#1C1F27", "#0F1116", WHITE, 30),
    "black": ("#060607", "#000000", WHITE, 24),
    "sirius": (BG_ALT, BG, CYAN, 96),
}
if styles.DOT_MATRIX:      # монохромная тема: капсула без синеватого оттенка
    THEMES = {"graphite": ("#141414", "#0A0A0A", WHITE, 40), "black": ("#050505", "#000000", WHITE, 34),
              "sirius": ("#1B1B1B", "#0E0E0E", WHITE, 70)}
_dot_brush: QBrush | None = None


def _dots() -> QBrush:
    """Кисть с сеткой точек для раскрытой части капсулы (строится один раз)."""
    global _dot_brush
    if _dot_brush is None:
        tile = QPixmap(10, 10)
        tile.fill(Qt.GlobalColor.transparent)
        tp = QPainter(tile)
        tp.setRenderHint(QPainter.RenderHint.Antialiasing)
        tp.setPen(Qt.PenStyle.NoPen)
        tp.setBrush(QColor(255, 255, 255, 20))
        tp.drawEllipse(QPointF(5.0, 5.0), 0.9, 0.9)
        tp.end()
        _dot_brush = QBrush(tile)
    return _dot_brush


def _c(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(max(0, min(255, alpha)))
    return color


class MiniLisa(QWidget):
    clicked = Signal()
    ticked = Signal()

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
        self.ticked.emit()

    def phase(self) -> float:
        return self._phase

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def color(self) -> str:
        if self.state in (AvatarState.IDLE, AvatarState.THINKING, AvatarState.SPEAKING) and self.mood in _MOOD_COLORS:
            return _MOOD_COLORS[self.mood]
        return _STATE_COLORS.get(self.state, CYAN)

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


class RowChip(QFrame):
    """Небольшой ярлык в строке капсулы: что играет, таймер Pomodoro. Щелчок открывает режим."""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("rowChip")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(26)
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(9, 0, 10, 0)
        self.lay.setSpacing(6)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()

    def mousePressEvent(self, event) -> None:
        event.accept()        # иначе нажатие ушло бы окну и начало перетаскивание островка


class CompactBar(QWidget):
    send_requested = Signal(str)
    expand_requested = Signal()
    voice_toggled = Signal(bool)
    avatar_clicked = Signal()
    position_changed = Signal(dict)      # пользователь перетащил островок: новые position/custom_pos/screen
    visibility_changed = Signal(bool)
    files_dropped = Signal(list)         # пути файлов, брошенных на островок

    def __init__(self, parent: QWidget | None = None, config: dict | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)   # события не отбирают фокус у других окон
        self.setWindowTitle("SIRIUS — островок")
        self.setAcceptDrops(True)
        self._cfg = normalize(config)
        self._row_h = self._cfg["height"]
        self._radius = self._row_h / 2
        self._body_h = 0
        self._bottom = False                       # капсула у нижнего края: раскрывается вверх
        self._anchor: tuple[int, int] | None = None   # x центра и y края, от которого растёт капсула
        self._screen = None
        self._drag_from: QPointF | None = None
        self._drag_start: QPoint | None = None
        self._dragged = False
        self._reply = ""
        self._asked_here = False
        self._busy = False
        self._target_key: tuple | None = None
        self._shown_key: tuple | None = None
        self._swapping = False
        self._metric_values: dict = {}
        self._metrics_mode = "full"
        self._unread = 0
        self._row_width = -1

        self.states = IslandStateManager(self)
        self.animator = IslandAnimator(self)
        self.animator.frame.connect(self._on_frame)
        self.animator.morph_finished.connect(self._on_morph_finished)

        self._build_row()
        self._build_body()
        self.states.changed.connect(self._on_state_changed)
        self.states.pinned_changed.connect(self.nav.set_pinned)

        for keys, slot in (("Esc", self._on_escape), ("Ctrl+M", self.expand_requested.emit)):
            QShortcut(QKeySequence(keys), self, activated=slot)

        self._reanchor_timer = QTimer(self)
        self._reanchor_timer.setSingleShot(True)
        self._reanchor_timer.setInterval(250)
        self._reanchor_timer.timeout.connect(self._reanchor)
        app = QGuiApplication.instance()
        if app is not None:
            app.screenAdded.connect(self._watch_screen)
            app.screenRemoved.connect(self._on_screens_changed)
            app.primaryScreenChanged.connect(self._on_screens_changed)
            for screen in app.screens():
                self._watch_screen(screen)

        self.apply_config(self._cfg)

    # --- построение ------------------------------------------------------------------

    def _build_row(self) -> None:
        self.row = QWidget(self)
        lay = QHBoxLayout(self.row)
        lay.setContentsMargins(4, 0, 10, 0)
        lay.setSpacing(8)
        self.lisa = MiniLisa()
        self.lisa.clicked.connect(self.avatar_clicked)
        self.lisa.ticked.connect(self._on_lisa_tick)
        lay.addWidget(self.lisa)

        self.input = QLineEdit()
        self.input.setObjectName("islandInput")
        self.input.setPlaceholderText("Спросите LISA…")
        self.input.setMinimumWidth(150)
        self.input.returnPressed.connect(self._send)
        lay.addWidget(self.input, 3)

        self.reply = QLabel("")
        self.reply.setObjectName("secondary")
        self.reply.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.reply.setMinimumWidth(0)
        lay.addWidget(self.reply, 4)

        # что сейчас играет: мини-визуализатор и название
        self.media_chip = RowChip()
        self.media_chip.setToolTip("Управление музыкой")
        self.media_chip.clicked.connect(lambda: self.states.toggle(IslandState.MEDIA))
        self.mini_visualizer = Visualizer(5)
        self.mini_visualizer.setFixedSize(20, 14)
        self.media_icon = QLabel(GLYPHS["music"])
        self.media_icon.setFont(glyph_font(12))
        self.media_text = ElidedLabel("")
        self.media_text.setObjectName("isLine")
        self.media_text.setFixedWidth(130)
        self.media_chip.lay.addWidget(self.media_icon)
        self.media_chip.lay.addWidget(self.mini_visualizer)
        self.media_chip.lay.addWidget(self.media_text)
        self.media_chip.hide()
        lay.addWidget(self.media_chip)

        self.pomo_chip = RowChip()
        self.pomo_chip.setToolTip("Таймер Pomodoro")
        self.pomo_chip.clicked.connect(lambda: self.open_tool("pomodoro"))
        pomo_icon = QLabel(GLYPHS["timer"])
        pomo_icon.setFont(glyph_font(12))
        self.pomo_text = QLabel("25:00")
        self.pomo_text.setObjectName("isMono")
        self.pomo_chip.lay.addWidget(pomo_icon)
        self.pomo_chip.lay.addWidget(self.pomo_text)
        self.pomo_chip.hide()
        lay.addWidget(self.pomo_chip)

        self.bell_btn = IconButton("bell", "Уведомления", 28)
        self.bell_btn.clicked.connect(lambda: self.states.toggle(IslandState.NOTIFICATION))
        self.bell_btn.hide()
        lay.addWidget(self.bell_btn)

        self.metrics = QLabel("")
        self.metrics.setTextFormat(Qt.TextFormat.RichText)
        self.metrics.setStyleSheet(f"font-family: {styles.FONT_MONO}; font-size: 11px;")
        self.metrics.setCursor(Qt.CursorShape.PointingHandCursor)
        self.metrics.setToolTip("Системные индикаторы")
        self.metrics.mouseReleaseEvent = lambda event: self.states.toggle(IslandState.SYSTEM)
        self.metrics.mousePressEvent = lambda event: event.accept()
        lay.addWidget(self.metrics)

        self.voice_btn = QPushButton("VOICE")
        self.voice_btn.setCheckable(True)
        self.voice_btn.setObjectName("islandPill")
        self.voice_btn.setToolTip("Голос LISA (Ctrl+Shift+V)")
        self.voice_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.voice_btn.toggled.connect(self.voice_toggled)
        lay.addWidget(self.voice_btn)

        self.menu_btn = IconButton("down", "Раскрыть островок", 28)
        self.menu_btn.clicked.connect(self._on_menu)
        lay.addWidget(self.menu_btn)

        self.expand_btn = IconButton("expand", "Открыть полное окно SIRIUS (Ctrl+M или Esc)", 28)
        self.expand_btn.clicked.connect(self.expand_requested)
        lay.addWidget(self.expand_btn)

    def _build_body(self) -> None:
        self.body = QWidget(self)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(PAD, 2, PAD, BODY_BOTTOM)
        lay.setSpacing(0)
        self.nav = NavBar()
        self.nav.selected.connect(self.states.open)
        self.nav.pin_toggled.connect(self.states.set_pinned)
        lay.addWidget(self.nav)
        self.pages = QStackedWidget()
        self.hub = HubView()
        self.media_view = MediaView()
        self.system_view = SystemView()
        self.toast = NoteToast()
        self.notes_list = NoteList()
        self.indicator = IndicatorView()
        self.tools = ToolsView()
        for page in (self.hub, self.media_view, self.system_view, self.toast, self.notes_list, self.indicator,
                     self.tools):
            self.pages.addWidget(page)
        lay.addWidget(self.pages, 1)
        self.toast.expand_requested.connect(lambda: self.states.open(IslandState.NOTIFICATION))
        self._fx = QGraphicsOpacityEffect(self.body)
        self._fx.setOpacity(0.0)
        self.body.setGraphicsEffect(self._fx)
        self.body.hide()
        self.body.installEventFilter(self)

    def eventFilter(self, obj, event) -> bool:
        # любое действие в раскрытой капсуле откладывает автоматическое сворачивание
        if obj is self.body and event.type() in (event.Type.MouseButtonPress, event.Type.Wheel, event.Type.KeyPress):
            self.states.touch()
        return super().eventFilter(obj, event)

    # --- настройки -------------------------------------------------------------------

    def config(self) -> dict:
        return dict(self._cfg)

    def apply_config(self, config: dict | None) -> None:
        """Размер, тема, прозрачность, положение, анимации и набор включённых функций."""
        cfg = self._cfg = normalize(config)
        self._row_h = cfg["height"]
        self.row.setFixedHeight(self._row_h)
        self.input.setFixedHeight(max(26, self._row_h - 14))
        self.animator.enabled = cfg["animations"]
        self.animator.speed = cfg["animation_speed"] / 100.0
        duration = 0 if not cfg["animations"] else int(180 / max(0.25, self.animator.speed))
        for bar in (self.media_view.bar, self.indicator.bar, self.tools.pomodoro.bar):
            bar.duration_ms = duration
        self.states.auto_collapse_ms = cfg["auto_collapse_s"] * 1000
        self.states.enabled = cfg["enabled"]
        if not cfg["enabled"]:
            self.states.close()
        self.menu_btn.setVisible(cfg["enabled"])
        self.media_view.visualizer.set_style(cfg["visualizer_style"])
        self.media_view.visualizer.setVisible(cfg["visualizer"])
        self.mini_visualizer.setVisible(cfg["visualizer"])
        self.media_icon.setVisible(not cfg["visualizer"])
        if not (cfg["enabled"] and cfg["media"]):
            self.media_chip.hide()
        if not (cfg["enabled"] and cfg["pomodoro"]):
            self.pomo_chip.hide()
        tools_on = any(cfg[k] for k in ("shelf", "clipboard", "pomodoro", "actions"))
        self.tools.set_features(shelf=cfg["shelf"], clipboard=cfg["clipboard"], pomodoro=cfg["pomodoro"],
                                actions=cfg["actions"])
        available = {IslandState.EXPANDED, IslandState.SYSTEM}
        if cfg["media"]:
            available.add(IslandState.MEDIA)
        if cfg["notifications"] or cfg["notifications_windows"]:
            available.add(IslandState.NOTIFICATION)
        if tools_on:
            available.add(IslandState.INTERACTIVE)
        self._available = available
        self.nav.set_available(available)
        if self.states.base not in available and self.states.base is not IslandState.COMPACT:
            self.states.close()
        self.setStyleSheet(self._style())
        self._reanchor()
        self._fit_row()
        self.update()

    def _style(self) -> str:
        radius = max(10, (self._row_h - 14) // 2)
        return f"""
        QLineEdit#islandInput {{ background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: {radius}px; padding: 0px 12px; color: {WHITE}; selection-background-color: {VIOLET}; }}
        QLineEdit#islandInput:focus {{ border-color: rgba({_rgb(CYAN)}, 0.75); background: rgba(255, 255, 255, 0.09); }}
        QLineEdit#islandInput:disabled {{ color: {TEXT_SECONDARY}; }}
        QLineEdit#islandSearch {{ background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 12px; padding: 2px 10px; min-height: 20px; }}
        QLineEdit#islandSearch:focus {{ border-color: rgba({_rgb(CYAN)}, 0.75); }}
        QPushButton#islandPill {{ background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 12px; padding: 3px 10px; min-height: 16px; font-size: 10px; font-weight: 600;
            letter-spacing: 1px; color: {TEXT_SECONDARY}; }}
        QPushButton#islandPill:hover {{ background: rgba(255, 255, 255, 0.12); color: {WHITE}; }}
        QPushButton#islandPill:checked {{ color: {CYAN}; border-color: rgba({_rgb(CYAN)}, 0.55);
            background: rgba({_rgb(CYAN)}, 0.12); }}
        QFrame#rowChip {{ background: rgba(255, 255, 255, 0.06); border: 1px solid rgba(255, 255, 255, 0.10);
            border-radius: 13px; }}
        QFrame#rowChip:hover {{ background: rgba(255, 255, 255, 0.13); border-color: rgba({_rgb(CYAN)}, 0.45); }}
        QLabel#isTitle {{ font-size: 13px; font-weight: 600; color: {WHITE}; }}
        QLabel#isCaption {{ font-size: 11px; font-weight: 600; letter-spacing: 1px; color: {CYAN}; }}
        QLabel#isSub {{ font-size: 11px; color: {TEXT_SECONDARY}; }}
        QLabel#isLine {{ font-size: 12px; color: #D8DEEA; }}
        QLabel#isReply {{ font-size: 13px; }}
        QLabel#isValue {{ font-size: 13px; font-weight: 600; color: {WHITE}; }}
        QLabel#isMono {{ font-family: {styles.FONT_MONO}; font-size: 11px; color: {TEXT_SECONDARY}; }}
        QLabel#isBig {{ font-size: 40px; font-weight: 300; color: {WHITE}; }}
        QListWidget#islandList {{ background: transparent; border: none; outline: none; padding: 0px; font-size: 11px; }}
        QListWidget#islandList::item {{ padding: 2px; border-radius: 9px; color: #D8DEEA; }}
        QListWidget#islandList::item:hover {{ background: rgba(255, 255, 255, 0.07); }}
        QListWidget#islandList::item:selected {{ background: rgba({_rgb(CYAN)}, 0.18); color: {WHITE}; }}
        QScrollBar:vertical {{ width: 6px; }}
        QScrollBar:horizontal {{ height: 6px; }}
        """

    # --- данные (прежний интерфейс компактной полоски) -------------------------------

    def set_state(self, state: AvatarState) -> None:
        previous = self.lisa.state
        self.lisa.state = state
        self.hub.set_lisa_state(state.name)
        if state is previous or not self.isVisible():
            return
        if state is AvatarState.ERROR:
            self._flash_text("warning", "LISA", "ошибка", ERROR, "Ответ не получен — подробности в чате SIRIUS",
                             4000, CRITICAL_PRIORITY)
        elif state is AvatarState.OFFLINE:
            self._flash_text("warning", "LISA", "офлайн", WARNING, "Ollama недоступна", 4000)
        self.update()

    def set_mood(self, mood: str) -> None:
        self.lisa.mood = mood

    def set_voice(self, enabled: bool) -> None:
        self.voice_btn.blockSignals(True)
        self.voice_btn.setChecked(enabled)
        self.voice_btn.setText("VOICE ON" if enabled else "VOICE OFF")
        self.voice_btn.blockSignals(False)

    def set_busy(self, busy: bool) -> None:
        was_busy, self._busy = self._busy, busy
        self.input.setEnabled(not busy)
        self.input.setPlaceholderText("LISA отвечает…" if busy else "Спросите LISA…")
        self.states.set_busy(busy)
        if not busy:
            if self.isActiveWindow():
                self.input.setFocus()
            if (was_busy and self.isVisible() and self.states.state is IslandState.COMPACT
                    and self._reply.strip() and self.lisa.state is not AvatarState.ERROR):
                self._flash_text("chat", "LISA", "ответ готов", CYAN, " ".join(self._reply.split())[:160], 3000)
            self._asked_here = False

    def begin_reply(self) -> None:
        self._reply = ""
        self.reply.setText("")
        self.hub.set_reply("")
        if (self._asked_here and self._cfg["lisa_expand"] and self.isVisible()
                and self.states.base is IslandState.COMPACT):
            self.states.open(IslandState.EXPANDED)

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
        if self.hub.isVisible() or self.states.base is IslandState.EXPANDED:
            self.hub.set_reply(self._reply)

    def set_metrics(self, values: dict[str, float | None]) -> None:
        self._metric_values = dict(values)
        self._fit_row()
        if self.system_view.isVisible():
            self.system_view.set_metrics(values)

    def _render_metrics(self) -> None:
        values = self._metric_values

        def part(name: str, key: str, unit: str = "%", warn: float = 85.0) -> str:
            v = values.get(key)
            if v is None:
                return f'<span style="color:{TEXT_SECONDARY}">{name} —</span>'
            color = ERROR if v >= warn else WARNING if v >= warn - 15 else SUCCESS if unit == "%" else WHITE
            return f'<span style="color:{TEXT_SECONDARY}">{name}</span> <span style="color:{color}">{v:.0f}{unit}</span>'

        if not values:
            self.metrics.setText("")
            return
        parts = [part("CPU", "cpu")]
        if self._metrics_mode == "full":
            parts += [part("GPU", "gpu"), part("RAM", "ram"), part("VRAM", "vram")]
        else:
            parts.append(part("RAM", "ram"))
        parts.append(part("", "gpu_temp", "°C", warn=85.0))
        self.metrics.setText("&nbsp; ".join(parts))

    def _fit_row(self) -> None:
        """Строка капсулы не переполняется: когда места мало, второстепенное ужимается по очереди —
        сокращённые метрики, значок уведомлений, название трека, метрики целиком."""
        lay = self.row.layout()
        margins = lay.contentsMargins()
        budget = self.row.width() - margins.left() - margins.right()
        fixed = (self.lisa, self.media_chip, self.pomo_chip, self.bell_btn, self.metrics, self.voice_btn,
                 self.menu_btn, self.expand_btn)
        for mode, media_text, bell in (("full", True, True), ("short", True, True), ("short", True, False),
                                       ("short", False, False), ("none", False, False)):
            self._metrics_mode = mode
            self._render_metrics()
            self.metrics.setVisible(mode != "none")
            self.media_text.setVisible(media_text)
            self.bell_btn.setVisible(bell and self._unread > 0 and self._cfg["enabled"])
            shown = [w for w in fixed if not w.isHidden()]
            widths = sum(max(w.minimumWidth(), w.sizeHint().width()) for w in shown)   # у кнопок размер задан жёстко
            need = self.input.minimumWidth() + widths + lay.spacing() * (len(shown) + 1)
            if need + 12 <= budget:
                break

    # --- данные островка -------------------------------------------------------------

    def set_media(self, info) -> None:
        """Что сейчас играет (monitoring.winrt_bridge.MediaInfo) или None."""
        self.media_view.set_media(info)
        show = info is not None and self._cfg["enabled"] and self._cfg["media"]
        if show:
            self.media_text.setText(" — ".join(p for p in (info.title, info.artist) if p) or info.app_name)
            self.media_chip.setToolTip(f"{info.app_name}: {'играет' if info.playing else 'пауза'}")
            if not info.playing:
                self.mini_visualizer.clear()
        self.media_chip.setVisible(show)
        self._fit_row()

    def push_audio_level(self, level: float) -> None:
        """Настоящий уровень звука устройства вывода — для визуализаторов."""
        if self.media_view.isVisible():
            self.media_view.visualizer.push(level)
        if self.media_chip.isVisible():
            self.mini_visualizer.push(level)

    def set_pomodoro(self, text: str | None) -> None:
        """Оставшееся время в строке капсулы; None — таймер не запущен."""
        show = text is not None and self._cfg["enabled"] and self._cfg["pomodoro"]
        if show:
            self.pomo_text.setText(text)
        changed = show != (not self.pomo_chip.isHidden())
        self.pomo_chip.setVisible(show)
        if changed:
            self._fit_row()

    def set_unread(self, count: int) -> None:
        self._unread = count
        self.bell_btn.set_badge(count)
        self.nav.set_unread(count)
        self._fit_row()

    def open_tool(self, tab: str) -> None:
        if self.states.open(IslandState.INTERACTIVE):
            self.tools.show_tab(tab)

    def _flash_text(self, glyph: str, title: str, value: str, color: str, detail: str, ms: int,
                    priority: int | None = None) -> None:
        if self.states.flash(IslandState.SYSTEM, {"kind": "text"}, ms, priority):
            self.indicator.show_text(glyph, title, value, color, detail)

    # --- состояния и анимации --------------------------------------------------------

    def _page_for(self, state: IslandState, transient: bool) -> QWidget | None:
        if state is IslandState.COMPACT:
            return None
        if state is IslandState.EXPANDED:
            return self.hub
        if state is IslandState.MEDIA:
            return self.media_view
        if state is IslandState.INTERACTIVE:
            return self.tools
        if state is IslandState.NOTIFICATION:
            return self.toast if transient else self.notes_list
        if state is IslandState.SYSTEM and not transient:
            return self.system_view
        return self.indicator          # громкость, яркость, питание, Caps Lock и Num Lock

    def _on_state_changed(self, state: IslandState, _payload) -> None:
        transient = self.states.transient is not None
        page = self._page_for(state, transient)
        self._target_key = None if page is None else (page, not transient)
        if not transient and state in USER_STATES:
            self.nav.set_current(state)
        expanded = self.states.base is not IslandState.COMPACT
        self.menu_btn.set_glyph("up" if expanded else "down")
        self.menu_btn.setToolTip("Свернуть островок" if expanded else "Раскрыть островок")
        if state is IslandState.EXPANDED:
            self.hub.set_reply(self._reply)
        self._transition()

    def _body_height(self, key: tuple) -> int:
        page, nav = key
        return 2 + (NavBar.HEIGHT if nav else 0) + page.HEIGHT + BODY_BOTTOM

    def _capsule_height(self, key: tuple | None) -> int:
        return self._row_h if key is None else self._row_h + self._body_height(key)

    def _transition(self) -> None:
        if self._swapping:
            return                       # идёт смена содержимого: по её окончании применится последняя цель
        key = self._target_key
        if key is None:
            if self._shown_key is None and not self.body.isVisible():
                self._morph_to(None)
                return
            self.animator.fade(self._fx, 0.0, 120)
            self._morph_to(None)
        elif self._shown_key is None:
            self._show_page(key)
        elif self._shown_key != key:
            self._swapping = True
            self.animator.fade(self._fx, 0.0, 90, self._after_swap)

    def _after_swap(self) -> None:
        self._swapping = False
        key = self._target_key
        if key is None:
            self._morph_to(None)
        else:
            self._show_page(key)

    def _show_page(self, key: tuple) -> None:
        page, nav = key
        self._shown_key = key
        self.nav.setVisible(nav)
        self.pages.setCurrentWidget(page)
        self._body_h = self._body_height(key)
        self.body.show()
        self._layout_children()
        self.animator.fade(self._fx, 1.0, 220)
        self._morph_to(key)

    def _morph_to(self, key: tuple | None) -> None:
        target = self._rect_for(self._capsule_height(key))
        radius = self._row_h / 2 if key is None else EXPANDED_RADIUS
        if not self.isVisible():
            self._on_frame(target, radius)
            self._on_morph_finished()
            return
        self.animator.morph(self.geometry(), target, self._radius, radius)

    def _on_frame(self, rect: QRect, radius: float) -> None:
        self._radius = radius
        if rect != self.geometry():
            self.setGeometry(rect)
        self.update()

    def _on_morph_finished(self) -> None:
        if self._target_key is None and not self._swapping:
            self.body.hide()
            self._shown_key = None
            self._body_h = 0

    def _on_menu(self) -> None:
        if self.states.base is IslandState.COMPACT:
            self.states.open(IslandState.EXPANDED)
        else:
            self.states.close()

    def _on_escape(self) -> None:
        if self.states.state is not IslandState.COMPACT:
            self.states.close()
        else:
            self.expand_requested.emit()

    def _on_lisa_tick(self) -> None:
        # пульс свечения, пока LISA думает или говорит: перерисовывается только кайма капсулы
        if self.lisa.state in _ACTIVE_STATES and int(self.lisa.phase() * 20) % 2 == 0:
            ring = QRegion(self.rect()) - QRegion(self.rect().adjusted(MARGIN + 3, MARGIN + 3, -MARGIN - 3, -MARGIN - 3))
            self.update(ring)

    # --- окно ------------------------------------------------------------------------

    def _watch_screen(self, screen) -> None:
        screen.geometryChanged.connect(self._on_screens_changed)
        screen.availableGeometryChanged.connect(self._on_screens_changed)
        self._on_screens_changed()

    def _on_screens_changed(self, *_args) -> None:
        # смена разрешения, масштаба, панели задач или набора мониторов: вернуть островок на место
        self._reanchor_timer.start()

    def _pick_screen(self, fallback=None):
        screens = QGuiApplication.screens()
        wanted = self._cfg["screen"]
        for screen in screens:
            if wanted and screen.name() == wanted:
                return screen
        if fallback is not None and fallback in screens:
            return fallback
        if self._screen is not None and self._screen in screens:
            return self._screen
        return QGuiApplication.primaryScreen()

    def place_on_screen(self, screen=None) -> None:
        """Ставит островок на место по настройкам (экран, край, своё положение)."""
        self._screen = self._pick_screen(screen)
        self._reanchor()

    def _reanchor(self) -> None:
        screen = self._screen = self._pick_screen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = self._window_width(area)
        position = self._cfg["position"]
        custom = self._cfg["custom_pos"]
        self._bottom = position == "bottom"
        if position == "custom" and custom:
            cx, top = custom
            cx = max(area.left() + width // 2, min(area.right() - width // 2, cx))
            top = max(area.top(), min(area.bottom() - self._row_h - 2 * MARGIN, top))
            self._bottom = top + self._row_h // 2 > area.center().y()
            edge = top + self._row_h + 2 * MARGIN if self._bottom else top
        else:
            cx = area.center().x()
            if position == "top-left":
                cx = area.left() + EDGE_GAP + width // 2
            elif position == "top-right":
                cx = area.right() - EDGE_GAP - width // 2
            edge = area.bottom() + 1 - EDGE_GAP + MARGIN if self._bottom else area.top() + EDGE_GAP - MARGIN
        self._anchor = (cx, edge)
        self.animator.stop()
        self._swapping = False
        key = self._shown_key if self._target_key is not None else None
        if key is not None:
            self._body_h = self._body_height(key)
            self.animator.fade(self._fx, 1.0, 0)
        self._on_frame(self._rect_for(self._capsule_height(key)), self._row_h / 2 if key is None else EXPANDED_RADIUS)
        self._on_morph_finished()
        self._layout_children()

    def _window_width(self, area: QRect) -> int:
        return min(self._cfg["width"] + 2 * MARGIN, area.width() - 8)

    def _rect_for(self, capsule_height: int) -> QRect:
        screen = self._screen or self._pick_screen()
        area = screen.availableGeometry() if screen is not None else QRect(0, 0, 1920, 1080)
        width = self._window_width(area)
        height = min(capsule_height + 2 * MARGIN, area.height())
        cx, edge = self._anchor or (area.center().x(), area.top())
        x = max(area.left(), min(area.right() + 1 - width, cx - width // 2))
        y = edge - height if self._bottom else edge
        y = max(area.top() - MARGIN, min(area.bottom() + 1 + MARGIN - height, y))
        return QRect(x, y, width, height)

    def _layout_children(self) -> None:
        cap = self.rect().adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        if self._bottom:                # у нижнего края строка остаётся внизу, содержимое раскрывается вверх
            row_y = cap.bottom() + 1 - self._row_h
            self.row.setGeometry(cap.x(), row_y, cap.width(), self._row_h)
            self.body.setGeometry(cap.x(), row_y - self._body_h, cap.width(), self._body_h)
        else:
            self.row.setGeometry(cap.x(), cap.y(), cap.width(), self._row_h)
            self.body.setGeometry(cap.x(), cap.y() + self._row_h, cap.width(), self._body_h)
        if cap.width() != self._row_width:
            self._row_width = cap.width()
            self._fit_row()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_children()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.visibility_changed.emit(True)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self.states.hold(False)
        self.states.close()             # в следующий раз островок появится компактным
        self.visibility_changed.emit(False)

    def enterEvent(self, event) -> None:
        self.states.hold(True)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.states.hold(False)
        super().leaveEvent(event)

    def _send(self) -> None:
        text = self.input.text().strip()
        if text:
            self.input.clear()
            self._asked_here = True
            self.send_requested.emit(text)

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cap = QRectF(self.rect()).adjusted(MARGIN, MARGIN, -MARGIN, -MARGIN)
        radius = min(self._radius, cap.height() / 2)
        top, bottom, border, border_alpha = THEMES.get(self._cfg["theme"], THEMES["graphite"])
        alpha = int(255 * self._cfg["opacity"] / 100)
        accent = self.lisa.color()
        active = self.lisa.state in _ACTIVE_STATES
        pulse = 0.5 + 0.5 * math.sin(self.lisa.phase() * 4) if active else 0.0
        # мягкое свечение цвета состояния LISA вокруг капсулы
        glow = 30 + int(70 * pulse) if active else 20
        p.setBrush(Qt.BrushStyle.NoBrush)
        for step, strength in ((1, 1.0), (2, 0.5), (3, 0.22)):
            p.setPen(QPen(_c(accent, int(glow * strength)), 1.4))
            grown = cap.adjusted(-step, -step, step, step)
            p.drawRoundedRect(grown, radius + step, radius + step)
        fill = QLinearGradient(cap.topLeft(), cap.bottomLeft())
        fill.setColorAt(0.0, _c(top, alpha))
        fill.setColorAt(1.0, _c(bottom, alpha))
        p.setPen(QPen(_c(accent, 150) if active else _c(border, border_alpha), 1.0))
        p.setBrush(fill)
        p.drawRoundedRect(cap.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        if cap.height() > self._row_h + 6:      # тонкая граница между строкой и раскрытой частью
            y = cap.bottom() - self._row_h if self._bottom else cap.top() + self._row_h
            if styles.DOT_MATRIX:               # точечная сетка под содержимым раскрытой части
                shape = QPainterPath()
                shape.addRoundedRect(cap, radius, radius)
                body = (QRectF(cap.left(), cap.top(), cap.width(), y - cap.top()) if self._bottom
                        else QRectF(cap.left(), y, cap.width(), cap.bottom() - y))
                p.save()
                p.setClipPath(shape)
                p.fillRect(body, _dots())
                p.restore()
            line = QLinearGradient(cap.left(), y, cap.right(), y)
            line.setColorAt(0.0, _c(WHITE, 0))
            line.setColorAt(0.5, _c(WHITE, 26))
            line.setColorAt(1.0, _c(WHITE, 0))
            p.setPen(QPen(line, 1.0))
            p.drawLine(QPointF(cap.left() + PAD, y), QPointF(cap.right() - PAD, y))
        p.end()

    # --- перетаскивание островка за свободное место ----------------------------------

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_from = event.globalPosition() - QPointF(self.pos())
            self._drag_start = event.globalPosition().toPoint()
            self._dragged = False

    def mouseMoveEvent(self, event) -> None:
        if self._drag_from is None:
            return
        if not self._dragged:
            if (event.globalPosition().toPoint() - self._drag_start).manhattanLength() < DRAG_THRESHOLD:
                return
            self._dragged = True
            self.animator.stop()
        pos = event.globalPosition() - self._drag_from
        self.move(int(pos.x()), int(pos.y()))

    def mouseReleaseEvent(self, event) -> None:
        dragged, self._drag_from, self._dragged = self._dragged, None, False
        if dragged:
            self._commit_drag()

    def _commit_drag(self) -> None:
        """Новое место островка становится его постоянным положением."""
        screen = QGuiApplication.screenAt(self.geometry().center()) or self._screen
        geo = self.geometry()
        top = geo.bottom() + 1 - self._row_h - 2 * MARGIN if self._bottom else geo.top()
        patch = {"position": "custom", "custom_pos": [geo.left() + geo.width() // 2, top],
                 "screen": screen.name() if screen is not None else ""}
        self._cfg.update(patch)
        self._screen = screen
        self._reanchor()
        self.position_changed.emit(patch)

    # --- файлы: перетаскивание на островок -------------------------------------------

    def _local_files(self, mime) -> list[str]:
        if not mime.hasUrls():
            return []
        return [u.toLocalFile() for u in mime.urls() if u.isLocalFile() and os.path.exists(u.toLocalFile())]

    def dragEnterEvent(self, event) -> None:
        if event.source() is not None and self.isAncestorOf(event.source()):
            event.ignore()               # перетаскивание из самой полки
            return
        if self._cfg["enabled"] and self._cfg["shelf"] and self._local_files(event.mimeData()):
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()
            self.open_tool("shelf")
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if self._cfg["enabled"] and self._cfg["shelf"] and event.mimeData().hasUrls():
            event.setDropAction(Qt.DropAction.CopyAction)
            event.accept()

    def dropEvent(self, event) -> None:
        files = self._local_files(event.mimeData())
        if files and self._cfg["enabled"] and self._cfg["shelf"]:
            event.setDropAction(Qt.DropAction.CopyAction)   # исходный файл остаётся на месте
            event.accept()
            self.files_dropped.emit(files)
        else:
            event.ignore()
