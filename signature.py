"""
signature.py
------------
Imza: bir kez fareyle cizilir (ya da resimden yuklenir), ayarlarda saklanir,
sonra Isaretle modunda istenen yere tek tikla konur.

Saklama (QSettings "signatures", JSON listesi, en yeni basta):
  {"type": "ink", "strokes": [[[x, y], ...]], "aspect": h/w}   genislik 1'e olceklenmis
  {"type": "image", "png": base64, "aspect": h/w}                arka plani saydam PNG
"""
import base64
import json

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QWidget, QLabel,
                               QFileDialog, QMessageBox)
from PySide6.QtGui import QPainter, QPen, QColor, QPainterPath, QImage, QPixmap
from PySide6.QtCore import Qt, QPointF, QRectF, QBuffer, QIODevice, Signal
from i18n import _t

MAX_SAVED = 8
KEY = "signatures"


def load(settings):
    try:
        data = json.loads(settings.value(KEY, "", type=str) or "[]")
    except (ValueError, TypeError):
        return []
    return [s for s in data if isinstance(s, dict) and s.get("type") in ("ink", "image")]


def store(settings, sigs):
    settings.setValue(KEY, json.dumps(sigs[:MAX_SAVED]))


def _smooth_path(pts):
    """Noktalardan gecen yumusak yol (Catmull-Rom; PDF'teki cizimle ayni egri)."""
    path = QPainterPath(pts[0])
    if len(pts) == 1:
        path.addEllipse(pts[0], 0.5, 0.5)
        return path
    n = len(pts)
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else p2
        path.cubicTo(p1 + (p2 - p0) / 6, p2 - (p3 - p1) / 6, p2)
    return path


def preview(sig, w, h, color=QColor(20, 30, 90)):
    """Kayitli imzanin kucuk resmi (liste / dugme icin)."""
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    asp = float(sig.get("aspect", 0.35)) or 0.35
    bw = min(w - 8, (h - 8) / asp)
    bh = bw * asp
    box = QRectF((w - bw) / 2, (h - bh) / 2, bw, bh)
    if sig["type"] == "image":
        img = QImage.fromData(base64.b64decode(sig["png"]))
        p.drawImage(box, img)
    else:
        pen = QPen(color, max(1.2, bw / 110))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        for st in sig["strokes"]:
            pts = [QPointF(box.x() + x * bw, box.y() + y * bw) for x, y in st]
            p.drawPath(_smooth_path(pts))
    p.end()
    return pm


def placed_strokes(sig, cx, cy, width):
    """Imzanin sayfada (cx, cy) merkezli, width genislikte kalem cizgileri."""
    h = width * float(sig.get("aspect", 0.35))
    x0, y0 = cx - width / 2, cy - h / 2
    return [[[x0 + x * width, y0 + y * width] for x, y in st] for st in sig["strokes"]]


class SignaturePad(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.strokes = []
        self._cur = None
        self.setMinimumSize(560, 220)
        self.setCursor(Qt.CrossCursor)

    def clear(self):
        self.strokes = []
        self.update()
        self.changed.emit()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._cur = [e.position()]
            self.strokes.append(self._cur)
            self.update()

    def mouseMoveEvent(self, e):
        if self._cur is not None:
            q = e.position()
            if (q - self._cur[-1]).manhattanLength() >= 1.5:
                self._cur.append(q)
                self.update()

    def mouseReleaseEvent(self, e):
        if self._cur is not None:
            self._cur = None
            self.changed.emit()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(255, 255, 255))
        p.setPen(QPen(QColor(200, 204, 212), 1, Qt.DashLine))
        y = int(self.height() * 0.72)
        p.drawLine(24, y, self.width() - 24, y)
        p.setPen(QColor(160, 165, 175))
        p.drawText(QRectF(24, y + 4, 300, 20), Qt.AlignLeft, _t("İmzanızı bu çizginin üstüne atın"))
        pen = QPen(QColor(20, 30, 90), 2.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        for st in self.strokes:
            p.drawPath(_smooth_path(st))
        p.end()

    def to_signature(self):
        """Normalize edilmis imza (genislik 1). Bos ise None."""
        pts = [q for st in self.strokes for q in st]
        if not pts:
            return None
        import pdf_markup
        x0, y0 = min(q.x() for q in pts), min(q.y() for q in pts)
        x1, y1 = max(q.x() for q in pts), max(q.y() for q in pts)
        w = max(x1 - x0, 1.0)
        out = []
        for st in self.strokes:
            simp = pdf_markup.simplify_stroke(pdf_markup.smooth_points([(q.x(), q.y()) for q in st], 5.0), 0.4)
            out.append([[round((q.x - x0) / w, 5), round((q.y - y0) / w, 5)] for q in simp])
        return {"type": "ink", "strokes": out, "aspect": max((y1 - y0) / w, 0.02)}


def image_signature(path):
    """Resimden imza: beyaza yakin pikseller saydam yapilir (taranmis imza)."""
    img = QImage(path)
    if img.isNull():
        return None
    if img.width() > 1000:              # once kucult: piksel dongusu buyuk fotografta yavas
        img = img.scaledToWidth(1000, Qt.SmoothTransformation)
    img = img.convertToFormat(QImage.Format_ARGB32)
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.lightness() > 225:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
    # bos kenarlari kirp
    xs, ys = [], []
    for y in range(0, img.height(), 2):
        for x in range(0, img.width(), 2):
            if img.pixelColor(x, y).alpha() > 0:
                xs.append(x)
                ys.append(y)
    if xs:
        img = img.copy(max(min(xs) - 4, 0), max(min(ys) - 4, 0),
                       min(max(xs) - min(xs) + 9, img.width()), min(max(ys) - min(ys) + 9, img.height()))
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return {"type": "image", "png": base64.b64encode(bytes(buf.data())).decode("ascii"),
            "aspect": img.height() / max(img.width(), 1)}


class SignatureDialog(QDialog):
    """Yeni imza: fareyle ciz ya da resimden yukle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_t("Yeni imza"))
        self.result_sig = None
        v = QVBoxLayout(self)
        info = QLabel(_t("Fareyle imzanızı atın. Kaydedilir; sonra İşaretle > İmza ile istediğiniz "
                      "yere tek tıkla koyarsınız. Rengi ve kalınlığı sonradan değiştirilebilir."))
        info.setWordWrap(True)
        v.addWidget(info)
        self.pad = SignaturePad()
        v.addWidget(self.pad, 1)
        row = QHBoxLayout()
        b_clear = QPushButton(_t("Temizle"))
        b_clear.clicked.connect(self.pad.clear)
        b_img = QPushButton(_t("Resimden yükle…"))
        b_img.setToolTip(_t("Kâğıda atılmış imzanın fotoğrafı/taraması: beyaz arka plan kaldırılır"))
        b_img.clicked.connect(self._from_image)
        row.addWidget(b_clear)
        row.addWidget(b_img)
        row.addStretch()
        b_cancel = QPushButton(_t("Vazgeç"))
        b_cancel.clicked.connect(self.reject)
        self.b_ok = QPushButton(_t("Kaydet ve kullan"))
        self.b_ok.setObjectName("primary")
        self.b_ok.setEnabled(False)
        self.b_ok.clicked.connect(self._accept)
        row.addWidget(b_cancel)
        row.addWidget(self.b_ok)
        v.addLayout(row)
        self.pad.changed.connect(lambda: self.b_ok.setEnabled(bool(self.pad.strokes)))

    def _accept(self):
        self.result_sig = self.pad.to_signature()
        if self.result_sig is not None:
            self.accept()

    def _from_image(self):
        path, _ = QFileDialog.getOpenFileName(self, _t("İmza resmi"), "",
                                              _t("Görüntüler (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff)"))
        if not path:
            return
        sig = image_signature(path)
        if sig is None:
            QMessageBox.warning(self, _t("Açılamadı"), _t("Bu resim dosyası açılamadı."))
            return
        self.result_sig = sig
        self.accept()
