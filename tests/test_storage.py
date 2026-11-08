"""Тесты JSON-хранилища: атомарная запись, чаты, сообщения, настройки, повреждённые файлы."""

from __future__ import annotations

import json

from storage.chat_storage import ChatStorage
from storage.settings_storage import DEFAULT_SETTINGS, SettingsStorage
from storage.storage_manager import atomic_write_json, read_json_safe


def test_atomic_write_creates_file_without_leftover_tmp(tmp_path):
    target = tmp_path / "data.json"
    atomic_write_json(target, {"привет": "мир"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"привет": "мир"}
    assert list(tmp_path.glob("*.tmp")) == []


def test_read_json_safe_handles_missing_and_broken_files(tmp_path):
    assert read_json_safe(tmp_path / "missing.json") is None
    broken = tmp_path / "broken.json"
    broken.write_text("{не json", encoding="utf-8")
    assert read_json_safe(broken) is None


def test_create_chat_assigns_sequential_file_ids(tmp_path):
    storage = ChatStorage(tmp_path / "chats")
    first = storage.create_chat("Первый")
    second = storage.create_chat("Второй")
    assert first["file_id"] == "chat_001"
    assert second["file_id"] == "chat_002"
    assert first["id"] != second["id"]


def test_add_message_persists_and_reloads(tmp_path):
    storage = ChatStorage(tmp_path / "chats")
    chat = storage.create_chat()
    storage.add_message(chat["file_id"], "user", "Привет")
    storage.add_message(chat["file_id"], "assistant", "Здравствуйте")

    loaded = ChatStorage(tmp_path / "chats").load_chat(chat["file_id"])
    assert [m["role"] for m in loaded["messages"]] == ["user", "assistant"]
    assert loaded["messages"][0]["text"] == "Привет"
    assert "timestamp" in loaded["messages"][0]


def test_list_chats_is_sorted_and_skips_broken_files(tmp_path):
    storage = ChatStorage(tmp_path / "chats")
    storage.create_chat("A")
    storage.create_chat("B")
    (tmp_path / "chats" / "chat_099.json").write_text("повреждён", encoding="utf-8")

    titles = [c["title"] for c in storage.list_chats()]
    assert sorted(titles) == ["A", "B"]


def test_rename_and_delete_chat(tmp_path):
    storage = ChatStorage(tmp_path / "chats")
    chat = storage.create_chat("Старое имя")
    assert storage.rename_chat(chat["file_id"], "  Новое имя  ")
    assert storage.load_chat(chat["file_id"])["title"] == "Новое имя"

    assert storage.delete_chat(chat["file_id"])
    assert storage.load_chat(chat["file_id"]) is None
    assert not storage.delete_chat(chat["file_id"])


def test_broken_chat_does_not_crash_add_message(tmp_path):
    storage = ChatStorage(tmp_path / "chats")
    (tmp_path / "chats" / "chat_001.json").write_text("{}", encoding="utf-8")
    assert storage.add_message("chat_001", "user", "тест") is None


def test_settings_defaults_when_file_missing(tmp_path):
    settings = SettingsStorage(tmp_path / "settings.json").load()
    assert settings == DEFAULT_SETTINGS


def test_settings_roundtrip_survives_restart(tmp_path):
    path = tmp_path / "settings.json"
    store = SettingsStorage(path)
    settings = store.load()
    settings["voice_enabled"] = True
    settings["voice_volume"] = 35
    store.save(settings)

    reloaded = SettingsStorage(path).load()
    assert reloaded["voice_enabled"] is True
    assert reloaded["voice_volume"] == 35


def test_settings_ignore_unknown_keys_and_broken_file(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"voice_volume": 10, "чужой_ключ": 1}), encoding="utf-8")
    loaded = SettingsStorage(path).load()
    assert loaded["voice_volume"] == 10
    assert "чужой_ключ" not in loaded

    path.write_text("сломано", encoding="utf-8")
    assert SettingsStorage(path).load() == DEFAULT_SETTINGS
