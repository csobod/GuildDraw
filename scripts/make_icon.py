"""Render assets/icon.svg into a multi-resolution Windows .ico.

Build-time helper (no Pillow dependency — uses the Qt that GuildDraw already
ships with). Renders the SVG at the standard icon sizes and assembles a
PNG-compressed .ico (Vista+ reads PNG entries natively).

    .venv\\Scripts\\python scripts\\make_icon.py

Writes assets/icon.ico.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

SIZES = [256, 128, 64, 48, 32, 24, 16]


def render_png(renderer: QSvgRenderer, size: int) -> bytes:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def build_ico(pngs: list[tuple[int, bytes]]) -> bytes:
    # ICONDIR header: reserved=0, type=1 (icon), count
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = bytearray()
    image_data = bytearray()
    offset = 6 + 16 * len(pngs)  # past header + all dir entries
    for size, png in pngs:
        dim = 0 if size >= 256 else size  # 0 encodes 256
        entries += struct.pack(
            "<BBBBHHII",
            dim,            # width
            dim,            # height
            0,              # palette count
            0,              # reserved
            1,              # color planes
            32,             # bits per pixel
            len(png),       # bytes of image data
            offset,         # offset to image data
        )
        image_data += png
        offset += len(png)
    return bytes(header) + bytes(entries) + bytes(image_data)


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    svg_path = repo / "assets" / "icon.svg"
    ico_path = repo / "assets" / "icon.ico"
    if not svg_path.exists():
        print(f"missing {svg_path}", file=sys.stderr)
        return 1

    # A QGuiApplication is required before any QImage/QPainter work.
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        print(f"invalid SVG: {svg_path}", file=sys.stderr)
        return 1

    pngs = [(size, render_png(renderer, size)) for size in SIZES]
    ico_path.write_bytes(build_ico(pngs))
    print(f"wrote {ico_path} ({ico_path.stat().st_size} bytes, "
          f"{len(SIZES)} sizes)")
    del app  # noqa: F841 — keep the app alive until rendering is done
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
