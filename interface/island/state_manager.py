"""Единый диспетчер состояний островка.

Компоненты не меняют интерфейс напрямую: они просят диспетчер открыть состояние (open) или
показать временное событие (flash). Диспетчер решает, что сейчас видно, и сообщает об этом сигналом.

Два слоя:
  основа    — COMPACT или состояние, открытое пользователем; сворачивается само после бездействия,
              если не закреплено;
  временное — событие (громкость, уведомление…) поверх основы; исчезает по таймеру и возвращает основу.
Событие с меньшим приоритетом не вытесняет более важное.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from island.states import TRANSIENT_PRIORITY, USER_STATES, IslandState

MIN_RESUME_MS = 1200      # после ухода курсора событие остаётся ещё хотя бы столько


class IslandStateManager(QObject):
    changed = Signal(object, object)       # IslandState, данные состояния
    pinned_changed = Signal(bool)
    transient_finished = Signal(object)    # IslandState временного события, которое закончилось

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.enabled = True
        self.auto_collapse_ms = 8000
        self._base = IslandState.COMPACT
        self._base_payload: Any = None
        self._transient: IslandState | None = None
        self._transient_payload: Any = None
        self._transient_priority = 0
        self._transient_ms = 0
        self._pinned = False
        self._held = False
        self._busy = False
        self._idle = QTimer(self)
        self._idle.setSingleShot(True)
        self._idle.timeout.connect(self._on_idle)
        self._flash = QTimer(self)
        self._flash.setSingleShot(True)
        self._flash.timeout.connect(self._on_flash_done)

    # --- чтение ----------------------------------------------------------------------

    @property
    def state(self) -> IslandState:
        return self._transient or self._base

    @property
    def payload(self) -> Any:
        return self._transient_payload if self._transient is not None else self._base_payload

    @property
    def base(self) -> IslandState:
        return self._base

    @property
    def transient(self) -> IslandState | None:
        return self._transient

    @property
    def pinned(self) -> bool:
        return self._pinned

    # --- основа ----------------------------------------------------------------------

    def open(self, state: IslandState, payload: Any = None) -> bool:
        """Открыть расширенное состояние по действию пользователя."""
        if not self.enabled or state not in USER_STATES:
            return False
        ended = self._drop_transient()
        self._base, self._base_payload = state, payload
        self._restart_idle()
        self._emit()
        if ended is not None:
            self.transient_finished.emit(ended)
        return True

    def close(self) -> None:
        """Вернуться в компактный режим (закрепление снимается)."""
        ended = self._drop_transient()
        was_compact = self._base is IslandState.COMPACT
        self._base, self._base_payload = IslandState.COMPACT, None
        self._idle.stop()
        if self._pinned:
            self._pinned = False
            self.pinned_changed.emit(False)
        if not was_compact or ended is not None:
            self._emit()
        if ended is not None:
            self.transient_finished.emit(ended)

    def toggle(self, state: IslandState, payload: Any = None) -> None:
        if self._base is state and self._transient is None:
            self.close()
        else:
            self.open(state, payload)

    def set_pinned(self, pinned: bool) -> None:
        if pinned == self._pinned:
            return
        self._pinned = pinned
        self._restart_idle()
        self.pinned_changed.emit(pinned)

    # --- временные события -----------------------------------------------------------

    def flash(self, state: IslandState, payload: Any = None, timeout_ms: int = 2000,
              priority: int | None = None) -> bool:
        """Показать событие на время. False — сейчас видно более важное событие."""
        if not self.enabled:
            return False
        priority = TRANSIENT_PRIORITY.get(state, 0) if priority is None else priority
        if self._transient is not None and priority < self._transient_priority:
            return False
        previous = self._transient if self._transient is not state else None
        self._transient, self._transient_payload = state, payload
        self._transient_priority, self._transient_ms = priority, timeout_ms
        if not self._held:
            self._flash.start(timeout_ms)
        self._emit()
        if previous is not None:
            self.transient_finished.emit(previous)
        return True

    def dismiss_transient(self) -> None:
        ended = self._drop_transient()
        if ended is not None:
            self._restart_idle()
            self._emit()
            self.transient_finished.emit(ended)

    def _drop_transient(self) -> IslandState | None:
        ended = self._transient
        self._flash.stop()
        self._transient, self._transient_payload, self._transient_priority = None, None, 0
        return ended

    def _on_flash_done(self) -> None:
        self.dismiss_transient()

    # --- бездействие -----------------------------------------------------------------

    def hold(self, held: bool) -> None:
        """Курсор над островком: таймеры стоят, чтобы содержимое не исчезло из-под руки."""
        if held == self._held:
            return
        self._held = held
        if held:
            self._idle.stop()
            if self._flash.isActive():
                self._transient_ms = max(MIN_RESUME_MS, self._flash.remainingTime())
                self._flash.stop()
        else:
            if self._transient is not None:
                self._flash.start(max(MIN_RESUME_MS, self._transient_ms))
            self._restart_idle()

    def set_busy(self, busy: bool) -> None:
        """LISA отвечает: расширенный режим не сворачивается, пока идёт ответ."""
        self._busy = busy
        self._restart_idle()

    def touch(self) -> None:
        """Пользователь что-то сделал в островке — отсчёт бездействия начинается заново."""
        self._restart_idle()

    def _restart_idle(self) -> None:
        if (self._base is IslandState.COMPACT or self._pinned or self._held or self._busy
                or self.auto_collapse_ms <= 0):
            self._idle.stop()
        else:
            self._idle.start(self.auto_collapse_ms)

    def _on_idle(self) -> None:
        if self._transient is not None:
            self._restart_idle()      # событие ещё на экране — сворачиваемся после него
            return
        self._base, self._base_payload = IslandState.COMPACT, None
        self._emit()

    def _emit(self) -> None:
        self.changed.emit(self.state, self.payload)
