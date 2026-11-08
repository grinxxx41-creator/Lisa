"""Панель CODE: блоки кода из реальных ответов LISA в текущем диалоге.

Код только показывается, выделяется и копируется. Панель ничего не выполняет.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QSyntaxHighlighter, QTextCharFormat, QTextDocument
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from core.code_blocks import CodeBlock, extract_code_blocks
from interface.styles import CYAN, TEAL, TEXT_SECONDARY, WARNING

log = logging.getLogger("sirius.ui.code")

EMPTY_TEXT = "No code generated"

try:  # Pygments необязателен: без него код показывается без подсветки
    from pygments.lexers import get_lexer_by_name
    from pygments.token import Comment, Keyword, Name, Number, Operator, String, Token
    from pygments.util import ClassNotFound
except ImportError:  # pragma: no cover - зависит от окружения
    get_lexer_by_name = None


def _fmt(color: str, bold: bool = False, italic: bool = False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Weight.DemiBold)
    f.setFontItalic(italic)
    return f


def _token_formats() -> list[tuple[object, QTextCharFormat]]:
    if get_lexer_by_name is None:
        return []
    # порядок важен: более частные типы токенов раньше общих
    return [
        (Comment, _fmt("#6B7891", italic=True)),
        (String, _fmt(TEAL)),
        (Number, _fmt(WARNING)),
        (Keyword, _fmt("#A08CFF", bold=True)),
        (Name.Function, _fmt(CYAN)),
        (Name.Class, _fmt(CYAN, bold=True)),
        (Name.Builtin, _fmt("#7FD3FF")),
        (Name.Decorator, _fmt("#A08CFF")),
        (Operator, _fmt(TEXT_SECONDARY)),
    ]


class PygmentsHighlighter(QSyntaxHighlighter):
    """Подсветка готового (неизменяемого) кода.

    Весь текст разбирается Pygments один раз, затем каждая строка документа получает свои фрагменты.
    Так многострочные строки и комментарии подсвечиваются правильно.
    """

    def __init__(self, document: QTextDocument) -> None:
        super().__init__(document)
        self._formats = _token_formats()
        self._lines: list[list[tuple[int, int, QTextCharFormat]]] = []

    def prepare(self, code: str, language: str) -> None:
        """Готовит подсветку до установки текста: документ подсвечивается один раз."""
        self._lines = self._tokenize(code, language)

    def _format_for(self, ttype) -> QTextCharFormat | None:
        for base, fmt in self._formats:
            if ttype in base:
                return fmt
        return None

    def _tokenize(self, code: str, language: str) -> list[list[tuple[int, int, QTextCharFormat]]]:
        lines: list[list[tuple[int, int, QTextCharFormat]]] = [[]]
        if get_lexer_by_name is None or not language:
            return lines
        try:
            lexer = get_lexer_by_name(language, stripnl=False, ensurenl=False)
        except ClassNotFound:
            return lines
        except Exception:
            log.debug("Не удалось создать лексер %s", language, exc_info=True)
            return lines
        col = 0
        for ttype, value in lexer.get_tokens(code):
            fmt = self._format_for(ttype)
            parts = value.split("\n")
            for i, part in enumerate(parts):
                if i > 0:
                    lines.append([])
                    col = 0
                if part and fmt is not None:
                    lines[-1].append((col, len(part), fmt))
                col += len(part)
        return lines

    def highlightBlock(self, text: str) -> None:
        number = self.currentBlock().blockNumber()
        if 0 <= number < len(self._lines):
            for start, length, fmt in self._lines[number]:
                self.setFormat(start, length, fmt)


@dataclass(frozen=True)
class _Entry:
    answer: int        # номер ответа LISA в диалоге, с 1
    block: CodeBlock


class CodePanel(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._entries: list[_Entry] = []
        self._answers = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(4, 0, 4, 2)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self.selector = QComboBox()
        self.selector.setToolTip("Блоки кода из ответов LISA: сначала новые")
        self.selector.currentIndexChanged.connect(self._show_current)
        bar.addWidget(self.selector, 1)
        self.copy_btn = QPushButton("Копировать")
        self.copy_btn.setObjectName("small")
        self.copy_btn.clicked.connect(self.copy_current)
        bar.addWidget(self.copy_btn)
        root.addLayout(bar)

        self.stack = QStackedWidget()
        self.empty_label = QLabel(EMPTY_TEXT)
        self.empty_label.setObjectName("emptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stack.addWidget(self.empty_label)
        self.view = QPlainTextEdit()
        self.view.setObjectName("codeView")
        self.view.setReadOnly(True)  # выделение и копирование работают, изменение — нет
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.view.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        self.highlighter = PygmentsHighlighter(self.view.document())
        self.stack.addWidget(self.view)
        root.addWidget(self.stack, 1)

        self.info = QLabel("")
        self.info.setObjectName("panelHint")
        root.addWidget(self.info)
        self._refresh()

    # --- данные --------------------------------------------------------------

    def set_messages(self, assistant_texts: list[str]) -> None:
        """Все ответы LISA текущего диалога (при открытии диалога)."""
        self._entries = []
        self._answers = 0
        for text in assistant_texts:
            self._append(text)
        self._refresh()

    def add_message(self, assistant_text: str) -> None:
        """Новый полностью полученный ответ LISA."""
        before = len(self._entries)
        self._append(assistant_text)
        self._refresh(select_newest=len(self._entries) > before)

    def clear(self) -> None:
        self.set_messages([])

    def blocks(self) -> list[CodeBlock]:
        """Блоки в порядке показа: сначала из новых ответов."""
        return [e.block for e in self._ordered()]

    def _append(self, text: str) -> None:
        self._answers += 1
        for block in extract_code_blocks(text):
            if block.code.strip():
                self._entries.append(_Entry(self._answers, block))

    def _ordered(self) -> list[_Entry]:
        return sorted(self._entries, key=lambda e: (-e.answer, e.block.index))

    # --- отображение ------------------------------------------------------------

    def _refresh(self, select_newest: bool = True) -> None:
        current = self.selector.currentIndex()
        self.selector.blockSignals(True)
        self.selector.clear()
        ordered = self._ordered()
        for entry in ordered:
            lines = entry.block.code.count("\n") + 1
            self.selector.addItem(
                f"Ответ {entry.answer} · блок {entry.block.index} · {entry.block.display_language} · {lines} стр."
            )
        if ordered:
            self.selector.setCurrentIndex(0 if select_newest or current < 0 else min(current, len(ordered) - 1))
        self.selector.blockSignals(False)
        has_code = bool(ordered)
        self.selector.setEnabled(has_code)
        self.copy_btn.setEnabled(has_code)
        self.info.setText(f"Блоков кода: {len(ordered)}" if has_code else "Код появится здесь, когда LISA его напишет")
        self._show_current()

    def _current_entry(self) -> _Entry | None:
        ordered = self._ordered()
        index = self.selector.currentIndex()
        return ordered[index] if 0 <= index < len(ordered) else None

    def _show_current(self, *_args) -> None:
        entry = self._current_entry()
        if entry is None:
            self.view.clear()
            self.stack.setCurrentWidget(self.empty_label)
            return
        self.highlighter.prepare(entry.block.code, entry.block.language)
        self.view.setPlainText(entry.block.code)
        self.stack.setCurrentWidget(self.view)

    def current_code(self) -> str:
        entry = self._current_entry()
        return entry.block.code if entry else ""

    def copy_current(self) -> None:
        code = self.current_code()
        if code:
            QGuiApplication.clipboard().setText(code)
