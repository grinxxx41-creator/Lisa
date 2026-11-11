"""Таймер Pomodoro: работа, короткий и длинный перерыв. Только логика, время — по часам системы,
поэтому таймер идёт независимо от того, виден ли островок, и переживает перезапуск SIRIUS."""

from __future__ import annotations

import time
from typing import Any, Callable

WORK, SHORT, LONG = "work", "short", "long"
IDLE, RUNNING, PAUSED = "idle", "running", "paused"
PHASE_TITLES = {WORK: "Работа", SHORT: "Короткий перерыв", LONG: "Длинный перерыв"}


class Pomodoro:
    def __init__(self, work: int = 25, short: int = 5, long: int = 15, rounds: int = 4,
                 clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._minutes = {WORK: work, SHORT: short, LONG: long}
        self.rounds = max(1, rounds)
        self.state = IDLE
        self.phase = WORK
        self.rounds_done = 0          # завершённые рабочие отрезки в текущем цикле
        self._ends_at = 0.0
        self._remaining = float(work * 60)

    # --- настройка -------------------------------------------------------------------

    def configure(self, work: int, short: int, long: int, rounds: int) -> None:
        """Новые длительности действуют со следующего отрезка; простаивающий таймер обновляется сразу."""
        self._minutes = {WORK: work, SHORT: short, LONG: long}
        self.rounds = max(1, rounds)
        if self.state == IDLE:
            self._remaining = self.duration()

    def duration(self, phase: str | None = None) -> float:
        return float(self._minutes[phase or self.phase] * 60)

    # --- управление ------------------------------------------------------------------

    def start(self) -> None:
        if self.state == PAUSED:
            self.resume()
        elif self.state == IDLE:
            self.phase = WORK
            self._begin()

    def pause(self) -> None:
        if self.state == RUNNING:
            self._remaining = max(0.0, self._ends_at - self._clock())
            self.state = PAUSED

    def resume(self) -> None:
        if self.state == PAUSED:
            self._ends_at = self._clock() + self._remaining
            self.state = RUNNING

    def reset(self) -> None:
        """Завершить цикл: таймер возвращается к началу."""
        self.state = IDLE
        self.phase = WORK
        self.rounds_done = 0
        self._remaining = self.duration()

    def skip(self) -> list[str]:
        """Закончить текущий отрезок досрочно и перейти к следующему."""
        if self.state == IDLE:
            return []
        return self._advance()

    def _begin(self) -> None:
        self._remaining = self.duration()
        self._ends_at = self._clock() + self._remaining
        self.state = RUNNING

    # --- время -----------------------------------------------------------------------

    def remaining(self) -> float:
        if self.state == RUNNING:
            return max(0.0, self._ends_at - self._clock())
        return self._remaining

    def progress(self) -> float:
        total = self.duration()
        return 0.0 if total <= 0 else min(1.0, max(0.0, 1.0 - self.remaining() / total))

    def tick(self) -> list[str]:
        """События, наступившие к этому моменту: work_done, break_done, cycle_done."""
        if self.state == RUNNING and self._clock() >= self._ends_at:
            return self._advance()
        return []

    def _advance(self) -> list[str]:
        if self.phase == WORK:
            self.rounds_done += 1
            self.phase = LONG if self.rounds_done % self.rounds == 0 else SHORT
            self._begin()
            return ["work_done"]
        if self.phase == SHORT:
            self.phase = WORK
            self._begin()
            return ["break_done"]
        self.reset()
        return ["cycle_done"]

    # --- сохранение ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        return {"state": self.state, "phase": self.phase, "rounds_done": self.rounds_done,
                "ends_at": self._ends_at if self.state == RUNNING else 0.0,
                "remaining": self.remaining()}

    def restore(self, data: Any) -> list[str]:
        """Восстанавливает таймер после перезапуска. Если отрезок закончился, пока SIRIUS был закрыт,
        следующий отрезок ставится на паузу и возвращается событие — пользователь сам решит, продолжать ли."""
        if not isinstance(data, dict) or data.get("state") not in (RUNNING, PAUSED):
            return []
        if data.get("phase") not in PHASE_TITLES:
            return []
        try:
            rounds_done = max(0, int(data.get("rounds_done", 0)))
            ends_at = float(data.get("ends_at", 0.0))
            remaining = float(data.get("remaining", 0.0))
        except (TypeError, ValueError):
            return []
        self.phase = data["phase"]
        self.rounds_done = rounds_done
        if data["state"] == PAUSED:
            self._remaining = min(self.duration(), max(0.0, remaining))
            self.state = PAUSED
            return []
        if ends_at > self._clock():
            self._ends_at = min(ends_at, self._clock() + self.duration())
            self.state = RUNNING
            return []
        self.state = RUNNING
        events = self._advance()
        if self.state == RUNNING:
            self.pause()
        return events


def format_time(seconds: float) -> str:
    seconds = int(round(max(0.0, seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"
