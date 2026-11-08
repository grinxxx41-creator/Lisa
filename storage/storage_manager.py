"""Безопасная работа с JSON-файлами: атомарная запись и устойчивое чтение."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

log = logging.getLogger("sirius.storage")


def atomic_write_json(path: Path, data: Any) -> None:
    """Записывает JSON через временный файл и заменяет целевой файл."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.remove(tmp_name)
        except OSError:
            pass
        raise


def read_json_safe(path: Path) -> Any | None:
    """Читает JSON. Возвращает None, если файл отсутствует или повреждён."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        log.error("Не удалось прочитать %s: %s", path.name, exc)
        return None
