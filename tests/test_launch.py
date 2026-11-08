"""Запуск двойным кликом: один экземпляр, иконка, журнал ошибок без консоли, ярлык."""

from __future__ import annotations

import logging
import struct
import sys
import time
import uuid
from pathlib import Path

import pytest

from core.single_instance import SingleInstance, channel_name

PROJECT = Path(__file__).resolve().parent.parent


def _pump(qt_app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


SECOND_LAUNCH = """
import sys
sys.path.insert(0, sys.argv[1])
from PySide6.QtCore import QCoreApplication
from core.single_instance import SingleInstance
app = QCoreApplication([])
print("primary" if SingleInstance(sys.argv[2], sys.argv[3]).acquire() else "secondary")
"""


def test_second_launch_activates_first(qt_app, tmp_path):
    import subprocess

    name = f"SIRIUS-test-{uuid.uuid4().hex[:8]}"
    lock = tmp_path / "sirius.lock"
    first = SingleInstance(lock, name)
    assert first.acquire()
    calls = []
    first.activation_requested.connect(lambda: calls.append(1))
    # второй запуск — отдельный процесс, как при повторном двойном клике по ярлыку
    second = subprocess.Popen([sys.executable, "-c", SECOND_LAUNCH, str(PROJECT), str(lock), name],
                              stdout=subprocess.PIPE, text=True)
    assert _pump(qt_app, lambda: second.poll() is not None, timeout=20)
    assert second.stdout.read().strip() == "secondary"   # второе окно не открывается
    assert _pump(qt_app, lambda: calls == [1])            # первое просят показаться
    first.release()
    third = SingleInstance(tmp_path / "sirius.lock", name)
    assert third.acquire()                    # после закрытия первого запуск снова возможен
    third.release()


def test_channel_name_depends_on_project_folder(tmp_path):
    assert channel_name(tmp_path / "a") != channel_name(tmp_path / "b")
    assert channel_name(tmp_path / "a") == channel_name(tmp_path / "A")  # регистр путей Windows


def test_icon_is_multisize_ico():
    icon = PROJECT / "resources" / "icons" / "sirius.ico"
    if not icon.exists():
        pytest.skip("иконка ещё не создана")
    data = icon.read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 5
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert {16, 32, 256} <= sizes


def test_uncaught_errors_go_to_log(tmp_path):
    import main

    main.setup_logging(tmp_path)
    previous = sys.excepthook
    try:
        main._install_excepthook()
        try:
            raise RuntimeError("проверка журнала")
        except RuntimeError:
            sys.excepthook(*sys.exc_info())
        logging.shutdown()
        text = (tmp_path / "sirius.log").read_text(encoding="utf-8")
        assert "Необработанная ошибка" in text and "проверка журнала" in text
    finally:
        sys.excepthook = previous
        logging.getLogger().handlers.clear()


def test_shortcut_targets_pythonw_without_console():
    sys.path.insert(0, str(PROJECT / "tools"))
    try:
        import create_shortcut
    finally:
        sys.path.pop(0)
    assert create_shortcut.PYTHONW.name == "pythonw.exe"   # без окна консоли
    assert create_shortcut.ENTRY == PROJECT / "main.py"
    assert "$env:SIRIUS_LNK" in create_shortcut._CREATE_LNK   # пути не подставляются в текст команды
