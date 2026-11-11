"""Состояния островка и приоритеты временных (всплывающих) состояний."""

from __future__ import annotations

from enum import Enum


class IslandState(Enum):
    COMPACT = "compact"            # обычная капсула
    EXPANDED = "expanded"          # LISA: ответ целиком и быстрые действия
    MEDIA = "media"                # управление музыкой
    NOTIFICATION = "notification"  # уведомления
    SYSTEM = "system"              # системные индикаторы
    VOLUME = "volume"              # изменение громкости
    BRIGHTNESS = "brightness"      # изменение яркости
    BATTERY = "battery"            # аккумулятор и питание
    INTERACTIVE = "interactive"    # инструменты: полка, буфер, Pomodoro, действия


# Состояния, которые пользователь открывает сам (остаются до закрытия или тайм-аута бездействия)
USER_STATES = (IslandState.EXPANDED, IslandState.MEDIA, IslandState.SYSTEM,
               IslandState.NOTIFICATION, IslandState.INTERACTIVE)

# Временные состояния: событие с большим приоритетом вытесняет меньшее, обратное — нет
TRANSIENT_PRIORITY = {
    IslandState.MEDIA: 30,         # смена трека
    IslandState.SYSTEM: 40,        # Caps Lock, Num Lock
    IslandState.VOLUME: 50,
    IslandState.BRIGHTNESS: 50,
    IslandState.BATTERY: 60,
    IslandState.NOTIFICATION: 70,
}
CRITICAL_PRIORITY = 90             # важное уведомление
