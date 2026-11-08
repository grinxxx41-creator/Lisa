"""История значений метрик за последние минуты — только в памяти, без баз данных. Без Qt."""

from __future__ import annotations

from collections import deque

from monitoring.system_info import SystemSnapshot

WINDOW_SECONDS = 300.0   # графики показывают последние 5 минут

# метрики в процентах (0..100), которые рисуются на графиках
SERIES = ("cpu", "ram", "gpu", "vram")


def snapshot_values(snap: SystemSnapshot) -> dict[str, float | None]:
    """Проценты загрузки и прочие числа из снимка. None — значение недоступно."""
    gpu = snap.gpu
    vram = None
    if gpu is not None and gpu.memory_used_mb is not None and gpu.memory_total_mb:
        vram = gpu.memory_used_mb / gpu.memory_total_mb * 100
    return {
        "cpu": snap.cpu_percent,
        "ram": snap.ram_percent,
        "gpu": gpu.utilization if gpu is not None else None,
        "vram": vram,
        "gpu_temp": gpu.temperature_c if gpu is not None else None,
        "cpu_temp": snap.cpu_temp_c,
        "net_down": snap.net_recv_bps,
        "net_up": snap.net_sent_bps,
        "disk_read": snap.disk_read_bps,
        "disk_write": snap.disk_write_bps,
    }


class MetricsHistory:
    def __init__(self, window: float = WINDOW_SECONDS) -> None:
        self.window = window
        self._data: dict[str, deque[tuple[float, float]]] = {}
        self.last_time: float | None = None

    def add(self, snap: SystemSnapshot) -> None:
        t = snap.timestamp
        self.last_time = t
        for key, value in snapshot_values(snap).items():
            if value is None:
                continue
            series = self._data.setdefault(key, deque())
            series.append((t, float(value)))
            while series and series[0][0] < t - self.window:
                series.popleft()

    def series(self, key: str) -> list[tuple[float, float]]:
        return list(self._data.get(key, ()))

    def latest(self, key: str) -> float | None:
        s = self._data.get(key)
        return s[-1][1] if s else None

    def average(self, key: str, seconds: float) -> float | None:
        s = self._data.get(key)
        if not s:
            return None
        since = s[-1][0] - seconds
        values = [v for t, v in s if t >= since]
        return sum(values) / len(values) if values else None
