"""Подготовка изображения аватара LISA из референса пользователя.

Вырезает фигуру LISA из исходной картинки (1200x627, фигура в центре между панелями),
строит маску силуэта с мягкими краями и прозрачность по яркости: тёмный фон исчезает,
светящаяся голограмма остаётся. Результат — resources/images/lisa.png (RGBA).

Запуск (нужен numpy, он ставится вместе с piper-tts):
    python tools/prepare_lisa_avatar.py путь/к/референсу.jpg [resources/images/lisa.png]

Координаты силуэта заданы для референса 1200x627. Для другой картинки того же кадра
они масштабируются пропорционально её размеру.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPolygonF

REF_W, REF_H = 1200, 627
CROP = (420, 0, 360, 627)            # x, y, ширина, высота области с фигурой
HEAD = (601, 150, 92, 132)           # центр и радиусы овала головы с причёской
BODY = [                             # контур шеи, плеч, рук и подставки
    (560, 232), (642, 232), (648, 288), (702, 298), (740, 330), (754, 385), (750, 515),
    (772, 555), (772, 604), (428, 604), (428, 555), (452, 515), (448, 385), (462, 330),
    (500, 298), (554, 288),
]
FEATHER = 9.0                        # размытие краёв маски, пикселей исходника


def _to_array(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    ptr = image.constBits()
    arr = np.frombuffer(ptr, dtype=np.uint8, count=image.sizeInBytes())
    return arr.reshape(image.height(), image.bytesPerLine() // 4, 4)[:, : image.width()].copy()


def _gaussian_blur(mask: np.ndarray, sigma: float) -> np.ndarray:
    radius = int(sigma * 3)
    x = np.arange(-radius, radius + 1)
    kernel = np.exp(-(x ** 2) / (2 * sigma ** 2))
    kernel /= kernel.sum()
    padded = np.pad(mask, radius, mode="edge")
    rows = np.apply_along_axis(lambda r: np.convolve(r, kernel, mode="valid"), 1, padded)
    return np.apply_along_axis(lambda c: np.convolve(c, kernel, mode="valid"), 0, rows)


def _silhouette(width: int, height: int, sx: float, sy: float, x0: float) -> np.ndarray:
    mask = QImage(width, height, QImage.Format.Format_Grayscale8)
    mask.fill(0)
    p = QPainter(mask)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(255, 255, 255))
    path = QPainterPath()
    hx, hy, rx, ry = HEAD
    path.addEllipse(QPointF((hx - x0) * sx, hy * sy), rx * sx, ry * sy)
    path.addPolygon(QPolygonF([QPointF((x - x0) * sx, y * sy) for x, y in BODY]))
    path.setFillRule(Qt.FillRule.WindingFill)
    p.drawPath(path)
    p.end()
    arr = np.frombuffer(mask.constBits(), dtype=np.uint8, count=mask.sizeInBytes())
    arr = arr.reshape(height, mask.bytesPerLine())[:, :width].astype(np.float32) / 255.0
    return _gaussian_blur(arr, FEATHER * sx)


def prepare(source: Path, target: Path) -> None:
    image = QImage(str(source))
    if image.isNull():
        raise SystemExit(f"Не удалось открыть {source}")
    sx, sy = image.width() / REF_W, image.height() / REF_H
    cx, cy, cw, ch = CROP
    crop = image.copy(int(cx * sx), int(cy * sy), int(cw * sx), int(ch * sy))
    rgba = _to_array(crop).astype(np.float32)

    shape = _silhouette(crop.width(), crop.height(), sx, sy, cx)
    lum = 0.2126 * rgba[..., 0] + 0.7152 * rgba[..., 1] + 0.0722 * rgba[..., 2]
    glow = np.clip((lum - 22.0) / 95.0, 0.0, 1.0) ** 0.75
    # тёмные участки внутри силуэта остаются слегка видны: голограмма объёмная, а не вырезанная
    alpha = shape * (0.28 + 0.72 * glow)

    out = rgba.copy()
    out[..., 3] = np.clip(alpha * 255.0, 0, 255)
    out = out.astype(np.uint8)
    result = QImage(out.data, crop.width(), crop.height(), crop.width() * 4,
                    QImage.Format.Format_RGBA8888).copy()
    target.parent.mkdir(parents=True, exist_ok=True)
    if not result.save(str(target)):
        raise SystemExit(f"Не удалось сохранить {target}")
    print(f"Готово: {target} ({result.width()}x{result.height()})")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841 - нужен для QPainter
    project = Path(__file__).resolve().parent.parent
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else project / "resources" / "images" / "lisa.png"
    prepare(Path(sys.argv[1]), target)


if __name__ == "__main__":
    main()
