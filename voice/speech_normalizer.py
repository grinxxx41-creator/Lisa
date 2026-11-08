"""Подготовка текста к произношению русским голосом Piper.

Почему это нужно. Русский голос (ru_RU-irina) обучен только на русских звуках. Латинские слова
espeak-ng переводит в английские звуки (θ, ɹ, əʊ…), которых модель не знает, и вместо слова
получается неразборчивое «лювилирду». Поэтому латиница заранее записывается кириллицей:
известные слова — по словарю, аббревиатуры — по буквам, остальное — по правилам чтения.
Также раскрываются сокращения (т.е., т.к., г.), символы и единицы (%, °C, ГБ), убираются ссылки.

Модуль не зависит от Qt, функции чистые — их легко проверять тестами.
"""

from __future__ import annotations

import re

# --- словари ---------------------------------------------------------------------

# Слова и имена, которые часто встречаются в ответах LISA (ключ — в нижнем регистре)
WORDS: dict[str, str] = {
    "sirius": "сириус", "lisa": "лиза", "qwen": "квен", "ollama": "оллама", "piper": "пайпер",
    "python": "пайтон", "pytorch": "пайторч", "numpy": "нампай", "pandas": "пандас", "django": "джанго",
    "flask": "фласк", "pyside": "пайсайд", "pyqt": "пай-кью-ти", "qt": "кьют", "pip": "пип",
    "venv": "ви-энв", "pytest": "пайтест", "java": "джава", "javascript": "джаваскрипт",
    "typescript": "тайпскрипт", "node": "ноуд", "react": "риэкт", "html": "эйч-ти-эм-эл",
    "css": "си-эс-эс", "json": "джейсон", "yaml": "ямл", "sql": "эс-кью-эл", "sqlite": "эс-кью-лайт",
    "rust": "раст", "golang": "голэнг", "kotlin": "котлин", "swift": "свифт", "php": "пи-эйч-пи",
    "windows": "виндоус", "linux": "линукс", "ubuntu": "убунту", "macos": "мак-о-эс", "android": "андроид",
    "ios": "ай-о-эс", "iphone": "айфон", "apple": "эппл", "microsoft": "майкрософт", "google": "гугл",
    "chrome": "хром", "firefox": "файрфокс", "edge": "эдж", "github": "гитхаб", "gitlab": "гитлаб",
    "git": "гит", "docker": "докер", "nvidia": "энвидиа", "geforce": "джифорс", "amd": "эй-эм-ди",
    "ryzen": "райзен", "intel": "интел", "openai": "оупен-эй-ай", "chatgpt": "чат-джи-пи-ти",
    "claude": "клод", "gemini": "джемини", "llama": "лама", "mistral": "мистраль", "deepseek": "дипсик",
    "youtube": "ютуб", "telegram": "телеграм", "discord": "дискорд", "steam": "стим", "excel": "эксель",
    "word": "ворд", "office": "офис", "powershell": "пауэршелл", "cmd": "си-эм-ди", "bash": "баш",
    "terminal": "терминал", "console": "консоль", "vscode": "ви-эс-код", "code": "код", "studio": "студио",
    "ok": "окей", "okay": "окей", "wifi": "вай-фай", "email": "имейл", "online": "онлайн",
    "offline": "офлайн", "chat": "чат", "voice": "войс", "on": "он", "off": "офф", "workspace": "воркспейс",
    "system": "систем", "logs": "логи", "log": "лог", "history": "хистори", "settings": "сеттингс",
    "hello": "хеллоу", "world": "ворлд", "print": "принт", "def": "деф", "return": "ретёрн",
    "import": "импорт", "from": "фром", "class": "класс", "self": "селф", "true": "тру", "false": "фолс",
    "none": "нан", "null": "налл", "list": "лист", "dict": "дикт", "str": "стринг", "int": "инт",
    "float": "флоат", "range": "рейндж", "len": "лен", "sum": "сам", "for": "фор", "if": "иф",
    "else": "элс", "while": "вайл", "async": "эйсинк", "await": "эвейт", "file": "файл", "data": "дата",
    "model": "модел", "stream": "стрим", "reply": "риплай", "engine": "энджин", "server": "сервер",
    "client": "клиент", "update": "апдейт", "backup": "бэкап", "debug": "дебаг", "bug": "баг",
    "error": "эррор", "warning": "ворнинг", "info": "инфо", "the": "зе", "and": "энд", "or": "ор",
    "of": "оф", "to": "ту", "in": "ин", "is": "из", "it": "ит", "you": "ю", "are": "ар", "how": "хау",
    "what": "вот", "web": "веб", "app": "апп", "cloud": "клауд", "token": "токен", "tokens": "токены",
    "prompt": "промпт", "core": "кор", "thread": "тред", "main": "мейн", "window": "виндоу",
    "panel": "панель", "widget": "виджет", "layout": "лейаут", "test": "тест", "tests": "тесты",
    "commit": "коммит", "push": "пуш", "pull": "пулл", "merge": "мёрж", "branch": "бранч",
    "readme": "ридми", "changelog": "чейнджлог", "unavailable": "анавейлабл", "py": "пай",
    "exe": "экзе", "txt": "тэ-экс-тэ", "pdf": "пэ-дэ-эф", "zip": "зип", "png": "пи-эн-джи",
    "jpg": "джейпег", "mp3": "эм-пэ-три", "wav": "вэйв", "onnx": "оникс", "gpt": "джи-пи-ти",
    "llm": "эл-эл-эм", "tts": "ти-ти-эс", "usb": "ю-эс-би", "ssd": "эс-эс-ди", "api": "эй-пи-ай",
    "gpu": "джи-пи-ю", "cpu": "си-пи-ю", "ai": "эй-ай", "id": "ай-ди", "url": "ю-ар-эл", "pc": "пи-си",
    # единицы и сокращения, записанные латиницей
    "gb": "гигабайт", "mb": "мегабайт", "kb": "килобайт", "tb": "терабайт", "ghz": "гигагерц",
    "mhz": "мегагерц", "hz": "герц", "fps": "кадров в секунду", "ms": "миллисекунд",
    "ram": "оперативная память", "vram": "видеопамять",
}

# Русские сокращения: шаблон → как произносить
ABBREVIATIONS: list[tuple[str, str]] = [
    (r"\bи\s*т\.\s*д\.", "и так далее"),
    (r"\bи\s*т\.\s*п\.", "и тому подобное"),
    (r"\bт\.\s*е\.", "то есть"),
    (r"\bт\.\s*к\.", "так как"),
    (r"\bт\.\s*н\.", "так называемый"),
    (r"\bт\.\s*д\.", "так далее"),
    (r"\bт\.\s*п\.", "тому подобное"),
    (r"\bи\s+др\.", "и другие"),
    (r"\bнапр\.", "например"),
    (r"(\d)\s*см\b\.?", r"\1 сантиметров"),
    (r"(\d)\s*км\b\.?", r"\1 километров"),
    (r"(\d)\s*кг\b\.?", r"\1 килограммов"),
    (r"\bсм\.", "смотрите"),
    (r"(\d)\s*гг\.", r"\1 годы"),
    (r"(\d)\s*г\.", r"\1 год"),
    (r"(\d)\s*руб\.?", r"\1 рублей"),
    (r"(\d)\s*коп\.?", r"\1 копеек"),
    (r"(\d)\s*тыс\.?", r"\1 тысяч"),
    (r"(\d)\s*млн\.?", r"\1 миллионов"),
    (r"(\d)\s*млрд\.?", r"\1 миллиардов"),
    (r"(\d)\s*мин\.", r"\1 минут"),
    (r"(\d)\s*сек\.", r"\1 секунд"),
    (r"(\d)\s*ГБ\b", r"\1 гигабайт"),
    (r"(\d)\s*МБ\b", r"\1 мегабайт"),
    (r"(\d)\s*КБ\b", r"\1 килобайт"),
    (r"(\d)\s*ТБ\b", r"\1 терабайт"),
    (r"(\d)\s*ГГц\b", r"\1 гигагерц"),
    (r"(\d)\s*МГц\b", r"\1 мегагерц"),
    (r"(\d)\s*мс\b", r"\1 миллисекунд"),
    (r"\bИИ\b", "и-и"),
    (r"\bСША\b", "сэ-шэ-а"),
    (r"\bРФ\b", "эр-эф"),
    (r"\bОЗУ\b", "оперативная память"),
    (r"\bОС\b", "о-эс"),
    (r"\bПК\b", "пэ-ка"),
    (r"№\s*", "номер "),
]
_ABBREVIATIONS = [(re.compile(p, re.IGNORECASE if p.startswith(r"\b") and p[2].islower() else 0), r)
                  for p, r in ABBREVIATIONS]

LETTERS = {
    "a": "эй", "b": "би", "c": "си", "d": "ди", "e": "и", "f": "эф", "g": "джи", "h": "эйч", "i": "ай",
    "j": "джей", "k": "кей", "l": "эл", "m": "эм", "n": "эн", "o": "оу", "p": "пи", "q": "кью", "r": "ар",
    "s": "эс", "t": "ти", "u": "ю", "v": "ви", "w": "дабл-ю", "x": "экс", "y": "уай", "z": "зед",
}

# Правила чтения английских слов (от длинных сочетаний к коротким)
_RULES = [
    ("tion", "шн"), ("sion", "жн"), ("ture", "чер"), ("ight", "айт"), ("igh", "ай"), ("ough", "оу"),
    ("augh", "о"), ("sch", "ск"), ("tch", "ч"), ("ch", "ч"), ("sh", "ш"), ("th", "т"), ("ph", "ф"),
    ("wh", "в"), ("ck", "к"), ("qu", "кв"), ("ee", "и"), ("ea", "и"), ("oo", "у"), ("ou", "ау"),
    ("ow", "оу"), ("ai", "эй"), ("ay", "эй"), ("oa", "оу"), ("oi", "ой"), ("oy", "ой"), ("au", "о"),
    ("aw", "о"), ("ew", "ью"), ("ie", "и"), ("ng", "нг"), ("x", "кс"), ("ce", "се"), ("ci", "си"),
    ("cy", "си"), ("ge", "дж"), ("gi", "джи"), ("y", "и"), ("a", "а"), ("b", "б"), ("c", "к"), ("d", "д"),
    ("e", "е"), ("f", "ф"), ("g", "г"), ("h", "х"), ("i", "и"), ("j", "дж"), ("k", "к"), ("l", "л"),
    ("m", "м"), ("n", "н"), ("o", "о"), ("p", "п"), ("q", "к"), ("r", "р"), ("s", "с"), ("t", "т"),
    ("u", "у"), ("v", "в"), ("w", "в"), ("z", "з"),
]
_MAGIC_E = {"a": "эй", "i": "ай", "o": "оу", "u": "ю", "e": "и"}
_VOWELS = set("aeiouy")

_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b")
_WIN_PATH_RE = re.compile(r"\b[A-Za-z]:\\(?:[^\s,;]*[^\s,;.!?:])?")
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:[.\-'][A-Za-z0-9_]+)*")
_PARTS_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
_THOUSANDS_RE = re.compile(r"(?<![\d.,])(\d{1,3})(?:[  ](\d{3}))+(?![\d.,])")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_DEGREE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*°\s*[CС]?")
_TIMES_RE = re.compile(r"(\d)\s*[×xх]\s*(\d)")


# --- правила ---------------------------------------------------------------------


def plural(number: str, one: str, few: str, many: str) -> str:
    """Форма слова после числа: 1 процент, 2 процента, 5 процентов; дробь — «процента»."""
    if "." in number or "," in number:
        return few
    n = int(number) % 100
    if 11 <= n <= 14:
        return many
    last = n % 10
    if last == 1:
        return one
    if 2 <= last <= 4:
        return few
    return many


def transliterate_word(word: str) -> str:
    """Английское слово (только буквы) → кириллица по упрощённым правилам чтения."""
    w = word.lower()
    if not w:
        return ""
    if w in WORDS:
        return WORDS[w]
    # «немая e»: make → мейк, code → коуд
    tail = ""
    if len(w) >= 4 and w.endswith("e") and w[-2] not in _VOWELS and w[-3] in _MAGIC_E and w[-4] not in _VOWELS:
        tail = _MAGIC_E[w[-3]] + _translit_plain(w[-2])
        w = w[:-3]
    # после согласной русская запись английского «эй» — «ей»: make → мейк, day → дей
    return re.sub(r"(?<=[бвгджзклмнпрстфхцчшщ])э", "е", _translit_plain(w) + tail)


def _translit_plain(w: str) -> str:
    out, i = [], 0
    while i < len(w):
        for src, dst in _RULES:
            if w.startswith(src, i):
                # y в начале слова перед гласной — «й»: yes → йес
                if src == "y" and i == 0 and len(w) > 1 and w[1] in _VOWELS:
                    dst = "й"
                out.append(dst)
                i += len(src)
                break
        else:
            i += 1  # символ без правила пропускается
    return "".join(out)


def _spell(acronym: str) -> str:
    return "-".join(LETTERS.get(ch, ch) for ch in acronym.lower())


def latin_token_to_russian(token: str) -> str:
    """Слово, идентификатор или аббревиатура латиницей → как это произнести по-русски.

    stream_reply → «стрим риплай», AIEngine → «эй-ай энджин», GPU → «джи-пи-ю», qwen3 → «квен 3».
    """
    low = token.lower()
    if low in WORDS:
        return WORDS[low]
    words = []
    for chunk in re.split(r"[_.\-']+", token):
        if not chunk:
            continue
        if chunk.lower() in WORDS:
            words.append(WORDS[chunk.lower()])
            continue
        for part in _PARTS_RE.findall(chunk):
            if part.isdigit():
                words.append(part)
            elif part.lower() in WORDS:
                words.append(WORDS[part.lower()])
            elif part.isupper() and len(part) <= 5 or len(part) == 1:
                words.append(_spell(part))
            else:
                words.append(transliterate_word(part))
    return " ".join(w for w in words if w)


def normalize_for_speech(text: str) -> str:
    """Готовит фразу к синтезу: только то, что русский голос может нормально произнести."""
    text = re.sub(r"\(\s*\)", "", text)                       # print() → print
    text = _URL_RE.sub(" ссылка ", text)
    text = _EMAIL_RE.sub(" адрес почты ", text)
    text = _WIN_PATH_RE.sub(" путь к файлу ", text)

    # числа: «1 500» → «1500», проценты, градусы, размеры
    text = _THOUSANDS_RE.sub(lambda m: m.group(0).replace(" ", "").replace(" ", ""), text)
    text = _PERCENT_RE.sub(lambda m: f"{m.group(1)} {plural(m.group(1), 'процент', 'процента', 'процентов')}", text)
    text = _DEGREE_RE.sub(lambda m: f"{m.group(1)} {plural(m.group(1), 'градус', 'градуса', 'градусов')}", text)
    text = _TIMES_RE.sub(r"\1 на \2", text)

    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)

    text = _LATIN_TOKEN_RE.sub(lambda m: " " + latin_token_to_russian(m.group(0)) + " ", text)
    text = re.sub(r"(?<=\d)\s*:\s*(?=\d)", " ", text)         # 3:8, 10:30

    # символы
    text = re.sub(r"\s[—–-]\s|[—–]", ", ", text)              # тире — пауза
    text = re.sub(r"(?<=\d)\s*\+\s*(?=\d)", " плюс ", text)
    text = re.sub(r"(?<=\d)\s*=\s*(?=\d)", " равно ", text)
    text = re.sub(r"\s*[(\[]\s*", ", ", text)                 # скобки — паузы
    text = re.sub(r"\s*[)\]]\s*", ", ", text)
    text = text.replace("…", ".").replace("&", " и ")
    text = re.sub("[←-⇿➔➡]", " ", text)   # стрелки
    text = re.sub(r"[«»\"“”„*_#|\\/^~<>{}=+@$`]", " ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r"([,;:])(?:\s*[,;:])+", r"\1", text)       # «, ,» после замен
    text = re.sub(r"^[\s,;:.]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text
