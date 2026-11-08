"""Управление Ollama: проверка установки, запуск сервера, наличие и загрузка модели."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable

import requests

from core.ai_engine import CONNECT_TIMEOUT, KEEP_ALIVE, OllamaError, OllamaUnavailable

log = logging.getLogger("sirius.model")

OLLAMA_DOWNLOAD_URL = "https://ollama.com/download"
MODEL_SIZE_HINT = "около 5.2 ГБ"

ProgressCallback = Callable[[str, float | None], None]  # (статус, доля 0..1 или None)


class OllamaStatus(Enum):
    NOT_INSTALLED = "not_installed"
    NOT_RUNNING = "not_running"
    NO_MODEL = "no_model"
    READY = "ready"


@dataclass
class StatusInfo:
    status: OllamaStatus
    message: str


class ModelManager:
    def __init__(self, base_url: str, model_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    def update(self, base_url: str, model_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name

    # --- установка и запуск -------------------------------------------------

    @staticmethod
    def find_executable() -> Path | None:
        found = shutil.which("ollama")
        if found:
            return Path(found)
        local = os.environ.get("LOCALAPPDATA")
        if local:
            candidate = Path(local) / "Programs" / "Ollama" / "ollama.exe"
            if candidate.exists():
                return candidate
        return None

    def is_api_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=CONNECT_TIMEOUT)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def start_server(self, wait_seconds: float = 20.0, cancel_event: threading.Event | None = None) -> bool:
        """Пытается запустить установленный Ollama (`ollama serve`) и дождаться API.

        Если cancel_event установлен, ожидание прекращается.
        """
        exe = self.find_executable()
        if exe is None:
            return False
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
        try:
            subprocess.Popen(
                [str(exe), "serve"],
                creationflags=flags,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as exc:
            log.error("Не удалось запустить Ollama: %s", exc)
            return False
        log.info("Запущен процесс Ollama, ожидание API")
        wake = cancel_event if cancel_event is not None else threading.Event()
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if wake.is_set():
                return False
            if self.is_api_available():
                log.info("Подключение к Ollama установлено")
                return True
            wake.wait(0.5)
        return False

    # --- модель -------------------------------------------------------------

    def list_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=CONNECT_TIMEOUT)
            r.raise_for_status()
            return [m.get("name", "") for m in r.json().get("models", [])]
        except requests.RequestException as exc:
            raise OllamaUnavailable("Ollama не отвечает.") from exc
        except ValueError as exc:
            raise OllamaError("Некорректный ответ Ollama при запросе моделей.") from exc

    def loaded_models(self) -> list[tuple[str, int]]:
        """Модели, загруженные сейчас в память (/api/ps): имя и объём в видеопамяти в байтах.

        Только чтение: ничего не загружает и не выгружает.
        """
        try:
            r = requests.get(f"{self.base_url}/api/ps", timeout=CONNECT_TIMEOUT)
            r.raise_for_status()
            models = r.json().get("models", [])
        except requests.RequestException as exc:
            raise OllamaUnavailable("Ollama не отвечает.") from exc
        except (ValueError, AttributeError) as exc:
            raise OllamaError("Некорректный ответ Ollama при запросе загруженных моделей.") from exc
        result = []
        for m in models if isinstance(models, list) else []:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                vram = m.get("size_vram")
                result.append((m["name"], int(vram) if isinstance(vram, (int, float)) else 0))
        return result

    def has_model(self) -> bool:
        names = self.list_models()
        wanted = self.model_name if ":" in self.model_name else f"{self.model_name}:latest"
        return any(n == self.model_name or n == wanted for n in names)

    def pull_model(
        self,
        progress: ProgressCallback | None = None,
        cancel_event: threading.Event | None = None,
        on_response: Callable[[requests.Response], None] | None = None,
    ) -> None:
        """Загружает модель через Ollama и сообщает прогресс.

        on_response вызывается с открытым HTTP-ответом: так вызывающий код может закрыть
        поток и прервать загрузку, даже если сервер временно молчит.
        """
        log.info("Начало загрузки модели %s", self.model_name)
        try:
            with requests.post(
                f"{self.base_url}/api/pull",
                json={"model": self.model_name, "stream": True},
                stream=True,
                timeout=(CONNECT_TIMEOUT, 600),
            ) as r:
                r.raise_for_status()
                if on_response is not None:
                    on_response(r)
                for line in r.iter_lines(decode_unicode=True):
                    if cancel_event is not None and cancel_event.is_set():
                        raise OllamaError("Загрузка отменена.")
                    if not line:
                        continue
                    data = json.loads(line)
                    if "error" in data:
                        raise OllamaError(f"Ошибка загрузки модели: {data['error']}")
                    status = data.get("status", "")
                    total = data.get("total")
                    completed = data.get("completed")
                    fraction = (completed / total) if total and completed is not None else None
                    if progress:
                        progress(status, fraction)
        except requests.ConnectionError as exc:
            raise OllamaUnavailable("Ollama не отвечает.") from exc
        except requests.RequestException as exc:
            raise OllamaError("Ошибка сети во время загрузки модели.") from exc
        log.info("Загрузка модели %s завершена", self.model_name)

    # --- модель в видеопамяти ------------------------------------------------

    def preload(self, num_ctx: int, timeout: float = 180.0) -> float:
        """Загружает модель в видеопамять заранее, чтобы первый ответ пришёл сразу.

        Пустой список сообщений в /api/chat только загружает модель. num_ctx должен совпадать с
        генерацией: при другом размере контекста Ollama перезагрузит модель на первом сообщении.
        Возвращает время загрузки в секундах. Бросает OllamaError.
        """
        start = time.monotonic()
        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model_name, "messages": [], "keep_alive": KEEP_ALIVE,
                      "options": {"num_ctx": num_ctx}},
                timeout=(CONNECT_TIMEOUT, timeout),
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"Не удалось загрузить модель в память: {exc}") from exc
        elapsed = time.monotonic() - start
        log.info("Модель %s загружена в память за %.1f с", self.model_name, elapsed)
        return elapsed

    def unload(self, timeout: float = 3.0) -> bool:
        """Выгружает модель из видеопамяти (keep_alive = 0). Ошибки не бросает: вызывается при закрытии."""
        try:
            r = requests.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model_name, "messages": [], "keep_alive": 0},
                timeout=(min(CONNECT_TIMEOUT, timeout), timeout),
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            log.warning("Не удалось выгрузить модель: %s", exc)
            return False
        log.info("Модель %s выгружена из памяти", self.model_name)
        return True

    # --- состояние для интерфейса -------------------------------------------

    def check_status(self) -> StatusInfo:
        if not self.is_api_available():
            if self.find_executable() is None:
                return StatusInfo(OllamaStatus.NOT_INSTALLED, "Ollama не установлена")
            return StatusInfo(OllamaStatus.NOT_RUNNING, "Ollama не запущена")
        try:
            if not self.has_model():
                return StatusInfo(OllamaStatus.NO_MODEL, f"Модель {self.model_name} не загружена")
        except OllamaError as exc:
            return StatusInfo(OllamaStatus.NOT_RUNNING, str(exc))
        return StatusInfo(OllamaStatus.READY, f"Модель {self.model_name} готова")
