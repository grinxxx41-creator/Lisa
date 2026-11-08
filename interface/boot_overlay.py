"""Экран запуска SIRIUS: голографические кольца, этапы загрузки и общий прогресс.

Показывается поверх рабочего пространства, пока BootWorker подключает Ollama, загружает Qwen
в видеопамять и готовит голос. Интерфейс под ним уже работает: щелчок или Esc скрывают экран,
загрузка продолжается в фоне. Анимация идёт только пока экран виден.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QRadialGradient
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

from interface.styles import BG, CYAN, ERROR, SUCCESS, TEAL, TEXT_SECONDARY, VIOLET, WARNING, WHITE

FRAME_MS = 33
HOLD_AFTER_DONE_MS = 700      # «Системы готовы» видно чуть дольше, чем один кадр
HOLD_AFTER_FAIL_MS = 1800     # ошибки нужно успеть прочитать
FADE_MS = 450

_MARKS = {"pending": "○", "run": "◌", "ok": "✓", "fail": "✕", "skip": "–"}
_STATE_COLORS = {"pending": TEXT_SECONDARY, "run": CYAN, "ok": SUCCESS, "fail": ERROR, "skip": TEXT_SECONDARY}


def _c(hex_color: str, alpha: int = 255) -> QColor:
    color = QColor(hex_color)
    color.setAlpha(alpha)
    return color


class BootOverlay(QWidget):
    finished = Signal()          # экран скрыт (загрузка завершена или пользователь пропустил)

    def __init__(self, stages, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._order = [key for key, _ in stages]
        self._titles = dict(stages)
        self._states = {key: "pending" for key in self._order}
        self._details = {key: "" for key in self._order}
        self._started = {}
        self._done = False
        self._failed = False
        self._closing = False
        self._t0 = time.monotonic()
        self._progress_shown = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Щёлкните или нажмите Esc — загрузка продолжится в фоне")

        self._effect = QGraphicsOpacityEffect(self)
        self._effect.setOpacity(1.0)
        self.setGraphicsEffect(self._effect)
        self._fade = QPropertyAnimation(self._effect, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setEasingCurve(QEasingCurve.Type.InOutQuad)
        self._fade.finished.connect(self._on_faded)

        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        if parent is not None:
            parent.installEventFilter(self)
            self.setGeometry(parent.rect())

    # --- API -------------------------------------------------------------------------

    def start(self) -> None:
        self.raise_()
        self.show()
        self.setFocus()
        self._timer.start()

    def set_stage(self, key: str, state: str, detail: str = "") -> None:
        if key not in self._states:
            return
        if state == "run" and self._states[key] != "run":
            self._started[key] = time.monotonic()
        self._states[key] = state
        self._details[key] = detail
        if state == "fail" and key in ("ollama", "model"):
            self._failed = True
        self.update()

    def finish(self) -> None:
        """Все этапы завершены: короткая пауза, затем экран плавно исчезает."""
        if self._done:
            return
        self._done = True
        for key, state in self._states.items():
            if state in ("pending", "run"):
                self._states[key] = "skip"
        QTimer.singleShot(HOLD_AFTER_FAIL_MS if self._failed else HOLD_AFTER_DONE_MS, self.dismiss)
        self.update()

    def dismiss(self) -> None:
        if self._closing or not self.isVisible():
            return
        self._closing = True
        self._fade.setStartValue(self._effect.opacity())
        self._fade.setEndValue(0.0)
        self._fade.start()

    def progress(self) -> float:
        """Доля завершённых этапов; этап в работе засчитывается наполовину."""
        if not self._order:
            return 1.0
        score = 0.0
        for state in self._states.values():
            score += 1.0 if state in ("ok", "fail", "skip") else 0.5 if state == "run" else 0.0
        return score / len(self._order)

    def stage_state(self, key: str) -> str:
        return self._states[key]

    # --- события ---------------------------------------------------------------------

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(obj.rect())
        return False

    def mousePressEvent(self, event) -> None:
        self.dismiss()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Escape, Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.dismiss()
        else:
            super().keyPressEvent(event)

    def _on_faded(self) -> None:
        self._timer.stop()
        self.hide()
        self.finished.emit()
        self.deleteLater()

    def _tick(self) -> None:
        target = self.progress()
        self._progress_shown += (target - self._progress_shown) * 0.12
        self.update()

    # --- отрисовка -------------------------------------------------------------------

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        t = time.monotonic() - self._t0

        # затемнение: город за экраном едва виден
        p.fillRect(self.rect(), _c(BG, 228))
        radius = max(60.0, min(w * 0.17, h * 0.21))
        center = QPointF(w / 2, h * 0.40)
        glow = QRadialGradient(center, radius * 2.2)
        glow.setColorAt(0.0, _c(CYAN, 46))
        glow.setColorAt(0.5, _c(VIOLET, 20))
        glow.setColorAt(1.0, _c(BG, 0))
        p.fillRect(self.rect(), glow)

        self._paint_rings(p, center, radius, t)
        self._paint_core(p, center, radius, t)
        self._paint_stages(p, center, radius, w, h, t)
        p.end()

    def _arc(self, p: QPainter, center: QPointF, r: float, start_deg: float, span_deg: float,
             color: QColor, width: float) -> None:
        pen = QPen(color, width)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        rect = QRectF(center.x() - r, center.y() - r, 2 * r, 2 * r)
        p.drawArc(rect, int(start_deg * 16), int(span_deg * 16))

    def _paint_rings(self, p: QPainter, c: QPointF, r: float, t: float) -> None:
        # внешняя шкала из 72 делений, медленно вращается; каждое шестое — длиннее
        p.save()
        p.translate(c)
        p.rotate(t * 6)
        for i in range(72):
            long_tick = i % 6 == 0
            p.setPen(QPen(_c(CYAN, 150 if long_tick else 60), 1.4 if long_tick else 1.0))
            r1 = r * 1.30
            r2 = r * (1.38 if long_tick else 1.34)
            a = math.radians(i * 5)
            p.drawLine(QPointF(math.cos(a) * r1, math.sin(a) * r1), QPointF(math.cos(a) * r2, math.sin(a) * r2))
        p.restore()

        # три вращающиеся дуги в разные стороны
        for k, (color, rr, speed, span, width) in enumerate((
            (CYAN, 1.18, 70, 110, 2.6), (VIOLET, 1.06, -45, 150, 2.0), (TEAL, 0.94, 110, 70, 1.6),
        )):
            for j in range(2):
                start = t * speed + j * 180 + k * 40
                self._arc(p, c, r * rr, start, span, _c(color, 200), width)
                self._arc(p, c, r * rr, start, span, _c(color, 40), width + 6)   # мягкое свечение

        # общий прогресс — кольцо вокруг ядра
        self._arc(p, c, r * 0.80, 90, -360, _c(TEXT_SECONDARY, 35), 4)
        progress = max(0.0, min(1.0, self._progress_shown))
        color = ERROR if self._failed and self._done else SUCCESS if self._done else CYAN
        self._arc(p, c, r * 0.80, 90, -360 * progress, _c(color, 230), 4)
        self._arc(p, c, r * 0.80, 90, -360 * progress, _c(color, 50), 12)

    def _paint_core(self, p: QPainter, c: QPointF, r: float, t: float) -> None:
        pulse = 0.5 + 0.5 * math.sin(t * 2.4)
        core = QRadialGradient(c, r * 0.66)
        core.setColorAt(0.0, _c(CYAN, int(40 + 30 * pulse)))
        core.setColorAt(1.0, _c(BG, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(core)
        p.drawEllipse(c, r * 0.66, r * 0.66)

        title = QFont("Segoe UI", max(14, int(r * 0.20)), QFont.Weight.DemiBold)
        title.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 125)
        p.setFont(title)
        p.setPen(_c(WHITE))
        p.drawText(QRectF(c.x() - r, c.y() - r * 0.30, 2 * r, r * 0.34), Qt.AlignmentFlag.AlignCenter, "SIRIUS")

        small = QFont("Segoe UI", max(8, int(r * 0.058)))
        small.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 118)
        p.setFont(small)
        p.setPen(_c(TEXT_SECONDARY))
        p.drawText(QRectF(c.x() - r, c.y() + r * 0.06, 2 * r, r * 0.16), Qt.AlignmentFlag.AlignCenter,
                   "LISA  ·  ИНИЦИАЛИЗАЦИЯ")
        percent = QFont("Consolas", max(9, int(r * 0.09)))
        p.setFont(percent)
        p.setPen(_c(CYAN, 220))
        p.drawText(QRectF(c.x() - r, c.y() + r * 0.24, 2 * r, r * 0.18), Qt.AlignmentFlag.AlignCenter,
                   f"{round(self._progress_shown * 100):3d} %")

    def _paint_stages(self, p: QPainter, c: QPointF, r: float, w: int, h: int, t: float) -> None:
        row_h = max(22, int(h * 0.036))
        width = min(520, int(w * 0.8))
        x = (w - width) / 2
        y = c.y() + r * 1.55
        mono = QFont("Consolas", max(9, int(row_h * 0.46)))
        p.setFont(mono)
        for key in self._order:
            state = self._states[key]
            color = _c(_STATE_COLORS[state])
            mark = _MARKS[state]
            if state == "run":
                mark = "◐◓◑◒"[int(t * 8) % 4]
            p.setPen(color)
            p.drawText(QRectF(x, y, 24, row_h), Qt.AlignmentFlag.AlignVCenter, mark)
            p.setPen(_c(WHITE if state in ("run", "ok") else TEXT_SECONDARY))
            p.drawText(QRectF(x + 26, y, width * 0.6, row_h), Qt.AlignmentFlag.AlignVCenter,
                       self._titles[key].upper())
            detail = self._details[key]
            if state == "run" and not detail:
                detail = f"{time.monotonic() - self._started.get(key, time.monotonic()):.1f} с"
            p.setPen(color if state != "ok" else _c(TEXT_SECONDARY))
            p.drawText(QRectF(x, y, width, row_h), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       detail)
            # тонкая линия-разделитель со сканирующим бликом у активного этапа
            p.setPen(QPen(_c(CYAN, 30), 1))
            p.drawLine(QPointF(x, y + row_h), QPointF(x + width, y + row_h))
            if state == "run":
                pos = (t * 0.6) % 1.0
                p.setPen(QPen(_c(CYAN, 170), 1.5))
                p.drawLine(QPointF(x + width * pos, y + row_h), QPointF(x + width * min(1, pos + 0.12), y + row_h))
            y += row_h + 4

        hint = QFont("Segoe UI", max(8, int(row_h * 0.38)))
        p.setFont(hint)
        if self._done:
            text, color = (("ЧАСТЬ СИСТЕМ НЕДОСТУПНА — ПОДРОБНОСТИ В СТРОКЕ СОСТОЯНИЯ", WARNING) if self._failed
                           else ("СИСТЕМЫ ГОТОВЫ", SUCCESS))
        else:
            text, color = "Щёлкните или нажмите Esc — загрузка продолжится в фоне", TEXT_SECONDARY
        p.setPen(_c(color, 200))
        p.drawText(QRectF(0, y + 10, w, row_h), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, text)
