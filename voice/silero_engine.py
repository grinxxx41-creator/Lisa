"""Голос Silero TTS (v4_ru, по умолчанию xenia). Локально, на процессоре, без GUI.

Silero не читает цифры и латиницу: числа переводятся в слова (voice/numbers_ru.py), а оставшиеся
латинские буквы удаляются (латиницу заранее переписывает voice/speech_normalizer.py).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from xml.sax.saxutils import escape

from voice.numbers_ru import numbers_to_words

log = logging.getLogger("sirius.voice")

SAMPLE_RATE = 48000
SPEAKERS = ("xenia", "baya", "kseniya", "aidar", "eugene")
DEFAULT_SPEAKER = "xenia"
THREADS = 4  # не занимать все ядра: рядом работают Ollama и интерфейс


def silero_text(text: str) -> str:
    """Готовит фразу для Silero: числа словами, без латиницы и лишних символов."""
    text = numbers_to_words(text)
    text = re.sub(r"[A-Za-z]+", " ", text)
    text = re.sub(r"[^\w\s.,!?:;—–\-+ёЁ()«»\"']", " ", text)
    return re.sub(r"\s+", " ", text).strip()


class SileroVoice:
    """Загруженная модель Silero. Методы вызываются из одного рабочего потока."""

    def __init__(self, model) -> None:
        self._model = model

    @classmethod
    def load(cls, path: Path) -> "SileroVoice":
        import torch

        torch.set_num_threads(THREADS)
        importer = torch.package.PackageImporter(str(path))
        model = importer.load_pickle("tts_models", "model")
        model.to(torch.device("cpu"))
        log.info("Модель Silero загружена: %s", Path(path).name)
        return cls(model)

    @property
    def speakers(self) -> list[str]:
        return list(getattr(self._model, "speakers", SPEAKERS))

    def synthesize(self, text: str, speaker: str, speed: float):
        """Возвращает numpy float32 (−1..1) с частотой SAMPLE_RATE или None, если читать нечего."""
        phrase = silero_text(text)
        if not re.search(r"[а-яёА-ЯЁ]", phrase):
            return None
        rate = max(50, min(200, round(speed * 100)))
        ssml = f'<speak><prosody rate="{rate}%">{escape(phrase)}</prosody></speak>'
        audio = self._model.apply_tts(ssml_text=ssml, speaker=speaker, sample_rate=SAMPLE_RATE,
                                      put_accent=True, put_yo=True)
        return audio.numpy()
