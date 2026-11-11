"""Настройки приложения, хранятся в storage/settings.json."""

from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any

from storage.storage_manager import atomic_write_json, read_json_safe

log = logging.getLogger("sirius.settings")

OLD_DEFAULT_SPEED = 1.2
# localhost на Windows сначала пробует IPv6 и теряет ~2 с на каждый запрос; 127.0.0.1 — 13 мс.
OLD_DEFAULT_URL = "http://localhost:11434"

DEFAULT_SETTINGS: dict[str, Any] = {
    "ollama_url": "http://127.0.0.1:11434",
    "model_name": "qwen3:8b-q4_K_M",
    "voice_enabled": False,
    "voice_model_path": "resources/voices/ru_RU-irina-medium.onnx",
    "voice_engine": "silero",  # v0.2.5: "silero" (голос xenia) или "piper" (запасной)
    "silero_model_path": "resources/voices/silero_v4_ru.pt",
    "voice_speaker": "xenia",
    "voice_volume": 80,       # 0..100
    "voice_speed": 1.0,       # множитель скорости речи (до v0.2.3 по умолчанию было 1.2 — слишком быстро)
    "voice_pitch": 4.0,       # v0.2.3: высота голоса, % (−8..+12)
    "voice_softness": 60,     # v0.2.3: мягкость тембра, 0..100
    "theme": "nothing",       # тема оформления: interface/styles.THEMES (меняется после перезапуска)
    "window_width": 1280,
    "window_height": 800,
    # v0.2: расположение панелей рабочего пространства (координаты, размеры, видимость, порядок
    # наложения, активная панель, компоновка). Пустой словарь — стандартная компоновка.
    # Содержимое проверяет interface/workspace/panel_layout.parse_state.
    "workspace": {},
    # v0.3: мониторинг
    "alerts_enabled": True,     # предупреждения о перегреве, памяти, диске, батарее
    "alert_voice": False,       # LISA произносит предупреждения (только если голос включён)
    "alert_thresholds": {},     # переопределения порогов monitoring.alerts.DEFAULT_THRESHOLDS
    "close_to_tray": False,     # закрытие окна сворачивает SIRIUS в трей (модель остаётся в памяти)
    "autostart": False,         # запуск вместе с Windows (HKCU\...\Run)
    # Островок (Living Island): развитие компактного режима. Пустой словарь — значения по умолчанию.
    # Содержимое проверяет island/settings.normalize.
    "island": {},
}


class SettingsStorage:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, Any]:
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        stored = read_json_safe(self.path)
        if isinstance(stored, dict):
            for key, value in stored.items():
                if key not in DEFAULT_SETTINGS:
                    continue
                if isinstance(DEFAULT_SETTINGS[key], dict) and not isinstance(value, dict):
                    log.warning("Настройка %s повреждена, используется значение по умолчанию", key)
                    continue
                settings[key] = value
            # Настройки до v0.2.3 (без тембра): скорость 1.2 — прежнее значение по умолчанию,
            # а не выбор пользователя. Новый спокойный темп 1.0 подходит нежному голосу.
            if "voice_softness" not in stored and stored.get("voice_speed") == OLD_DEFAULT_SPEED:
                settings["voice_speed"] = DEFAULT_SETTINGS["voice_speed"]
                log.info("Скорость речи: прежнее значение по умолчанию 1.2 заменено на 1.0")
            if str(settings.get("ollama_url", "")).rstrip("/") == OLD_DEFAULT_URL:
                settings["ollama_url"] = DEFAULT_SETTINGS["ollama_url"]
                log.info("Адрес Ollama: localhost заменён на 127.0.0.1 (быстрее на Windows)")
        return settings

    def save(self, settings: dict[str, Any]) -> None:
        data = {k: settings.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
        atomic_write_json(self.path, data)
        log.info("Настройки сохранены")

    def reset(self) -> dict[str, Any]:
        settings = copy.deepcopy(DEFAULT_SETTINGS)
        self.save(settings)
        return settings
