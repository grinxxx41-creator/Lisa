"""Панель SYSTEM: загрузка CPU, RAM и видеокарты, графики, процессы, диски и сеть, сводка сессии,
состояние Ollama и голоса.

v0.3: данные приходят от MonitorService (постоянный мониторинг). Пока панель открыта, служба
дополнительно собирает список процессов. Без службы (тесты, v0.2) панель опрашивает систему сама,
только пока открыта. Недоступные значения показываются как «Unavailable».
"""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QSizePolicy,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from interface.charts import CoreBars, LineChart, format_rate
from interface.motion import animate_tabs
from interface.styles import CYAN, TEAL, TEXT_SECONDARY, VIOLET, WARNING
from interface.workers import SystemInfoWorker
from interface.workspace.panel_titlebar import StatusDot
from monitoring.session_stats import GenerationStats, format_duration
from monitoring.system_info import SystemInfoCollector, SystemSnapshot

log = logging.getLogger("sirius.ui.system")

UNAVAILABLE = "Unavailable"
HIGH_LOAD = 85.0


def _gb(value_bytes: float) -> str:
    return f"{value_bytes / 1024 ** 3:.1f}"


class SystemPanel(QWidget):
    def __init__(self, collector_factory: Callable[[], SystemInfoCollector] = SystemInfoCollector,
                 models_source: Callable[[], list] | None = None, interval_ms: int = 1500,
                 service=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._collector_factory = collector_factory
        self._collector: SystemInfoCollector | None = None
        self._models_source = models_source
        self._interval_ms = interval_ms
        self._service = service
        self._worker: SystemInfoWorker | None = None
        self._threads: list[SystemInfoWorker] = []   # все потоки, которые ещё не убраны
        self._model_name = ""
        self._ollama_ready = False
        self._visible = False
        self.last_snapshot: SystemSnapshot | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.tabs.setObjectName("sysTabs")
        self.tabs.setDocumentMode(True)
        animate_tabs(self.tabs)
        outer.addWidget(self.tabs)

        self.tabs.addTab(self._build_overview(), "Обзор")
        self.tabs.addTab(self._build_charts(), "Графики")
        self.tabs.addTab(self._build_processes(), "Процессы")
        self.tabs.addTab(self._build_io(), "Диски и сеть")
        self.tabs.addTab(self._build_session(), "Сессия")
        self.tabs.currentChanged.connect(lambda _i: self._refresh_from_service())

        self._show_unavailable()
        self.ollama_value.setText("Проверка…")
        self.model_value.setText("Проверка…")

        if service is not None:
            service.updated.connect(self.apply_snapshot)
            service.models_updated.connect(self.apply_models)
            service.generation.connect(self.apply_generation)

    # --- построение -------------------------------------------------------------

    @staticmethod
    def _name(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("metricName")
        label.setFixedWidth(52)
        return label

    def _build_overview(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(6, 4, 6, 2)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        grid.setColumnStretch(1, 1)
        self.cpu_bar, self.cpu_value = self._metric_row(grid, 0, "CPU")
        self.ram_bar, self.ram_value = self._metric_row(grid, 1, "RAM")
        self.gpu_bar, self.gpu_value = self._metric_row(grid, 2, "GPU")
        self.vram_bar, self.vram_value = self._metric_row(grid, 3, "VRAM")
        self.temp_dot, self.temp_value = self._status_row(grid, 4, "TEMP")
        self.power_dot, self.power_value = self._status_row(grid, 5, "POWER")
        self.ollama_dot, self.ollama_value = self._status_row(grid, 6, "OLLAMA")
        self.model_dot, self.model_value = self._status_row(grid, 7, "MODEL")
        self.speed_dot, self.speed_value = self._status_row(grid, 8, "SPEED")
        self.piper_dot, self.piper_value = self._status_row(grid, 9, "VOICE")
        grid.setRowStretch(10, 1)
        self.speed_value.setText("ещё не было ответов")
        return page

    def _build_charts(self) -> QWidget:
        page = QWidget()
        grid = QGridLayout(page)
        grid.setContentsMargins(4, 4, 4, 2)
        grid.setSpacing(5)
        self.cpu_chart = LineChart("CPU", CYAN)
        self.gpu_chart = LineChart("GPU", VIOLET)
        self.ram_chart = LineChart("RAM", TEAL)
        self.vram_chart = LineChart("VRAM", WARNING)
        grid.addWidget(self.cpu_chart, 0, 0)
        grid.addWidget(self.gpu_chart, 0, 1)
        grid.addWidget(self.ram_chart, 1, 0)
        grid.addWidget(self.vram_chart, 1, 1)
        self.core_bars = CoreBars(CYAN)
        grid.addWidget(self.core_bars, 2, 0, 1, 2)
        return page

    def _build_processes(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(4, 4, 4, 2)
        lay.setSpacing(3)
        self.proc_table = QTableWidget(0, 3)
        self.proc_table.setObjectName("procTable")
        self.proc_table.setHorizontalHeaderLabels(["Процесс", "CPU", "Память"])
        self.proc_table.verticalHeader().setVisible(False)
        self.proc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.proc_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.proc_table.setShowGrid(False)
        self.proc_table.verticalHeader().setDefaultSectionSize(20)
        header = self.proc_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        lay.addWidget(self.proc_table, 1)
        self.proc_hint = QLabel("Только просмотр: SIRIUS не завершает процессы. Обновление раз в 4 с.")
        self.proc_hint.setObjectName("metricName")
        self.proc_hint.setWordWrap(True)
        lay.addWidget(self.proc_hint)
        return page

    def _build_io(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(6, 4, 6, 2)
        lay.setSpacing(4)
        self.disk_grid = QGridLayout()
        self.disk_grid.setHorizontalSpacing(10)
        self.disk_grid.setColumnStretch(1, 1)
        lay.addLayout(self.disk_grid)
        self._disk_rows: dict[str, tuple[QProgressBar, QLabel]] = {}
        self.disk_io_value = QLabel("Диски: чтение — · запись —")
        self.disk_io_value.setObjectName("metricValue")
        lay.addWidget(self.disk_io_value)
        charts = QHBoxLayout()
        charts.setSpacing(5)
        self.net_down_chart = LineChart("Сеть ↓", CYAN, unit="rate", max_value=None)
        self.net_up_chart = LineChart("Сеть ↑", VIOLET, unit="rate", max_value=None)
        charts.addWidget(self.net_down_chart)
        charts.addWidget(self.net_up_chart)
        lay.addLayout(charts, 1)
        return page

    def _build_session(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(8, 6, 8, 2)
        lay.setSpacing(3)
        self.session_labels: dict[str, QLabel] = {}
        for key in ("uptime", "responses", "speed", "first", "peaks_load", "peaks_temp", "alerts"):
            label = QLabel("—")
            label.setObjectName("sessionLine")
            label.setWordWrap(True)
            lay.addWidget(label)
            self.session_labels[key] = label
        lay.addStretch(1)
        return page

    def _metric_row(self, grid: QGridLayout, row: int, name: str) -> tuple[QProgressBar, QLabel]:
        grid.addWidget(self._name(name), row, 0)
        bar = QProgressBar()
        bar.setObjectName("metricBar")
        bar.setRange(0, 1000)
        bar.setTextVisible(False)
        bar.setFixedHeight(6)
        grid.addWidget(bar, row, 1)
        value = QLabel()
        value.setObjectName("metricValue")
        value.setMinimumWidth(110)
        grid.addWidget(value, row, 2)
        return bar, value

    def _status_row(self, grid: QGridLayout, row: int, name: str) -> tuple[StatusDot, QLabel]:
        grid.addWidget(self._name(name), row, 0)
        dot = StatusDot(TEXT_SECONDARY)
        value = QLabel("—")
        value.setObjectName("metricValue")
        value.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        holder = QWidget()
        layout = QHBoxLayout(holder)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(dot)
        layout.addWidget(value, 1)
        grid.addWidget(holder, row, 1, 1, 2)
        return dot, value

    # --- видимость: запуск и остановка сбора --------------------------------------

    def panel_shown(self) -> None:
        self._visible = True
        if self._service is not None:
            self._service.set_detail(True)
            self._refresh_from_service()
            return
        if self._worker is not None and self._worker.isRunning():
            return
        if self._collector is None:
            self._collector = self._collector_factory()
        worker = SystemInfoWorker(self._collector, self._models_source, self._interval_ms, parent=self)
        worker.snapshot.connect(self.apply_snapshot)
        worker.models.connect(self.apply_models)
        # слот QObject, а не lambda: он выполняется в GUI-потоке после выхода из run()
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._threads.append(worker)
        worker.start()

    def panel_hidden(self) -> None:
        """Останавливает подробный опрос без ожидания."""
        self._visible = False
        if self._service is not None:
            self._service.set_detail(False)
            return
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

    def is_polling(self) -> bool:
        """Идёт ли подробный сбор для панели (процессы при службе, свой поток без неё)."""
        if self._service is not None:
            return self._service.detail
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self, timeout_ms: int = 4000) -> None:
        """Закрытие окна: останавливает и дожидается собственных потоков сбора."""
        self.panel_hidden()
        for worker in list(self._threads):
            worker.stop()
            if not worker.wait(timeout_ms):
                log.error("Поток системной информации не завершился за %d мс", timeout_ms)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if worker in self._threads:
            self._threads.remove(worker)
            worker.deleteLater()

    # --- данные от главного окна ----------------------------------------------------

    def set_ollama_status(self, text: str, color: str, ready: bool, model_name: str) -> None:
        self._ollama_ready = ready
        self._model_name = model_name
        self.ollama_dot.set_color(color)
        self.ollama_value.setText(text)
        self.ollama_value.setToolTip(text)
        if not ready:
            self.model_dot.set_color(TEXT_SECONDARY)
            self.model_value.setText(f"{model_name} · {UNAVAILABLE}" if model_name else UNAVAILABLE)
        elif not self.model_value.text().startswith(model_name) or UNAVAILABLE in self.model_value.text():
            self.model_value.setText(model_name)

    def set_voice_state(self, text: str, color: str) -> None:
        self.piper_dot.set_color(color)
        self.piper_value.setText(text)
        self.piper_value.setToolTip(text)

    # --- данные мониторинга ----------------------------------------------------------

    def _set_bar(self, bar: QProgressBar, percent: float | None) -> None:
        bar.setValue(0 if percent is None else int(max(0.0, min(percent, 100.0)) * 10))
        high = percent is not None and percent >= HIGH_LOAD
        name = "metricBarHigh" if high else "metricBar"
        if bar.objectName() != name:
            bar.setObjectName(name)
            bar.style().unpolish(bar)
            bar.style().polish(bar)

    def _show_unavailable(self) -> None:
        for bar, label in ((self.cpu_bar, self.cpu_value), (self.ram_bar, self.ram_value),
                           (self.gpu_bar, self.gpu_value), (self.vram_bar, self.vram_value)):
            self._set_bar(bar, None)
            label.setText(UNAVAILABLE)
        self.temp_value.setText(UNAVAILABLE)
        self.power_value.setText(UNAVAILABLE)

    def apply_snapshot(self, snap: SystemSnapshot) -> None:
        self.last_snapshot = snap
        self._apply_overview(snap)
        if not self.isVisible() and self._service is not None:
            return   # графики и таблицы обновим, когда панель покажут
        page = self.tabs.currentIndex()
        if page == 1:
            self._apply_charts(snap)
        elif page == 2:
            self._apply_processes()
        elif page == 3:
            self._apply_io(snap)
        elif page == 4:
            self._apply_session()

    def _refresh_from_service(self) -> None:
        if self.last_snapshot is not None:
            self.apply_snapshot(self.last_snapshot)

    def _apply_overview(self, snap: SystemSnapshot) -> None:
        self._set_bar(self.cpu_bar, snap.cpu_percent)
        self.cpu_value.setText(UNAVAILABLE if snap.cpu_percent is None else f"{snap.cpu_percent:.0f}%")
        if snap.cpu_per_core:
            self.cpu_value.setToolTip(f"Ядер: {len(snap.cpu_per_core)}, максимум {max(snap.cpu_per_core):.0f}%")

        if snap.ram_total and snap.ram_used is not None and snap.ram_available is not None:
            self._set_bar(self.ram_bar, snap.ram_percent)
            self.ram_value.setText(f"{_gb(snap.ram_used)} / {_gb(snap.ram_total)} ГБ")
            self.ram_value.setToolTip(
                f"Всего: {_gb(snap.ram_total)} ГБ\nЗанято: {_gb(snap.ram_used)} ГБ\n"
                f"Свободно: {_gb(snap.ram_available)} ГБ"
            )
        else:
            self._set_bar(self.ram_bar, None)
            self.ram_value.setText(UNAVAILABLE)

        self._apply_temp_power(snap)
        gpu = snap.gpu
        if gpu is None:
            self._set_bar(self.gpu_bar, None)
            self.gpu_value.setText(UNAVAILABLE)
            self._set_bar(self.vram_bar, None)
            self.vram_value.setText(UNAVAILABLE)
            self.gpu_value.setToolTip("Видеокарта NVIDIA или nvidia-smi недоступны")
            return
        parts = [UNAVAILABLE if gpu.utilization is None else f"{gpu.utilization:.0f}%"]
        if gpu.temperature_c is not None:
            parts.append(f"{gpu.temperature_c:.0f}°C")
        self._set_bar(self.gpu_bar, gpu.utilization)
        self.gpu_value.setText(" · ".join(parts))
        temp = UNAVAILABLE if gpu.temperature_c is None else f"{gpu.temperature_c:.0f}°C"
        self.gpu_value.setToolTip(f"{gpu.name}\nТемпература: {temp}")
        if gpu.memory_used_mb is not None and gpu.memory_total_mb:
            self._set_bar(self.vram_bar, gpu.memory_used_mb / gpu.memory_total_mb * 100)
            self.vram_value.setText(f"{gpu.memory_used_mb / 1024:.1f} / {gpu.memory_total_mb / 1024:.1f} ГБ")
        else:
            self._set_bar(self.vram_bar, None)
            self.vram_value.setText(UNAVAILABLE)

    def _apply_temp_power(self, snap: SystemSnapshot) -> None:
        from interface.styles import ERROR, SUCCESS

        gpu_t = snap.gpu.temperature_c if snap.gpu is not None else None
        parts = [f"GPU {gpu_t:.0f}°C" if gpu_t is not None else f"GPU {UNAVAILABLE}",
                 f"CPU {snap.cpu_temp_c:.0f}°C" if snap.cpu_temp_c is not None else f"CPU {UNAVAILABLE}"]
        self.temp_value.setText(" · ".join(parts))
        self.temp_value.setToolTip("Температуру процессора Windows обычно не отдаёт без прав администратора.")
        hot = max([t for t in (gpu_t, snap.cpu_temp_c) if t is not None], default=None)
        self.temp_dot.set_color(TEXT_SECONDARY if hot is None else ERROR if hot >= 85 else
                                WARNING if hot >= 75 else SUCCESS)
        b = snap.battery
        if b is None:
            self.power_value.setText("От сети · батареи нет")
            self.power_dot.set_color(SUCCESS)
            return
        text = f"{b.percent:.0f}% · " + ("от сети" if b.plugged else "от батареи")
        if b.seconds_left:
            text += f" · {format_duration(b.seconds_left)}"
        self.power_value.setText(text)
        self.power_dot.set_color(SUCCESS if b.plugged else ERROR if b.percent <= 15 else
                                 WARNING if b.percent <= 30 else TEAL)

    def _apply_charts(self, snap: SystemSnapshot) -> None:
        history = self._service.history if self._service is not None else None
        if history is None:
            return
        now = snap.timestamp
        for chart, key in ((self.cpu_chart, "cpu"), (self.gpu_chart, "gpu"),
                           (self.ram_chart, "ram"), (self.vram_chart, "vram")):
            chart.set_series(history.series(key), now)
        self.core_bars.set_values(snap.cpu_per_core)

    def _apply_processes(self) -> None:
        procs = self._service.last_processes if self._service is not None else self.last_snapshot.processes
        if not procs:
            self.proc_table.setRowCount(0)
            return
        self.proc_table.setRowCount(len(procs))
        for row, p in enumerate(procs):
            cells = (p.name, f"{p.cpu_percent:.1f}%", f"{p.rss / 1024 ** 2:.0f} МБ")
            for col, text in enumerate(cells):
                item = self.proc_table.item(row, col)
                if item is None:
                    item = QTableWidgetItem()
                    if col:
                        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    self.proc_table.setItem(row, col, item)
                item.setText(text)
            self.proc_table.item(row, 0).setToolTip(f"PID {p.pid}")

    def _apply_io(self, snap: SystemSnapshot) -> None:
        for d in snap.disks or ():
            if d.mount not in self._disk_rows:
                self._disk_rows[d.mount] = self._metric_row(self.disk_grid, len(self._disk_rows), d.mount.rstrip("\\"))
            bar, label = self._disk_rows[d.mount]
            self._set_bar(bar, d.percent)
            label.setText(f"свободно {_gb(d.free)} из {_gb(d.total)} ГБ")
        self.disk_io_value.setText(
            f"Диски: чтение {format_rate(snap.disk_read_bps)} · запись {format_rate(snap.disk_write_bps)}")
        history = self._service.history if self._service is not None else None
        if history is not None:
            self.net_down_chart.set_series(history.series("net_down"), snap.timestamp)
            self.net_up_chart.set_series(history.series("net_up"), snap.timestamp)

    def _apply_session(self) -> None:
        if self._service is None:
            return
        s = self._service.stats
        L = self.session_labels
        L["uptime"].setText(f"Сессия: {format_duration(s.uptime())}")
        L["responses"].setText(f"Ответов LISA: {s.responses} · токенов: {s.tokens}")
        L["speed"].setText("Скорость модели: " + (f"в среднем {s.avg_tokens_per_second:.1f} ток/с"
                                                  if s.avg_tokens_per_second else "—"))
        L["first"].setText("Время до первого токена: " + (f"в среднем {s.avg_first_token:.2f} с"
                                                          if s.avg_first_token is not None else "—"))
        load = [f"{t} {s.peaks[k]:.0f}%" for k, t in (("cpu", "CPU"), ("ram", "RAM"), ("gpu", "GPU"), ("vram", "VRAM"))
                if k in s.peaks]
        L["peaks_load"].setText("Пики нагрузки: " + (", ".join(load) or "—"))
        temps = [f"{t} {s.peaks[k]:.0f}°C" for k, t in (("gpu_temp", "GPU"), ("cpu_temp", "CPU")) if k in s.peaks]
        L["peaks_temp"].setText("Максимальная температура: " + (", ".join(temps) or "—"))
        L["alerts"].setText(f"Предупреждений: {s.alerts}")

    def apply_generation(self, stats: GenerationStats) -> None:
        parts = []
        if stats.tokens_per_second:
            parts.append(f"{stats.tokens_per_second:.1f} ток/с")
        if stats.first_token_seconds is not None:
            parts.append(f"первый токен {stats.first_token_seconds:.2f} с")
        parts.append(f"{stats.tokens} ток.")
        self.speed_value.setText(" · ".join(parts))
        self.speed_dot.set_color(CYAN)
        self.speed_value.setToolTip("Последний ответ модели по данным Ollama")

    def apply_models(self, models: list[tuple[str, int]] | None) -> None:
        """Какая модель сейчас загружена в память Ollama."""
        name = self._model_name
        if not name:
            return
        if models is None:
            self.model_dot.set_color(TEXT_SECONDARY)
            self.model_value.setText(f"{name} · {UNAVAILABLE}")
            self.model_value.setToolTip("Ollama не отвечает")
            return
        loaded = {n: vram for n, vram in models}
        wanted = name if ":" in name else f"{name}:latest"
        vram = loaded.get(name, loaded.get(wanted))
        if vram is None:
            self.model_dot.set_color(TEXT_SECONDARY)
            self.model_value.setText(f"{name} · не в памяти")
            tooltip = "Модель не загружена в память. Ollama загрузит её при первом ответе."
        else:
            self.model_dot.set_color(TEAL)
            self.model_value.setText(f"{name} · VRAM {_gb(vram)} ГБ")
            tooltip = f"Модель загружена в память, видеопамять {_gb(vram)} ГБ"
        others = [n for n in loaded if n not in (name, wanted)]
        if others:
            tooltip += "\nТакже загружены: " + ", ".join(others)
        self.model_value.setToolTip(tooltip)
