"""Контроллер островка: связывает окно-капсулу (interface/compact_bar.py) с данными и сервисами.

Владеет логикой островка (уведомления, Pomodoro, буфер обмена, полка, действия) и системными
сервисами (громкость, яркость, клавиши, медиа и уведомления Windows). Окно островка само ничего
не опрашивает и не хранит: контроллер приносит ему данные и просит диспетчер состояний показать событие.

Что работает всегда: Pomodoro, история буфера обмена, журнал уведомлений SIRIUS — им не нужен
видимый островок. Что работает только пока островок на экране: медиа, уведомления Windows,
опрос громкости, яркости и клавиш, уровень звука для визуализатора.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from interface.styles import CYAN, TEXT_SECONDARY
from island import actions as quick
from island.clipboard import ClipboardHistory
from island.notifications import CRITICAL, NORMAL, NotificationCenter
from island.pomodoro import IDLE, PHASE_TITLES, RUNNING, Pomodoro, format_time
from island.settings import normalize
from island.shelf import QuickShelf
from island.states import CRITICAL_PRIORITY, IslandState
from monitoring.history import snapshot_values
from storage.island_storage import IslandStorage

log = logging.getLogger("sirius.island")

EVENTS_IDLE_MS = 300          # опрос громкости, яркости и клавиш в покое
EVENTS_ACTIVE_MS = 60         # пока пользователь крутит громкость — чаще, чтобы шкала шла плавно
EVENTS_ACTIVE_SECONDS = 2.5
DEVICE_RECHECK_TICKS = 30     # раз в ~9 с проверяем, не сменилось ли устройство вывода звука
METER_MS = 40                 # уровень звука для визуализатора: 25 раз в секунду
LEVEL_TIMEOUT_MS = 1800
MEDIA_POPUP_MS = 4000
CONNECTIVITY_MS = 10_000
WEATHER_MS = 20 * 60 * 1000       # погода обновляется раз в 20 минут, пока островок виден
STALE_NOTE_SECONDS = 60


class IslandController(QObject):
    action_requested = Signal(str)       # встроенное быстрое действие — выполняет главное окно
    settings_patch = Signal(dict)        # изменения настроек островка, которые нужно сохранить
    status_message = Signal(str)

    SYSTEM_SERVICES = True               # тесты выключают: без потоков WinRT и обращения к устройствам

    _media_ready = Signal(object)        # из потока WinRT в поток интерфейса
    _notes_ready = Signal(object)
    _bridge_status = Signal(str, str)
    _connectivity_ready = Signal(object, object)
    _weather_ready = Signal(object, str)   # ((место, погода) или None, причина ошибки)

    def __init__(self, base_dir: Path, settings: Any = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.cfg = normalize(settings)
        self.bar = None
        self.storage = IslandStorage(Path(base_dir) / "storage" / "island.json")
        self.center = NotificationCenter()
        self.pomodoro = Pomodoro(self.cfg["pomodoro_work"], self.cfg["pomodoro_short"], self.cfg["pomodoro_long"],
                                 self.cfg["pomodoro_rounds"])
        self.clipboard = ClipboardHistory(self.cfg["clipboard_limit"], self.cfg["clipboard_allow_secrets"])
        self.shelf = QuickShelf(self.cfg["shelf_limit"])
        self._active = False
        self._closed = False
        self._media = None
        self._media_primed = False
        self._popped_key: tuple | None = None
        self._bridge = None
        self._audio = None
        self._brightness = None
        self._volume: tuple[float, bool] | None = None
        self._bright: int | None = None
        self._locks: dict | None = None
        self._battery = None
        self._values: dict = {}
        self._events_tick = 0
        self._fast_until = 0.0
        self._toast_id: int | None = None
        self._toast_critical = False
        self._probing = False
        self._clipboard_connected = False
        self._notes_hint = ""
        self._warned_winrt = False
        self._weather = None
        self._weather_hint = ""
        self._weather_place: tuple | None = None     # (город из настроек, широта, долгота, название)
        self._weather_busy = False

        self._pomo_timer = self._timer(1000, self._pomo_tick)
        self._events_timer = self._timer(EVENTS_IDLE_MS, self._poll_events)
        self._meter_timer = self._timer(METER_MS, self._poll_meter)
        self._sys_timer = self._timer(CONNECTIVITY_MS, self._probe_connectivity)
        self._save_timer = self._timer(1500, self._save, single=True)
        self._pump_timer = self._timer(350, self._pump_notes, single=True)
        self._media_pop_timer = self._timer(450, self._media_popup, single=True)
        self._weather_timer = self._timer(WEATHER_MS, self._fetch_weather)

        self._media_ready.connect(self._on_media)
        self._notes_ready.connect(self._on_win_notes)
        self._bridge_status.connect(self._on_bridge_status)
        self._connectivity_ready.connect(self._on_connectivity)
        self._weather_ready.connect(self._on_weather)

        self._load()
        self._sync_clipboard()

    def _timer(self, ms: int, slot, single: bool = False) -> QTimer:
        timer = QTimer(self)
        timer.setInterval(ms)
        timer.setSingleShot(single)
        timer.timeout.connect(slot)
        return timer

    # --- хранение --------------------------------------------------------------------

    def _load(self) -> None:
        data = self.storage.load()
        self.shelf.load(data.get("shelf"))
        if self.cfg["clipboard_persist"]:
            self.clipboard.load(data.get("clipboard"))
        if self.cfg["pomodoro"] and self.cfg["pomodoro_restore"]:
            for event in self.pomodoro.restore(data.get("pomodoro")):
                self._pomo_event(event, offline=True)
        if self.pomodoro.state == RUNNING:
            self._pomo_timer.start()

    def _save(self) -> None:
        data: dict[str, Any] = {"shelf": self.shelf.to_json()}
        if self.cfg["pomodoro_restore"]:
            data["pomodoro"] = self.pomodoro.snapshot()
        if self.cfg["clipboard_persist"]:
            data["clipboard"] = self.clipboard.to_json()
        self.storage.save(data)

    def _schedule_save(self) -> None:
        if not self._closed:
            self._save_timer.start()

    # --- окно островка ---------------------------------------------------------------

    def attach(self, bar) -> None:
        """Подключает окно островка. Вызывается один раз, когда окно создано."""
        self.bar = bar
        bar.apply_config(self.cfg)
        bar.visibility_changed.connect(self._on_visibility)
        bar.position_changed.connect(self._on_position)
        bar.files_dropped.connect(self.add_files)
        bar.states.changed.connect(self._on_state_changed)
        bar.states.transient_finished.connect(self._on_transient_finished)
        bar.media_view.command.connect(self._media_command)
        bar.media_view.volume_changed.connect(self._set_volume)
        bar.control.triggered.connect(self.run_action)
        bar.weather_view.city_submitted.connect(self._set_city)
        bar.toast.dismissed.connect(self.dismiss_note)
        bar.notes_list.dismissed.connect(self.dismiss_note)
        bar.notes_list.cleared.connect(self.clear_notes)
        bar.hub.action_triggered.connect(self.run_action)
        tools = bar.tools
        tools.shelf.open_requested.connect(self._open_path)
        tools.shelf.reveal_requested.connect(self._reveal_path)
        tools.shelf.remove_requested.connect(self._remove_from_shelf)
        tools.shelf.clear_requested.connect(self.clear_shelf)
        tools.clipboard.copy_requested.connect(self._copy_again)
        tools.clipboard.remove_requested.connect(self._remove_clip)
        tools.clipboard.clear_requested.connect(self.clear_clipboard)
        tools.clipboard.query_changed.connect(lambda _text: self._refresh_clipboard())
        tools.pomodoro.start_requested.connect(self.pomodoro_start)
        tools.pomodoro.pause_requested.connect(self.pomodoro_pause)
        tools.pomodoro.skip_requested.connect(self.pomodoro_skip)
        tools.pomodoro.reset_requested.connect(self.pomodoro_reset)
        self._refresh_all()
        if bar.isVisible():
            self._on_visibility(True)

    def _visible(self) -> bool:
        return self.bar is not None and self.bar.isVisible() and self.cfg["enabled"]

    def shows_notifications(self) -> bool:
        """Островок сейчас на экране и сам покажет уведомление SIRIUS (значок в трее может молчать)."""
        return self._visible() and self.cfg["notifications"]

    def _refresh_all(self) -> None:
        if self.bar is None:
            return
        self.bar.set_media(self._media if self.cfg["media"] else None)
        self._refresh_actions()
        self._refresh_weather()
        self._refresh_shelf()
        self._refresh_clipboard()
        self._refresh_pomodoro(force=True)
        self._refresh_notes()

    def apply_settings(self, raw: Any) -> None:
        old_city = self.cfg["weather_city"].strip()
        self.cfg = normalize(raw)
        if self.cfg["weather_city"].strip() != old_city or not self.cfg["weather"]:
            self._weather, self._weather_hint, self._weather_place = None, "", None
        self.pomodoro.configure(self.cfg["pomodoro_work"], self.cfg["pomodoro_short"], self.cfg["pomodoro_long"],
                                self.cfg["pomodoro_rounds"])
        if not self.cfg["pomodoro"] and self.pomodoro.state != IDLE:
            self.pomodoro.reset()
            self._pomo_timer.stop()
        self.clipboard.set_limit(self.cfg["clipboard_limit"])
        self.clipboard.allow_secrets = self.cfg["clipboard_allow_secrets"]
        self.shelf.set_limit(self.cfg["shelf_limit"])
        self._sync_clipboard()
        if self.bar is not None:
            self.bar.apply_config(self.cfg)
            self._refresh_all()
            self._set_active(self.bar.isVisible())
        self._schedule_save()

    def _on_position(self, patch: dict) -> None:
        self.cfg.update(patch)
        self.settings_patch.emit(dict(patch))

    def _on_visibility(self, visible: bool) -> None:
        self._set_active(visible)
        if visible:
            self._refresh_all()
            self._pump_timer.start()

    # --- системные сервисы (только пока островок виден) ------------------------------

    def _set_active(self, active: bool) -> None:
        active = bool(active) and self.cfg["enabled"] and not self._closed
        self._active = active
        if not self.SYSTEM_SERVICES:
            return
        if active and self._weather_wanted():
            if not self._weather_timer.isActive():
                self._weather_timer.start()
            if self._weather is None or time.time() - self._weather.fetched > WEATHER_MS / 1000:
                self._fetch_weather()
        else:
            self._weather_timer.stop()
        want_events = active and (self.cfg["indicators"] or self.cfg["lock_keys"])
        if want_events and not self._events_timer.isActive():
            self._volume = self._bright = self._locks = None      # первое чтение — без всплывающего индикатора
            self._events_timer.start(EVENTS_IDLE_MS)
        elif not want_events:
            self._events_timer.stop()
        want_media = active and self.cfg["media"]
        want_notes = active and self.cfg["notifications_windows"]
        if want_media or want_notes:
            if self._bridge is None:
                from monitoring.winrt_bridge import WinRtBridge, available

                if not available():
                    if not self._warned_winrt:
                        self._warned_winrt = True
                        log.warning("Пакеты winrt-* не установлены: музыка и уведомления Windows в островке недоступны")
                else:
                    self._bridge = WinRtBridge(self._media_ready.emit, self._notes_ready.emit,
                                               self._bridge_status.emit)
            if self._bridge is not None:
                if not self._bridge.is_running():
                    self._media_primed = False
                self._bridge.set_features(want_media, want_notes)
        elif self._bridge is not None:
            self._bridge.stop()
            self._media = None
            if self.bar is not None:
                self.bar.set_media(None)
        if not active:
            self._meter_timer.stop()
            self._sys_timer.stop()
        self._sync_meter()

    def _ensure_audio(self):
        if self._audio is None:
            from monitoring.win_audio import AudioEndpoint

            self._audio = AudioEndpoint()
        return self._audio

    def _poll_events(self) -> None:
        """Громкость, яркость, Caps Lock и Num Lock: три быстрых системных вызова."""
        self._events_tick += 1
        changed = False
        if self.cfg["indicators"]:
            audio = self._ensure_audio()
            if self._events_tick % DEVICE_RECHECK_TICKS == 0 and time.monotonic() >= self._fast_until:
                audio.open()                    # устройство вывода могло смениться (наушники, монитор)
            volume = audio.volume()
            if volume is not None:
                volume = (round(volume[0]), volume[1])
                if self._volume is not None and volume != self._volume:
                    changed = True
                    self._show_volume(*volume)
                self._volume = volume
                if self.bar is not None:
                    self.bar.set_volume(*volume)
            if self._brightness is None:
                from monitoring.win_system import Brightness

                self._brightness = Brightness()
            if self._brightness.available:
                on_battery = self._battery is not None and not self._battery.plugged
                value = self._brightness.get(on_battery)
                if value is not None:
                    if self._bright is not None and value != self._bright:
                        changed = True
                        self._show_brightness(value)
                    self._bright = value
        if self.cfg["lock_keys"]:
            from monitoring.win_system import lock_keys

            locks = lock_keys()
            if locks is not None:
                if self._locks is not None:
                    for key, title in (("caps", "Caps Lock"), ("num", "Num Lock")):
                        if locks[key] != self._locks[key]:
                            self._show_lock(title, locks[key])
                self._locks = locks
                if self.bar is not None and self.bar.system_view.isVisible():
                    self.bar.system_view.set_locks(locks)
        if changed:
            self._fast_until = time.monotonic() + EVENTS_ACTIVE_SECONDS
        wanted = EVENTS_ACTIVE_MS if time.monotonic() < self._fast_until else EVENTS_IDLE_MS
        if self._events_timer.interval() != wanted:
            self._events_timer.setInterval(wanted)

    def _show_volume(self, percent: float, muted: bool) -> None:
        if self._visible() and self.bar.states.flash(IslandState.VOLUME, None, LEVEL_TIMEOUT_MS):
            self.bar.indicator.show_volume(percent, muted)

    def _show_brightness(self, percent: float) -> None:
        if self._visible() and self.bar.states.flash(IslandState.BRIGHTNESS, None, LEVEL_TIMEOUT_MS):
            self.bar.indicator.show_brightness(percent)

    def _show_lock(self, title: str, enabled: bool) -> None:
        if self._visible() and self.bar.states.flash(IslandState.SYSTEM, None, LEVEL_TIMEOUT_MS):
            self.bar.indicator.show_text("keyboard", title, "включён" if enabled else "выключен",
                                         CYAN if enabled else TEXT_SECONDARY)

    # --- мониторинг (данные приходят от MonitorService главного окна) ----------------

    def on_snapshot(self, snap) -> None:
        self._values = snapshot_values(snap)
        battery = snap.battery
        previous, self._battery = self._battery, battery
        if battery is not None and previous is not None and battery.plugged != previous.plugged:
            if self.cfg["battery_events"] and self._visible():
                if self.bar.states.flash(IslandState.BATTERY, None, 3000):
                    self.bar.indicator.show_battery(battery.percent, battery.plugged, self._battery_detail(battery))
        if self.bar is not None and self.bar.system_view.isVisible():
            self.bar.system_view.set_battery(self._battery_line())

    @staticmethod
    def _battery_detail(battery) -> str:
        if battery.plugged:
            return "Питание от сети" if battery.percent < 99.5 else "Аккумулятор заряжен"
        if battery.seconds_left:
            hours, minutes = battery.seconds_left // 3600, battery.seconds_left % 3600 // 60
            return f"Осталось примерно {hours} ч {minutes:02d} мин" if hours else f"Осталось примерно {minutes} мин"
        return "Питание от аккумулятора"

    def _battery_line(self) -> str:
        battery = self._battery
        if not self._values:
            return "Питание: данные мониторинга ещё не получены"
        if battery is None:
            return "Аккумулятора нет: питание от сети"
        return f"Аккумулятор {battery.percent:.0f}% · {self._battery_detail(battery).lower()}"

    def _probe_connectivity(self) -> None:
        if self._probing or not self.SYSTEM_SERVICES:
            return
        self._probing = True

        def work() -> None:
            from monitoring.win_system import bluetooth_status, wifi_status

            try:
                wifi, bluetooth = wifi_status(), bluetooth_status()
            except Exception:  # noqa: BLE001 — сбой чтения не должен ронять поток без записи в журнал
                log.exception("Не удалось прочитать состояние Wi-Fi и Bluetooth")
                wifi = bluetooth = None
            self._connectivity_ready.emit(wifi, bluetooth)

        threading.Thread(target=work, daemon=True, name="sirius-connectivity").start()

    def _on_connectivity(self, wifi, bluetooth) -> None:
        self._probing = False
        if self.bar is not None:
            self.bar.system_view.set_connectivity(wifi, bluetooth)
            self.bar.set_action_active("wifi", bool(wifi is not None and wifi.connected))
            self.bar.set_action_active("bluetooth", bool(bluetooth is not None and bluetooth.enabled))

    # --- состояния -------------------------------------------------------------------

    def _on_state_changed(self, state: IslandState, _payload) -> None:
        bar = self.bar
        base_only = bar.states.transient is None
        if state is IslandState.SYSTEM and base_only:
            bar.system_view.set_metrics(self._values)
            bar.system_view.set_battery(self._battery_line())
            if self.SYSTEM_SERVICES:
                from monitoring.win_system import lock_keys

                bar.system_view.set_locks(lock_keys())
                self._probe_connectivity()
                self._sys_timer.start()
        elif base_only:
            self._sys_timer.stop()
        if state is IslandState.CONTROL and base_only and self.SYSTEM_SERVICES:
            self._probe_connectivity()           # подсветка кнопок Wi-Fi и Bluetooth
        if state is IslandState.MEDIA and base_only and self.SYSTEM_SERVICES:
            self._push_volume()
        if state is IslandState.WEATHER and base_only:
            self._refresh_weather()
        if state is IslandState.NOTIFICATION and base_only:
            self.center.mark_read()
            self._drain_queue()
            self._refresh_notes(force_list=True)
        if state is IslandState.INTERACTIVE:
            self._refresh_shelf()
            self._refresh_clipboard()
            self._refresh_pomodoro(force=True)
        self._sync_meter()

    def _on_transient_finished(self, state: IslandState) -> None:
        if state is IslandState.NOTIFICATION:
            self._toast_id, self._toast_critical = None, False
        self._pump_timer.start()

    # --- медиа -----------------------------------------------------------------------

    def _on_media(self, info) -> None:
        if not (self._active and self.cfg["media"]):
            info = None
        self._media = info
        if self.bar is not None:
            self.bar.set_media(info)
        key = None if info is None else (info.app_id, info.title, info.artist)
        if not self._media_primed:
            self._media_primed = True          # то, что уже играло при появлении островка, не всплывает
            self._popped_key = key
        elif key is not None and key != self._popped_key and info.playing and info.title:
            self._media_pop_timer.start()      # плеер присылает название и исполнителя по частям — ждём
        self._sync_meter()

    def _media_popup(self) -> None:
        info = self._media
        if info is None or not info.playing or not self.cfg["media_popup"] or not self._visible():
            return
        key = (info.app_id, info.title, info.artist)
        if key == self._popped_key:
            return
        self._popped_key = key
        if self.bar.states.base is not IslandState.MEDIA:
            self.bar.states.flash(IslandState.MEDIA, None, MEDIA_POPUP_MS)

    def _media_command(self, name: str, value) -> None:
        if self._bridge is not None:
            self._bridge.command(name, value)

    def _sync_meter(self) -> None:
        bar = self.bar
        want = (self.SYSTEM_SERVICES and self._active and bar is not None and self.cfg["visualizer"]
                and self._media is not None and self._media.playing and bar.isVisible())
        if want and not self._meter_timer.isActive():
            self._meter_timer.start()
        elif not want and self._meter_timer.isActive():
            self._meter_timer.stop()
            if bar is not None:
                bar.media_view.visualizer.clear()
                bar.mini_visualizer.clear()
                bar.mini.visualizer.clear()

    # --- громкость (шкала во вкладке «Медиа») ----------------------------------------

    def _push_volume(self) -> None:
        volume = self._ensure_audio().volume()
        if self.bar is not None:
            self.bar.set_volume(*(volume if volume is not None else (None, False)))

    def _set_volume(self, percent: float) -> None:
        """Пользователь подвинул шкалу громкости: меняем общую громкость Windows."""
        if not self.SYSTEM_SERVICES:
            return
        audio = self._ensure_audio()
        if not audio.set_volume(percent):
            self.status_message.emit("Не удалось изменить громкость: устройство вывода недоступно")
            return
        muted = self._volume[1] if self._volume is not None else False
        self._volume = (round(percent), muted)     # своё изменение не показываем всплывающим индикатором

    # --- погода ----------------------------------------------------------------------

    def _weather_wanted(self) -> bool:
        return bool(self.cfg["weather"] and self.cfg["weather_city"].strip())

    def _refresh_weather(self) -> None:
        if self.bar is None:
            return
        if not self.cfg["weather"]:
            self.bar.set_weather(None, "Погода выключена в настройках островка")
            return
        self.bar.set_weather(self._weather, self._weather_hint, self.cfg["weather_city"])

    def _set_city(self, city: str) -> None:
        """Город введён прямо во вкладке «Погода»: запоминаем его в настройках и запрашиваем погоду."""
        city = city.strip()[:80]
        if not city:
            return
        self.cfg["weather_city"] = city
        self._weather, self._weather_place = None, None
        self._weather_hint = f"Запрашиваю погоду: {city}…" if self.SYSTEM_SERVICES else ""
        self.settings_patch.emit({"weather_city": city})
        self._refresh_weather()
        if self.SYSTEM_SERVICES and self._active:
            self._weather_timer.start()
            self._fetch_weather()

    def _fetch_weather(self) -> None:
        """Запрос в фоновом потоке; в сеть уходит только название города и его координаты."""
        if not (self.SYSTEM_SERVICES and self._active and self._weather_wanted()) or self._weather_busy:
            return
        city = self.cfg["weather_city"].strip()
        place = self._weather_place if self._weather_place and self._weather_place[0] == city else None
        self._weather_busy = True

        def work() -> None:
            from monitoring import weather as service

            try:
                found = place or (city, *service.geocode(city))
                self._weather_ready.emit((found, service.fetch(found[1], found[2], found[3] or city)), "")
            except service.WeatherError as exc:
                self._weather_ready.emit(None, str(exc))
            except Exception:
                log.exception("Погода: неожиданная ошибка")
                self._weather_ready.emit(None, "Не удалось получить погоду")

        threading.Thread(target=work, daemon=True, name="sirius-weather").start()

    def _on_weather(self, payload, error: str) -> None:
        self._weather_busy = False
        if self._closed:
            return
        if payload is not None:
            place, weather = payload
            if place[0] != self.cfg["weather_city"].strip():
                self._fetch_weather()              # город сменили, пока шёл запрос
                return
            self._weather_place, self._weather, self._weather_hint = place, weather, ""
        else:
            log.warning("Погода: %s", error)
            self._weather_hint = error             # прежние данные остаются на экране с пояснением
        self._refresh_weather()

    def _poll_meter(self) -> None:
        level = self._ensure_audio().peak()
        if level is None:                      # устройства вывода нет: визуализатор честно молчит
            self._meter_timer.stop()
            return
        self.bar.push_audio_level(level)

    def _on_bridge_status(self, kind: str, text: str) -> None:
        log.warning("Островок: %s", text)
        self.status_message.emit(text)
        if kind == "notifications" and self.bar is not None:
            self._notes_hint = text
            self._refresh_notes()

    # --- уведомления -----------------------------------------------------------------

    def notify(self, app: str, title: str, text: str = "", critical: bool = False, icon: bytes | None = None,
               source: str = "sirius", when: float | None = None) -> None:
        """Уведомление в островок: предупреждения SIRIUS, Pomodoro, сообщения LISA, уведомления Windows."""
        if source == "sirius" and not self.cfg["notifications"]:
            return
        note = self.center.post(app, title, text, CRITICAL if critical else NORMAL, icon, source, when)
        self._refresh_notes()
        if note is not None:
            self._pump_notes()

    def _on_win_notes(self, notes) -> None:
        for note in notes:
            self.notify(note.app, note.title, note.text, icon=note.icon, source="windows", when=note.time)

    def _drain_queue(self) -> None:
        while self.center.next() is not None:
            pass

    def _pump_notes(self) -> None:
        """Показывает следующее уведомление из очереди, если островок свободен."""
        if not self._visible():
            return
        states = self.bar.states
        if states.transient is IslandState.NOTIFICATION:
            urgent = (self.center.top_priority() or 0) >= CRITICAL and not self._toast_critical
            if not urgent:
                return                         # текущее уведомление досмотрят; важное его вытесняет
        if states.base is IslandState.NOTIFICATION and states.transient is None:
            self.center.mark_read()            # журнал открыт: новые сообщения сразу видны в нём
            self._drain_queue()
            self._refresh_notes(force_list=True)
            return
        while True:
            note = self.center.next()
            if note is None:
                return
            if time.time() - note.time <= STALE_NOTE_SECONDS or note.priority >= CRITICAL:
                break                          # устаревшие (островок был скрыт) остаются только в журнале
        critical = note.priority >= CRITICAL
        ms = int(self.cfg["notification_seconds"] * 1000 * (1.5 if critical else 1.0))
        if states.flash(IslandState.NOTIFICATION, note.id, ms, CRITICAL_PRIORITY if critical else None):
            self._toast_id, self._toast_critical = note.id, critical
            self.bar.toast.show_note(note, self.center.pending())
        else:
            self.center.requeue(note)

    def _refresh_notes(self, force_list: bool = False) -> None:
        if self.bar is None:
            return
        self.bar.set_unread(self.center.unread())
        if force_list or self.bar.notes_list.isVisible():
            hint = self._notes_hint
            if not hint and not self.cfg["notifications_windows"]:
                hint = "Уведомлений нет. Уведомления Windows включаются в настройках островка."
            self.bar.notes_list.set_notes(self.center.history(), hint)

    def dismiss_note(self, note_id: int) -> None:
        self.center.dismiss(note_id)
        if self.bar is not None and self._toast_id == note_id:
            self.bar.states.dismiss_transient()
        self._refresh_notes()

    def clear_notes(self) -> None:
        self.center.clear()
        self._refresh_notes()

    # --- Pomodoro --------------------------------------------------------------------

    def pomodoro_start(self) -> None:
        self.pomodoro.start()
        self._pomo_changed()

    def pomodoro_pause(self) -> None:
        self.pomodoro.pause()
        self._pomo_changed()

    def pomodoro_skip(self) -> None:
        for event in self.pomodoro.skip():
            self._pomo_event(event)
        self._pomo_changed()

    def pomodoro_reset(self) -> None:
        self.pomodoro.reset()
        self._pomo_changed()

    def _pomo_changed(self) -> None:
        if self.pomodoro.state == RUNNING:
            self._pomo_timer.start()
        else:
            self._pomo_timer.stop()
        self._refresh_pomodoro(force=True)
        self._schedule_save()

    def _pomo_tick(self) -> None:
        events = self.pomodoro.tick()
        for event in events:
            self._pomo_event(event)
        if events:
            self._pomo_changed()
        else:
            self._refresh_pomodoro()

    def _pomo_event(self, event: str, offline: bool = False) -> None:
        suffix = " Таймер на паузе — продолжите, когда будете готовы." if offline else ""
        if event == "work_done":
            title = PHASE_TITLES[self.pomodoro.phase]
            self.notify("Pomodoro", "Рабочий отрезок завершён",
                        f"Пора отдохнуть: {title.lower()}, {int(self.pomodoro.duration() // 60)} мин.{suffix}")
        elif event == "break_done":
            self.notify("Pomodoro", "Перерыв окончен", f"Возвращаемся к работе.{suffix}")
        elif event == "cycle_done":
            self.notify("Pomodoro", "Цикл завершён", "Все рабочие отрезки и длинный перерыв пройдены.")

    def _refresh_pomodoro(self, force: bool = False) -> None:
        if self.bar is None:
            return
        pomo = self.pomodoro
        remaining = format_time(pomo.remaining())
        self.bar.set_pomodoro(None if pomo.state == IDLE else remaining)
        page = self.bar.tools.pomodoro
        if force or page.isVisible() or pomo.state == IDLE:     # раз в секунду — только видимый экран
            page.set_state(pomo.state, pomo.phase, PHASE_TITLES[pomo.phase], remaining, pomo.progress(),
                           pomo.rounds_done, pomo.rounds)

    # --- буфер обмена ----------------------------------------------------------------

    def _sync_clipboard(self) -> None:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return
        want = self.cfg["clipboard"] and not self._closed
        if want and not self._clipboard_connected:
            clipboard.dataChanged.connect(self._on_clipboard)
            self._clipboard_connected = True
        elif not want and self._clipboard_connected:
            clipboard.dataChanged.disconnect(self._on_clipboard)
            self._clipboard_connected = False
            self.clipboard.clear()             # история выключена — прежние записи не хранятся

    def _on_clipboard(self) -> None:
        mime = QGuiApplication.clipboard().mimeData()
        if mime is None or not mime.hasText():
            return
        skipped = self.clipboard.skipped_secrets
        entry = self.clipboard.add(mime.text(), mime.formats())
        if entry is not None:
            self._refresh_clipboard()
            if self.cfg["clipboard_persist"]:
                self._schedule_save()
        elif self.clipboard.skipped_secrets != skipped and self.bar is not None:
            self.bar.tools.clipboard.set_status("Скопированное похоже на пароль или ключ — в историю не сохранено")

    def _refresh_clipboard(self) -> None:
        if self.bar is None:
            return
        page = self.bar.tools.clipboard
        if page.isVisible() or not len(self.clipboard):
            page.set_items(self.clipboard.items(page.search.text()))

    def _copy_again(self, entry_id: int) -> None:
        entry = self.clipboard.get(entry_id)
        if entry is not None:
            QGuiApplication.clipboard().setText(entry.text)
            self.bar.tools.clipboard.set_status("Скопировано в буфер обмена")

    def _remove_clip(self, entry_id: int) -> None:
        if self.clipboard.remove(entry_id):
            self._refresh_clipboard()
            self._schedule_save()

    def clear_clipboard(self) -> None:
        self.clipboard.clear()
        self._refresh_clipboard()
        self._schedule_save()

    # --- файловая полка --------------------------------------------------------------

    def add_files(self, paths: list) -> None:
        added = self.shelf.add(paths)
        if added:
            status = f"Добавлено на полку: {added}"
            self._schedule_save()
        elif self.shelf.is_full():
            status = f"Полка заполнена ({self.shelf.limit}). Уберите лишнее или увеличьте размер в настройках."
        else:
            status = "Эти файлы уже лежат на полке"
        if self.bar is not None:
            self.bar.open_tool("shelf")
            self.bar.tools.shelf.set_items(self.shelf.items(), status)

    def _refresh_shelf(self, status: str = "") -> None:
        if self.bar is not None:
            self.bar.tools.shelf.set_items(self.shelf.items(), status)

    def _open_path(self, path: str) -> None:
        ok, message = quick.launch_target(path)
        self._refresh_shelf(message)

    def _reveal_path(self, path: str) -> None:
        ok, message = quick.launch_target(str(Path(path).parent))
        self._refresh_shelf(message if not ok else f"Открыта папка: {Path(path).parent}")

    def _remove_from_shelf(self, path: str) -> None:
        if self.shelf.remove(path):
            self._refresh_shelf("Убрано с полки. Файл на диске остался.")
            self._schedule_save()

    def clear_shelf(self) -> None:
        self.shelf.clear()
        self._refresh_shelf("Полка очищена. Файлы на диске остались.")
        self._schedule_save()

    # --- быстрые действия ------------------------------------------------------------

    def actions(self) -> list:
        if not self.cfg["actions"]:
            return []
        return list(quick.BUILTIN_ACTIONS) + quick.custom_actions(self.cfg["custom_actions"])

    def _refresh_actions(self) -> None:
        if self.bar is not None:
            actions = self.actions()
            self.bar.hub.set_actions([a for a in actions if a.id not in quick.SETTINGS_PAGES])
            self.bar.control.set_actions(actions)

    def run_action(self, action_id: str) -> None:
        action = next((a for a in self.actions() if a.id == action_id), None)
        if action is None:
            return
        if action.custom:
            ok, message = quick.launch_target(action.target)
        elif action.id in quick.SETTINGS_PAGES:
            ok, message = quick.open_settings_page(action.id)
        elif action.id == "explorer":
            ok, message = quick.open_explorer()
            message = "Проводник открыт" if ok else message
        else:
            self.action_requested.emit(action.id)
            return
        log.info("Быстрое действие «%s»: %s", action.title, message)
        if self.bar is not None:
            self.bar.control.set_status(message, ok)
        self.status_message.emit(message)

    # --- завершение ------------------------------------------------------------------

    def shutdown(self) -> None:
        if self._closed:
            return
        self._save_timer.stop()
        self._save()
        self._closed = True
        for timer in (self._weather_timer, self._pomo_timer, self._events_timer, self._meter_timer, self._sys_timer, self._pump_timer,
                      self._media_pop_timer):
            timer.stop()
        self._sync_clipboard()
        if self._bridge is not None:
            self._bridge.stop()
            self._bridge = None
        if self._audio is not None:
            self._audio.close()
            self._audio = None
        if self._brightness is not None:
            self._brightness.close()
            self._brightness = None

