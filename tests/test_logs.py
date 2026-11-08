"""Журнал: чтение только новых строк, усечение файла, фильтр уровней, поиск, пауза, панель LOGS."""

from __future__ import annotations

import time

from core.log_reader import LogTailer, filter_entries, parse_line

LINES = [
    "2026-11-07 18:00:30,425 [INFO] sirius.settings: Настройки сохранены",
    "2026-11-07 18:00:31,001 [WARNING] sirius.voice: Голос недоступен",
    "2026-11-07 18:00:32,100 [ERROR] sirius.workers: Непредвиденная ошибка генерации",
    "Traceback (most recent call last):",
    '  File "x.py", line 1, in <module>',
    "2026-11-07 18:00:33,000 [DEBUG] sirius.model: отладка",
    "2026-11-07 18:00:34,000 [CRITICAL] sirius: авария",
]


def _write(path, lines, mode="a"):
    with open(path, mode, encoding="utf-8", newline="\n") as fh:
        for line in lines:
            fh.write(line + "\n")


def test_parse_line_fields():
    e = parse_line(LINES[1])
    assert (e.time, e.level, e.source, e.message) == (
        "2026-11-07 18:00:31", "WARNING", "sirius.voice", "Голос недоступен")
    assert e.clock == "18:00:31"
    assert parse_line(LINES[5]).level == "INFO"      # DEBUG показывается вместе с INFO
    assert parse_line(LINES[6]).level == "ERROR"     # CRITICAL — вместе с ERROR


def test_traceback_lines_inherit_level(tmp_path):
    path = tmp_path / "sirius.log"
    _write(path, LINES[:5])
    entries = LogTailer(path).read_new()
    assert [e.level for e in entries] == ["INFO", "WARNING", "ERROR", "ERROR", "ERROR"]
    assert entries[3].continuation


def test_reads_only_new_lines(tmp_path):
    path = tmp_path / "sirius.log"
    _write(path, LINES[:2])
    tailer = LogTailer(path)
    assert len(tailer.read_new()) == 2
    offset = tailer.offset
    assert tailer.read_new() == []
    _write(path, LINES[2:3])
    new = tailer.read_new()
    assert [e.level for e in new] == ["ERROR"]
    assert tailer.offset > offset


def test_incomplete_last_line_waits_for_newline(tmp_path):
    path = tmp_path / "sirius.log"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(LINES[0] + "\n" + LINES[1][:20])
    tailer = LogTailer(path)
    assert len(tailer.read_new()) == 1
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(LINES[1][20:] + "\n")
    new = tailer.read_new()
    assert len(new) == 1 and new[0].message == "Голос недоступен"


def test_initial_read_takes_only_tail(tmp_path):
    path = tmp_path / "sirius.log"
    _write(path, [LINES[0]] * 5000)
    entries = LogTailer(path, initial_tail_bytes=1000).read_new()
    assert 0 < len(entries) < 30
    assert all(not e.continuation for e in entries)  # обрезанная первая строка отброшена


def test_truncated_file_is_read_from_start(tmp_path):
    path = tmp_path / "sirius.log"
    _write(path, LINES[:3])
    tailer = LogTailer(path)
    tailer.read_new()
    _write(path, LINES[6:7], mode="w")
    new = tailer.read_new()
    assert len(new) == 1 and new[0].message == "авария"


def test_missing_file_is_not_an_error(tmp_path):
    tailer = LogTailer(tmp_path / "nope.log")
    assert tailer.read_new() == []


def test_filter_levels_and_text(tmp_path):
    path = tmp_path / "sirius.log"
    _write(path, LINES)
    entries = LogTailer(path).read_new()
    assert {e.level for e in filter_entries(entries, {"ERROR"})} == {"ERROR"}
    assert [e.message for e in filter_entries(entries, {"INFO", "WARNING", "ERROR"}, "ГОЛОС")] == ["Голос недоступен"]
    assert len(filter_entries(entries, {"WARNING"}, "voice")) == 1   # поиск и по источнику
    assert filter_entries(entries, set()) == []


# --- панель --------------------------------------------------------------------


def _pump(qt_app, predicate, timeout=5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qt_app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    return False


def test_panel_tails_file_in_background(qt_app, tmp_path):
    from interface.panels.logs_panel import LogsPanel

    path = tmp_path / "sirius.log"
    _write(path, LINES[:2])
    panel = LogsPanel(path, interval_ms=100)
    panel.panel_shown()
    try:
        assert _pump(qt_app, lambda: len(panel.visible_entries()) == 2)
        _write(path, LINES[2:3])
        assert _pump(qt_app, lambda: len(panel.visible_entries()) == 3)
        assert "Непредвиденная ошибка генерации" in panel.view.toPlainText()
        assert "18:00:32" in panel.view.toPlainText()          # время события
    finally:
        panel.shutdown()
    assert not panel.is_reading()


def test_panel_level_filter_and_search(qt_app, tmp_path):
    from interface.panels.logs_panel import LogsPanel

    panel = LogsPanel(tmp_path / "sirius.log")
    path = tmp_path / "sirius.log"
    _write(path, LINES)
    panel.add_entries(panel.tailer.read_new())
    panel.level_buttons["INFO"].setChecked(False)
    panel.level_buttons["WARNING"].setChecked(False)
    assert {e.level for e in panel.visible_entries()} == {"ERROR"}
    assert "Настройки сохранены" not in panel.view.toPlainText()
    panel.level_buttons["INFO"].setChecked(True)
    panel.search.setText("настройки")
    assert [e.message for e in panel.visible_entries()] == ["Настройки сохранены"]


def test_panel_pause_and_clear_keep_file(qt_app, tmp_path):
    from interface.panels.logs_panel import LogsPanel

    path = tmp_path / "sirius.log"
    _write(path, LINES[:2])
    panel = LogsPanel(path)
    panel.add_entries(panel.tailer.read_new())
    panel.set_paused(True)
    panel.add_entries([parse_line(LINES[2])])
    assert len(panel.visible_entries()) == 2              # на паузе новые записи не показываются
    panel.set_paused(False)
    assert len(panel.visible_entries()) == 3
    size = path.stat().st_size
    panel.clear_view()
    assert panel.view.toPlainText() == ""
    assert path.stat().st_size == size                    # исходный журнал не тронут


def test_panel_autoscroll_off_keeps_position(qt_app, tmp_path):
    from interface.panels.logs_panel import LogsPanel

    panel = LogsPanel(tmp_path / "sirius.log")
    panel.resize(400, 200)
    panel.add_entries([parse_line(LINES[0])] * 200)
    bar = panel.view.verticalScrollBar()
    panel.autoscroll.setChecked(False)
    bar.setValue(0)
    panel.add_entries([parse_line(LINES[1])] * 20)
    assert bar.value() == 0
