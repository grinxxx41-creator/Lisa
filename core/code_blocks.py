"""Извлечение блоков кода из Markdown-ответов модели.

Разбираются только огороженные блоки (``` или ~~~). Язык берётся из строки после открывающей
ограды, если модель его указала. Код никогда не выполняется — только показывается и копируется.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_FENCE_RE = re.compile(r"^ {0,3}(?P<fence>`{3,}|~{3,})(?P<info>[^\n`]*)$")

_ALIASES = {
    "py": "python", "python3": "python", "py3": "python",
    "js": "javascript", "node": "javascript", "jsx": "javascript",
    "ts": "typescript", "tsx": "typescript",
    "sh": "bash", "shell": "bash", "zsh": "bash", "console": "bash",
    "ps": "powershell", "ps1": "powershell", "pwsh": "powershell",
    "bat": "batch", "cmd": "batch",
    "c++": "cpp", "cc": "cpp", "hpp": "cpp",
    "c#": "csharp", "cs": "csharp",
    "yml": "yaml", "md": "markdown", "html": "html", "htm": "html",
    "golang": "go", "rs": "rust", "kt": "kotlin", "rb": "ruby",
}


@dataclass(frozen=True)
class CodeBlock:
    index: int          # номер блока в сообщении, с 1
    language: str       # "" — язык не указан
    code: str
    complete: bool      # False — ответ оборвался внутри блока

    @property
    def display_language(self) -> str:
        return self.language or "text"


def normalize_language(info: str) -> str:
    """Первое слово строки после ограды в нижнем регистре, с распространёнными синонимами."""
    word = info.strip().split(maxsplit=1)[0] if info.strip() else ""
    word = word.strip("{}.").lower()
    if word.startswith("language-"):
        word = word[len("language-"):]
    return _ALIASES.get(word, word)


def extract_code_blocks(text: str, include_incomplete: bool = False) -> list[CodeBlock]:
    """Возвращает блоки кода в порядке появления.

    Незакрытый блок в конце (обрыв генерации) возвращается только при include_incomplete=True.
    """
    blocks: list[CodeBlock] = []
    lines = text.splitlines()
    fence: str | None = None
    language = ""
    body: list[str] = []
    for line in lines:
        if fence is None:
            m = _FENCE_RE.match(line)
            if m:
                fence = m.group("fence")
                language = normalize_language(m.group("info"))
                body = []
            continue
        stripped = line.strip()
        if stripped and stripped[0] == fence[0] and set(stripped) == {fence[0]} and len(stripped) >= len(fence):
            blocks.append(CodeBlock(len(blocks) + 1, language, "\n".join(body), True))
            fence = None
            continue
        body.append(line)
    if fence is not None and include_incomplete:
        blocks.append(CodeBlock(len(blocks) + 1, language, "\n".join(body), False))
    return blocks
