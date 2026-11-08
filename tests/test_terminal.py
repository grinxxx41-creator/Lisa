"""Ограниченная консоль: проверка команд, запуск без оболочки, ошибки, коды возврата, подтверждение."""

from __future__ import annotations

import sys
import time

import pytest
from PySide6.QtWidgets import QMessageBox

from core.command_policy import check_command, program_name, split_command
from core.terminal_session import ConsoleDecoder

PY = sys.executable


# --- разбор и политика ----------------------------------------------------------


def test_split_keeps_windows_paths_and_quotes():
    assert split_command(r'dir "C:\Program Files" C:\Users') == ["dir", r"C:\Program Files", r"C:\Users"]
    assert split_command('  echo   "a b"  c ') == ["echo", "a b", "c"]
    assert split_command('echo ""') == ["echo", ""]


def test_unclosed_quote_is_rejected():
    check = check_command('echo "abc')
    assert not check.allowed and "кавычка" in check.reason


def test_program_name_normalized():
    assert program_name(r"C:\Windows\System32\CMD.EXE") == "cmd"
    assert program_name("script.ps1") == "script"


@pytest.mark.parametrize("command", [
    "runas /user:Administrator cmd",
    "powershell -Command Start-Process cmd -Verb RunAs",
    "sudo rm -rf /",
    "powershell -EncodedCommand ZQBjAGgAbwA=",
    "pwsh -enc ZQBjAGgAbwA=",
])
def test_elevation_and_hidden_commands_blocked(command):
    check = check_command(command)
    assert not check.allowed
    assert check.reason


@pytest.mark.parametrize("command", [
    r"del C:\temp\file.txt",
    "cmd /c del file.txt",
    "cmd /c echo hi > out.txt",
    "powershell -Command Remove-Item x.txt",
    "reg add HKCU\\Software\\X",
    "shutdown /s /t 0",
    "git clean -fdx",
    "taskkill /IM notepad.exe",
])
def test_dangerous_commands_need_confirmation(command):
    check = check_command(command)
    assert check.allowed and check.needs_confirmation, command


def test_system_folder_is_mentioned():
    check = check_command(r"cmd /c del C:\Windows\System32\x.dll")
    assert "системную папку" in check.reason


@pytest.mark.parametrize("command", ["ping 127.0.0.1 -n 1", "cmd /c dir", "git status", "ipconfig", "python --version"])
def test_safe_commands_run_without_extra_confirmation(command):
    check = check_command(command)
    assert check.allowed and not check.needs_confirmation


def test_builtins_detected():
    assert check_command("cd ..").builtin == "cd"
    assert check_command("cls").builtin == "clear"
    assert check_command("HISTORY").builtin == "history"


# --- декодирование вывода --------------------------------------------------------


def test_decoder_utf8_split_across_chunks():
    d = ConsoleDecoder(fallback="cp866")
    data = "Привет".encode("utf-8")
    assert d.decode(data[:3]) + d.decode(data[3:]) == "Привет"


def test_decoder_falls_back_to_console_codepage():
    d = ConsoleDecoder(fallback="cp866")
    assert d.decode("Обмен пакетами".encode("cp866")) == "Обмен пакетами"


# --- сеанс и панель ---------------------------------------------------------------


def _pump(qt_app, predicate, timeout=15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def terminal(qt_app, tmp_path):
    from interface.panels.terminal_panel import TerminalPanel

    panel = TerminalPanel(cwd=tmp_path, elevated=False)
    results: list[int] = []
    panel.session.finished.connect(lambda code, _d: results.append(code))
    panel.results = results
    yield panel
    panel.shutdown()


def test_runs_program_and_shows_exit_code(terminal, qt_app):
    assert terminal.execute(f'"{PY}" -c "print(\'hello sirius\')"')
    assert _pump(qt_app, lambda: terminal.results == [0])
    text = terminal.output.toPlainText()
    assert "hello sirius" in text
    assert "[код возврата 0]" in text


def test_nonzero_exit_code_and_stderr(terminal, qt_app):
    assert terminal.execute(f'"{PY}" -c "import sys; sys.stderr.write(\'bad\'); sys.exit(3)"')
    assert _pump(qt_app, lambda: terminal.results == [3])
    text = terminal.output.toPlainText()
    assert "bad" in text and "[код возврата 3]" in text


def test_unknown_program_reports_error(terminal):
    assert not terminal.execute("nosuchprogram_sirius_xyz --flag")
    assert "Команда не найдена" in terminal.output.toPlainText()
    assert not terminal.session.is_running()


def test_program_waiting_for_input_does_not_hang(terminal, qt_app):
    assert terminal.execute(f'"{PY}" -c "input()"')   # ввод закрыт: программа получает EOF
    assert _pump(qt_app, lambda: len(terminal.results) == 1)
    assert terminal.results[0] != 0


def test_stop_long_command(terminal, qt_app):
    assert terminal.execute(f'"{PY}" -c "import time; time.sleep(30)"')
    assert _pump(qt_app, terminal.session.is_running, 5)
    started = time.monotonic()
    terminal.session.stop()
    assert _pump(qt_app, lambda: not terminal.session.is_running(), 10)
    assert time.monotonic() - started < 5
    assert "прервана" in terminal.output.toPlainText()


def test_execute_does_not_block_gui(terminal, qt_app):
    started = time.monotonic()
    terminal.execute(f'"{PY}" -c "import time; time.sleep(1)"')
    assert time.monotonic() - started < 0.5
    _pump(qt_app, lambda: terminal.results)


def test_dangerous_command_requires_confirmation(terminal, monkeypatch, tmp_path):
    victim = tmp_path / "keep.txt"
    victim.write_text("x", encoding="utf-8")
    asked = []
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: asked.append(a[2]) or QMessageBox.StandardButton.No))
    assert not terminal.execute("cmd /c del keep.txt")
    assert asked and "del keep.txt" in asked[0]
    assert victim.exists()
    assert "Отменено" in terminal.output.toPlainText()


def test_blocked_command_never_starts(terminal):
    assert not terminal.execute("runas /user:Administrator cmd")
    assert not terminal.session.is_running()
    assert "администратора" in terminal.output.toPlainText()


def test_cd_and_history(terminal, tmp_path):
    (tmp_path / "sub").mkdir()
    terminal.execute("cd sub")
    assert terminal.session.cwd == (tmp_path / "sub").resolve()
    terminal.execute("cd nope_dir")
    assert "Папка не найдена" in terminal.output.toPlainText()
    terminal.execute("history")
    assert "cd sub" in terminal.output.toPlainText()
    assert terminal.session.history[:2] == ["cd sub", "cd nope_dir"]


def test_elevated_session_disables_console(qt_app, tmp_path):
    from interface.panels.terminal_panel import TerminalPanel

    panel = TerminalPanel(cwd=tmp_path, elevated=True)
    assert not panel.input.isEnabled()
    assert not panel.execute("ipconfig")


def test_model_has_no_path_to_terminal(qt_app, tmp_path, monkeypatch):
    """Ответ модели с командой не попадает в консоль и не выполняется."""
    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    try:
        calls = []
        monkeypatch.setattr(win.terminal_panel.session, "run", lambda argv: calls.append(argv) or True)
        win._assistant_card = win.chat.add_message("assistant", "")
        win._generating = True
        win._on_token("Выполните:\n```cmd\ndel C:\\important\n```")
        win._on_generation_done("Выполните:\n```cmd\ndel C:\\important\n```")
        assert calls == []
        assert win.terminal_panel.session.history == []
    finally:
        win.close()
