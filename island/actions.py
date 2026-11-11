"""Быстрые действия островка: встроенные (их выполняет главное окно) и пользовательские —
открыть выбранное приложение, файл, папку или http(s)-адрес. Командная строка не используется:
цель открывается средствами Windows так же, как двойным щелчком в проводнике."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("sirius.island")


@dataclass(frozen=True)
class QuickAction:
    id: str
    title: str
    hint: str = ""
    target: str = ""        # только у пользовательских действий
    icon: str = "bolt"

    @property
    def custom(self) -> bool:
        return bool(self.target)


BUILTIN_ACTIONS = (
    QuickAction("open_sirius", "SIRIUS", "Открыть главное окно", icon="window"),
    QuickAction("new_chat", "Новый диалог", "Начать новый диалог с LISA", icon="chat"),
    QuickAction("voice", "Голос", "Включить или выключить голос LISA", icon="volume"),
    QuickAction("heavy", "Ресурсы", "Освободить или вернуть модель и голос", icon="chip"),
    QuickAction("settings", "Настройки", "Открыть настройки SIRIUS", icon="settings"),
    QuickAction("explorer", "Проводник", "Открыть проводник Windows", icon="folder"),
    QuickAction("wifi", "Wi-Fi", "Открыть параметры Wi-Fi в Windows", icon="wifi"),
    QuickAction("bluetooth", "Bluetooth", "Открыть параметры Bluetooth в Windows", icon="bluetooth"),
)
# действия, которые открывают страницу «Параметров» Windows
SETTINGS_PAGES = {"wifi": "ms-settings:network-wifi", "bluetooth": "ms-settings:bluetooth"}


def custom_actions(raw: Any) -> list[QuickAction]:
    result: list[QuickAction] = []
    if not isinstance(raw, list):
        return result
    for index, item in enumerate(raw):
        if isinstance(item, dict) and item.get("title") and item.get("target"):
            target = str(item["target"])
            icon = "link" if is_url(target) else "folder" if os.path.isdir(target) else "app"
            result.append(QuickAction(f"custom:{index}", str(item["title"]), target, target, icon))
    return result


def is_url(target: str) -> bool:
    return target.lower().startswith(("http://", "https://"))


def validate_target(target: str) -> str | None:
    """None — цель можно открыть; иначе причина отказа."""
    target = target.strip()
    if not target:
        return "Цель не указана"
    if is_url(target):
        return None
    if "://" in target:
        return "Поддерживаются только адреса http и https"
    if not os.path.isabs(target):
        return "Нужен полный путь к файлу, папке или приложению"
    if not os.path.exists(target):
        return f"Не найдено: {target}"
    return None


def launch_target(target: str) -> tuple[bool, str]:
    """Открывает файл, папку, приложение или сайт. Возвращает (успех, сообщение)."""
    problem = validate_target(target)
    if problem:
        return False, problem
    try:
        os.startfile(target.strip())  # noqa: S606 — цель задал сам пользователь в настройках
    except OSError as exc:
        log.warning("Не удалось открыть %s: %s", target, exc)
        return False, f"Не удалось открыть: {exc.strerror or exc}"
    return True, f"Открыто: {Path(target).name or target}"


def open_settings_page(action_id: str) -> tuple[bool, str]:
    """Открывает страницу «Параметров» Windows из SETTINGS_PAGES."""
    uri = SETTINGS_PAGES.get(action_id)
    if uri is None or not hasattr(os, "startfile"):
        return False, "Параметры Windows недоступны"
    try:
        os.startfile(uri)   # noqa: S606 — адрес из постоянного списка выше
    except OSError as exc:
        return False, f"Не удалось открыть параметры Windows: {exc}"
    return True, "Открыты параметры Windows"


def open_explorer() -> tuple[bool, str]:
    return launch_target(str(Path.home()))
