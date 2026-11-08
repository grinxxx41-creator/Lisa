"""Точка входа SIRIUS v0.2: настройка логирования и запуск главного окна.

Запуск двойным кликом: ярлык SIRIUS (tools/create_shortcut.py) запускает этот файл через
.venv\\Scripts\\pythonw.exe — без окна консоли. Поэтому ошибки запуска показываются в окне
сообщения и пишутся в logs/sirius.log, а не в консоль.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ICON_PATH = BASE_DIR / "resources" / "icons" / "sirius.ico"
LOCK_PATH = BASE_DIR / "storage" / "sirius.lock"
APP_USER_MODEL_ID = "SIRIUS.LISA.Assistant"


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(log_dir / "sirius.log", encoding="utf-8")]
    stream = sys.stderr
    if stream is not None:  # при запуске через pythonw стандартного потока ошибок нет
        if hasattr(stream, "reconfigure"):
            # консоль Windows может быть не в UTF-8: русский текст не должен ломать журнал
            stream.reconfigure(encoding="utf-8", errors="replace")
        handlers.append(logging.StreamHandler(stream))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _install_excepthook() -> None:
    """Без консоли необработанные ошибки иначе пропали бы бесследно: пишем их в журнал."""
    log = logging.getLogger("sirius")

    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        log.critical("Необработанная ошибка", exc_info=(exc_type, exc, tb))

    sys.excepthook = hook


def _native_error(text: str) -> None:
    """Сообщение об ошибке, когда Qt ещё не загружен (например, сломано окружение .venv)."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(None, text, "SIRIUS", 0x10)
            return
        except Exception:
            pass
    print(text, file=sys.stderr or sys.__stdout__)


def _set_app_user_model_id() -> None:
    """Своя иконка и группа на панели задач Windows, а не значок Python."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        logging.getLogger("sirius").debug("AppUserModelID не установлен", exc_info=True)


def main() -> int:
    setup_logging(BASE_DIR / "logs")
    _install_excepthook()
    log = logging.getLogger("sirius")
    log.info("Запуск SIRIUS v0.2")

    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as exc:
        log.critical("Не удалось загрузить PySide6: %s", exc)
        _native_error(
            "Не удалось запустить SIRIUS: не найдены библиотеки интерфейса (PySide6).\n\n"
            "Установите зависимости: .venv\\Scripts\\pip install -r requirements.txt"
        )
        return 1

    _set_app_user_model_id()
    app = QApplication(sys.argv)
    app.setApplicationName("SIRIUS")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    from core.single_instance import SingleInstance, channel_name

    instance = SingleInstance(LOCK_PATH, channel_name(BASE_DIR))
    if not instance.acquire():
        log.info("SIRIUS уже запущен: окно выведено на передний план")
        return 0

    try:
        from interface.main_window import MainWindow
        from interface.styles import STYLE

        app.setStyleSheet(STYLE)
        window = MainWindow(BASE_DIR)
    except Exception as exc:
        log.exception("Ошибка запуска главного окна")
        QMessageBox.critical(
            None, "SIRIUS",
            f"Не удалось запустить SIRIUS:\n{exc}\n\nПодробности в журнале logs/sirius.log",
        )
        instance.release()
        return 1

    def bring_to_front() -> None:
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()

    instance.activation_requested.connect(bring_to_front)
    window.show()
    code = app.exec()
    instance.release()
    log.info("Приложение завершено (код %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
