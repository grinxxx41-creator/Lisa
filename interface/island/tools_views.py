"""Инструменты островка (режим INTERACTIVE): файловая полка, история буфера обмена, Pomodoro,
быстрые действия. Экраны показывают данные и сообщают о действиях сигналами; сами данные
хранит и меняет контроллер (interface/island/controller.py)."""

from __future__ import annotations

import os

from PySide6.QtCore import QFileInfo, QMimeData, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDrag, QIcon, QImageReader, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QFileIconProvider, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListView, QListWidget, QListWidgetItem, QStackedWidget, QVBoxLayout, QWidget)

from interface import styles
from interface.dotmatrix import DotLabel
from interface.island.views import format_ago, label
from interface.island.widgets import Chip, ElidedLabel, IconButton, SmoothBar
from interface.styles import CYAN, SUCCESS, TEAL, TEXT_SECONDARY, WARNING
from island.pomodoro import IDLE, PAUSED, RUNNING, WORK

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp", ".ico"}
THUMB_MAX_BYTES = 15 * 1024 * 1024       # миниатюры больших изображений не строим — берём значок файла
THUMB = 44


class ShelfList(QListWidget):
    """Список файлов полки. Перетаскивание наружу только копирует: файл с диска не уходит."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("islandList")
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(False)
        self.setMovement(QListView.Movement.Static)
        self.setIconSize(QSize(THUMB, THUMB))
        self.setGridSize(QSize(92, 84))
        self.setUniformItemSizes(True)
        self.setWordWrap(False)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragEnabled(True)
        self.setAcceptDrops(False)        # приём файлов обрабатывает само окно островка
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)

    def startDrag(self, supported) -> None:  # noqa: N802 — имя Qt
        paths = [i.data(Qt.ItemDataRole.UserRole) for i in self.selectedItems()]
        paths = [p for p in paths if p and os.path.exists(p)]
        if not paths:
            return
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile(p) for p in paths])
        drag = QDrag(self)
        drag.setMimeData(mime)
        item = self.currentItem()
        if item is not None and not item.icon().isNull():
            drag.setPixmap(item.icon().pixmap(THUMB, THUMB))
        drag.exec(Qt.DropAction.CopyAction)     # разрешено только копирование


class ShelfPage(QWidget):
    open_requested = Signal(str)
    reveal_requested = Signal(str)
    remove_requested = Signal(str)
    clear_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icons = QFileIconProvider()
        self._thumbs: dict[tuple[str, float], QIcon] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.list = ShelfList()
        self.list.itemDoubleClicked.connect(lambda item: self.open_requested.emit(item.data(Qt.ItemDataRole.UserRole)))
        self.list.itemSelectionChanged.connect(self._sync_buttons)
        lay.addWidget(self.list, 1)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.hint = label("Перетащите файлы на островок — они останутся под рукой", "isSub", elided=True)
        self.open_btn = Chip("Открыть", "file")
        self.reveal_btn = Chip("В папке", "folder")
        self.remove_btn = Chip("Убрать с полки", "close")
        self.clear_btn = Chip("Очистить", "delete")
        self.open_btn.clicked.connect(lambda: self._each(self.open_requested))
        self.reveal_btn.clicked.connect(lambda: self._each(self.reveal_requested, first_only=True))
        self.remove_btn.clicked.connect(lambda: self._each(self.remove_requested))
        self.clear_btn.clicked.connect(self.clear_requested)
        self.remove_btn.setToolTip("Убирает только ссылку с полки. Файл на диске остаётся.")
        self.clear_btn.setToolTip("Очищает полку. Файлы на диске остаются.")
        row.addWidget(self.hint, 1)
        for chip in (self.open_btn, self.reveal_btn, self.remove_btn, self.clear_btn):
            row.addWidget(chip)
        lay.addLayout(row)
        self.set_items([])

    def _each(self, signal, first_only: bool = False) -> None:
        paths = [i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()]
        for path in paths[:1] if first_only else paths:
            signal.emit(path)

    def _sync_buttons(self) -> None:
        selected = bool(self.list.selectedItems())
        for chip in (self.open_btn, self.reveal_btn, self.remove_btn):
            chip.setEnabled(selected)
        self.clear_btn.setEnabled(self.list.count() > 0)

    def _icon(self, path: str) -> QIcon:
        suffix = os.path.splitext(path)[1].lower()
        if suffix in IMAGE_SUFFIXES:
            try:
                stat = os.stat(path)
            except OSError:
                stat = None
            if stat is not None and stat.st_size <= THUMB_MAX_BYTES:
                key = (path, stat.st_mtime)
                if key not in self._thumbs:
                    reader = QImageReader(path)
                    reader.setAutoTransform(True)
                    size = reader.size()
                    if size.isValid():
                        reader.setScaledSize(size.scaled(THUMB * 2, THUMB * 2, Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    self._thumbs[key] = QIcon(QPixmap.fromImage(image)) if not image.isNull() else QIcon()
                if not self._thumbs[key].isNull():
                    return self._thumbs[key]
        return self._icons.icon(QFileInfo(path))

    def set_items(self, items, status: str = "") -> None:
        selected = {i.data(Qt.ItemDataRole.UserRole) for i in self.list.selectedItems()}
        self.list.clear()
        for entry in items:
            exists = entry.exists
            item = QListWidgetItem(self._icon(entry.path) if exists else QIcon(), entry.name)
            item.setData(Qt.ItemDataRole.UserRole, entry.path)
            item.setToolTip(entry.path if exists else f"Файл не найден:\n{entry.path}")
            if not exists:
                item.setForeground(QColor(TEXT_SECONDARY))
                item.setText("нет файла")
            item.setSizeHint(QSize(88, 80))
            self.list.addItem(item)
            item.setSelected(entry.path in selected)      # выбор переживает обновление списка
        if status:
            self.hint.setText(status)
        elif not items:
            self.hint.setText("Перетащите файлы на островок — они останутся под рукой")
        else:
            self.hint.setText(f"Файлов: {len(items)} · двойной щелчок открывает, перетаскивание копирует")
        self._sync_buttons()


class ClipRow(QWidget):
    copy = Signal(int)
    remove = Signal(int)

    def __init__(self, entry, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.entry_id = entry.id
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 0, 2, 0)
        lay.setSpacing(8)
        self.text = ElidedLabel(entry.preview(200))
        self.text.setObjectName("isLine")
        self.text.setToolTip(entry.text[:1500])
        self.when = label(format_ago(entry.time), "isSub")
        copy_btn = IconButton("copy", "Скопировать снова", 24)
        copy_btn.clicked.connect(lambda: self.copy.emit(self.entry_id))
        del_btn = IconButton("close", "Удалить из истории", 24)
        del_btn.clicked.connect(lambda: self.remove.emit(self.entry_id))
        lay.addWidget(self.text, 1)
        lay.addWidget(self.when)
        lay.addWidget(copy_btn)
        lay.addWidget(del_btn)

    def mouseDoubleClickEvent(self, event) -> None:
        self.copy.emit(self.entry_id)


class ClipboardPage(QWidget):
    copy_requested = Signal(int)
    remove_requested = Signal(int)
    clear_requested = Signal()
    query_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.search = QLineEdit()
        self.search.setObjectName("islandSearch")
        self.search.setPlaceholderText("Поиск в истории буфера…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.query_changed)
        self.clear_btn = Chip("Очистить", "delete")
        self.clear_btn.clicked.connect(self.clear_requested)
        head.addWidget(self.search, 1)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)
        self.list = QListWidget()
        self.list.setObjectName("islandList")
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.list, 1)
        self.status = label("", "isSub", elided=True)
        lay.addWidget(self.status)
        self.set_items([])

    def set_items(self, entries, status: str = "") -> None:
        self.list.clear()
        for entry in entries:
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 28))
            row = ClipRow(entry)
            row.copy.connect(self.copy_requested)
            row.remove.connect(self.remove_requested)
            self.list.addItem(item)
            self.list.setItemWidget(item, row)
        self.clear_btn.setEnabled(bool(entries))
        if status:
            self.status.setText(status)
        elif not entries:
            self.status.setText("Ничего не найдено" if self.search.text().strip()
                                else "История пуста: скопированный текст появится здесь")
        else:
            self.status.setText(f"Записей: {len(entries)} · двойной щелчок копирует снова")

    def set_status(self, text: str) -> None:
        self.status.setText(text)


class PomodoroPage(QWidget):
    start_requested = Signal()
    pause_requested = Signal()
    skip_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = IDLE
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        if styles.DOT_MATRIX:      # таймер точечным шрифтом; «негорящие» точки едва видны
            self.time = DotLabel("25:00", dot=4.4, gap=2.0, color=styles.WHITE, ghost_alpha=12)
        else:
            self.time = QLabel("25:00")
        self.time.setObjectName("isBig")
        self.time.setMinimumWidth(150)
        lay.addWidget(self.time)
        column = QVBoxLayout()
        column.setSpacing(6)
        self.phase = label("Работа", "isTitle")
        self.rounds = label("Таймер не запущен", "isSub")
        self.bar = SmoothBar(TEAL, CYAN)
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.main_btn = Chip("Старт", "play")
        self.skip_btn = Chip("Пропустить", "next")
        self.reset_btn = Chip("Завершить", "stop")
        self.main_btn.clicked.connect(self._on_main)
        self.skip_btn.clicked.connect(self.skip_requested)
        self.reset_btn.clicked.connect(self.reset_requested)
        self.skip_btn.setToolTip("Закончить текущий отрезок и перейти к следующему")
        self.reset_btn.setToolTip("Завершить цикл и сбросить таймер")
        for chip in (self.main_btn, self.skip_btn, self.reset_btn):
            buttons.addWidget(chip)
        buttons.addStretch(1)
        column.addStretch(1)
        column.addWidget(self.phase)
        column.addWidget(self.rounds)
        column.addWidget(self.bar)
        column.addLayout(buttons)
        column.addStretch(1)
        lay.addLayout(column, 1)

    def _on_main(self) -> None:
        (self.pause_requested if self._state == RUNNING else self.start_requested).emit()

    def set_state(self, state: str, phase: str, phase_title: str, remaining: str, progress: float,
                  rounds_done: int, rounds: int) -> None:
        self._state = state
        self.time.setText(remaining)
        self.phase.setText(phase_title)
        color = CYAN if phase == WORK else SUCCESS
        self.phase.setStyleSheet(f"color: {color if state != IDLE else TEXT_SECONDARY};")
        self.bar.set_colors(TEAL if phase == WORK else SUCCESS, CYAN if phase == WORK else TEAL)
        self.bar.set_value(progress)
        if state == IDLE:
            self.rounds.setText(f"Цикл: {rounds} рабочих отрезков, затем длинный перерыв")
        else:
            current = rounds_done % rounds + (1 if phase == WORK else 0)
            self.rounds.setText(f"Круг {max(1, min(rounds, current or rounds))} из {rounds}"
                                + (" · пауза" if state == PAUSED else ""))
        self.main_btn.setText("Пауза" if state == RUNNING else "Продолжить" if state == PAUSED else "Старт")
        self.main_btn.set_glyph("pause" if state == RUNNING else "play")
        self.main_btn.updateGeometry()
        self.skip_btn.setEnabled(state != IDLE)
        self.reset_btn.setEnabled(state != IDLE)


class ActionsPage(QWidget):
    triggered = Signal(str)
    COLUMNS = 4

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(8)
        self._grid.setVerticalSpacing(8)
        lay.addLayout(self._grid)
        lay.addStretch(1)
        self.status = label("Свои действия добавляются в настройках: вкладка «Островок»", "isSub", elided=True)
        lay.addWidget(self.status)

    def set_actions(self, actions) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, action in enumerate(actions):
            chip = Chip(action.title, action.icon)
            chip.setToolTip(action.hint)
            chip.clicked.connect(lambda _checked=False, a=action.id: self.triggered.emit(a))
            self._grid.addWidget(chip, index // self.COLUMNS, index % self.COLUMNS, Qt.AlignmentFlag.AlignLeft)
        self._grid.setColumnStretch(self.COLUMNS, 1)

    def set_status(self, text: str, ok: bool = True) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {TEXT_SECONDARY if ok else WARNING};")


class ToolsView(QWidget):
    HEIGHT = 168
    TABS = (("shelf", "Полка", "shelf"), ("clipboard", "Буфер", "clipboard"),
            ("pomodoro", "Pomodoro", "timer"), ("actions", "Действия", "bolt"))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        tabs = QHBoxLayout()
        tabs.setSpacing(6)
        self.shelf = ShelfPage()
        self.clipboard = ClipboardPage()
        self.pomodoro = PomodoroPage()
        self.actions = ActionsPage()
        self.pages = {"shelf": self.shelf, "clipboard": self.clipboard, "pomodoro": self.pomodoro,
                      "actions": self.actions}
        self.stack = QStackedWidget()
        self.chips: dict[str, Chip] = {}
        for key, title, glyph in self.TABS:
            chip = Chip(title, glyph, checkable=True)
            chip.clicked.connect(lambda _checked=False, k=key: self.show_tab(k))
            self.chips[key] = chip
            tabs.addWidget(chip)
            self.stack.addWidget(self.pages[key])
        tabs.addStretch(1)
        self.empty = label("Все инструменты выключены в настройках островка", "isSub")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty)
        lay.addLayout(tabs)
        lay.addWidget(self.stack, 1)
        self._enabled = {key: True for key in self.pages}
        self._current = "shelf"
        self.show_tab("shelf")

    def set_features(self, **enabled: bool) -> None:
        self._enabled.update({k: bool(v) for k, v in enabled.items() if k in self.pages})
        for key, chip in self.chips.items():
            chip.setVisible(self._enabled[key])
        self.show_tab(self._current)

    def any_enabled(self) -> bool:
        return any(self._enabled.values())

    def current_tab(self) -> str:
        return self._current

    def show_tab(self, key: str) -> None:
        if not self._enabled.get(key, False):
            key = next((k for k, on in self._enabled.items() if on), "")
        if not key:
            self.stack.setCurrentWidget(self.empty)
            return
        self._current = key
        for name, chip in self.chips.items():
            chip.setChecked(name == key)
        self.stack.setCurrentWidget(self.pages[key])

