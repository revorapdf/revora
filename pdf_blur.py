"""
pdf_blur.py
-----------
Guvenli bulaniklastirma: secilen alandaki yazi/cizim/resim PDF'ten GERCEKTEN
silinir (MuPDF redaction), yerine o alanin bulaniklastirilmis / pikselli
goruntusu konur (ya da duz siyah kutu). Sadece ustune bulanik resim koymak
yetmez: alttaki metin secilip kopyalanabilir, resim kaldirilip okunabilirdi.

Goruntu isleme Qt ile yapilir (ek kutuphane gerekmez); ayni fonksiyonlar
arayuzdeki canli onizlemede de kullanilir -> onizleme = sonuc.
"""
import math

# import sirasi kurali: PySide6, fitz'ten once
from PySide6.QtCore import Qt, QRectF, QBuffer, QIODevice, QPointF
from PySide6.QtGui import QImage, QPainter, QPixmap, QColor, QPainterPath, QPolygonF
from PySide6.QtWidgets import QGraphicsScene, QGraphicsPixmapItem, QGraphicsBlurEffect
import fitz
from i18n import _t

MODES = (("blur", _t("Bulanık")), ("pixel", _t("Pikselli")), ("solid", _t("Siyah kutu")))
SCALE = 2.0            # PDF'e konan goruntunun cozunurlugu (2 = 144 dpi)
LEVELS = (1, 10)       # guc ayari araligi
SEAM = 0.8             # pt: goruntu alanin bu kadar disina tasar (bkz. apply)


def amount_pt(mode, level):
    """Guc seviyesinin PDF birimi (pt) karsiligi: bulanikta yaricap, pikselde kare boyu."""
    level = max(LEVELS[0], min(LEVELS[1], int(level)))
    return level * 2.5 if mode == "blur" else 1.5 + level * 1.5


def pad_pt(mode, level):
    """Kenarlarda beyaza solma olmasin diye alanin biraz disi da islenir."""
    return amount_pt(mode, level) * 2.5 if mode == "blur" else 0.0


def render(page, rect, scale, pad=0.0):
    """Sayfanin (isaretlemeler haric) alan goruntusu; pad kadar tasmali."""
    clip = fitz.Rect(rect.x0 - pad, rect.y0 - pad, rect.x1 + pad, rect.y1 + pad)
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, annots=False, alpha=False)
    return QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()


def _gauss(img, radius):
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(QPixmap.fromImage(img))
    eff = QGraphicsBlurEffect()
    eff.setBlurRadius(radius)
    eff.setBlurHints(QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = QImage(img.size(), QImage.Format_RGB32)
    out.fill(QColor(255, 255, 255))
    p = QPainter(out)
    src = QRectF(0, 0, img.width(), img.height())
    scene.render(p, src, src)
    p.end()
    scene.removeItem(item)
    return out


def process(img, mode, level, scale, pad_px=0):
    """img'yi isle; pad_px kadar kenar payi varsa sonucta kirpilir."""
    w, h = img.width() - 2 * pad_px, img.height() - 2 * pad_px
    if w < 1 or h < 1:
        return img
    a = amount_pt(mode, level) * scale                  # piksel
    if mode == "solid":
        out = QImage(w, h, QImage.Format_RGB32)
        out.fill(QColor(0, 0, 0))
        return out
    if mode == "pixel":
        core = img.copy(pad_px, pad_px, w, h)
        bw, bh = max(1, math.ceil(w / a)), max(1, math.ceil(h / a))
        small = core.scaled(bw, bh, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.FastTransformation)
    # bulanik: iki gecis (daha yumusak, gercek Gauss'a yakin)
    out = _gauss(_gauss(img, a), a * 0.6)
    return out.copy(pad_px, pad_px, w, h)


def poly(rect, angle):
    """Donmus alanin koseleri (sol-ust, sag-ust, sag-alt, sol-alt); aci ekranda saat yonu."""
    r = fitz.Rect(rect).normalize()
    c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
    a = math.radians(angle or 0.0)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for q in (r.tl, r.tr, r.br, r.bl):
        dx, dy = q.x - c.x, q.y - c.y
        out.append(fitz.Point(c.x + dx * ca - dy * sa, c.y + dx * sa + dy * ca))
    return out


def bounds(pts):
    return fitz.Rect(min(q.x for q in pts), min(q.y for q in pts),
                     max(q.x for q in pts), max(q.y for q in pts))


def strips(pts, step=1.5):
    """Bukey dortgeni (pts) kaplayan ince yatay dikdortgenler (yukseklik = step pt)."""
    bb = bounds(pts)
    out = []
    y = bb.y0
    while y < bb.y1 - 1e-6:
        y2 = min(y + step, bb.y1)
        xs = []
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            if abs(a.y - b.y) < 1e-9:
                if y - 1e-9 <= a.y <= y2 + 1e-9:
                    xs += [a.x, b.x]
                continue
            for yy in (y, y2):
                if min(a.y, b.y) - 1e-9 <= yy <= max(a.y, b.y) + 1e-9:
                    t = (yy - a.y) / (b.y - a.y)
                    xs.append(a.x + t * (b.x - a.x))
            # seridin icine dusen kose (tepe/dip noktasi)
            if y < a.y < y2:
                xs.append(a.x)
        if len(xs) >= 2:
            out.append(fitz.Rect(min(xs), y, max(xs), y2))
        y = y2
    return out


def _render_any(page, clip, scale):
    """clip sayfanin disina tasiyorsa da tam boyutlu goruntu (disi beyaz)."""
    inside = clip & page.rect
    W, H = max(1, round(clip.width * scale)), max(1, round(clip.height * scale))
    out = QImage(W, H, QImage.Format_RGB32)
    out.fill(QColor(255, 255, 255))
    if not inside.is_empty and inside.width > 0 and inside.height > 0:
        part = render(page, inside, scale)
        p = QPainter(out)
        p.drawImage(round((inside.x0 - clip.x0) * scale), round((inside.y0 - clip.y0) * scale), part)
        p.end()
    return out


def make_image(page, rect, mode, level, scale=SCALE, angle=0.0):
    """PDF'e konacak islenmis goruntu (PNG/JPEG baytlari). Duz kutuda None.
    angle verilirse goruntu donmus alanin sinir kutusunu kaplar ve alanin DISI
    saydamdir (egik dortgen seklinde maske)."""
    if mode == "solid":
        return None
    pad = pad_pt(mode, level)
    pad_px = round(pad * scale) if pad else 0
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    if not angle:
        img = render(page, rect, scale, pad)
        out = process(img, mode, level, scale, pad_px)
        # bulanik goruntu fotograf gibi: JPEG cok daha kucuk; piksellide keskin kenar -> PNG
        out.save(buf, "JPG" if mode == "blur" else "PNG", 88 if mode == "blur" else -1)
        return bytes(buf.data())
    pts = poly(rect, angle)
    b = bounds(pts)
    img = _render_any(page, fitz.Rect(b.x0 - pad, b.y0 - pad, b.x1 + pad, b.y1 + pad), scale)
    out = process(img, mode, level, scale, pad_px)
    masked = QImage(out.size(), QImage.Format_ARGB32_Premultiplied)
    masked.fill(Qt.transparent)
    sx, sy = out.width() / max(b.width, 1e-6), out.height() / max(b.height, 1e-6)
    path = QPainterPath()
    path.addPolygon(QPolygonF([QPointF((q.x - b.x0) * sx, (q.y - b.y0) * sy) for q in pts]))
    path.closeSubpath()
    p = QPainter(masked)
    p.setRenderHint(QPainter.Antialiasing)
    p.setClipPath(path)
    p.drawImage(0, 0, out)
    p.end()
    masked.save(buf, "PNG")                   # saydamlik icin PNG
    return bytes(buf.data())


def apply(doc, pno, rect, mode, level, angle=0.0, before_redact=None, after_redact=None):
    """Alani guvenli bicimde bulaniklastirir. rect: donmemis sayfa koordinatlari
    (uygulamanin kullandigi), angle: alanin donme acisi. Dondurur: uygulanan alan.
    before_redact(page) / after_redact(page): goruntu alindiktan sonra, silmeden
    once / sonra (ve goruntu konmadan once) cagrilir - motor, alana tasan dev
    filigran yazilarini silmeden korumak icin kullanir."""
    page = doc[pno]
    rot = page.rotation
    if rot:
        page.set_rotation(0)            # tum islemler donmemis koordinatlarda
    try:
        rect = fitz.Rect(rect).normalize()
        if not angle:
            rect = rect & page.rect
        if rect.is_empty or rect.width < 1 or rect.height < 1:
            return None
        # goruntu biraz tasar: altta kismen temizlenen resim piksellerinin kenarda
        # biraktigi ince cizgiyi (dikis izi) orter
        cover = fitz.Rect(rect.x0 - SEAM, rect.y0 - SEAM, rect.x1 + SEAM, rect.y1 + SEAM)
        if not angle:
            cover = cover & page.rect
        data = make_image(page, cover, mode, level, angle=angle)   # ONCE goruntu (icerik silinmeden)
        if before_redact is not None:
            before_redact(page)
        if angle:
            # MuPDF redaksiyonu egik dortgeni (QuadPoints) yok sayip cevreleyen DUZ kutuyu
            # siliyor: egik alanin disindaki yazilar da gidiyordu. Egik alani ince
            # yatay seritlerle kapliyoruz -> sadece alanin icindekiler silinir.
            for strip in strips(poly(rect, angle)):
                page.add_redact_annot(strip, fill=False, cross_out=False)
        else:
            page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_PIXELS,
                              graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED,
                              text=fitz.PDF_REDACT_TEXT_REMOVE)
        if after_redact is not None:
            after_redact(page)
        if data:
            page.insert_image(bounds(poly(cover, angle)) if angle else cover,
                              stream=data, keep_proportion=False, overlay=True)
        else:                           # siyah kutu (donukse egik)
            sh = page.new_shape()
            pts = poly(rect, angle)
            sh.draw_polyline(pts + [pts[0]])
            sh.finish(color=None, fill=(0, 0, 0), closePath=True)
            sh.commit()
    finally:
        if rot:
            page.set_rotation(rot)
    return rect
