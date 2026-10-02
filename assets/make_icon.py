"""
make_icon.py
------------
assets/revora.png (kare, seffaf arka planli logo) dosyasindan Windows icin
cok boyutlu assets/revora.ico uretir. build_exe.bat her paketlemede bunu
calistirir; logoyu degistirmek icin sadece revora.png'yi degistirmek yeter.

Pillow gerektirmez (PySide6/Qt ile olcekler). ICO icindeki her boyut PNG
olarak saklanir (Windows Vista ve sonrasi destekler).
"""
import os
import struct

from PySide6.QtCore import Qt, QBuffer, QByteArray, QIODevice
from PySide6.QtGui import QImage, QPainter

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "revora.png")
OUT = os.path.join(HERE, "revora.ico")
SIZES = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]
PAD = 0.05  # her kenarda %5 bosluk: gorev cubugunda diger ikonlardan buyuk durmasin


def padded(src):
    n = max(src.width(), src.height())
    canvas = QImage(n, n, QImage.Format_ARGB32_Premultiplied)
    canvas.fill(Qt.transparent)
    inner = round(n * (1 - 2 * PAD))
    logo = src.scaled(inner, inner, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawImage((n - logo.width()) // 2, (n - logo.height()) // 2, logo)
    p.end()
    return canvas


def shrink(img, size):
    """Yarilayarak kucult: tek adimda 1024 -> 16 kucultmek kenarlari tirtikli yapar."""
    img = img.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    while img.width() // 2 >= size:
        img = img.scaled(img.width() // 2, img.height() // 2,
                         Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return img.scaled(size, size, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)


def png_bytes(img):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    buf.close()
    return bytes(ba)


def build_icon(src_path=SRC, out_path=OUT, sizes=SIZES):
    src = QImage(src_path)
    if src.isNull():
        raise SystemExit(f"Logo okunamadi: {src_path}")
    base = padded(src)
    images = [(s, png_bytes(shrink(base, s))) for s in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries, data = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size   # ICO'da 256 "0" olarak yazilir
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(out_path, "wb") as f:
        f.write(header + entries + data)
    return out_path


if __name__ == "__main__":
    print("Ikon olusturuldu:", build_icon())
