"""Автозапуск SIRIUS вместе с Windows: запись в HKCU\\...\\Run текущего пользователя.

Права администратора не нужны, системные настройки не меняются. По умолчанию выключен.
Запуск — через pythonw.exe (без окна консоли), как ярлык на рабочем столе.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

log = logging.getLogger("sirius.autostart")

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "SIRIUS"


def command_line(base_dir: Path) -> str:
    """Команда запуска: pythonw.exe из виртуального окружения проекта и main.py."""
    base_dir = Path(base_dir)
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.exists():
        venv = base_dir / ".venv" / "Scripts" / "pythonw.exe"
        pythonw = venv if venv.exists() else exe
    return f'"{pythonw}" "{base_dir / "main.py"}"'


class Autostart:
    """Чтение и изменение автозапуска. registry — модуль winreg (подменяется в тестах)."""

    def __init__(self, base_dir: Path, registry=None) -> None:
        self.base_dir = Path(base_dir)
        if registry is None and sys.platform == "win32":
            import winreg as registry  # noqa: PLW0127
        self._reg = registry

    @property
    def supported(self) -> bool:
        return self._reg is not None

    def is_enabled(self) -> bool:
        if self._reg is None:
            return False
        try:
            with self._reg.OpenKey(self._reg.HKEY_CURRENT_USER, RUN_KEY, 0, self._reg.KEY_READ) as key:
                value, _ = self._reg.QueryValueEx(key, VALUE_NAME)
                return bool(value)
        except OSError:
            return False

    def set_enabled(self, enabled: bool) -> bool:
        """Включает или выключает автозапуск. Возвращает True при успехе."""
        if self._reg is None:
            return False
        try:
            with self._reg.OpenKey(self._reg.HKEY_CURRENT_USER, RUN_KEY, 0, self._reg.KEY_SET_VALUE) as key:
                if enabled:
                    self._reg.SetValueEx(key, VALUE_NAME, 0, self._reg.REG_SZ, command_line(self.base_dir))
                else:
                    try:
                        self._reg.DeleteValue(key, VALUE_NAME)
                    except FileNotFoundError:
                        pass
            log.info("Автозапуск %s", "включён" if enabled else "выключен")
            return True
        except OSError as exc:
            log.error("Не удалось изменить автозапуск: %s", exc)
            return False
