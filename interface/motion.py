"""Общие плавные переходы интерфейса: появление панели и смена вкладки."""

from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QObject, QPropertyAnimation, Slot
from PySide6.QtWidgets import QGraphicsOpacityEffect, QTabWidget, QWidget

PANEL_MS = 190
TAB_MS = 150


class _Fade(QObject):
    """Плавно проявляет виджет и снимает эффект, чтобы дальше он рисовался как обычно."""

    def __init__(self, widget: QWidget, ms: int) -> None:
        super().__init__(widget)
        self._widget = widget
        self._effect = QGraphicsOpacityEffect(widget)
        self._effect.setOpacity(0.0)
        widget.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._anim.setDuration(ms)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._done)
        self._anim.start()

    @Slot()
    def _done(self) -> None:
        if self._widget.graphicsEffect() is self._effect:
            self._widget.setGraphicsEffect(None)
        self.deleteLater()


def fade_in(widget: QWidget | None, ms: int = PANEL_MS) -> bool:
    """Запускает проявление. Ничего не делает для невидимого виджета и если переход уже идёт."""
    if widget is None or ms <= 0 or not widget.isVisible() or widget.graphicsEffect() is not None:
        return False
    _Fade(widget, ms)
    return True


class _TabFader(QObject):
    def __init__(self, tabs: QTabWidget) -> None:
        super().__init__(tabs)
        self._tabs = tabs
        tabs.currentChanged.connect(self._on_changed)

    @Slot(int)
    def _on_changed(self, index: int) -> None:
        fade_in(self._tabs.widget(index), TAB_MS)


def animate_tabs(tabs: QTabWidget) -> None:
    """Содержимое вкладки плавно проявляется при переключении."""
    _TabFader(tabs)
