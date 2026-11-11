"""Вертикальная боковая панель навигации: значки панелей рабочего пространства.

Используется в темах с боковой навигацией (interface.styles.NAV_SIDE) вместо кнопок в верхней полосе.
Сигналы те же, что у ControlBar, поэтому логика окна не меняется.
"""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import QAbstractButton, QFrame, QVBoxLayout, QWidget

from interface import styles

# значки Segoe Fluent Icons / Segoe MDL2 Assets
ICONS = {
    "chat": "", "code": "", "system": "", "terminal": "", "logs": "",
    "history": "", "hide": "", "reset": "", "settings": "",
}
WIDTH = 56
BUTTON = 40


def _mix(a: QColor, b: QColor, k: float) -> QColor:
    return QColor(round(a.red() + (b.red() - a.red()) * k), round(a.green() + (b.green() - a.green()) * k),
                  round(a.blue() + (b.blue() - a.blue()) * k))


class RailButton(QAbstractButton):
    """Значок с плавным выделением: наведение подсвечивает фон, активный раздел заливается целиком."""

    def __init__(self, icon: str, tooltip: str, checkable: bool = True, fallback: str = "",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon = ICONS.get(icon, "")
        self._fallback = fallback[:1].upper()
        self._on = 0.0       # 0..1 — насколько раздел «включён»
        self._hover = 0.0
        self.setCheckable(checkable)
        self.setFixedSize(BUTTON, BUTTON)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._on_anim = self._animation(190, "_on")
        self._hover_anim = self._animation(130, "_hover")
        self.toggled.connect(self._on_toggled)

    def _animation(self, ms: int, attr: str) -> QVariantAnimation:
        anim = QVariantAnimation(self)
        anim.setDuration(ms)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.valueChanged.connect(lambda v, name=attr: self._set(name, v))
        return anim

    def _set(self, name: str, value) -> None:
        setattr(self, name, float(value))
        self.update()

    def _run(self, anim: QVariantAnimation, current: float, target: float) -> None:
        anim.stop()
        anim.setStartValue(float(current))
        anim.setEndValue(float(target))
        anim.start()

    def _on_toggled(self, checked: bool) -> None:
        self._run(self._on_anim, self._on, 1.0 if checked else 0.0)

    def level(self) -> float:
        return self._on

    def enterEvent(self, event) -> None:   # noqa: N802
        self._run(self._hover_anim, self._hover, 1.0)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:   # noqa: N802
        self._run(self._hover_anim, self._hover, 0.0)
        super().leaveEvent(event)

    def sizeHint(self) -> QSize:   # noqa: N802
        return QSize(BUTTON, BUTTON)

    def paintEvent(self, _event) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        fill = QColor(styles.CYAN)
        hover_alpha = int(30 * self._hover * (1.0 - self._on)) + (18 if self.isDown() else 0)
        fill.setAlpha(min(255, int(255 * self._on) + hover_alpha))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(r, 11, 11)
        # значок: серый → белый при наведении → цвет фона на залитой кнопке
        idle = _mix(QColor(styles.TEXT_SECONDARY), QColor(styles.WHITE), self._hover)
        p.setPen(_mix(idle, QColor(styles.BG), self._on))
        if self._icon:
            font = QFont()
            font.setFamilies(["Segoe Fluent Icons", "Segoe MDL2 Assets"])
            font.setPixelSize(17)
        else:
            font = self.font()
            font.setPixelSize(14)
            font.setBold(True)
        p.setFont(font)
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, self._icon or self._fallback)
        if self._on > 0.02:      # красная точка-метка активного раздела
            dot = QColor(styles.VIOLET)
            dot.setAlpha(int(255 * self._on))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QRectF(0.0, self.height() / 2 - 2, 4, 4))
        p.end()


class SideRail(QFrame):
    toggle_panel = Signal(str)
    hide_all_requested = Signal()
    reset_layout_requested = Signal()
    settings_requested = Signal()

    def __init__(self, panels: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        """panels: (id, короткое название, подсказка) в порядке показа."""
        super().__init__(parent)
        self.setObjectName("sideRail")
        self.setFixedWidth(WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 10)
        layout.setSpacing(6)
        self._buttons: dict[str, RailButton] = {}
        for panel_id, caption, tooltip in panels:
            btn = RailButton(panel_id, f"{caption} — {tooltip}", fallback=caption)
            btn.clicked.connect(lambda _checked=False, pid=panel_id: self.toggle_panel.emit(pid))
            layout.addWidget(btn)
            self._buttons[panel_id] = btn
        layout.addStretch(1)
        self.hide_all_btn = RailButton("hide", "Скрыть все панели", checkable=False)
        self.hide_all_btn.clicked.connect(self.hide_all_requested.emit)
        layout.addWidget(self.hide_all_btn)
        self.reset_btn = RailButton("reset", "Вернуть стандартное расположение панелей", checkable=False)
        self.reset_btn.clicked.connect(self.reset_layout_requested.emit)
        layout.addWidget(self.reset_btn)
        self.settings_btn = RailButton("settings", "Настройки (Ctrl+,)", checkable=False)
        self.settings_btn.clicked.connect(self.settings_requested.emit)
        layout.addWidget(self.settings_btn)

    def button(self, panel_id: str) -> RailButton:
        return self._buttons[panel_id]

    def set_panel_open(self, panel_id: str, is_open: bool) -> None:
        btn = self._buttons.get(panel_id)
        if btn is not None and btn.isChecked() != is_open:
            btn.setChecked(is_open)
