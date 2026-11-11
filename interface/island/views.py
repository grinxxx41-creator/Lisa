"""Экраны расширенных режимов островка: LISA, медиа, система, уведомления, индикаторы событий.

Экраны ничего не решают сами: они показывают переданные данные и сообщают о действиях
пользователя сигналами. HEIGHT — высота экрана в раскрытой капсуле.
"""

from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from interface.island.widgets import (BatteryIcon, Chip, Cover, ElidedLabel, Gauge, GLYPHS, IconButton, SmoothBar,
                                      Visualizer, glyph_font)
from interface.styles import CYAN, ERROR, SUCCESS, TEAL, TEXT_SECONDARY, VIOLET, WARNING, WHITE
from island.notifications import CRITICAL, Note
from island.states import IslandState

LISA_STATUS = {
    "IDLE": ("готова", CYAN), "THINKING": ("думает…", VIOLET), "SPEAKING": ("говорит", TEAL),
    "STOPPED": ("речь остановлена", TEXT_SECONDARY), "ERROR": ("ошибка", ERROR),
    "OFFLINE": ("Ollama недоступна", "#6F7D99"), "LISTENING": ("слушает…", SUCCESS),
}


def label(text: str = "", name: str = "isSub", elided: bool = False) -> QLabel:
    widget = ElidedLabel(text) if elided else QLabel(text)
    widget.setObjectName(name)
    return widget


def glyph_label(glyph: str, size: int = 14, color: str = TEXT_SECONDARY) -> QLabel:
    widget = QLabel(GLYPHS.get(glyph, glyph))
    widget.setFont(glyph_font(size))
    widget.setStyleSheet(f"color: {color};")
    widget.setFixedWidth(size + 6)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    return widget


def format_clock(seconds: float) -> str:
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


def format_rate(bps: float | None) -> str:
    if bps is None:
        return "—"
    for unit, size in (("ГБ/с", 1 << 30), ("МБ/с", 1 << 20), ("КБ/с", 1 << 10)):
        if bps >= size:
            return f"{bps / size:.1f} {unit}"
    return f"{bps:.0f} Б/с"


def format_ago(when: float, now: float | None = None) -> str:
    delta = (now if now is not None else time.time()) - when
    if delta < 60:
        return "сейчас"
    if delta < 3600:
        return f"{int(delta // 60)} мин"
    return datetime.fromtimestamp(when).strftime("%H:%M")


# --- навигация -------------------------------------------------------------------------

class NavBar(QWidget):
    HEIGHT = 30
    selected = Signal(object)          # IslandState
    pin_toggled = Signal(bool)
    close_requested = Signal()

    ITEMS = ((IslandState.EXPANDED, "LISA", "chat"), (IslandState.MEDIA, "Медиа", "music"),
             (IslandState.SYSTEM, "Система", "system"), (IslandState.NOTIFICATION, "Уведомления", "bell"),
             (IslandState.INTERACTIVE, "Инструменты", "tools"))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(self.HEIGHT)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 4)
        lay.setSpacing(6)
        self.chips: dict[IslandState, Chip] = {}
        for state, title, glyph in self.ITEMS:
            chip = Chip(title, glyph, checkable=True)
            chip.clicked.connect(lambda _checked=False, s=state: self.selected.emit(s))
            self.chips[state] = chip
            lay.addWidget(chip)
        lay.addStretch(1)
        self.pin_btn = IconButton("pin", "Закрепить: островок не свернётся сам", 26)
        self.pin_btn.setCheckable(True)
        self.pin_btn.toggled.connect(self._on_pin)
        lay.addWidget(self.pin_btn)

    def _on_pin(self, checked: bool) -> None:
        self.pin_btn.set_glyph("pinned" if checked else "pin")
        self.pin_toggled.emit(checked)

    def set_current(self, state: IslandState) -> None:
        for key, chip in self.chips.items():
            chip.setChecked(key is state)

    def set_pinned(self, pinned: bool) -> None:
        self.pin_btn.blockSignals(True)
        self.pin_btn.setChecked(pinned)
        self.pin_btn.set_glyph("pinned" if pinned else "pin")
        self.pin_btn.blockSignals(False)

    def set_available(self, states: set[IslandState]) -> None:
        for key, chip in self.chips.items():
            chip.setVisible(key in states)

    def set_unread(self, count: int) -> None:
        chip = self.chips[IslandState.NOTIFICATION]
        chip.setText(f"Уведомления · {count}" if count else "Уведомления")
        chip.updateGeometry()


# --- LISA ------------------------------------------------------------------------------

class HubView(QWidget):
    """Расширенный режим: состояние LISA, её ответ целиком и быстрые действия."""

    HEIGHT = 136
    action_triggered = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._text = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.status = label("LISA · готова", "isCaption")
        lay.addWidget(self.status)
        self.reply = QLabel("")
        self.reply.setObjectName("isReply")
        self.reply.setWordWrap(True)
        self.reply.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.reply.setTextFormat(Qt.TextFormat.PlainText)
        self.reply.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.reply.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.reply, 1)
        self._actions_host = QWidget()
        self._actions_lay = QHBoxLayout(self._actions_host)
        self._actions_lay.setContentsMargins(0, 0, 0, 0)
        self._actions_lay.setSpacing(6)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._actions_host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setFixedHeight(26)
        lay.addWidget(self._scroll)
        self.set_reply("")

    def set_lisa_state(self, state_name: str) -> None:
        text, color = LISA_STATUS.get(state_name, (state_name.lower(), CYAN))
        self.status.setText(f"LISA · {text}")
        self.status.setStyleSheet(f"color: {color};")

    def set_reply(self, text: str) -> None:
        self._text = text
        self._refresh()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        text = self._text.strip()
        if not text:
            self.reply.setText("Спросите LISA в поле выше — ответ появится здесь.")
            self.reply.setStyleSheet(f"color: {TEXT_SECONDARY};")
            return
        self.reply.setStyleSheet(f"color: {WHITE};")
        metrics = self.reply.fontMetrics()
        lines = max(1, self.reply.height() // max(1, metrics.lineSpacing()))
        per_line = max(20, int(self.reply.width() / max(1.0, metrics.averageCharWidth() * 1.08)))
        room = lines * per_line - 4
        if len(text) > room:                      # виден конец ответа — он растёт по мере генерации
            text = "…" + text[-room:].lstrip()
        self.reply.setText(text)

    def set_actions(self, actions) -> None:
        while self._actions_lay.count():
            item = self._actions_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for action in actions:
            chip = Chip(action.title, action.icon)
            chip.setToolTip(action.hint)
            chip.clicked.connect(lambda _checked=False, a=action.id: self.action_triggered.emit(a))
            self._actions_lay.addWidget(chip)
        self._actions_lay.addStretch(1)
        self._scroll.setVisible(bool(actions))

    def wheelEvent(self, event) -> None:
        bar = self._scroll.horizontalScrollBar()
        bar.setValue(bar.value() - event.angleDelta().y() // 2)


# --- медиа -----------------------------------------------------------------------------

class MediaView(QWidget):
    HEIGHT = 96
    command = Signal(str, object)      # toggle | next | prev | seek (секунды)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._info = None
        self._seek_hold_until = 0.0
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(14)
        self.cover = Cover(84, 16)
        lay.addWidget(self.cover)

        middle = QVBoxLayout()
        middle.setSpacing(2)
        self.title = label("", "isTitle", elided=True)
        self.artist = label("", "isSub", elided=True)
        middle.addStretch(1)
        middle.addWidget(self.title)
        middle.addWidget(self.artist)
        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.position = label("0:00", "isMono")
        self.bar = SmoothBar()
        self.bar.sought.connect(self._on_seek)
        self.duration = label("0:00", "isMono")
        progress.addWidget(self.position)
        progress.addWidget(self.bar, 1)
        progress.addWidget(self.duration)
        self._progress_row = QWidget()
        self._progress_row.setLayout(progress)
        progress.setContentsMargins(0, 4, 0, 0)
        middle.addWidget(self._progress_row)
        middle.addStretch(1)
        lay.addLayout(middle, 1)

        self.prev_btn = IconButton("prev", "Предыдущий трек", 32)
        self.play_btn = IconButton("play", "Воспроизведение / пауза", 42)
        self.next_btn = IconButton("next", "Следующий трек", 32)
        self.prev_btn.clicked.connect(lambda: self.command.emit("prev", None))
        self.play_btn.clicked.connect(lambda: self.command.emit("toggle", None))
        self.next_btn.clicked.connect(lambda: self.command.emit("next", None))
        for button in (self.prev_btn, self.play_btn, self.next_btn):
            lay.addWidget(button)
        self.visualizer = Visualizer(22)
        self.visualizer.setFixedSize(110, 44)
        lay.addWidget(self.visualizer)

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self.set_media(None)

    def set_media(self, info) -> None:
        self._info = info
        has = info is not None
        for widget in (self.prev_btn, self.play_btn, self.next_btn):
            widget.setVisible(has)
        self._progress_row.setVisible(has and info.duration > 0)
        if not has:
            self.cover.set_image(None)
            self.title.setText("Сейчас ничего не воспроизводится")
            self.artist.setText("Включите музыку в любом плеере Windows — она появится здесь")
            self._timer.stop()
            return
        self.cover.set_image(info.thumbnail)
        self.title.setText(info.title or "Без названия")
        self.artist.setText(" · ".join(part for part in (info.artist, info.app_name) if part))
        self.play_btn.set_glyph("pause" if info.playing else "play")
        self.play_btn.setEnabled(info.can_toggle)
        self.prev_btn.setEnabled(info.can_prev)
        self.next_btn.setEnabled(info.can_next)
        self.bar.set_interactive(info.can_seek)
        self.duration.setText(format_clock(info.duration))
        self._tick()
        self._sync_timer()

    def _sync_timer(self) -> None:
        run = self.isVisible() and self._info is not None and self._info.playing and self._info.duration > 0
        if run and not self._timer.isActive():
            self._timer.start()
        elif not run:
            self._timer.stop()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._tick()
        self._sync_timer()

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self) -> None:
        info = self._info
        if info is None or info.duration <= 0 or time.monotonic() < self._seek_hold_until:
            return
        pos = info.live_position()
        self.position.setText(format_clock(pos))
        self.bar.set_value(pos / info.duration)

    def _on_seek(self, fraction: float) -> None:
        if self._info is not None and self._info.duration > 0:
            self._seek_hold_until = time.monotonic() + 1.0    # ждём подтверждения новой позиции от плеера
            seconds = fraction * self._info.duration
            self.position.setText(format_clock(seconds))
            self.command.emit("seek", seconds)


# --- система ---------------------------------------------------------------------------

class SystemView(QWidget):
    HEIGHT = 108
    battery_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(6)
        self.gauges = {key: Gauge(title) for key, title in
                       (("cpu", "CPU"), ("gpu", "GPU"), ("ram", "RAM"), ("vram", "VRAM"))}
        for gauge in self.gauges.values():
            lay.addWidget(gauge)
        lay.addSpacing(14)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(7)
        self.lines: dict[str, ElidedLabel] = {}
        rows = (("temp", "chip", 0, 0), ("net", "link", 1, 0), ("battery", "plug", 2, 0),
                ("wifi", "wifi", 0, 2), ("bluetooth", "bluetooth", 1, 2), ("keys", "keyboard", 2, 2))
        for key, glyph, row, col in rows:
            grid.addWidget(glyph_label(glyph, 13), row, col)
            text = label("—", "isLine", elided=True)
            grid.addWidget(text, row, col + 1)
            self.lines[key] = text
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        holder = QVBoxLayout()
        holder.addStretch(1)
        holder.addLayout(grid)
        holder.addStretch(1)
        lay.addLayout(holder, 1)
        self.lines["wifi"].setText("Wi-Fi: проверка…")
        self.lines["bluetooth"].setText("Bluetooth: проверка…")
        self.lines["keys"].setText("Caps Lock — · Num Lock —")
        self.lines["temp"].setText("Температура: —")
        self.lines["net"].setText("Сеть: —")
        self.lines["battery"].setText("Питание: —")

    def set_metrics(self, values: dict) -> None:
        for key, gauge in self.gauges.items():
            gauge.set_value(values.get(key))
        cpu_t, gpu_t = values.get("cpu_temp"), values.get("gpu_temp")
        parts = [f"{name} {temp:.0f}°C" for name, temp in (("CPU", cpu_t), ("GPU", gpu_t)) if temp is not None]
        self.lines["temp"].setText("Температура: " + (" · ".join(parts) if parts else "нет данных"))
        self.lines["net"].setText(f"Сеть: ↓ {format_rate(values.get('net_down'))}  ↑ {format_rate(values.get('net_up'))}")

    def set_battery(self, text: str) -> None:
        self.lines["battery"].setText(text)

    def set_connectivity(self, wifi, bluetooth) -> None:
        if wifi is None:
            text = "Wi-Fi: нет данных"
        elif not wifi.present:
            text = "Wi-Fi: адаптера нет"
        elif not wifi.connected:
            text = "Wi-Fi: не подключён"
        else:
            name = wifi.ssid or "подключён"
            text = f"Wi-Fi: {name}" + (f" · {wifi.signal}%" if wifi.signal is not None else "")
        self.lines["wifi"].setText(text)
        if bluetooth is None:
            text = "Bluetooth: нет данных"
        elif not bluetooth.enabled:
            text = "Bluetooth: выключен"
        else:
            text = f"Bluetooth: включён · устройств: {bluetooth.connected}"
        self.lines["bluetooth"].setText(text)

    def set_locks(self, locks: dict | None) -> None:
        if locks is None:
            self.lines["keys"].setText("Caps Lock и Num Lock: нет данных")
            return
        self.lines["keys"].setText(f"Caps Lock {'вкл' if locks.get('caps') else 'выкл'} · "
                                   f"Num Lock {'вкл' if locks.get('num') else 'выкл'}")


# --- уведомления -----------------------------------------------------------------------

class NoteRow(QFrame):
    dismissed = Signal(int)
    clicked = Signal(int)

    def __init__(self, note: Note, wrap: bool, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.note_id = note.id
        self.setObjectName("isNote")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 2, 0, 2)
        lay.setSpacing(12)
        self.icon = Cover(40, 11, "warning" if note.priority >= CRITICAL else "bell")
        self.icon.set_image(note.icon)
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        column = QVBoxLayout()
        column.setSpacing(1)
        head = note.app + " · " + format_ago(note.time) + (f" · ×{note.count}" if note.count > 1 else "")
        self.head = label(head, "isSub", elided=True)
        if note.priority >= CRITICAL:
            self.head.setStyleSheet(f"color: {WARNING};")
        self.title = label(note.title or note.app, "isTitle", elided=True)
        column.addWidget(self.head)
        column.addWidget(self.title)
        if wrap:
            self.text = QLabel(note.text)
            self.text.setObjectName("isLine")
            self.text.setWordWrap(True)
            self.text.setTextFormat(Qt.TextFormat.PlainText)
        else:
            self.text = label(note.text, "isLine", elided=True)
        self.text.setVisible(bool(note.text))
        column.addWidget(self.text)
        lay.addLayout(column, 1)
        self.close_btn = IconButton("close", "Закрыть уведомление", 24)
        self.close_btn.clicked.connect(lambda: self.dismissed.emit(self.note_id))
        lay.addWidget(self.close_btn, 0, Qt.AlignmentFlag.AlignTop)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.note_id)


class NoteToast(QWidget):
    """Одно всплывшее уведомление. Щелчок открывает журнал уведомлений."""

    HEIGHT = 64
    dismissed = Signal(int)
    expand_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(8)
        self._row: NoteRow | None = None
        self.more = label("", "isSub")
        self._lay.addWidget(self.more, 0, Qt.AlignmentFlag.AlignVCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def show_note(self, note: Note, pending: int = 0) -> None:
        if self._row is not None:
            self._lay.removeWidget(self._row)
            self._row.deleteLater()
        self._row = NoteRow(note, wrap=False)
        self._row.dismissed.connect(self.dismissed)
        self._row.clicked.connect(lambda _id: self.expand_requested.emit())
        self._lay.insertWidget(0, self._row, 1)
        self.more.setText(f"ещё {pending}" if pending else "")
        self.more.setVisible(bool(pending))

    def note_id(self) -> int | None:
        return self._row.note_id if self._row is not None else None


class NoteList(QWidget):
    """Журнал уведомлений: последние сообщения с полным текстом."""

    HEIGHT = 196
    dismissed = Signal(int)
    cleared = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        head = QHBoxLayout()
        self.caption = label("Уведомления", "isCaption")
        self.clear_btn = Chip("Очистить", "delete")
        self.clear_btn.clicked.connect(self.cleared)
        head.addWidget(self.caption)
        head.addStretch(1)
        head.addWidget(self.clear_btn)
        lay.addLayout(head)
        self._host = QWidget()
        self._rows = QVBoxLayout(self._host)
        self._rows.setContentsMargins(0, 0, 6, 0)
        self._rows.setSpacing(8)
        self._scroll = QScrollArea()
        self._scroll.setWidget(self._host)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self._scroll, 1)
        self.set_notes([])

    def set_notes(self, notes: list[Note], hint: str = "") -> None:
        while self._rows.count():
            item = self._rows.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        self.caption.setText(f"Уведомления · {len(notes)}" if notes else "Уведомления")
        self.clear_btn.setVisible(bool(notes))
        if not notes:
            empty = label(hint or "Новых уведомлений нет", "isSub")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._rows.addWidget(empty)
        for note in notes[:30]:
            row = NoteRow(note, wrap=True)
            row.dismissed.connect(self.dismissed)
            self._rows.addWidget(row)
        self._rows.addStretch(1)

    def count(self) -> int:
        return sum(1 for i in range(self._rows.count()) if isinstance(self._rows.itemAt(i).widget(), NoteRow))


# --- индикаторы событий ----------------------------------------------------------------

class IndicatorView(QWidget):
    """Короткая строка события: громкость, яркость, аккумулятор, Caps Lock и Num Lock."""

    HEIGHT = 38

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 0, 4, 0)
        lay.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFont(glyph_font(18))
        self.icon.setFixedWidth(26)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.battery = BatteryIcon()
        self.title = label("", "isTitle")
        self.bar = SmoothBar()
        self.detail = label("", "isSub", elided=True)
        self.value = label("", "isValue")
        self.value.setMinimumWidth(48)
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.icon)
        lay.addWidget(self.battery)
        lay.addWidget(self.title)
        lay.addWidget(self.bar, 2)
        lay.addWidget(self.detail, 2)
        lay.addWidget(self.value)
        self.kind = ""

    def _mode(self, kind: str, glyph: str | None, color: str = WHITE, bar: bool = False, detail: bool = False) -> None:
        self.kind = kind
        self.icon.setVisible(glyph is not None)
        self.battery.setVisible(glyph is None)
        if glyph is not None:
            self.icon.setText(GLYPHS.get(glyph, glyph))
            self.icon.setStyleSheet(f"color: {color};")
        self.bar.setVisible(bar)
        self.detail.setVisible(detail)

    def show_volume(self, percent: float, muted: bool) -> None:
        animate = self.kind == "volume" and self.isVisible()
        glyph = "mute" if muted or percent < 0.5 else ("volume1" if percent < 34 else "volume2" if percent < 67 else "volume3")
        self._mode("volume", glyph, TEXT_SECONDARY if muted else WHITE, bar=True)
        self.title.setText("Без звука" if muted else "Громкость")
        self.bar.set_colors(TEXT_SECONDARY if muted else CYAN, TEXT_SECONDARY if muted else VIOLET)
        self.bar.set_value(percent / 100.0, animate)
        self.value.setText(f"{percent:.0f}%")

    def show_brightness(self, percent: float) -> None:
        animate = self.kind == "brightness" and self.isVisible()
        self._mode("brightness", "brightness", WARNING, bar=True)
        self.title.setText("Яркость")
        self.bar.set_colors(WARNING, WHITE)
        self.bar.set_value(percent / 100.0, animate)
        self.value.setText(f"{percent:.0f}%")

    def show_battery(self, percent: float | None, charging: bool, detail: str) -> None:
        self._mode("battery", None, bar=True, detail=True)
        self.battery.set_state(percent, charging)
        self.title.setText("Заряжается" if charging else "От аккумулятора")
        low = percent is not None and percent <= 20 and not charging
        self.bar.set_colors(SUCCESS if charging else ERROR if low else CYAN, SUCCESS if charging else ERROR if low else TEAL)
        self.bar.set_value((percent or 0.0) / 100.0, self.isVisible())
        self.detail.setText(detail)
        self.value.setText("—" if percent is None else f"{percent:.0f}%")

    def show_text(self, glyph: str, title: str, value: str, color: str = WHITE, detail: str = "") -> None:
        self._mode("text", glyph, color, detail=True)
        self.title.setText(title)
        self.detail.setText(detail)
        self.value.setText(value)
