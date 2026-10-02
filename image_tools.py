"""
image_tools.py
--------------
Resim <-> PDF:
  - Sayfayi resim olarak kaydet (PNG / JPG, cozunurluk secilir; tek sayfa, secilenler ya da hepsi)
  - Sayfadaki fotograflari cikar (PDF'e gomulu resim KALITE KAYBI OLMADAN, kendi cozunurlugunde)
  - Sayfayi panoya resim olarak kopyala
  - Resimlerden PDF olustur (sirala, sayfa boyutu, kenar boslugu; telefon fotografinin
    yan donmesi EXIF'ten duzeltilir, JPEG yeniden sikistirilmaz)
  - Acik PDF'e resmi yeni sayfa olarak ekle (main.py, images_to_pdf ile)

Not: Qt kullanir; import sirasi kurali: PySide6, fitz'ten once.
"""
import math
import os
import re

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QComboBox,
                               QRadioButton, QButtonGroup, QLineEdit, QFileDialog, QMessageBox,
                               QApplication, QScrollArea, QStackedWidget, QWidget)
from PySide6.QtGui import QImage, QImageReader, QPixmap, QTransform
from PySide6.QtCore import Qt, QBuffer, QByteArray, QIODevice, QSize
import fitz
from i18n import _t
from merge_split import (_btn, _icon, _header, _muted_label, _separator, _fmt_size, _color,
                         DropZone, done_box, paint_merge_card, DANGER)
from reorder_view import ReorderView
from PySide6.QtGui import QPalette

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp")
IMAGE_PATTERN = "*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff *.webp"
DPI_CHOICES = ((96, _t("Ekran")), (150, _t("Normal")), (300, _t("Baskı")), (600, _t("Yüksek")))
PAGE_SIZES = {"a4": (595.28, 841.89), "letter": (612.0, 792.0)}
MIN_PHOTO_PX = 48          # bundan kucuk gomulu resimler (simge, cizgi) fotograf sayilmaz


def image_filter():
    return _t("Resimler ({p})", p=IMAGE_PATTERN)


def is_image(path):
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def image_paths(mime):
    return [u.toLocalFile() for u in mime.urls() if is_image(u.toLocalFile())]


# ---------------------------------------------------------------- resim -> PDF
# Qt'nin EXIF yon bilgisi -> resmi duz gostermek icin SAAT YONUNDE kac derece
_EXIF_ROT = {0: 0, 3: 180, 4: 90, 7: 270}


def _image_stream(path):
    """(veri, en, boy, saat_yonu_donme). JPEG / PNG oldugu gibi gomulur (yeniden
    sikistirma yok); EXIF donmesi PDF'te yerlestirirken uygulanir. Diger bicimler ve
    aynali EXIF Qt ile okunup PNG (kayipsiz) olarak gomulur."""
    r = QImageReader(path)
    size = r.size()
    rot = _EXIF_ROT.get(int(r.transformation().value if hasattr(r.transformation(), "value")
                            else r.transformation()))
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png") and rot is not None and size.isValid():
        with open(path, "rb") as f:
            return f.read(), size.width(), size.height(), rot
    r = QImageReader(path)
    r.setAutoTransform(True)
    img = r.read()
    if img.isNull():
        raise ValueError(r.errorString() or _t("resim okunamadı"))
    return _encode(img, "PNG"), img.width(), img.height(), 0


def _encode(img, fmt, quality=-1):
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, fmt, quality)
    buf.close()
    return bytes(ba)


def images_to_pdf(paths, size="a4", margin_mm=0.0):
    """Resimlerden PDF -> (fitz belgesi, atlananlar[(ad, neden)]).
    size: 'a4' / 'letter' (resme gore dikey/yatay), 'image' (resmin kendi oraninda,
    uzun kenar A4 kadar), ya da (en, boy) pt (acik belgeye eklerken komsu sayfa boyutu)."""
    doc = fitz.open()
    skipped = []
    m = max(0.0, float(margin_mm)) * 72 / 25.4
    for path in paths:
        try:
            data, w, h, rot = _image_stream(path)
        except Exception as e:
            skipped.append((os.path.basename(path), str(e)))
            continue
        dw, dh = (h, w) if rot in (90, 270) else (w, h)      # dogru yondeki en/boy
        if size == "image":
            long_side = PAGE_SIZES["a4"][1]
            if dw >= dh:
                pw, ph = long_side, long_side * dh / dw
            else:
                pw, ph = long_side * dw / dh, long_side
            pw, ph = pw + 2 * m, ph + 2 * m
        else:
            pw, ph = PAGE_SIZES.get(size, size) if isinstance(size, str) else size
            if (dw > dh) != (pw > ph):                       # yatay resim -> yatay sayfa
                pw, ph = ph, pw
        page = doc.new_page(width=pw, height=ph)
        box = fitz.Rect(m, m, pw - m, ph - m)
        s = min(box.width / dw, box.height / dh)
        r = fitz.Rect(0, 0, dw * s, dh * s)
        r = r + (box.x0 + (box.width - r.width) / 2, box.y0 + (box.height - r.height) / 2) * 2
        try:
            # PyMuPDF'te rotate saat yonunun TERSI
            page.insert_image(r, stream=data, rotate=(360 - rot) % 360)
        except Exception as e:
            doc.delete_page(len(doc) - 1)
            skipped.append((os.path.basename(path), str(e)))
    return doc, skipped


# ---------------------------------------------------------------- PDF -> resim
def page_image_bytes(doc, pno, dpi, fmt="png", quality=92):
    """Sayfanin goruntusu (isaretlemeler dahil, ekranda nasil gorunuyorsa)."""
    pix = doc[pno].get_pixmap(dpi=int(dpi), alpha=False)
    if fmt == "jpg":
        return pix.tobytes("jpg", jpg_quality=quality)
    return pix.tobytes("png")


def page_qimage(doc, pno, dpi=150):
    pix = doc[pno].get_pixmap(dpi=int(dpi), alpha=False)
    return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()


def page_pixel_size(doc, pno, dpi):
    r = doc[pno].rect
    return round(r.width * dpi / 72), round(r.height * dpi / 72)


def parse_pages(text, count):
    """'1-3, 5' -> [0, 1, 2, 4] (gecersiz/aralik disi olanlar atlanir, sira korunur)."""
    out = []
    for part in re.split(r"[,;\s]+", text or ""):
        if not part:
            continue
        m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", part)
        if m:
            a, b = int(m.group(1)), int(m.group(2))
            rng = range(a, b + 1) if a <= b else range(a, b - 1, -1)
        elif part.isdigit():
            rng = [int(part)]
        else:
            continue
        for n in rng:
            if 1 <= n <= count and n - 1 not in out:
                out.append(n - 1)
    return out


def _placement_rotation(info, page_rotation):
    """Gomulu resmin sayfada gorundugu donme (saat yonu, 90'in kati)."""
    a, b = info["transform"][0], info["transform"][1]
    ang = math.degrees(math.atan2(b, a))
    return int(round((ang + page_rotation) / 90.0)) * 90 % 360


def page_photos(doc, pno):
    """Sayfadaki fotograflar (gomulu resimler; kucuk simgeler haric)."""
    page = doc[pno]
    out, seen = [], set()
    for info in page.get_image_info(xrefs=True):
        x = info.get("xref") or 0
        if not x or x in seen:
            continue
        seen.add(x)
        if info["width"] < MIN_PHOTO_PX or info["height"] < MIN_PHOTO_PX:
            continue
        out.append({"xref": x, "w": info["width"], "h": info["height"], "page": pno,
                    "rot": _placement_rotation(info, page.rotation)})
    return out


def extract_photo(doc, item):
    """Gomulu resmi KENDI cozunurlugunde -> (veri, uzanti). JPEG / PNG ve donmemisse
    hic dokunmadan (bire bir ayni dosya); saydamlik maskesi, CMYK ya da sayfada
    donuk yerlesim varsa duzeltilip PNG (JPEG kaynakta %95 kaliteli JPG) yazilir."""
    x = item["xref"]
    base = doc.extract_image(x) or {}
    ext = (base.get("ext") or "").lower()
    rot = item.get("rot", 0)
    smask = base.get("smask") or 0
    if base.get("image") and ext in ("jpeg", "jpg", "png") and not smask and not rot:
        return base["image"], "jpg" if ext in ("jpeg", "jpg") else "png"
    pix = fitz.Pixmap(doc, x)
    if smask:
        try:
            pix = fitz.Pixmap(pix, fitz.Pixmap(doc, smask))
        except Exception:
            pass
    if pix.colorspace is not None and pix.colorspace.n not in (1, 3):
        pix = fitz.Pixmap(fitz.csRGB, pix)
    if not rot:
        return pix.tobytes("png"), "png"
    fmt = QImage.Format_RGBA8888 if pix.alpha else (QImage.Format_Grayscale8 if pix.n == 1
                                                        else QImage.Format_RGB888)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()
    img = img.transformed(QTransform().rotate(rot))
    if ext in ("jpeg", "jpg") and not pix.alpha:
        return _encode(img, "JPG", 95), "jpg"
    return _encode(img, "PNG"), "png"


def _unique(path):
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    k = 2
    while os.path.exists(f"{base} ({k}){ext}"):
        k += 1
    return f"{base} ({k}){ext}"


# ---------------------------------------------------------------- pencereler
def _setting(settings, key, default, typ=str):
    try:
        return settings.value(key, default, type=typ) if settings is not None else default
    except Exception:
        return default


def _set(settings, key, value):
    try:
        if settings is not None:
            settings.setValue(key, value)
    except Exception:
        pass


class ExportPagesDialog(QDialog):
    """Sayfayi / sayfalari resim olarak kaydet."""

    def __init__(self, parent, doc, current, base_path, settings=None):
        super().__init__(parent)
        self.doc, self.current, self.settings = doc, current, settings
        self.base = os.path.splitext(base_path)[0] if base_path else os.path.join(
            os.path.expanduser("~"), "Belge")
        self.setWindowTitle(_t("Sayfayı resim olarak kaydet"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(14)
        v.addWidget(_header(_t("Sayfayı resim olarak kaydet"),
                            _t("Sayfa, ekranda göründüğü gibi (işaretlemeler dahil) resme çevrilir.")))
        g = QGridLayout()
        g.setHorizontalSpacing(12)
        g.setVerticalSpacing(10)
        n = len(doc)
        self.r_cur = QRadioButton(_t("Bu sayfa ({n})", n=current + 1))
        self.r_all = QRadioButton(_t("Tüm sayfalar ({n})", n=n))
        self.r_sel = QRadioButton(_t("Seçilen sayfalar:"))
        self.ed_pages = QLineEdit()
        self.ed_pages.setPlaceholderText(_t("ör. 1-3, 5"))
        self.ed_pages.textEdited.connect(lambda _: self.r_sel.setChecked(True))
        bg = QButtonGroup(self)
        for b in (self.r_cur, self.r_all, self.r_sel):
            bg.addButton(b)
            b.toggled.connect(self._update)
        self.r_cur.setChecked(True)
        g.addWidget(QLabel(_t("Sayfalar")), 0, 0, Qt.AlignTop)
        pv = QVBoxLayout()
        pv.setSpacing(6)
        pv.addWidget(self.r_cur)
        pv.addWidget(self.r_all)
        row = QHBoxLayout()
        row.addWidget(self.r_sel)
        row.addWidget(self.ed_pages, 1)
        pv.addLayout(row)
        g.addLayout(pv, 0, 1)
        self.cb_fmt = QComboBox()
        self.cb_fmt.addItem(_t("PNG (kayıpsız, net yazı)"), "png")
        self.cb_fmt.addItem(_t("JPG (küçük dosya, fotoğraflar için)"), "jpg")
        self.cb_fmt.setCurrentIndex(max(self.cb_fmt.findData(_setting(settings, "export_fmt", "png")), 0))
        self.cb_dpi = QComboBox()
        for dpi, name in DPI_CHOICES:
            self.cb_dpi.addItem(_t("{name} ({dpi} dpi)", name=name, dpi=dpi), dpi)
        self.cb_dpi.setCurrentIndex(max(self.cb_dpi.findData(_setting(settings, "export_dpi", 150, int)), 0))
        self.cb_dpi.currentIndexChanged.connect(self._update)
        g.addWidget(QLabel(_t("Biçim")), 1, 0)
        g.addWidget(self.cb_fmt, 1, 1)
        g.addWidget(QLabel(_t("Çözünürlük")), 2, 0)
        g.addWidget(self.cb_dpi, 2, 1)
        v.addLayout(g)
        self.lbl_info = _muted_label()
        v.addWidget(self.lbl_info)
        v.addWidget(_separator())
        ft = QHBoxLayout()
        ft.addStretch()
        cancel = _btn(_t("Vazgeç"))
        cancel.clicked.connect(self.reject)
        self.btn_ok = _btn(_t("Kaydet"), _icon("fa5s.image", "#ffffff"), "primary")
        self.btn_ok.clicked.connect(self.do_export)
        ft.addWidget(cancel)
        ft.addWidget(self.btn_ok)
        v.addLayout(ft)
        self._update()

    def pages(self):
        if self.r_cur.isChecked():
            return [self.current]
        if self.r_all.isChecked():
            return list(range(len(self.doc)))
        return parse_pages(self.ed_pages.text(), len(self.doc))

    def _update(self, *_):
        if not hasattr(self, "btn_ok"):        # pencere kurulurken (secenekler henuz yok)
            return
        pages = self.pages()
        dpi = self.cb_dpi.currentData()
        if not pages:
            self.lbl_info.setText(_t("Sayfa numarası yazın (ör. 1-3, 5)."))
        else:
            w, h = page_pixel_size(self.doc, pages[0], dpi)
            self.lbl_info.setText(_t("{n} resim · {w} × {h} px", n=len(pages), w=w, h=h))
        self.btn_ok.setEnabled(bool(pages))

    def do_export(self):
        pages, fmt, dpi = self.pages(), self.cb_fmt.currentData(), self.cb_dpi.currentData()
        if not pages:
            return
        _set(self.settings, "export_fmt", fmt)
        _set(self.settings, "export_dpi", dpi)
        if len(pages) == 1:
            start = f"{self.base}_s{pages[0] + 1}.{fmt}"
            flt = "PNG (*.png)" if fmt == "png" else "JPG (*.jpg *.jpeg)"
            out, _ = QFileDialog.getSaveFileName(self, _t("Resmi kaydet"), start, flt)
            if not out:
                return
            targets = [(pages[0], out)]
            reveal = out
        else:
            folder = QFileDialog.getExistingDirectory(self, _t("Resimlerin kaydedileceği klasör"),
                                                      os.path.dirname(self.base))
            if not folder:
                return
            name = os.path.basename(self.base)
            targets = [(p, _unique(os.path.join(folder, f"{name}_s{p + 1:03d}.{fmt}"))) for p in pages]
            reveal = folder
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for p, out in targets:
                with open(out, "wb") as f:
                    f.write(page_image_bytes(self.doc, p, dpi, fmt))
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _t("Hata"), _t("Resim kaydedilemedi:\n{e}", e=e))
            return
        QApplication.restoreOverrideCursor()
        done_box(self, _t("Kaydedildi"), _t("{n} resim kaydedildi:\n{path}", n=len(targets), path=reveal),
                 reveal)
        self.accept()


class ExtractPhotosDialog(QDialog):
    """Sayfadaki fotograflari (PDF'e gomulu resimleri) kayipsiz cikar."""

    def __init__(self, parent, doc, current, base_path):
        super().__init__(parent)
        self.doc, self.current = doc, current
        self.base = os.path.splitext(base_path)[0] if base_path else os.path.join(
            os.path.expanduser("~"), "Belge")
        self.setWindowTitle(_t("Fotoğrafları çıkar"))
        self.setMinimumWidth(460)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(14)
        v.addWidget(_header(_t("Fotoğrafları çıkar"),
                            _t("PDF'in içindeki fotoğraflar kendi çözünürlüğünde, kalite kaybı "
                               "olmadan kaydedilir.")))
        self.r_cur = QRadioButton(_t("Bu sayfa ({n})", n=current + 1))
        self.r_all = QRadioButton(_t("Tüm sayfalar"))
        bg = QButtonGroup(self)
        for b in (self.r_cur, self.r_all):
            bg.addButton(b)
            b.toggled.connect(self._update)
            v.addWidget(b)
        self.lbl_info = _muted_label()
        self.lbl_info.setWordWrap(True)
        v.addWidget(self.lbl_info)
        v.addWidget(_separator())
        ft = QHBoxLayout()
        ft.addStretch()
        cancel = _btn(_t("Vazgeç"))
        cancel.clicked.connect(self.reject)
        self.btn_ok = _btn(_t("Kaydet"), _icon("fa5s.images", "#ffffff"), "primary")
        self.btn_ok.clicked.connect(self.do_extract)
        ft.addWidget(cancel)
        ft.addWidget(self.btn_ok)
        v.addLayout(ft)
        self._all = None
        self.r_cur.setChecked(True)
        if not page_photos(doc, current) and self._photos_all():
            self.r_all.setChecked(True)
        self._update()

    def _photos_all(self):
        if self._all is None:
            self._all, seen = [], set()
            for p in range(len(self.doc)):
                for it in page_photos(self.doc, p):
                    if it["xref"] not in seen:          # ayni resim birden cok sayfada: bir kez
                        seen.add(it["xref"])
                        self._all.append(it)
        return self._all

    def photos(self):
        return page_photos(self.doc, self.current) if self.r_cur.isChecked() else self._photos_all()

    def _update(self, *_):
        ph = self.photos()
        if not ph:
            self.lbl_info.setText(_t("Bu kapsamda fotoğraf bulunamadı. (Sayfanın tamamını resim olarak "
                                     "kaydetmek için \"Sayfayı resim olarak kaydet\"i kullanın.)"))
        elif len(ph) == 1:
            self.lbl_info.setText(_t("1 fotoğraf · {w} × {h} px", w=ph[0]["w"], h=ph[0]["h"]))
        else:
            big = max(ph, key=lambda it: it["w"] * it["h"])
            self.lbl_info.setText(_t("{n} fotoğraf · en büyüğü {w} × {h} px", n=len(ph), w=big["w"], h=big["h"]))
        self.btn_ok.setEnabled(bool(ph))

    def do_extract(self):
        ph = self.photos()
        if not ph:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            items = [(it, *extract_photo(self.doc, it)) for it in ph]
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _t("Hata"), _t("Fotoğraf çıkarılamadı:\n{e}", e=e))
            return
        QApplication.restoreOverrideCursor()
        name = os.path.basename(self.base)
        if len(items) == 1:
            it, data, ext = items[0]
            start = f"{self.base}_foto_s{it['page'] + 1}.{ext}"
            flt = "JPG (*.jpg *.jpeg)" if ext == "jpg" else "PNG (*.png)"
            out, _ = QFileDialog.getSaveFileName(self, _t("Fotoğrafı kaydet"), start, flt)
            if not out:
                return
            targets, reveal = [(out, data)], out
        else:
            folder = QFileDialog.getExistingDirectory(self, _t("Fotoğrafların kaydedileceği klasör"),
                                                      os.path.dirname(self.base))
            if not folder:
                return
            counts = {}
            targets = []
            for it, data, ext in items:
                k = counts[it["page"]] = counts.get(it["page"], 0) + 1
                targets.append((_unique(os.path.join(folder, f"{name}_foto_s{it['page'] + 1}_{k}.{ext}")), data))
            reveal = folder
        try:
            for out, data in targets:
                with open(out, "wb") as f:
                    f.write(data)
        except Exception as e:
            QMessageBox.critical(self, _t("Hata"), _t("Fotoğraf kaydedilemedi:\n{e}", e=e))
            return
        done_box(self, _t("Kaydedildi"), _t("{n} fotoğraf kaydedildi:\n{path}", n=len(targets), path=reveal),
                 reveal)
        self.accept()


def _image_thumb(path, height, dpr):
    r = QImageReader(path)
    r.setAutoTransform(True)
    size = r.size()
    if size.isValid() and size.height() > 0:
        # buyuk fotografi tamamen okumadan kucult (hizli)
        tr = r.transformation()
        rot90 = int(tr.value if hasattr(tr, "value") else tr) in (4, 5, 6, 7)
        sw, sh = (size.height(), size.width()) if rot90 else (size.width(), size.height())
        h = round(height * dpr)
        w = max(1, round(sw * h / sh))
        r.setScaledSize(QSize(h, w) if rot90 else QSize(w, h))
    img = r.read()
    if img.isNull():
        return None, None
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    tr = QImageReader(path).transformation()
    rot90 = int(tr.value if hasattr(tr, "value") else tr) in (4, 5, 6, 7)
    return pm, ((size.height(), size.width()) if rot90 else (size.width(), size.height()))   # gorunen yonde


class ImagesToPdfDialog(QDialog):
    """Resimlerden PDF: sirala, sayfa boyutu, kenar boslugu."""

    def __init__(self, parent=None, initial=None, settings=None):
        super().__init__(parent)
        self.settings = settings
        self.created = None             # olusturulan PDF'in yolu ("uygulamada ac" icin)
        self.setWindowTitle(_t("Resimlerden PDF oluştur"))
        self.resize(660, 600)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(14)
        v.addWidget(_header(_t("Resimlerden PDF oluştur"),
                            _t("Resimleri ekleyin ve sürükleyerek sıralayın; her resim bir sayfa olur. "
                               "Fotoğraflar yeniden sıkıştırılmaz, yan dönmüş telefon fotoğrafları "
                               "düzeltilir.")))
        self.stack = QStackedWidget()
        self.zone = DropZone(_t("Resimleri buraya sürükleyin"),
                             _t("ya da bilgisayarınızdan seçin (birden fazla seçebilirsiniz)"),
                             _t("Resim ekle"), exts=IMAGE_EXTS, icon="fa5s.file-image")
        self.zone.clicked.connect(self.add_files)
        self.zone.filesDropped.connect(self.add_paths)
        self.view = ReorderView(80, paint_merge_card, spacing=8, margin=3, accept_files=True)
        self.view.file_exts = IMAGE_EXTS
        self.view.filesDropped.connect(self.add_paths)
        self.view.deleteRequested.connect(self.remove_selected)
        self.view.currentChanged.connect(lambda _: self._update())
        self.view.moved.connect(lambda *_: self._update())
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sc.setStyleSheet("QScrollArea, QScrollArea > QWidget { background: transparent; border: none; }")
        sc.setWidget(self.view)
        self.stack.addWidget(self.zone)
        self.stack.addWidget(sc)
        v.addWidget(self.stack, 1)

        txt = _color(QPalette.WindowText)
        self.toolbar = QWidget()
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)
        self.btn_add = _btn(_t("Resim ekle"), _icon("fa5s.plus", txt))
        self.btn_up = _btn("", _icon("fa5s.arrow-up", txt), "toolbtn", _t("Yukarı taşı"))
        self.btn_down = _btn("", _icon("fa5s.arrow-down", txt), "toolbtn", _t("Aşağı taşı"))
        self.btn_remove = _btn("", _icon("fa5s.trash-alt", DANGER), "toolbtn", _t("Listeden kaldır (Delete)"))
        for b, fallback in ((self.btn_up, "▲"), (self.btn_down, "▼"), (self.btn_remove, _t("Kaldır"))):
            if b.icon().isNull():
                b.setText(fallback)
        self.btn_add.clicked.connect(self.add_files)
        self.btn_up.clicked.connect(lambda: self.move_item(-1))
        self.btn_down.clicked.connect(lambda: self.move_item(1))
        self.btn_remove.clicked.connect(self.remove_selected)
        tb.addWidget(self.btn_add)
        tb.addStretch()
        tb.addWidget(self.btn_up)
        tb.addWidget(self.btn_down)
        tb.addWidget(self.btn_remove)
        v.addWidget(self.toolbar)

        opts = QHBoxLayout()
        opts.setSpacing(8)
        self.cb_size = QComboBox()
        self.cb_size.addItem(_t("A4 (dikey/yatay resme göre)"), "a4")
        self.cb_size.addItem(_t("Letter (dikey/yatay resme göre)"), "letter")
        self.cb_size.addItem(_t("Resmin kendi oranında"), "image")
        self.cb_size.setCurrentIndex(max(self.cb_size.findData(_setting(settings, "img2pdf_size", "a4")), 0))
        self.cb_margin = QComboBox()
        for label, mm in ((_t("Kenar boşluğu yok"), 0), (_t("Dar kenar boşluğu"), 8), (_t("Normal kenar boşluğu"), 18)):
            self.cb_margin.addItem(label, mm)
        self.cb_margin.setCurrentIndex(max(self.cb_margin.findData(_setting(settings, "img2pdf_margin", 0, int)), 0))
        opts.addWidget(QLabel(_t("Sayfa")))
        opts.addWidget(self.cb_size, 1)
        opts.addWidget(self.cb_margin, 1)
        self.opts = QWidget()
        self.opts.setLayout(opts)
        opts.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self.opts)

        v.addWidget(_separator())
        ft = QHBoxLayout()
        self.lbl_sum = _muted_label()
        ft.addWidget(self.lbl_sum)
        ft.addStretch()
        cancel = _btn(_t("Vazgeç"))
        cancel.clicked.connect(self.reject)
        self.btn_make = _btn(_t("PDF oluştur"), _icon("fa5s.file-pdf", "#ffffff"), "primary")
        self.btn_make.clicked.connect(self.do_make)
        ft.addWidget(cancel)
        ft.addWidget(self.btn_make)
        v.addLayout(ft)
        if initial:
            self.add_paths(initial)
        self._update()

    def add_files(self):
        start = os.path.dirname(self.view.item(0)["path"]) if self.view.count() else \
            _setting(self.settings, "img2pdf_dir", "")
        paths, _ = QFileDialog.getOpenFileNames(self, _t("Resim ekle"), start, image_filter())
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        skipped = []
        dpr = self.devicePixelRatioF()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for path in paths:
                if not is_image(path):
                    continue
                thumb, size = _image_thumb(path, 58, dpr)
                if thumb is None:
                    skipped.append(os.path.basename(path))
                    continue
                self.view.add_item({"path": path, "name": os.path.basename(path), "thumb": thumb,
                                    "info": f"{size[0]} × {size[1]} px · {_fmt_size(os.path.getsize(path))}"})
        finally:
            QApplication.restoreOverrideCursor()
        self._update()
        if skipped:
            QMessageBox.warning(self, _t("Eklenemedi"), _t("Şu resimler okunamadı:\n\n") + "\n".join(skipped))

    def move_item(self, direction):
        row = self.view.current
        new_row = row + direction
        if row < 0 or not (0 <= new_row < self.view.count()):
            return
        self.view.move(row, new_row)
        self.view.ensure_visible(new_row)
        self._update()

    def remove_selected(self):
        if self.view.current >= 0:
            self.view.remove(self.view.current)
            self._update()

    def _update(self):
        n = self.view.count()
        self.stack.setCurrentIndex(1 if n else 0)
        self.toolbar.setVisible(n > 0)
        self.opts.setVisible(n > 0)
        row = self.view.current
        self.btn_up.setEnabled(row > 0)
        self.btn_down.setEnabled(0 <= row < n - 1)
        self.btn_remove.setEnabled(row >= 0)
        self.btn_make.setEnabled(n > 0)
        self.lbl_sum.setText(_t("{n} resim → {n} sayfa", n=n) if n else "")

    def do_make(self):
        n = self.view.count()
        if not n:
            return
        paths = [self.view.item(i)["path"] for i in range(n)]
        first = os.path.splitext(paths[0])[0]
        start = first + ".pdf" if n == 1 else os.path.join(os.path.dirname(paths[0]), "resimler.pdf")
        out, _ = QFileDialog.getSaveFileName(self, _t("PDF'i kaydet"), start, _t("PDF Dosyaları (*.pdf)"))
        if not out:
            return
        size, margin = self.cb_size.currentData(), self.cb_margin.currentData()
        _set(self.settings, "img2pdf_size", size)
        _set(self.settings, "img2pdf_margin", margin)
        _set(self.settings, "img2pdf_dir", os.path.dirname(paths[0]))
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            doc, skipped = images_to_pdf(paths, size, margin)
            if not len(doc):
                raise ValueError(_t("Hiçbir resim eklenemedi."))
            doc.save(out, garbage=3, deflate=True)
            pages = len(doc)
            doc.close()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _t("Hata"), _t("PDF oluşturulamadı:\n{e}", e=e))
            return
        QApplication.restoreOverrideCursor()
        text = _t("{n} sayfalık PDF oluşturuldu:\n{path}", n=pages, path=out)
        if skipped:
            text += "\n\n" + _t("Eklenemeyen resimler:\n") + "\n".join(f"{a} ({b})" for a, b in skipped)
        box = QMessageBox(self)
        box.setWindowTitle(_t("PDF oluşturuldu"))
        box.setIcon(QMessageBox.Information)
        box.setText(text)
        open_btn = box.addButton(_t("Uygulamada aç"), QMessageBox.AcceptRole)
        show = box.addButton(_t("Klasörde göster"), QMessageBox.ActionRole)
        box.addButton(_t("Tamam"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is show:
            from merge_split import reveal
            reveal(out)
        elif box.clickedButton() is open_btn:
            self.created = out
        self.accept()
