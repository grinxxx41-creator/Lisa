"""Проверка отсутствия ошибок импорта во всех модулях проекта."""

from __future__ import annotations

import importlib

import pytest

MODULES = [
    "main",
    "core.ai_engine",
    "core.code_blocks",
    "core.command_policy",
    "core.context_manager",
    "core.log_reader",
    "core.single_instance",
    "voice.audio_effects",
    "voice.speech_normalizer",
    "core.terminal_session",
    "monitoring.system_info",
    "interface.workspace.backdrop",
    "interface.workspace.control_bar",
    "interface.workspace.floating_panel",
    "interface.workspace.panel_layout",
    "interface.workspace.panel_registry",
    "interface.workspace.panel_titlebar",
    "interface.workspace.workspace_canvas",
    "interface.workspace.workspace_manager",
    "interface.panels.code_panel",
    "interface.panels.logs_panel",
    "interface.panels.system_panel",
    "interface.panels.terminal_panel",
    "core.model_manager",
    "core.title_generator",
    "voice.audio_player",
    "voice.text_processing",
    "voice.tts_engine",
    "voice.voice_controller",
    "storage.chat_storage",
    "storage.settings_storage",
    "storage.storage_manager",
    "interface.avatar_widget",
    "interface.chat_panel",
    "interface.history_panel",
    "interface.main_window",
    "interface.settings_panel",
    "interface.styles",
    "interface.workers",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name):
    importlib.import_module(module_name)
