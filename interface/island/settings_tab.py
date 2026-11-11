"""Вкладка «Островок» окна настроек SIRIUS. Значения сохраняет главное окно вместе с остальными
настройками (settings.json["island"])."""

from __future__ import annotations

import os
from typing import Any

from PySide6.QtCore import Qt

from interface.styles import CYAN
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog,
                               QLabel, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

from island.actions import validate_target
from island.settings import MAX_CUSTOM_ACTIONS, RANGES, normalize

POSITION_TITLES = (("top", "Сверху по центру"), ("top-left", "Сверху слева"), ("top-right", "Сверху справа"),
                   ("bottom", "Снизу по центру"), ("custom", "Своё место (задано перетаскиванием)"))
THEME_TITLES = (("graphite", "Графит"), ("black", "Чёрная"), ("sirius", "SIRIUS — тёмно-синяя с голубой каймой"))
VISUALIZER_TITLES = (("bars", "Столбики уровня"), ("wave", "Волна"), ("pulse", "Пульс от центра"))


class IslandSettingsTab(QWidget):
    def __init__(self, settings: Any, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = normalize(settings)
        self.clear_shelf = False          # «Очистить полку» — выполняет главное окно после сохранения
        self.clear_clipboard = False
        self.checks: dict[str, QCheckBox] = {}
        self.spins: dict[str, QSpinBox] = {}
        self.combos: dict[str, QComboBox] = {}
        self.sliders: dict[str, QSlider] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        self.form = QFormLayout(host)
        scroll.setWidget(host)
        outer.addWidget(scroll)

        self._section("Островок")
        self._check("enabled", "Живой островок: события, музыка, уведомления и расширенные режимы",
                    "Выключено — остаётся прежняя компактная полоска без событий")
        self._check("show_always", "Показывать островок всегда, а не только в компактном режиме")
        self._combo("position", "Положение:", POSITION_TITLES, skip=() if self._cfg["custom_pos"] else ("custom",))
        self._spin("width", "Ширина капсулы, px:")
        self._spin("height", "Высота капсулы, px:")
        self._slider("opacity", "Непрозрачность фона:", "%")
        self._combo("theme", "Тема:", THEME_TITLES)

        self._section("Анимации и поведение")
        self._check("animations", "Плавные анимации")
        self._slider("animation_speed", "Скорость анимаций:", "%")
        self._spin("auto_collapse_s", "Сворачивать без действий через, с:")
        self._check("lisa_expand", "Раскрывать ответ LISA, когда вопрос задан в островке")

        self._section("Музыка")
        self._check("media", "Показывать, что сейчас играет, и управлять плеером",
                    "Работает с любым плеером, который виден Windows: Spotify, браузеры, VLC, AIMP и другие")
        self._check("media_popup", "Показывать новую композицию при смене трека")
        self._check("visualizer", "Визуализатор уровня звука")
        self._combo("visualizer_style", "Вид визуализатора:", VISUALIZER_TITLES)

        self._section("Системные индикаторы")
        self._check("indicators", "Показывать изменение громкости и яркости")
        self._check("lock_keys", "Показывать Caps Lock и Num Lock")
        self._check("battery_events", "Показывать подключение и отключение питания")

        self._section("Уведомления")
        self._check("notifications", "Уведомления SIRIUS: предупреждения мониторинга, Pomodoro, LISA")
        self._check("notifications_windows", "Уведомления Windows от других приложений",
                    "SIRIUS читает уведомления Windows только на этом компьютере и никуда их не передаёт.\n"
                    "Windows может спросить разрешение на доступ к уведомлениям.")
        self._spin("notification_seconds", "Показывать уведомление, с:")

        self._section("Файловая полка")
        self._check("shelf", "Полка: перетащите файлы на островок, чтобы держать их под рукой")
        self._spin("shelf_limit", "Файлов на полке, не больше:")
        self._action_button("Очистить полку", "clear_shelf", "Полка будет очищена после сохранения. Файлы на диске останутся.")

        self._section("История буфера обмена")
        self._check("clipboard", "Запоминать скопированный текст")
        self._spin("clipboard_limit", "Записей в истории, не больше:")
        self._check("clipboard_persist", "Сохранять историю между запусками SIRIUS",
                    "История записывается в storage/island.json в открытом виде")
        self._check("clipboard_allow_secrets", "Сохранять и то, что похоже на пароли, токены и ключи",
                    "По умолчанию такие записи в историю не попадают")
        self._action_button("Очистить историю", "clear_clipboard", "История буфера будет очищена после сохранения.")

        self._section("Pomodoro")
        self._check("pomodoro", "Таймер Pomodoro")
        self._spin("pomodoro_work", "Работа, мин:")
        self._spin("pomodoro_short", "Короткий перерыв, мин:")
        self._spin("pomodoro_long", "Длинный перерыв, мин:")
        self._spin("pomodoro_rounds", "Рабочих отрезков до длинного перерыва:")
        self._check("pomodoro_restore", "Восстанавливать таймер после перезапуска SIRIUS")

        self._section("Быстрые действия")
        self._check("actions", "Быстрые действия в островке")
        self.actions_list = QListWidget()
        self.actions_list.setFixedHeight(96)
        for item in self._cfg["custom_actions"]:
            self._add_action_item(item["title"], item["target"])
        self.form.addRow("Свои действия:", self.actions_list)
        row = QHBoxLayout()
        for title, slot in (("Приложение или файл…", self._add_file), ("Папка…", self._add_folder),
                            ("Сайт…", self._add_url), ("Удалить", self._remove_action)):
            button = QPushButton(title)
            button.setObjectName("small")
            button.clicked.connect(slot)
            row.addWidget(button)
        row.addStretch(1)
        self.form.addRow(row)
        self.actions_hint = QLabel("Действие открывает выбранный файл, папку, приложение или сайт — "
                                   "так же, как двойной щелчок в проводнике.")
        self.actions_hint.setObjectName("secondary")
        self.actions_hint.setWordWrap(True)
        self.form.addRow(self.actions_hint)

    # --- построение строк ------------------------------------------------------------

    def _section(self, title: str) -> None:
        caption = QLabel(title.upper())
        caption.setStyleSheet(f"color: {CYAN}; font-size: 11px; font-weight: 600; letter-spacing: 2px; margin-top: 10px;")
        self.form.addRow(caption)

    def _check(self, key: str, text: str, tip: str = "") -> None:
        box = QCheckBox(text)
        box.setChecked(bool(self._cfg[key]))
        box.setToolTip(tip)
        self.checks[key] = box
        self.form.addRow(box)

    def _spin(self, key: str, title: str) -> None:
        spin = QSpinBox()
        spin.setRange(*RANGES[key])
        spin.setValue(int(self._cfg[key]))
        self.spins[key] = spin
        self.form.addRow(title, spin)

    def _slider(self, key: str, title: str, suffix: str) -> None:
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(*RANGES[key])
        slider.setValue(int(self._cfg[key]))
        value = QLabel(f"{slider.value()}{suffix}")
        value.setMinimumWidth(48)
        slider.valueChanged.connect(lambda v: value.setText(f"{v}{suffix}"))
        row = QHBoxLayout()
        row.addWidget(slider, 1)
        row.addWidget(value)
        self.sliders[key] = slider
        self.form.addRow(title, row)

    def _combo(self, key: str, title: str, items, skip: tuple = ()) -> None:
        combo = QComboBox()
        for value, text in items:
            if value not in skip:
                combo.addItem(text, value)
        combo.setCurrentIndex(max(0, combo.findData(self._cfg[key])))
        self.combos[key] = combo
        self.form.addRow(title, combo)

    def _action_button(self, title: str, flag: str, done_text: str) -> None:
        button = QPushButton(title)
        button.setObjectName("small")
        note = QLabel("")
        note.setObjectName("secondary")
        note.setWordWrap(True)

        def mark() -> None:
            setattr(self, flag, True)
            note.setText(done_text)

        button.clicked.connect(mark)
        row = QHBoxLayout()
        row.addWidget(button)
        row.addWidget(note, 1)
        self.form.addRow(row)

    # --- свои действия ---------------------------------------------------------------

    def _add_action_item(self, title: str, target: str) -> None:
        item = QListWidgetItem(f"{title}  —  {target}")
        item.setData(Qt.ItemDataRole.UserRole, (title, target))
        item.setToolTip(target)
        self.actions_list.addItem(item)

    def _add_target(self, target: str, title: str = "") -> None:
        target = target.strip()
        if not target:
            return
        problem = validate_target(target)
        if problem:
            self.actions_hint.setText(problem)
            return
        if self.actions_list.count() >= MAX_CUSTOM_ACTIONS:
            self.actions_hint.setText(f"Своих действий может быть не больше {MAX_CUSTOM_ACTIONS}.")
            return
        default = title or os.path.splitext(os.path.basename(target.rstrip("\\/")))[0] or target
        name, ok = QInputDialog.getText(self, "Быстрое действие", "Название:", text=default[:60])
        if ok and name.strip():
            self._add_action_item(name.strip()[:60], target)

    def _add_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Приложение или файл", "", "Все файлы (*)")
        if path:
            self._add_target(os.path.normpath(path))

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Папка")
        if path:
            self._add_target(os.path.normpath(path))

    def _add_url(self) -> None:
        url, ok = QInputDialog.getText(self, "Сайт", "Адрес (http:// или https://):", text="https://")
        if ok and url.strip() not in ("", "https://"):
            self._add_target(url.strip(), title=url.strip().split("//", 1)[-1].split("/", 1)[0])

    def _remove_action(self) -> None:
        row = self.actions_list.currentRow()
        if row >= 0:
            self.actions_list.takeItem(row)

    # --- результат -------------------------------------------------------------------

    def values(self) -> dict[str, Any]:
        result = dict(self._cfg)
        result.update({key: box.isChecked() for key, box in self.checks.items()})
        result.update({key: spin.value() for key, spin in self.spins.items()})
        result.update({key: slider.value() for key, slider in self.sliders.items()})
        result.update({key: combo.currentData() for key, combo in self.combos.items()})
        if result["position"] != "custom":
            result["custom_pos"] = None
        actions = []
        for index in range(self.actions_list.count()):
            title, target = self.actions_list.item(index).data(Qt.ItemDataRole.UserRole)
            actions.append({"title": title, "target": target})
        result["custom_actions"] = actions
        return normalize(result)
