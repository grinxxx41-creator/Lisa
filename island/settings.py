"""Настройки островка: значения по умолчанию и проверка сохранённых значений.

Хранятся в settings.json["island"]. normalize() принимает что угодно и всегда возвращает полный
корректный словарь, поэтому старые настройки без раздела "island" продолжают работать.
"""

from __future__ import annotations

import copy
from typing import Any

POSITIONS = ("top", "top-left", "top-right")      # островок закреплён у верхнего края
THEMES = ("graphite", "black", "sirius")
VISUALIZERS = ("bars", "wave", "pulse")

ISLAND_DEFAULTS: dict[str, Any] = {
    "enabled": True,             # живой островок; False — прежняя полоска без событий и расширенных режимов
    "show_always": False,        # показывать и при открытом главном окне (иначе только в компактном режиме)
    "position": "top",
    "mini": True,                # свёрнутый островок — маленькая капсула: время, градусы или эквалайзер
    "custom_pos": None,          # [x центра, y края] после перетаскивания
    "screen": "",                # имя экрана; пусто — экран главного окна
    "width": 860,
    "height": 46,
    "opacity": 94,               # непрозрачность фона капсулы, %
    "theme": "graphite",
    "animations": True,
    "animation_speed": 100,      # %, больше — быстрее
    "auto_collapse_s": 8,        # расширенный режим сворачивается без действий пользователя
    "lisa_expand": True,         # раскрывать ответ LISA при вопросе из островка
    "media": True,
    "media_popup": True,         # показывать новую композицию
    "visualizer": True,
    "visualizer_style": "bars",
    "indicators": True,          # громкость и яркость
    "lock_keys": True,           # Caps Lock и Num Lock
    "battery_events": True,      # подключение и отключение питания
    "notifications": True,       # уведомления SIRIUS
    "notifications_windows": False,   # уведомления Windows (нужен доступ к уведомлениям)
    "notification_seconds": 6,
    "shelf": True,
    "shelf_limit": 12,
    "clipboard": True,
    "clipboard_limit": 30,
    "clipboard_persist": False,  # сохранять историю буфера между запусками
    "clipboard_allow_secrets": False,
    "pomodoro": True,
    "pomodoro_work": 25,
    "pomodoro_short": 5,
    "pomodoro_long": 15,
    "pomodoro_rounds": 4,
    "pomodoro_restore": True,    # восстанавливать таймер после перезапуска
    "actions": True,
    "weather": True,             # вкладка погоды и градусы в мини-капсуле (нужен город)
    "weather_city": "",          # пусто — запросов в интернет нет
    "custom_actions": [],        # [{"title": ..., "target": путь или http(s)-адрес}]
}

RANGES = {
    "width": (640, 1400), "height": (40, 64), "opacity": (40, 100), "animation_speed": (50, 200),
    "auto_collapse_s": (3, 60), "notification_seconds": (2, 30), "shelf_limit": (1, 30),
    "clipboard_limit": (5, 200), "pomodoro_work": (1, 180), "pomodoro_short": (1, 60),
    "pomodoro_long": (1, 120), "pomodoro_rounds": (1, 12),
}
_CHOICES = {"position": POSITIONS, "theme": THEMES, "visualizer_style": VISUALIZERS}
MAX_CUSTOM_ACTIONS = 12


def normalize(raw: Any) -> dict[str, Any]:
    """Полный словарь настроек островка: неизвестные ключи отброшены, значения проверены."""
    result = copy.deepcopy(ISLAND_DEFAULTS)
    if not isinstance(raw, dict):
        return result
    for key, default in ISLAND_DEFAULTS.items():
        if key not in raw:
            continue
        value = raw[key]
        if key in RANGES:
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lo, hi = RANGES[key]
                result[key] = int(min(hi, max(lo, value)))
        elif key in _CHOICES:
            if value in _CHOICES[key]:
                result[key] = value
        elif isinstance(default, bool):
            if isinstance(value, bool):
                result[key] = value
        elif key == "custom_pos":
            if (isinstance(value, (list, tuple)) and len(value) == 2
                    and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in value)):
                result[key] = [int(value[0]), int(value[1])]
        elif key == "custom_actions":
            result[key] = _clean_actions(value)
        elif isinstance(default, str):
            if isinstance(value, str):
                result[key] = value[:200]
    if result["position"] == "custom" and result["custom_pos"] is None:
        result["position"] = "top"
    return result


def _clean_actions(value: Any) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not isinstance(value, list):
        return items
    for item in value:
        if not isinstance(item, dict):
            continue
        title, target = item.get("title"), item.get("target")
        if isinstance(title, str) and isinstance(target, str) and title.strip() and target.strip():
            items.append({"title": title.strip()[:60], "target": target.strip()[:1000]})
        if len(items) >= MAX_CUSTOM_ACTIONS:
            break
    return items
