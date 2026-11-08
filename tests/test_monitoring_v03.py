"""v0.3: метрики, история, предупреждения, сводка, данные для LISA, автозапуск, графики, окно."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QMessageBox

from monitoring.alerts import COOLDOWN, AlertMonitor, system_mood
from monitoring.history import MetricsHistory
from monitoring.session_stats import SessionStats, parse_ollama_stats
from monitoring.system_info import (
    BatteryInfo, DiskInfo, GpuInfo, ProcessInfo, SystemInfoCollector, SystemSnapshot,
)
from monitoring.system_report import build_report, is_system_question, report_message

GB = 1024 ** 3


def snap(t=0.0, cpu=10.0, ram=50.0, gpu=5.0, vram_mb=1000.0, gpu_temp=50.0, disks=None, battery=None,
         processes=None) -> SystemSnapshot:
    return SystemSnapshot(
        cpu, 16 * GB, int(16 * GB * ram / 100), int(16 * GB * (1 - ram / 100)), ram,
        GpuInfo("RTX 3050", gpu, vram_mb, 6144.0, gpu_temp), t,
        cpu_per_core=(cpu, cpu / 2), disks=disks, battery=battery, processes=processes,
        net_recv_bps=2048.0, net_sent_bps=1024.0,
    )


# --- сбор --------------------------------------------------------------------------


class FakePsutil:
    def __init__(self):
        self.read = 0

    def cpu_percent(self, interval=None, percpu=False):
        return [20.0, 40.0] if percpu else 30.0

    def cpu_count(self):
        return 2

    def virtual_memory(self):
        return SimpleNamespace(total=16 * GB, available=8 * GB, percent=50.0)

    def disk_partitions(self, all=False):
        return [SimpleNamespace(mountpoint="C:\\", fstype="NTFS", opts="rw"),
                SimpleNamespace(mountpoint="E:\\", fstype="", opts="cdrom")]

    def disk_usage(self, path):
        return SimpleNamespace(total=100 * GB, used=90 * GB, free=10 * GB, percent=90.0)

    def disk_io_counters(self):
        self.read += 10 * 1024 ** 2
        return SimpleNamespace(read_bytes=self.read, write_bytes=0)

    def net_io_counters(self):
        return SimpleNamespace(bytes_recv=self.read, bytes_sent=0)

    def sensors_battery(self):
        return SimpleNamespace(percent=40, secsleft=3600, power_plugged=False)

    def process_iter(self, attrs):
        class P:
            def __init__(self, pid, name, rss):
                self.info = {"pid": pid, "name": name}
                self._rss = rss

            def oneshot(self):
                import contextlib
                return contextlib.nullcontext()

            def cpu_percent(self, interval=None):
                return 50.0

            def memory_info(self):
                return SimpleNamespace(rss=self._rss)

        return [P(0, "Idle", 0), P(10, "game.exe", 3 * GB), P(11, "ollama.exe", 1 * GB)]


def test_collector_extended_fields():
    clock = iter([0.0, 1.0, 2.0, 3.0])
    c = SystemInfoCollector(psutil_module=FakePsutil(), nvidia_smi_path=None, clock=lambda: next(clock))
    c.collect()
    s = c.collect(processes=True)
    assert s.cpu_per_core == (20.0, 40.0)
    assert s.disks == (DiskInfo("C:\\", 100 * GB, 90 * GB, 10 * GB, 90.0),)       # привод пропущен
    assert s.disk_read_bps == pytest.approx(10 * 1024 ** 2)
    assert s.battery == BatteryInfo(40.0, False, 3600)
    assert [p.name for p in s.processes] == ["game.exe", "ollama.exe"]           # «Бездействие» пропущено
    assert s.processes[0].cpu_percent == 25.0                                    # 50% одного ядра из двух
    assert c.collect().processes is None                                          # процессы — по запросу


# --- история, предупреждения, настроение -----------------------------------------------


def test_history_keeps_window():
    h = MetricsHistory(window=10)
    for t in range(0, 30, 2):
        h.add(snap(t=float(t), cpu=float(t)))
    pts = h.series("cpu")
    assert pts[0][0] >= 18 and h.latest("cpu") == 28.0
    assert h.average("cpu", 4) == pytest.approx((24 + 26 + 28) / 3)


def test_alert_needs_sustain_and_respects_cooldown_and_hysteresis():
    m = AlertMonitor()
    assert m.check(snap(t=0, cpu=99)) == []            # CPU должен держаться 15 с
    fired = m.check(snap(t=16, cpu=99))
    assert [a.kind for a in fired] == ["cpu"]
    assert m.check(snap(t=20, cpu=99)) == []           # пауза между повторами
    assert m.check(snap(t=COOLDOWN + 30, cpu=99)) == []   # не опускался ниже порога — не повторяем
    m.check(snap(t=COOLDOWN + 40, cpu=10))
    m.check(snap(t=COOLDOWN + 50, cpu=99))
    assert [a.kind for a in m.check(snap(t=COOLDOWN + 70, cpu=99))] == ["cpu"]


def test_alerts_for_temperature_disk_battery_and_disable():
    disks = (DiskInfo("C:\\", 100 * GB, 97 * GB, 3 * GB, 97.0),)
    s = snap(gpu_temp=90, disks=disks, battery=BatteryInfo(10, False, None))
    kinds = {a.kind for a in AlertMonitor().check(s)}
    assert {"gpu_temp", "disk_free_gb", "battery"} <= kinds
    assert all(a.critical for a in AlertMonitor().check(s) if a.kind in ("gpu_temp", "battery"))
    assert AlertMonitor(enabled=False).check(s) == []
    plugged = snap(battery=BatteryInfo(10, True, None))
    assert "battery" not in {a.kind for a in AlertMonitor().check(plugged)}
    custom = AlertMonitor({"gpu_temp": 95})
    assert "gpu_temp" not in {a.kind for a in custom.check(s)}


def test_alert_spoken_text_has_no_symbols():
    alert = AlertMonitor().check(snap(gpu_temp=90))[0]
    assert "°" not in alert.spoken() and "градусов" in alert.spoken()


def test_system_mood():
    assert system_mood(snap()) == "normal"
    assert system_mood(snap(gpu=95)) == "busy"
    assert system_mood(snap(vram_mb=6000)) == "busy"
    assert system_mood(snap(gpu_temp=88)) == "hot"


# --- сводка и модель ---------------------------------------------------------------


def test_parse_ollama_stats_and_session():
    st = parse_ollama_stats({"done": True, "eval_count": 100, "eval_duration": 4_000_000_000,
                             "load_duration": 500_000_000}, first_token_seconds=0.3)
    assert st.tokens == 100 and st.tokens_per_second == pytest.approx(25.0) and st.load_seconds == 0.5
    assert parse_ollama_stats({"done": True}) is None
    s = SessionStats()
    s.add_generation(st)
    s.add_snapshot(snap(cpu=70, gpu_temp=66))
    s.add_snapshot(snap(cpu=20, gpu_temp=60))
    assert s.responses == 1 and s.tokens == 100 and s.avg_first_token == 0.3
    assert s.peaks["cpu"] == 70 and s.peaks["gpu_temp"] == 66


# --- LISA и данные мониторинга ------------------------------------------------------------


@pytest.mark.parametrize("text, expected", [
    ("Как там мой компьютер?", True), ("Почему ноутбук греется?", True), ("Сколько свободно на диске?", True),
    ("Какая загрузка GPU?", True), ("Сколько памяти занимает Qwen?", True),
    ("Напиши стихотворение про осень", False), ("Как сварить борщ?", False),
])
def test_is_system_question(text, expected):
    assert is_system_question(text) is expected


def test_report_contains_real_values_and_names_missing_sensors():
    s = snap(cpu=42, gpu_temp=61, disks=(DiskInfo("C:\\", 200 * GB, 150 * GB, 50 * GB, 75.0),),
             processes=(ProcessInfo(1, "game.exe", 30.0, 2 * GB),))
    text = build_report(s, model_vram=4 * GB)
    assert "42%" in text and "61 °C" in text and "50.0 ГБ" in text and "game.exe" in text
    assert "датчик недоступен" in text          # температура CPU не выдумывается
    assert "4.0 ГБ" in text
    assert report_message(text)["role"] == "system"


def test_build_messages_inserts_monitoring_after_prompt():
    from core.context_manager import SYSTEM_PROMPT, build_messages

    msgs = build_messages([{"role": "user", "text": "как компьютер?"}], extra_system=[report_message("CPU 5%")])
    assert msgs[0]["content"] == SYSTEM_PROMPT and "CPU 5%" in msgs[1]["content"] and msgs[2]["role"] == "user"
    assert len(build_messages([{"role": "user", "text": "привет"}])) == 2


# --- автозапуск ------------------------------------------------------------------------


class FakeReg:
    HKEY_CURRENT_USER = "HKCU"
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        self.values = {}

    class _Key:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def OpenKey(self, root, path, reserved, access):
        assert root == "HKCU" and path.endswith(r"CurrentVersion\Run")   # только текущий пользователь
        return self._Key()

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        return self.values[name], 1

    def SetValueEx(self, key, name, reserved, kind, value):
        self.values[name] = value

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError
        del self.values[name]


def test_autostart_writes_only_user_run_key(tmp_path):
    from core.autostart import Autostart as RealAutostart
    import importlib
    import core.autostart as mod

    importlib.reload(mod)   # conftest подменил методы класса — берём настоящий модуль
    reg = FakeReg()
    a = mod.Autostart(tmp_path, registry=reg)
    assert not a.is_enabled()
    assert a.set_enabled(True) and a.is_enabled()
    assert "main.py" in reg.values["SIRIUS"] and "pythonw" in reg.values["SIRIUS"].lower()
    assert a.set_enabled(False) and not a.is_enabled()
    assert a.set_enabled(False)          # повторное выключение — не ошибка
    assert RealAutostart is not None


# --- интерфейс -------------------------------------------------------------------------


def _pump(qt_app, predicate, timeout=10.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_charts_and_panel_with_service(qt_app):
    from interface.monitor_service import MonitorService
    from interface.panels.system_panel import SystemPanel

    service = MonitorService(collector_factory=lambda: None)
    panel = SystemPanel(service=service)
    panel.resize(420, 300)
    panel.show()
    for t in range(5):
        service.inject(snap(t=float(t), cpu=20.0 + t, processes=(ProcessInfo(5, "game.exe", 12.0, 2 * GB),),
                            disks=(DiskInfo("C:\\", 100 * GB, 50 * GB, 50 * GB, 50.0),),
                            battery=BatteryInfo(55, False, 5400)))
    assert "24%" in panel.cpu_value.text() and "55%" in panel.power_value.text()
    for page in range(5):
        panel.tabs.setCurrentIndex(page)
        panel.grab()
    panel.tabs.setCurrentIndex(1)
    assert panel.cpu_chart.latest() == 24.0 and panel.core_bars.values() == (24.0, 12.0)
    panel.tabs.setCurrentIndex(2)
    assert panel.proc_table.item(0, 0).text() == "game.exe"
    panel.panel_shown()
    assert service.detail and panel.is_polling()
    panel.panel_hidden()
    assert not service.detail
    panel.close()


def test_generation_worker_reports_speed(qt_app):
    from interface.workers import GenerationWorker

    class Engine:
        def __init__(self):
            self.done = None

        def stream_reply(self, messages, cancel_event=None, max_tokens=None, on_response=None):
            yield "Привет"
            self.done = {"done": True, "eval_count": 20, "eval_duration": 1_000_000_000}

        def take_done_stats(self):
            return self.done

    worker = GenerationWorker(Engine(), [])
    got = []
    worker.stats.connect(got.append)
    worker.start()
    assert _pump(qt_app, lambda: got)
    worker.wait(2000)
    assert got[0].tokens_per_second == pytest.approx(20.0) and got[0].first_token_seconds is not None


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    yield win
    win._quitting = True
    win.close()


def test_window_heavy_mode_unloads_and_restores(window, qt_app, monkeypatch):
    from core.model_manager import ModelManager

    unloaded, released = [], []
    monkeypatch.setattr(ModelManager, "unload", lambda self, timeout=3.0: unloaded.append(1) or True)
    monkeypatch.setattr(window.tts, "release", lambda: released.append(1))
    window.set_heavy_mode(True)
    assert window.heavy_mode and released and _pump(qt_app, lambda: unloaded)
    assert window.heavy_btn.text() == "ВЕРНУТЬ"
    window.set_heavy_mode(False)
    assert not window.heavy_mode and window.heavy_btn.text() == "ОСВОБОДИТЬ"


def test_window_compact_mode_roundtrip(window, qt_app):
    window.show()
    window.enter_compact()
    assert window.compact and window.compact_bar.isVisible() and not window.isVisible()
    window.monitor.inject(snap(cpu=33))
    assert "33%" in window.compact_bar.metrics.text()
    window.leave_compact()
    assert not window.compact and window.isVisible() and not window.compact_bar.isVisible()


def test_window_adds_monitoring_to_system_questions(window, qt_app, monkeypatch):
    import interface.main_window as mw

    captured = []

    class Worker:
        def __init__(self, engine, messages, parent=None):
            captured.append(messages)
            from PySide6.QtCore import Signal  # noqa: F401
            for name in ("token", "finished_ok", "failed", "stopped", "finished", "stats"):
                setattr(self, name, SimpleNamespace(connect=lambda *a: None))

        def start(self):
            pass

        def stop(self):
            pass

        def isRunning(self):
            return False

    monkeypatch.setattr(mw, "GenerationWorker", Worker)
    window.monitor.inject(snap(cpu=77))
    window._on_send("Как там компьютер, не перегружен?")
    assert any("77%" in m["content"] for m in captured[0] if m["role"] == "system")
    window._generating = False
    window._on_send("Расскажи анекдот")
    assert sum(m["role"] == "system" for m in captured[1]) == 1
    window._generating = False
    window._worker = None


def test_window_alert_and_mood(window, qt_app):
    window.monitor.inject(snap(gpu_temp=92))
    assert window.avatar.mood == "hot"
    assert "нагрелась" in window.statusBar().currentMessage()
    window.monitor.inject(snap(t=1, gpu_temp=50))
    assert window.avatar.mood == "normal"
