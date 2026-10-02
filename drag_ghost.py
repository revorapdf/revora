"""Surukleme sirasinda nesnenin KENDISI fareyle gider.

Gercek tasima hala birakinca yapilir (her fare hareketinde PDF'i yeniden yazip
sayfayi yeniden cizmek iyi bilgisayarda bile takilir). Ama surukleme basinda
BIR KEZ:
  - nesnesiz sayfa goruntusu cizilir (asil belgeye dokunmadan, kopyasinda),
  - nesnenin kendi goruntusu cikarilir;
surukleme boyunca sayfa nesnesiz gosterilir, nesnenin goruntusu fareyle kayar.
Boylece cift goruntu ya da mavi silüet yerine nesnenin kendisi tasinir.

Not: Qt'yi kullanir; fitz'den ONCE PySide6 yuklenmis olmali (main.py zaten oyle)."""
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QBitmap, QPixmap, QColor
import fitz

BLACK = QColor(0, 0, 0).rgb().to_bytes(4, "little")     # RGB32 siyah piksel


def _qimage(pix):
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def render_without(doc, pno, scale, remove, rect):
    """Sayfanin, remove(doc, page) ile nesnesi cikarilmis halini ayni olcekte,
    SADECE rect bolgesinde (goruntu pikseli, QRect) cizer -> (QImage, QRect).
    Bolge cizimi tam sayfa ciziminin ayni pikselleridir ama cok daha hizlidir.
    Islem belgenin bellekteki KOPYASINDA yapilir; nesne numaralari ayni kalir,
    boylece cizim/metin konumlari birebir gecerlidir. remove False donerse ya
    da hata olursa None."""
    tmp = None
    try:
        tmp = fitz.open("pdf", doc.tobytes())
        page = tmp[pno]
        if remove(tmp, page) is False:
            return None
        clip = fitz.Rect(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height()) * (1 / scale)
        if _images_touch(page, clip):
            # resimler bolgesel cizimde FARKLI orneklenir (MuPDF resmin sadece gereken
            # kismini, baska olcekte cozer) -> resmin parcasi "degismis" sanilip nesneyle
            # birlikte tasiniyordu. Resim varsa tam sayfa cizilir (birebir ayni pikseller).
            img = _qimage(page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False))
            r = rect.intersected(img.rect())
            return img.copy(r), r
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        return _qimage(pix), QRect(pix.x, pix.y, pix.width, pix.height)
    except Exception:
        return None
    finally:
        if tmp is not None:
            tmp.close()


def _images_touch(page, clip):
    try:
        infos = page.get_image_info()
    except Exception:
        return True
    if not infos:
        return False
    if page.rotation:                      # (resim kutulari donmemis koordinatta)
        return True
    return any(fitz.Rect(i["bbox"]).intersects(clip) for i in infos)


def diff_ghost(a, b):
    """Ayni bolgenin nesneli (a) ve nesnesiz (b) goruntusunun FARKI = nesnenin
    kendi pikselleri: digerleri saydam. QPixmap ya da (fark yoksa) None."""
    if a.size() != b.size() or a.isNull():
        return None
    a = a.convertToFormat(QImage.Format_RGB32)
    b = b.convertToFormat(QImage.Format_RGB32)
    diff = QImage(a)
    p = QPainter(diff)
    p.setCompositionMode(QPainter.CompositionMode_Difference)
    p.drawImage(0, 0, b)
    p.end()
    # hic fark yoksa (nesne cikarilamadi) bos
    if not bytes(diff.constBits()).replace(BLACK, b""):
        return None
    # ayni kalan (fark = siyah) pikseller saydam (QBitmap: maskede "renkli" bit = saydam)
    mask = diff.createMaskFromColor(QColor(0, 0, 0).rgb(), Qt.MaskInColor)
    pm = QPixmap.fromImage(a)
    pm.setMask(QBitmap.fromImage(mask))
    return pm


def annot_ghost(page, xrefs, scale):
    """Isaretlemenin (bir ya da birkac annot) tek basina, saydam zeminli
    goruntusu. (QPixmap, goruntu pikseli bolgesi QRect) ya da None. Donuk sayfada
    None (annot goruntuleri donmemis koordinatta cizilir)."""
    if page.rotation:
        return None
    parts = []
    for annot in page.annots() or ():
        if annot.xref in xrefs:
            try:
                pix = annot.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
            except Exception:
                return None
            parts.append((pix.x, pix.y, _qimage(pix)))
    if not parts:
        return None
    x0 = min(x for x, _, _ in parts)
    y0 = min(y for _, y, _ in parts)
    x1 = max(x + im.width() for x, _, im in parts)
    y1 = max(y + im.height() for _, y, im in parts)
    out = QImage(x1 - x0, y1 - y0, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    for x, y, im in parts:
        p.drawImage(x - x0, y - y0, im)
    p.end()
    return QPixmap.fromImage(out), QRect(x0, y0, x1 - x0, y1 - y0)


def render_hidden(doc, page, xrefs, scale, rect):
    """Bolgeyi (QRect, goruntu pikseli) bu annot'lar gizliyken cizer -> QImage.
    Gizleme gecici (F=2), cizimden hemen sonra geri alinir."""
    saved = []
    try:
        for x in xrefs:
            saved.append((x, doc.xref_get_key(x, "F")))
            doc.xref_set_key(x, "F", "2")
        clip = fitz.Rect(rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height()) * (1 / scale)
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        if (pix.x, pix.y, pix.width, pix.height) != (rect.x(), rect.y(), rect.width(), rect.height()):
            return None
        return _qimage(pix)
    except Exception:
        return None
    finally:
        for x, (t, v) in saved:
            doc.xref_set_key(x, "F", v if t != "null" else "null")
