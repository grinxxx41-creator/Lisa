"""Цвета и таблица стилей SIRIUS."""

BG = "#080B12"
BG_ALT = "#0D1424"
CYAN = "#36BFFF"
VIOLET = "#795BFF"
TEAL = "#3DDCC8"
WARNING = "#FFB454"
WHITE = "#FFFFFF"
TEXT_SECONDARY = "#A5B0C5"
ERROR = "#FF5555"
SUCCESS = "#35D49A"

STYLE = f"""
QMainWindow, QDialog {{ background: {BG}; }}
QWidget {{ color: {WHITE}; font-family: "Segoe UI", "Inter", sans-serif; font-size: 13px; }}
QLabel#title {{ font-size: 18px; font-weight: 600; letter-spacing: 4px; color: {CYAN}; }}
QLabel#secondary {{ color: {TEXT_SECONDARY}; }}
QFrame#panel {{ background: rgba(10, 16, 34, 0.38); border: 1px solid rgba(54, 191, 255, 0.22); border-radius: 14px; }}
QFrame#bubbleUser {{ background: rgba(121, 91, 255, 0.16); border: 1px solid rgba(121, 91, 255, 0.45); border-radius: 12px; }}
QFrame#bubbleLisa {{ background: rgba(54, 191, 255, 0.10); border: 1px solid rgba(54, 191, 255, 0.35); border-radius: 12px; }}
QFrame#bubbleError {{ background: rgba(255, 85, 85, 0.12); border: 1px solid rgba(255, 85, 85, 0.5); border-radius: 12px; }}
QPushButton {{ background: rgba(54, 191, 255, 0.08); border: 1px solid rgba(54, 191, 255, 0.35);
              border-radius: 10px; padding: 7px 14px; color: {WHITE}; }}
QPushButton:hover {{ background: rgba(54, 191, 255, 0.2); border-color: {CYAN}; }}
QPushButton:pressed {{ background: rgba(121, 91, 255, 0.35); }}
QPushButton:disabled {{ color: #5A6478; border-color: rgba(90, 100, 120, 0.3); }}
QPushButton#primary {{ background: rgba(54, 191, 255, 0.25); border-color: {CYAN}; font-weight: 600; }}
QPushButton#danger {{ border-color: rgba(255, 85, 85, 0.6); color: {ERROR}; }}
QPushButton#small {{ padding: 3px 9px; font-size: 11px; border-radius: 8px; }}
QPlainTextEdit, QLineEdit, QListWidget, QSpinBox, QDoubleSpinBox, QComboBox {{
    background: rgba(6, 10, 24, 0.42); border: 1px solid rgba(120, 170, 255, 0.24);
    border-radius: 10px; padding: 6px; selection-background-color: {VIOLET}; }}
QPlainTextEdit:focus, QLineEdit:focus {{ border-color: {CYAN}; }}
QListWidget::item {{ padding: 8px; border-radius: 8px; }}
QListWidget::item:selected {{ background: rgba(121, 91, 255, 0.35); }}
QListWidget::item:hover {{ background: rgba(54, 191, 255, 0.12); }}
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: rgba(54, 191, 255, 0.35); border-radius: 4px; min-height: 30px; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: rgba(54, 191, 255, 0.35); border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0px; width: 0px; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QAbstractScrollArea::corner {{ background: transparent; }}
QTabWidget::pane {{ border: 1px solid rgba(54, 191, 255, 0.22); border-radius: 12px; background: {BG_ALT}; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {TEXT_SECONDARY}; }}
QTabBar::tab:selected {{ color: {CYAN}; border-bottom: 2px solid {CYAN}; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {CYAN}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {CYAN}; }}
QSlider::groove:horizontal {{ height: 4px; background: rgba(54, 191, 255, 0.2); border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {CYAN}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QSlider::sub-page:horizontal {{ background: {VIOLET}; border-radius: 2px; }}
QProgressBar {{ background: rgba(6, 10, 24, 0.42); border: 1px solid rgba(54, 191, 255, 0.25);
               border-radius: 6px; text-align: center; height: 14px; }}
QProgressBar::chunk {{ background: {VIOLET}; border-radius: 6px; }}
QStatusBar {{ background: #05060C; color: {TEXT_SECONDARY}; border-top: 1px solid rgba(54, 191, 255, 0.15); }}
QToolTip {{ background: {BG_ALT}; color: {WHITE}; border: 1px solid {CYAN}; }}
QMessageBox {{ background: {BG_ALT}; }}

/* --- рабочее пространство v0.2 --- */
QFrame#controlBar {{ background: rgba(10, 16, 38, 0.48); border: 1px solid rgba(170, 195, 255, 0.20);
                    border-radius: 12px; }}
QPushButton#dockButton {{ background: transparent; border: 1px solid transparent; border-radius: 8px;
                         padding: 5px 10px; font-size: 11px; font-weight: 600; letter-spacing: 1px;
                         color: {TEXT_SECONDARY}; }}
QPushButton#dockButton:hover {{ color: {WHITE}; background: rgba(54, 191, 255, 0.10); }}
QPushButton#dockButton:checked {{ color: {CYAN}; background: rgba(54, 191, 255, 0.12);
                                 border-color: rgba(54, 191, 255, 0.45); }}
QPushButton#barButton {{ padding: 5px 10px; font-size: 11px; border-radius: 8px; }}
QLabel#panelTitle {{ color: {TEXT_SECONDARY}; font-size: 11px; font-weight: 600; letter-spacing: 2px; }}
QLabel#panelTitle[active="true"] {{ color: {WHITE}; }}
QLabel#panelHint {{ color: {TEXT_SECONDARY}; font-size: 11px; }}
QLabel#emptyState {{ color: {TEXT_SECONDARY}; font-size: 13px; letter-spacing: 1px; }}
QLabel#metricName {{ color: {TEXT_SECONDARY}; font-size: 11px; letter-spacing: 1px; }}
QLabel#metricValue {{ color: {WHITE}; font-size: 12px; font-weight: 600; }}
QTabWidget#sysTabs::pane {{ border: none; background: transparent; top: -1px; }}
QTabWidget#sysTabs QTabBar::tab {{ padding: 3px 8px; font-size: 11px; min-width: 0px; }}
QTableWidget#procTable {{ background: transparent; border: none; color: {WHITE}; font-size: 11px;
    gridline-color: transparent; selection-background-color: rgba(54, 191, 255, 0.18); }}
QTableWidget#procTable QHeaderView::section {{ background: transparent; color: {TEXT_SECONDARY};
    border: none; border-bottom: 1px solid rgba(54, 191, 255, 0.22); padding: 2px 4px; font-size: 10px; }}
QLabel#sessionLine {{ color: {WHITE}; font-size: 11px; }}
QPlainTextEdit#console {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
                          background: rgba(3, 6, 16, 0.5); border-color: rgba(61, 220, 200, 0.22); }}
QLineEdit#consoleInput {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px; }}
QPlainTextEdit#codeView {{ font-family: "Cascadia Mono", "Consolas", monospace; font-size: 12px;
                           background: rgba(3, 6, 16, 0.5); }}
QComboBox {{ padding: 4px 8px; }}
QProgressBar#metricBar, QProgressBar#metricBarHigh {{ background: rgba(54, 191, 255, 0.10); border: none;
                                                     border-radius: 3px; }}
QProgressBar#metricBar::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {CYAN}, stop:1 {TEAL}); }}
QProgressBar#metricBarHigh::chunk {{ border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {WARNING}, stop:1 {ERROR}); }}
QComboBox QAbstractItemView {{ background: {BG_ALT}; selection-background-color: rgba(121, 91, 255, 0.45); }}
"""
