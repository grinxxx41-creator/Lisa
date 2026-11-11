"""Анимации капсулы островка: плавное изменение размера окна и скругления, появление и
исчезновение содержимого. Одновременно работает не больше двух анимаций (форма и прозрачность).
Скорость настраивается, анимации можно отключить — тогда всё применяется сразу."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, QRect, QVariantAnimation, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect

EXPAND_MS = 320
COLLAPSE_MS = 240


class IslandAnimator(QObject):
    frame = Signal(QRect, float)      # геометрия окна и радиус скругления на текущем шаге
    morph_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = True
        self.speed = 1.0              # 2.0 — вдвое быстрее
        self._start = QRect()
        self._end = QRect()
        self._r0 = self._r1 = 0.0
        self._morph = QVariantAnimation(self)
        self._morph.setStartValue(0.0)
        self._morph.setEndValue(1.0)
        self._morph.valueChanged.connect(self._on_step)
        self._morph.finished.connect(self.morph_finished)
        self._fade: QPropertyAnimation | None = None
        self._fade_done: Callable[[], None] | None = None

    def duration(self, ms: int) -> int:
        return 0 if not self.enabled or ms <= 0 else max(1, int(ms / max(0.25, self.speed)))

    def is_morphing(self) -> bool:
        return self._morph.state() == QVariantAnimation.State.Running

    # --- форма -----------------------------------------------------------------------

    def morph(self, start: QRect, end: QRect, radius_from: float, radius_to: float) -> None:
        self._morph.stop()
        expanding = end.height() >= start.height()
        ms = self.duration(EXPAND_MS if expanding else COLLAPSE_MS)
        if ms == 0 or (start == end and abs(radius_from - radius_to) < 0.01):
            self.frame.emit(QRect(end), radius_to)
            self.morph_finished.emit()
            return
        self._start, self._end, self._r0, self._r1 = QRect(start), QRect(end), radius_from, radius_to
        self._morph.setDuration(ms)
        self._morph.setEasingCurve(QEasingCurve.Type.OutQuart if expanding else QEasingCurve.Type.InOutCubic)
        self._morph.start()

    def _on_step(self, t) -> None:
        t = float(t)
        a, b = self._start, self._end

        def mix(x: int, y: int) -> int:
            return round(x + (y - x) * t)

        rect = QRect(mix(a.x(), b.x()), mix(a.y(), b.y()), mix(a.width(), b.width()), mix(a.height(), b.height()))
        self.frame.emit(rect, self._r0 + (self._r1 - self._r0) * t)

    # --- прозрачность содержимого ----------------------------------------------------

    def fade(self, effect: QGraphicsOpacityEffect, target: float, ms: int,
             done: Callable[[], None] | None = None) -> None:
        self._drop_fade()
        self._fade_done = done
        ms = self.duration(ms)
        if ms == 0 or abs(effect.opacity() - target) < 0.01:
            self._apply_opacity(effect, target)
            self._finish_fade()
            return
        effect.setEnabled(True)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(effect.opacity())
        anim.setEndValue(target)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.finished.connect(self._on_fade_finished)
        self._fade = anim
        self._effect, self._target = effect, target
        anim.start()

    def _drop_fade(self) -> None:
        if self._fade is not None:
            self._fade.stop()
            self._fade.deleteLater()
            self._fade = None

    def _on_fade_finished(self) -> None:
        self._drop_fade()
        self._apply_opacity(self._effect, self._target)
        self._finish_fade()

    @staticmethod
    def _apply_opacity(effect: QGraphicsOpacityEffect, target: float) -> None:
        effect.setOpacity(target)
        effect.setEnabled(target < 0.999)     # без эффекта содержимое рисуется напрямую — дешевле

    def _finish_fade(self) -> None:
        done, self._fade_done = self._fade_done, None
        if done is not None:
            done()

    def stop(self) -> None:
        self._morph.stop()
        self._drop_fade()
        self._fade_done = None
