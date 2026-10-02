"""
make_wizard_images.py
---------------------
Kurulum sihirbazinin sag ustundeki kucuk gorsel (WizardSmallImageFile):
assets/revora.png'den, beyaz zeminli 24 bit BMP olarak birkac boyutta
(ekran olcegine gore Inno Setup en uygununu secer). build_exe.bat her
paketlemede calistirir; logo degisince kendiliginden guncellenir.
"""
import os
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtWidgets import QApplication

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "revora.png")
OUT_DIR = os.path.join(HERE, "installer")
SIZES = (55, 69, 83, 110, 138)        # %100 .. %250 olcek


def main():
    app = QApplication.instance() or QApplication(sys.argv)
    src = QImage(SRC)
    if src.isNull():
        raise SystemExit(f"logo okunamadi: {SRC}")
    os.makedirs(OUT_DIR, exist_ok=True)
    for n in SIZES:
        img = QImage(n, n, QImage.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        m = round(n * 0.06)
        logo = src.scaled(n - 2 * m, n - 2 * m, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p.drawImage((n - logo.width()) // 2, (n - logo.height()) // 2, logo)
        p.end()
        img.convertToFormat(QImage.Format_RGB888).save(os.path.join(OUT_DIR, f"wizard_small_{n}.bmp"), "BMP")
    print("sihirbaz gorselleri:", ", ".join(f"{n}px" for n in SIZES))


if __name__ == "__main__":
    main()
