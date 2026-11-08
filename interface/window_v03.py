"""Возможности главного окна v0.3: мониторинг, предупреждения, режим «тяжёлая задача», компактный режим,
значок в трее, горячие клавиши и автозапуск. Подключается к MainWindow как примесь (mixin):
методы используют поля главного окна (self.monitor, self.voice, self.models, self.settings …).
"""

from __future__ import annotations

import dataclasses
import logging
import threading

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import QMenu, QPushButton, QSystemTrayIcon

from core.autostart import Autostart
from interface.compact_bar import CompactBar
from interface.styles import CYAN, WARNING
from monitoring.alerts import Alert, system_mood, thresholds_from_settings
from monitoring.history import snapshot_values
from monitoring.system_report import build_report, is_system_question, report_message

log = logging.getLogger("sirius.ui")

HOTKEYS = (
    ("Ctrl+1 … Ctrl+6", "открыть или закрыть панели CHAT, CODE, SYSTEM, TERMINAL, LOGS, HISTORY"),
    ("Ctrl+M", "компактный режим"),
    ("Ctrl+Shift+V", "голос вкл/выкл"),
    ("Ctrl+Shift+H", "освободить ресурсы / вернуть модель"),
    ("Ctrl+,", "настройки"),
    ("Esc", "остановить речь"),
)


class WindowV03Mixin:
    # --- запуск ----------------------------------------------------------------------

    def _init_v03_state(self) -> None:
        self._heavy = False
        self._compact = False
        self._quitting = False
        self._tray: QSystemTrayIcon | None = None
        self._tray_hint_shown = False
        self._mood = "normal"
        self.compact_bar: CompactBar | None = None
        self.autostart = Autostart(self.base_dir)

    def _build_v03_buttons(self) -> None:
        """Кнопки панели управления: компактный режим и освобождение ресурсов."""
        self.compact_btn = QPushButton("КОМПАКТНО")
        self.compact_btn.setObjectName("barButton")
        self.compact_btn.setToolTip("Свернуть SIRIUS в полоску у верхнего края экрана (Ctrl+M)")
        self.control_bar.add_right_widget(self.compact_btn)
        self.heavy_btn = QPushButton("ОСВОБОДИТЬ")
        self.heavy_btn.setObjectName("barButton")
        self.heavy_btn.setToolTip("Выгрузить Qwen и голос из памяти — для игр и тяжёлых задач (Ctrl+Shift+H)")
        self.control_bar.add_right_widget(self.heavy_btn)

    def _setup_v03(self) -> None:
        self.compact_btn.clicked.connect(self.enter_compact)
        self.heavy_btn.clicked.connect(lambda: self.set_heavy_mode(not self._heavy))
        self.monitor.model_name = self.models.model_name
        self._apply_monitor_settings(self.settings)
        self.monitor.updated.connect(self._on_monitor_update)
        self.monitor.alert.connect(self._on_alert)
        self.monitor.start()
        self._setup_shortcuts()
        self._setup_tray()
        self._sync_autostart(self.settings.get("autostart", False), quiet=True)

    def _apply_monitor_settings(self, values: dict) -> None:
        self.monitor.alerts.enabled = bool(values.get("alerts_enabled", True))
        self.monitor.alerts.set_thresholds(thresholds_from_settings(values))

    # --- мониторинг ------------------------------------------------------------------

    def _on_monitor_update(self, snap) -> None:
        mood = system_mood(snap, self.monitor.alerts.thresholds, self.monitor.history.average("cpu", 10))
        if mood != self._mood:
            self._mood = mood
            log.info("Настроение LISA по состоянию системы: %s", mood)
        self.avatar.set_system_mood(mood)
        if self.compact_bar is not None:
            self.compact_bar.set_mood(mood)
            if self._compact:
                self.compact_bar.set_metrics(snapshot_values(snap))

    def _on_alert(self, alert: Alert) -> None:
        self.statusBar().showMessage(f"⚠ {alert.text}", 15000)
        self.chat_notice(alert)
        if self._tray is not None and (not self.isVisible() or self._compact):
            icon = QSystemTrayIcon.MessageIcon.Critical if alert.critical else QSystemTrayIcon.MessageIcon.Warning
            self._tray.showMessage("SIRIUS", alert.text, icon, 8000)
        if (self.settings.get("alert_voice") and self.voice.enabled and not self._generating
                and not self.voice.is_speaking()):
            self.voice.say(alert.spoken())

    def chat_notice(self, alert: Alert) -> None:
        """Предупреждение в индикаторе состояния SYSTEM-панели (в чат не пишем: это не реплика LISA)."""
        self.workspace.set_status("system", WARNING, alert.text)

    def system_context(self, text: str) -> list[dict]:
        """Реальные данные мониторинга для вопроса о компьютере (иначе пусто)."""
        if not is_system_question(text) or self.monitor.last_snapshot is None:
            return []
        snap = self.monitor.last_snapshot
        if snap.processes is None and self.monitor.last_processes:
            snap = dataclasses.replace(snap, processes=self.monitor.last_processes)
        report = build_report(snap, self.monitor.history, self.monitor.stats, self.monitor.model_vram)
        log.info("К вопросу добавлены данные мониторинга (%d символов)", len(report))
        return [report_message(report)]

    # --- режим «тяжёлая задача» ------------------------------------------------------

    def set_heavy_mode(self, enabled: bool) -> None:
        """Выгружает Qwen и голос из памяти (enabled=True) или загружает их обратно."""
        if enabled == self._heavy:
            return
        self._heavy = enabled
        if enabled:
            if self._generating and self._worker is not None:
                self._worker.stop()
            self.voice.stop()
            if self._boot_worker is not None:
                self._boot_worker.cancel()
            self.tts.release()
            threading.Thread(target=self.models.unload, daemon=True, name="sirius-heavy-unload").start()
            self.heavy_btn.setText("ВЕРНУТЬ")
            self.heavy_btn.setToolTip("Загрузить Qwen и голос обратно (Ctrl+Shift+H)")
            self._set_status_indicator("Ресурсы освобождены: Qwen и голос выгружены", WARNING)
            self.statusBar().showMessage("Qwen и голос выгружены из памяти. Модель загрузится при следующем сообщении.")
            log.info("Режим «тяжёлая задача»: модель и голос выгружены")
        else:
            self.heavy_btn.setText("ОСВОБОДИТЬ")
            self.heavy_btn.setToolTip("Выгрузить Qwen и голос из памяти — для игр и тяжёлых задач (Ctrl+Shift+H)")
            self._set_status_indicator("Загрузка модели в видеопамять…", CYAN)
            if not self._boot_running():
                self._start_boot(show_overlay=False)
            log.info("Режим «тяжёлая задача» выключен: загрузка модели")
        self._update_tray_menu()

    @property
    def heavy_mode(self) -> bool:
        return self._heavy

    def _leave_heavy_silently(self) -> None:
        """Новое сообщение в режиме «тяжёлая задача»: модель загрузится сама при запросе."""
        if self._heavy:
            self._heavy = False
            self.heavy_btn.setText("ОСВОБОДИТЬ")
            self._update_tray_menu()

    # --- компактный режим ------------------------------------------------------------

    def _ensure_compact_bar(self) -> CompactBar:
        if self.compact_bar is None:
            bar = CompactBar()
            bar.setWindowIcon(self.windowIcon())
            bar.send_requested.connect(self._on_send)
            bar.expand_requested.connect(self.leave_compact)
            bar.voice_toggled.connect(self._set_voice)
            bar.avatar_clicked.connect(self._on_avatar_clicked)
            self.compact_bar = bar
        return self.compact_bar

    def enter_compact(self) -> None:
        if self._compact:
            return
        bar = self._ensure_compact_bar()
        self._compact = True
        bar.set_voice(self.voice.enabled)
        bar.set_mood(self._mood)
        bar.set_busy(self._generating)
        bar.set_state(self.avatar.state)
        if self.monitor.last_snapshot is not None:
            bar.set_metrics(snapshot_values(self.monitor.last_snapshot))
        bar.place_on_screen(self.screen())
        self.hide()
        bar.show()
        bar.raise_()
        bar.activateWindow()
        bar.input.setFocus()
        self._update_tray_menu()

    def leave_compact(self) -> None:
        if not self._compact:
            return
        self._compact = False
        if self.compact_bar is not None:
            self.compact_bar.hide()
        self.show_from_tray()
        self._update_tray_menu()

    def toggle_compact(self) -> None:
        self.leave_compact() if self._compact else self.enter_compact()

    @property
    def compact(self) -> bool:
        return self._compact

    # --- трей ------------------------------------------------------------------------

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        tray = QSystemTrayIcon(self.windowIcon() if not self.windowIcon().isNull() else QIcon(), self)
        tray.setToolTip("SIRIUS — LISA")
        menu = QMenu()
        self._tray_show = menu.addAction("Показать SIRIUS", self.show_from_tray)
        self._tray_compact = menu.addAction("Компактный режим", self.toggle_compact)
        self._tray_heavy = menu.addAction("Освободить ресурсы", lambda: self.set_heavy_mode(not self._heavy))
        menu.addSeparator()
        menu.addAction("Выход", self.quit_app)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray
        self._tray_menu = menu

    def _update_tray_menu(self) -> None:
        if self._tray is None:
            return
        self._tray_compact.setText("Полное окно" if self._compact else "Компактный режим")
        self._tray_heavy.setText("Вернуть модель" if self._heavy else "Освободить ресурсы")

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick):
            if self._compact:
                self.leave_compact()
            elif self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_from_tray()

    def show_from_tray(self) -> None:
        self.showNormal() if self.isMinimized() else self.show()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        if self.compact_bar is not None:
            self.compact_bar.hide()
        self.close()

    def _close_to_tray_requested(self, event) -> bool:
        """True — окно только спрятано в трей, приложение продолжает работу."""
        if self._quitting or self._tray is None or not self.settings.get("close_to_tray", False):
            return False
        event.ignore()
        self.hide()
        if not self._tray_hint_shown:
            self._tray_hint_shown = True
            self._tray.showMessage("SIRIUS работает в трее",
                                   "Модель остаётся в памяти. Выход — в меню значка SIRIUS.",
                                   QSystemTrayIcon.MessageIcon.Information, 6000)
        return True

    def _shutdown_v03(self) -> None:
        self.monitor.shutdown()
        if self.compact_bar is not None:
            self.compact_bar.close()
            self.compact_bar.deleteLater()
            self.compact_bar = None
        if self._tray is not None:
            self._tray.hide()

    # --- горячие клавиши -------------------------------------------------------------

    def _setup_shortcuts(self) -> None:
        self._shortcuts: list[QShortcut] = []

        def add(keys: str, slot) -> None:
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(slot)
            self._shortcuts.append(sc)

        for i, panel_id in enumerate(self.panel_registry.ids()[:9], start=1):
            add(f"Ctrl+{i}", lambda pid=panel_id: self.workspace.toggle(pid))
        add("Ctrl+M", self.toggle_compact)
        add("Ctrl+Shift+V", lambda: self._set_voice(not self.voice.enabled))
        add("Ctrl+Shift+H", lambda: self.set_heavy_mode(not self._heavy))
        add("Ctrl+,", self._open_settings)
        add("Esc", self._on_avatar_clicked)
        self.settings_btn.setToolTip("Настройки (Ctrl+,)\n\nГорячие клавиши:\n"
                                     + "\n".join(f"{k} — {v}" for k, v in HOTKEYS))

    # --- автозапуск ------------------------------------------------------------------

    def _sync_autostart(self, enabled: bool, quiet: bool = False) -> None:
        """Приводит запись автозапуска в реестре к настройке."""
        if not self.autostart.supported:
            return
        if self.autostart.is_enabled() == bool(enabled):
            return
        if quiet and not enabled:
            return   # при запуске не удаляем запись, созданную вручную, без явного решения в настройках
        ok = self.autostart.set_enabled(bool(enabled))
        if not quiet:
            self.statusBar().showMessage(
                ("Автозапуск включён" if enabled else "Автозапуск выключен") if ok else "Не удалось изменить автозапуск",
                6000)

