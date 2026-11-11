"""Пульт островка — главная вкладка: быстрые действия круглыми значками, как в шторке управления телефона."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGridLayout, QVBoxLayout, QWidget

from interface import styles
from interface.island.views import label
from interface.island.widgets import GLYPHS, ElidedLabel, _Hover, glyph_font, rgba
from interface.styles import TEXT_SECONDARY, WARNING, WHITE

TILE = 46            # диаметр круглой кнопки
CELL = 78            # ширина ячейки с подписью


class TileButton(_Hover):
    """Круглая кнопка пульта. Включённое состояние — сплошная заливка с тёмным значком."""

    def __init__(self, glyph: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._glyph = glyph
        self._active = False
        self.setFixedSize(TILE, TILE)

    def is_active(self) -> bool:
        return self._active

    def set_active(self, active: bool) -> None:
        if active != self._active:
            self._active = active
            self.update()

    def paintEvent(self, _event) -> None:   # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.PenStyle.NoPen)
        if self._active:
            p.setBrush(rgba(styles.CYAN, 235 if self.isDown() else 255))
        else:
            p.setBrush(rgba(WHITE, 26 + int(26 * self._glow) + (22 if self.isDown() else 0)))
        p.drawEllipse(r)
        on_colour = WHITE if styles.ISLAND_IOS else styles.BG      # на синей кнопке iPhone значок белый
        p.setPen(rgba(on_colour if self._active else WHITE, 255 if self.isEnabled() else 90))
        p.setFont(glyph_font(19))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, GLYPHS.get(self._glyph, self._glyph))
        p.end()


class ControlTile(QWidget):
    """Кнопка пульта с подписью под ней."""

    clicked = Signal()

    def __init__(self, title: str, glyph: str, hint: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(CELL)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.button = TileButton(glyph)
        self.button.setToolTip(hint or title)
        self.button.clicked.connect(self.clicked)
        lay.addWidget(self.button, 0, Qt.AlignmentFlag.AlignHCenter)
        self.caption = ElidedLabel(title)
        self.caption.setObjectName("isSub")
        self.caption.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self.caption.setStyleSheet("font-size: 10px;")
        lay.addWidget(self.caption)


class ControlView(QWidget):
    HEIGHT = 162          # для двух рядов; высота следует за числом рядов (см. _rebuild)
    ROW_HEIGHT = 70
    COLUMNS = 10          # при полной ширине капсулы; на узкой колонок меньше
    ROWS = 3
    SPACING = 4
    triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tiles: dict[str, ControlTile] = {}
        self._active: dict[str, bool] = {}
        self._actions: list = []
        self._columns = self.COLUMNS
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(4)
        self._grid = QGridLayout()
        self._grid.setHorizontalSpacing(self.SPACING)
        self._grid.setVerticalSpacing(8)
        lay.addLayout(self._grid)
        lay.addStretch(1)
        self.status = label("Свои действия добавляются в настройках: вкладка «Островок»", "isSub")
        lay.addWidget(self.status)

    def columns(self) -> int:
        return self._columns

    def set_available_width(self, width: int) -> None:
        """Ширина содержимого капсулы: от неё зависит, сколько кнопок помещается в ряд."""
        columns = max(3, min(self.COLUMNS, (int(width) + self.SPACING) // (CELL + self.SPACING)))
        if columns != self._columns:
            self._columns = columns
            self._rebuild()

    def set_actions(self, actions) -> None:
        """actions: island.actions.QuickAction. Показывается столько, сколько помещается в три ряда."""
        self._actions = list(actions)
        self._rebuild()

    def _rebuild(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for column in range(self.COLUMNS + 1):
            self._grid.setColumnStretch(column, 0)
        self.tiles = {}
        for index, action in enumerate(self._actions[:self._columns * self.ROWS]):
            tile = ControlTile(action.title, action.icon, action.hint)
            tile.clicked.connect(lambda a=action.id: self.triggered.emit(a))
            tile.button.set_active(self._active.get(action.id, False))
            self._grid.addWidget(tile, index // self._columns, index % self._columns, Qt.AlignmentFlag.AlignLeft)
            self.tiles[action.id] = tile
        self._grid.setColumnStretch(self._columns, 1)
        rows = max(1, -(-len(self.tiles) // self._columns))
        self.HEIGHT = type(self).HEIGHT + (rows - 2) * self.ROW_HEIGHT

    def set_active(self, action_id: str, active: bool) -> None:
        """Подсветка переключателя: голос включён, ресурсы освобождены, Wi-Fi подключён и т. п."""
        self._active[action_id] = bool(active)
        tile = self.tiles.get(action_id)
        if tile is not None:
            tile.button.set_active(bool(active))

    def is_active(self, action_id: str) -> bool:
        return self._active.get(action_id, False)

    def set_status(self, text: str, ok: bool = True) -> None:
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {TEXT_SECONDARY if ok else WARNING};")
