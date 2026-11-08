"""Панель истории диалогов: список чатов и действия над ними."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)


class HistoryPanel(QFrame):
    new_chat = Signal()
    open_chat = Signal(str)     # file_id
    rename_chat = Signal(str)   # file_id
    delete_chat = Signal(str)   # file_id

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # панель живёт внутри плавающей панели HISTORY: собственная рамка и заголовок не нужны
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 2)
        layout.setSpacing(8)

        self.new_btn = QPushButton("+ Новый диалог")
        self.new_btn.setObjectName("primary")
        self.new_btn.clicked.connect(self.new_chat.emit)
        layout.addWidget(self.new_btn)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Поиск по названию…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._apply_filter)
        layout.addWidget(self.search)

        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(self._on_open)
        self.list.itemClicked.connect(self._on_open)
        layout.addWidget(self.list, 1)
        self.empty_label = QLabel("Ничего не найдено")
        self.empty_label.setObjectName("panelHint")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.hide()
        layout.addWidget(self.empty_label)

        actions = QHBoxLayout()
        self.rename_btn = QPushButton("Переименовать")
        self.rename_btn.setObjectName("small")
        self.rename_btn.clicked.connect(self._on_rename)
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.setProperty("small", True)
        self.delete_btn.clicked.connect(self._on_delete)
        actions.addWidget(self.rename_btn)
        actions.addWidget(self.delete_btn)
        layout.addLayout(actions)

    def set_chats(self, chats: list[dict], current_id: str | None = None) -> None:
        self.list.blockSignals(True)
        self.list.clear()
        for chat in chats:
            item = QListWidgetItem(f"{chat['title']}\n{_format_date(chat['updated_at'])}")
            item.setData(Qt.ItemDataRole.UserRole, chat["file_id"])
            self.list.addItem(item)
            item.setData(Qt.ItemDataRole.UserRole + 1, chat["title"])
            if chat["file_id"] == current_id:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self._apply_filter(self.search.text())

    def _apply_filter(self, text: str = "") -> None:
        """Скрывает диалоги, в названии которых нет строки поиска (без учёта регистра)."""
        needle = text.strip().casefold()
        shown = 0
        for row in range(self.list.count()):
            item = self.list.item(row)
            title = str(item.data(Qt.ItemDataRole.UserRole + 1) or "")
            hidden = bool(needle) and needle not in title.casefold()
            item.setHidden(hidden)
            shown += not hidden
        self.empty_label.setVisible(self.list.count() > 0 and shown == 0)

    def visible_titles(self) -> list[str]:
        return [
            str(self.list.item(r).data(Qt.ItemDataRole.UserRole + 1))
            for r in range(self.list.count()) if not self.list.item(r).isHidden()
        ]

    def _selected_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None or item.isHidden():
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _on_open(self, item: QListWidgetItem) -> None:
        self.open_chat.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_rename(self) -> None:
        file_id = self._selected_id()
        if file_id:
            self.rename_chat.emit(file_id)

    def _on_delete(self) -> None:
        file_id = self._selected_id()
        if file_id:
            self.delete_chat.emit(file_id)


def _format_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return ""
