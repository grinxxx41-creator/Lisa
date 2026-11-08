"""Постоянный мониторинг (v0.3): снимок системы раз в 2 секунды для графиков, предупреждений,
компактного режима и ответов LISA о состоянии компьютера.

Сбор идёт в фоновом потоке (SystemInfoWorker). Список процессов дорогой (~0,7 с), поэтому
собирается только пока открыта панель SYSTEM (set_detail(True)) и не на каждом шаге.
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QObject, Signal

from interface.workers import SystemInfoWorker
from monitoring.alerts import Alert, AlertMonitor
from monitoring.history import MetricsHistory
from monitoring.session_stats import GenerationStats, SessionStats
from monitoring.system_info import SystemInfoCollector, SystemSnapshot

log = logging.getLogger("sirius.monitor")

INTERVAL_MS = 2000
PROCESSES_EVERY = 2       # процессы — каждый второй снимок (раз в 4 с)


class MonitorService(QObject):
    updated = Signal(object)          # SystemSnapshot
    models_updated = Signal(object)   # list[(имя, байт VRAM)] | None
    alert = Signal(object)            # monitoring.alerts.Alert
    generation = Signal(object)       # GenerationStats последнего ответа

    def __init__(self, collector_factory: Callable[[], SystemInfoCollector] = SystemInfoCollector,
                 models_source: Callable[[], list] | None = None, interval_ms: int = INTERVAL_MS,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._collector_factory = collector_factory
        self._models_source = models_source
        self._interval_ms = interval_ms
        self._worker: SystemInfoWorker | None = None
        self._detail = False
        self._tick = 0
        self.history = MetricsHistory()
        self.stats = SessionStats()
        self.alerts = AlertMonitor()
        self.last_snapshot: SystemSnapshot | None = None
        self.last_processes = None
        self.last_models: list | None = None
        self.model_vram: float | None = None
        self.model_name = ""

    # --- управление ------------------------------------------------------------------

    def start(self) -> None:
        if self.is_running():
            return
        collector = self._collector_factory()
        self._worker = SystemInfoWorker(collector, self._models_source, self._interval_ms, models_every=3,
                                        processes_source=self._want_processes, parent=self)
        self._worker.snapshot.connect(self._on_snapshot)
        self._worker.models.connect(self._on_models)
        self._worker.start()

    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def set_detail(self, enabled: bool) -> None:
        """Подробный режим (список процессов) — пока открыта панель SYSTEM."""
        self._detail = enabled

    @property
    def detail(self) -> bool:
        return self._detail

    def _want_processes(self) -> bool:
        # вызывается из рабочего потока: только чтение простых значений
        self._tick += 1
        return self._detail and self._tick % PROCESSES_EVERY == 1

    def shutdown(self, timeout_ms: int = 4000) -> None:
        if self._worker is not None:
            self._worker.stop()
            if not self._worker.wait(timeout_ms):
                log.error("Поток мониторинга не завершился за %d мс", timeout_ms)
            self._worker = None

    # --- данные ----------------------------------------------------------------------

    def _on_snapshot(self, snap: SystemSnapshot) -> None:
        self.last_snapshot = snap
        if snap.processes is not None:
            self.last_processes = snap.processes
        self.history.add(snap)
        self.stats.add_snapshot(snap)
        for item in self.alerts.check(snap):
            self.stats.alerts += 1
            log.warning("Предупреждение: %s", item.text)
            self.alert.emit(item)
        self.updated.emit(snap)

    def _on_models(self, models) -> None:
        self.last_models = models
        vram = None
        if models and self.model_name:
            wanted = self.model_name if ":" in self.model_name else f"{self.model_name}:latest"
            for name, size in models:
                if name in (self.model_name, wanted):
                    vram = float(size)
        self.model_vram = vram
        self.models_updated.emit(models)

    def add_generation(self, stats: GenerationStats) -> None:
        self.stats.add_generation(stats)
        self.generation.emit(stats)

    def inject(self, snap: SystemSnapshot) -> None:
        """Для тестов: подать снимок как от фонового потока."""
        self._on_snapshot(snap)


__all__ = ["MonitorService", "Alert"]
