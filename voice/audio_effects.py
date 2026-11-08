"""Обработка синтезированной речи: более мягкий и нежный тембр голоса LISA.

Русский голос Piper (ru_RU-irina) — единственный женский русский голос Piper, поэтому тембр
меняется обработкой, а не заменой модели:
- высота: голос записывается с чуть большей частотой дискретизации (он звучит выше и легче),
  а синтез заранее замедляется на ту же величину — темп речи не меняется;
- мягкость: ослабление резких высоких частот (шипящие и свистящие звучат мягче);
- плавные края фразы без щелчков и короткая пауза после неё.

Работает в фоновом потоке синтеза, на numpy (ставится вместе с piper-tts). Не зависит от Qt.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

PITCH_RANGE = (-8.0, 12.0)     # % от исходной высоты
SOFTNESS_RANGE = (0, 100)


@dataclass(frozen=True)
class VoiceStyle:
    pitch: float = 4.0     # на сколько процентов выше исходного голоса
    softness: int = 60     # 0 — исходный тембр, 100 — максимально мягкий
    pause_ms: int = 140    # тишина после фразы

    @property
    def pitch_factor(self) -> float:
        lo, hi = PITCH_RANGE
        return 1.0 + max(lo, min(hi, float(self.pitch))) / 100.0

    @classmethod
    def from_settings(cls, settings: dict) -> "VoiceStyle":
        try:
            pitch = float(settings.get("voice_pitch", cls.pitch))
        except (TypeError, ValueError):
            pitch = cls.pitch
        try:
            softness = int(settings.get("voice_softness", cls.softness))
        except (TypeError, ValueError):
            softness = cls.softness
        lo, hi = PITCH_RANGE
        return cls(pitch=max(lo, min(hi, pitch)), softness=max(0, min(100, softness)))


ORIGINAL = VoiceStyle(pitch=0.0, softness=0, pause_ms=0)   # голос как в v0.1
GENTLE = VoiceStyle()                                      # голос по умолчанию


def _smooth(x: np.ndarray) -> np.ndarray:
    """Простой фильтр нижних частот [1, 2, 1] / 4: на верхних частотах звук становится тише."""
    padded = np.concatenate(([x[0]], x, [x[-1]]))
    return 0.25 * padded[:-2] + 0.5 * padded[1:-1] + 0.25 * padded[2:]


def apply_style(samples: np.ndarray, sample_rate: int, style: VoiceStyle) -> tuple[np.ndarray, int]:
    """samples — моно float32 в диапазоне −1..1. Возвращает int16 и частоту для записи в WAV."""
    x = np.asarray(samples, dtype=np.float32)
    if x.size == 0:
        return np.zeros(0, dtype=np.int16), sample_rate

    softness = max(0, min(100, int(style.softness))) / 100.0
    if softness > 0 and x.size > 4:
        low = _smooth(_smooth(x))
        x = x + (0.75 * softness) * (low - x)   # ослабляем «колючие» верхние частоты

    # плавное начало и конец фразы: без щелчков между фрагментами
    fade_in = min(x.size, int(sample_rate * 0.008))
    fade_out = min(x.size, int(sample_rate * 0.018))
    if fade_in:
        x[:fade_in] *= np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    if fade_out:
        x[-fade_out:] *= np.linspace(1.0, 0.0, fade_out, dtype=np.float32)

    peak = float(np.max(np.abs(x))) if x.size else 0.0
    if peak > 1e-6:
        x *= 0.85 / peak   # ровная громкость без перегрузки

    out_rate = int(round(sample_rate * style.pitch_factor))
    pause = np.zeros(int(out_rate * max(0, style.pause_ms) / 1000.0), dtype=np.float32)
    x = np.concatenate((x, pause))
    return np.clip(x * 32767.0, -32768, 32767).astype(np.int16), out_rate
