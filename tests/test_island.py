"""Островок SIRIUS (Living Island): логика, диспетчер состояний, окно-капсула, контроллер и связь
с главным окном. Системные сервисы Windows в тестах выключены (см. conftest)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from PySide6.QtCore import QMimeData, QPoint, Qt, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from island import actions as quick
from island.clipboard import ClipboardHistory, is_private, looks_secret
from island.notifications import CRITICAL, NotificationCenter
from island.pomodoro import IDLE, LONG, PAUSED, RUNNING, SHORT, WORK, Pomodoro, format_time
from island.settings import ISLAND_DEFAULTS, normalize
from island.shelf import QuickShelf
from island.states import CRITICAL_PRIORITY, IslandState


class Clock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _pump(app, condition, timeout: float = 3.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


# --- настройки ---------------------------------------------------------------------------

def test_settings_defaults_and_validation():
    assert normalize(None) == ISLAND_DEFAULTS and normalize("мусор") == ISLAND_DEFAULTS
    cfg = normalize({"width": 99999, "height": -5, "opacity": "много", "theme": "розовая", "enabled": "да",
                     "position": "custom", "неизвестно": 1, "animation_speed": 150.7,
                     "custom_actions": [{"title": " Проект ", "target": " D:\\x "}, {"title": "", "target": "y"}, 5]})
    assert cfg["width"] == 1400 and cfg["height"] == 40 and cfg["opacity"] == ISLAND_DEFAULTS["opacity"]
    assert cfg["theme"] == "graphite" and cfg["enabled"] is True and cfg["animation_speed"] == 150
    assert cfg["position"] == "top", "своё место без координат невозможно"
    assert cfg["custom_actions"] == [{"title": "Проект", "target": "D:\\x"}] and "неизвестно" not in cfg
    assert normalize({"position": "custom", "custom_pos": [300, 40]})["position"] == "custom"


def test_old_settings_without_island_section_still_load(tmp_path):
    from storage.settings_storage import SettingsStorage
    from storage.storage_manager import atomic_write_json

    path = tmp_path / "settings.json"
    atomic_write_json(path, {"voice_volume": 55})                 # настройки до появления островка
    store = SettingsStorage(path)
    loaded = store.load()
    assert loaded["voice_volume"] == 55 and loaded["island"] == {}
    loaded["island"] = normalize({"width": 900, "theme": "black"})
    store.save(loaded)
    assert store.load()["island"]["theme"] == "black"
    atomic_write_json(path, {"island": "сломано"})
    assert store.load()["island"] == {}


# --- уведомления -------------------------------------------------------------------------

def test_notifications_priority_merge_and_spam_guard():
    clock = Clock()
    center = NotificationCenter(clock=clock)
    first = center.post("Почта", "Письмо", "Привет")
    urgent = center.post("SIRIUS", "Перегрев", "95°C", CRITICAL)
    assert center.pending() == 2 and center.next() is urgent and center.next() is first and center.next() is None
    clock.now += 5
    assert center.post("Почта", "Письмо", "Привет") is None, "повтор объединяется, а не всплывает снова"
    assert first.count == 2 and len(center.history()) == 2
    clock.now += 120
    assert center.post("Почта", "Письмо", "Привет") is not None, "через долгое время это новое уведомление"

    spam = NotificationCenter(clock=clock)
    shown = [spam.post("Чат", f"Сообщение {i}") for i in range(8)]
    assert sum(n is not None for n in shown) == 4 and len(spam.history()) == 8
    assert all(n.silent for n in spam.history()[:4])
    assert spam.post("Чат", "Важное", priority=CRITICAL) is not None, "важное проходит сквозь защиту от спама"
    assert spam.unread() == 9
    spam.mark_read()
    assert spam.unread() == 0 and spam.dismiss(spam.history()[0].id) and len(spam.history()) == 8
    spam.clear()
    assert not spam.history() and spam.pending() == 0


# --- Pomodoro ----------------------------------------------------------------------------

def test_pomodoro_full_cycle_pause_and_skip():
    clock = Clock()
    pomo = Pomodoro(work=25, short=5, long=15, rounds=2, clock=clock)
    assert pomo.state == IDLE and format_time(pomo.remaining()) == "25:00" and pomo.tick() == []
    pomo.start()
    clock.now += 10 * 60
    assert pomo.state == RUNNING and format_time(pomo.remaining()) == "15:00" and pomo.progress() == pytest.approx(0.4)
    pomo.pause()
    clock.now += 3600                                   # на паузе время не идёт
    assert pomo.state == PAUSED and format_time(pomo.remaining()) == "15:00"
    pomo.start()
    clock.now += 15 * 60
    assert pomo.tick() == ["work_done"] and pomo.phase == SHORT and pomo.state == RUNNING
    clock.now += 5 * 60
    assert pomo.tick() == ["break_done"] and pomo.phase == WORK
    assert pomo.skip() == ["work_done"] and pomo.phase == LONG, "после второго отрезка — длинный перерыв"
    clock.now += 15 * 60
    assert pomo.tick() == ["cycle_done"] and pomo.state == IDLE and pomo.rounds_done == 0
    pomo.configure(50, 10, 20, 3)
    assert format_time(pomo.remaining()) == "50:00"


def test_pomodoro_survives_restart():
    clock = Clock()
    pomo = Pomodoro(clock=clock)
    pomo.start()
    clock.now += 600
    saved = pomo.snapshot()

    clock.now += 300                                    # SIRIUS был закрыт 5 минут
    resumed = Pomodoro(clock=clock)
    assert resumed.restore(saved) == [] and resumed.state == RUNNING
    assert format_time(resumed.remaining()) == "10:00", "время шло и без SIRIUS"

    clock.now += 3600                                   # отрезок закончился, пока SIRIUS был закрыт
    late = Pomodoro(clock=clock)
    assert late.restore(saved) == ["work_done"] and late.phase == SHORT and late.state == PAUSED

    paused = Pomodoro(clock=clock)
    paused.start()
    clock.now += 60
    paused.pause()
    again = Pomodoro(clock=clock)
    assert again.restore(paused.snapshot()) == [] and again.state == PAUSED and format_time(again.remaining()) == "24:00"
    for junk in (None, {}, {"state": "running", "phase": "обед"}, {"state": "running", "phase": WORK, "ends_at": "x"}):
        assert Pomodoro(clock=clock).restore(junk) == []


# --- буфер обмена ------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Qwerty123!", "ghp_1234567890abcdefghijklmnopqrstuv", "sk-proj-abcdefghijklmnop1234",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NSJ9.abcdefghijk", "-----BEGIN RSA PRIVATE KEY-----\nabc",
    "password: hunter2secret", "пароль = МойСекрет", "5f4dcc3b5aa765d61d8327deb882cf99",
    "AKIAIOSFODNN7EXAMPLE", "Bearer abcdefghijklmnopqrstuvwxyz",
])
def test_clipboard_recognizes_secrets(text):
    assert looks_secret(text)


@pytest.mark.parametrize("text", [
    "обычная фраза с пробелами", "https://example.org/Path/Page?x=1", "C:\\Users\\Test\\File1.txt", "hello",
    "user@example.org", "QPropertyAnimation", "Python312", "2026-11-10", "12345678",
])
def test_clipboard_keeps_ordinary_text(text):
    assert not looks_secret(text)


def test_clipboard_history_limit_search_and_secrets():
    clock = Clock()
    history = ClipboardHistory(limit=3, clock=clock)
    assert history.add("   ") is None and history.add("x" * 30_000) is None
    for word in ("один", "два", "три", "четыре"):
        clock.now += 1
        history.add(word)
    assert [e.text for e in history.items()] == ["четыре", "три", "два"], "старые записи вытесняются"
    history.add("два")
    assert [e.text for e in history.items()] == ["два", "четыре", "три"], "повтор поднимается наверх без дубля"
    assert [e.text for e in history.items("ЧЕТ")] == ["четыре"]
    assert history.add("Qwerty123!") is None and history.skipped_secrets == 1
    private = ['application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"']
    assert is_private(private) and history.add("из менеджера паролей", private) is None
    history.allow_secrets = True
    assert history.add("Qwerty123!") is not None
    entry = history.items()[0]
    assert history.remove(entry.id) and not history.remove(entry.id)
    restored = ClipboardHistory(limit=2)
    restored.load(history.to_json() + [{"text": 5}, "мусор"])
    assert [e.text for e in restored.items()] == ["два", "четыре"]
    history.clear()
    assert len(history) == 0


# --- полка и действия --------------------------------------------------------------------

def test_shelf_never_touches_files(tmp_path):
    files = [tmp_path / f"f{i}.txt" for i in range(4)]
    for f in files:
        f.write_text("данные", encoding="utf-8")
    shelf = QuickShelf(limit=3)
    assert shelf.add([str(files[0]), str(files[0]), str(tmp_path / "нет.txt"), str(tmp_path)]) == 2
    assert shelf.add([str(files[1]), str(files[2])]) == 1 and shelf.is_full()
    assert shelf.remove(str(files[0])) and not shelf.remove(str(files[0]))
    shelf.clear()
    assert all(f.read_text(encoding="utf-8") == "данные" for f in files), "файлы на диске не изменились"
    shelf.add([str(files[3])])
    files[3].unlink()
    restored = QuickShelf()
    restored.load(shelf.to_json() + ["относительный.txt", 7])
    assert len(restored) == 1 and not restored.items()[0].exists, "пропавший файл остаётся с пометкой"


def test_quick_actions_validation(tmp_path, monkeypatch):
    assert quick.validate_target("") and quick.validate_target("ftp://host/x") and quick.validate_target("notes.txt")
    assert quick.validate_target(str(tmp_path / "нет")) and quick.validate_target("javascript://x")
    assert quick.validate_target("https://example.org") is None and quick.validate_target(str(tmp_path)) is None
    opened = []
    monkeypatch.setattr(quick.os, "startfile", opened.append, raising=False)
    assert quick.launch_target(str(tmp_path))[0] and opened == [str(tmp_path)]
    assert not quick.launch_target("cmd /c del x")[0] and len(opened) == 1, "команды не выполняются"
    custom = quick.custom_actions([{"title": "Сайт", "target": "https://example.org"}, {"title": "", "target": "x"}])
    assert [a.id for a in custom] == ["custom:0"] and custom[0].custom and custom[0].icon == "link"


# --- диспетчер состояний -----------------------------------------------------------------

@pytest.fixture
def states(qt_app):
    from interface.island.state_manager import IslandStateManager

    manager = IslandStateManager()
    manager.log = []
    manager.changed.connect(lambda state, payload: manager.log.append(state))
    return manager


def test_state_manager_open_close_and_pin(states):
    assert states.state is IslandState.COMPACT
    assert not states.open(IslandState.VOLUME), "событие нельзя открыть как постоянное состояние"
    assert states.open(IslandState.MEDIA) and states.state is IslandState.MEDIA and states._idle.isActive()
    states.set_pinned(True)
    assert not states._idle.isActive(), "закреплённое состояние не сворачивается само"
    states.toggle(IslandState.SYSTEM)
    assert states.base is IslandState.SYSTEM
    states.toggle(IslandState.SYSTEM)
    assert states.state is IslandState.COMPACT and not states.pinned
    states.open(IslandState.EXPANDED)
    states._on_idle()
    assert states.state is IslandState.COMPACT, "без действий пользователя островок сворачивается"
    states.open(IslandState.EXPANDED)
    states.set_busy(True)
    assert not states._idle.isActive(), "пока LISA отвечает, ответ остаётся на экране"
    states.set_busy(False)
    assert states._idle.isActive()
    states.enabled = False
    states.close()
    assert not states.open(IslandState.MEDIA) and not states.flash(IslandState.VOLUME)


def test_state_manager_transient_priority_and_return(states):
    finished = []
    states.transient_finished.connect(finished.append)
    states.open(IslandState.MEDIA)
    assert states.flash(IslandState.VOLUME, {"p": 1}, 5000) and states.state is IslandState.VOLUME
    assert states.flash(IslandState.NOTIFICATION, "n", 5000) and finished == [IslandState.VOLUME]
    assert not states.flash(IslandState.VOLUME, None, 5000), "громкость не вытесняет уведомление"
    assert not states.flash(IslandState.BATTERY) and states.payload == "n"
    assert states.flash(IslandState.NOTIFICATION, "важное", 5000, CRITICAL_PRIORITY)
    assert not states.flash(IslandState.NOTIFICATION, "обычное", 5000), "обычное уведомление ждёт важное"
    states._on_flash_done()
    assert states.state is IslandState.MEDIA and finished[-1] is IslandState.NOTIFICATION, "возврат к прежнему состоянию"
    states.flash(IslandState.BRIGHTNESS, None, 5000)
    states.hold(True)
    assert not states._flash.isActive(), "под курсором событие не исчезает"
    states.hold(False)
    assert states._flash.isActive()
    states.close()
    assert states.state is IslandState.COMPACT and states.transient is None


# --- окно-капсула ------------------------------------------------------------------------

@pytest.fixture
def bar(qt_app):
    from interface.compact_bar import CompactBar

    widget = CompactBar(config={"animations": False})
    widget.place_on_screen()
    widget.show()
    qt_app.processEvents()
    widget.states.hold(False)        # в тестах курсор стоит в углу экрана — прямо над островком
    yield widget
    widget.close()
    widget.deleteLater()


def test_bar_keeps_compact_mode_interface(bar, qt_app):
    from interface.avatar_widget import AvatarState

    sent, expanded, voice, avatar = [], [], [], []
    bar.send_requested.connect(sent.append)
    bar.expand_requested.connect(lambda: expanded.append(1))
    bar.voice_toggled.connect(voice.append)
    bar.avatar_clicked.connect(lambda: avatar.append(1))
    flags = bar.windowFlags()
    assert flags & Qt.WindowType.FramelessWindowHint and flags & Qt.WindowType.WindowStaysOnTopHint
    assert bar.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert bar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    bar.input.setText("  привет  ")
    bar.input.returnPressed.emit()
    assert sent == ["привет"] and bar.input.text() == ""
    QTest.mouseClick(bar.lisa, Qt.MouseButton.LeftButton)
    bar.expand_btn.click()
    bar.set_voice(True)
    assert bar.voice_btn.text() == "VOICE ON" and voice == [], "set_voice не порождает сигнал"
    bar.voice_btn.click()
    assert avatar == [1] and expanded == [1] and voice == [False]
    bar.set_state(AvatarState.THINKING)
    bar.set_mood("hot")
    assert bar.lisa.state is AvatarState.THINKING and bar.lisa.mood == "hot"
    bar.set_busy(True)
    assert not bar.input.isEnabled()
    bar.begin_reply()
    bar.append_reply("Привет, ")
    bar.append_reply("я LISA")
    assert bar.reply_text() == "Привет, я LISA" and "LISA" in bar.reply.text()
    bar.set_busy(False)
    assert bar.input.isEnabled()
    bar.set_metrics({"cpu": 33, "ram": 95, "gpu": None, "vram": 10, "gpu_temp": 60})
    assert "33%" in bar.metrics.text() and "60°C" in bar.metrics.text()


def test_bar_expands_and_collapses_per_state(bar, qt_app):
    compact = bar.geometry()
    assert compact.height() == bar._row_h + 8 and not bar.body.isVisible()
    pages = {IslandState.EXPANDED: bar.hub, IslandState.MEDIA: bar.media_view, IslandState.SYSTEM: bar.system_view,
             IslandState.NOTIFICATION: bar.notes_list, IslandState.INTERACTIVE: bar.tools}
    for state, page in pages.items():
        assert bar.states.open(state)
        assert bar.pages.currentWidget() is page and bar.nav.isVisible() and bar.body.isVisible()
        assert bar.geometry().height() == bar._row_h + 8 + bar.nav.HEIGHT + page.HEIGHT + 14
        assert bar.geometry().top() == compact.top() and bar.geometry().center().x() == compact.center().x()
        assert bar.row.geometry().height() == bar._row_h, "строка капсулы не меняется при раскрытии"
    assert bar.states.flash(IslandState.VOLUME, None, 5000)
    assert bar.pages.currentWidget() is bar.indicator and not bar.nav.isVisible()
    assert bar.geometry().height() == bar._row_h + 8 + bar.indicator.HEIGHT + 14
    bar.states.dismiss_transient()
    assert bar.pages.currentWidget() is bar.tools, "после события возвращается прежний режим"
    bar.states.close()
    assert bar.geometry() == compact and not bar.body.isVisible()
    for transient, page in ((IslandState.NOTIFICATION, bar.toast), (IslandState.SYSTEM, bar.indicator),
                            (IslandState.BATTERY, bar.indicator), (IslandState.BRIGHTNESS, bar.indicator)):
        bar.states.flash(transient, None, 5000, 100)
        assert bar.pages.currentWidget() is page
    bar.states.close()


def test_bar_controls_open_states_and_escape_collapses(bar, qt_app):
    escaped = []
    bar.expand_requested.connect(lambda: escaped.append(1))
    bar.menu_btn.click()
    assert bar.states.base is IslandState.EXPANDED
    bar.nav.chips[IslandState.MEDIA].click()
    assert bar.states.base is IslandState.MEDIA
    bar.nav.pin_btn.click()
    assert bar.states.pinned
    bar._on_escape()
    assert bar.states.state is IslandState.COMPACT and escaped == [], "Esc сначала сворачивает островок"
    bar._on_escape()
    assert escaped == [1], "в компактном состоянии Esc возвращает полное окно"
    QTest.mouseClick(bar.metrics, Qt.MouseButton.LeftButton)
    assert bar.states.base is IslandState.SYSTEM
    bar.menu_btn.click()
    assert bar.states.state is IslandState.COMPACT


def test_bar_animated_transitions_settle(qt_app):
    from interface.compact_bar import CompactBar

    bar = CompactBar(config={"animation_speed": 200})
    bar.place_on_screen()
    bar.show()
    qt_app.processEvents()
    bar.states.hold(False)
    compact = bar.geometry()
    bar.states.open(IslandState.MEDIA)
    bar.states.open(IslandState.SYSTEM)                # несколько событий подряд, пока идёт анимация
    bar.states.flash(IslandState.VOLUME, None, 5000)
    bar.states.open(IslandState.INTERACTIVE)
    target = bar._row_h + 8 + bar.nav.HEIGHT + bar.tools.HEIGHT + 14
    assert _pump(qt_app, lambda: bar.geometry().height() == target and bar._fx.opacity() > 0.99
                 and not bar.animator.is_morphing())
    assert bar.pages.currentWidget() is bar.tools
    bar.states.close()
    assert _pump(qt_app, lambda: bar.geometry() == compact and not bar.body.isVisible())
    bar.close()


def test_bar_config_position_size_and_classic_mode(qt_app):
    from interface.compact_bar import MARGIN, CompactBar

    bar = CompactBar(config={"animations": False, "height": 56, "width": 700, "position": "bottom"})
    bar.place_on_screen()
    bar.show()
    qt_app.processEvents()
    bar.states.hold(False)
    area = bar.screen().availableGeometry()
    assert bar.geometry().height() == 56 + 2 * MARGIN and bar.geometry().width() == 700 + 2 * MARGIN
    bottom = bar.geometry().bottom()
    assert area.bottom() - bottom < 12, "островок у нижнего края"
    bar.states.open(IslandState.MEDIA)
    assert bar.geometry().bottom() == bottom, "у нижнего края капсула раскрывается вверх"
    assert bar.row.geometry().top() > bar.body.geometry().top()
    cfg = bar.config()
    cfg.update(position="top-right", enabled=False)
    bar.apply_config(cfg)
    assert bar.states.state is IslandState.COMPACT and not bar.states.open(IslandState.MEDIA)
    assert bar.menu_btn.isHidden() and area.right() - bar.geometry().right() < 12
    cfg.update(enabled=True, media=False, shelf=False, clipboard=False, pomodoro=False, actions=False,
               notifications=False)
    bar.apply_config(cfg)
    assert bar.nav.chips[IslandState.MEDIA].isHidden() and bar.nav.chips[IslandState.INTERACTIVE].isHidden()
    assert bar.nav.chips[IslandState.NOTIFICATION].isHidden() and not bar.nav.chips[IslandState.SYSTEM].isHidden()
    bar.close()


def test_bar_drag_remembers_position(qt_app):
    from interface.compact_bar import CompactBar

    bar = CompactBar(config={"animations": False, "width": 640})     # уже экрана: есть куда двигать
    bar.place_on_screen()
    bar.show()
    qt_app.processEvents()
    bar.states.hold(False)
    moved = []
    bar.position_changed.connect(moved.append)
    start = bar.geometry()
    free = QPoint(bar.reply.geometry().center().x(), bar.height() // 2)      # свободное место строки
    QTest.mousePress(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, free)
    QTest.mouseMove(bar, free + QPoint(-60, 90))
    QTest.mouseRelease(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, free + QPoint(-60, 90))
    assert moved and moved[0]["position"] == "custom"
    assert bar.geometry().top() == start.top() + 90 and bar.geometry().left() == start.left() - 60
    assert bar.config()["custom_pos"] == moved[0]["custom_pos"]
    bar.states.open(IslandState.SYSTEM)
    assert bar.geometry().top() == start.top() + 90, "раскрытие идёт от нового места"
    QTest.mouseClick(bar, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, free)
    assert len(moved) == 1, "щелчок без движения положение не меняет"
    bar.close()


def test_bar_row_never_overflows(qt_app):
    from interface.compact_bar import CompactBar
    from monitoring.winrt_bridge import MediaInfo

    bar = CompactBar(config={"animations": False, "width": 640})
    bar.place_on_screen()
    bar.show()
    bar.set_voice(False)
    bar.set_metrics({"cpu": 100, "gpu": 100, "ram": 100, "vram": 100, "gpu_temp": 100})
    assert "VRAM" not in bar.metrics.text() and "CPU" in bar.metrics.text(), "на узкой капсуле метрики короче"
    bar.set_media(MediaInfo("x.exe", "X", "Очень длинное название композиции", "Исполнитель", "", "playing",
                            1.0, 100.0, time.time()))
    bar.set_pomodoro("24:59")
    bar.set_unread(3)
    qt_app.processEvents()
    visible = [w for w in (bar.lisa, bar.input, bar.media_chip, bar.pomo_chip, bar.bell_btn, bar.metrics,
                           bar.voice_btn, bar.menu_btn, bar.expand_btn) if not w.isHidden()]
    assert bar.input.width() >= bar.input.minimumWidth()
    assert all(w.geometry().right() <= bar.row.width() for w in visible), "ничто не выходит за капсулу"
    assert bar.media_chip.isVisible() and bar.pomo_chip.isVisible()
    bar.set_media(None)
    bar.set_pomodoro(None)
    wide = bar.config()
    wide["width"] = 780
    bar.apply_config(wide)
    qt_app.processEvents()
    assert all(w.geometry().right() <= bar.row.width() for w in visible if not w.isHidden())
    assert bar.media_chip.isHidden() and bar.pomo_chip.isHidden()
    bar.close()


# --- контроллер --------------------------------------------------------------------------

@pytest.fixture
def island(qt_app, tmp_path):
    from interface.compact_bar import CompactBar
    from interface.island.controller import IslandController

    controller = IslandController(tmp_path, {"animations": False})
    widget = CompactBar(config=controller.cfg)
    controller.attach(widget)
    widget.place_on_screen()
    widget.show()
    qt_app.processEvents()
    widget.states.hold(False)
    yield controller
    controller.shutdown()
    widget.close()
    widget.deleteLater()


def test_controller_notifications_queue_toast_and_journal(island, qt_app):
    bar = island.bar
    island.notify("SIRIUS", "Первое", "текст")
    island.notify("Почта", "Второе", "текст")
    assert bar.states.state is IslandState.NOTIFICATION and bar.pages.currentWidget() is bar.toast
    assert bar.toast._row.title.full_text() == "Первое" and island.center.pending() == 1
    assert not bar.bell_btn.isHidden() and bar.bell_btn._badge == 2
    island.notify("SIRIUS", "Перегрев", "95°C", critical=True)
    assert bar.toast._row.title.full_text() == "Перегрев", "важное уведомление показывается немедленно"
    bar.toast._row.close_btn.click()                    # ручное закрытие
    assert _pump(qt_app, lambda: bar.states.state is IslandState.NOTIFICATION
                 and bar.toast._row.title.full_text() == "Второе"), "после закрытия показывается следующее"
    bar.toast._row.clicked.emit(0)                      # щелчок открывает журнал
    assert bar.states.base is IslandState.NOTIFICATION and bar.pages.currentWidget() is bar.notes_list
    assert bar.notes_list.count() == 2 and island.center.unread() == 0 and bar.bell_btn.isHidden()
    island.notify("Чат", "Пока журнал открыт")
    assert bar.states.transient is None and bar.notes_list.count() == 3, "в открытом журнале новое видно сразу"
    bar.notes_list.clear_btn.click()
    assert bar.notes_list.count() == 0 and not island.center.history()
    island.apply_settings({"animations": False, "notifications": False})
    island.notify("SIRIUS", "Выключено")
    assert not island.center.history(), "уведомления SIRIUS выключены в настройках"
    island.notify("Почта", "От Windows", source="windows")
    assert len(island.center.history()) == 1


def test_controller_media_chip_popup_and_commands(island, qt_app):
    from monitoring.winrt_bridge import MediaInfo

    bar = island.bar
    island._active = True
    commands = []

    class Bridge:
        def command(self, name, value=None):
            commands.append((name, value))

        def stop(self):
            pass

    island._bridge = Bridge()
    assert bar.media_chip.isHidden()
    track = MediaInfo("spotify.exe", "Spotify", "Песня", "Группа", "Альбом", "playing", 30.0, 200.0, time.time(),
                      None, True, True, False, True)
    island._on_media(track)
    assert not bar.media_chip.isHidden() and "Песня — Группа" in bar.media_text.full_text()
    assert bar.states.state is IslandState.COMPACT, "то, что уже играло, не всплывает"
    bar.media_chip.clicked.emit()
    assert bar.states.base is IslandState.MEDIA and bar.media_view.title.full_text() == "Песня"
    assert bar.media_view.duration.text() == "3:20" and bar.media_view.position.text() in ("0:30", "0:31")
    assert bar.media_view.next_btn.isEnabled() and not bar.media_view.prev_btn.isEnabled()
    bar.media_view.play_btn.click()
    bar.media_view.next_btn.click()
    bar.media_view.bar.sought.emit(0.5)
    assert commands == [("toggle", None), ("next", None), ("seek", 100.0)]
    bar.states.close()
    import dataclasses

    island._on_media(dataclasses.replace(track, title="Новая песня"))
    island._media_popup()
    assert bar.states.state is IslandState.MEDIA and bar.states.transient is IslandState.MEDIA, "новый трек всплывает"
    bar.states.close()
    island._on_media(dataclasses.replace(track, title="Новая песня", status="paused"))
    assert bar.media_view.play_btn._glyph == "play"
    island._on_media(None)
    assert bar.media_chip.isHidden() and "ничего не воспроизводится" in bar.media_view.title.full_text()
    assert bar.media_view.play_btn.isHidden()


def test_media_info_live_position_and_app_names():
    from monitoring.winrt_bridge import MediaInfo, app_title

    info = MediaInfo("a", "A", "t", "", "", "playing", 10.0, 60.0, 100.0)
    assert info.live_position(105.0) == 15.0 and info.live_position(1000.0) == 60.0
    paused = MediaInfo("a", "A", "t", "", "", "paused", 10.0, 60.0, 100.0)
    assert paused.live_position(500.0) == 10.0
    assert app_title("Spotify.exe") == "Spotify" and app_title("chrome.exe") == "Google Chrome"
    assert app_title("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify") == "Spotify"
    assert app_title("C:\\Apps\\MyPlayer.exe") == "MyPlayer" and app_title("") == "Медиа"


def test_controller_pomodoro_runs_without_island_and_notifies(qt_app, tmp_path):
    from interface.island.controller import IslandController

    controller = IslandController(tmp_path, None)       # окна островка нет вообще
    clock = Clock(time.time())
    controller.pomodoro._clock = clock
    controller.pomodoro_start()
    assert controller.pomodoro.state == RUNNING and controller._pomo_timer.isActive()
    clock.now += 25 * 60 + 1
    controller._pomo_tick()
    assert controller.pomodoro.phase == SHORT
    assert [n.title for n in controller.center.history()] == ["Рабочий отрезок завершён"]
    controller.shutdown()

    restored = IslandController(tmp_path, None)         # перезапуск SIRIUS
    assert restored.pomodoro.phase == SHORT and restored.pomodoro.state == RUNNING
    restored.pomodoro_reset()
    assert not restored._pomo_timer.isActive()
    restored.shutdown()
    off = IslandController(tmp_path, {"pomodoro_restore": False})
    off.pomodoro_start()
    off.shutdown()
    assert IslandController(tmp_path, {"pomodoro_restore": False}).pomodoro.state == IDLE


def test_controller_pomodoro_page_and_chip(island, qt_app):
    bar = island.bar
    bar.open_tool("pomodoro")
    page = bar.tools.pomodoro
    assert bar.pomo_chip.isHidden() and page.main_btn.text() == "Старт" and not page.skip_btn.isEnabled()
    page.main_btn.click()
    assert island.pomodoro.state == RUNNING and not bar.pomo_chip.isHidden() and page.main_btn.text() == "Пауза"
    assert bar.pomo_text.text() in ("25:00", "24:59") and page.time.text() in ("25:00", "24:59")
    page.main_btn.click()
    assert island.pomodoro.state == PAUSED and page.main_btn.text() == "Продолжить"
    page.skip_btn.click()
    assert island.pomodoro.phase == SHORT and "перерыв" in page.phase.text().lower()
    page.reset_btn.click()
    assert island.pomodoro.state == IDLE and bar.pomo_chip.isHidden()


def test_controller_clipboard_history(island, qt_app):
    bar = island.bar
    clipboard = QGuiApplication.clipboard()
    bar.open_tool("clipboard")
    page = bar.tools.clipboard
    for text in ("первая запись", "вторая запись", "Qwerty123!"):
        clipboard.setText(text)
        qt_app.processEvents()
    assert [e.text for e in island.clipboard.items()] == ["вторая запись", "первая запись"]
    assert page.list.count() == 2 and "пароль" in page.status.text()
    page.search.setText("перв")
    assert page.list.count() == 1
    page.search.clear()
    first = island.clipboard.items()[-1]
    page.copy_requested.emit(first.id)
    qt_app.processEvents()
    assert clipboard.text() == "первая запись" and island.clipboard.items()[0].text == "первая запись"
    page.remove_requested.emit(first.id)
    assert page.list.count() == 1
    page.clear_btn.click()
    assert page.list.count() == 0 and len(island.clipboard) == 0
    island.apply_settings({"animations": False, "clipboard": False})
    clipboard.setText("после отключения")
    qt_app.processEvents()
    assert len(island.clipboard) == 0, "выключенная история ничего не запоминает"


def test_controller_shelf_drop_open_and_persist(island, qt_app, tmp_path, monkeypatch):
    from interface.island.controller import IslandController

    bar = island.bar
    files = [tmp_path / "отчёт.txt", tmp_path / "фото.png"]
    for f in files:
        f.write_bytes(b"data")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(f)) for f in files] + [QUrl("https://example.org/x")])
    assert bar._local_files(mime) == [str(Path(f)) for f in files] or len(bar._local_files(mime)) == 2
    bar.files_dropped.emit(bar._local_files(mime))
    page = bar.tools.shelf
    assert bar.states.base is IslandState.INTERACTIVE and bar.tools.current_tab() == "shelf"
    assert page.list.count() == 2 and len(island.shelf) == 2
    opened = []
    monkeypatch.setattr(quick.os, "startfile", opened.append, raising=False)
    page.list.setCurrentRow(0)
    page.list.item(0).setSelected(True)
    page.open_btn.click()
    assert len(opened) == 1 and Path(opened[0]).name == "отчёт.txt"
    page.remove_btn.click()
    assert page.list.count() == 1 and all(f.exists() for f in files), "файл остаётся на диске"
    island._save()
    again = IslandController(tmp_path, None)
    assert [Path(i.path).name for i in again.shelf.items()] == ["фото.png"]
    again.shutdown()
    page.clear_btn.click()
    assert page.list.count() == 0 and all(f.exists() for f in files)


def test_controller_actions_and_battery_events(island, qt_app, tmp_path, monkeypatch):
    from monitoring.system_info import BatteryInfo, SystemSnapshot

    bar = island.bar
    requested, opened = [], []
    island.action_requested.connect(requested.append)
    monkeypatch.setattr(quick.os, "startfile", opened.append, raising=False)
    island.apply_settings({"animations": False, "custom_actions": [{"title": "Папка", "target": str(tmp_path)}]})
    assert [a.id for a in island.actions()][-1] == "custom:0"
    island.run_action("settings")
    island.run_action("custom:0")
    island.run_action("explorer")
    island.run_action("нет такого")
    assert requested == ["settings"] and opened == [str(tmp_path), str(Path.home())]
    assert "открыт" in bar.tools.actions.status.text().lower()

    snapshot = SystemSnapshot.__dataclass_fields__
    assert "battery" in snapshot

    def snap(plugged: bool):
        import dataclasses

        base = _snapshot()
        return dataclasses.replace(base, battery=BatteryInfo(64.0, plugged, None if plugged else 5400))

    island.on_snapshot(snap(True))
    assert bar.states.state is IslandState.COMPACT, "первый снимок — не событие"
    island.on_snapshot(snap(False))
    assert bar.states.state is IslandState.BATTERY and bar.indicator.title.text() == "От аккумулятора"
    assert "1 ч 30 мин" in bar.indicator.detail.full_text() and bar.indicator.value.text() == "64%"
    bar.states.dismiss_transient()
    bar.states.open(IslandState.SYSTEM)
    assert "64%" in bar.system_view.lines["battery"].full_text()


def _snapshot():
    from tests.test_monitoring_v03 import snap

    return snap(cpu=10)


def test_controller_level_indicators(island, qt_app):
    bar = island.bar
    island._show_volume(42, False)
    assert bar.states.state is IslandState.VOLUME and bar.indicator.value.text() == "42%"
    assert bar.indicator.title.text() == "Громкость" and bar.indicator.bar.value == pytest.approx(0.42)
    island._show_volume(0, True)
    assert bar.indicator.title.text() == "Без звука"
    island._show_brightness(80)
    assert bar.states.state is IslandState.BRIGHTNESS and bar.indicator.value.text() == "80%"
    bar.states.dismiss_transient()
    island._show_lock("Caps Lock", True)
    assert bar.states.state is IslandState.SYSTEM and bar.indicator.value.text() == "включён"
    assert bar.pages.currentWidget() is bar.indicator
    island.notify("SIRIUS", "Важнее")
    island._show_volume(50, False)
    assert bar.states.state is IslandState.NOTIFICATION, "индикатор громкости не перебивает уведомление"


# --- главное окно ------------------------------------------------------------------------

@pytest.fixture
def window(qt_app, tmp_path, monkeypatch):
    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    yield win
    win._quitting = True
    win.close()


def test_window_routes_alerts_and_lisa_to_island(window, qt_app):
    from interface.avatar_widget import AvatarState
    from monitoring.alerts import Alert

    window.show()
    assert window.island is not None and window.compact_bar is None, "окно островка создаётся при первом показе"
    window._on_alert(Alert("vram", "Видеопамять", "занято 95%", True))
    assert [n.title for n in window.island.center.history()] == ["Видеопамять"], "журнал ведётся и без островка"
    window.enter_compact()
    bar = window.compact_bar
    qt_app.processEvents()
    bar.states.hold(False)
    assert _pump(qt_app, lambda: bar.states.state is IslandState.NOTIFICATION), "пропущенное важное показано"
    assert bar.toast._row.title.full_text() == "Видеопамять"
    bar.states.close()
    window._on_alert(Alert("ram", "Память", "занято 97%", False))
    assert bar.states.state is IslandState.NOTIFICATION and bar.toast._row.title.full_text() == "Память"
    bar.states.close()
    bar._asked_here = True                               # вопрос задан в островке
    bar.begin_reply()
    bar.set_busy(True)
    assert bar.states.base is IslandState.EXPANDED, "ответ LISA раскрывается в островке"
    bar.append_reply("Ответ LISA")
    assert "Ответ LISA" in bar.hub.reply.text() and not bar.states._idle.isActive()
    bar.states.hold(False)
    bar.set_busy(False)
    assert bar.states._idle.isActive()
    bar.states.close()
    bar.set_state(AvatarState.ERROR)
    assert bar.states.state is IslandState.SYSTEM and bar.indicator.value.text() == "ошибка"
    assert "ошибка" in bar.hub.status.text()
    window.leave_compact()
    assert not bar.isVisible() and bar.states.state is IslandState.COMPACT


def test_window_island_actions(window, qt_app, monkeypatch):
    window.show()
    window.enter_compact()
    opened = []
    monkeypatch.setattr(window, "_open_settings", lambda: opened.append(1))
    voice = window.voice.enabled
    window.island.run_action("heavy")
    assert window.heavy_mode
    window.island.run_action("heavy")
    window.island.run_action("voice")
    assert window.voice.enabled != voice or window._voice_error, "голос переключён (или недоступен в тестах)"
    window.island.run_action("open_sirius")
    assert not window.compact and window.isVisible()
    window.island.run_action("settings")
    assert _pump(qt_app, lambda: opened == [1])


def test_window_island_settings_roundtrip(window, qt_app):
    from interface.settings_panel import SettingsDialog

    dialog = SettingsDialog(window.settings, window)
    tab = dialog.island_tab
    assert tab.checks["enabled"].isChecked() and not tab.checks["show_always"].isChecked()
    tab.checks["show_always"].setChecked(True)
    tab.spins["width"].setValue(1000)
    tab.sliders["opacity"].setValue(70)
    tab.combos["theme"].setCurrentIndex(tab.combos["theme"].findData("black"))
    tab.combos["position"].setCurrentIndex(tab.combos["position"].findData("bottom"))
    tab._add_action_item("Сайт", "https://example.org")
    values = dialog.values()
    assert values["island"]["width"] == 1000 and values["island"]["theme"] == "black"
    window.show()
    window._apply_settings(values)
    bar = window.compact_bar
    assert bar is not None and bar.isVisible() and window.isVisible(), "островок показан вместе с главным окном"
    assert bar.config()["opacity"] == 70 and bar.config()["position"] == "bottom"
    assert window.island.actions()[-1].title == "Сайт"
    assert window.settings_store.load()["island"]["show_always"] is True, "настройки островка сохранены"
    window.enter_compact()
    window.leave_compact()
    assert bar.isVisible(), "в режиме «показывать всегда» островок остаётся на экране"
    bar.position_changed.emit({"position": "custom", "custom_pos": [400, 300], "screen": ""})
    assert window.settings_store.load()["island"]["custom_pos"] == [400, 300], "место после перетаскивания сохранено"
    values = dict(window.settings)
    values["island"] = dict(values["island"], show_always=False)
    window._apply_settings(values)
    assert not bar.isVisible()
    dialog.deleteLater()
