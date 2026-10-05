"""
pdf_images.py
-------------
Sayfadaki RESIM nesneleri (logo, fotograf, grafik goruntusu): bul, tasi, boyutlandir, sil.

PDF'te resim, icerik akisinda `/Im3 Do` ile cizilir; yeri ve boyutu o andaki donusum
matrisidir (CTM: birim kareyi sayfadaki dortgene tasir). Burada:
  - page_images: sayfanin KENDI akisindaki resim cizimlerini (sirasi, adi, dortgeni) listeler.
    Form nesnesi icindeki resimler ve satir ici resimler (BI..EI) kapsam disi.
  - transform / delete: o `Do` cagrisi `q M cm /Im3 Do Q` ile sarilir (ya da kaldirilir).
    Baska hicbir seye dokunulmaz; resmin verisi degismez (kalite kaybi yok).

Koordinatlar pdf_paths / Span ile ayni: dondurulmemis sayfa, sol-ust kose (0, 0).
"""
import fitz
from pdf_content import _scan_cached, single_stream

UNIT = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))


class ImageItem:
    __slots__ = ("index", "name", "xref", "ctm", "quad", "bbox", "tok")

    def __init__(self, index, name, xref, ctm, quad, tok):
        self.index, self.name, self.xref, self.ctm, self.quad, self.tok = index, name, xref, ctm, quad, tok
        self.bbox = fitz.Rect(min(p.x for p in quad), min(p.y for p in quad),
                              max(p.x for p in quad), max(p.y for p in quad))

    def contains(self, point, base):
        """Nokta (sayfa koordinati) resmin dortgeninin icinde mi (egik / donuk resim dahil)."""
        try:
            u = fitz.Point(point) * ~fitz.Matrix(*tuple(base)) * ~fitz.Matrix(*self.ctm)
        except Exception:
            return self.bbox.contains(point)
        return -1e-6 <= u.x <= 1 + 1e-6 and -1e-6 <= u.y <= 1 + 1e-6


def _names(page):
    """Sayfanin kendi kaynaklarindaki resim adlari -> xref."""
    out = {}
    try:
        for im in page.get_images(full=True):
            if len(im) > 9 and im[9] == 0:           # (0: sayfanin kendisi cagiriyor)
                out[im[7]] = im[0]
    except Exception:
        pass
    return out


def page_images(doc, page, data=None):
    """Sayfadaki resim cizimleri, cizim sirasiyla (sonraki ustte). data verilirse o akis
    taranir (duzenleme icin: tok konumlari o akisa gore)."""
    if data is None:
        data = page.read_contents()
    base = page.transformation_matrix
    try:
        _, dos = _scan_cached(data, base)
    except Exception:
        return []
    names = _names(page)
    bm = fitz.Matrix(*tuple(base))
    out = []
    for do in dos:
        xref = names.get(do["name"])
        if xref is None:
            continue
        a, b, c, d, e, f = do["ctm"]
        quad = [fitz.Point(x * a + y * c + e, x * b + y * d + f) * bm for x, y in UNIT]
        out.append(ImageItem(len(out), do["name"], xref, tuple(do["ctm"]), quad, do["tok"]))
    return out


def _fmt(v):
    s = f"{v:.5f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _apply(doc, page, edits):
    """edits: {sira: fitz.Matrix (sayfa uzayinda uygulanacak donusum) | None (sil)}.
    Uygulanan resim sayisini dondurur."""
    xref = single_stream(doc, page)
    if xref is None:
        return 0
    data = doc.xref_stream(xref)
    items = [it for it in page_images(doc, page, data) if it.index in edits]
    base = fitz.Matrix(*tuple(page.transformation_matrix))
    done = 0
    for it in sorted(items, key=lambda it: it.tok[0], reverse=True):      # sondan basa: konumlar kaymasin
        s, e = it.tok
        k = e
        while k < len(data) and data[k:k + 1] in b" \t\r\n\x00\x0c":
            k += 1
        if data[k:k + 2] != b"Do":
            continue
        end = k + 2
        D = edits[it.index]
        if D is None:
            rep = b" "
        else:
            try:
                C = fitz.Matrix(*it.ctm)
                M = C * (base * D * ~base) * ~C     # cm, CTM'nin ONUNE gelir: M x CTM = CTM x D
            except Exception:
                continue
            rep = (b"q " + " ".join(_fmt(v) for v in tuple(M)).encode() + b" cm /"
                   + it.name.encode("latin-1") + b" Do Q")
        data = data[:s] + rep + data[end:]
        done += 1
    if done:
        doc.update_stream(xref, data)
    return done


def move(doc, page, indices, dx, dy):
    D = fitz.Matrix(1, 0, 0, 1, dx, dy)
    return _apply(doc, page, {i: D for i in indices})


def scale(doc, page, index, old, new):
    """Resmi old sinir kutusundan new sinir kutusuna tasi / boyutlandir."""
    old, new = fitz.Rect(old), fitz.Rect(new)
    if old.width < 1e-6 or old.height < 1e-6:
        return 0
    D = (fitz.Matrix(1, 0, 0, 1, -old.x0, -old.y0)
         * fitz.Matrix(new.width / old.width, 0, 0, new.height / old.height, 0, 0)
         * fitz.Matrix(1, 0, 0, 1, new.x0, new.y0))
    return _apply(doc, page, {index: D})


def delete(doc, page, indices):
    return _apply(doc, page, {i: None for i in indices})
