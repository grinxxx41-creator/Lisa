"""Расположение панелей рабочего пространства: стандартная компоновка, исправление координат, сохранение.

Модуль не зависит от Qt: прямоугольники — простые значения, поэтому логику легко проверять тестами.

Каждая панель хранит «желаемый» прямоугольник и размер рабочей области, в которой он задан.
Фактическое положение вычисляется так:
1. прямоугольник переносится в текущую область с привязкой к ближайшим краям (anchor_rect):
   панель справа остаётся справа, панель внизу остаётся внизу;
2. затем он вписывается в область (clamp_rect): панель не может уйти за её пределы.
Поэтому временное уменьшение окна не портит размеры панелей.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

PANEL_IDS = ("chat", "code", "system", "terminal", "logs", "history")
DEFAULT_VISIBLE = ("chat", "system")
DEFAULT_PRESET = "default"
STATE_VERSION = 1

MARGIN = 14              # отступ панелей от краёв рабочей области
COLLAPSED_HEIGHT = 40    # высота свёрнутой панели (только заголовок)
MAX_COORD = 100_000      # защита от нелепых значений в settings.json


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @property
    def right(self) -> int:
        return self.x + self.w

    @property
    def bottom(self) -> int:
        return self.y + self.h

    def intersects(self, other: "Rect") -> bool:
        return self.x < other.right and other.x < self.right and self.y < other.bottom and other.y < self.bottom

    def to_list(self) -> list[int]:
        return [self.x, self.y, self.w, self.h]

    @staticmethod
    def from_value(value: Any) -> "Rect | None":
        """Прямоугольник из JSON-списка [x, y, w, h]. Неверные данные дают None."""
        if not isinstance(value, (list, tuple)) or len(value) != 4:
            return None
        numbers = []
        for item in value:
            if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(item):
                return None
            if abs(item) > MAX_COORD:
                return None
            numbers.append(int(item))
        x, y, w, h = numbers
        if w <= 0 or h <= 0:
            return None
        return Rect(x, y, w, h)


def _bound(value: int, lo: int, hi: int) -> int:
    return max(lo, min(value, hi))


def clamp_rect(rect: Rect, area_w: int, area_h: int, min_w: int, min_h: int) -> Rect:
    """Вписывает прямоугольник в рабочую область, соблюдая минимальный размер.

    Если область меньше минимального размера, панель получает минимальный размер и прижимается
    к левому верхнему углу: заголовок остаётся доступен.
    """
    min_w, min_h = max(1, min_w), max(1, min_h)
    w = max(min_w, min(rect.w, max(area_w, min_w)))
    h = max(min_h, min(rect.h, max(area_h, min_h)))
    x = _bound(rect.x, 0, max(area_w - w, 0))
    y = _bound(rect.y, 0, max(area_h - h, 0))
    return Rect(x, y, w, h)


def anchor_rect(rect: Rect, from_w: int, from_h: int, to_w: int, to_h: int) -> Rect:
    """Переносит прямоугольник в область другого размера, сохраняя отступ до ближайших краёв."""
    if from_w <= 0 or from_h <= 0:
        return rect
    x, y = rect.x, rect.y
    if rect.x + rect.w / 2 > from_w / 2:
        x = to_w - (from_w - rect.right) - rect.w
    if rect.y + rect.h / 2 > from_h / 2:
        y = to_h - (from_h - rect.bottom) - rect.h
    return Rect(x, y, rect.w, rect.h)


def chat_width(area_w: int) -> int:
    return _bound(int(area_w * 0.30), 360, 560)


def side_width(area_w: int) -> int:
    return _bound(int(area_w * 0.24), 340, 420)


def avatar_rect(area_w: int, area_h: int) -> Rect:
    """Место аватара: центр рабочей области, свободный от стандартной колонки чата."""
    h = max(1, int(area_h * 0.95))
    free = area_w - 2 * (chat_width(area_w) + 2 * MARGIN)
    w = max(1, int(min(area_w * 0.30, h * 0.85, max(free, 220))))
    return Rect((area_w - w) // 2, area_h - h - int(area_h * 0.01), w, h)


def default_layout(area_w: int, area_h: int) -> dict[str, Rect]:
    """Стандартная компоновка: LISA в центре, CHAT справа, SYSTEM сверху слева,
    CODE и HISTORY слева, TERMINAL и LOGS внизу по центру."""
    m = MARGIN
    area_w, area_h = max(area_w, 1), max(area_h, 1)
    cw = chat_width(area_w)
    sw = side_width(area_w)
    chat = Rect(area_w - cw - m, m, cw, area_h - 2 * m)

    system_h = min(310, max(236, int(area_h * 0.42)))   # v0.3: вкладки с графиками
    system = Rect(m, m, sw, system_h)
    lower_y = m + system_h + m
    lower = Rect(m, lower_y, sw, area_h - lower_y - m)

    center_x = m + sw + m
    center_w = max(chat.x - m - center_x, 1)
    bottom_h = max(int(area_h * 0.38), 220)
    bottom = Rect(center_x, area_h - bottom_h - m, center_w, bottom_h)

    return {
        "chat": chat,
        "system": system,
        "code": lower,
        "history": lower,
        "terminal": bottom,
        "logs": bottom,
    }


# --- сохранение -------------------------------------------------------------


@dataclass
class PanelState:
    rect: Rect | None = None              # None — стандартное место
    canvas: tuple[int, int] | None = None  # размер области, в которой задан rect
    visible: bool = False
    collapsed: bool = False


@dataclass
class WorkspaceState:
    panels: dict[str, PanelState] = field(default_factory=dict)
    z_order: list[str] = field(default_factory=list)  # снизу вверх
    active: str | None = None
    preset: str = DEFAULT_PRESET

    def to_dict(self) -> dict[str, Any]:
        panels = {}
        for panel_id, st in self.panels.items():
            item: dict[str, Any] = {"visible": st.visible, "collapsed": st.collapsed}
            if st.rect is not None and st.canvas is not None:
                item["rect"] = st.rect.to_list()
                item["canvas"] = list(st.canvas)
            panels[panel_id] = item
        return {
            "version": STATE_VERSION,
            "preset": self.preset,
            "active": self.active,
            "z_order": list(self.z_order),
            "panels": panels,
        }


def _parse_size(value: Any) -> tuple[int, int] | None:
    rect = Rect.from_value([0, 0, *value]) if isinstance(value, (list, tuple)) and len(value) == 2 else None
    return (rect.w, rect.h) if rect else None


def parse_state(raw: Any, known_ids: tuple[str, ...] | list[str] = PANEL_IDS) -> WorkspaceState | None:
    """Разбирает сохранённое состояние. Неизвестные панели и неверные значения отбрасываются.

    Возвращает None, если сохранённого состояния нет или оно непригодно (будет стандартная компоновка).
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("panels"), dict):
        return None
    state = WorkspaceState()
    for panel_id, item in raw["panels"].items():
        if panel_id not in known_ids or not isinstance(item, dict):
            continue
        rect = Rect.from_value(item.get("rect"))
        canvas = _parse_size(item.get("canvas"))
        if rect is None or canvas is None:
            rect, canvas = None, None
        state.panels[panel_id] = PanelState(
            rect=rect,
            canvas=canvas,
            visible=item.get("visible") is True,
            collapsed=item.get("collapsed") is True,
        )
    if not state.panels:
        return None
    z_order = raw.get("z_order")
    if isinstance(z_order, list):
        seen: set[str] = set()
        for panel_id in z_order:
            if isinstance(panel_id, str) and panel_id in known_ids and panel_id not in seen:
                seen.add(panel_id)
                state.z_order.append(panel_id)
    active = raw.get("active")
    state.active = active if isinstance(active, str) and active in known_ids else None
    preset = raw.get("preset")
    state.preset = preset if isinstance(preset, str) and preset else DEFAULT_PRESET
    return state
