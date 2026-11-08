"""История диалогов: по одному JSON-файлу на чат (storage/chats пути задаёт вызывающий код)."""

from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from storage.storage_manager import atomic_write_json, read_json_safe

log = logging.getLogger("sirius.chats")

_CHAT_FILE_RE = re.compile(r"^chat_(\d{3,})\.json$")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ChatStorage:
    def __init__(self, chats_dir: Path) -> None:
        self.chats_dir = Path(chats_dir)
        self.chats_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, file_id: str) -> Path:
        return self.chats_dir / f"{file_id}.json"

    def _next_file_id(self) -> str:
        numbers = [0]
        for p in self.chats_dir.glob("chat_*.json"):
            m = _CHAT_FILE_RE.match(p.name)
            if m:
                numbers.append(int(m.group(1)))
        return f"chat_{max(numbers) + 1:03d}"

    def list_chats(self) -> list[dict[str, Any]]:
        """Список чатов (id, title, updated_at). Повреждённые файлы пропускаются."""
        result = []
        for p in sorted(self.chats_dir.glob("chat_*.json")):
            data = read_json_safe(p)
            if not _is_valid_chat(data):
                log.warning("Пропущен повреждённый файл чата: %s", p.name)
                continue
            result.append({
                "file_id": p.stem,
                "id": data["id"],
                "title": data["title"],
                "updated_at": data["updated_at"],
            })
        result.sort(key=lambda c: c["updated_at"], reverse=True)
        return result

    def delete_empty_chats(self, keep: str | None = None) -> int:
        """Удаляет чаты без сообщений, кроме чата keep. Возвращает число удалённых."""
        removed = 0
        for p in self.chats_dir.glob("chat_*.json"):
            if p.stem == keep:
                continue
            data = read_json_safe(p)
            if _is_valid_chat(data) and not data["messages"]:
                try:
                    p.unlink()
                    removed += 1
                except OSError as exc:
                    log.warning("Не удалось удалить пустой чат %s: %s", p.name, exc)
        if removed:
            log.info("Удалено пустых чатов: %d", removed)
        return removed

    def create_chat(self, title: str = "Новый диалог") -> dict[str, Any]:
        now = _now()
        chat = {
            "id": uuid.uuid4().hex,
            "title": title,
            "created_at": now,
            "updated_at": now,
            "messages": [],
        }
        file_id = self._next_file_id()
        atomic_write_json(self._path_for(file_id), chat)
        chat["file_id"] = file_id
        log.info("Создан чат %s", file_id)
        return chat

    def load_chat(self, file_id: str) -> dict[str, Any] | None:
        data = read_json_safe(self._path_for(file_id))
        if not _is_valid_chat(data):
            log.error("Чат %s повреждён или не найден", file_id)
            return None
        data["file_id"] = file_id
        return data

    def add_message(self, file_id: str, role: str, text: str) -> dict[str, Any] | None:
        chat = self.load_chat(file_id)
        if chat is None:
            return None
        chat["messages"].append({"role": role, "text": text, "timestamp": _now()})
        chat["updated_at"] = _now()
        self._write(file_id, chat)
        return chat

    def rename_chat(self, file_id: str, title: str) -> bool:
        chat = self.load_chat(file_id)
        if chat is None:
            return False
        chat["title"] = title.strip() or "Без названия"
        chat["updated_at"] = _now()
        self._write(file_id, chat)
        return True

    def delete_chat(self, file_id: str) -> bool:
        path = self._path_for(file_id)
        if not path.exists():
            return False
        path.unlink()
        log.info("Удалён чат %s", file_id)
        return True

    def _write(self, file_id: str, chat: dict[str, Any]) -> None:
        payload = {k: v for k, v in chat.items() if k != "file_id"}
        atomic_write_json(self._path_for(file_id), payload)


def _is_valid_chat(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("id"), str)
        and isinstance(data.get("title"), str)
        and isinstance(data.get("updated_at"), str)
        and isinstance(data.get("messages"), list)
    )
