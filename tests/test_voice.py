"""Тесты голосового режима: очистка текста, разбиение на фразы, VOICE ON/OFF, остановка речи.

Piper и звуковая карта не используются: синтез и плеер заменены заглушками.
"""

from __future__ import annotations

import threading
import time
import wave
from concurrent.futures import Future
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Signal

from voice.text_processing import SentenceBuffer, clean_markdown
from voice.tts_engine import TTSEngine
from voice.voice_controller import VoiceController


def test_clean_markdown_removes_markup_and_code():
    text = "**Важно**: см. [документацию](http://x) и `print(1)`.\n```python\nx = 1\n```\n- пункт"
    cleaned = clean_markdown(text)
    assert "**" not in cleaned and "`" not in cleaned and "http" not in cleaned
    assert "x = 1" not in cleaned
    assert "Важно" in cleaned and "документацию" in cleaned


def test_sentence_buffer_emits_only_complete_sentences():
    buf = SentenceBuffer()
    assert buf.feed("Привет, как дела у тебя сегодня") == []
    sentences = buf.feed(". Всё хорошо, спасибо большое за вопрос! Что дальше")
    assert len(sentences) >= 1
    assert sentences[0].endswith("!") or sentences[0].endswith(".")
    assert buf.flush() == ["Что дальше"]


class FakeEngine:
    def __init__(self, available=True):
        self.available = available
        self.calls: list[str] = []
        self.dir = Path(".")

    def check(self):
        from voice.tts_engine import VoiceUnavailable

        if not self.available:
            raise VoiceUnavailable("Голосовая модель не найдена.")

    def synthesize(self, text: str, speed: float = 1.0) -> Path:
        self.calls.append(text)
        return self.dir / f"fake_{len(self.calls)}.wav"


class FakePlayer(QObject):
    finished = Signal(str)  # как в AudioPlayer: путь файла

    def __init__(self):
        super().__init__()
        self.played: list[Path] = []
        self.stopped = 0
        self._playing = False
        self._current: Path | None = None

    def play(self, path: Path) -> None:
        self._current = Path(path)
        self.played.append(Path(path))
        self._playing = True

    def stop(self) -> None:
        self.stopped += 1
        self._playing = False
        self._current = None

    def set_volume(self, percent: int) -> None:
        self.volume = percent

    def is_playing(self) -> bool:
        return self._playing

    def end_playback(self) -> None:
        """Имитирует окончание текущего файла."""
        done = str(self._current) if self._current else ""
        self._playing = False
        self._current = None
        self.finished.emit(done)


def _wait(qt_app, predicate, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _controller(qt_app, tmp_path, available=True):
    engine = FakeEngine(available)
    engine.dir = tmp_path
    for i in range(20):
        (tmp_path / f"fake_{i + 1}.wav").write_bytes(b"x")
    player = FakePlayer()
    controller = VoiceController(engine, player)
    return controller, engine, player


def test_voice_off_ignores_text(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(False)
    controller.feed("Это длинное предложение которое не должно озвучиваться никогда.")
    controller.finish_message()
    qt_app.processEvents()
    assert engine.calls == []
    assert player.played == []
    controller.shutdown()


def test_voice_on_speaks_completed_sentence(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(True)
    controller.feed("Это достаточно длинное предложение для озвучивания. ")
    assert _wait(qt_app, lambda: len(player.played) == 1)
    assert engine.calls and engine.calls[0].startswith("Это достаточно длинное")
    controller.shutdown()


def test_stop_clears_queue_and_stops_player(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(True)
    controller.say("Первая фраза достаточно длинная, чтобы её озвучили. Вторая фраза тоже длинная.")
    assert _wait(qt_app, lambda: len(player.played) >= 1)

    controller.stop()
    assert player.stopped >= 1
    assert controller.is_speaking() is False
    controller.shutdown()


def test_missing_voice_model_disables_voice_without_crash(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path, available=False)
    errors: list[str] = []
    controller.error.connect(errors.append)
    controller.set_enabled(True)
    assert controller.check_available() is False
    assert errors and "не найдена" in errors[0]
    controller.feed("Текст, который не должен падать даже без голоса. ")
    qt_app.processEvents()
    assert player.played == []
    controller.shutdown()


def test_avatar_stop_mutes_current_reply_until_next_message(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(True)
    controller.begin_message()
    controller.feed("Первое предложение достаточно длинное для озвучивания. ")
    assert _wait(qt_app, lambda: len(player.played) == 1)

    controller.stop()  # нажатие на аватар
    calls_after_stop = len(engine.calls)
    controller.feed("Второе предложение, которое не должно прозвучать после остановки. ")
    controller.finish_message()
    qt_app.processEvents()
    assert len(engine.calls) == calls_after_stop
    assert controller.is_speaking() is False

    controller.begin_message()  # новый ответ снова озвучивается
    controller.feed("Новый ответ достаточно длинный, чтобы его озвучили. ")
    assert _wait(qt_app, lambda: len(engine.calls) > calls_after_stop)
    controller.shutdown()


def test_phrase_synthesized_before_stop_is_not_played(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(True)
    controller.begin_message()
    old_token = controller._token
    controller.stop()
    result = Future()
    result.set_result(tmp_path / "fake_3.wav")  # синтез закончился уже после остановки
    controller._on_synth_done(old_token, result)
    qt_app.processEvents()
    assert player.played == []
    assert not (tmp_path / "fake_3.wav").exists()  # временный файл удалён
    controller.shutdown()


def test_stale_finished_signal_does_not_skip_current_phrase(qt_app, tmp_path):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(True)
    controller.begin_message()
    controller.feed("Первая фраза достаточно длинная для проверки. Вторая фраза тоже достаточно длинная. ")
    assert _wait(qt_app, lambda: len(player.played) == 1)
    first = str(player.played[0])
    player.end_playback()
    assert _wait(qt_app, lambda: len(player.played) == 2)
    controller._on_playback_finished(first)  # запоздавший сигнал от уже доигранного файла
    qt_app.processEvents()
    assert len(player.played) == 2
    assert controller._current is not None and str(controller._current) == str(player.played[1])
    controller.shutdown()


def test_stop_does_not_fail_when_temp_file_is_locked(qt_app, tmp_path, monkeypatch):
    controller, engine, player = _controller(qt_app, tmp_path)
    controller.set_enabled(True)
    locked = tmp_path / "fake_1.wav"
    real_unlink = Path.unlink
    state = {"locked": True}

    def flaky_unlink(self, missing_ok=False):
        if self == locked and state["locked"]:
            raise PermissionError("файл занят плеером")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    controller._current = locked
    controller.stop()  # не должно бросать исключение
    assert locked.exists()
    state["locked"] = False
    controller.shutdown()  # повторная попытка удаления при завершении
    assert not locked.exists()


# --- голосовая модель: смена пути и блокировки ----------------------------------

class FakeVoice:
    def synthesize_wav(self, text, wav, syn_config=None):
        if FakePiperVoice.synth_delay:
            time.sleep(FakePiperVoice.synth_delay)
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * 2205)


class FakePiperVoice:
    load_calls: list[str] = []
    synth_delay = 0.0

    @classmethod
    def load(cls, model_path, config_path=None, **kwargs):
        cls.load_calls.append(model_path)
        return FakeVoice()


@pytest.fixture
def fake_piper(monkeypatch):
    import piper

    FakePiperVoice.load_calls = []
    FakePiperVoice.synth_delay = 0.0
    monkeypatch.setattr(piper, "PiperVoice", FakePiperVoice)
    return FakePiperVoice


def _voice_files(tmp_path: Path, name: str) -> Path:
    model = tmp_path / f"{name}.onnx"
    model.write_bytes(b"x")
    (tmp_path / f"{name}.onnx.json").write_text("{}", encoding="utf-8")
    return model


def test_same_model_path_keeps_loaded_voice(fake_piper, tmp_path):
    model = _voice_files(tmp_path, "a")
    engine = TTSEngine(model, tmp_path / "tmp")
    first = engine.synthesize("Первая фраза.")
    engine.set_model_path(model)  # тот же путь: модель не сбрасывается
    second = engine.synthesize("Вторая фраза.")
    assert len(fake_piper.load_calls) == 1
    for p in (first, second):
        p.unlink()


def test_changed_model_path_reloads_voice_once(fake_piper, tmp_path):
    model_a = _voice_files(tmp_path, "a")
    model_b = _voice_files(tmp_path, "b")
    engine = TTSEngine(model_a, tmp_path / "tmp")
    engine.synthesize("Раз.").unlink()
    engine.set_model_path(model_b)
    engine.synthesize("Два.").unlink()
    engine.synthesize("Три.").unlink()
    assert len(fake_piper.load_calls) == 2
    assert fake_piper.load_calls[1].endswith("b.onnx")


def test_set_model_path_does_not_wait_for_running_synthesis(fake_piper, tmp_path):
    model = _voice_files(tmp_path, "a")
    engine = TTSEngine(model, tmp_path / "tmp")
    engine.synthesize("Прогрев.").unlink()
    fake_piper.synth_delay = 0.8
    worker = threading.Thread(target=lambda: engine.synthesize("Фраза, которая долго синтезируется."))
    worker.start()
    time.sleep(0.1)
    started = time.monotonic()
    engine.set_model_path(_voice_files(tmp_path, "b"))  # GUI-поток не должен ждать синтеза
    waited = time.monotonic() - started
    worker.join()
    assert waited < 0.2


def test_empty_phrase_returns_none(fake_piper, tmp_path):
    engine = TTSEngine(_voice_files(tmp_path, "a"), tmp_path / "tmp")
    assert engine.synthesize(".") is None
    assert fake_piper.load_calls == []  # модель не загружалась ради пустой фразы
