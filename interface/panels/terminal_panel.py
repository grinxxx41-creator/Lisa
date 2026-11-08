"""Панель TERMINAL: ограниченная консоль для команд, которые пользователь вводит сам.

Ограничения (видны по команде help):
- без оболочки: встроенные команды cmd запускаются явно, например «cmd /c dir»;
- без прав администратора; если SIRIUS запущен от администратора, консоль отключена;
- без интерактивного ввода: стандартный ввод программы закрыт;
- опасные команды требуют отдельного подтверждения;
- команды из ответов LISA сюда не передаются и автоматически не выполняются.
"""

from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.command_policy import check_command, is_elevated
from core.terminal_session import TerminalSession
from interface.styles import CYAN, ERROR, SUCCESS, TEAL, TEXT_SECONDARY, WARNING

MAX_BLOCKS = 5000

HELP_TEXT = """Ограниченная консоль SIRIUS. Команды выполняются только после вашего ввода.
  cd <папка>    сменить папку (cd без аргумента — показать текущую)
  clear, cls    очистить вывод
  history       команды этого сеанса
  help          эта справка
Программы запускаются без оболочки. Команды cmd: cmd /c dir, PowerShell: powershell -Command Get-Date
Удаление, перемещение, реестр, службы и выключение требуют подтверждения.
Повышение прав запрещено. Интерактивный ввод не поддерживается. Стоп — прервать команду."""

_KIND_COLORS = {"stdout": "#DCE6F5", "stderr": WARNING, "info": TEXT_SECONDARY, "error": ERROR}


class _CommandInput(QLineEdit):
    """Поле ввода с историей команд по стрелкам вверх и вниз."""

    def __init__(self, history: list[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._history = history
        self._pos: int | None = None

    def reset_position(self) -> None:
        self._pos = None

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._history:
            if event.key() == Qt.Key.Key_Up:
                self._pos = len(self._history) - 1 if self._pos is None else max(0, self._pos - 1)
            elif self._pos is not None:
                self._pos += 1
                if self._pos >= len(self._history):
                    self._pos = None
                    self.clear()
                    return
            if self._pos is not None:
                self.setText(self._history[self._pos])
            return
        super().keyPressEvent(event)


class TerminalPanel(QWidget):
    def __init__(self, cwd: Path | None = None, elevated: bool | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session = TerminalSession(cwd, self)
        self.session.output.connect(self._print)
        self.session.finished.connect(self._on_finished)
        self.session.running_changed.connect(self._on_running_changed)
        self.elevated = is_elevated() if elevated is None else elevated

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 2)
        root.setSpacing(6)

        self.output = QPlainTextEdit()
        self.output.setObjectName("console")
        self.output.setReadOnly(True)
        self.output.setMaximumBlockCount(MAX_BLOCKS)
        self.output.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)  # как в консоли: пробелы сохраняются
        root.addWidget(self.output, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.cwd_label = QLabel()
        self.cwd_label.setObjectName("panelHint")
        self.cwd_label.setMaximumWidth(220)
        row.addWidget(self.cwd_label)
        self.input = _CommandInput(self.session.history)
        self.input.setObjectName("consoleInput")
        self.input.setPlaceholderText("Команда… (help — справка)")
        self.input.returnPressed.connect(self.submit_input)
        row.addWidget(self.input, 1)
        self.run_btn = QPushButton("Выполнить")
        self.run_btn.setObjectName("small")
        self.run_btn.clicked.connect(self._on_run_clicked)
        row.addWidget(self.run_btn)
        self.clear_btn = QPushButton("Очистить")
        self.clear_btn.setObjectName("small")
        self.clear_btn.clicked.connect(self.output.clear)
        row.addWidget(self.clear_btn)
        root.addLayout(row)

        self._update_cwd()
        if self.elevated:
            self.input.setEnabled(False)
            self.run_btn.setEnabled(False)
            self._print("SIRIUS запущен с правами администратора. Консоль отключена в целях безопасности.\n"
                        "Перезапустите SIRIUS от имени обычного пользователя.", "error")
        else:
            self._print("Ограниченная консоль. Команды выполняются только по вашему вводу. help — справка.", "info")

    # --- ввод ---------------------------------------------------------------------

    def _on_run_clicked(self) -> None:
        if self.session.is_running():
            self.session.stop()
        else:
            self.submit_input()

    def submit_input(self) -> None:
        text = self.input.text().strip()
        if not text or self.session.is_running():
            return
        self.input.clear()
        self.input.reset_position()
        self.execute(text)

    def execute(self, text: str) -> bool:
        """Выполняет команду, которую ввёл пользователь. Возвращает True, если процесс запущен."""
        if self.elevated:
            return False
        self._print_command(text)
        self.session.remember(text)
        check = check_command(text)
        if check.builtin:
            return self._run_builtin(check.builtin, check.argv)
        if not check.allowed:
            self._print(f"Команда не выполнена: {check.reason}", "error")
            return False
        if check.needs_confirmation and not self._confirm(text, check.reason):
            self._print("Отменено пользователем", "info")
            return False
        return self.session.run(check.argv)

    def _confirm(self, command: str, reason: str) -> bool:
        answer = QMessageBox.question(
            self, "Подтверждение команды",
            f"Команда может изменить или удалить данные:\n\n{command}\n\nПричина: {reason}\n\nВыполнить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _run_builtin(self, name: str, argv: list[str]) -> bool:
        if name == "clear":
            self.output.clear()
        elif name == "help":
            self._print(HELP_TEXT, "info")
        elif name == "history":
            lines = [f"{i:>3}  {cmd}" for i, cmd in enumerate(self.session.history, start=1)]
            self._print("\n".join(lines) or "История пуста", "info")
        elif name == "cd":
            self.session.change_dir(" ".join(argv[1:]) or None)
            self._update_cwd()
        return False

    # --- вывод ------------------------------------------------------------------------

    def _print_command(self, text: str) -> None:
        self.output.appendHtml(
            f'<span style="color:{TEAL};">{html.escape(self._short_cwd())}&gt;</span> '
            f'<span style="color:{CYAN};">{html.escape(text)}</span>'
        )
        self._scroll_down()

    def _print(self, text: str, kind: str) -> None:
        color = _KIND_COLORS.get(kind, TEXT_SECONDARY)
        body = html.escape(text.rstrip("\r\n")).replace("\r\n", "\n").replace(" ", "&nbsp;").replace("\n", "<br>")
        if body:
            self.output.appendHtml(f'<span style="color:{color};">{body}</span>')
            self._scroll_down()

    def _on_finished(self, exit_code: int, duration: float) -> None:
        color = SUCCESS if exit_code == 0 else ERROR
        self.output.appendHtml(
            f'<span style="color:{color};">[код возврата {exit_code}]</span> '
            f'<span style="color:{TEXT_SECONDARY};">{duration:.2f} с</span>'
        )
        self._scroll_down()
        self.input.setFocus()

    def _on_running_changed(self, running: bool) -> None:
        self.run_btn.setText("Стоп" if running else "Выполнить")
        self.run_btn.setObjectName("danger" if running else "small")
        self.run_btn.setStyle(self.run_btn.style())
        self.input.setEnabled(not running and not self.elevated)

    def _scroll_down(self) -> None:
        bar = self.output.verticalScrollBar()
        bar.setValue(bar.maximum())
        self.output.horizontalScrollBar().setValue(0)  # начало строк остаётся видно

    def _short_cwd(self) -> str:
        return str(self.session.cwd)

    def _update_cwd(self) -> None:
        path = str(self.session.cwd)
        self.cwd_label.setText(path if len(path) <= 32 else "…" + path[-31:])
        self.cwd_label.setToolTip(path)

    # --- жизненный цикл --------------------------------------------------------------

    def panel_shown(self) -> None:
        if self.input.isEnabled():
            self.input.setFocus()

    def shutdown(self) -> None:
        self.session.shutdown()
