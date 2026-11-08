"""Предупреждения о состоянии системы: пороги, гистерезис и пауза между повторами. Без Qt.

Предупреждение срабатывает, когда значение держится выше порога заданное время, и повторно —
не раньше чем через COOLDOWN, и только если значение успело опуститься ниже порога с запасом.
"""

from __future__ import annotations

from dataclasses import dataclass

from monitoring.system_info import SystemSnapshot

COOLDOWN = 300.0      # секунд между повторами одного предупреждения
HYSTERESIS = 5.0      # на сколько значение должно опуститься, чтобы предупреждение «сбросилось»

DEFAULT_THRESHOLDS: dict[str, float] = {
    "vram": 92.0,          # % видеопамяти
    "ram": 90.0,           # % оперативной памяти
    "cpu": 95.0,           # % CPU, держится SUSTAIN секунд
    "gpu_temp": 85.0,      # °C
    "cpu_temp": 90.0,      # °C, если датчик доступен
    "disk_free_gb": 5.0,   # ГБ свободно на системном диске — меньше этого
    "battery": 15.0,       # % заряда при работе от батареи — меньше этого
}
SUSTAIN = {"cpu": 15.0, "ram": 10.0, "vram": 5.0}   # секунд выше порога до предупреждения

TITLES = {
    "vram": "Видеопамять почти заполнена",
    "ram": "Мало оперативной памяти",
    "cpu": "Процессор загружен почти полностью",
    "gpu_temp": "Видеокарта сильно нагрелась",
    "cpu_temp": "Процессор сильно нагрелся",
    "disk_free_gb": "Мало места на системном диске",
    "battery": "Низкий заряд батареи",
}


@dataclass(frozen=True)
class Alert:
    kind: str
    title: str
    detail: str
    critical: bool

    @property
    def text(self) -> str:
        return f"{self.title}: {self.detail}"

    def spoken(self) -> str:
        """Короткая фраза для LISA (без символов, которые плохо читаются)."""
        return f"Внимание. {self.title}. {self.detail.replace('%', ' процентов').replace('°C', ' градусов')}."


def _system_disk_free_gb(snap: SystemSnapshot) -> float | None:
    if not snap.disks:
        return None
    for d in snap.disks:
        if d.mount.upper().startswith("C:"):
            return d.free / 1024 ** 3
    return snap.disks[0].free / 1024 ** 3


def _values(snap: SystemSnapshot) -> dict[str, tuple[float | None, str]]:
    """Значение для сравнения (больше — хуже) и подпись для текста."""
    from monitoring.history import snapshot_values

    v = snapshot_values(snap)
    out: dict[str, tuple[float | None, str]] = {}
    for key in ("vram", "ram", "cpu"):
        out[key] = (v[key], "" if v[key] is None else f"{v[key]:.0f}%")
    for key in ("gpu_temp", "cpu_temp"):
        out[key] = (v[key], "" if v[key] is None else f"{v[key]:.0f}°C")
    free = _system_disk_free_gb(snap)
    # «меньше — хуже» переводим в «больше — хуже» через минус
    out["disk_free_gb"] = (None if free is None else -free, "" if free is None else f"свободно {free:.1f} ГБ")
    b = snap.battery
    if b is not None and not b.plugged:
        out["battery"] = (-b.percent, f"заряд {b.percent:.0f}%")
    else:
        out["battery"] = (None, "")
    return out


class AlertMonitor:
    def __init__(self, thresholds: dict[str, float] | None = None, enabled: bool = True) -> None:
        self.enabled = enabled
        self.thresholds = dict(DEFAULT_THRESHOLDS)
        if thresholds:
            self.set_thresholds(thresholds)
        self._above_since: dict[str, float] = {}
        self._fired_at: dict[str, float] = {}
        self._armed: dict[str, bool] = {}

    def set_thresholds(self, thresholds: dict[str, float]) -> None:
        for key, value in thresholds.items():
            if key in DEFAULT_THRESHOLDS:
                try:
                    self.thresholds[key] = float(value)
                except (TypeError, ValueError):
                    pass

    def _limit(self, key: str) -> float:
        t = self.thresholds[key]
        return -t if key in ("disk_free_gb", "battery") else t

    def check(self, snap: SystemSnapshot) -> list[Alert]:
        if not self.enabled:
            return []
        now = snap.timestamp
        fired: list[Alert] = []
        for key, (value, label) in _values(snap).items():
            if value is None:
                self._above_since.pop(key, None)
                continue
            limit = self._limit(key)
            margin = HYSTERESIS if key not in ("disk_free_gb",) else 1.0
            if value < limit - margin:
                self._armed[key] = True
            if value < limit:
                self._above_since.pop(key, None)
                continue
            start = self._above_since.setdefault(key, now)
            if now - start < SUSTAIN.get(key, 0.0):
                continue
            if not self._armed.get(key, True):
                continue
            if now - self._fired_at.get(key, -1e9) < COOLDOWN:
                continue
            self._fired_at[key] = now
            self._armed[key] = False
            critical = key in ("gpu_temp", "cpu_temp", "battery") or value >= limit + 5
            fired.append(Alert(key, TITLES[key], label, critical))
        return fired


def thresholds_from_settings(settings: dict) -> dict[str, float]:
    raw = settings.get("alert_thresholds") or {}
    return {k: v for k, v in raw.items() if k in DEFAULT_THRESHOLDS} if isinstance(raw, dict) else {}


def system_mood(snap: SystemSnapshot, thresholds: dict[str, float] | None = None,
                cpu_average: float | None = None) -> str:
    """Настроение LISA по состоянию компьютера: hot — перегрев, busy — высокая нагрузка, normal."""
    t = dict(DEFAULT_THRESHOLDS)
    t.update(thresholds or {})
    from monitoring.history import snapshot_values

    v = snapshot_values(snap)
    for key in ("gpu_temp", "cpu_temp"):
        if v[key] is not None and v[key] >= t[key]:
            return "hot"
    cpu = cpu_average if cpu_average is not None else v["cpu"]
    if (cpu is not None and cpu >= 85) or (v["gpu"] is not None and v["gpu"] >= 90):
        return "busy"
    for key in ("vram", "ram"):
        if v[key] is not None and v[key] >= t[key]:
            return "busy"
    return "normal"
