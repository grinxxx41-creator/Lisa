"""История буфера обмена: только текст, с ограничением количества и фильтром секретов.

Пароли, токены и ключи не сохраняются, пока пользователь явно не разрешит это в настройках.
Фильтр — эвристика: он может не узнать необычный секрет, поэтому историю можно отключить целиком.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

MAX_TEXT = 20_000          # более длинный текст в историю не попадает

# Форматы Windows, которыми менеджеры паролей помечают содержимое «не сохранять в истории»
PRIVATE_FORMATS = ("ExcludeClipboardContentFromMonitorProcessing", "CanIncludeInClipboardHistory",
                   "Clipboard Viewer Ignore")

_SECRET_PATTERNS = [re.compile(p) for p in (
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    r"\b(sk|pk|rk)-[A-Za-z0-9_\-]{16,}",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}",
    r"\bgithub_pat_[A-Za-z0-9_]{20,}",
    r"\bxox[abprs]-[A-Za-z0-9\-]{10,}",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bAIza[0-9A-Za-z_\-]{30,}",
    r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}",
    r"(?i)\bBearer\s+[A-Za-z0-9._\-]{16,}",
    r"(?i)\b(password|passwd|pwd|пароль|token|токен|secret|api[_-]?key)\b\s*[:=]\s*\S{4,}",
)]
_TOKEN = re.compile(r"^[A-Za-z0-9+/_=\-]+$")
_HEX = re.compile(r"^[0-9a-fA-F]+$")
_SYMBOLS = set("!@#$%^&*()_+-=[]{};:,.<>?~|")


def looks_secret(text: str) -> bool:
    """Похоже ли содержимое на пароль, токен или ключ."""
    text = text.strip()
    if not text:
        return False
    if any(p.search(text) for p in _SECRET_PATTERNS):
        return True
    if any(ch.isspace() for ch in text):
        return False
    lowered = text.lower()
    if "://" in text or lowered.startswith("www.") or "\\" in text or "/" in text:
        return False                                  # адрес или путь
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", text):
        return False                                  # e-mail
    has_lower = any(c.islower() for c in text)
    has_upper = any(c.isupper() for c in text)
    has_digit = any(c.isdigit() for c in text)
    has_symbol = any(c in _SYMBOLS for c in text)
    n = len(text)
    if n >= 32 and _HEX.match(text) and has_digit and (has_lower or has_upper):
        return True                                   # хэш или ключ в шестнадцатеричном виде
    if n >= 20 and _TOKEN.match(text) and has_digit and has_lower and has_upper:
        return True                                   # длинный случайный токен
    if 8 <= n <= 64 and has_lower and has_upper and has_digit and has_symbol:
        return True                                   # похоже на пароль
    return False


def is_private(formats: Iterable[str]) -> bool:
    """Содержимое помечено источником как не подлежащее сохранению."""
    joined = " ".join(formats)
    return any(name in joined for name in PRIVATE_FORMATS)


@dataclass
class ClipEntry:
    id: int
    text: str
    time: float

    def preview(self, limit: int = 120) -> str:
        line = " ".join(self.text.split())
        return line if len(line) <= limit else line[:limit - 1] + "…"


class ClipboardHistory:
    def __init__(self, limit: int = 30, allow_secrets: bool = False,
                 clock: Callable[[], float] = time.time) -> None:
        self.limit = limit
        self.allow_secrets = allow_secrets
        self._clock = clock
        self._items: list[ClipEntry] = []      # новые — в начале
        self._next_id = 1
        self.skipped_secrets = 0

    def add(self, text: str, formats: Iterable[str] = ()) -> ClipEntry | None:
        """Добавляет текст. None — пусто, слишком длинно или похоже на секрет."""
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            return None
        if not self.allow_secrets and (is_private(formats) or looks_secret(text)):
            self.skipped_secrets += 1
            return None
        for item in self._items:
            if item.text == text:              # повтор поднимается наверх
                self._items.remove(item)
                item.time = self._clock()
                self._items.insert(0, item)
                return item
        entry = ClipEntry(self._next_id, text, self._clock())
        self._next_id += 1
        self._items.insert(0, entry)
        del self._items[self.limit:]
        return entry

    def set_limit(self, limit: int) -> None:
        self.limit = max(1, limit)
        del self._items[self.limit:]

    def items(self, query: str = "") -> list[ClipEntry]:
        query = query.strip().casefold()
        if not query:
            return list(self._items)
        return [i for i in self._items if query in i.text.casefold()]

    def get(self, entry_id: int) -> ClipEntry | None:
        return next((i for i in self._items if i.id == entry_id), None)

    def remove(self, entry_id: int) -> bool:
        entry = self.get(entry_id)
        if entry is None:
            return False
        self._items.remove(entry)
        return True

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    # --- сохранение (только если пользователь включил) --------------------------------

    def to_json(self) -> list[dict[str, Any]]:
        return [{"text": i.text, "time": i.time} for i in self._items]

    def load(self, data: Any) -> None:
        self._items.clear()
        if not isinstance(data, list):
            return
        for raw in data[:self.limit]:
            if isinstance(raw, dict) and isinstance(raw.get("text"), str) and raw["text"].strip():
                when = raw.get("time")
                self._items.append(ClipEntry(self._next_id, raw["text"][:MAX_TEXT],
                                             float(when) if isinstance(when, (int, float)) else self._clock()))
                self._next_id += 1
