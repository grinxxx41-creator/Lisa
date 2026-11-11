"""Файловая полка островка: список путей. Сами файлы не трогаются — полка хранит только ссылки,
удаление с полки не удаляет файл с диска, перетаскивание из полки всегда копирует."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class ShelfItem:
    path: str

    @property
    def name(self) -> str:
        return Path(self.path).name or self.path

    @property
    def exists(self) -> bool:
        return os.path.exists(self.path)

    @property
    def is_dir(self) -> bool:
        return os.path.isdir(self.path)


def _norm(path: str) -> str:
    return os.path.normcase(os.path.abspath(path))


class QuickShelf:
    def __init__(self, limit: int = 12) -> None:
        self.limit = limit
        self._items: list[ShelfItem] = []

    def add(self, paths: Iterable[str]) -> int:
        """Добавляет существующие файлы и папки. Возвращает, сколько добавлено."""
        added = 0
        known = {_norm(i.path) for i in self._items}
        for raw in paths:
            if len(self._items) >= self.limit:
                break
            if not isinstance(raw, str) or not raw.strip():
                continue
            path = os.path.abspath(raw)
            if not os.path.exists(path) or _norm(path) in known:
                continue
            self._items.append(ShelfItem(path))
            known.add(_norm(path))
            added += 1
        return added

    def remove(self, path: str) -> bool:
        """Убирает ссылку с полки. Файл на диске остаётся."""
        for item in self._items:
            if _norm(item.path) == _norm(path):
                self._items.remove(item)
                return True
        return False

    def clear(self) -> None:
        self._items.clear()

    def set_limit(self, limit: int) -> None:
        self.limit = max(1, limit)
        del self._items[self.limit:]

    def items(self) -> list[ShelfItem]:
        return list(self._items)

    def is_full(self) -> bool:
        return len(self._items) >= self.limit

    def __len__(self) -> int:
        return len(self._items)

    def to_json(self) -> list[str]:
        return [i.path for i in self._items]

    def load(self, data: Any) -> None:
        """Восстанавливает полку. Пропавшие файлы остаются в списке с пометкой — пользователь уберёт их сам."""
        self._items.clear()
        if not isinstance(data, list):
            return
        known: set[str] = set()
        for raw in data:
            if isinstance(raw, str) and raw.strip() and os.path.isabs(raw) and _norm(raw) not in known:
                self._items.append(ShelfItem(raw))
                known.add(_norm(raw))
            if len(self._items) >= self.limit:
                break
