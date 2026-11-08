"""Управление голосом: очередь фраз, синтез в фоне, воспроизведение, мгновенная остановка.

Текстовая генерация не связана с этим модулем и продолжается при остановке речи.
"""

from __future__ import annotations

import logging
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from voice.audio_player import AudioPlayer
from voice.text_processing import SentenceBuffer
from voice.tts_engine import TTSEngine, VoiceUnavailable, unlink_quietly

log = logging.getLogger("sirius.voice")


class VoiceController(QObject):
    speaking_changed = Signal(bool)   # True — LISA сейчас говорит или готова говорить
    error = Signal(str)               # понятное сообщение для пользователя
    _synth_done = Signal(int, object)  # (токен, Future) — из рабочего потока в GUI

    def __init__(self, engine: TTSEngine, player: AudioPlayer, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._engine = engine
        self._player = player
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="piper")
        self._buffer = SentenceBuffer()
        self._queue: deque[Path] = deque()
        self._current: Path | None = None
        self._to_delete: list[Path] = []  # временные файлы, которые Windows пока не отпустила
        self._pending = 0
        self._token = 0
        self._speed = 1.0
        self._enabled = False
        self._muted = False       # после нажатия на аватар до следующего сообщения речь не возобновляется
        self._unavailable = False
        self._speaking = False
        self._closed = False
        self._synth_done.connect(self._on_synth_done)
        self._player.finished.connect(self._on_playback_finished)

    # --- настройки ----------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.stop()
        else:
            self._muted = False

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.5, min(2.0, speed))

    def set_volume(self, percent: int) -> None:
        self._player.set_volume(percent)

    def check_available(self) -> bool:
        """Проверяет наличие голосовой модели. Ошибка выводится через сигнал error."""
        try:
            self._engine.check()
            self._unavailable = False
            return True
        except VoiceUnavailable as exc:
            self._unavailable = True
            self.error.emit(str(exc))
            return False

    # --- поток текста от модели ---------------------------------------------

    def feed(self, delta: str) -> None:
        """Принимает очередной фрагмент ответа модели."""
        if not self._enabled or self._unavailable or self._muted:
            return
        for sentence in self._buffer.feed(delta):
            self._enqueue(sentence)

    def begin_message(self) -> None:
        """Вызывается перед новым ответом: снимает приглушение после нажатия на аватар."""
        self._muted = False
        self._buffer = SentenceBuffer()

    def say(self, text: str) -> None:
        """Произносит произвольный текст сразу (например, тест голоса в настройках)."""
        if self._unavailable:
            return
        self.stop()
        self._muted = False
        from voice.text_processing import prepare_phrase
        cleaned = prepare_phrase(text)
        if cleaned:
            self._enqueue(cleaned)

    def set_style(self, style) -> None:
        """Тембр голоса (voice.audio_effects.VoiceStyle) для следующих фраз."""
        set_style = getattr(self._engine, "set_style", None)
        if callable(set_style):
            set_style(style)

    def finish_message(self) -> None:
        """Озвучивает остаток текста после завершения ответа."""
        if not self._enabled or self._unavailable or self._muted:
            self._buffer = SentenceBuffer()
            return
        for sentence in self._buffer.flush():
            self._enqueue(sentence)

    # --- остановка ----------------------------------------------------------

    def stop(self) -> None:
        """Немедленно останавливает речь и очищает очередь. Генерация текста не затрагивается.

        Текущий ответ больше не озвучивается, пока не начнётся следующий (см. begin_message).
        """
        self._muted = True
        self._buffer = SentenceBuffer()
        self._token += 1          # результаты уже запущенного синтеза будут отброшены
        self._pending = 0
        self._player.stop()       # после этого файл можно удалить
        while self._queue:
            self._remove_later(self._queue.popleft())
        if self._current is not None:
            self._remove_later(self._current)
            self._current = None
        self._update_speaking()

    def is_speaking(self) -> bool:
        return self._speaking

    def shutdown(self) -> None:
        """Останавливает речь и завершает фоновый синтез перед закрытием приложения."""
        self.stop()
        self._closed = True
        self._executor.shutdown(wait=True, cancel_futures=True)  # ждём только уже идущий синтез
        self._flush_deletions()

    # --- внутренняя логика ---------------------------------------------------

    def _enqueue(self, text: str) -> None:
        if self._closed:
            return
        self._pending += 1
        token = self._token
        future = self._executor.submit(self._engine.synthesize, text, self._speed)
        future.add_done_callback(lambda f, t=token: self._synth_done.emit(t, f))
        self._update_speaking()

    def _on_synth_done(self, token: int, future: Future) -> None:
        if token == self._token:
            self._pending = max(0, self._pending - 1)
        try:
            path = future.result()
        except VoiceUnavailable as exc:
            # голос выключен целиком (нет модели или библиотеки), чат продолжает работать
            log.error("Синтез речи недоступен: %s", exc)
            self._unavailable = True
            self._buffer = SentenceBuffer()
            self.error.emit(str(exc))
            self._update_speaking()
            return
        except Exception as exc:  # сбой одной фразы не отключает голос
            log.warning("Фраза не озвучена: %s", exc)
            self._update_speaking()
            return

        if path is None:  # во фразе нет речи, например одна точка
            self._update_speaking()
            return
        if token != self._token:  # фраза создана до остановки: не воспроизводим
            self._remove_later(Path(path))
            self._update_speaking()
            return
        self._queue.append(Path(path))
        self._play_next()

    def _play_next(self) -> None:
        if self._player.is_playing() or self._current is not None:
            self._update_speaking()
            return
        if not self._queue:
            self._update_speaking()
            return
        self._current = self._queue.popleft()
        self._player.play(self._current)
        self._update_speaking()

    def _on_playback_finished(self, path: str) -> None:
        if self._current is None or str(self._current) != path:
            return  # сигнал относится к файлу, который уже не воспроизводится
        self._remove_later(self._current)  # файлы фраз одноразовые
        self._current = None
        self._play_next()
        self._update_speaking()

    def _remove_later(self, path: Path) -> None:
        """Удаляет временный файл. Если файл ещё занят плеером, попробует позже."""
        if path not in self._to_delete:
            self._to_delete.append(path)
        self._flush_deletions()

    def _flush_deletions(self) -> None:
        self._to_delete = [p for p in self._to_delete if not unlink_quietly(p)]

    def _update_speaking(self) -> None:
        busy = self._current is not None or bool(self._queue) or self._pending > 0
        if busy != self._speaking:
            self._speaking = busy
            self.speaking_changed.emit(busy)
