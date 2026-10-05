"""Surukleme sirasinda nesnenin KENDISI fareyle gider.

Gercek tasima hala birakinca yapilir (her fare hareketinde PDF'i yeniden yazip
sayfayi yeniden cizmek iyi bilgisayarda bile takilir). Ama surukleme basinda
BIR KEZ:
  - nesnesiz sayfa goruntusu cizilir (asil belgeye dokunmadan, kopyasinda),
  - nesnenin kendi goruntusu cikarilir;
surukleme boyunca sayfa nesnesiz gosterilir, nesnenin goruntusu fareyle kayar.
Boylece cift goruntu ya da mavi silüet yerine nesnenin kendisi tasinir.

Not: Qt'yi kullanir; fitz'den ONCE PySide6 yuklenmis olmali (main.py zaten oyle)."""
from collections import Counter

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPainter, QBitmap, QPixmap, QColor
import fitz

mupdf = fitz.mupdf

BLACK = QColor(0, 0, 0).rgb().to_bytes(4, "little")     # RGB32 siyah piksel


def _qimage(pix):
    fmt = QImage.Format_RGBA8888 if pix.alpha else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


def render_without(doc, pno, scale, remove, rect, isolate=False):
    """Sayfanin, remove(doc, page) ile nesnesi cikarilmis halini ayni olcekte,
    SADECE rect bolgesinde (goruntu pikseli, QRect) cizer -> (QImage, QRect, nesne).
    Bolge cizimi tam sayfa ciziminin ayni pikselleridir ama cok daha hizlidir.
    Islem belgenin bellekteki KOPYASINDA yapilir; nesne numaralari ayni kalir,
    boylece cizim/metin konumlari birebir gecerlidir. remove False donerse ya
    da hata olursa None.
    isolate: cikarilan YAZININ tek basina, saydam zeminli goruntusu de uretilir
    (nesne; olmazsa None) - bkz. text_only."""
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
            part = img.copy(r)
        else:
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
            part, r = _qimage(pix), QRect(pix.x, pix.y, pix.width, pix.height)
        return part, r, (text_only(doc[pno], page, scale, r) if isolate else None)
    except Exception:
        return None
    finally:
        if tmp is not None:
            tmp.close()


# ------------------------------------------------ yazinin KENDI goruntusu (saydam zeminli)
# Fark yontemi (diff_ghost) nesnenin pikselleri alttakiyle AYNI renkteyse o pikselleri
# kaybeder: siyah yazi baska bir siyah yazinin ustundeyse tasirken harfleri delik desik
# gorunuyordu. Burada cikarilan glifler bulunur ve yalnizca onlar yeniden cizilir:
#   1) nesnesiz sayfadaki gliflerin imzalari toplanir (tur, glif no, konum),
#   2) asil sayfa bir "suzgec aygit"tan gecirilir: imzasi nesnesiz sayfada OLMAYAN
#      glifler (= cikarilan yazi) saydam bir goruntuye cizilir; baska hicbir sey cizilmez.
# Kirpma yollari iletilmez (yazi kirpilmissa tamami gorunur) - sonucu composes() dener.
def _glyphs(box, text, ctm):
    """Yazi nesnesindeki, baslangic noktasi kutuda olan glifler: (parca, oge, x, y)."""
    x0, y0, x1, y1 = box
    # hizli eleme: yazi nesnesinin kutusu bolgeden uzaksa glifleri tek tek gezme (yogun
    # sayfada binlerce glif Python'da gezilirdi). Pay genis: glifin baslangic noktasi,
    # kendi kutusundan en cok bir harf boyu kadar uzakta olur.
    bb = mupdf.ll_fz_bound_text(text, None, ctm)
    pad = 256 + max(x1 - x0, y1 - y0)
    if bb.x1 < x0 - pad or bb.x0 > x1 + pad or bb.y1 < y0 - pad or bb.y0 > y1 + pad:
        return
    a, b, c, d, e, f = ctm.a, ctm.b, ctm.c, ctm.d, ctm.e, ctm.f
    span = text.head
    while span:
        sp = mupdf.FzTextSpan(span)
        for i in range(span.len):
            it = sp.items(i)
            x = it.x * a + it.y * c + e
            y = it.x * b + it.y * d + f
            if x0 <= x <= x1 and y0 <= y <= y1:
                yield span, it, round(x, 1), round(y, 1)
        span = span.next


class _GlyphSigs(mupdf.FzDevice2):
    def __init__(self, box, out):
        super().__init__()
        self.use_virtual_fill_text()
        self.use_virtual_stroke_text()
        self.box, self.out = box, out

    def fill_text(self, ctx, text, ctm, cs, color, alpha, cp):
        for _, it, x, y in _glyphs(self.box, text, ctm):
            self.out[(0, it.gid, x, y)] += 1

    def stroke_text(self, ctx, text, stroke, ctm, cs, color, alpha, cp):
        for _, it, x, y in _glyphs(self.box, text, ctm):
            self.out[(1, it.gid, x, y)] += 1


class _GlyphsOnly(mupdf.FzDevice2):
    def __init__(self, box, have, target):
        super().__init__()
        self.use_virtual_fill_text()
        self.use_virtual_stroke_text()
        self.box, self.have, self.target = box, have, target
        self.count = 0

    def _pick(self, kind, text, ctm):
        new = None
        for span, it, x, y in _glyphs(self.box, text, ctm):
            key = (kind, it.gid, x, y)
            if self.have.get(key, 0) > 0:          # nesnesiz sayfada da var: baska yazi
                self.have[key] -= 1
                continue
            if new is None:
                new = mupdf.ll_fz_new_text()
            t = span.trm
            mupdf.ll_fz_show_glyph(new, span.font, mupdf.ll_fz_make_matrix(t.a, t.b, t.c, t.d, it.x, it.y),
                                   it.gid, it.ucs, span.wmode, span.bidi_level, span.markup_dir, span.language)
            self.count += 1
        return new

    @staticmethod
    def _color(cs, color):
        return [mupdf.floats_getitem(color, i) for i in range(mupdf.ll_fz_colorspace_n(cs))]

    def fill_text(self, ctx, text, ctm, cs, color, alpha, cp):
        new = self._pick(0, text, ctm)
        if new is not None:
            try:
                mupdf.ll_fz_fill_text(self.target.m_internal, new, ctm, cs, self._color(cs, color), alpha, cp)
            finally:
                mupdf.ll_fz_drop_text(new)

    def stroke_text(self, ctx, text, stroke, ctm, cs, color, alpha, cp):
        new = self._pick(1, text, ctm)
        if new is not None:
            try:
                mupdf.ll_fz_stroke_text(self.target.m_internal, new, stroke, ctm, cs,
                                        self._color(cs, color), alpha, cp)
            finally:
                mupdf.ll_fz_drop_text(new)


def _run(page, dev, scale):
    mupdf.fz_run_page_contents(page.this, dev, mupdf.FzMatrix(scale, 0, 0, scale, 0, 0), mupdf.FzCookie())
    mupdf.fz_close_device(dev)


def text_only(page, page_without, scale, rect):
    """page'de olup page_without'ta olmayan yazi, rect bolgesinde (goruntu pikseli, QRect)
    tek basina ve saydam zeminde -> QImage (ARGB, onceden carpilmis) ya da None."""
    try:
        box = (rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height())
        have = Counter()
        _run(page_without, _GlyphSigs(box, have), scale)
        # Goruntu, sayfa cizimiyle AYNI yolla olusturulmali (PyMuPDF'in get_pixmap'i gibi,
        # bos FzSeparations ile). fitz.Pixmap(cs, irect, 1) ile olusturulunca cizim aygiti
        # renkleri baski (CMYK) yolundan ceviriyor: siyah (0,0,0) yerine (35,31,32) cikiyor,
        # tasirken yazi koyu gri gorunuyordu.
        raw = mupdf.fz_new_pixmap_with_bbox(mupdf.FzColorspace(mupdf.FzColorspace.Fixed_RGB),
                                            mupdf.FzIrect(*box), mupdf.FzSeparations(), 1)
        mupdf.fz_clear_pixmap(raw)                 # tum baytlar 0: saydam
        draw = mupdf.fz_new_draw_device(mupdf.FzMatrix(), raw)
        only = _GlyphsOnly(box, have, draw)
        _run(page, only, scale)
        mupdf.fz_close_device(draw)
        if not only.count:
            return None
        pix = fitz.Pixmap("raw", raw)
        return QImage(pix.samples, pix.width, pix.height, pix.stride,
                      QImage.Format_RGBA8888_Premultiplied).copy()
    except Exception:
        return None


_NEAR = bytes(0 if v <= 24 else 1 for v in range(256))


def composes(a, b, obj):
    """Saglama: nesnesiz goruntu (b) + nesne (obj) = asil goruntu (a) mi? Degilse nesne
    yanlis ayrilmis demektir (kirpilmis / baska seyin ALTINDA kalmis / karisimli yazi):
    o zaman eski fark yontemi kullanilir."""
    if obj is None or a.size() != b.size() or a.size() != obj.size() or a.isNull():
        return False
    out = b.convertToFormat(QImage.Format_RGB32)
    p = QPainter(out)
    p.drawImage(0, 0, obj)
    p.setCompositionMode(QPainter.CompositionMode_Difference)
    p.drawImage(0, 0, a.convertToFormat(QImage.Format_RGB32))
    p.end()
    raw = bytes(out.constBits())
    bad = sum(raw[c::4].translate(_NEAR).count(1) for c in range(3))    # B, G, R (A haric)
    return bad <= max(12, a.width() * a.height() // 400)


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
