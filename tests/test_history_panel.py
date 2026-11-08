"""Панель HISTORY: поиск по названиям и открытие диалога из рабочего пространства."""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QMessageBox

from interface.history_panel import HistoryPanel

CHATS = [
    {"file_id": "chat_001", "title": "Рецепт пиццы", "updated_at": "2026-11-07T10:00:00"},
    {"file_id": "chat_002", "title": "Python и списки", "updated_at": "2026-11-07T11:00:00"},
    {"file_id": "chat_003", "title": "ПИТОН: декораторы", "updated_at": "2026-11-07T12:00:00"},
]


def test_search_filters_by_title_case_insensitive(qt_app):
    panel = HistoryPanel()
    panel.set_chats(CHATS)
    panel.search.setText("питон")
    assert panel.visible_titles() == ["ПИТОН: декораторы"]
    panel.search.setText("PYTHON")
    assert panel.visible_titles() == ["Python и списки"]
    panel.search.setText("")
    assert len(panel.visible_titles()) == 3


def test_search_without_results_shows_hint(qt_app):
    panel = HistoryPanel()
    panel.set_chats(CHATS)
    panel.search.setText("нет такого")
    assert panel.visible_titles() == []
    assert not panel.empty_label.isHidden()


def test_filter_survives_list_refresh(qt_app):
    panel = HistoryPanel()
    panel.set_chats(CHATS)
    panel.search.setText("пицц")
    panel.set_chats(CHATS)
    assert panel.visible_titles() == ["Рецепт пиццы"]


@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    yield win
    win.close()


def test_history_panel_opens_dialog(window):
    first = window._current_chat_id
    window.chats.add_message(first, "user", "Первый вопрос")
    window._new_chat()
    assert window._current_chat_id != first
    window.workspace.open("history")
    assert window.workspace.is_open("history")
    window.history.open_chat.emit(first)
    assert window._current_chat_id == first


def test_delete_requires_confirmation(window, monkeypatch):
    chat_id = window._current_chat_id
    window.chats.add_message(chat_id, "user", "Важный диалог")
    original = window.chats.load_chat(chat_id)["id"]
    window._delete_chat(chat_id)  # подтверждение отклонено (заглушка отвечает «Нет»)
    assert window.chats.load_chat(chat_id)["id"] == original
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    window._delete_chat(chat_id)
    # после удаления единственного диалога открывается новый пустой (файл может получить тот же номер)
    assert original not in [c["id"] for c in window.chats.list_chats()]
