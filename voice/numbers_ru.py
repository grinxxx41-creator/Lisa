"""Числа словами по-русски для Silero TTS (Silero пропускает цифры). Без зависимостей."""

from __future__ import annotations

import re

_UNITS = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
_UNITS_F = ["ноль", "одна", "две"]
_TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
          "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать"]
_TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят",
         "восемьдесят", "девяносто"]
_HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот",
             "восемьсот", "девятьсот"]
# (единственное, 2–4, 5+), женский род
_SCALES = [(("тысяча", "тысячи", "тысяч"), True), (("миллион", "миллиона", "миллионов"), False),
           (("миллиард", "миллиарда", "миллиардов"), False)]


def _form(n: int, forms: tuple[str, str, str]) -> str:
    if 11 <= n % 100 <= 14:
        return forms[2]
    return forms[0] if n % 10 == 1 else forms[1] if 2 <= n % 10 <= 4 else forms[2]


def _triple(n: int, feminine: bool) -> list[str]:
    words = []
    if n >= 100:
        words.append(_HUNDREDS[n // 100])
    rest = n % 100
    if 10 <= rest < 20:
        words.append(_TEENS[rest - 10])
        return words
    if rest >= 20:
        words.append(_TENS[rest // 10])
    unit = rest % 10
    if unit:
        words.append(_UNITS_F[unit] if feminine and unit < 3 else _UNITS[unit])
    return words


def int_to_words(n: int, feminine: bool = False) -> str:
    if n == 0:
        return "ноль"
    if n < 0:
        return "минус " + int_to_words(-n, feminine)
    if n >= 10 ** 12:  # длинные номера — по цифрам
        return " ".join(_UNITS[int(d)] for d in str(n))
    words: list[str] = []
    groups = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        if i == 0:
            words += _triple(g, feminine)
        else:
            forms, fem = _SCALES[i - 1]
            words += _triple(g, fem) + [_form(g, forms)]
    return " ".join(words)


_FRACTION = {1: ("десятая", "десятых", "десятых"), 2: ("сотая", "сотых", "сотых"),
             3: ("тысячная", "тысячных", "тысячных")}


def number_to_words(token: str) -> str:
    """'45' → 'сорок пять', '12,5' → 'двенадцать целых пять десятых', '3.12' → 'три точка двенадцать'."""
    m = re.fullmatch(r"(\d+)([.,])(\d+)", token)
    if m:
        whole, sep, frac = m.groups()
        if sep == "," and len(frac) <= 3:
            w = int(whole)
            f = int(frac)
            return (f"{int_to_words(w, True)} {_form(w, ('целая', 'целых', 'целых'))} "
                    f"{int_to_words(f, True)} {_form(f, _FRACTION[len(frac)])}")
        # версии, время и т. п.: читаем части по отдельности
        return f"{_digits_group(whole)} точка {_digits_group(frac)}"
    return _digits_group(token)


def _digits_group(digits: str) -> str:
    if len(digits) > 1 and digits.startswith("0"):
        return " ".join(_UNITS[int(d)] for d in digits)
    return int_to_words(int(digits))


_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)?(?![\w])|\d+")


def numbers_to_words(text: str) -> str:
    """Заменяет все числа в тексте словами."""
    return _NUMBER.sub(lambda m: number_to_words(m.group(0)), text)
