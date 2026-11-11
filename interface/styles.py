"""Цвета, темы и таблица стилей SIRIUS.

Смена темы на лету — заготовка (LIVE_SWITCH = False). Что уже есть:
  set_theme(name) — меняет палитру, таблицу стилей приложения и рассылает notifier().changed;
  виджет подписывается: styles.notifier().changed.connect(self.apply_theme) и в apply_theme()
  перестраивает то, что зависит от флагов темы (NAV_SIDE, DOT_MATRIX, SHOW_AVATAR, ISLAND_IOS).
Чтобы виджет перекрашивался сам, он должен читать цвет в момент рисования — styles.CYAN,
а не запоминать его при импорте (from interface.styles import CYAN). Какие модули ещё запоминают,
показывает tools/theme_audit.py; пока такие есть, LIVE_SWITCH остаётся False и тема меняется перезапуском.

Тема выбирается один раз при запуске: main.py вызывает apply_theme() до загрузки остальных
модулей интерфейса, потому что они берут цвета отсюда при импорте. Смена темы в настройках
поэтому вступает в силу после перезапуска SIRIUS.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

DEFAULT_THEME = "sirius"
# Заготовка: True — тема из настроек применяется сразу (set_theme), без перезапуска.
# Включать, когда tools/theme_audit.py перестанет находить модули с запомненными цветами.
LIVE_SWITCH = False

# название темы в настройках
THEME_TITLES = (
    ("sirius", "SIRIUS — голография"),
    ("nothing", "Nothing OS × iOS — монохром с точками"),
    ("ios", "iPhone — тёмное стекло"),
)

_BASE = {
    "BG": "#080B12", "BG_ALT": "#0D1424", "CYAN": "#36BFFF", "VIOLET": "#795BFF", "TEAL": "#3DDCC8",
    "WARNING": "#FFB454", "WHITE": "#FFFFFF", "TEXT_SECONDARY": "#A5B0C5", "ERROR": "#FF5555",
    "SUCCESS": "#35D49A",
    # заливки и границы таблицы стилей
    "PANEL_BG": "#0A1022", "FIELD_BG": "#060A18", "CONSOLE_BG": "#030610", "STATUS_BG": "#05060C",
    "EDGE": "#78AAFF", "EDGE_SOFT": "#AAC3FF", "DISABLED": "#5A6478",
    "FONT": '"Segoe UI", "Inter", sans-serif',
    "FONT_TITLE": '"Segoe UI", "Inter", sans-serif',
    "FONT_MONO": '"Cascadia Mono", "Consolas", monospace',   # цифры и системные показатели
    # плавающие панели: цвет стекла (верх, низ), прозрачность поверх фона, блик, граница, линия сверху
    "GLASS_TOP": "#101834", "GLASS_BOTTOM": "#080C1E", "GLASS_ALPHA": (120, 150),
    "GLASS_SHEEN": 22, "PANEL_BORDER": "#AAC3FF", "PANEL_BORDER_ALPHA": 62, "PANEL_TOP_LINE": True,
    "PANEL_RADIUS": 12,
    "BACKDROP": "city",      # фон окна: city — ночной город, dots — точки, glow — мягкие пятна света
    "SHOW_AVATAR": True,     # аватар LISA в центре рабочей области
    "NAV_SIDE": False,       # значки панелей в вертикальной боковой панели, а не в верхней полосе
    "DOT_MATRIX": False,     # точечные (Dot Matrix) надписи и узоры
    "ISLAND_IOS": False,     # островок как Dynamic Island: сплошная чёрная капсула без каймы и свечения
    "EXTRA": "",
}

THEMES: dict[str, dict] = {
    "sirius": {},
    "nothing": {
        "BG": "#000000", "BG_ALT": "#0E0E0E", "CYAN": "#FFFFFF", "VIOLET": "#D71921", "TEAL": "#B4B4B4",
        "WARNING": "#F2B84B", "TEXT_SECONDARY": "#8C8C8C", "ERROR": "#FF4A4A", "SUCCESS": "#7BD88F",
        "PANEL_BG": "#0A0A0A", "FIELD_BG": "#000000", "CONSOLE_BG": "#000000", "STATUS_BG": "#000000",
        "EDGE": "#FFFFFF", "EDGE_SOFT": "#FFFFFF", "DISABLED": "#4A4A4A",
        "FONT": '"Inter", "Segoe UI Variable Text", "Segoe UI", sans-serif',
        "FONT_TITLE": '"Inter Display", "Inter", "Segoe UI Variable Display", "Segoe UI", sans-serif',
        "GLASS_TOP": "#101010", "GLASS_BOTTOM": "#060606", "GLASS_ALPHA": (214, 232),
        "GLASS_SHEEN": 0, "PANEL_BORDER": "#FFFFFF", "PANEL_BORDER_ALPHA": 46, "PANEL_TOP_LINE": False,
        "PANEL_RADIUS": 18, "BACKDROP": "dots", "SHOW_AVATAR": False,
        "NAV_SIDE": True, "DOT_MATRIX": True,
        "EXTRA": """
QLabel#secondary { letter-spacing: 0.2px; }
QFrame#controlBar, QFrame#sideRail { background: rgba(8, 8, 8, 0.88); border: 1px solid rgba(255, 255, 255, 0.10);
                                     border-radius: 18px; }
QPushButton { background: rgba(255, 255, 255, 0.05); border: 1px solid rgba(255, 255, 255, 0.16);
              border-radius: 14px; font-weight: 500; }
QPushButton:hover { background: rgba(255, 255, 255, 0.12); border-color: rgba(255, 255, 255, 0.45); }
QPushButton:pressed { background: rgba(255, 255, 255, 0.22); }
QPushButton:disabled { border-color: rgba(255, 255, 255, 0.08); }
QPushButton#primary { background: #FFFFFF; color: #000000; border-color: #FFFFFF; font-weight: 600; }
QPushButton#primary:hover { background: #D9D9D9; border-color: #D9D9D9; }
QPushButton#danger { background: transparent; border-color: #D71921; color: #FF4A4A; }
QPushButton#danger:hover { background: rgba(215, 25, 33, 0.18); }
QPushButton#barButton { border-radius: 10px; font-family: "Cascadia Mono", "Consolas", monospace; font-size: 10px; letter-spacing: 1px; }
QPushButton#small { border-radius: 10px; font-size: 10px; }
QPushButton#dockButton { border-radius: 11px; }
QPushButton#dockButton:checked { color: #000000; background: #FFFFFF; border-color: #FFFFFF; }

/* чат: сообщение пользователя — светлая карточка, LISA — тёмная с тонким контуром */
QFrame#bubbleUser { background: #F2F2F2; border: none; border-radius: 18px; }
QFrame#bubbleUser QLabel { color: #000000; }
QFrame#bubbleUser QLabel#secondary { color: #6E6E6E; }
QFrame#bubbleUser QPushButton#small { background: transparent; color: #3A3A3A; border-color: rgba(0, 0, 0, 0.22); }
QFrame#bubbleUser QPushButton#small:hover { background: rgba(0, 0, 0, 0.08); }
QFrame#bubbleLisa { background: #101010; border: 1px solid rgba(255, 255, 255, 0.10); border-radius: 18px; }
QFrame#bubbleError { background: rgba(215, 25, 33, 0.10); border: 1px solid rgba(215, 25, 33, 0.55);
                     border-radius: 18px; }
QFrame#panel { background: #0C0C0C; border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 22px; }
QFrame#panel QPlainTextEdit { background: transparent; border: none; padding: 4px 6px; font-size: 14px; }

QPlainTextEdit, QLineEdit, QListWidget, QSpinBox, QDoubleSpinBox, QComboBox {
    background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.14); border-radius: 12px; }
QPlainTextEdit:focus, QLineEdit:focus { border-color: #FFFFFF; }
QSpinBox, QDoubleSpinBox { font-family: "Cascadia Mono", "Consolas", monospace; }
QListWidget::item { border-radius: 10px; }
QListWidget::item:selected { background: rgba(255, 255, 255, 0.14); }
QListWidget::item:hover { background: rgba(255, 255, 255, 0.07); }
QScrollBar::handle:vertical, QScrollBar::handle:horizontal { background: rgba(255, 255, 255, 0.22); }
QTabWidget::pane { border: 1px solid rgba(255, 255, 255, 0.10); border-radius: 16px; background: #0A0A0A; }
QTabBar::tab { font-size: 12px; padding: 8px 14px; }
QTabBar::tab:hover { color: #FFFFFF; }
QTabBar::tab:selected { color: #FFFFFF; border-bottom: 2px solid #D71921; }
QCheckBox::indicator { border-radius: 8px; border-color: rgba(255, 255, 255, 0.55); }
QCheckBox::indicator:checked { background: #D71921; border-color: #D71921; }
QSlider::groove:horizontal { background: rgba(255, 255, 255, 0.16); }
QSlider::handle:horizontal { background: #FFFFFF; }
QSlider::sub-page:horizontal { background: #FFFFFF; }
QProgressBar { border: 1px solid rgba(255, 255, 255, 0.14); font-family: "Cascadia Mono", "Consolas", monospace; }
QProgressBar::chunk { background: #FFFFFF; }
QProgressBar#metricBar, QProgressBar#metricBarHigh { background: rgba(255, 255, 255, 0.10); border: none; }
QStatusBar { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px; border-top: 1px solid rgba(255, 255, 255, 0.08); }
QToolTip { border: 1px solid rgba(255, 255, 255, 0.35); padding: 4px 6px; }
QLabel#panelTitle { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 10px; letter-spacing: 3px; }
QLabel#metricName { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 10px; letter-spacing: 2px; }
QLabel#metricValue, QLabel#sessionLine { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px; }
QTableWidget#procTable { font-family: "Cascadia Mono", "Consolas", monospace; }
QLabel#emptyState { font-family: "Cascadia Mono", "Consolas", monospace; font-size: 11px; letter-spacing: 2px; }
""",
    },
    "ios": {
        "BG": "#000000", "BG_ALT": "#1C1C1E", "CYAN": "#0A84FF", "VIOLET": "#5E5CE6", "TEAL": "#64D2FF",
        "WARNING": "#FF9F0A", "TEXT_SECONDARY": "#98989F", "ERROR": "#FF453A", "SUCCESS": "#30D158",
        "PANEL_BG": "#1C1C1E", "FIELD_BG": "#3A3A3C", "CONSOLE_BG": "#000000", "STATUS_BG": "#000000",
        "EDGE": "#8E8E93", "EDGE_SOFT": "#8E8E93", "DISABLED": "#5A5A5E",
        "FONT": '"SF Pro Text", "Segoe UI Variable Text", "Segoe UI", sans-serif',
        "FONT_TITLE": '"SF Pro Display", "Segoe UI Variable Display", "Segoe UI", sans-serif',
        "GLASS_TOP": "#2C2C2E", "GLASS_BOTTOM": "#1C1C1E", "GLASS_ALPHA": (196, 214),
        "GLASS_SHEEN": 10, "PANEL_BORDER": "#FFFFFF", "PANEL_BORDER_ALPHA": 34, "PANEL_TOP_LINE": False,
        "PANEL_RADIUS": 20, "BACKDROP": "glow", "SHOW_AVATAR": False, "ISLAND_IOS": True,
        "EXTRA": """
QLabel#title { letter-spacing: 1px; color: #FFFFFF; }
QPushButton { background: rgba(118, 118, 128, 0.30); border: 1px solid transparent; border-radius: 12px; }
QPushButton:hover { background: rgba(118, 118, 128, 0.46); border-color: transparent; }
QPushButton:pressed { background: rgba(118, 118, 128, 0.60); }
QPushButton:disabled { border-color: transparent; }
QPushButton#primary { background: #0A84FF; border-color: #0A84FF; }
QPushButton#primary:hover { background: #3A9BFF; }
QPushButton#danger { border-color: transparent; color: #FF453A; }
QPushButton#dockButton { background: transparent; letter-spacing: 0px; border-radius: 10px; }
QPushButton#dockButton:checked { color: #FFFFFF; background: #0A84FF; border-color: #0A84FF; }
QFrame#controlBar { border-radius: 16px; }
QPlainTextEdit, QLineEdit, QListWidget, QSpinBox, QDoubleSpinBox, QComboBox { border-radius: 12px; }
QCheckBox::indicator { border-radius: 8px; border-color: #8E8E93; }
QCheckBox::indicator:checked { background: #30D158; border-color: #30D158; }
QSlider::handle:horizontal { background: #FFFFFF; }
QSlider::sub-page:horizontal { background: #0A84FF; }
QProgressBar::chunk { background: #0A84FF; }
QTabBar::tab:selected { color: #FFFFFF; }
QLabel#panelTitle { letter-spacing: 0px; font-size: 12px; }
QToolTip { border: 1px solid rgba(255, 255, 255, 0.18); }
""",
    },
}


def rgb(color: str) -> str:
    """«#36BFFF» → «54, 191, 255» для rgba() в таблицах стилей."""
    c = color.lstrip("#")
    return f"{int(c[0:2], 16)}, {int(c[2:4], 16)}, {int(c[4:6], 16)}"


def _build_style() -> str:
    cyan, violet, error, teal = rgb(CYAN), rgb(VIOLET), rgb(ERROR), rgb(TEAL)
    panel, field, console = rgb(PANEL_BG), rgb(FIELD_BG), rgb(CONSOLE_BG)
    edge, edge_soft = rgb(EDGE), rgb(EDGE_SOFT)
    return f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {WHITE}; font-family: {FONT}; font-size: 13px; }}
QLabel#title {{ font-family: {FONT_TITLE}; font-size: 18px; font-weight: 600; letter-spacing: 4px; color: {CYAN}; }}
QLabel#secondary {{ color: {TEXT_SECONDARY}; }}
QFrame#panel {{ background: rgba({panel}, 0.38); border: 1px solid rgba({cyan}, 0.22); border-radius: 14px; }}
QFrame#bubbleUser {{ background: rgba({violet}, 0.16); border: 1px solid rgba({violet}, 0.45); border-radius: 12px; }}
QFrame#bubbleLisa {{ background: rgba({cyan}, 0.10); border: 1px solid rgba({cyan}, 0.35); border-radius: 12px; }}
QFrame#bubbleError {{ background: rgba({error}, 0.12); border: 1px solid rgba({error}, 0.5); border-radius: 12px; }}
QPushButton {{ background: rgba({cyan}, 0.08); border: 1px solid rgba({cyan}, 0.35);
              border-radius: 10px; padding: 7px 14px; color: {WHITE}; }}
QPushButton:hover {{ background: rgba({cyan}, 0.2); border-color: {CYAN}; }}
QPushButton:pressed {{ background: rgba({violet}, 0.35); }}
QPushButton:disabled {{ color: {DISABLED}; border-color: rgba(90, 100, 120, 0.3); }}
QPushButton#primary {{ background: rgba({cyan}, 0.25); border-color: {CYAN}; font-weight: 600; }}
QPushButton#danger {{ border-color: rgba({error}, 0.6); color: {ERROR}; }}
QPushButton#small {{ padding: 3px 9px; font-size: 11px; border-radius: 8px; }}
QPlainTextEdit, QLineEdit, QListWidget, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: rgba({field}, 0.42); border: 1px solid rgba({edge}, 0.24);
    border-radius: 10px; padding: 6px; selection-background-color: {VIOLET}; }}
QPlainTextEdit:focus, QLineEdit:focus {{ border-color: {CYAN}; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba({violet}, 0.35); }}
QListWidget::item:hover {{ background: rgba({cyan}, 0.12); }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba({cyan}, 0.35); border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba({cyan}, 0.35); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}
QTabWidget::pane {{ border: 1px solid rgba({cyan}, 0.22); border-radius: 12px; background: {BG_ALT}; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {TEXT_SECONDARY}; }}
QTabBar::tab:selected {{ color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {CYAN}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {CYAN}; }}
QSlider::groove:horizontal {{ height: 4px; background: rgba({cyan}, 0.2); border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {CYAN}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QSlider::sub-page:horizontal {{ background: {VIOLET}; border-radius: 2px; }}
QProgressBar {{ background: rgba({field}, 0.42); border: 1px solid rgba({cyan}, 0.25);
               border-radius: 6px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {VIOLET}; border-radius: 6px; }}
QStatusBar {{ background: {STATUS_BG}; color: {TEXT_SECONDARY}; border-top: 1px solid rgba({cyan}, 0.15); }}
QToolTip {{ background: {BG_ALT}; color: {WHITE}; border: 1px solid {CYAN}; }}
QMessageBox {{ background: {BG_ALT}; }}

/* --- рабочее пространство v0.2 --- */
QFrame#controlBar {{ background: rgba({panel}, 0.48); border: 1px solid rgba({edge_soft}, 0.20);
                    border-radius: 12px; }}
QFrame#sideRail {{ background: rgba({panel}, 0.48); border: 1px solid rgba({edge_soft}, 0.20);
                  border-radius: 16px; }}
QPushButton#dockButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px;
                         padding: 5px 10px; font-family: {FONT_TITLE}; font-size: 11px; font-weight: 600;
                         letter-spacing: 1px; color: {TEXT_SECONDARY}; }}
QPushButton#dockButton:hover {{ color: {WHITE}; background: rgba({cyan}, 0.10); }}
QPushButton#dockButton:checked {{ color: {CYAN}; background: rgba({cyan}, 0.12);
                                 border-color: rgba({cyan}, 0.45); }}
QPushButton#barButton {{ padding: 5px 10px; font-size: 11px; border-radius: 8px; }}
QLabel#panelTitle {{ color: {TEXT_SECONDARY}; font-family: {FONT_TITLE}; font-size: 11px; font-weight: 600;
                    letter-spacing: 2px; }}
QLabel#panelTitle[active="true"] {{ color: {WHITE}; }}
QLabel#panelHint {{ color: {TEXT_SECONDARY}; font-size: 11px; }}
QLabel#emptyState {{ color: {TEXT_SECONDARY}; font-size: 13px; letter-spacing: 1px; }}
QLabel#metricName {{ color: {TEXT_SECONDARY}; font-size: 11px; letter-spacing: 1px; }}
QLabel#metricValue {{ color: {WHITE}; font-size: 12px; font-weight: 600; }}
QTabWidget#sysTabs::pane {{ border: none; background: transparent; top: -1px; }}
QTabWidget#sysTabs QTabBar::tab {{ padding: 3px 8px; font-size: 11px; min-width: 0px; }}
QTableWidget#procTable {{ background: transparent; border: none; color: {WHITE}; font-size: 11px;
    gridline-color: transparent; selection-background-color: rgba({cyan}, 0.18); }}
QTableWidget#procTable QHeaderView::section {{ background: transparent; color: {TEXT_SECONDARY};
    border: none; border-bottom: 1px solid rgba({cyan}, 0.22); padding: 2px 4px; font-size: 10px; }}
QLabel#sessionLine {{ color: {WHITE}; font-size: 11px; }}
QPlainTextEdit#console {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
                          background: rgba({console}, 0.5); border-color: rgba({teal}, 0.22); }}
QLineEdit#consoleInput {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }}
QPlainTextEdit#codeView {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
                           background: rgba({console}, 0.5); }}
QComboBox {{ padding: 4px 8px; }}
QProgressBar#metricBar, QProgressBar#metricBarHigh {{ background: rgba({cyan}, 0.10); border: none;
                                                     border-radius: 3px; }}
QProgressBar#metricBar::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:1 {TEAL}); }}
QProgressBar#metricBarHigh::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {WARNING}, stop:1 {ERROR}); }}
QComboBox QAbstractItemView {{ background: {BG_ALT}; selection-background-color: rgba({violet}, 0.45); }}
{EXTRA}"""


class ThemeNotifier(QObject):
    """Сообщает работающим окнам, что тема сменилась (имя новой темы)."""

    changed = Signal(str)


_notifier: ThemeNotifier | None = None


def notifier() -> ThemeNotifier:
    global _notifier
    if _notifier is None:
        _notifier = ThemeNotifier()
    return _notifier


def set_theme(name) -> bool:
    """Меняет тему работающего приложения. False — эта тема уже включена.

    Палитра и таблица стилей меняются сразу; подписчики notifier().changed перестраивают своё;
    все виджеты перерисовываются. Виджеты, запомнившие цвета при импорте, останутся прежними —
    поэтому из настроек функция вызывается, только когда LIVE_SWITCH = True.
    """
    name = normalize_theme(name)
    if name == THEME:
        return False
    apply_theme(name)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(STYLE)
    notifier().changed.emit(name)
    if app is not None:
        for widget in app.allWidgets():
            widget.update()
    return True


def load_fonts(folder) -> list[str]:
    """Подключает шрифты из папки (resources/fonts) только для SIRIUS, без установки в Windows.

    Вызывать после создания QApplication. Возвращает названия подключённых семейств.
    """
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    families: list[str] = []
    for path in sorted(Path(folder).glob("*.ttf")):
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id >= 0:
            families += [f for f in QFontDatabase.applicationFontFamilies(font_id) if f not in families]
    return families


def normalize_theme(name) -> str:
    return name if isinstance(name, str) and name in THEMES else DEFAULT_THEME


def apply_theme(name) -> str:
    """Делает тему текущей: задаёт цвета этого модуля и пересобирает STYLE. Возвращает её имя.

    Вызывать до импорта остальных модулей интерфейса: они запоминают цвета при загрузке.
    """
    global THEME, STYLE
    THEME = normalize_theme(name)
    globals().update({**_BASE, **THEMES[THEME]})
    STYLE = _build_style()
    return THEME


THEME = DEFAULT_THEME
STYLE = ""
apply_theme(DEFAULT_THEME)
