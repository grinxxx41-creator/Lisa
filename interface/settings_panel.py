"""Окно настроек: AI, голос, интерфейс. Сохранение выполняет главное окно."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
    QProgressBar, QPushButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget,
)

from core.model_manager import MODEL_SIZE_HINT
from interface.island.settings_tab import IslandSettingsTab
from interface.motion import animate_tabs
from interface.styles import THEME_TITLES, normalize_theme
from voice.audio_effects import GENTLE, ORIGINAL, PITCH_RANGE, VoiceStyle


class SettingsDialog(QDialog):
    check_requested = Signal()
    pull_requested = Signal()
    test_voice_requested = Signal()

    def __init__(self, settings: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Настройки SIRIUS")
        self.setMinimumWidth(520)
        self._settings = dict(settings)
        self.layout_reset = False  # «Восстановить интерфейс»: после сохранения панели встанут на стандартные места

        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        animate_tabs(self.tabs)
        self.tabs.addTab(self._build_ai_tab(), "AI")
        self.tabs.addTab(self._build_voice_tab(), "Голос")
        self.tabs.addTab(self._build_interface_tab(), "Интерфейс")
        self.tabs.addTab(self._build_monitoring_tab(), "Мониторинг")
        self.island_tab = IslandSettingsTab(self._settings.get("island"))
        self.tabs.addTab(self.island_tab, "Островок")
        root.addWidget(self.tabs)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Сохранить")
        save.setObjectName("primary")
        save.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)

    # --- вкладки ------------------------------------------------------------

    def _build_ai_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.url_edit = QLineEdit(self._settings["ollama_url"])
        self.model_edit = QLineEdit(self._settings["model_name"])
        form.addRow("Адрес Ollama:", self.url_edit)
        form.addRow("Название модели:", self.model_edit)

        self.ai_status = QLabel("—")
        self.ai_status.setObjectName("secondary")
        form.addRow("Состояние:", self.ai_status)

        row = QHBoxLayout()
        check = QPushButton("Проверить соединение")
        check.clicked.connect(self.check_requested.emit)
        self.pull_btn = QPushButton(f"Загрузить модель ({MODEL_SIZE_HINT})")
        self.pull_btn.clicked.connect(self.pull_requested.emit)
        row.addWidget(check)
        row.addWidget(self.pull_btn)
        form.addRow(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setVisible(False)
        form.addRow(self.progress)
        return w

    def _build_voice_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.voice_check = QCheckBox("Озвучивать ответы LISA")
        self.voice_check.setChecked(bool(self._settings["voice_enabled"]))
        form.addRow(self.voice_check)

        # v0.2.5: голос Silero (естественнее) или Piper (запасной, если нет PyTorch или модели)
        self.engine_combo = QComboBox()
        self.engine_combo.addItem("Silero — естественный голос", "silero")
        self.engine_combo.addItem("Piper — запасной голос", "piper")
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(self._settings.get("voice_engine", "silero"))))
        form.addRow("Движок речи:", self.engine_combo)
        self.speaker_combo = QComboBox()
        for name, title in (("xenia", "Ксения (xenia)"), ("baya", "Бая (baya)"), ("kseniya", "Ксения 2 (kseniya)")):
            self.speaker_combo.addItem(title, name)
        self.speaker_combo.setCurrentIndex(max(0, self.speaker_combo.findData(self._settings.get("voice_speaker", "xenia"))))
        form.addRow("Голос Silero:", self.speaker_combo)

        path_row = QHBoxLayout()
        self.voice_path = QLineEdit(self._settings["voice_model_path"])
        browse = QPushButton("Выбрать…")
        browse.setObjectName("small")
        browse.clicked.connect(self._browse_voice)
        path_row.addWidget(self.voice_path, 1)
        path_row.addWidget(browse)
        form.addRow("Модель Piper (.onnx):", path_row)

        self.volume_slider, self.volume_label = self._slider(0, 100, int(self._settings["voice_volume"]), "%")
        form.addRow("Громкость:", _row(self.volume_slider, self.volume_label))

        speed_value = int(round(float(self._settings["voice_speed"]) * 100))
        self.speed_slider, self.speed_label = self._slider(50, 200, speed_value, "×", scale=100)
        form.addRow("Скорость речи:", _row(self.speed_slider, self.speed_label))

        # тембр: высота и мягкость голоса (обработка звука после синтеза Piper)
        style = VoiceStyle.from_settings(self._settings)
        self.pitch_slider = QSlider(Qt.Orientation.Horizontal)
        self.pitch_slider.setRange(int(PITCH_RANGE[0]), int(PITCH_RANGE[1]))
        self.pitch_slider.setValue(int(round(style.pitch)))
        self.pitch_label = QLabel()
        self.pitch_label.setMinimumWidth(56)
        self.pitch_slider.valueChanged.connect(lambda v: self.pitch_label.setText(f"{v:+d}%"))
        self.pitch_label.setText(f"{self.pitch_slider.value():+d}%")
        self.pitch_slider.setToolTip("Выше — голос легче и нежнее. Темп речи не меняется.")
        form.addRow("Высота голоса:", _row(self.pitch_slider, self.pitch_label))
        self.softness_slider, self.softness_label = self._slider(0, 100, style.softness, "%")
        self.softness_slider.setToolTip("Смягчает резкие высокие звуки (с, ш, ч)")
        form.addRow("Мягкость:", _row(self.softness_slider, self.softness_label))

        presets = QHBoxLayout()
        gentle = QPushButton("Нежный голос")
        gentle.setObjectName("small")
        gentle.setToolTip("Высота +4%, мягкость 60%, скорость 1.0")
        gentle.clicked.connect(lambda: self._apply_voice_preset(GENTLE, 1.0))
        original = QPushButton("Исходный голос")
        original.setObjectName("small")
        original.setToolTip("Голос Piper без обработки, как в v0.1")
        original.clicked.connect(lambda: self._apply_voice_preset(ORIGINAL, 1.0))
        presets.addWidget(gentle)
        presets.addWidget(original)
        presets.addStretch(1)
        form.addRow("Тембр:", presets)

        test = QPushButton("Тестовое воспроизведение")
        test.clicked.connect(self.test_voice_requested.emit)
        form.addRow(test)
        return w

    def _build_interface_tab(self) -> QWidget:
        w = QWidget()
        form = QFormLayout(w)
        self.theme_combo = QComboBox()
        for theme_id, theme_title in THEME_TITLES:
            self.theme_combo.addItem(theme_title, theme_id)
        self.theme_combo.setCurrentIndex(max(0, self.theme_combo.findData(normalize_theme(self._settings.get("theme")))))
        form.addRow("Тема:", self.theme_combo)
        theme_hint = QLabel("Тема меняет всё окно и островок и применяется после перезапуска SIRIUS. "
                            "В темах Nothing и iPhone аватара LISA в центре нет.")
        theme_hint.setObjectName("secondary")
        theme_hint.setWordWrap(True)
        form.addRow(theme_hint)
        self.width_spin = QSpinBox()
        self.width_spin.setRange(900, 3840)
        self.width_spin.setValue(int(self._settings["window_width"]))
        self.height_spin = QSpinBox()
        self.height_spin.setRange(600, 2160)
        self.height_spin.setValue(int(self._settings["window_height"]))
        form.addRow("Ширина окна:", self.width_spin)
        form.addRow("Высота окна:", self.height_spin)
        reset = QPushButton("Восстановить интерфейс")
        reset.clicked.connect(self._reset_interface)
        form.addRow(reset)
        self.reset_hint = QLabel("Сбрасывает размер окна и расположение панелей рабочего пространства")
        self.reset_hint.setObjectName("secondary")
        self.reset_hint.setWordWrap(True)
        form.addRow(self.reset_hint)
        return w

    def _build_monitoring_tab(self) -> QWidget:
        from monitoring.alerts import DEFAULT_THRESHOLDS

        w = QWidget()
        form = QFormLayout(w)
        self.alerts_check = QCheckBox("Предупреждать о перегреве, нехватке памяти, места и заряда")
        self.alerts_check.setChecked(bool(self._settings.get("alerts_enabled", True)))
        form.addRow(self.alerts_check)
        self.alert_voice_check = QCheckBox("LISA сообщает о предупреждениях голосом (если голос включён)")
        self.alert_voice_check.setChecked(bool(self._settings.get("alert_voice", False)))
        form.addRow(self.alert_voice_check)
        saved = self._settings.get("alert_thresholds") or {}
        self.threshold_spins: dict[str, QSpinBox] = {}
        rows = (
            ("vram", "Видеопамять, %:", 50, 100), ("ram", "Оперативная память, %:", 50, 100),
            ("cpu", "Процессор (15 с подряд), %:", 50, 100), ("gpu_temp", "Температура видеокарты, °C:", 50, 105),
            ("cpu_temp", "Температура процессора, °C:", 50, 105),
            ("disk_free_gb", "Свободно на диске C: меньше, ГБ:", 1, 200),
            ("battery", "Заряд батареи меньше, %:", 5, 50),
        )
        for key, title, lo, hi in rows:
            spin = QSpinBox()
            spin.setRange(lo, hi)
            spin.setValue(int(float(saved.get(key, DEFAULT_THRESHOLDS[key]))))
            form.addRow(title, spin)
            self.threshold_spins[key] = spin
        self.tray_check = QCheckBox("Закрытие окна сворачивает SIRIUS в трей (модель остаётся в памяти)")
        self.tray_check.setChecked(bool(self._settings.get("close_to_tray", False)))
        form.addRow(self.tray_check)
        self.autostart_check = QCheckBox("Запускать SIRIUS вместе с Windows")
        self.autostart_check.setChecked(bool(self._settings.get("autostart", False)))
        form.addRow(self.autostart_check)
        return w

    # --- helpers ------------------------------------------------------------

    def _slider(self, lo: int, hi: int, value: int, suffix: str, scale: int = 1):
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(lo, hi)
        slider.setValue(value)
        label = QLabel()
        label.setMinimumWidth(56)

        def refresh(v: int) -> None:
            label.setText(f"{v / scale:.2f}{suffix}" if scale > 1 else f"{v}{suffix}")

        slider.valueChanged.connect(refresh)
        refresh(value)
        return slider, label

    def _browse_voice(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Голосовая модель Piper", "", "Piper voice (*.onnx)")
        if path:
            self.voice_path.setText(path)

    def _apply_voice_preset(self, style: VoiceStyle, speed: float) -> None:
        self.pitch_slider.setValue(int(round(style.pitch)))
        self.softness_slider.setValue(int(style.softness))
        self.speed_slider.setValue(int(round(speed * 100)))

    def _reset_interface(self) -> None:
        from storage.settings_storage import DEFAULT_SETTINGS

        self.width_spin.setValue(int(DEFAULT_SETTINGS["window_width"]))
        self.height_spin.setValue(int(DEFAULT_SETTINGS["window_height"]))
        self.layout_reset = True
        self.reset_hint.setText("Размер окна и расположение панелей будут сброшены после сохранения")

    # --- публичный интерфейс для главного окна -------------------------------

    def set_ai_status(self, text: str) -> None:
        self.ai_status.setText(text)

    def set_pull_progress(self, text: str, fraction: float | None) -> None:
        self.progress.setVisible(True)
        if fraction is None or fraction < 0:
            self.progress.setRange(0, 0)  # неопределённый прогресс
        else:
            self.progress.setRange(0, 100)
            self.progress.setValue(int(fraction * 100))
        self.ai_status.setText(text)

    def set_pull_running(self, running: bool) -> None:
        self.pull_btn.setEnabled(not running)
        if not running:
            self.progress.setVisible(False)
            self.progress.setRange(0, 100)

    def values(self) -> dict[str, Any]:
        result = dict(self._settings)
        result.update({
            "ollama_url": self.url_edit.text().strip() or self._settings["ollama_url"],
            "model_name": self.model_edit.text().strip() or self._settings["model_name"],
            "voice_enabled": self.voice_check.isChecked(),
            "voice_model_path": self.voice_path.text().strip(),
            "voice_volume": self.volume_slider.value(),
            "voice_speed": self.speed_slider.value() / 100.0,
            "voice_pitch": float(self.pitch_slider.value()),
            "voice_softness": self.softness_slider.value(),
            "voice_engine": self.engine_combo.currentData(),
            "voice_speaker": self.speaker_combo.currentData(),
            "silero_model_path": self._settings.get("silero_model_path", "resources/voices/silero_v4_ru.pt"),
            "theme": self.theme_combo.currentData(),
            "window_width": self.width_spin.value(),
            "window_height": self.height_spin.value(),
            "alerts_enabled": self.alerts_check.isChecked(),
            "alert_voice": self.alert_voice_check.isChecked(),
            "alert_thresholds": {k: float(s.value()) for k, s in self.threshold_spins.items()},
            "close_to_tray": self.tray_check.isChecked(),
            "autostart": self.autostart_check.isChecked(),
            "island": self.island_tab.values(),
        })
        return result


def _row(*widgets: QWidget) -> QWidget:
    w = QWidget()
    layout = QHBoxLayout(w)
    layout.setContentsMargins(0, 0, 0, 0)
    for widget in widgets:
        layout.addWidget(widget, 1 if widget is widgets[0] else 0)
    return w
