"""Темы оформления: палитры, таблица стилей, фон окна, аватар, настройки."""

from __future__ import annotations

import pytest

from interface import styles
from storage.settings_storage import DEFAULT_SETTINGS, SettingsStorage


@pytest.fixture
def theme():
    """Включает тему на время теста и возвращает стандартную."""
    yield styles.apply_theme
    styles.apply_theme(styles.DEFAULT_THEME)


def test_default_theme_keeps_sirius_palette():
    assert styles.THEME == "sirius"
    assert (styles.BG, styles.CYAN, styles.VIOLET) == ("#080B12", "#36BFFF", "#795BFF")
    assert styles.SHOW_AVATAR is True and styles.BACKDROP == "city"
    assert "rgba(54, 191, 255, 0.22)" in styles.STYLE


@pytest.mark.parametrize("name, accent, backdrop", [("nothing", "#D71921", "dots"), ("ios", "#0A84FF", "glow")])
def test_new_themes_change_palette_and_hide_avatar(theme, name, accent, backdrop):
    assert theme(name) == name
    assert styles.BG == "#000000"
    assert accent in styles.STYLE
    assert "54, 191, 255" not in styles.STYLE      # голубого SIRIUS в таблице стилей не остаётся
    assert styles.SHOW_AVATAR is False and styles.BACKDROP == backdrop


def test_unknown_theme_falls_back(theme):
    assert theme("нет такой") == "sirius"
    assert theme(None) == "sirius"
    assert styles.CYAN == "#36BFFF"


def test_every_theme_has_title_and_known_keys():
    assert {t for t, _ in styles.THEME_TITLES} == set(styles.THEMES)
    for palette in styles.THEMES.values():
        assert set(palette) <= set(styles._BASE)


def test_theme_is_saved_in_settings(tmp_path):
    assert DEFAULT_SETTINGS["theme"] == "nothing"
    store = SettingsStorage(tmp_path / "settings.json")
    data = store.load()
    data["theme"] = "ios"
    store.save(data)
    assert store.load()["theme"] == "ios"


@pytest.mark.parametrize("name", ["sirius", "nothing", "ios"])
def test_backdrop_renders_for_theme(qt_app, theme, name):
    from interface.workspace.backdrop import render_backdrop

    theme(name)
    pix = render_backdrop(320, 200)
    assert (pix.width(), pix.height()) == (320, 200)
    corner = pix.toImage().pixelColor(318, 2)
    if name != "sirius":
        assert corner.red() < 40 and corner.green() < 40      # чёрное поле, а не город


def test_settings_dialog_returns_theme(qt_app):
    import copy

    from interface.settings_panel import SettingsDialog

    dlg = SettingsDialog(copy.deepcopy(DEFAULT_SETTINGS))
    assert dlg.values()["theme"] == "nothing"
    dlg.theme_combo.setCurrentIndex(dlg.theme_combo.findData("ios"))
    assert dlg.values()["theme"] == "ios"
    dlg.deleteLater()


def test_avatar_hidden_in_theme_without_avatar(qt_app, tmp_path, theme):
    from interface.main_window import MainWindow

    theme("nothing")
    win = MainWindow(tmp_path)
    try:
        win.show()
        assert win.avatar.isHidden()
        win._refresh_avatar()                # состояния LISA продолжают работать без видимого аватара
        assert win.avatar.isHidden()
    finally:
        win._quitting = True
        win.close()


def test_avatar_shown_in_default_theme(qt_app, tmp_path):
    from interface.main_window import MainWindow

    win = MainWindow(tmp_path)
    try:
        win.show()
        assert win.avatar.isVisible()
    finally:
        win._quitting = True
        win.close()


# --- Nothing OS × iOS: точечный шрифт, боковая навигация, переходы ---

def test_bundled_inter_font_loads(qt_app):
    from pathlib import Path

    families = styles.load_fonts(Path(__file__).resolve().parent.parent / "resources" / "fonts")
    assert "Inter" in families and "Inter Display" in families
    assert styles.load_fonts(Path(__file__).parent / "нет такой папки") == []


def test_dotmatrix_glyphs_are_5x7():
    from interface import dotmatrix

    for char in "SIRIUS0123456789:%":
        rows = dotmatrix.glyph(char)
        assert len(rows) == 7 and all(len(r) == 5 and set(r) <= {"0", "1"} for r in rows)
    assert "1" not in "".join(dotmatrix.glyph("Ж"))          # неизвестный знак — пустая клетка
    assert dotmatrix.text_columns("25:00") == 27              # двоеточие уже цифр
    assert dotmatrix.text_columns("") == 0


def test_dot_label_draws_text(qt_app):
    from interface.dotmatrix import DotLabel

    lbl = DotLabel("25:00", dot=4.0, gap=2.0)
    lbl.resize(lbl.sizeHint())
    image = lbl.grab().toImage()
    assert any(image.pixelColor(x, y).red() > 200 for x in range(image.width()) for y in range(image.height()))
    lbl.setText("24:59")
    assert lbl.text() == "24:59"


def test_side_rail_toggles_and_syncs(qt_app):
    from interface.workspace.side_rail import SideRail

    rail = SideRail([("chat", "CHAT", "Диалог"), ("system", "SYSTEM", "Мониторинг")])
    seen = []
    rail.toggle_panel.connect(seen.append)
    rail.hide_all_requested.connect(lambda: seen.append("hide"))
    rail.settings_requested.connect(lambda: seen.append("settings"))
    rail.button("system").click()
    rail.hide_all_btn.click()
    rail.settings_btn.click()
    assert seen == ["system", "hide", "settings"]
    rail.set_panel_open("chat", True)
    assert rail.button("chat").isChecked()
    rail.set_panel_open("chat", False)
    assert not rail.button("chat").isChecked()
    assert not rail.grab().isNull()


def test_main_window_uses_side_rail_in_nothing_theme(qt_app, tmp_path, theme):
    from interface.main_window import MainWindow

    theme("nothing")
    win = MainWindow(tmp_path)
    try:
        win.show()
        assert win.side_rail is not None and win.side_rail.isVisible()
        assert not win.control_bar.button("chat").isVisible()     # кнопки панелей убраны из верхней полосы
        was_open = win.workspace.is_open("logs")
        win.side_rail.button("logs").click()
        assert win.workspace.is_open("logs") is not was_open
        assert win.side_rail.button("logs").isChecked() is not was_open
        win.control_bar.button("logs").click()                    # прежняя кнопка по-прежнему работает
        assert win.workspace.is_open("logs") is was_open
    finally:
        win.close()


def test_main_window_keeps_top_navigation_in_default_theme(qt_app, tmp_path):
    from interface.main_window import MainWindow

    win = MainWindow(tmp_path)
    try:
        win.show()
        assert win.side_rail.isHidden() and win.control_bar.button("chat").isVisible()
    finally:
        win.close()


def test_fade_in_removes_effect_when_done(qt_app):
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QWidget

    from interface.motion import fade_in

    hidden = QWidget()
    assert fade_in(hidden) is False                 # невидимый виджет не трогаем
    w = QWidget()
    w.show()
    assert fade_in(w, 40) is True
    assert fade_in(w, 40) is False                  # переход уже идёт
    loop = QEventLoop()
    QTimer.singleShot(200, loop.quit)
    loop.exec()
    assert w.graphicsEffect() is None
    w.close()


# --- заготовка смены темы на лету ---

@pytest.fixture
def live_theme(qt_app):
    """set_theme на время теста; после — прежняя тема и прежняя таблица стилей приложения."""
    sheet = qt_app.styleSheet()
    yield styles.set_theme
    styles.set_theme(styles.DEFAULT_THEME)
    styles.apply_theme(styles.DEFAULT_THEME)
    qt_app.setStyleSheet(sheet)


def test_live_switch_is_off_by_default():
    assert styles.LIVE_SWITCH is False, "пока не все модули перекрашиваются на лету, тема меняется перезапуском"


def test_set_theme_updates_style_and_notifies(qt_app, live_theme):
    seen = []
    styles.notifier().changed.connect(seen.append)
    try:
        assert live_theme("sirius") is False and seen == [], "та же тема — ничего не происходит"
        assert live_theme("ios") is True
        assert styles.THEME == "ios" and styles.CYAN == "#0A84FF" and seen == ["ios"]
        assert "#0A84FF" in qt_app.styleSheet()
        assert live_theme("нет такой") is True and styles.THEME == "sirius" and seen == ["ios", "sirius"]
    finally:
        styles.notifier().changed.disconnect(seen.append)


def test_main_window_follows_theme_on_the_fly(qt_app, tmp_path, live_theme):
    from interface.main_window import MainWindow

    win = MainWindow(tmp_path)
    try:
        win.resize(1100, 700)
        win.show()
        qt_app.processEvents()
        bar = win.control_bar
        assert win.side_rail.isHidden() and win.avatar.isVisible() and bar.title is bar.title_text
        assert bar.title_text.isVisible() and bar.title_dots.isHidden() and win.settings_btn.isVisible()
        city = win.centralWidget().pixmap().toImage().pixelColor(5, 5)

        live_theme("nothing")
        qt_app.processEvents()
        assert win.side_rail.isVisible() and win.avatar.isHidden() and bar.title is bar.title_dots
        assert bar.title_dots.isVisible() and bar.title_text.isHidden() and win.settings_btn.isHidden()
        assert not bar.button("chat").isVisible() and not bar.hide_all_btn.isVisible()
        dots = win.centralWidget().pixmap().toImage().pixelColor(5, 5)
        assert dots != city and dots.blue() < 40, "фон окна перестроен под новую тему"
        was_open = win.workspace.is_open("logs")
        win.side_rail.button("logs").click()
        assert win.workspace.is_open("logs") is not was_open

        live_theme("sirius")
        qt_app.processEvents()
        assert win.side_rail.isHidden() and win.avatar.isVisible() and bar.button("chat").isVisible()
        assert bar.button("logs").isChecked() is win.workspace.is_open("logs"), "обе навигации остаются согласованы"
    finally:
        win.close()


def test_settings_keep_restart_until_live_switch_enabled(qt_app, tmp_path, live_theme, monkeypatch):
    from interface.main_window import MainWindow

    win = MainWindow(tmp_path)
    try:
        values = dict(win.settings, theme="ios")
        win._apply_settings(values)
        assert styles.THEME == "sirius" and "перезапуска" in win.statusBar().currentMessage()
        monkeypatch.setattr(styles, "LIVE_SWITCH", True)
        win._apply_settings(dict(values, theme="nothing"))
        assert styles.THEME == "nothing" and "перезапуска" not in win.statusBar().currentMessage()
        assert win.side_rail.isVisibleTo(win)
    finally:
        win.close()


def test_theme_audit_lists_modules_that_capture_colours(tmp_path):
    from tools import theme_audit

    sample = tmp_path / "sample.py"
    sample.write_text("from interface import styles\nfrom interface.styles import CYAN, rgb\n"
                      "RADIUS = styles.PANEL_RADIUS\n\n\ndef paint():\n    return styles.CYAN\n", encoding="utf-8")
    assert theme_audit.audit_file(sample) == (["CYAN"], [3]), "чтение внутри функции — это уже правильно"
    found = theme_audit.audit()
    assert "interface/workspace/side_rail.py" not in found and "interface/workspace/backdrop.py" not in found
    assert all(names or lines for names, lines in found.values())
