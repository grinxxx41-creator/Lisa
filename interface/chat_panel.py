"""Панель чата: карточки сообщений, поле ввода, кнопки отправки и остановки генерации."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QKeyEvent, QPainter
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QScrollArea,
    QSizePolicy, QVBoxLayout, QWidget,
)

from core.code_blocks import extract_code_blocks
from interface.styles import TEAL


class MessageCard(QFrame):
    def __init__(self, role: str, text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.role = role
        self._text = text
        self._code_row: QHBoxLayout | None = None
        if role == "user":
            self.setObjectName("bubbleUser")
        elif role == "error":
            self.setObjectName("bubbleError")
        else:
            self.setObjectName("bubbleLisa")

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(14, 10, 14, 10)
        self._layout.setSpacing(6)

        head = QHBoxLayout()
        caption = {"user": "ВЫ", "assistant": "LISA", "error": "ОШИБКА"}.get(role, role.upper())
        title = QLabel(caption)
        title.setObjectName("secondary")
        title.setStyleSheet("font-size: 10px; letter-spacing: 2px;")
        head.addWidget(title)
        head.addStretch(1)
        self._copy_btn = QPushButton("Копировать")
        self._copy_btn.setObjectName("small")
        self._copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._text))
        head.addWidget(self._copy_btn)
        self._layout.addLayout(head)

        self._body = QLabel()
        self._body.setWordWrap(True)
        self._body.setTextFormat(Qt.TextFormat.MarkdownText)
        self._body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._layout.addWidget(self._body)
        self._code_container = QVBoxLayout()
        self._layout.addLayout(self._code_container)
        self.set_text(text)

    def set_text(self, text: str) -> None:
        self._text = text
        self._body.setText(text)

    def append_text(self, delta: str) -> None:
        self.set_text(self._text + delta)

    @property
    def text(self) -> str:
        return self._text

    def finish(self) -> None:
        """Добавляет кнопки копирования для блоков кода, когда ответ полностью получен."""
        while self._code_container.count():
            item = self._code_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for block in extract_code_blocks(self._text):
            code = block.code
            row = QHBoxLayout()
            label = QLabel(f"Блок кода {block.index} · {block.display_language}")
            label.setObjectName("secondary")
            label.setStyleSheet("font-size: 11px;")
            row.addWidget(label)
            row.addStretch(1)
            btn = QPushButton("Копировать код")
            btn.setObjectName("small")
            btn.clicked.connect(lambda _=False, c=code: QGuiApplication.clipboard().setText(c))
            row.addWidget(btn)
            self._code_container.addLayout(row)


class InputEdit(QPlainTextEdit):
    send_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setPlaceholderText("Напишите LISA… (Enter — отправить, Shift+Enter — новая строка)")
        self.setFixedHeight(84)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
            event.modifiers() & Qt.KeyboardModifier.ShiftModifier
        ):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class BusyIndicator(QWidget):
    """Индикатор генерации в заголовке панели: три точки, анимация идёт только во время ответа."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(30, 14)
        self.setToolTip("LISA формирует ответ")
        self._step = 0
        self._timer = QTimer(self)
        self._timer.setInterval(160)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def set_running(self, running: bool) -> None:
        if running:
            self._step = 0
            self._timer.start()
            self.show()
        else:
            self._timer.stop()
            self.hide()

    def is_running(self) -> bool:
        return self._timer.isActive()

    def _tick(self) -> None:
        self._step = (self._step + 1) % 3
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(3):
            color = QColor(TEAL)
            color.setAlpha(255 if i == self._step else 90)
            p.setBrush(color)
            p.drawEllipse(QPointF(5 + i * 10, 7), 2.6, 2.6)


class ChatPanel(QWidget):
    send_requested = Signal(str)
    stop_requested = Signal()
    new_chat_requested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._busy = False

        self.busy_indicator = BusyIndicator()
        self.new_chat_btn = QPushButton("+ Новый")
        self.new_chat_btn.setObjectName("small")
        self.new_chat_btn.setToolTip("Новый диалог")
        self.new_chat_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.new_chat_btn.clicked.connect(self.new_chat_requested.emit)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._holder = QWidget()
        self._messages = QVBoxLayout(self._holder)
        self._messages.setContentsMargins(6, 6, 6, 6)
        self._messages.setSpacing(10)
        self._messages.addStretch(1)
        self._scroll.setWidget(self._holder)
        root.addWidget(self._scroll, 1)

        bar = QFrame()
        bar.setObjectName("panel")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(10, 10, 10, 10)
        self.input = InputEdit()
        self.input.send_requested.connect(self._on_send)
        bar_layout.addWidget(self.input, 1)
        self.action_btn = QPushButton("Отправить")
        self.action_btn.setObjectName("primary")
        self.action_btn.setMinimumWidth(120)
        self.action_btn.clicked.connect(self._on_action)
        bar_layout.addWidget(self.action_btn)
        root.addWidget(bar)

        self._scroll_timer = QTimer(self)
        self._scroll_timer.setSingleShot(True)
        self._scroll_timer.timeout.connect(self._scroll_to_bottom)

    # --- сообщения ----------------------------------------------------------

    def clear_messages(self) -> None:
        while self._messages.count() > 1:
            item = self._messages.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def add_message(self, role: str, text: str = "") -> MessageCard:
        card = MessageCard(role, text)
        self._messages.insertWidget(self._messages.count() - 1, card)
        self._schedule_scroll()
        return card

    def title_widgets(self) -> list[QWidget]:
        """Индикатор генерации и кнопка нового диалога в заголовке панели CHAT."""
        return [self.busy_indicator, self.new_chat_btn]

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_indicator.set_running(busy)
        self.new_chat_btn.setEnabled(not busy)
        if busy:
            self.action_btn.setText("Стоп")
            self.action_btn.setObjectName("danger")
        else:
            self.action_btn.setText("Отправить")
            self.action_btn.setObjectName("primary")
        self.action_btn.setStyle(self.action_btn.style())

    def is_busy(self) -> bool:
        return self._busy

    def focus_input(self) -> None:
        self.input.setFocus()

    def follow_stream(self) -> None:
        """Прокручивает чат вниз во время потоковой генерации."""
        self._schedule_scroll()

    # --- внутреннее ---------------------------------------------------------

    def _on_action(self) -> None:
        if self._busy:
            self.stop_requested.emit()
        else:
            self._on_send()

    def _on_send(self) -> None:
        if self._busy:
            return
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.input.clear()
        self.send_requested.emit(text)

    def _schedule_scroll(self) -> None:
        self._scroll_timer.start(30)

    def _scroll_to_bottom(self) -> None:
        bar = self._scroll.verticalScrollBar()
        bar.setValue(bar.maximum())
