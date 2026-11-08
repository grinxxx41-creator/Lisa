"""Синтез речи: Silero TTS (голос xenia, по умолчанию) или Piper TTS (запасной). Локально, без GUI.

Если Silero недоступен (нет PyTorch или файла модели), речь продолжается голосом Piper.

Блокировки:
- `_state_lock` защищает путь к модели и ссылку на загруженный голос. Его держат только короткие
  операции, поэтому GUI-поток может вызвать `set_model_path` и не ждёт синтеза.
- `_work_lock` сериализует загрузку модели и синтез. Он нужен только рабочему потоку.
"""

from __future__ import annotations

import io
import logging
import re
import tempfile
import threading
import wave
from pathlib import Path

from voice.audio_effects import GENTLE, VoiceStyle

log = logging.getLogger("sirius.voice")

# Вариативность интонации и ритма Piper: ближе к значениям модели (0.667 / 0.8), чем в v0.1 (0.5 / 0.7):
# речь живее и мягче, без «роботизированной» ровности
NOISE_SCALE = 0.6
NOISE_W_SCALE = 0.75


class VoiceUnavailable(Exception):
    """Голосовая модель или библиотека Piper недоступны."""


class SynthesisError(Exception):
    """Не удалось озвучить одну фразу. Голос в целом остаётся доступным."""


def unlink_quietly(path: Path) -> bool:
    """Удаляет файл. Возвращает False, если файл занят или удалить его не удалось."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError as exc:
        log.debug("Не удалось удалить временный файл %s: %s", path.name, exc)
        return False


class TTSEngine:
    def __init__(self, model_path: Path, temp_dir: Path | None = None) -> None:
        self.model_path = Path(model_path)
        self.temp_dir = Path(temp_dir or tempfile.gettempdir())
        self._voice = None
        self._voice_path: Path | None = None  # путь, из которого загружен self._voice
        self.style: VoiceStyle = GENTLE
        self.engine_name = "piper"
        self.silero_path: Path | None = None
        self.speaker = "xenia"
        self._silero = None
        self._silero_loaded_path: Path | None = None
        self._silero_failed: Path | None = None   # модель, которую не удалось загрузить
        self._state_lock = threading.Lock()
        self._work_lock = threading.Lock()

    def set_model_path(self, model_path: Path) -> None:
        """Меняет голосовую модель. Если путь не изменился, загруженная модель сохраняется."""
        new_path = Path(model_path)
        with self._state_lock:
            if new_path == self.model_path:
                return
            self.model_path = new_path
            self._voice = None
            self._voice_path = None

    def set_engine(self, name: str, silero_path: Path | None = None, speaker: str = "xenia") -> None:
        """Выбор голоса: "silero" или "piper". Модель Silero загружается при первой фразе."""
        with self._state_lock:
            self.engine_name = "silero" if name == "silero" else "piper"
            self.speaker = speaker or "xenia"
            new_path = Path(silero_path) if silero_path else None
            if new_path != self.silero_path:
                self.silero_path = new_path
                self._silero = None
                self._silero_loaded_path = None
                self._silero_failed = None

    def silero_available(self) -> bool:
        """Silero выбран, файл модели есть, PyTorch установлен и модель не падала при загрузке."""
        with self._state_lock:
            path, failed, name = self.silero_path, self._silero_failed, self.engine_name
        if name != "silero" or path is None or not path.exists() or path == failed:
            return False
        import importlib.util

        return importlib.util.find_spec("torch") is not None

    def active_engine(self) -> str:
        return "silero" if self.silero_available() else "piper"

    def check(self, path: Path | None = None) -> None:
        """Проверяет, что голос доступен. Бросает VoiceUnavailable."""
        if path is None and self.silero_available():
            return
        model = Path(path) if path is not None else self.model_path
        config = Path(str(model) + ".json")
        if not model.exists():
            raise VoiceUnavailable(
                f"Голосовая модель не найдена: {model}. "
                "Положите файл .onnx и .onnx.json в папку resources/voices."
            )
        if not config.exists():
            raise VoiceUnavailable(f"Нет файла конфигурации голоса: {config.name}")

    def _load_voice(self, path: Path):
        self.check(path)
        try:
            from piper import PiperVoice
        except ImportError as exc:
            raise VoiceUnavailable("Библиотека piper-tts не установлена.") from exc
        try:
            voice = PiperVoice.load(str(path), config_path=str(path) + ".json")
        except Exception as exc:  # piper сообщает разные типы ошибок при порче модели
            raise VoiceUnavailable(f"Не удалось загрузить голосовую модель: {exc}") from exc
        log.info("Голосовая модель загружена: %s", path.name)
        return voice

    def _current_voice(self):
        """Возвращает голос для текущего пути, при необходимости загружая его.

        Вызывается только под `_work_lock`. Во время самой загрузки `_state_lock` не удерживается.
        """
        with self._state_lock:
            path = self.model_path
            if self._voice is not None and self._voice_path == path:
                return self._voice
        voice = self._load_voice(path)
        with self._state_lock:
            if self.model_path == path:  # путь не менялся, пока шла загрузка
                self._voice = voice
                self._voice_path = path
        return voice

    def synthesize(self, text: str, speed: float = 1.0) -> Path | None:
        """Синтезирует текст в WAV-файл во временной папке и возвращает путь к нему.

        Возвращает None, если во фразе нечего произносить (например, одна точка).
        Бросает VoiceUnavailable, если голос недоступен, и SynthesisError при сбое одной фразы.
        """
        if not re.search(r"\w", text):
            return None
        if self.silero_available():
            try:
                return self._synthesize_silero(text, speed)
            except VoiceUnavailable as exc:
                log.warning("Silero недоступен, используется голос Piper: %s", exc)
        from piper import SynthesisConfig

        with self._state_lock:
            style = self.style
        with self._work_lock:
            voice = self._current_voice()
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=str(self.temp_dir), suffix=".wav", prefix="tts_")
            path = Path(name)
            try:
                # length_scale > 1 — речь медленнее. Повышение тона ускоряет воспроизведение,
                # поэтому синтез заранее замедляется на ту же величину: темп остаётся прежним.
                syn = SynthesisConfig(
                    length_scale=style.pitch_factor / max(speed, 0.1),
                    noise_scale=NOISE_SCALE,
                    noise_w_scale=NOISE_W_SCALE,
                )
                buffer = io.BytesIO()
                with wave.open(buffer, "wb") as wav:
                    voice.synthesize_wav(text, wav, syn_config=syn)
                with open(fd, "wb") as raw:
                    raw.write(_styled_wav(buffer.getvalue(), style))
            except Exception as exc:
                unlink_quietly(path)
                raise SynthesisError(f"Не удалось озвучить фразу: {exc}") from exc
            if path.stat().st_size <= 44:  # только заголовок WAV, звука нет
                unlink_quietly(path)
                return None
            return path

    def _current_silero(self):
        with self._state_lock:
            path = self.silero_path
            if self._silero is not None and self._silero_loaded_path == path:
                return self._silero
        try:
            from voice.silero_engine import SileroVoice

            voice = SileroVoice.load(path)
        except Exception as exc:  # нет torch, повреждённый файл и т. п.
            with self._state_lock:
                self._silero_failed = path
            raise VoiceUnavailable(f"Не удалось загрузить модель Silero: {exc}") from exc
        with self._state_lock:
            if self.silero_path == path:
                self._silero = voice
                self._silero_loaded_path = path
        return voice

    def _synthesize_silero(self, text: str, speed: float) -> Path | None:
        from voice.silero_engine import SAMPLE_RATE

        with self._state_lock:
            style, speaker = self.style, self.speaker
        with self._work_lock:
            voice = self._current_silero()
            try:
                # повышение тона ускоряет воспроизведение — синтез заранее замедляется на столько же
                samples = voice.synthesize(text, speaker, max(speed, 0.1) / style.pitch_factor)
            except Exception as exc:
                raise SynthesisError(f"Не удалось озвучить фразу: {exc}") from exc
            if samples is None or not len(samples):
                return None
            self.temp_dir.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(dir=str(self.temp_dir), suffix=".wav", prefix="tts_")
            path = Path(name)
            try:
                with open(fd, "wb") as raw:
                    raw.write(_samples_to_wav(samples, SAMPLE_RATE, style))
            except Exception as exc:
                unlink_quietly(path)
                raise SynthesisError(f"Не удалось озвучить фразу: {exc}") from exc
            return path

    def preload(self) -> str:
        """Загружает модель голоса заранее (из фонового потока). Возвращает название голоса.

        Бросает VoiceUnavailable, если не доступен ни Silero, ни Piper.
        """
        if self.silero_available():
            try:
                with self._work_lock:
                    self._current_silero()
                return f"Silero {self.speaker}"
            except VoiceUnavailable as exc:
                log.warning("Silero недоступен, используется голос Piper: %s", exc)
        with self._work_lock:
            self._current_voice()
        return "Piper"

    def release(self) -> None:
        """Освобождает память голосовых моделей (режим «тяжёлая задача»). Следующая фраза загрузит их снова."""
        with self._state_lock:
            self._silero = None
            self._silero_loaded_path = None
            self._voice = None
            self._voice_path = None
        import gc

        gc.collect()
        log.info("Голосовые модели выгружены из памяти")

    def set_style(self, style: VoiceStyle) -> None:
        """Тембр голоса (высота, мягкость). Применяется к следующим фразам, синтез не ждёт."""
        with self._state_lock:
            self.style = style


def _styled_wav(data: bytes, style: VoiceStyle) -> bytes:
    """Применяет тембр к WAV из Piper. Без numpy или в необычном формате звук не меняется."""
    with wave.open(io.BytesIO(data), "rb") as src:
        channels, width, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()
        frames = src.readframes(src.getnframes())
    if not frames:
        return b""
    try:
        import numpy as np

        from voice.audio_effects import apply_style
    except ImportError:
        log.warning("numpy недоступен: голос без обработки тембра")
        return data
    if channels != 1 or width != 2:
        return data
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    return _samples_to_wav(samples, rate, style)


def _samples_to_wav(samples, rate: int, style: VoiceStyle) -> bytes:
    """float −1..1 → WAV с применённым тембром."""
    from voice.audio_effects import apply_style

    pcm, out_rate = apply_style(samples, rate, style)
    out = io.BytesIO()
    with wave.open(out, "wb") as dst:
        dst.setnchannels(1)
        dst.setsampwidth(2)
        dst.setframerate(out_rate)
        dst.writeframes(pcm.astype("<i2").tobytes())
    return out.getvalue()
