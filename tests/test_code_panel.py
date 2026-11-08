"""Блоки кода: разбор Markdown, панель CODE, отсутствие кода."""

from __future__ import annotations

from PySide6.QtGui import QGuiApplication

from core.code_blocks import extract_code_blocks, normalize_language
from interface.panels.code_panel import EMPTY_TEXT, CodePanel

ANSWER = """Вот пример:

```python
def hello():
    s = \"\"\"многострочная
строка\"\"\"
    return s
```

И команда:

~~~ps1
Get-ChildItem
~~~

Код без языка:

```
plain text
```
"""


def test_extract_blocks_with_languages():
    blocks = extract_code_blocks(ANSWER)
    assert [b.language for b in blocks] == ["python", "powershell", ""]
    assert blocks[0].code.startswith("def hello():")
    assert blocks[0].code.endswith("return s")
    assert blocks[1].code == "Get-ChildItem"
    assert blocks[2].display_language == "text"
    assert all(b.complete for b in blocks)
    assert [b.index for b in blocks] == [1, 2, 3]


def test_no_code_in_plain_answer():
    assert extract_code_blocks("Столица Италии — Рим. Используйте `print()` в Python.") == []


def test_unclosed_block_only_on_request():
    text = "Начало\n```js\nconsole.log(1)"
    assert extract_code_blocks(text) == []
    blocks = extract_code_blocks(text, include_incomplete=True)
    assert blocks[0].language == "javascript" and not blocks[0].complete


def test_longer_fence_contains_shorter():
    text = "````markdown\n```python\nx = 1\n```\n````"
    blocks = extract_code_blocks(text)
    assert len(blocks) == 1
    assert "```python" in blocks[0].code


def test_language_aliases():
    assert normalize_language(" py title=x") == "python"
    assert normalize_language("{.cpp}") == "cpp"
    assert normalize_language("language-ts") == "typescript"
    assert normalize_language("") == ""


def test_panel_shows_empty_state(qt_app):
    panel = CodePanel()
    panel.set_messages(["Просто текст без кода"])
    assert panel.stack.currentWidget() is panel.empty_label
    assert panel.empty_label.text() == EMPTY_TEXT == "No code generated"
    assert not panel.copy_btn.isEnabled()


def test_panel_shows_blocks_newest_first(qt_app):
    panel = CodePanel()
    panel.set_messages([ANSWER])
    panel.add_message("```bash\necho hi\n```")
    assert panel.selector.count() == 4
    assert panel.current_code() == "echo hi"         # выбран блок из нового ответа
    assert panel.view.toPlainText() == "echo hi"
    assert panel.view.isReadOnly()
    panel.selector.setCurrentIndex(1)
    assert panel.current_code().startswith("def hello():")


def test_panel_copy_block(qt_app):
    panel = CodePanel()
    panel.set_messages(["```python\nprint('x')\n```"])
    panel.copy_current()
    assert QGuiApplication.clipboard().text() == "print('x')"


def test_highlighting_applies_formats(qt_app):
    panel = CodePanel()
    panel.set_messages(["```python\ndef f():\n    return 'a'\n```"])
    block = panel.view.document().firstBlock()
    assert block.layout().formats(), "ключевое слово def должно быть подсвечено"


def test_unknown_language_still_shown(qt_app):
    panel = CodePanel()
    panel.set_messages(["```nosuchlang\nabc\n```"])
    assert panel.view.toPlainText() == "abc"


def test_window_code_panel_follows_dialog(qt_app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from interface.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    win = MainWindow(tmp_path)
    try:
        chat_id = win._current_chat_id
        win.chats.add_message(chat_id, "user", "Напиши код")
        win.chats.add_message(chat_id, "assistant", "```python\nx = 1\n```")
        win._open_chat(chat_id)
        assert win.code_panel.current_code() == "x = 1"
        win._new_chat()
        assert win.code_panel.blocks() == []
    finally:
        win.close()
