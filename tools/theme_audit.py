"""Что ещё мешает менять тему без перезапуска.

Показывает модули интерфейса, которые запоминают тему при загрузке:
  - импортируют цвета по имени (from interface.styles import CYAN) — после смены темы цвет остаётся прежним;
  - читают styles.X на уровне модуля (константы, словари) — значение вычисляется один раз.
Когда список пуст, в interface/styles.py можно включить LIVE_SWITCH.

Запуск: .venv\\Scripts\\python tools\\theme_audit.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# имена, которые не зависят от темы: их можно импортировать как угодно
STATIC = {"THEME_TITLES", "THEMES", "DEFAULT_THEME", "normalize_theme", "apply_theme", "set_theme", "notifier",
          "load_fonts", "rgb", "ThemeNotifier", "LIVE_SWITCH"}


def audit_file(path: Path) -> tuple[list[str], list[int]]:
    """(цвета, импортированные по имени; строки, где styles.X читается на уровне модуля)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "interface.styles":
            names += [a.name for a in node.names if a.name not in STATIC]
        elif isinstance(node, ast.ImportFrom) and node.module == "interface":
            aliases |= {a.asname or a.name for a in node.names if a.name == "styles"}
    lines: list[int] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ClassDef):       # значения по умолчанию и поля класса тоже считаются один раз
                scan = [n for n in node.body if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
            else:
                continue
        else:
            scan = [node]
        for part in scan:
            for sub in ast.walk(part):
                if (isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id in aliases
                        and sub.attr not in STATIC):
                    lines.append(sub.lineno)
    return sorted(set(names)), sorted(set(lines))


def audit(root: Path = ROOT) -> dict[str, tuple[list[str], list[int]]]:
    """Модули interface/, которые запоминают тему при загрузке: путь → (имена, строки)."""
    result = {}
    for path in sorted((root / "interface").rglob("*.py")):
        if path.name == "styles.py":
            continue
        names, lines = audit_file(path)
        if names or lines:
            result[path.relative_to(root).as_posix()] = (names, lines)
    return result


def main() -> int:
    found = audit()
    if not found:
        print("Все модули читают тему в момент рисования: LIVE_SWITCH можно включать.")
        return 0
    print(f"Модулей, которые запоминают тему при загрузке: {len(found)}\n")
    for rel, (names, lines) in found.items():
        print(rel)
        if names:
            print("    импорт по имени: " + ", ".join(names))
        if lines:
            print("    styles.* на уровне модуля, строки: " + ", ".join(map(str, lines)))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
