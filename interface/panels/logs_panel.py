"""Панель LOGS: журнал logs/sirius.log в реальном времени.

Фильтр INFO / WARNING / ERROR, поиск, пауза, автопрокрутка и очистка отображения.
Исходный файл журнала панель никогда не изменяет.
"""

from __future__ import annotations

import html
import logging
from collections import deque
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)

from core.log_reader import LEVELS, LogEntry, LogTailer, filter_entries
from interface.styles import ERROR, TEXT_SECONDARY, WARNING
from interface.workers import LogTailWorker

log = logging.getLogger("sirius.ui.logs")

MAX_ENTRIES = 5000
_LEVEL_COLORS = {"INFO": "#7FD3FF", "WARNING": WARNING, "ERROR": ERROR}


def format_entry(entry: LogEntry) -> str:
    message = html.escape(entry.message)
    if entry.continuation:
        return f'<span style="color:{TEXT_SECONDARY};">{"&nbsp;" * 10}{message}</span>'
    color = _LEVEL_COLORS.get(entry.level, TEXT_SECONDARY)
    pad = "&nbsp;" * max(1, 8 - len(entry.level))  # выравнивание колонки уровня (HTML схлопывает пробелы)
    return (
        f'<span style="color:{TEXT_SECONDARY};">{entry.clock}</span>&nbsp;&nbsp;'
        f'<span style="color:{color};">{entry.level}</span>{pad}'
        f'<span style="color:{TEXT_SECONDARY};">{html.escape(entry.source)}</span>&nbsp;&nbsp;'
        f"{message}"
    )


class LogsPanel(QWidget):
    def __init__(self, log_path: Path, interval_ms: int = 700, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tailer = LogTailer(log_path)
        self._interval_ms = interval_ms
        self._worker: LogTailWorker | None = None
        self._threads: list[LogTailWorker] = []
        self._entries: deque[LogEntry] = deque(maxlen=MAX_ENTRIES)
        self._pending: list[LogEntry] = []
        self._paused = False

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 2)
        root.setSpacing(6)

        filters = QHBoxLayout()
        filters.setSpacing(4)
        self.level_buttons: dict[str, QPushButton] = {}
        for level in LEVELS:
            btn = QPushButton(level)
            btn.setObjectName("dockButton")
            btn.setCheckable(True)
            btn.setChecked(True)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.toggled.connect(self._rerender)
            filters.addWidget(btn)
            self.level_buttons[level] = btn
        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rerender)
        filters.addWidget(self.search, 1)
        root.addLayout(filters)

        self.view = QPlainTextEdit()
        self.view.setObjectName("console")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setMaximumBlockCount(MAX_ENTRIES)
        root.addWidget(self.view, 1)

        controls = QHBoxLayout()
        self.autoscroll = QCheckBox("Автопрокрутка")
        self.autoscroll.setChecked(True)
        controls.addWidget(self.autoscroll)
        self.status = QLabel("")
        self.status.setObjectName("panelHint")
        controls.addWidget(self.status, 1)
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.setObjectName("small")
        self.pause_btn.setCheckable(True)
        self.pause_btn.toggled.connect(self.set_paused)
        controls.addWidget(self.pause_btn)
        self.clear_btn = QPushButton("Очистить")
        self.clear_btn.setObjectName("small")
        self.clear_btn.setToolTip("Очистить отображение. Файл журнала не изменяется.")
        self.clear_btn.clicked.connect(self.clear_view)
        controls.addWidget(self.clear_btn)
        root.addLayout(controls)
        self._update_status()

    # --- видимость ------------------------------------------------------------

    def panel_shown(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        worker = LogTailWorker(self.tailer, self._interval_ms, parent=self)
        worker.entries.connect(self.add_entries)
        worker.finished.connect(self._on_worker_finished)
        self._worker = worker
        self._threads.append(worker)
        worker.start()

    def panel_hidden(self) -> None:
        if self._worker is not None:
            self._worker.stop()
            self._worker = None

    def is_reading(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self, timeout_ms: int = 3000) -> None:
        self.panel_hidden()
        for worker in list(self._threads):
            worker.stop()
            if not worker.wait(timeout_ms):
                log.error("Поток чтения журнала не завершился за %d мс", timeout_ms)

    def _on_worker_finished(self) -> None:
        worker = self.sender()
        if worker in self._threads:
            self._threads.remove(worker)
            worker.deleteLater()

    # --- записи ------------------------------------------------------------------

    def active_levels(self) -> set[str]:
        return {lvl for lvl, btn in self.level_buttons.items() if btn.isChecked()}

    def add_entries(self, entries: list[LogEntry]) -> None:
        if self._paused:
            self._pending.extend(entries)
            self._update_status()
            return
        self._entries.extend(entries)
        visible = filter_entries(entries, self.active_levels(), self.search.text())
        if visible:
            self._append(visible)
        self._update_status()

    def visible_entries(self) -> list[LogEntry]:
        return filter_entries(self._entries, self.active_levels(), self.search.text())

    def _append(self, entries: list[LogEntry]) -> None:
        bar = self.view.verticalScrollBar()
        keep = bar.value()
        self.view.appendHtml("<br>".join(format_entry(e) for e in entries))
        if self.autoscroll.isChecked():
            bar.setValue(bar.maximum())
        else:
            bar.setValue(keep)
        self.view.horizontalScrollBar().setValue(0)

    def _rerender(self, *_args) -> None:
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        visible = self.visible_entries()
        if visible:
            self._append(visible)
        self.view.setUpdatesEnabled(True)
        self._update_status()

    def set_paused(self, paused: bool) -> None:
        self._paused = paused
        if self.pause_btn.isChecked() != paused:
            self.pause_btn.setChecked(paused)
        self.pause_btn.setText("Продолжить" if paused else "Пауза")
        if not paused and self._pending:
            pending, self._pending = self._pending, []
            self.add_entries(pending)
        self._update_status()

    def clear_view(self) -> None:
        """Очищает только отображение: файл журнала остаётся без изменений."""
        self._entries.clear()
        self._pending.clear()
        self.view.clear()
        self._update_status()

    def _update_status(self) -> None:
        text = f"Записей: {len(self._entries)}"
        if self._paused:
            text += f" · пауза, новых: {len(self._pending)}"
        self.status.setText(text)
