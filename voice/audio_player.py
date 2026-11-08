"""Воспроизведение WAV-файлов через Qt Multimedia. Создаётся в главном потоке GUI."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

log = logging.getLogger("sirius.audio")


class AudioPlayer(QObject):
    finished = Signal(str)  # путь файла, который доигран или не смог воспроизвестись

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._output = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._output)
        self._player.mediaStatusChanged.connect(self._on_status)
        self._active = False
        self._path: str | None = None
        self._output.setVolume(0.8)

    def play(self, path: Path) -> None:
        self._path = str(path)
        self._active = True
        self._player.setSource(QUrl.fromLocalFile(self._path))
        self._player.play()
        log.info("Начало воспроизведения")

    def stop(self) -> None:
        """Немедленно останавливает воспроизведение и не сообщает о завершении."""
        if self._active or self.is_playing():
            log.info("Остановка голоса")
        self._active = False
        self._path = None
        self._player.stop()
        self._player.setSource(QUrl())  # отпускаем файл, чтобы его можно было удалить

    def set_volume(self, percent: int) -> None:
        self._output.setVolume(max(0, min(100, percent)) / 100.0)

    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    def _on_status(self, status) -> None:
        # Сигнал может прийти от уже остановленного файла: учитываем его, только если он
        # совпадает с текущим состоянием плеера.
        if not self._active or status != self._player.mediaStatus():
            return
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            finished_path = self._path or ""
            self._finish_current()
            self.finished.emit(finished_path)
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            log.error("Аудиофайл не удалось воспроизвести")
            finished_path = self._path or ""
            self._finish_current()
            self.finished.emit(finished_path)

    def _finish_current(self) -> None:
        self._active = False
        self._path = None
        self._player.setSource(QUrl())
