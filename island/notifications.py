"""Очередь уведомлений островка: приоритеты, объединение повторов, защита от спама.

Источники — сам SIRIUS (предупреждения мониторинга, Pomodoro, ошибки LISA) и, если разрешено,
уведомления Windows (monitoring/winrt_bridge.py). Виджетов и таймеров здесь нет.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

LOW, NORMAL, CRITICAL = 0, 1, 2


@dataclass
class Note:
    id: int
    app: str
    title: str
    text: str
    time: float
    priority: int = NORMAL
    icon: bytes | None = None      # значок приложения (PNG), если Windows его отдала
    source: str = "sirius"         # sirius | windows
    count: int = 1                 # сколько одинаковых уведомлений объединено
    silent: bool = False           # попало под защиту от спама: только в журнале
    read: bool = field(default=False, compare=False)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.app.casefold(), self.title.strip().casefold(), self.text.strip().casefold())


class NotificationCenter:
    def __init__(self, history_limit: int = 50, merge_window: float = 60.0, burst_limit: int = 4,
                 burst_window: float = 10.0, clock: Callable[[], float] = time.time) -> None:
        self._history: deque[Note] = deque(maxlen=history_limit)
        self._queue: list[Note] = []
        self._bursts: dict[str, deque[float]] = {}
        self._merge_window = merge_window
        self._burst_limit = burst_limit
        self._burst_window = burst_window
        self._clock = clock
        self._next_id = 1

    def post(self, app: str, title: str, text: str = "", priority: int = NORMAL, icon: bytes | None = None,
             source: str = "sirius", when: float | None = None) -> Note | None:
        """Добавляет уведомление. Возвращает его, если оно встало в очередь показа;
        None — объединено с таким же недавним или скрыто защитой от спама (осталось в журнале)."""
        now = self._clock()
        app = (app or "Система").strip()[:80]
        title = (title or "").strip()[:200]
        text = (text or "").strip()[:2000]
        probe = Note(0, app, title, text, now)
        for old in self._history:
            if old.key == probe.key and now - old.time <= self._merge_window:
                old.count += 1
                old.time = when or now
                old.read = False
                return None
        note = Note(self._next_id, app, title, text, when or now, priority, icon, source)
        self._next_id += 1
        times = self._bursts.setdefault(app.casefold(), deque())
        while times and now - times[0] > self._burst_window:
            times.popleft()
        times.append(now)
        if len(times) > self._burst_limit and priority < CRITICAL:
            note.silent = True
        self._history.appendleft(note)
        if note.silent:
            return None
        self._queue.append(note)
        return note

    def next(self) -> Note | None:
        """Следующее уведомление к показу: сначала важные, внутри приоритета — по порядку."""
        if not self._queue:
            return None
        best = max(self._queue, key=lambda n: (n.priority, -n.id))
        self._queue.remove(best)
        return best

    def top_priority(self) -> int | None:
        """Наибольший приоритет среди ожидающих показа; None — очередь пуста."""
        return max((n.priority for n in self._queue), default=None)

    def requeue(self, note: Note) -> None:
        """Вернуть уведомление в очередь (островок был занят более важным событием)."""
        if note not in self._queue and note in self._history:
            self._queue.append(note)

    def pending(self) -> int:
        return len(self._queue)

    def history(self) -> list[Note]:
        return list(self._history)

    def unread(self) -> int:
        return sum(1 for n in self._history if not n.read)

    def mark_read(self, note_id: int | None = None) -> None:
        for n in self._history:
            if note_id is None or n.id == note_id:
                n.read = True

    def dismiss(self, note_id: int) -> bool:
        for n in list(self._history):
            if n.id == note_id:
                self._history.remove(n)
                if n in self._queue:
                    self._queue.remove(n)
                return True
        return False

    def clear(self) -> None:
        self._history.clear()
        self._queue.clear()
