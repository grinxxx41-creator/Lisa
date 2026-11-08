"""Фоновые задачи GUI: генерация ответа, загрузка модели, проверка состояния Ollama.

Вся сетевая работа выполняется в QThread, главный поток только получает сигналы.
"""

from __future__ import annotations

import logging
import threading
import time

from PySide6.QtCore import QThread, Signal

from core.ai_engine import AIEngine, OllamaError
from core.model_manager import ModelManager, OllamaStatus, StatusInfo
from monitoring.session_stats import parse_ollama_stats

log = logging.getLogger("sirius.workers")


class GenerationWorker(QThread):
    token = Signal(str)
    finished_ok = Signal(str)   # полный ответ, его нужно сохранить в диалоге
    stopped = Signal(str)       # ответ прерван пользователем: текст не сохраняется
    failed = Signal(str)
    stats = Signal(object)      # v0.3: monitoring.session_stats.GenerationStats, перед finished_ok

    def __init__(self, engine: AIEngine, messages: list[dict], parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._messages = messages
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._response = None  # открытый HTTP-поток, его можно закрыть из GUI-потока

    def stop(self) -> None:
        """Прерывает генерацию: закрывает HTTP-поток, чтение прекращается сразу."""
        self._cancel.set()
        with self._lock:
            response = self._response
        if response is not None:
            _close_response(response)

    def _on_response(self, response) -> None:
        with self._lock:
            self._response = response
        if self._cancel.is_set():  # остановка пришла раньше, чем открылся поток
            _close_response(response)

    def run(self) -> None:
        parts: list[str] = []
        start = time.monotonic()
        first_token: float | None = None
        try:
            for piece in self._engine.stream_reply(self._messages, self._cancel, on_response=self._on_response):
                if first_token is None:
                    first_token = time.monotonic() - start
                parts.append(piece)
                self.token.emit(piece)
            text = "".join(parts)
            if self._cancel.is_set():
                self.stopped.emit(text)
            else:
                self._emit_stats(first_token)
                self.finished_ok.emit(text)
        except OllamaError as exc:
            if self._cancel.is_set():
                self.stopped.emit("".join(parts))
            else:
                self.failed.emit(str(exc))
        except Exception:  # непредвиденная ошибка не должна закрывать приложение
            if self._cancel.is_set():
                self.stopped.emit("".join(parts))
                return
            log.exception("Непредвиденная ошибка генерации")
            self.failed.emit("Внутренняя ошибка генерации. Подробности в журнале.")
        finally:
            with self._lock:
                self._response = None

    def _emit_stats(self, first_token: float | None) -> None:
        """v0.3: скорость генерации и время до первого токена (данные Ollama)."""
        take = getattr(self._engine, "take_done_stats", None)
        done = take() if take is not None else None
        stats = parse_ollama_stats(done, first_token) if done else None
        if stats is not None:
            self.stats.emit(stats)


def _close_response(response) -> None:
    """Закрывает HTTP-поток. Ошибки закрытия не важны: поток всё равно не нужен."""
    try:
        response.close()
    except Exception:
        log.debug("Ошибка при закрытии HTTP-потока", exc_info=True)


class TitleWorker(QThread):
    """Придумывает название диалога в фоне: модель не должна задерживать интерфейс."""

    done = Signal(str, str)  # file_id, название

    def __init__(self, engine: AIEngine, file_id: str, first_message: str, parent=None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._file_id = file_id
        self._first_message = first_message

    def run(self) -> None:
        from core.title_generator import generate_title

        self.done.emit(self._file_id, generate_title(self._engine, self._first_message))


class PullWorker(QThread):
    progress = Signal(str, float)  # статус, доля (-1, если неизвестна)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, manager: ModelManager, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._response = None

    def cancel(self) -> None:
        """Отменяет загрузку: закрывает HTTP-поток, даже если сервер временно молчит."""
        self._cancel.set()
        with self._lock:
            response = self._response
        if response is not None:
            _close_response(response)

    def _on_response(self, response) -> None:
        with self._lock:
            self._response = response
        if self._cancel.is_set():
            _close_response(response)

    def run(self) -> None:
        def on_progress(status: str, fraction: float | None) -> None:
            self.progress.emit(status, -1.0 if fraction is None else fraction)

        try:
            self._manager.pull_model(on_progress, self._cancel, on_response=self._on_response)
            if not self._cancel.is_set():
                self.finished_ok.emit()
        except OllamaError as exc:
            if not self._cancel.is_set():  # при отмене ошибка ожидаема и не показывается
                self.failed.emit(str(exc))
        except Exception:
            if self._cancel.is_set():
                return
            log.exception("Непредвиденная ошибка загрузки модели")
            self.failed.emit("Не удалось загрузить модель. Подробности в журнале.")
        finally:
            with self._lock:
                self._response = None


class SystemInfoWorker(QThread):
    """Периодический сбор системной информации для панели SYSTEM.

    Работает, пока панель видна. stop() не ждёт завершения: GUI-поток не блокируется.
    """

    snapshot = Signal(object)   # monitoring.system_info.SystemSnapshot
    models = Signal(object)     # list[(имя, байт видеопамяти)] или None, если Ollama недоступна

    def __init__(self, collector, models_source=None, interval_ms: int = 1500, models_every: int = 4,
                 processes_source=None, parent=None) -> None:
        super().__init__(parent)
        self._collector = collector
        self._models_source = models_source
        self._processes_source = processes_source   # v0.3: функция → собирать ли процессы на этом шаге
        self._interval = max(interval_ms, 200) / 1000.0
        self._models_every = max(models_every, 1)
        self._cancel = threading.Event()

    def stop(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        tick = 0
        while not self._cancel.is_set():
            try:
                if self._processes_source is None:
                    self.snapshot.emit(self._collector.collect())
                else:
                    self.snapshot.emit(self._collector.collect(processes=bool(self._processes_source())))
            except Exception:
                log.exception("Ошибка сбора системной информации")
            if self._models_source is not None and tick % self._models_every == 0 and not self._cancel.is_set():
                try:
                    self.models.emit(self._models_source())
                except OllamaError:
                    self.models.emit(None)
                except Exception:
                    log.exception("Ошибка запроса загруженных моделей")
                    self.models.emit(None)
            tick += 1
            self._cancel.wait(self._interval)


class LogTailWorker(QThread):
    """Читает новые строки журнала для панели LOGS, пока панель видна."""

    entries = Signal(object)   # list[core.log_reader.LogEntry]

    def __init__(self, tailer, interval_ms: int = 700, parent=None) -> None:
        super().__init__(parent)
        self._tailer = tailer
        self._interval = max(interval_ms, 100) / 1000.0
        self._cancel = threading.Event()

    def stop(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        while not self._cancel.is_set():
            try:
                batch = self._tailer.read_new()
                if batch and not self._cancel.is_set():
                    self.entries.emit(batch)
            except Exception:
                log.exception("Ошибка чтения журнала")
            self._cancel.wait(self._interval)


class StatusWorker(QThread):
    result = Signal(object)  # StatusInfo

    def __init__(self, manager: ModelManager, try_start: bool, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._try_start = try_start
        self._cancel = threading.Event()

    def cancel(self) -> None:
        """Прерывает ожидание запуска сервера, когда окно закрывается."""
        self._cancel.set()

    def run(self) -> None:
        try:
            if self._try_start and not self._manager.is_api_available():
                if self._manager.find_executable() is not None:
                    self._manager.start_server(cancel_event=self._cancel)
            if self._cancel.is_set():
                return
            info: StatusInfo = self._manager.check_status()
        except Exception:
            log.exception("Ошибка проверки состояния Ollama")
            info = StatusInfo(OllamaStatus.NOT_RUNNING, "Не удалось проверить Ollama")
        if not self._cancel.is_set():
            self.result.emit(info)


# --- загрузка при запуске ---------------------------------------------------------------

BOOT_STAGES = (
    ("ollama", "Подключение к Ollama"),
    ("model", "Проверка модели"),
    ("vram", "Загрузка Qwen в видеопамять"),
    ("voice", "Голосовой модуль"),
)


def _run_cancellable(fn, cancel: threading.Event, poll: float = 0.2):
    """Выполняет блокирующий вызов в отдельном daemon-потоке и ждёт его, проверяя отмену.

    HTTP-запрос загрузки модели нельзя прервать изнутри, поэтому при закрытии окна рабочий поток
    просто перестаёт ждать: daemon-поток не мешает завершению приложения.
    Возвращает (готово, результат, исключение).
    """
    box: dict = {}
    done = threading.Event()

    def target():
        try:
            box["result"] = fn()
        except BaseException as exc:  # передаётся вызывающему коду
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=target, daemon=True, name="sirius-boot-call").start()
    while not done.wait(poll):
        if cancel.is_set():
            return False, None, None
    return True, box.get("result"), box.get("error")


class BootWorker(QThread):
    """Последовательность запуска: Ollama → модель → загрузка в видеопамять → голос.

    stage(ключ, состояние, подробности): состояние — run, ok, fail или skip.
    status(StatusInfo) — итог проверки Ollama, как у StatusWorker.
    """

    stage = Signal(str, str, str)
    status = Signal(object)

    def __init__(self, manager: ModelManager, num_ctx: int, voice_preload=None, parent=None) -> None:
        super().__init__(parent)
        self._manager = manager
        self._num_ctx = num_ctx
        self._voice_preload = voice_preload   # функция без аргументов → название голоса, или None
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    def run(self) -> None:
        try:
            info = self._boot_model()
        except Exception:
            log.exception("Ошибка запуска Ollama")
            info = StatusInfo(OllamaStatus.NOT_RUNNING, "Не удалось проверить Ollama")
        if self._cancel.is_set():
            return
        self._boot_voice()
        if not self._cancel.is_set():
            self.status.emit(info)

    def _boot_model(self) -> StatusInfo:
        m = self._manager
        self.stage.emit("ollama", "run", "")
        if not m.is_api_available():
            if m.find_executable() is None:
                self.stage.emit("ollama", "fail", "не установлена")
                self._skip_model("нет Ollama")
                return StatusInfo(OllamaStatus.NOT_INSTALLED, "Ollama не установлена")
            self.stage.emit("ollama", "run", "запуск сервера…")
            m.start_server(cancel_event=self._cancel)
            if self._cancel.is_set():
                return StatusInfo(OllamaStatus.NOT_RUNNING, "")
        info = m.check_status()
        if info.status in (OllamaStatus.NOT_RUNNING, OllamaStatus.NOT_INSTALLED):
            self.stage.emit("ollama", "fail", "не отвечает")
            self._skip_model("нет Ollama")
            return info
        self.stage.emit("ollama", "ok", "на связи")
        if info.status == OllamaStatus.NO_MODEL:
            self.stage.emit("model", "fail", "не загружена")
            self.stage.emit("vram", "skip", "")
            return info
        self.stage.emit("model", "ok", m.model_name)
        self.stage.emit("vram", "run", "")
        done, elapsed, error = _run_cancellable(lambda: m.preload(self._num_ctx), self._cancel)
        if done:
            if error is None:
                self.stage.emit("vram", "ok", f"{elapsed:.1f} с")
            else:
                log.warning("Предзагрузка модели: %s", error)
                self.stage.emit("vram", "fail", "загрузится при первом сообщении")
        return info

    def _skip_model(self, reason: str) -> None:
        self.stage.emit("model", "skip", reason)
        self.stage.emit("vram", "skip", "")

    def _boot_voice(self) -> None:
        if self._voice_preload is None:
            self.stage.emit("voice", "skip", "VOICE OFF")
            return
        self.stage.emit("voice", "run", "")
        done, name, error = _run_cancellable(self._voice_preload, self._cancel)
        if not done:
            return
        if error is None:
            self.stage.emit("voice", "ok", str(name))
        else:
            log.warning("Голос при запуске: %s", error)
            self.stage.emit("voice", "fail", "недоступен")
