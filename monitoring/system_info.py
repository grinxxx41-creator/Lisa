"""Снимок системной информации: CPU и RAM через psutil, видеокарта NVIDIA через nvidia-smi.

Только чтение и только реальные значения: если датчик недоступен, значение равно None,
и интерфейс показывает «Unavailable». Модуль не зависит от Qt и вызывается из фонового потока.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger("sirius.monitoring")

NVIDIA_QUERY = "name,utilization.gpu,memory.used,memory.total,temperature.gpu"
NVIDIA_TIMEOUT = 3.0
GPU_RETRY_AFTER = 30.0   # после ошибки nvidia-smi не вызывается так часто
CREATE_NO_WINDOW = 0x08000000  # без мигающего окна консоли на Windows


@dataclass(frozen=True)
class GpuInfo:
    name: str
    utilization: float | None      # %
    memory_used_mb: float | None
    memory_total_mb: float | None
    temperature_c: float | None


@dataclass(frozen=True)
class DiskInfo:
    mount: str
    total: int        # байты
    used: int
    free: int
    percent: float


@dataclass(frozen=True)
class BatteryInfo:
    percent: float
    plugged: bool
    seconds_left: int | None   # None — неизвестно или питание от сети


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    name: str
    cpu_percent: float         # % от всего процессора (0..100)
    rss: int                   # байты


@dataclass(frozen=True)
class SystemSnapshot:
    cpu_percent: float | None
    ram_total: int | None          # байты
    ram_used: int | None
    ram_available: int | None
    ram_percent: float | None
    gpu: GpuInfo | None            # None — видеокарта или nvidia-smi недоступны
    timestamp: float
    # v0.3: всё ниже — None, если недоступно или не собиралось
    cpu_per_core: tuple[float, ...] | None = None
    disks: tuple[DiskInfo, ...] | None = None
    disk_read_bps: float | None = None
    disk_write_bps: float | None = None
    net_recv_bps: float | None = None
    net_sent_bps: float | None = None
    battery: BatteryInfo | None = None
    processes: tuple[ProcessInfo, ...] | None = None
    cpu_temp_c: float | None = None   # Windows без прав администратора обычно не отдаёт


def _number(value: str) -> float | None:
    value = value.strip()
    if not value or value.startswith("[") or value.upper() in ("N/A", "NOT SUPPORTED"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_nvidia_smi(output: str) -> GpuInfo | None:
    """Разбирает первую строку вывода nvidia-smi --format=csv,noheader,nounits."""
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5 or not parts[0]:
            continue
        return GpuInfo(
            name=parts[0],
            utilization=_number(parts[1]),
            memory_used_mb=_number(parts[2]),
            memory_total_mb=_number(parts[3]),
            temperature_c=_number(parts[4]),
        )
    return None


Runner = Callable[[list[str]], str]


def _run_nvidia_smi(args: list[str]) -> str:
    flags = CREATE_NO_WINDOW if sys.platform == "win32" else 0
    done = subprocess.run(
        args, capture_output=True, text=True, timeout=NVIDIA_TIMEOUT, check=True,
        creationflags=flags, encoding="utf-8", errors="replace",
    )
    return done.stdout


class SystemInfoCollector:
    """Собирает снимок. Методы блокирующие: вызывать только из фонового потока."""

    def __init__(self, psutil_module=None, nvidia_smi_path: str | None = "auto",
                 runner: Runner | None = None, clock: Callable[[], float] = time.monotonic) -> None:
        if psutil_module is None:
            try:
                import psutil as psutil_module  # noqa: PLW0127
            except ImportError:
                log.warning("psutil не установлен: CPU и RAM недоступны")
                psutil_module = None
        self._psutil = psutil_module
        self._smi = shutil.which("nvidia-smi") if nvidia_smi_path == "auto" else nvidia_smi_path
        self._runner = runner or _run_nvidia_smi
        self._clock = clock
        self._gpu_retry_at = 0.0
        self._gpu_error_logged = False
        self._last_io: tuple[float, float, float] | None = None    # (время, чтение, запись)
        self._last_net: tuple[float, float, float] | None = None   # (время, принято, отправлено)
        self._procs: dict[int, object] = {}   # psutil.Process между вызовами: нужен для cpu_percent
        self._cores = 1
        self._disks_at = -1e9
        self._disks: tuple[DiskInfo, ...] | None = None
        if self._psutil is not None:
            try:
                self._psutil.cpu_percent(interval=None)  # первый вызов всегда 0: задаём точку отсчёта
                self._psutil.cpu_percent(interval=None, percpu=True)
                self._cores = max(1, int(self._psutil.cpu_count() or 1))
            except Exception:
                log.debug("Не удалось прочитать загрузку CPU", exc_info=True)

    @property
    def has_nvidia_smi(self) -> bool:
        return bool(self._smi)

    def collect(self, processes: bool = False) -> SystemSnapshot:
        """processes=True — также самые тяжёлые процессы (дороже; только пока открыта панель SYSTEM)."""
        cpu = ram_total = ram_used = ram_available = ram_percent = None
        if self._psutil is not None:
            try:
                cpu = float(self._psutil.cpu_percent(interval=None))
            except Exception:
                log.debug("Ошибка чтения CPU", exc_info=True)
            try:
                vm = self._psutil.virtual_memory()
                ram_total, ram_used, ram_available = int(vm.total), int(vm.total - vm.available), int(vm.available)
                ram_percent = float(vm.percent)
            except Exception:
                log.debug("Ошибка чтения RAM", exc_info=True)
        now = self._clock()
        extra: dict = {}
        if self._psutil is not None:
            extra = {
                "cpu_per_core": self._safe(self._collect_cores),
                "disks": self._collect_disks(now),
                "battery": self._safe(self._collect_battery),
                "processes": self._safe(self._collect_processes) if processes else None,
            }
            extra.update(self._collect_rates(now))
        return SystemSnapshot(cpu, ram_total, ram_used, ram_available, ram_percent, self._collect_gpu(), now, **extra)

    @staticmethod
    def _safe(fn):
        try:
            return fn()
        except Exception:
            log.debug("Ошибка чтения системных данных", exc_info=True)
            return None

    def _collect_cores(self) -> tuple[float, ...]:
        return tuple(float(x) for x in self._psutil.cpu_percent(interval=None, percpu=True))

    def _collect_disks(self, now: float) -> tuple[DiskInfo, ...] | None:
        """Место на дисках меняется медленно: раз в 30 с достаточно."""
        if self._disks is not None and now - self._disks_at < 30.0:
            return self._disks
        self._disks_at = now
        disks = []
        try:
            for part in self._psutil.disk_partitions(all=False):
                if "cdrom" in (part.opts or "") or not part.fstype:
                    continue
                try:
                    u = self._psutil.disk_usage(part.mountpoint)
                except OSError:
                    continue
                disks.append(DiskInfo(part.mountpoint, int(u.total), int(u.used), int(u.free), float(u.percent)))
        except Exception:
            log.debug("Ошибка чтения дисков", exc_info=True)
            return self._disks
        self._disks = tuple(disks) or None
        return self._disks

    def _collect_battery(self) -> BatteryInfo | None:
        b = self._psutil.sensors_battery()
        if b is None:
            return None
        left = b.secsleft
        secs = int(left) if isinstance(left, (int, float)) and left >= 0 and not b.power_plugged else None
        return BatteryInfo(float(b.percent), bool(b.power_plugged), secs)

    def _collect_rates(self, now: float) -> dict:
        """Скорость дисков и сети — по разнице счётчиков между вызовами."""
        out: dict = {}
        io = self._safe(lambda: self._psutil.disk_io_counters())
        if io is not None:
            cur = (now, float(io.read_bytes), float(io.write_bytes))
            if self._last_io and now > self._last_io[0]:
                dt = now - self._last_io[0]
                out["disk_read_bps"] = max(0.0, (cur[1] - self._last_io[1]) / dt)
                out["disk_write_bps"] = max(0.0, (cur[2] - self._last_io[2]) / dt)
            self._last_io = cur
        net = self._safe(lambda: self._psutil.net_io_counters())
        if net is not None:
            cur = (now, float(net.bytes_recv), float(net.bytes_sent))
            if self._last_net and now > self._last_net[0]:
                dt = now - self._last_net[0]
                out["net_recv_bps"] = max(0.0, (cur[1] - self._last_net[1]) / dt)
                out["net_sent_bps"] = max(0.0, (cur[2] - self._last_net[2]) / dt)
            self._last_net = cur
        return out

    def _collect_processes(self, limit: int = 8) -> tuple[ProcessInfo, ...]:
        """Самые тяжёлые процессы по CPU и по памяти. Только чтение."""
        seen: dict[int, object] = {}
        rows: list[ProcessInfo] = []
        for proc in self._psutil.process_iter(["pid", "name"]):
            pid = proc.info["pid"]
            if not pid:  # «Бездействие системы» — это не нагрузка
                continue
            cached = self._procs.get(pid, proc)
            seen[pid] = cached
            try:
                with cached.oneshot():
                    cpu = cached.cpu_percent(interval=None) / self._cores
                    rss = cached.memory_info().rss
            except Exception:  # процесс завершился или нет доступа
                continue
            rows.append(ProcessInfo(pid, proc.info.get("name") or "?", float(cpu), int(rss)))
        self._procs = seen
        by_cpu = sorted(rows, key=lambda x: x.cpu_percent, reverse=True)[:limit]
        by_ram = sorted(rows, key=lambda x: x.rss, reverse=True)[:limit]
        merged = {x.pid: x for x in by_cpu + by_ram}
        return tuple(sorted(merged.values(), key=lambda x: (x.cpu_percent, x.rss), reverse=True))

    def _collect_gpu(self) -> GpuInfo | None:
        if not self._smi or self._clock() < self._gpu_retry_at:
            return None
        try:
            output = self._runner([self._smi, f"--query-gpu={NVIDIA_QUERY}", "--format=csv,noheader,nounits"])
            info = parse_nvidia_smi(output)
            if info is None:
                raise ValueError("пустой ответ nvidia-smi")
            self._gpu_error_logged = False
            return info
        except Exception as exc:  # FileNotFoundError, TimeoutExpired, CalledProcessError, ValueError
            self._gpu_retry_at = self._clock() + GPU_RETRY_AFTER
            if not self._gpu_error_logged:
                log.warning("Данные видеокарты недоступны: %s", exc)
                self._gpu_error_logged = True
            return None
