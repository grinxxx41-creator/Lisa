"""Сеанс ограниченной консоли: запуск одной команды за раз через QProcess.

- Отдельный процесс, GUI-поток не ждёт его завершения.
- Без оболочки: программа и аргументы передаются списком (shell=True не используется).
- Стандартный ввод закрыт сразу после запуска: программа, ожидающая ввода, получает конец файла
  и не зависает. Интерактивные программы в этой консоли не поддерживаются.
- Остановка завершает процесс вместе с дочерними процессами.
- В журнал пишется только имя программы и код возврата, но не аргументы и не вывод.

Команды принимаются только из панели TERMINAL, то есть от пользователя. Модель доступа к сеансу не имеет.
"""

from __future__ import annotations

import codecs
import locale
import logging
import os
import shutil
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

log = logging.getLogger("sirius.terminal")

MAX_HISTORY = 200


def _oem_encoding() -> str:
    if sys.platform == "win32":
        try:
            codecs.lookup("oem")
            return "oem"
        except LookupError:
            pass
    return locale.getpreferredencoding(False) or "utf-8"


class ConsoleDecoder:
    """Декодирует вывод консольных программ Windows.

    Программы пишут кто в UTF-8 (git, python в UTF-8 режиме), кто в кодовой странице консоли
    (cmd, ping, ipconfig на русской Windows — cp866). Каждый фрагмент сначала пробуется как UTF-8;
    незавершённая последовательность UTF-8 в конце фрагмента ждёт следующего фрагмента.
    """

    def __init__(self, fallback: str | None = None) -> None:
        self.fallback = fallback or _oem_encoding()
        self._tail = b""

    def decode(self, data: bytes, final: bool = False) -> str:
        data = self._tail + data
        self._tail = b""
        if not data:
            return ""
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.reason == "unexpected end of data" and not final and len(data) - exc.start < 4:
                try:
                    text = data[: exc.start].decode("utf-8")
                    self._tail = data[exc.start:]
                    return text
                except UnicodeDecodeError:
                    pass
        return data.decode(self.fallback, errors="replace")


class TerminalSession(QObject):
    output = Signal(str, str)        # текст, вид: stdout / stderr / info / error
    finished = Signal(int, float)    # код возврата, длительность в секундах
    running_changed = Signal(bool)

    def __init__(self, cwd: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cwd = Path(cwd) if cwd else Path.home()
        self.history: list[str] = []
        self._process: QProcess | None = None
        self._started_at = 0.0
        self._stdout = ConsoleDecoder()
        self._stderr = ConsoleDecoder()
        self._program = ""
        self._killed = False

    # --- состояние ------------------------------------------------------------

    def is_running(self) -> bool:
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def remember(self, command: str) -> None:
        command = command.strip()
        if command and (not self.history or self.history[-1] != command):
            self.history.append(command)
            del self.history[:-MAX_HISTORY]

    # --- встроенные команды ------------------------------------------------------

    def change_dir(self, target: str | None) -> bool:
        if not target:
            self.output.emit(str(self.cwd), "info")
            return True
        path = Path(os.path.expandvars(os.path.expanduser(target)))
        if not path.is_absolute():
            path = self.cwd / path
        try:
            path = path.resolve()
        except OSError:
            pass
        if not path.is_dir():
            self.output.emit(f"Папка не найдена: {target}", "error")
            return False
        self.cwd = path
        self.output.emit(str(self.cwd), "info")
        return True

    # --- запуск ----------------------------------------------------------------------

    def resolve_program(self, name: str) -> str | None:
        candidate = Path(name)
        if candidate.is_absolute() or os.sep in name or "/" in name:
            path = candidate if candidate.is_absolute() else self.cwd / candidate
            return str(path) if path.is_file() else None
        local = self.cwd / name
        if local.is_file() and local.suffix.lower() in (".exe", ".com"):
            return str(local)
        return shutil.which(name)

    def run(self, argv: list[str]) -> bool:
        """Запускает проверенную команду. Возвращает False, если запуск невозможен."""
        if self.is_running():
            self.output.emit("Предыдущая команда ещё выполняется", "error")
            return False
        program = self.resolve_program(argv[0])
        if program is None:
            self.output.emit(
                f"Команда не найдена: {argv[0]}. Встроенные команды cmd запускайте так: cmd /c {' '.join(argv)}",
                "error",
            )
            return False
        if Path(program).suffix.lower() in (".bat", ".cmd"):
            self.output.emit("Пакетные файлы запускайте явно: cmd /c " + " ".join(argv), "error")
            return False

        process = QProcess(self)
        process.setWorkingDirectory(str(self.cwd))
        process.setProcessChannelMode(QProcess.ProcessChannelMode.SeparateChannels)
        process.readyReadStandardOutput.connect(self._read_stdout)
        process.readyReadStandardError.connect(self._read_stderr)
        process.finished.connect(self._on_finished)
        process.errorOccurred.connect(self._on_error)
        self._process = process
        self._stdout, self._stderr = ConsoleDecoder(), ConsoleDecoder()
        self._program = Path(program).name
        self._killed = False
        self._started_at = time.monotonic()
        log.info("Терминал: запуск %s", self._program)
        process.start(program, argv[1:])
        process.closeWriteChannel()
        self.running_changed.emit(True)
        return True

    def stop(self) -> None:
        """Прерывает команду вместе с дочерними процессами. Не ждёт завершения."""
        process = self._process
        if process is None or process.state() == QProcess.ProcessState.NotRunning:
            return
        self._killed = True
        pid = process.processId()
        if sys.platform == "win32" and pid:
            # TerminateProcess завершил бы только сам процесс, а не запущенные им программы
            QProcess.startDetached("taskkill", ["/PID", str(pid), "/T", "/F"])
        process.kill()

    def shutdown(self, timeout_ms: int = 2000) -> None:
        if self.is_running():
            self.stop()
            if self._process is not None and not self._process.waitForFinished(timeout_ms):
                log.error("Процесс терминала не завершился за %d мс", timeout_ms)

    # --- внутреннее -------------------------------------------------------------------

    def _read_stdout(self) -> None:
        if self._process is not None:
            text = self._stdout.decode(bytes(self._process.readAllStandardOutput()))
            if text:
                self.output.emit(text, "stdout")

    def _read_stderr(self) -> None:
        if self._process is not None:
            text = self._stderr.decode(bytes(self._process.readAllStandardError()))
            if text:
                self.output.emit(text, "stderr")

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            self.output.emit(f"Не удалось запустить: {self._program}", "error")
            log.warning("Терминал: не удалось запустить %s", self._program)
            self._finish(-1)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        for decoder, kind in ((self._stdout, "stdout"), (self._stderr, "stderr")):
            rest = decoder.decode(b"", final=True)
            if rest:
                self.output.emit(rest, kind)
        if self._killed:
            self.output.emit("Команда прервана пользователем", "info")
        elif exit_status == QProcess.ExitStatus.CrashExit:
            self.output.emit("Процесс завершился аварийно", "error")
        self._finish(exit_code)

    def _finish(self, exit_code: int) -> None:
        if self._process is None:
            return
        duration = time.monotonic() - self._started_at
        log.info("Терминал: %s завершён, код %s", self._program, exit_code)
        process, self._process = self._process, None
        process.deleteLater()
        self.running_changed.emit(False)
        self.finished.emit(int(exit_code), duration)
