"""Данные островка между запусками: файловая полка, состояние Pomodoro и (если включено)
история буфера обмена. Хранятся в storage/island.json отдельно от настроек."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from storage.storage_manager import atomic_write_json, read_json_safe

log = logging.getLogger("sirius.island")

KEYS = ("shelf", "pomodoro", "clipboard")


class IslandStorage:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        data = read_json_safe(self.path)
        if not isinstance(data, dict):
            return {}
        return {k: data[k] for k in KEYS if k in data}

    def save(self, data: dict[str, Any]) -> bool:
        try:
            atomic_write_json(self.path, {k: data[k] for k in KEYS if k in data})
        except OSError as exc:
            log.error("Не удалось сохранить данные островка: %s", exc)
            return False
        return True
