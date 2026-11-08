"""Ярлык для запуска SIRIUS двойным кликом, без окна консоли.

Ярлык запускает main.py через .venv\\Scripts\\pythonw.exe (Python без консоли), рабочая папка — проект.
По умолчанию ярлык создаётся на рабочем столе и в папке проекта. Если проект переместить,
скрипт нужно запустить ещё раз: в ярлыке хранятся полные пути.

    .venv\\Scripts\\python.exe tools\\create_shortcut.py              рабочий стол и папка проекта
    .venv\\Scripts\\python.exe tools\\create_shortcut.py --start-menu  дополнительно меню «Пуск»

Иконка resources/icons/sirius.ico создаётся из изображения LISA, если её ещё нет.
"""

from __future__ import annotations

import os
import struct
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent
ICON = PROJECT / "resources" / "icons" / "sirius.ico"
AVATAR = PROJECT / "resources" / "images" / "lisa.png"
PYTHONW = PROJECT / ".venv" / "Scripts" / "pythonw.exe"
ENTRY = PROJECT / "main.py"
ICON_SIZES = (16, 24, 32, 48, 64, 128, 256)
HEAD_CROP = (0.17, 0.04, 0.67, 0.40)   # голова LISA на lisa.png: x, y, ширина, высота (доли)

_CREATE_LNK = r"""
$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($env:SIRIUS_LNK)
$lnk.TargetPath = $env:SIRIUS_TARGET
$lnk.Arguments = $env:SIRIUS_ARGS
$lnk.WorkingDirectory = $env:SIRIUS_WORKDIR
$lnk.IconLocation = $env:SIRIUS_ICON
$lnk.Description = 'SIRIUS - LISA, локальный ИИ-помощник'
$lnk.WindowStyle = 1
$lnk.Save()
"""


def _icon_image(size: int):
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient

    img = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    r = QRectF(0.5, 0.5, size - 1, size - 1)
    shape = QPainterPath()
    shape.addRoundedRect(r, size * 0.22, size * 0.22)
    bg = QLinearGradient(QPointF(0, 0), QPointF(0, size))
    bg.setColorAt(0.0, QColor(22, 26, 70))
    bg.setColorAt(1.0, QColor(6, 8, 20))
    p.fillPath(shape, bg)
    glow = QRadialGradient(QPointF(size / 2, size * 0.45), size * 0.55)
    glow.setColorAt(0.0, QColor(54, 191, 255, 110))
    glow.setColorAt(1.0, QColor(121, 91, 255, 0))
    p.fillPath(shape, glow)
    avatar = QImage(str(AVATAR))
    if not avatar.isNull():
        x, y, w, h = HEAD_CROP
        head = avatar.copy(int(x * avatar.width()), int(y * avatar.height()),
                           int(w * avatar.width()), int(h * avatar.height()))
        p.save()
        p.setClipPath(shape)
        side = size * 0.98
        p.drawImage(QRectF((size - side) / 2, size * 0.04, side, side * head.height() / head.width()), head)
        p.restore()
    p.setPen(QPen(QColor(54, 191, 255, 200), max(1.0, size / 48)))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(shape)
    p.end()
    return img


def build_icon(target: Path = ICON) -> Path:
    """Многоразмерный .ico (PNG внутри, Windows Vista и новее): чёткий и в 16, и в 256 пикселей."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    blobs = []
    for size in ICON_SIZES:
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        _icon_image(size).save(buf, "PNG")
        buf.close()
        blobs.append((size, bytes(data)))
    header = struct.pack("<HHH", 0, 1, len(blobs))
    offset = 6 + 16 * len(blobs)
    entries, payload = b"", b""
    for size, blob in blobs:
        dim = 0 if size >= 256 else size  # 0 означает 256
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(blob), offset + len(payload))
        payload += blob
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(header + entries + payload)
    return target


def _special_folder(name: str) -> Path:
    out = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", f"[Environment]::GetFolderPath('{name}')"],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return Path(out.stdout.strip())


def create_shortcut(link: Path) -> None:
    env = dict(os.environ)
    env.update({
        "SIRIUS_LNK": str(link),
        "SIRIUS_TARGET": str(PYTHONW),
        "SIRIUS_ARGS": f'"{ENTRY}"',
        "SIRIUS_WORKDIR": str(PROJECT),
        "SIRIUS_ICON": f"{ICON},0",
    })
    # пути передаются через переменные окружения: пробелы и скобки в путях не ломают команду
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _CREATE_LNK],
                   env=env, check=True, timeout=60, capture_output=True)


def main(argv: list[str]) -> int:
    if sys.platform != "win32":
        print("Ярлыки создаются только в Windows")
        return 1
    if not PYTHONW.exists():
        print(f"Не найден {PYTHONW}. Сначала создайте окружение: python -m venv .venv и pip install -r requirements.txt")
        return 1
    from PySide6.QtGui import QGuiApplication

    app = QGuiApplication.instance() or QGuiApplication(argv[:1])  # noqa: F841 - нужен для QPainter
    if not ICON.exists() or "--rebuild-icon" in argv:
        print("Иконка:", build_icon())
    targets = [_special_folder("Desktop") / "SIRIUS.lnk", PROJECT / "SIRIUS.lnk"]
    if "--start-menu" in argv:
        targets.append(_special_folder("Programs") / "SIRIUS.lnk")
    for link in targets:
        create_shortcut(link)
        print("Ярлык:", link)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
