"""Главное окно SIRIUS: аватар LISA, чат, история, переключатель голоса и связка модулей."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QInputDialog, QMainWindow, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

from core.ai_engine import AIEngine
from core.context_manager import build_messages
from core.model_manager import MODEL_SIZE_HINT, OllamaStatus, ModelManager, OLLAMA_DOWNLOAD_URL, StatusInfo
from interface.avatar_widget import AvatarState, AvatarWidget
from interface.chat_panel import ChatPanel
from interface.history_panel import HistoryPanel
from interface.panels.code_panel import CodePanel
from interface.panels.logs_panel import LogsPanel
from interface.panels.system_panel import SystemPanel
from interface.panels.terminal_panel import TerminalPanel
from interface.settings_panel import SettingsDialog
from interface.styles import CYAN, ERROR, SUCCESS, TEXT_SECONDARY, WARNING
from interface.boot_overlay import BootOverlay
from interface.monitor_service import MonitorService
from interface.window_v03 import WindowV03Mixin
from interface.workers import BOOT_STAGES, BootWorker, GenerationWorker, PullWorker, StatusWorker, TitleWorker
from interface.workspace.backdrop import WorkspaceBackdrop
from interface.workspace.control_bar import ControlBar
from interface.workspace.panel_registry import PanelRegistry, PanelSpec
from interface.workspace.workspace_canvas import WorkspaceCanvas
from interface.workspace.workspace_manager import WorkspaceManager
from core.title_generator import DEFAULT_TITLE
from storage.chat_storage import ChatStorage
from storage.settings_storage import SettingsStorage
from voice.audio_effects import VoiceStyle
from voice.audio_player import AudioPlayer
from voice.tts_engine import TTSEngine
from voice.voice_controller import VoiceController

log = logging.getLogger("sirius.ui")

SAMPLE_PHRASE = "Здравствуйте! Я LISA, ваш помощник в системе SIRIUS. Модель Qwen работает через Ollama, загрузка GPU — 45%. Чем могу помочь?"
OLLAMA_POLL_MS = 10_000


class MainWindow(WindowV03Mixin, QMainWindow):
    def __init__(self, base_dir: Path) -> None:
        super().__init__()
        self.base_dir = base_dir
        self.data_dir = base_dir / "storage"
        self.settings_store = SettingsStorage(self.data_dir / "settings.json")
        self.settings = self.settings_store.load()
        self.chats = ChatStorage(self.data_dir / "chats")

        self.models = ModelManager(self.settings["ollama_url"], self.settings["model_name"])
        self.engine = AIEngine(self.settings["ollama_url"], self.settings["model_name"])
        self.tts = TTSEngine(self._resolve(self.settings["voice_model_path"]), self.data_dir / "tmp")
        self.player = AudioPlayer(self)
        self.voice = VoiceController(self.tts, self.player, self)
        self._apply_voice_runtime(self.settings)

        self._current_chat_id: str | None = None
        self._worker: GenerationWorker | None = None
        self._generating = False
        self._pull_worker: PullWorker | None = None
        self._title_worker: TitleWorker | None = None
        self._status_worker: StatusWorker | None = None
        self._boot_worker: BootWorker | None = None
        self._boot_overlay: BootOverlay | None = None
        self._closing = False
        self._assistant_card = None
        self._speaking = False
        self._user_stopped_voice = False
        self._error_flag = False
        self._offline = False
        self._voice_error = ""
        self._last_status: OllamaStatus | None = None
        self._install_hint_shown = False
        self._settings_dialog: SettingsDialog | None = None

        self._init_v03_state()
        self.monitor = MonitorService(models_source=self.models.loaded_models, parent=self)
        self._build_ui()
        self._connect_signals()
        self.setMinimumSize(900, 520)
        self._restore_window_size()
        self.setWindowTitle("SIRIUS")
        self._dark_titlebar_applied = False
        # последнее расположение панелей; без сохранения или при повреждении — стандартная компоновка
        self.workspace.restore(self.settings.get("workspace"))
        # компоновка сохраняется вскоре после изменения, а не только при закрытии окна
        self._layout_save_timer = QTimer(self)
        self._layout_save_timer.setSingleShot(True)
        self._layout_save_timer.setInterval(1500)
        self._layout_save_timer.timeout.connect(self._save_settings)
        self.workspace.layout_changed.connect(self._layout_save_timer.start)

        self._clear_temp_audio()
        self._start_new_session()
        self._apply_voice_switch_from_settings()
        self._start_boot()
        self._setup_v03()

        # тихая периодическая проверка Ollama: обновляет индикаторы и состояние OFFLINE без диалогов
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(OLLAMA_POLL_MS)
        self._status_timer.timeout.connect(lambda: self._check_ollama(try_start=False, quiet=True))
        self._status_timer.start()

    # --- построение интерфейса ----------------------------------------------

    def _build_ui(self) -> None:
        """Рабочее пространство: фон-город на всё окно, панель управления сверху,
        ниже область с LISA и плавающими панелями."""
        central = WorkspaceBackdrop()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 4)
        root.setSpacing(6)

        # содержимое постоянных панелей живёт всё время работы окна: диалог не теряется при закрытии панели
        self.chat = ChatPanel()
        self.history = HistoryPanel()
        self.code_panel = CodePanel()
        # опрос системы идёт только пока панель SYSTEM открыта; загруженную модель спрашиваем у Ollama
        self.system_panel = SystemPanel(models_source=self.models.loaded_models, service=self.monitor)
        self.logs_panel = LogsPanel(self.base_dir / "logs" / "sirius.log")
        # консоль только для ручного ввода: ни чат, ни модель не передают в неё команды
        self.terminal_panel = TerminalPanel()
        self.panel_registry = self._build_registry()

        self.control_bar = ControlBar(
            [(s.panel_id, s.title, s.tooltip) for s in self.panel_registry.specs()]
        )
        self.status_label = self.control_bar.status_label
        self._build_v03_buttons()
        self.voice_switch = QCheckBox("VOICE OFF")
        self.voice_switch.setCursor(Qt.CursorShape.PointingHandCursor)
        self.control_bar.add_right_widget(self.voice_switch)
        self.settings_btn = QPushButton("Настройки")
        self.settings_btn.setObjectName("barButton")
        self.control_bar.add_right_widget(self.settings_btn)
        root.addWidget(self.control_bar)

        self.canvas = WorkspaceCanvas()
        self.canvas.set_backdrop(central)
        self.avatar = AvatarWidget(self._resolve("resources/images/lisa.png"))
        self.canvas.set_avatar(self.avatar)
        root.addWidget(self.canvas, 1)
        self.workspace = WorkspaceManager(self.canvas, self.panel_registry, self)

        self.setCentralWidget(central)
        self.statusBar().showMessage("Готово")

    def _build_registry(self) -> PanelRegistry:
        registry = PanelRegistry()
        registry.register(PanelSpec("chat", "CHAT", lambda: self.chat, (360, 300), "Диалог с LISA"))
        registry.register(PanelSpec("code", "CODE", lambda: self.code_panel, (340, 240), "Код из ответов LISA"))
        registry.register(PanelSpec("system", "SYSTEM", lambda: self.system_panel, (330, 260),
                                    "Мониторинг: графики, процессы, диски, сеть, сводка сессии"))
        registry.register(PanelSpec("terminal", "TERMINAL", lambda: self.terminal_panel, (380, 220),
                                    "Ограниченная консоль для ваших команд"))
        registry.register(PanelSpec("logs", "LOGS", lambda: self.logs_panel, (360, 220), "Журнал logs/sirius.log"))
        registry.register(PanelSpec("history", "HISTORY", lambda: self.history, (280, 260), "История диалогов"))
        return registry

    def _restore_window_size(self) -> None:
        """Размер окна из настроек, но не больше доступной области экрана (например, 1280x720)."""
        width, height = int(self.settings["window_width"]), int(self.settings["window_height"])
        screen = self.screen()
        if screen is not None:
            available = screen.availableGeometry()
            width = min(width, available.width())
            height = min(height, available.height())
        self.resize(max(width, self.minimumWidth()), max(height, self.minimumHeight()))

    def _sync_control_bar(self) -> None:
        for panel_id in self.panel_registry.ids():
            self.control_bar.set_panel_open(panel_id, self.workspace.is_open(panel_id))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._dark_titlebar_applied:
            self._dark_titlebar_applied = True
            _apply_dark_titlebar(self)

    def _connect_signals(self) -> None:
        self.voice_switch.toggled.connect(self._on_voice_toggled)
        self.settings_btn.clicked.connect(self._open_settings)
        self.avatar.clicked.connect(self._on_avatar_clicked)
        self.chat.send_requested.connect(self._on_send)
        self.chat.stop_requested.connect(self._on_stop_generation)
        self.chat.new_chat_requested.connect(self._new_chat)
        self.control_bar.toggle_panel.connect(self.workspace.toggle)
        self.control_bar.hide_all_requested.connect(self.workspace.hide_all)
        self.control_bar.reset_layout_requested.connect(self.workspace.reset_layout)
        self.workspace.panels_changed.connect(self._sync_control_bar)
        self.history.new_chat.connect(self._new_chat)
        self.history.open_chat.connect(self._open_chat)
        self.history.rename_chat.connect(self._rename_chat)
        self.history.delete_chat.connect(self._delete_chat)
        self.voice.speaking_changed.connect(self._on_speaking_changed)
        self.voice.error.connect(self._on_voice_error)

    # --- пути и утилиты -----------------------------------------------------

    def _resolve(self, path_str: str) -> Path:
        p = Path(path_str)
        return p if p.is_absolute() else self.base_dir / p

    def _set_status_indicator(self, text: str, color: str) -> None:
        self.status_label.setText(f'<span style="color:{color};">●</span> {text}')
        self.status_label.setTextFormat(Qt.TextFormat.RichText)

    # --- Ollama -------------------------------------------------------------

    # --- запуск: Ollama, модель в видеопамять, голос ----------------------------------

    def _start_boot(self, show_overlay: bool = True) -> None:
        """Экран запуска и фоновая загрузка. Интерфейс под экраном уже работает."""
        voice_preload = self.tts.preload if self.voice.enabled else None
        self._boot_worker = BootWorker(self.models, self.engine.num_ctx, voice_preload, self)
        if show_overlay:
            self._boot_overlay = BootOverlay(BOOT_STAGES, self.centralWidget())
            self._boot_worker.stage.connect(self._boot_overlay.set_stage)
            self._boot_overlay.finished.connect(self._on_boot_overlay_closed)
            self._boot_overlay.start()
        self._boot_worker.stage.connect(self._on_boot_stage)
        self._boot_worker.status.connect(self._on_boot_status)
        self._boot_worker.start()

    def _on_boot_stage(self, key: str, state: str, detail: str) -> None:
        if key == "vram" and state == "run":
            self._set_status_indicator("Загрузка модели в видеопамять…", CYAN)
        elif key == "vram" and state == "ok":
            log.info("Модель готова к работе (%s)", detail)

    def _on_boot_status(self, info: StatusInfo) -> None:
        if self._boot_overlay is not None:
            self._boot_overlay.finish()
        self._on_status(info)

    def _on_boot_overlay_closed(self) -> None:
        self._boot_overlay = None

    def _boot_running(self) -> bool:
        return self._boot_worker is not None and self._boot_worker.isRunning()

    def _unload_model_async(self, models: ModelManager) -> None:
        """Выгрузка прежней модели после смены в настройках — без ожидания в GUI-потоке."""
        threading.Thread(target=models.unload, daemon=True, name="sirius-unload").start()

    def _check_ollama(self, try_start: bool = False, quiet: bool = False) -> None:
        if self._closing or (self._status_worker is not None and self._status_worker.isRunning()):
            return
        if self._boot_running():
            return  # проверку уже выполняет загрузка при запуске
        if quiet and (self._generating or self._pull_worker is not None and self._pull_worker.isRunning()):
            return  # во время ответа или загрузки модели состояние и так известно
        # результат придёт раньше, чем можно запустить следующую проверку (очередь событий GUI-потока)
        self._status_quiet = quiet
        self._status_worker = StatusWorker(self.models, try_start, self)
        self._status_worker.result.connect(self._on_status_result)
        self._status_worker.start()

    def _on_status_result(self, info: StatusInfo) -> None:
        self._on_status(info, getattr(self, "_status_quiet", False))

    def _on_status(self, info: StatusInfo, quiet: bool = False) -> None:
        changed = info.status != self._last_status
        self._last_status = info.status
        self._offline = info.status in (OllamaStatus.NOT_RUNNING, OllamaStatus.NOT_INSTALLED)
        self._refresh_avatar()
        if quiet and not changed:
            return
        colors = {
            OllamaStatus.READY: SUCCESS,
            OllamaStatus.NO_MODEL: WARNING,
            OllamaStatus.NOT_RUNNING: ERROR,
            OllamaStatus.NOT_INSTALLED: ERROR,
        }
        self._set_status_indicator(info.message, colors[info.status])
        self.system_panel.set_ollama_status(
            info.message, colors[info.status], info.status == OllamaStatus.READY, self.models.model_name
        )
        # индикатор подключения к модели в заголовке панели CHAT
        self.workspace.set_status("chat", colors[info.status], info.message)
        if self._settings_dialog is not None:
            self._settings_dialog.set_ai_status(info.message)

        if info.status == OllamaStatus.NOT_INSTALLED and not self._install_hint_shown:
            self._install_hint_shown = True
            answer = QMessageBox.question(
                self, "Ollama не установлена",
                "Для работы LISA нужна программа Ollama.\nОткрыть официальную страницу загрузки?",
            )
            if answer == QMessageBox.StandardButton.Yes:
                QDesktopServices.openUrl(QUrl(OLLAMA_DOWNLOAD_URL))
        elif info.status == OllamaStatus.NOT_RUNNING:
            self.statusBar().showMessage("Ollama не запущена: запустите её и проверьте соединение в настройках")
        elif info.status == OllamaStatus.NO_MODEL and not quiet:
            self._ask_pull_model()
        elif info.status == OllamaStatus.READY:
            self.statusBar().showMessage("Модель готова")

    def _ask_pull_model(self) -> None:
        if self._pull_worker is not None and self._pull_worker.isRunning():
            return
        answer = QMessageBox.question(
            self, "Модель не найдена",
            f"Модель «{self.models.model_name}» не загружена.\n"
            f"Загрузить её через Ollama? Размер загрузки: {MODEL_SIZE_HINT}.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._start_pull()

    def _start_pull(self) -> None:
        if self._pull_worker is not None and self._pull_worker.isRunning():
            return
        self._pull_worker = PullWorker(self.models, self)
        self._pull_worker.progress.connect(self._on_pull_progress)
        self._pull_worker.finished_ok.connect(self._on_pull_done)
        self._pull_worker.failed.connect(self._on_pull_failed)
        if self._settings_dialog is not None:
            self._settings_dialog.set_pull_running(True)
        self.statusBar().showMessage("Загрузка модели…")
        self._pull_worker.start()

    def _on_pull_progress(self, status: str, fraction: float) -> None:
        value = None if fraction < 0 else fraction
        if self._settings_dialog is not None:
            self._settings_dialog.set_pull_progress(status, value)
        self.statusBar().showMessage(status)

    def _on_pull_done(self) -> None:
        self._finish_pull_ui()
        self.statusBar().showMessage("Модель загружена")
        self._check_ollama(try_start=False)

    def _on_pull_failed(self, message: str) -> None:
        self._finish_pull_ui()
        QMessageBox.warning(self, "Загрузка модели", message)
        self.statusBar().showMessage("Не удалось загрузить модель")

    def _finish_pull_ui(self) -> None:
        if self._settings_dialog is not None:
            self._settings_dialog.set_pull_running(False)

    # --- генерация ответа ---------------------------------------------------

    def _on_send(self, text: str) -> None:
        if self._generating or self._closing:
            return
        if self._current_chat_id is None:
            self._new_chat()
            if self._current_chat_id is None:
                return
        chat = self.chats.add_message(self._current_chat_id, "user", text)
        if chat is None:
            self.chat.add_message("error", "Не удалось сохранить сообщение: диалог повреждён.")
            return
        self.chat.add_message("user", text)
        self._refresh_chat_list()

        messages = build_messages(chat["messages"], extra_system=self.system_context(text))
        self._leave_heavy_silently()
        if self.compact_bar is not None:
            self.compact_bar.begin_reply()
            self.compact_bar.set_busy(True)
        self._assistant_card = self.chat.add_message("assistant", "")
        self._user_stopped_voice = False
        self._error_flag = False
        self.voice.begin_message()
        self._generating = True
        self.chat.set_busy(True)
        self._refresh_avatar()
        self.statusBar().showMessage("LISA думает…")

        self._worker = GenerationWorker(self.engine, messages, self)
        self._worker.token.connect(self._on_token)
        self._worker.finished_ok.connect(self._on_generation_done)
        self._worker.stats.connect(self.monitor.add_generation)
        self._worker.failed.connect(self._on_generation_failed)
        self._worker.stopped.connect(self._on_generation_stopped)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.start()

    def _on_worker_finished(self) -> None:
        # Ссылка на QThread хранится до его полного завершения, иначе Qt аварийно завершит приложение.
        self._worker = None

    def _on_token(self, delta: str) -> None:
        if self._assistant_card is not None:
            self._assistant_card.append_text(delta)
        if self.compact_bar is not None:
            self.compact_bar.append_reply(delta)
        self.voice.feed(delta)
        self.chat.follow_stream()

    def _on_stop_generation(self) -> None:
        if self._generating and self._worker is not None:
            self._worker.stop()
            self.voice.stop()
            self.statusBar().showMessage("Остановка генерации…")

    def _on_generation_done(self, full_text: str) -> None:
        card = self._assistant_card
        self._assistant_card = None
        if card is not None:
            card.finish()
        if full_text.strip() and self._current_chat_id is not None:
            self.chats.add_message(self._current_chat_id, "assistant", full_text)
            self.code_panel.add_message(full_text)
            self._maybe_auto_title()
        self.voice.finish_message()
        self._end_generation("Готово")

    def _on_generation_stopped(self, partial: str) -> None:
        """Ответ прерван пользователем. Частичный текст на экране остаётся, но в диалог не сохраняется."""
        card = self._assistant_card
        self._assistant_card = None
        if card is not None:
            if partial.strip():
                card.finish()
            else:  # остановили до первого слова: пустую карточку не оставляем
                card.setParent(None)
                card.deleteLater()
        self.voice.stop()
        self._end_generation("Ответ остановлен и не сохранён")

    def _on_generation_failed(self, message: str) -> None:
        if self._assistant_card is not None and not self._assistant_card.text.strip():
            self._assistant_card.setParent(None)
            self._assistant_card.deleteLater()
        elif self._assistant_card is not None:
            self._assistant_card.finish()
        self._assistant_card = None
        self.chat.add_message("error", message)
        self.voice.finish_message()
        self._flash_error()
        self._end_generation("Ошибка генерации")
        self._check_ollama(try_start=False)

    def _end_generation(self, status: str) -> None:
        self._generating = False
        self.chat.set_busy(False)
        if self.compact_bar is not None:
            self.compact_bar.set_busy(False)
        self.statusBar().showMessage(status)
        self._refresh_avatar()
        self.chat.focus_input()

    def _flash_error(self) -> None:
        self._error_flag = True
        self._refresh_avatar()
        QTimer.singleShot(4000, self._clear_error_flag)

    def _clear_error_flag(self) -> None:
        self._error_flag = False
        self._refresh_avatar()

    # --- голос --------------------------------------------------------------

    def _apply_voice_switch_from_settings(self) -> None:
        self.voice_switch.blockSignals(True)
        self.voice_switch.setChecked(False)
        self.voice_switch.blockSignals(False)
        self._update_voice_label()
        if self.settings["voice_enabled"]:
            self._set_voice(True)
        self._update_voice_panel()

    def _update_voice_label(self) -> None:
        self.voice_switch.setText("VOICE ON" if self.voice_switch.isChecked() else "VOICE OFF")

    def _on_voice_toggled(self, checked: bool) -> None:
        self._set_voice(checked)

    def _set_voice(self, enabled: bool) -> bool:
        """Включает или выключает голос. Возвращает фактическое состояние."""
        if enabled and not self.voice.check_available():
            enabled = False
        self.voice.set_enabled(enabled)
        self.voice_switch.blockSignals(True)
        self.voice_switch.setChecked(enabled)
        self.voice_switch.blockSignals(False)
        self._update_voice_label()
        if self.compact_bar is not None:
            self.compact_bar.set_voice(enabled)
        self.settings["voice_enabled"] = enabled
        self._save_settings()
        self._update_voice_panel()
        return enabled

    def _update_voice_panel(self) -> None:
        """Состояние голоса для панели SYSTEM. Последняя ошибка голоса видна, пока голос не включён снова."""
        if self.voice.enabled:
            self._voice_error = ""
        if self._voice_error:
            self.system_panel.set_voice_state(f"Недоступен: {self._voice_error}", ERROR)
        elif not self.voice.enabled:
            self.system_panel.set_voice_state("Выключен (VOICE OFF)", TEXT_SECONDARY)
        elif self._speaking:
            self.system_panel.set_voice_state("Говорит", CYAN)
        else:
            engine = (f"Silero {self.tts.speaker}" if self.tts.active_engine() == "silero" else "Piper")
            self.system_panel.set_voice_state(f"Включён, готов ({engine})", SUCCESS)

    def _on_speaking_changed(self, speaking: bool) -> None:
        self._speaking = speaking
        self._refresh_avatar()
        self._update_voice_panel()

    def _on_voice_error(self, message: str) -> None:
        self.statusBar().showMessage(f"Голос недоступен: {message}")
        log.warning("Голос недоступен: %s", message)
        self.voice_switch.blockSignals(True)
        self.voice_switch.setChecked(False)
        self.voice_switch.blockSignals(False)
        self._update_voice_label()
        self._voice_error = message
        self._update_voice_panel()

    def _on_avatar_clicked(self) -> None:
        if self.voice.is_speaking():
            self.voice.stop()
            self._user_stopped_voice = True
            self._refresh_avatar()

    def _refresh_avatar(self) -> None:
        """Приоритет: ERROR > SPEAKING > THINKING > OFFLINE > STOPPED > IDLE."""
        if self._error_flag:
            state = AvatarState.ERROR
        elif self._speaking:
            state = AvatarState.SPEAKING
        elif self._generating:
            state = AvatarState.THINKING
        elif self._offline:
            state = AvatarState.OFFLINE
        elif self._user_stopped_voice:
            state = AvatarState.STOPPED
        else:
            state = AvatarState.IDLE
        self.avatar.set_state(state)
        if self.compact_bar is not None:
            self.compact_bar.set_state(state)

    # --- диалоги ------------------------------------------------------------

    def _refresh_chat_list(self) -> None:
        self.history.set_chats(self.chats.list_chats(), self._current_chat_id)

    def _open_latest_or_new(self) -> None:
        chats = self.chats.list_chats()
        if chats:
            self._open_chat(chats[0]["file_id"])
        else:
            self._new_chat()

    def _busy_guard(self) -> bool:
        if self._generating:
            self.statusBar().showMessage("Дождитесь окончания ответа или остановите генерацию")
            return True
        return False

    def _start_new_session(self) -> None:
        """При запуске всегда открывается новый диалог; пустые диалоги не копятся."""
        self.chats.delete_empty_chats()
        self._new_chat()

    def _clear_temp_audio(self) -> None:
        """Удаляет WAV-файлы, оставшиеся от прошлых запусков (их держал плеер или сбой)."""
        for path in (self.data_dir / "tmp").glob("tts_*.wav"):
            try:
                path.unlink()
            except OSError:
                pass

    def _new_chat(self) -> None:
        if self._busy_guard():
            return
        self.chats.delete_empty_chats()
        chat = self.chats.create_chat()
        self._open_chat(chat["file_id"])

    def _maybe_auto_title(self) -> None:
        """После первого обмена репликами придумывает название диалога по теме."""
        file_id = self._current_chat_id
        if file_id is None or (self._title_worker is not None and self._title_worker.isRunning()):
            return
        chat = self.chats.load_chat(file_id)
        if chat is None or chat["title"] != DEFAULT_TITLE:
            return
        users = [m for m in chat["messages"] if m.get("role") == "user"]
        if len(users) != 1:
            return
        self._title_worker = TitleWorker(self.engine, file_id, users[0]["text"], self)
        self._title_worker.done.connect(self._on_title_ready)
        self._title_worker.start()

    def _on_title_ready(self, file_id: str, title: str) -> None:
        chat = self.chats.load_chat(file_id)
        if chat is None or chat["title"] != DEFAULT_TITLE or not title:
            return  # пользователь уже переименовал или диалог удалён
        if self.chats.rename_chat(file_id, title) and file_id == self._current_chat_id:
            self.setWindowTitle(f"SIRIUS — {title}")
        self._refresh_chat_list()

    def _open_chat(self, file_id: str) -> None:
        if self._busy_guard():
            return
        chat = self.chats.load_chat(file_id)
        if chat is None:
            QMessageBox.warning(self, "Диалог", "Этот диалог повреждён и не может быть открыт.")
            self._refresh_chat_list()
            return
        self._current_chat_id = file_id
        self.chat.clear_messages()
        self.code_panel.set_messages(
            [m.get("text", "") for m in chat["messages"] if m.get("role") == "assistant"]
        )
        for item in chat["messages"]:
            role = item.get("role")
            if role == "assistant":
                card = self.chat.add_message("assistant", item.get("text", ""))
                card.finish()
            elif role == "user":
                self.chat.add_message("user", item.get("text", ""))
        self.setWindowTitle(f"SIRIUS — {chat['title']}")
        self._refresh_chat_list()
        self.chat.focus_input()

    def _rename_chat(self, file_id: str) -> None:
        if self._busy_guard():
            return
        chat = self.chats.load_chat(file_id)
        if chat is None:
            return
        title, ok = QInputDialog.getText(self, "Переименовать диалог", "Название:", text=chat["title"])
        if ok and self.chats.rename_chat(file_id, title):
            if file_id == self._current_chat_id:
                self.setWindowTitle(f"SIRIUS — {title.strip() or 'Без названия'}")
            self._refresh_chat_list()

    def _delete_chat(self, file_id: str) -> None:
        if self._busy_guard():
            return
        answer = QMessageBox.question(self, "Удаление диалога", "Удалить этот диалог? Это действие необратимо.")
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.chats.delete_chat(file_id)
        if file_id == self._current_chat_id:
            self._current_chat_id = None
            self.chat.clear_messages()
            self._open_latest_or_new()
        self._refresh_chat_list()

    # --- настройки ----------------------------------------------------------

    def _save_settings(self) -> None:
        # компоновку берём из рабочего пространства в момент записи: копия настроек из окна
        # настроек или другого места не может затереть свежее расположение панелей
        if hasattr(self, "workspace"):
            self.settings["workspace"] = self.workspace.state()
        try:
            self.settings_store.save(self.settings)
        except OSError as exc:
            log.error("Не удалось сохранить настройки: %s", exc)
            self.statusBar().showMessage("Не удалось сохранить настройки")

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.settings, self)
        self._settings_dialog = dlg
        dlg.check_requested.connect(lambda: self._check_ollama(try_start=True))
        dlg.pull_requested.connect(self._start_pull)
        dlg.test_voice_requested.connect(lambda: self._test_voice(dlg))
        dlg.finished.connect(lambda _code: setattr(self, "_settings_dialog", None))
        self._check_ollama(try_start=False)
        if dlg.exec() == SettingsDialog.DialogCode.Accepted:
            self._apply_settings(dlg.values())
            if dlg.layout_reset:
                self.workspace.reset_layout()
                self._save_settings()
        else:
            self._apply_voice_runtime(self.settings)

    def _test_voice(self, dlg: SettingsDialog) -> None:
        values = dlg.values()
        self._apply_voice_runtime(values)
        if not self.voice.check_available():
            return
        self.voice.say(SAMPLE_PHRASE)

    def _apply_voice_runtime(self, values: dict) -> None:
        self.tts.set_model_path(self._resolve(values["voice_model_path"]))
        self.tts.set_engine(values.get("voice_engine", "silero"),
                            self._resolve(values.get("silero_model_path", "resources/voices/silero_v4_ru.pt")),
                            values.get("voice_speaker", "xenia"))
        self.voice.set_volume(int(values["voice_volume"]))
        self.voice.set_speed(float(values["voice_speed"]))
        self.voice.set_style(VoiceStyle.from_settings(values))

    def _apply_settings(self, values: dict) -> None:
        self.settings = values
        if (values["model_name"] != self.models.model_name
                or values["ollama_url"].rstrip("/") != self.models.base_url):
            # прежняя модель больше не нужна: освобождаем видеопамять сразу, а не через KEEP_ALIVE
            self._unload_model_async(ModelManager(self.models.base_url, self.models.model_name))
        self.models.update(values["ollama_url"], values["model_name"])
        self.engine.base_url = values["ollama_url"].rstrip("/")
        self.engine.model_name = values["model_name"]
        self.monitor.model_name = values["model_name"]
        self._apply_monitor_settings(values)
        self._sync_autostart(values.get("autostart", False))
        self._apply_voice_runtime(values)
        self._save_settings()
        if values["voice_enabled"] != self.voice_switch.isChecked():
            self._set_voice(bool(values["voice_enabled"]))
        self._check_ollama(try_start=False)
        self.statusBar().showMessage("Настройки сохранены")

    # --- завершение ---------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Порядок завершения: генерация → голос → загрузка модели → проверка Ollama → название → панели."""
        if self._close_to_tray_requested(event):
            return
        self._closing = True
        self._status_timer.stop()
        if self._worker is not None:
            self._worker.stop()
        self._wait_for(self._worker, 3000, "генерация ответа")
        self.voice.shutdown()
        if self._pull_worker is not None:
            self._pull_worker.cancel()
        self._wait_for(self._pull_worker, 5000, "загрузка модели")
        if self._status_worker is not None:
            self._status_worker.cancel()
        self._wait_for(self._status_worker, 5000, "проверка Ollama")
        if self._boot_worker is not None:
            self._boot_worker.cancel()
        self._wait_for(self._boot_worker, 5000, "загрузка при запуске")
        # модель больше не нужна: сразу освобождаем видеопамять (иначе Ollama держит её KEEP_ALIVE)
        self.models.unload()
        self._wait_for(self._title_worker, 5000, "название диалога")
        self.workspace.close_all_resources()
        self.system_panel.shutdown()
        self._shutdown_v03()
        self.logs_panel.shutdown()
        self.terminal_panel.shutdown()
        self.settings["window_width"] = self.width()
        self.settings["window_height"] = self.height()
        self._save_settings()
        log.info("Приложение закрыто")
        super().closeEvent(event)

    @staticmethod
    def _wait_for(thread, timeout_ms: int, name: str) -> None:
        if thread is None or not thread.isRunning():
            return
        if not thread.wait(timeout_ms):
            log.error("Фоновая задача «%s» не завершилась за %d мс", name, timeout_ms)


def _apply_dark_titlebar(window: QWidget) -> None:
    """Тёмный системный заголовок окна Windows 10/11 (DWMWA_USE_IMMERSIVE_DARK_MODE).

    Только оформление: при любой ошибке остаётся обычный заголовок.
    """
    import sys

    if sys.platform != "win32":
        return
    try:
        import ctypes

        value = ctypes.c_int(1)
        hwnd = int(window.winId())
        for attribute in (20, 19):  # 20 — Windows 10 2004+ и 11, 19 — более ранние сборки
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)
            ) == 0:
                return
    except Exception:
        log.debug("Не удалось включить тёмный заголовок окна", exc_info=True)
