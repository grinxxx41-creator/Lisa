"""Панель управления рабочим пространством: название, статус, переключатели панелей и общие действия."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QWidget


class ControlBar(QFrame):
    toggle_panel = Signal(str)
    hide_all_requested = Signal()
    reset_layout_requested = Signal()

    def __init__(self, panels: list[tuple[str, str, str]], parent: QWidget | None = None) -> None:
        """panels: (id, короткое название, подсказка) в порядке показа."""
        super().__init__(parent)
        self.setObjectName("controlBar")
        self.setFixedHeight(46)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 4, 8, 4)
        layout.setSpacing(4)

        title = QLabel("SIRIUS")
        title.setObjectName("title")
        layout.addWidget(title)
        layout.addSpacing(12)

        self.status_label = QLabel("Проверка Ollama…")
        self.status_label.setObjectName("secondary")
        self.status_label.setMinimumWidth(40)
        self.status_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.status_label, 1)

        self._buttons: dict[str, QPushButton] = {}
        for panel_id, caption, tooltip in panels:
            btn = QPushButton(caption)
            btn.setObjectName("dockButton")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setToolTip(tooltip)
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.clicked.connect(lambda _checked=False, pid=panel_id: self.toggle_panel.emit(pid))
            layout.addWidget(btn)
            self._buttons[panel_id] = btn

        layout.addSpacing(6)
        self.hide_all_btn = self._bar_button("Скрыть", "Скрыть все панели")
        self.hide_all_btn.clicked.connect(self.hide_all_requested.emit)
        layout.addWidget(self.hide_all_btn)
        self.reset_btn = self._bar_button("Сброс", "Вернуть стандартное расположение панелей")
        self.reset_btn.clicked.connect(self.reset_layout_requested.emit)
        layout.addWidget(self.reset_btn)
        layout.addSpacing(8)

        self._right = QHBoxLayout()
        self._right.setSpacing(8)
        layout.addLayout(self._right)

    @staticmethod
    def _bar_button(text: str, tooltip: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setObjectName("barButton")
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        return btn

    def add_right_widget(self, widget: QWidget) -> None:
        self._right.addWidget(widget)

    def button(self, panel_id: str) -> QPushButton:
        return self._buttons[panel_id]

    def set_panel_open(self, panel_id: str, is_open: bool) -> None:
        btn = self._buttons.get(panel_id)
        if btn is not None and btn.isChecked() != is_open:
            btn.setChecked(is_open)
