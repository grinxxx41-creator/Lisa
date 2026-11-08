"""Голос Silero (xenia): числа словами, подготовка текста, выбор движка и запасной Piper."""

from __future__ import annotations

import importlib.util
import wave
from pathlib import Path

import pytest

from voice.audio_effects import GENTLE, ORIGINAL
from voice.numbers_ru import int_to_words, number_to_words, numbers_to_words
from voice.silero_engine import SAMPLE_RATE, silero_text
from voice.text_processing import prepare_phrase
from voice.tts_engine import TTSEngine

PROJECT = Path(__file__).resolve().parent.parent
SILERO = PROJECT / "resources" / "voices" / "silero_v4_ru.pt"
HAS_TORCH = importlib.util.find_spec("torch") is not None


def test_integers_to_words():
    assert int_to_words(0) == "ноль"
    assert int_to_words(45) == "сорок пять"
    assert int_to_words(112) == "сто двенадцать"
    assert int_to_words(2023) == "две тысячи двадцать три"
    assert int_to_words(1500) == "одна тысяча пятьсот"
    assert int_to_words(3050) == "три тысячи пятьдесят"
    assert int_to_words(21_000_000) == "двадцать один миллион"


def test_decimals_and_versions():
    assert number_to_words("12,5") == "двенадцать целых пять десятых"
    assert number_to_words("3.12") == "три точка двенадцать"
    assert numbers_to_words("RTX 3050 и 16 ГБ") == "RTX три тысячи пятьдесят и шестнадцать ГБ"


def test_silero_text_has_no_digits_or_latin():
    for raw in ("Загрузка CPU — 45%, RAM 12,4 ГБ из 16 ГБ.", "Python 3.12 вышел в 2023 г.",
                "Модель qwen3:8b-q4_K_M работает через Ollama."):
        text = silero_text(prepare_phrase(raw))
        assert not any(ch.isdigit() for ch in text), text
        assert not any("a" <= ch.lower() <= "z" for ch in text), text
        assert text


def test_engine_falls_back_to_piper_without_silero(tmp_path):
    engine = TTSEngine(tmp_path / "v.onnx", tmp_path)
    engine.set_engine("silero", tmp_path / "missing.pt", "xenia")
    assert engine.active_engine() == "piper"
    engine.set_engine("piper", SILERO, "xenia")
    assert engine.active_engine() == "piper"


def test_broken_silero_model_is_not_retried(tmp_path, monkeypatch):
    if not HAS_TORCH:
        pytest.skip("нет PyTorch")
    broken = tmp_path / "broken.pt"
    broken.write_bytes(b"not a model")
    engine = TTSEngine(tmp_path / "v.onnx", tmp_path)
    engine.set_engine("silero", broken, "xenia")
    assert engine.active_engine() == "silero"
    with pytest.raises(Exception):
        engine._synthesize_silero("Привет.", 1.0)
    assert engine.active_engine() == "piper"   # дальше говорит Piper, без повторных попыток


def test_settings_defaults_choose_silero_xenia(tmp_path):
    from storage.settings_storage import SettingsStorage

    s = SettingsStorage(tmp_path / "settings.json").load()
    assert s["voice_engine"] == "silero" and s["voice_speaker"] == "xenia"


def test_settings_dialog_engine_choice(qt_app):
    from interface.settings_panel import SettingsDialog
    from storage.settings_storage import DEFAULT_SETTINGS

    dlg = SettingsDialog(dict(DEFAULT_SETTINGS, voice_engine="piper", voice_speaker="baya"))
    assert dlg.values()["voice_engine"] == "piper" and dlg.values()["voice_speaker"] == "baya"


@pytest.mark.skipif(not (HAS_TORCH and SILERO.exists()), reason="нет PyTorch или модели Silero")
def test_real_xenia_synthesis(tmp_path):
    engine = TTSEngine(tmp_path / "v.onnx", tmp_path)
    engine.set_engine("silero", SILERO, "xenia")
    engine.set_style(ORIGINAL)
    path = engine.synthesize(prepare_phrase("Здравствуйте! Загрузка GPU — 45%."), speed=1.0)
    with wave.open(str(path)) as w:
        assert w.getframerate() == SAMPLE_RATE
        seconds = w.getnframes() / w.getframerate()
    assert 1.5 < seconds < 8
    engine.set_style(GENTLE)
    path2 = engine.synthesize("Привет.", speed=1.0)
    with wave.open(str(path2)) as w:
        assert w.getframerate() == round(SAMPLE_RATE * GENTLE.pitch_factor)
    assert engine.synthesize("...", 1.0) is None
