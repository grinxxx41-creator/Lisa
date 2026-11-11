"""Анимации капсулы островка: плавное изменение формы и скругления, появление и исчезновение содержимого.

Форма анимируется дробными координатами (QRectF): окно островка на время анимации занимает общую область
начального и конечного положения, а растёт только нарисованная капсула. Так системное окно меняет размер
дважды за переход, а не на каждом кадре, — без рывков и мерцания.
Скорость настраивается, анимации можно отключить — тогда всё применяется сразу."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QEasingCurve, QObject, QPointF, QPropertyAnimation, QRectF, QVariantAnimation, Signal
from PySide6.QtWidgets import QGraphicsOpacityEffect

EXPAND_MS = 480
COLLAPSE_MS = 380
OVERSHOOT = 0.75          # лёгкий «пружинящий» выход за конечный размер при раскрытии
OVERSHOOT_SHARE = 0.04    # на какую долю изменения размера капсула может выйти за цель (с запасом)


def _expand_curve() -> QEasingCurve:
    curve = QEasingCurve(QEasingCurve.Type.OutBack)
    curve.setOvershoot(OVERSHOOT)
    return curve


def _collapse_curve() -> QEasingCurve:
    # медленный старт и мягкая остановка, как у стандартных переходов iOS и Material
    curve = QEasingCurve(QEasingCurve.Type.BezierSpline)
    curve.addCubicBezierSegment(QPointF(0.4, 0.0), QPointF(0.2, 1.0), QPointF(1.0, 1.0))
    return curve


class IslandAnimator(QObject):
    frame = Signal(QRectF, float)     # положение капсулы (с полями окна) и радиус скругления на текущем шаге
    morph_finished = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = True
        self.speed = 1.0              # 2.0 — вдвое быстрее
        self._start = QRectF()
        self._end = QRectF()
        self._r0 = self._r1 = 0.0
        self._morph = QVariantAnimation(self)
        self._morph.setStartValue(0.0)
        self._morph.setEndValue(1.0)
        self._morph.valueChanged.connect(self._on_step)
        self._morph.finished.connect(self._on_morph_done)
        # прозрачность: по одной анимации на эффект (строка, раскрытая часть, мини-капсула)
        self._fades: dict[int, tuple[QPropertyAnimation, QGraphicsOpacityEffect, float, Callable[[], None] | None]] = {}

    def duration(self, ms: int) -> int:
        return 0 if not self.enabled or ms <= 0 else max(1, int(ms / max(0.25, self.speed)))

    def is_morphing(self) -> bool:
        return self._morph.state() == QVariantAnimation.State.Running

    # --- форма -----------------------------------------------------------------------

    def morph(self, start, end, radius_from: float, radius_to: float) -> None:
        self._morph.stop()
        start, end = QRectF(start), QRectF(end)
        expanding = end.width() * end.height() >= start.width() * start.height()
        ms = self.duration(EXPAND_MS if expanding else COLLAPSE_MS)
        if ms == 0 or (start == end and abs(radius_from - radius_to) < 0.01):
            self.frame.emit(QRectF(end), radius_to)
            self.morph_finished.emit()
            return
        self._start, self._end, self._r0, self._r1 = start, end, radius_from, radius_to
        self._morph.setDuration(ms)
        self._morph.setEasingCurve(_expand_curve() if expanding else _collapse_curve())
        self._morph.start()

    def _on_morph_done(self) -> None:
        # последний кадр — точно конечная форма: окно принимает итоговый размер без скачка
        self.frame.emit(QRectF(self._end), self._r1)
        self.morph_finished.emit()

    def _on_step(self, t) -> None:
        t = float(t)
        a, b = self._start, self._end

        def mix(x: float, y: float) -> float:
            return x + (y - x) * t

        rect = QRectF(mix(a.x(), b.x()), mix(a.y(), b.y()), max(1.0, mix(a.width(), b.width())),
                      max(1.0, mix(a.height(), b.height())))
        self.frame.emit(rect, max(0.0, self._r0 + (self._r1 - self._r0) * t))

    # --- прозрачность содержимого ----------------------------------------------------

    def fade(self, effect: QGraphicsOpacityEffect, target: float, ms: int,
             done: Callable[[], None] | None = None,
             curve: QEasingCurve.Type = QEasingCurve.Type.OutCubic) -> None:
        """Плавно меняет прозрачность эффекта. Новый вызов для того же эффекта отменяет прежний
        (его done не вызывается); разные эффекты анимируются одновременно."""
        self._drop_fade(effect)
        ms = self.duration(ms)
        if ms == 0 or abs(effect.opacity() - target) < 0.01:
            self._apply_opacity(effect, target)
            if done is not None:
                done()
            return
        effect.setEnabled(True)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(effect.opacity())
        anim.setEndValue(target)
        anim.setEasingCurve(curve)
        key = id(effect)
        anim.finished.connect(lambda k=key: self._on_fade_finished(k))
        self._fades[key] = (anim, effect, target, done)
        anim.start()

    def is_fading(self, effect: QGraphicsOpacityEffect) -> bool:
        return id(effect) in self._fades

    def _drop_fade(self, effect: QGraphicsOpacityEffect) -> None:
        entry = self._fades.pop(id(effect), None)
        if entry is not None:
            entry[0].stop()
            entry[0].deleteLater()

    def _on_fade_finished(self, key: int) -> None:
        entry = self._fades.pop(key, None)
        if entry is None:
            return
        anim, effect, target, done = entry
        anim.deleteLater()
        self._apply_opacity(effect, target)
        if done is not None:
            done()

    @staticmethod
    def _apply_opacity(effect: QGraphicsOpacityEffect, target: float) -> None:
        effect.setOpacity(target)
        effect.setEnabled(target < 0.999)     # без эффекта содержимое рисуется напрямую — дешевле

    def stop(self) -> None:
        self._morph.stop()
        for anim, _effect, _target, _done in self._fades.values():
            anim.stop()
            anim.deleteLater()
        self._fades.clear()
