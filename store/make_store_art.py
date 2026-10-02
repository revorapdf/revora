"""
make_store_art.py
-----------------
Microsoft Store gorselleri (assets/revora.png ve ekran goruntulerinden):
  store/art/poster_9x16_<dil>.png   1440x2160  9:16 Poster art (Windows 11'de ana logo)
  store/art/boxart_1x1.png          2160x2160  1:1 Box art (iki dilde ayni)
  store/art/hero_16x9_<dil>.png     3840x2160  16:9 Super hero art (urun ADI OLMAMALI)

    python store/make_store_art.py      (once make_screenshots.py calismis olmali)
"""
import os
import sys

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QImage, QPainter, QColor, QFont, QLinearGradient, QRadialGradient,
                           QPainterPath)
from PySide6.QtWidgets import QApplication

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGO = os.path.join(ROOT, "assets", "revora.png")
SHOTS = os.path.join(ROOT, "store", "screenshots")
TAGLINE = {"en": "Edit the real text of your PDFs", "tr": "PDF'teki yazıyı gerçekten düzenleyin"}
OUT = os.path.join(ROOT, "store", "art")
BG_TOP, BG_BOTTOM = QColor("#1d2130"), QColor("#0e1017")
WHITE, RED, MUTED = QColor("#f5f7fb"), QColor("#f0383c"), QColor("#9aa3b5")


def canvas(w, h):
    img = QImage(w, h, QImage.Format_ARGB32)
    p = QPainter(img)
    p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform | QPainter.TextAntialiasing)
    g = QLinearGradient(0, 0, 0, h)
    g.setColorAt(0, BG_TOP)
    g.setColorAt(1, BG_BOTTOM)
    p.fillRect(0, 0, w, h, g)
    glow = QRadialGradient(QPointF(w * 0.5, h * 0.38), max(w, h) * 0.55)
    c = QColor(RED)
    c.setAlpha(38)
    glow.setColorAt(0, c)
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    p.fillRect(0, 0, w, h, glow)
    return img, p


def draw_logo(p, logo, cx, cy, size):
    s = logo.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    p.drawImage(int(cx - s.width() / 2), int(cy - s.height() / 2), s)


def text(p, s, rect, px, weight, color, align=Qt.AlignHCenter | Qt.AlignTop):
    f = QFont("Segoe UI", 10)
    f.setPixelSize(px)
    f.setWeight(weight)
    p.setFont(f)
    p.setPen(color)
    p.drawText(rect, align, s)


def main():
    QApplication.instance() or QApplication(sys.argv)
    os.makedirs(OUT, exist_ok=True)
    logo = QImage(LOGO)

    # 9:16 poster: logo + ad + kisa slogan (dil basina)
    for lang, tag in TAGLINE.items():
        w, h = 1440, 2160
        img, p = canvas(w, h)
        draw_logo(p, logo, w / 2, h * 0.40, 760)
        text(p, "Revora PDF", QRectF(0, h * 0.62, w, 200), 150, QFont.DemiBold, WHITE)
        text(p, tag, QRectF(0, h * 0.62 + 210, w, 100), 64, QFont.Normal, MUTED)
        p.end()
        img.save(os.path.join(OUT, f"poster_9x16_{lang}.png"))

    # 1:1 box art: logo + ad
    w = h = 2160
    img, p = canvas(w, h)
    draw_logo(p, logo, w / 2, h * 0.42, 1100)
    text(p, "Revora PDF", QRectF(0, h * 0.73, w, 260), 190, QFont.DemiBold, WHITE)
    p.end()
    img.save(os.path.join(OUT, "boxart_1x1.png"))

    # 16:9 hero: urun adi YOK (Store kurali); ekran goruntusu yuvarlak koseli cercevede
    for lang in TAGLINE:
        w, h = 3840, 2160
        img, p = canvas(w, h)
        shot = QImage(os.path.join(SHOTS, lang, "02_markup.png"))
        if not shot.isNull():
            sw = int(w * 0.80)
            s = shot.scaledToWidth(sw, Qt.SmoothTransformation)
            x, y = (w - s.width()) / 2, h * 0.11
            r = QRectF(x, y, s.width(), s.height())
            shadow = QColor(0, 0, 0, 110)
            for k in range(1, 40, 3):                      # yumusak golge
                sh = QColor(shadow)
                sh.setAlpha(max(0, 110 - k * 3))
                path = QPainterPath()
                path.addRoundedRect(r.adjusted(-k, -k + 30, k, k + 30), 40 + k, 40 + k)
                p.fillPath(path, sh)
            clip = QPainterPath()
            clip.addRoundedRect(r, 36, 36)
            p.setClipPath(clip)
            p.drawImage(r.topLeft(), s)
            p.setClipping(False)
        p.end()
        img.save(os.path.join(OUT, f"hero_16x9_{lang}.png"))
    print("hazir:", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
