"""Системная информация: сбор данных, недоступная видеокарта, фоновый поток, панель SYSTEM."""

from __future__ import annotations

import subprocess
import threading
import time
from types import SimpleNamespace

import pytest

from monitoring.system_info import GPU_RETRY_AFTER, SystemInfoCollector, SystemSnapshot, parse_nvidia_smi


class FakePsutil:
    def __init__(self) -> None:
        self.calls = 0

    def cpu_percent(self, interval=None):
        self.calls += 1
        return 37.5

    def virtual_memory(self):
        gb = 1024 ** 3
        return SimpleNamespace(total=16 * gb, available=6 * gb, percent=62.5)


SMI_OK = "NVIDIA GeForce RTX 3050 6GB Laptop GPU, 7, 5404, 6144, 49.84\n"


def test_parse_nvidia_smi_values():
    gpu = parse_nvidia_smi(SMI_OK)
    assert gpu.name.startswith("NVIDIA GeForce RTX 3050")
    assert gpu.utilization == 7.0
    assert gpu.memory_used_mb == 5404.0 and gpu.memory_total_mb == 6144.0
    assert gpu.temperature_c == pytest.approx(49.84)


def test_parse_nvidia_smi_missing_sensors_are_none():
    gpu = parse_nvidia_smi("Some GPU, [N/A], 100, 2048, [Not Supported]")
    assert gpu.utilization is None and gpu.temperature_c is None
    assert gpu.memory_used_mb == 100.0
    assert parse_nvidia_smi("") is None
    assert parse_nvidia_smi("garbage") is None


def test_collect_cpu_ram_and_gpu():
    collector = SystemInfoCollector(FakePsutil(), nvidia_smi_path="nvidia-smi", runner=lambda args: SMI_OK)
    snap = collector.collect()
    assert snap.cpu_percent == 37.5
    assert snap.ram_total == 16 * 1024 ** 3
    assert snap.ram_available == 6 * 1024 ** 3
    assert snap.ram_used == 10 * 1024 ** 3
    assert snap.gpu is not None and snap.gpu.utilization == 7.0


def test_no_nvidia_smi_means_unavailable_gpu():
    collector = SystemInfoCollector(FakePsutil(), nvidia_smi_path=None)
    assert collector.collect().gpu is None
    assert not collector.has_nvidia_smi


def test_failing_nvidia_smi_is_not_called_every_time():
    calls = []
    now = [100.0]

    def runner(args):
        calls.append(args)
        raise subprocess.TimeoutExpired(args, 3)

    collector = SystemInfoCollector(FakePsutil(), nvidia_smi_path="nvidia-smi", runner=runner, clock=lambda: now[0])
    assert collector.collect().gpu is None
    assert collector.collect().gpu is None
    assert len(calls) == 1                     # повтор только через GPU_RETRY_AFTER секунд
    now[0] += GPU_RETRY_AFTER + 1
    collector.collect()
    assert len(calls) == 2


def test_nvidia_smi_called_without_shell():
    seen = {}

    def runner(args):
        seen["args"] = args
        return SMI_OK

    SystemInfoCollector(FakePsutil(), nvidia_smi_path="nvidia-smi", runner=runner).collect()
    assert isinstance(seen["args"], list) and seen["args"][0] == "nvidia-smi"


def test_without_psutil_values_are_none():
    collector = SystemInfoCollector(psutil_module=None, nvidia_smi_path=None)
    collector._psutil = None
    snap = collector.collect()
    assert snap.cpu_percent is None and snap.ram_total is None


def test_real_collector_returns_real_numbers():
    snap = SystemInfoCollector().collect()
    assert snap.cpu_percent is not None and 0 <= snap.cpu_percent <= 100
    assert snap.ram_total and snap.ram_total > 0


# --- панель и фоновый поток -----------------------------------------------------


class ThreadRecordingCollector:
    def __init__(self, gpu=True) -> None:
        self.threads: list[threading.Thread] = []
        self.gpu = gpu

    def collect(self):
        self.threads.append(threading.current_thread())
        time.sleep(0.05)  # имитация медленного nvidia-smi
        gpu = parse_nvidia_smi(SMI_OK) if self.gpu else None
        return SystemSnapshot(12.0, 16 * 1024 ** 3, 8 * 1024 ** 3, 8 * 1024 ** 3, 50.0, gpu, time.monotonic())


def _pump(qt_app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_panel_collects_in_background_thread_and_stops(qt_app):
    from interface.panels.system_panel import SystemPanel

    collector = ThreadRecordingCollector()
    panel = SystemPanel(collector_factory=lambda: collector, interval_ms=200)
    started = time.monotonic()
    panel.panel_shown()
    assert time.monotonic() - started < 0.05      # запуск не ждёт сбора данных
    assert _pump(qt_app, lambda: panel.last_snapshot is not None)
    assert all(t is not threading.main_thread() for t in collector.threads)
    assert panel.cpu_value.text() == "12%"
    assert "°C" in panel.gpu_value.text()
    started = time.monotonic()
    panel.panel_hidden()
    assert time.monotonic() - started < 0.05      # остановка не ждёт потока
    panel.shutdown()
    assert not panel.is_polling()
    count = len(collector.threads)
    time.sleep(0.4)
    assert len(collector.threads) == count        # после скрытия опрос не продолжается


def test_panel_shows_unavailable_gpu(qt_app):
    from interface.panels.system_panel import UNAVAILABLE, SystemPanel

    panel = SystemPanel(collector_factory=lambda: ThreadRecordingCollector(gpu=False))
    panel.apply_snapshot(ThreadRecordingCollector(gpu=False).collect())
    assert panel.gpu_value.text() == UNAVAILABLE == "Unavailable"
    assert panel.vram_value.text() == UNAVAILABLE
    assert panel.cpu_value.text() == "12%"


def test_panel_shows_loaded_model(qt_app):
    from interface.panels.system_panel import SystemPanel

    panel = SystemPanel(collector_factory=lambda: ThreadRecordingCollector())
    panel.set_ollama_status("Модель готова", "#35D49A", True, "qwen3:8b-q4_K_M")
    panel.apply_models([("qwen3:8b-q4_K_M", 4 * 1024 ** 3)])
    assert panel.model_value.text() == "qwen3:8b-q4_K_M · VRAM 4.0 ГБ"
    panel.apply_models([])
    assert "не в памяти" in panel.model_value.text()
    panel.apply_models(None)
    assert "Unavailable" in panel.model_value.text()


def test_window_system_panel_shows_voice_and_ollama(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from core.model_manager import OllamaStatus, StatusInfo
    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    try:
        assert win.workspace.is_open("system")      # SYSTEM открыта в стандартной компоновке
        assert win.system_panel.is_polling()
        win._on_status(StatusInfo(OllamaStatus.NOT_RUNNING, "Ollama не запущена"))
        assert win.system_panel.ollama_value.text() == "Ollama не запущена"
        assert win.system_panel.piper_value.text() != "—"
        win.workspace.close("system")
        assert not win.system_panel.is_polling()
    finally:
        win.close()
    assert not win.system_panel.is_polling()
