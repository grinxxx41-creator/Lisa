"""Подготовка текста для озвучивания: очистка Markdown и разбиение потока на завершённые фразы.

Поток ответа приходит кусками. Фраза отдаётся на синтез только когда она точно закончилась:
- после знака конца предложения уже пришёл пробел или перевод строки (иначе «Python 3.» и «12»
  или «т.» и «е.» прочитались бы как отдельные фразы);
- точка после одной буквы или известного сокращения (т. е., г., руб.) фразу не завершает;
- блоки кода (``` … ```) не озвучиваются, даже если приходят по частям.
Каждая фраза перед синтезом проходит speech_normalizer: латиница, сокращения и символы
записываются так, как их нужно произнести.
"""

from __future__ import annotations

import re

from voice.speech_normalizer import normalize_for_speech

MIN_SPEECH_CHARS = 25    # короткие фрагменты объединяются со следующими
MAX_SPEECH_CHARS = 260   # длинная фраза делится по запятым: голос начинает говорить быстрее
CODE_ONLY_PHRASE = "Код показан на экране."

_CODE_BLOCK_RE = re.compile(r"(```|~~~).*?(\1|$)", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKUP_RE = re.compile(r"(\*\*|__|~~|(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w))")
_LINE_MARKERS_RE = re.compile(r"^\s*(?:#{1,6}\s+|>\s*|[-*+•]\s+|\d+[.)]\s+)")
_RULE_RE = re.compile(r"^\s*([-*_=])\1{2,}\s*$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}")
_SENTENCE_END_RE = re.compile(r"[.!?…]+(?=\s)")
_FENCE_RE = re.compile(r"^\s*(```|~~~)")
# эмодзи и декоративные символы: озвучивать их не нужно
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF←-⇿⌀-➿⬀-⯿️‍]"
)
# точка после этих слов не завершает предложение
_NO_SPLIT_WORDS = {
    "т", "е", "к", "д", "п", "н", "г", "гг", "др", "пр", "руб", "коп", "тыс", "млн", "млрд", "см",
    "напр", "стр", "рис", "им", "ул", "мин", "сек", "ок", "св", "проф", "доц", "акад", "вкл", "откл",
}
_WORD_BEFORE_RE = re.compile(r"(\w+)$")


def clean_markdown(text: str) -> str:
    """Убирает разметку и блоки кода, чтобы TTS не читал служебные символы."""
    text = _CODE_BLOCK_RE.sub(" ", text)
    text = _INLINE_CODE_RE.sub(r"\1", text)
    text = _LINK_RE.sub(r"\1", text)
    lines = []
    for line in text.split("\n"):
        if _RULE_RE.match(line) or _TABLE_SEP_RE.match(line):
            continue
        line = _LINE_MARKERS_RE.sub("", line)
        line = line.replace("|", ", ")
        lines.append(line)
    text = "\n".join(lines)
    text = _MARKUP_RE.sub("", text)
    text = _EMOJI_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def prepare_phrase(text: str) -> str:
    """Markdown → чистый текст → текст для произношения."""
    return normalize_for_speech(clean_markdown(text))


def _is_sentence_end(text: str, dot_index: int) -> bool:
    """Точка после одной буквы (инициалы, «т. е.») или сокращения не завершает фразу."""
    if text[dot_index] != ".":
        return True
    m = _WORD_BEFORE_RE.search(text[:dot_index])
    if m is None:
        return True
    word = m.group(1).lower()
    if word.isdigit():
        # «1.» в начале строки — номер пункта списка, а не конец предложения
        line_start = text.rfind("\n", 0, m.start()) + 1
        return text[line_start:m.start()].strip() != ""
    return not (len(word) == 1 or word in _NO_SPLIT_WORDS)


class SentenceBuffer:
    """Накапливает потоковый текст и выдаёт только завершённые фразы, готовые к синтезу."""

    def __init__(self) -> None:
        self._text = ""          # озвучиваемый текст (вне блоков кода), ещё не отданный
        self._line = ""          # текущая строка, если ещё неясно, не ограда ли это блока кода
        self._line_is_text = False
        self._in_code = False
        self._saw_code = False   # в ответе был блок кода
        self._spoke = False      # из ответа уже отдана хотя бы одна фраза

    # --- разбор строк и блоков кода ---------------------------------------------------

    def _finish_line(self) -> None:
        line, was_text = self._line, self._line_is_text
        self._line, self._line_is_text = "", False
        if was_text:
            self._text += "\n"
            return
        if _FENCE_RE.match(line):
            self._in_code = not self._in_code   # открытие или закрытие блока кода
            self._saw_code = True
            return
        if not self._in_code:
            self._text += line + "\n"

    def _consume(self, delta: str) -> None:
        parts = delta.split("\n")
        for i, part in enumerate(parts):
            if self._line_is_text:
                self._text += part
            else:
                self._line += part
                stripped = self._line.lstrip()
                # строка, которая точно не начинается с ограды, сразу идёт в текст
                if not self._in_code and stripped and stripped[0] not in "`~":
                    self._text += self._line
                    self._line, self._line_is_text = "", True
            if i < len(parts) - 1:
                self._finish_line()

    # --- выдача фраз ------------------------------------------------------------------

    def _cut(self, final: bool) -> list[str]:
        ready: list[str] = []
        last = 0
        boundaries = [m.end() for m in _SENTENCE_END_RE.finditer(self._text) if _is_sentence_end(self._text, m.start())]
        boundaries += [m.start() for m in re.finditer(r"\n", self._text)]
        for end in sorted(set(boundaries)):
            if end > last:
                ready.append(self._text[last:end])
                last = end
        self._text = self._text[last:]
        if final:
            if self._line and not self._in_code and not _FENCE_RE.match(self._line):
                self._text += self._line
            ready.append(self._text)
        phrases = [p for p in (prepare_phrase(s) for s in ready) if re.search(r"\w", p)]
        if final:
            if self._line.lstrip().startswith(("```", "~~~")) or self._in_code:
                self._saw_code = True
            if not phrases and not self._spoke and self._saw_code:
                phrases = [CODE_ONLY_PHRASE]   # ответ — только код: LISA не молчит
            self._text, self._line, self._line_is_text, self._in_code = "", "", False, False
            self._saw_code = self._spoke = False
        result = _split_long(_merge_short(phrases))
        self._spoke = self._spoke or bool(result)
        return result

    def feed(self, delta: str) -> list[str]:
        self._consume(delta)
        return self._cut(final=False)

    def flush(self) -> list[str]:
        """Конец ответа: отдаёт остаток текста (блок кода без закрывающей ограды не озвучивается)."""
        return self._cut(final=True)


def _merge_short(parts: list[str]) -> list[str]:
    merged: list[str] = []
    carry = ""
    for part in parts:
        candidate = f"{carry} {part}".strip() if carry else part
        if len(candidate) < MIN_SPEECH_CHARS:
            carry = candidate
        else:
            merged.append(candidate)
            carry = ""
    if carry:
        if merged:
            merged[-1] = f"{merged[-1]} {carry}"
        else:
            merged.append(carry)
    return merged


def _split_long(parts: list[str]) -> list[str]:
    out: list[str] = []
    for part in parts:
        while len(part) > MAX_SPEECH_CHARS:
            cut = max(part.rfind(", ", 0, MAX_SPEECH_CHARS), part.rfind("; ", 0, MAX_SPEECH_CHARS))
            if cut < MIN_SPEECH_CHARS:
                cut = part.rfind(" ", 0, MAX_SPEECH_CHARS)
            if cut < MIN_SPEECH_CHARS:
                break
            out.append(part[: cut + 1].strip())
            part = part[cut + 1:].strip()
        if part:
            out.append(part)
    return out
