"""Речь LISA: подготовка текста к произношению, нарезка потока на фразы, мягкий тембр."""

from __future__ import annotations

import io
import json
import re
import wave
from pathlib import Path

import numpy as np
import pytest

from voice.audio_effects import GENTLE, ORIGINAL, VoiceStyle, apply_style
from voice.speech_normalizer import latin_token_to_russian, normalize_for_speech, plural
from voice.text_processing import SentenceBuffer, prepare_phrase

PROJECT = Path(__file__).resolve().parent.parent
VOICE = PROJECT / "resources" / "voices" / "ru_RU-irina-medium.onnx"

ANSWERS = [
    "Python 3.12 вышел в 2023 г., т.е. год назад.",
    "Модель qwen3:8b-q4_K_M работает через Ollama на GPU RTX 3050.",
    "Загрузка CPU — 45%, RAM 12,4 ГБ из 16 ГБ, температура 52 °C.",
    "Используйте функцию `sum_list()` или метод AIEngine.stream_reply().",
    "Подробнее: https://ollama.com/download и C:\\Users\\User\\Desktop.",
    "Hello world! How are you? Это тест SIRIUS и LISA.",
    "Установите pip install requests, затем import json и print(data).",
]


def _stream(chunks: list[str]) -> list[str]:
    buf = SentenceBuffer()
    out: list[str] = []
    for chunk in chunks:
        out += buf.feed(chunk)
    return out + buf.flush()


# --- подготовка текста --------------------------------------------------------------


@pytest.mark.parametrize("text", ANSWERS)
def test_no_latin_letters_reach_the_voice(text):
    """Латиница даёт английские звуки, которых русский голос не знает, — отсюда «абракадабра»."""
    spoken = prepare_phrase(text)
    assert not re.search(r"[A-Za-z]", spoken), spoken
    assert spoken.strip()


def test_known_words_and_names():
    spoken = normalize_for_speech("SIRIUS, LISA, Python, Ollama и Qwen")
    for word in ("сириус", "лиза", "пайтон", "оллама", "квен"):
        assert word in spoken


def test_acronyms_and_identifiers():
    assert latin_token_to_russian("GPU") == "джи-пи-ю"
    assert latin_token_to_russian("stream_reply") == "стрим риплай"
    assert latin_token_to_russian("AIEngine") == "эй-ай энджин"
    assert latin_token_to_russian("qwen3") == "квен 3"


def test_unknown_english_words_are_read_by_rules():
    assert normalize_for_speech("make") == "мейк"
    assert normalize_for_speech("night") == "найт"
    assert normalize_for_speech("yes") == "йес"


def test_abbreviations_units_and_symbols():
    spoken = normalize_for_speech("Т.е. и т.д., 5 руб., 2024 г., 1 500 человек, 1920×1080")
    assert "то есть" in spoken.lower() and "и так далее" in spoken
    assert "5 рублей" in spoken and "2024 год" in spoken and "1500" in spoken and "1920 на 1080" in spoken


def test_percent_and_degree_agreement():
    assert normalize_for_speech("1%") == "1 процент"
    assert normalize_for_speech("3%") == "3 процента"
    assert normalize_for_speech("45%") == "45 процентов"
    assert normalize_for_speech("12,5%") == "12,5 процента"
    assert normalize_for_speech("52 °C") == "52 градуса"
    assert plural("11", "а", "б", "в") == "в"


def test_links_and_paths_are_not_spelled():
    spoken = normalize_for_speech("Смотрите https://ollama.com/download и C:\\Users\\User\\file.txt.")
    assert "ссылка" in spoken and "путь к файлу" in spoken
    assert "/" not in spoken and "\\" not in spoken


# --- поток ответа --------------------------------------------------------------------


def test_numbers_and_abbreviations_are_not_cut_mid_stream():
    out = _stream(["Версия Python 3.", "12 вышла, т.", "е. стоит обновиться. ", "Всё!"])
    assert out[0] == "Версия пайтон 3.12 вышла, то есть стоит обновиться."


def test_code_blocks_are_never_spoken():
    out = _stream([
        "Пример кода:\n```python\n# Считаем. ", "Сумму списка.\nx = sum(items)\n", "print(x)\n```\n",
        "Готово! Функция `sum_list()` вернёт результат.",
    ])
    text = " ".join(out)
    assert "Готово!" in text and "сам лист" in text
    assert "Считаем" not in text and "items" not in text and "принт" not in text


def test_unclosed_code_block_is_not_spoken():
    out = _stream(["Вот код:\n```bash\necho привет\nls -la"])
    assert " ".join(out) == "Вот код:"


def test_code_only_answer_gets_short_note():
    """Настоящий ответ Qwen: только блоки кода. Код не читается, LISA коротко говорит, где он."""
    tokens = ["```", "bash", "\n", "pip", " install", " requests", "\n", "``", "`\n\n", "```", "python",
              "\n", "import", " requests", "\n", "print", "(r)", "\n", "```"]
    assert _stream(tokens) == ["Код показан на экране."]
    assert _stream(["Обычный ответ без кода."]) == ["Обычный ответ без кода."]


def test_list_numbers_and_tables_are_cleaned():
    out = _stream(["Шаги:\n1. Откройте ", "настройки.\n2. Выберите голос.\n", "## Итог\n---\nГотово."])
    text = " ".join(out)
    assert "Откройте настройки." in text and "Выберите голос." in text
    assert not re.search(r"(^|\s)[12]\.", text)
    assert "#" not in text and "---" not in text


def test_long_sentence_is_split_at_commas():
    sentence = ", ".join(["это довольно длинная часть предложения"] * 12) + "."
    out = _stream([sentence + " "])
    assert len(out) > 1 and all(len(p) <= 270 for p in out)


@pytest.mark.skipif(not VOICE.exists(), reason="нет голосовой модели")
@pytest.mark.parametrize("text", ANSWERS)
def test_voice_gets_only_russian_sounds(text):
    """Проверка на настоящем Piper: после подготовки в фонемах нет английских звуков."""
    from piper import PiperVoice

    voice = _real_voice(PiperVoice)
    phonemes = "".join("".join(s) for s in voice.phonemize(prepare_phrase(text)))
    english = set("θðɹɜæʊɒ") | {"ː"}
    assert not english & set(phonemes), phonemes


_VOICE_CACHE: dict = {}


def _real_voice(cls):
    if "v" not in _VOICE_CACHE:
        _VOICE_CACHE["v"] = cls.load(str(VOICE))
    return _VOICE_CACHE["v"]


# --- тембр ---------------------------------------------------------------------------


def _tone(seconds=0.5, rate=22050):
    t = np.arange(int(seconds * rate)) / rate
    # низкий тон + резкая высокая составляющая (как шипящие)
    return (0.4 * np.sin(2 * np.pi * 220 * t) + 0.4 * np.sin(2 * np.pi * 9000 * t)).astype(np.float32)


def _high_energy(pcm: np.ndarray) -> float:
    x = pcm.astype(np.float32)
    return float(np.mean(np.abs(np.diff(x))))   # разность соседних отсчётов ~ верхние частоты


def test_softness_reduces_harsh_high_frequencies():
    x = _tone()
    soft, _ = apply_style(x, 22050, VoiceStyle(pitch=0, softness=100, pause_ms=0))
    plain, _ = apply_style(x, 22050, VoiceStyle(pitch=0, softness=0, pause_ms=0))
    assert _high_energy(soft) < 0.6 * _high_energy(plain)


def test_pitch_changes_playback_rate_and_pause_is_added():
    x = _tone(0.2)
    pcm, rate = apply_style(x, 22050, VoiceStyle(pitch=4, softness=0, pause_ms=100))
    assert rate == round(22050 * 1.04)
    assert pcm.dtype == np.int16
    assert len(pcm) == len(x) + int(rate * 0.1)
    assert not pcm[-int(rate * 0.1):].any()           # пауза — тишина
    assert abs(int(pcm[0])) < 50                       # плавное начало без щелчка


def test_original_style_keeps_rate():
    pcm, rate = apply_style(_tone(0.1), 22050, ORIGINAL)
    assert rate == 22050 and len(pcm) == int(0.1 * 22050)


def test_style_from_settings_clamps_values():
    style = VoiceStyle.from_settings({"voice_pitch": 99, "voice_softness": -5})
    assert style.pitch == 12 and style.softness == 0
    assert VoiceStyle.from_settings({}) == GENTLE


def test_engine_writes_styled_wav(monkeypatch, tmp_path):
    import piper

    from voice.tts_engine import TTSEngine

    class Voice:
        def synthesize_wav(self, text, wav, syn_config=None):
            Voice.length_scale = syn_config.length_scale
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(22050)
            wav.writeframes((_tone(0.2) * 32767).astype("<i2").tobytes())

    monkeypatch.setattr(piper, "PiperVoice", type("P", (), {"load": classmethod(lambda c, *a, **k: Voice())}))
    model = tmp_path / "v.onnx"
    model.write_bytes(b"x")
    (tmp_path / "v.onnx.json").write_text("{}", encoding="utf-8")
    engine = TTSEngine(model, tmp_path / "tmp")
    engine.set_style(GENTLE)
    path = engine.synthesize("Привет, мир.", speed=1.0)
    with wave.open(str(path)) as w:
        assert w.getframerate() == round(22050 * GENTLE.pitch_factor)
    assert Voice.length_scale == pytest.approx(GENTLE.pitch_factor)   # темп речи сохранён
    engine.set_style(ORIGINAL)
    path2 = engine.synthesize("Привет, мир.", speed=1.0)
    with wave.open(str(path2)) as w:
        assert w.getframerate() == 22050


# --- настройки -----------------------------------------------------------------------


def test_old_default_speed_is_migrated(tmp_path):
    from storage.settings_storage import SettingsStorage

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"voice_speed": 1.2}), encoding="utf-8")
    settings = SettingsStorage(path).load()
    assert settings["voice_speed"] == 1.0
    assert settings["voice_pitch"] == 4.0 and settings["voice_softness"] == 60


def test_user_chosen_speed_is_kept(tmp_path):
    from storage.settings_storage import SettingsStorage

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"voice_speed": 1.2, "voice_softness": 30}), encoding="utf-8")
    assert SettingsStorage(path).load()["voice_speed"] == 1.2      # уже новые настройки: выбор пользователя
    path.write_text(json.dumps({"voice_speed": 1.5}), encoding="utf-8")
    assert SettingsStorage(path).load()["voice_speed"] == 1.5


def test_settings_dialog_voice_presets(qt_app):
    from interface.settings_panel import SettingsDialog
    from storage.settings_storage import DEFAULT_SETTINGS

    dlg = SettingsDialog(dict(DEFAULT_SETTINGS))
    assert dlg.values()["voice_pitch"] == 4.0 and dlg.values()["voice_softness"] == 60
    dlg._apply_voice_preset(ORIGINAL, 1.0)
    assert dlg.values()["voice_pitch"] == 0.0 and dlg.values()["voice_softness"] == 0
    dlg._apply_voice_preset(GENTLE, 1.0)
    assert dlg.values()["voice_pitch"] == 4.0 and dlg.values()["voice_speed"] == 1.0


def test_localhost_ollama_url_is_migrated(tmp_path):
    from storage.settings_storage import SettingsStorage

    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"ollama_url": "http://localhost:11434/"}), encoding="utf-8")
    assert SettingsStorage(path).load()["ollama_url"] == "http://127.0.0.1:11434"
    path.write_text(json.dumps({"ollama_url": "http://192.168.1.5:11434"}), encoding="utf-8")
    assert SettingsStorage(path).load()["ollama_url"] == "http://192.168.1.5:11434"
