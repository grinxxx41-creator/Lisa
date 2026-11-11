"""Точечная (Dot Matrix) типографика: знаки 5×7 рисуются кругами, шрифт-файл не нужен.

Только для коротких декоративных надписей: логотип, таймер, крупные числа. Знаки — латиница,
цифры и несколько символов; неизвестный знак (например, кириллица) рисуется пустой клеткой.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QSizePolicy, QWidget

COLS, ROWS = 5, 7

_GLYPHS = {
    "A": "01110 10001 10001 11111 10001 10001 10001", "B": "11110 10001 10001 11110 10001 10001 11110",
    "C": "01110 10001 10000 10000 10000 10001 01110", "D": "11110 10001 10001 10001 10001 10001 11110",
    "E": "11111 10000 10000 11110 10000 10000 11111", "F": "11111 10000 10000 11110 10000 10000 10000",
    "G": "01110 10001 10000 10111 10001 10001 01111", "H": "10001 10001 10001 11111 10001 10001 10001",
    "I": "01110 00100 00100 00100 00100 00100 01110", "J": "00111 00010 00010 00010 00010 10010 01100",
    "K": "10001 10010 10100 11000 10100 10010 10001", "L": "10000 10000 10000 10000 10000 10000 11111",
    "M": "10001 11011 10101 10101 10001 10001 10001", "N": "10001 11001 10101 10011 10001 10001 10001",
    "O": "01110 10001 10001 10001 10001 10001 01110", "P": "11110 10001 10001 11110 10000 10000 10000",
    "Q": "01110 10001 10001 10001 10101 10010 01101", "R": "11110 10001 10001 11110 10100 10010 10001",
    "S": "01111 10000 10000 01110 00001 00001 11110", "T": "11111 00100 00100 00100 00100 00100 00100",
    "U": "10001 10001 10001 10001 10001 10001 01110", "V": "10001 10001 10001 10001 10001 01010 00100",
    "W": "10001 10001 10001 10101 10101 11011 10001", "X": "10001 10001 01010 00100 01010 10001 10001",
    "Y": "10001 10001 01010 00100 00100 00100 00100", "Z": "11111 00001 00010 00100 01000 10000 11111",
    "0": "01110 10001 10011 10101 11001 10001 01110", "1": "00100 01100 00100 00100 00100 00100 01110",
    "2": "01110 10001 00001 00010 00100 01000 11111", "3": "11110 00001 00001 01110 00001 00001 11110",
    "4": "00010 00110 01010 10010 11111 00010 00010", "5": "11111 10000 11110 00001 00001 10001 01110",
    "6": "00110 01000 10000 11110 10001 10001 01110", "7": "11111 00001 00010 00100 01000 01000 01000",
    "8": "01110 10001 10001 01110 10001 10001 01110", "9": "01110 10001 10001 01111 00001 00010 01100",
    ":": "00000 00100 00100 00000 00100 00100 00000", ".": "00000 00000 00000 00000 00000 00000 00100",
    "-": "00000 00000 00000 01110 00000 00000 00000", "%": "11001 11010 00010 00100 01000 01011 10011",
    "/": "00001 00010 00010 00100 01000 01000 10000", "+": "00000 00100 00100 11111 00100 00100 00000",
}
_NARROW = {":": 3, ".": 3, " ": 3}     # ширина узких знаков в клетках


def glyph(char: str) -> list[str]:
    """Семь строк по пять знаков «0»/«1» для символа; пустая клетка, если символа нет."""
    return _GLYPHS.get(char.upper(), "00000 " * ROWS).split()


def _cells(text: str) -> list[tuple[str, int, int]]:
    """(знак, первая колонка, ширина) для каждого знака строки."""
    out, col = [], 0
    for ch in text:
        width = _NARROW.get(ch, COLS)
        out.append((ch, col, width))
        col += width + 1
    return out


def text_columns(text: str) -> int:
    cells = _cells(text)
    return cells[-1][1] + cells[-1][2] if cells else 0


def text_size(text: str, dot: float, gap: float) -> tuple[float, float]:
    cols = text_columns(text)
    return (max(0.0, cols * (dot + gap) - gap), ROWS * (dot + gap) - gap)


def paint_text(p: QPainter, text: str, x: float, y: float, dot: float, gap: float, color: QColor,
               ghost: QColor | None = None) -> None:
    """Рисует строку точками от левого верхнего угла (x, y). ghost — цвет «негорящих» точек."""
    p.setPen(Qt.PenStyle.NoPen)
    pitch, r = dot + gap, dot / 2
    for ch, first, width in _cells(text):
        rows = glyph(ch)
        shift = (COLS - width) // 2          # узкие знаки берут середину клетки 5×7
        for row in range(ROWS):
            for col in range(width):
                lit = rows[row][col + shift] == "1"
                if not lit and ghost is None:
                    continue
                p.setBrush(color if lit else ghost)
                p.drawEllipse(QPointF(x + (first + col) * pitch + r, y + row * pitch + r), r, r)


class DotLabel(QWidget):
    """Надпись точечным шрифтом. Интерфейс как у QLabel: setText(), text()."""

    def __init__(self, text: str = "", dot: float = 3.0, gap: float = 1.4, color: str = "#FFFFFF",
                 ghost_alpha: int = 0, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text, self._dot, self._gap = text, dot, gap
        self._color = QColor(color)
        self._ghost_alpha = ghost_alpha
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def text(self) -> str:
        return self._text

    def setText(self, text: str) -> None:   # noqa: N802 — как у QLabel
        if text == self._text:
            return
        resized = text_columns(text) != text_columns(self._text)
        self._text = text
        if resized:
            self.updateGeometry()
        self.update()

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:   # noqa: N802
        w, h = text_size(self._text, self._dot, self._gap)
        return QSize(int(w + 1), int(h + 1))

    def minimumSizeHint(self) -> QSize:   # noqa: N802
        return self.sizeHint()

    def paintEvent(self, _event) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = text_size(self._text, self._dot, self._gap)
        ghost = None
        if self._ghost_alpha > 0:
            ghost = QColor(self._color)
            ghost.setAlpha(self._ghost_alpha)
        paint_text(p, self._text, 0.0, (self.height() - h) / 2, self._dot, self._gap, self._color, ghost)
        p.end()
