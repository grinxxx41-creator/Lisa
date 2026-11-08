"""Взаимодействие с языковой моделью через локальный HTTP API Ollama.

Модуль не зависит от GUI. Потоковая генерация выполняется синхронным генератором,
который вызывающий код запускает в фоновом потоке.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Callable, Iterator

import requests

# Сколько модель остаётся в видеопамяти после последнего запроса. Пока SIRIUS открыт, каждый запрос
# продлевает срок; при закрытии модель выгружается сразу (ModelManager.unload). Если приложение
# завершилось аварийно, Ollama сама освободит память через этот срок.
KEEP_ALIVE = "30m"

log = logging.getLogger("sirius.ai")

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 180  # первая загрузка модели в видеопамять может занимать время


class OllamaError(Exception):
    """Базовая ошибка работы с Ollama."""


class OllamaUnavailable(OllamaError):
    """Ollama не запущена или API недоступен."""


class AIEngine:
    def __init__(self, base_url: str, model_name: str, num_ctx: int = 4096) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.num_ctx = num_ctx
        # v0.3: итоговый фрагмент Ollama (счётчики токенов и длительности) — отдельно для каждого потока,
        # потому что ответ и название диалога могут генерироваться одновременно
        self._done_local = threading.local()

    def take_done_stats(self) -> dict | None:
        """Итоговый фрагмент последнего ответа, полученного в этом потоке (eval_count, eval_duration…)."""
        chunk = getattr(self._done_local, "chunk", None)
        self._done_local.chunk = None
        return chunk

    def stream_reply(
        self,
        messages: list[dict],
        cancel_event: threading.Event | None = None,
        max_tokens: int | None = None,
        on_response: Callable[[requests.Response], None] | None = None,
    ) -> Iterator[str]:
        """Отдаёт фрагменты ответа по мере генерации.

        cancel_event: при установке генерация прерывается; HTTP-поток закрывается, и генератор
            завершается без исключения. Проверить, была ли остановка, можно по cancel_event.is_set().
        on_response: вызывается сразу после получения ответа сервера. Вызывающий код может
            закрыть поток из другого потока, чтобы остановить генерацию немедленно.
        """
        options: dict = {"num_ctx": self.num_ctx, "temperature": 0.4}
        if max_tokens is not None:
            options["num_predict"] = max_tokens
        payload = {
            "model": self.model_name,
            "messages": messages,
            "stream": True,
            "keep_alive": KEEP_ALIVE,
            "think": False,  # режим размышлений выключен: быстрее и экономнее по памяти
            "options": options,
        }
        log.info("Начало генерации (модель %s)", self.model_name)
        response = None
        try:
            try:
                response = requests.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                    stream=True,
                    timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
                )
            except requests.ConnectionError as exc:
                raise OllamaUnavailable("Ollama не отвечает. Проверьте, что она запущена.") from exc
            except requests.Timeout as exc:
                raise OllamaUnavailable("Превышено время ожидания ответа Ollama.") from exc

            if response.status_code == 404:
                raise OllamaError(f"Модель «{self.model_name}» не найдена. Загрузите её в настройках.")
            if response.status_code != 200:
                raise OllamaError(f"Ошибка Ollama (HTTP {response.status_code}).")
            if on_response is not None:
                on_response(response)
            if cancel_event is not None and cancel_event.is_set():
                log.info("Генерация остановлена пользователем")
                return

            for line in response.iter_lines(decode_unicode=True):
                if cancel_event is not None and cancel_event.is_set():
                    log.info("Генерация остановлена пользователем")
                    return
                if not line:
                    continue
                try:
                    chunk = json.loads(line)
                except ValueError as exc:
                    if cancel_event is not None and cancel_event.is_set():
                        return  # поток закрыт при остановке: обрыв строки ожидаем
                    raise OllamaError("Некорректный ответ от Ollama.") from exc
                if "error" in chunk:
                    raise OllamaError(f"Ошибка генерации: {chunk['error']}")
                text = chunk.get("message", {}).get("content", "")
                if text:
                    yield text
                if chunk.get("done"):
                    self._done_local.chunk = chunk
                    break
            log.info("Завершение генерации")
        except requests.RequestException as exc:
            if cancel_event is not None and cancel_event.is_set():
                log.info("Генерация остановлена пользователем")
                return  # HTTP-поток закрыт при остановке: это не ошибка
            raise OllamaError("Соединение с Ollama прервано.") from exc
        except Exception:
            # внутренние ошибки urllib3 при закрытии потока из другого потока (например, AttributeError)
            if cancel_event is not None and cancel_event.is_set():
                log.info("Генерация остановлена пользователем")
                return
            raise
        finally:
            if response is not None:
                response.close()
