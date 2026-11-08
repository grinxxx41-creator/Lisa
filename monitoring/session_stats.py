"""Сводка за сессию: пики нагрузки и температур, работа модели. Только в памяти. Без Qt."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from monitoring.history import snapshot_values
from monitoring.system_info import SystemSnapshot

PEAK_KEYS = ("cpu", "ram", "gpu", "vram", "gpu_temp", "cpu_temp")


@dataclass
class GenerationStats:
    """Итог одного ответа модели по данным Ollama."""
    tokens: int
    tokens_per_second: float | None
    first_token_seconds: float | None
    load_seconds: float | None = None


def parse_ollama_stats(done_chunk: dict, first_token_seconds: float | None = None) -> GenerationStats | None:
    """Последний фрагмент потока Ollama (done=true) содержит счётчики и длительности в наносекундах."""
    count = done_chunk.get("eval_count")
    if not isinstance(count, int):
        return None
    duration = done_chunk.get("eval_duration") or 0
    tps = count / (duration / 1e9) if duration else None
    load = done_chunk.get("load_duration")
    return GenerationStats(count, tps, first_token_seconds, load / 1e9 if isinstance(load, (int, float)) else None)


@dataclass
class SessionStats:
    started: float = field(default_factory=time.monotonic)
    peaks: dict[str, float] = field(default_factory=dict)
    responses: int = 0
    tokens: int = 0
    last: GenerationStats | None = None
    _tps: list[float] = field(default_factory=list)
    _ttft: list[float] = field(default_factory=list)
    alerts: int = 0

    def add_snapshot(self, snap: SystemSnapshot) -> None:
        values = snapshot_values(snap)
        for key in PEAK_KEYS:
            v = values.get(key)
            if v is not None and v > self.peaks.get(key, float("-inf")):
                self.peaks[key] = v

    def add_generation(self, stats: GenerationStats) -> None:
        self.responses += 1
        self.tokens += stats.tokens
        self.last = stats
        if stats.tokens_per_second:
            self._tps.append(stats.tokens_per_second)
        if stats.first_token_seconds is not None:
            self._ttft.append(stats.first_token_seconds)

    @property
    def avg_tokens_per_second(self) -> float | None:
        return sum(self._tps) / len(self._tps) if self._tps else None

    @property
    def avg_first_token(self) -> float | None:
        return sum(self._ttft) / len(self._ttft) if self._ttft else None

    def uptime(self, now: float | None = None) -> float:
        return (now if now is not None else time.monotonic()) - self.started


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h} ч {m:02d} мин" if h else f"{m} мин {s:02d} с"
