"""Проверка команд ограниченной консоли TERMINAL.

Консоль выполняет только команды, которые пользователь сам ввёл. Перед запуском каждая команда
проходит проверку:
- повышение прав (runas, Start-Process -Verb RunAs, sudo и т. п.) и скрытые закодированные команды
  запрещены;
- удаление, перемещение и изменение файлов, работа с реестром, дисками, службами и питанием
  требуют отдельного подтверждения;
- остальные команды выполняются после нажатия Enter.

Оболочка (shell=True) не используется: программа и аргументы передаются списком.
Модуль не зависит от Qt.
"""

from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass, field

BUILTINS = ("cd", "clear", "cls", "history", "help")

_ELEVATION_PROGRAMS = {"runas", "sudo", "gsudo", "psexec", "psexec64", "nircmd", "elevate"}
_SHELLS = {"cmd", "powershell", "pwsh", "bash", "wsl", "sh"}

# программы, любое использование которых требует подтверждения
_DANGEROUS_PROGRAMS = {
    "del", "erase", "rd", "rmdir", "rm", "move", "mv", "ren", "rename", "copy", "xcopy", "robocopy",
    "format", "diskpart", "bcdedit", "bootrec", "chkdsk", "fsutil", "vssadmin", "cipher", "compact",
    "reg", "regedit", "regsvr32", "takeown", "icacls", "cacls", "attrib",
    "shutdown", "logoff", "taskkill", "sc", "net", "netsh", "schtasks", "wmic", "wevtutil",
    "sfc", "dism", "setx", "mklink", "msiexec", "winget", "choco",
}

# слова внутри команд оболочек (cmd /c ..., powershell -Command ...), требующие подтверждения
_DANGEROUS_WORDS = _DANGEROUS_PROGRAMS | {
    "remove-item", "move-item", "rename-item", "copy-item", "set-content", "add-content", "clear-content",
    "out-file", "new-item", "set-itemproperty", "remove-itemproperty", "new-itemproperty",
    "stop-process", "stop-service", "set-service", "restart-service", "stop-computer", "restart-computer",
    "set-executionpolicy", "format-volume", "clear-disk", "remove-partition", "invoke-expression", "iex",
    "invoke-webrequest", "iwr", "start-bitstransfer", "ri", "rni", "mi", "sc.exe",
}
_GIT_DANGEROUS = {"clean", "reset", "rm", "push", "checkout", "restore", "rebase", "filter-branch"}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*")
_REDIRECT_RE = re.compile(r"(^|[^0-9&])>{1,2}")  # перенаправление вывода в файл перезаписывает его
_SYSTEM_DIR_RE = re.compile(
    r"([a-z]:)?\\(windows|program files( \(x86\))?|programdata|system volume information)(\\|\b)", re.I
)


@dataclass(frozen=True)
class CommandCheck:
    argv: list[str] = field(default_factory=list)
    builtin: str | None = None          # встроенная команда консоли
    allowed: bool = True
    needs_confirmation: bool = False
    reasons: tuple[str, ...] = ()       # почему нужно подтверждение или почему команда запрещена

    @property
    def reason(self) -> str:
        return "; ".join(self.reasons)


def split_command(text: str) -> list[str]:
    """Разбивает строку на программу и аргументы по правилам, близким к Windows.

    Кавычки объединяют аргумент с пробелами, обратная косая черта остаётся как есть (пути Windows).
    """
    args: list[str] = []
    current: list[str] = []
    in_quotes = False
    has_token = False
    for ch in text.strip():
        if ch == '"':
            in_quotes = not in_quotes
            has_token = True
        elif ch.isspace() and not in_quotes:
            if has_token:
                args.append("".join(current))
                current, has_token = [], False
        else:
            current.append(ch)
            has_token = True
    if in_quotes:
        raise ValueError("Незакрытая кавычка")
    if has_token:
        args.append("".join(current))
    return args


def program_name(arg: str) -> str:
    name = arg.replace("/", "\\").rsplit("\\", 1)[-1].lower()
    for ext in (".exe", ".com", ".bat", ".cmd", ".ps1"):
        if name.endswith(ext):
            return name[: -len(ext)]
    return name


def check_command(text: str) -> CommandCheck:
    """Проверяет команду, введённую пользователем. Ничего не выполняет."""
    try:
        argv = split_command(text)
    except ValueError as exc:
        return CommandCheck(allowed=False, reasons=(str(exc),))
    if not argv:
        return CommandCheck(allowed=False, reasons=("Пустая команда",))

    program = program_name(argv[0])
    if program in BUILTINS:
        return CommandCheck(argv=argv, builtin="clear" if program == "cls" else program)

    lowered = [a.lower() for a in argv]
    joined = " ".join(lowered)
    words = {w.lower() for w in _WORD_RE.findall(joined)}

    # --- запрещено ---
    if program in _ELEVATION_PROGRAMS or "runas" in words or "-verb" in words and "runas" in joined:
        return CommandCheck(argv=argv, allowed=False,
                            reasons=("Запуск с правами администратора из SIRIUS запрещён",))
    if program in ("powershell", "pwsh") and any(
        a in ("-encodedcommand", "-enc", "-e", "-ec") or a.startswith("-encodedcommand") for a in lowered[1:]
    ):
        return CommandCheck(argv=argv, allowed=False,
                            reasons=("Закодированные (скрытые) команды PowerShell запрещены",))

    # --- требует подтверждения ---
    reasons: list[str] = []
    if program in _DANGEROUS_PROGRAMS:
        reasons.append(f"«{program}» изменяет файлы или систему")
    if program in _SHELLS:
        found = sorted(w for w in words if w in _DANGEROUS_WORDS and w != program)
        if found:
            reasons.append("внутри команды: " + ", ".join(found))
        if any(_REDIRECT_RE.search(a) for a in argv[1:]):
            reasons.append("перенаправление вывода в файл (>)")
    if program == "git" and len(lowered) > 1 and lowered[1] in _GIT_DANGEROUS:
        reasons.append(f"git {lowered[1]} может удалить или перезаписать изменения")
    if reasons and any(_SYSTEM_DIR_RE.search(a) for a in argv[1:]):
        reasons.append("затрагивает системную папку")
    return CommandCheck(argv=argv, needs_confirmation=bool(reasons), reasons=tuple(reasons))


def is_elevated() -> bool:
    """True, если процесс SIRIUS запущен с правами администратора (тогда консоль отключается)."""
    if sys.platform != "win32":
        try:
            import os

            return os.geteuid() == 0
        except AttributeError:
            return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False
