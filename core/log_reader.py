"""Чтение журнала logs/sirius.log для панели LOGS.

LogTailer читает только новые байты с последней позиции: файл не перечитывается целиком.
При первом чтении берётся только хвост файла. Усечение или замена файла обнаруживаются по размеру.
Модуль не зависит от Qt и вызывается из фонового потока.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

INITIAL_TAIL_BYTES = 200_000
MAX_READ_BYTES = 2_000_000   # за один шаг; остальное прочитается на следующих шагах

LEVELS = ("INFO", "WARNING", "ERROR")
_LEVEL_GROUP = {"DEBUG": "INFO", "INFO": "INFO", "WARNING": "WARNING", "ERROR": "ERROR", "CRITICAL": "ERROR"}

# формат из main.py: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_LINE_RE = re.compile(
    r"^(?P<time>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:,\d{3})? \[(?P<level>[A-Z]+)\] (?P<source>[^:]+): (?P<msg>.*)$"
)


@dataclass(frozen=True)
class LogEntry:
    time: str            # "ГГГГ-ММ-ДД ЧЧ:ММ:СС"; пусто у строк продолжения (traceback)
    level: str           # INFO / WARNING / ERROR (DEBUG → INFO, CRITICAL → ERROR)
    source: str
    message: str
    continuation: bool = False

    @property
    def clock(self) -> str:
        return self.time[11:19] if len(self.time) >= 19 else ""


def parse_line(line: str, previous_level: str = "INFO") -> LogEntry:
    m = _LINE_RE.match(line)
    if m is None:
        # продолжение многострочной записи наследует уровень предыдущей
        return LogEntry("", previous_level, "", line, continuation=True)
    level = _LEVEL_GROUP.get(m.group("level"), "INFO")
    return LogEntry(m.group("time"), level, m.group("source").strip(), m.group("msg"))


def filter_entries(entries: Iterable[LogEntry], levels: set[str] | frozenset[str], text: str = "") -> list[LogEntry]:
    needle = text.strip().casefold()
    result = []
    for e in entries:
        if e.level not in levels:
            continue
        if needle and needle not in e.message.casefold() and needle not in e.source.casefold():
            continue
        result.append(e)
    return result


class LogTailer:
    def __init__(self, path: Path, initial_tail_bytes: int = INITIAL_TAIL_BYTES) -> None:
        self.path = Path(path)
        self._initial_tail = initial_tail_bytes
        self._offset: int | None = None   # None — файл ещё не читался
        self._identity: tuple[int, int] | None = None
        self._partial = b""
        self._last_level = "INFO"

    @property
    def offset(self) -> int:
        return self._offset or 0

    def read_new(self) -> list[LogEntry]:
        try:
            st = os.stat(self.path)
        except OSError:
            self._offset, self._partial = None, b""
            return []
        identity = (st.st_dev, st.st_ino)
        skip_partial_line = False
        if self._offset is None:
            self._offset = max(0, st.st_size - self._initial_tail)
            skip_partial_line = self._offset > 0
        elif st.st_size < self._offset or (self._identity and identity != self._identity and st.st_ino):
            # файл усечён или заменён: читаем заново с начала
            self._offset, self._partial = 0, b""
        self._identity = identity
        if st.st_size == self._offset:
            return []
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                data = fh.read(min(st.st_size - self._offset, MAX_READ_BYTES))
        except OSError:
            return []
        self._offset += len(data)
        data = self._partial + data
        if skip_partial_line:
            cut = data.find(b"\n")
            data = data[cut + 1:] if cut >= 0 else b""
        lines = data.split(b"\n")
        self._partial = lines.pop()  # последняя строка может быть дописана не полностью
        entries = []
        for raw in lines:
            line = raw.decode("utf-8", errors="replace").rstrip("\r")
            if not line:
                continue
            entry = parse_line(line, self._last_level)
            self._last_level = entry.level
            entries.append(entry)
        return entries
