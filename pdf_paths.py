"""
pdf_paths.py
------------
Vektor cizimlerini (cizgi, dikdortgen, egri) icerik akisi seviyesinde
CERRAHI olarak duzenler.

Eski yontem cerceveyi "dolgulu seritler" sanip beyaz redaction ile siliyor
ve yeniden ciziyordu: tablo cizgileri (aslinda kontur/stroke) kayboluyor,
kalinlik/renk bozuluyor, ustune beyaz kutu boyaniyordu.

Buradaki yontem: her cizim yolunu (path) icerik akisinda kendi byte
araligiyla bulur ve koordinatlarini YERINDE yeniden yazar. Renk, kalinlik,
kesikli cizgi ve cizim sirasi (hangisi ustte) aynen korunur; baska hicbir
seye dokunulmaz.

Koordinat zinciri:  icerik uzayi --CTM--> PDF kullanici uzayi
                    --page.transformation_matrix--> sayfa (fitz, sol-ust) uzayi
"""
import math
import fitz
from pdf_content import _tokenize, _matmul, IDENT, single_stream
from curve_math import cubic_from_bend, bend_from_cubic, dash_array, dash_string, nearest_dash

_OPERANDS = {b"m": 2, b"l": 2, b"c": 6, b"v": 4, b"y": 4, b"re": 4, b"h": 0}
PAINT_OPS = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
STROKE_OPS = {"S", "s", "B", "B*", "b", "b*"}
FILL_OPS = {"f", "F", "f*", "B", "B*", "b", "b*"}


class PathItem:
    """Icerik akisindaki tek bir cizim yolu."""

    def __init__(self, index, start, end, paint_end, paint, segs, to_page):
        self.index = index          # sayfadaki sira no (duzenlemelerde sabit kalir)
        self.start = start          # insa operatorlerinin ilk byte'i
        self.end = end              # insa operatorlerinin son byte'i (boyamadan once)
        self.paint_end = paint_end  # boyama operatorunun son byte'i
        self.paint = paint          # "S", "f", "B" ...
        self.segs = segs            # [(op, [sayilar]), ...] icerik uzayinda
        self.to_page = to_page      # fitz.Matrix: icerik -> sayfa
        self.polys = _page_polys(segs, to_page)
        pts = [p for poly, _ in self.polys for p in poly]
        if pts:
            self.bbox = fitz.Rect(min(p.x for p in pts), min(p.y for p in pts),
                                  max(p.x for p in pts), max(p.y for p in pts))
        else:
            self.bbox = fitz.Rect()

    @property
    def stroked(self):
        return self.paint in STROKE_OPS

    @property
    def filled(self):
        return self.paint in FILL_OPS

    @property
    def kind(self):
        ops = [op for op, _ in self.segs]
        if ops in (["m", "l"], ["m", "l", "h"]):
            return "line"
        if ops == ["m", "c"] and self.stroked and not self.filled:
            return "curve"               # bukulmus cizgi (ortadaki tutamacla duzenlenir)
        if ops in (["re"], ["re", "h"]):
            return "rect"
        return "shape"

    def line_points(self):
        """kind == 'line' / 'curve' icin sayfa uzayinda iki uc nokta."""
        poly = self.polys[0][0]
        return poly[0], poly[-1]

    def bend_point(self):
        """Bukulmus cizginin orta noktasi (sayfa uzayi); duz cizgide None."""
        if self.kind != "curve":
            return None
        M = self.to_page
        (_, a), (_, c) = self.segs
        P = fitz.Point
        return bend_from_cubic(P(a[0], a[1]) * M, P(c[0], c[1]) * M, P(c[2], c[3]) * M,
                               P(c[4], c[5]) * M)


# ---------------------------------------------------------------- geometri
def _bezier(p0, p1, p2, p3, steps=16):
    out = []
    for i in range(1, steps + 1):
        t = i / steps
        u = 1 - t
        out.append(p0 * (u ** 3) + p1 * (3 * u * u * t) + p2 * (3 * u * t * t) + p3 * (t ** 3))
    return out


def _page_polys(segs, M):
    """Yolu sayfa uzayinda cizgi dizilerine (polyline) cevirir:
    [([Point, ...], kapali_mi), ...]. Egriler orneklenerek yaklasiklanir."""
    polys = []
    cur = []
    last = None      # icerik uzayindaki son nokta
    first = None
    P = fitz.Point
    for op, v in segs:
        if op == "m":
            if len(cur) > 1:
                polys.append((cur, False))
            last = first = P(v[0], v[1])
            cur = [last * M]
        elif op == "l":
            last = P(v[0], v[1])
            cur.append(last * M)
        elif op in ("c", "v", "y") and last is not None:
            if op == "c":
                c1, c2, p3 = P(v[0], v[1]), P(v[2], v[3]), P(v[4], v[5])
            elif op == "v":
                c1, c2, p3 = last, P(v[0], v[1]), P(v[2], v[3])
            else:
                c1, c2, p3 = P(v[0], v[1]), P(v[2], v[3]), P(v[2], v[3])
            cur.extend(q * M for q in _bezier(last, c1, c2, p3))
            last = p3
        elif op == "h":
            if len(cur) > 1:
                polys.append((cur + [cur[0]], True))
            cur = [first * M] if first is not None else []
            last = first
        elif op == "re":
            if len(cur) > 1:
                polys.append((cur, False))
            x, y, w, h = v
            corners = [P(x, y), P(x + w, y), P(x + w, y + h), P(x, y + h)]
            poly = [q * M for q in corners]
            polys.append((poly + [poly[0]], True))
            last = first = P(x, y)
            cur = []
    if len(cur) > 1:
        polys.append((cur, False))
    return polys


def _seg_dist(p, a, b):
    dx, dy = b.x - a.x, b.y - a.y
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))


def _inside(p, poly):
    inside = False
    n = len(poly)
    for i in range(n - 1):
        a, b = poly[i], poly[i + 1]
        if (a.y > p.y) != (b.y > p.y):
            x = a.x + (p.y - a.y) * (b.x - a.x) / (b.y - a.y)
            if p.x < x:
                inside = not inside
    return inside


def edge_distance(item, p):
    best = 1e9
    for poly, _ in item.polys:
        for i in range(len(poly) - 1):
            best = min(best, _seg_dist(p, poly[i], poly[i + 1]))
    return best


# ---------------------------------------------------------------- ayristirma
def parse_paths(doc, page):
    """Sayfanin icerik akisindaki tum boyanan yollari dondurur.
    Kirpma yollari (W n) ve Form XObject icindeki cizimler dahil edilmez."""
    xref = single_stream(doc, page)
    if xref is None:
        return []
    data = doc.xref_stream(xref)
    base = page.transformation_matrix
    ctm = IDENT
    stack = []
    nums, starts = [], []
    cur = None
    items = []
    for t in _tokenize(data):
        k = t["kind"]
        if k == "number":
            nums.append(float(t["val"]))
            starts.append(t["start"])
            continue
        if k != "op":
            nums, starts = [], []
            continue
        op = t["val"]
        if op in _OPERANDS:
            need = _OPERANDS[op]
            if len(nums) >= need:
                vals = nums[len(nums) - need:] if need else []
                if cur is None:
                    s = starts[len(starts) - need] if need else t["start"]
                    cur = {"start": s, "segs": [], "ctm": ctm, "clip": False}
                cur["segs"].append((op.decode(), vals))
                cur["end"] = t["end"]
        elif op in (b"W", b"W*"):
            if cur is not None:
                cur["clip"] = True
        elif op in PAINT_OPS or op == b"n":
            if cur is not None and not cur["clip"] and op != b"n":
                items.append(PathItem(len(items), cur["start"], cur["end"], t["end"],
                                      op.decode(), cur["segs"],
                                      fitz.Matrix(*cur["ctm"]) * base))
            cur = None
        elif op == b"q":
            stack.append(ctm)
        elif op == b"Q":
            if stack:
                ctm = stack.pop()
        elif op == b"cm" and len(nums) >= 6:
            ctm = _matmul(tuple(nums[-6:]), ctm)
        nums, starts = [], []
    return items


def hit_test(items, p, tol, page_rect):
    """Noktaya en yakin yolu secer. Once kenar (cizgi) isabetleri, en yakin
    olan (esitlikte en ustte cizilen) kazanir; yoksa dolgulu bir sekil
    icindeyse en kucuk alanli olan. Sayfayi kaplayan arka plan dolgulari
    ic tiklamada secilmez."""
    p = fitz.Point(p)
    best, best_d = None, tol
    for it in items:
        d = edge_distance(it, p)
        if d <= best_d:
            best, best_d = it, d
    if best is not None:
        return best
    page_area = abs(page_rect.width * page_rect.height)
    cand = None
    for it in items:
        if not it.filled or not it.bbox.contains(p):
            continue
        area = abs(it.bbox.width * it.bbox.height)
        if area >= 0.8 * page_area:
            continue
        if any(closed and _inside(p, poly) for poly, closed in it.polys):
            if cand is None or area <= abs(cand.bbox.width * cand.bbox.height):
                cand = it
    return cand


def items_in_rect(items, rect):
    """Tamamen dikdortgenin icinde kalan yollar (kutu ile secim)."""
    r = fitz.Rect(rect).normalize()
    return [it for it in items
            if r.x0 <= it.bbox.x0 and it.bbox.x1 <= r.x1
            and r.y0 <= it.bbox.y0 and it.bbox.y1 <= r.y1]


# ---------------------------------------------------------------- yazma
def _fmt(v):
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def _emit(segs):
    parts = []
    for op, vals in segs:
        parts.append(" ".join([_fmt(x) for x in vals] + [op]))
    return " ".join(parts).encode()


def _xform_segs(segs, T):
    """Icerik uzayindaki yolu T matrisiyle donusturur. 're' dikdortgeni
    eksen-hizali kalirsa 're' olarak kalir, yoksa dort kenarli yola cevrilir."""
    P = fitz.Point
    axis = abs(T.b) < 1e-9 and abs(T.c) < 1e-9
    out = []
    for op, v in segs:
        if op == "re":
            x, y, w, h = v
            if axis:
                q = P(x, y) * T
                out.append(("re", [q.x, q.y, w * T.a, h * T.d]))
            else:
                cs = [P(x, y) * T, P(x + w, y) * T, P(x + w, y + h) * T, P(x, y + h) * T]
                out.append(("m", [cs[0].x, cs[0].y]))
                out.extend(("l", [c.x, c.y]) for c in cs[1:])
                out.append(("h", []))
        else:
            pts = [P(v[i], v[i + 1]) * T for i in range(0, len(v), 2)]
            out.append((op, [c for q in pts for c in (q.x, q.y)]))
    return out


def _apply_replacements(doc, page, repl):
    """repl: [(start, end, yeni_bytes), ...] -> akisi tek seferde gunceller.
    Sondan basa uygulanir ki onceki araliklarin byte konumlari kaymasin."""
    xref = single_stream(doc, page)
    data = doc.xref_stream(xref)
    for s, e, b in sorted(repl, key=lambda r: r[0], reverse=True):
        data = data[:s] + b + data[e:]
    doc.update_stream(xref, data)


def transform_items(doc, page, items, A):
    """Secili yollari sayfa uzayindaki A matrisiyle (tasima/olcekleme)
    donusturur. Her yol kendi yerinde yeniden yazilir."""
    transform_each(doc, page, [(it, A) for it in items])


def transform_each(doc, page, pairs):
    """pairs: [(yol, sayfa_uzayi_matrisi), ...] - her yol kendi matrisiyle,
    hepsi tek seferde (byte konumlari kaymasin diye)."""
    repl = []
    for it, A in pairs:
        T = it.to_page * A * ~it.to_page
        repl.append((it.start, it.end, _emit(_xform_segs(it.segs, T))))
    if repl:
        _apply_replacements(doc, page, repl)


def _axis_rect_poly(item):
    """Yol tek, kapali, eksen-hizali bir dortgen mi (m l l l h ile cizilmis)."""
    if len(item.polys) != 1:
        return False
    poly, _ = item.polys[0]
    pts = []
    for p in poly:                       # ardisik ayni noktalari ele
        if not pts or abs(p - pts[-1]) > 1e-6:
            pts.append(p)
    if len(pts) > 1 and abs(pts[0] - pts[-1]) < 1e-6:
        pts.pop()                        # kapanis noktasi
    if len(pts) != 4:
        return False
    for i in range(4):
        a, b = pts[i], pts[(i + 1) % 4]
        if abs(a.x - b.x) > 1e-3 and abs(a.y - b.y) > 1e-3:
            return False
    return True


def is_filled_bar(item, max_thick=4.0):
    """Tablo cizgisi olarak cizilmis ince DOLGULU dikdortgen mi?
    Word/Excel ciktisi PDF'lerin cogu tablo cizgilerini boyle cizer (kontur
    degil 're f'). Bunlarda kalinlik = seridin kendi eni, renk = dolgu rengi."""
    if item.stroked or not item.filled:
        return False
    if item.kind != "rect" and not (item.kind == "shape" and _axis_rect_poly(item)):
        return False
    w, h = abs(item.bbox.width), abs(item.bbox.height)
    thin, long = min(w, h), max(w, h)
    return thin <= max_thick and long >= 3 * max(thin, 0.1)


def bar_thickness_matrix(item, thickness):
    """Dolgulu seridin enini merkezinden 'thickness' pt yapan sayfa matrisi
    (degisiklik gerekmiyorsa None)."""
    r = item.bbox
    w, h = abs(r.width), abs(r.height)
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    cur = h if w >= h else w
    if cur < 1e-6 or abs(cur - thickness) < 0.01:
        return None
    s = thickness / cur
    S = fitz.Matrix(1, 0, 0, s, 0, 0) if w >= h else fitz.Matrix(s, 0, 0, 1, 0, 0)
    return fitz.Matrix(1, 0, 0, 1, -cx, -cy) * S * fitz.Matrix(1, 0, 0, 1, cx, cy)


def set_line_points(doc, page, item, p1, p2, bend=None):
    """Tek bir cizginin uc noktalarini (sayfa uzayinda) degistirir. bend verilirse
    cizgi o noktadan gecen egri olur ("m ... c"), None ise duz ("m ... l").
    Renk/kalinlik/kesikli ayarlarina dokunulmaz (sadece yolun kendisi)."""
    inv = ~item.to_page
    a, b = fitz.Point(p1) * inv, fitz.Point(p2) * inv
    if bend is None:
        segs = [("m", [a.x, a.y]), ("l", [b.x, b.y])]
    else:
        c1, c2 = cubic_from_bend(p1, bend, p2)
        c1, c2 = c1 * inv, c2 * inv
        segs = [("m", [a.x, a.y]), ("c", [c1.x, c1.y, c2.x, c2.y, b.x, b.y])]
    _apply_replacements(doc, page, [(item.start, item.end, _emit(segs))])


def delete_items(doc, page, items):
    """Yollari (insa + boyama operatorleri) akistan tamamen cikarir."""
    _apply_replacements(doc, page, [(it.start, it.paint_end, b" ") for it in items])


def _scale(M):
    return math.sqrt(abs(M.a * M.d - M.b * M.c)) or 1.0


def restyle_items(doc, page, items, width=None, stroke=None, fill=None, dashed=None,
                  color=None):
    """Kalinlik / renk / kesikli cizgi degistirir: yolu 'q <ayarlar> ... Q'
    ile sarar, boylece sonraki cizimlerin ayarlari etkilenmez.

    color: yolun GORUNEN rengi - konturluysa kontur (RG), sadece dolguluysa
    dolgu (rg). Eskiden hep kontur rengi degisiyordu; dolgulu cizgilerde
    (Word/Excel tablolari) renk degisikligi hicbir sey yapmiyordu.
    Kalinlik ve kesikli stil yalnizca konturlu yollara uygulanir."""
    repl = []
    for it in items:
        pre = []
        sc = _scale(it.to_page)
        if it.stroked:
            if width is not None:
                pre.append(f"{_fmt(width / sc)} w")
            sc_col = stroke if stroke is not None else color
            if sc_col is not None:
                pre.append("{} {} {} RG".format(*[_fmt(c) for c in sc_col]))
            if dashed is not None:
                arr = dash_array(dashed, width if width is not None else style_of(page, it).get("width"))
                pre.append("[" + " ".join(_fmt(v / sc) for v in arr) + "] 0 d" if arr else "[] 0 d")
        fl_col = fill if fill is not None else (color if not it.stroked else None)
        if fl_col is not None:
            pre.append("{} {} {} rg".format(*[_fmt(c) for c in fl_col]))
        if not pre:
            continue
        data = doc.xref_stream(single_stream(doc, page))
        body = data[it.start:it.paint_end]
        repl.append((it.start, it.paint_end,
                     b"q " + " ".join(pre).encode() + b" " + body + b" Q"))
    if repl:
        _apply_replacements(doc, page, repl)


def style_of(page, item):
    """Yolun cizim ayarlarini (kalinlik, renkler, opaklik) PyMuPDF'in
    get_drawings ciktisindan, ayni konumdaki cizimi eslestirerek bulur."""
    best, bd = None, 1.0
    for d in page.get_drawings():
        r = d["rect"]
        dd = (abs(r.x0 - item.bbox.x0) + abs(r.y0 - item.bbox.y0)
              + abs(r.x1 - item.bbox.x1) + abs(r.y1 - item.bbox.y1))
        if dd < bd:
            best, bd = d, dd
    if best is None:
        return {"width": 1.0, "color": (0, 0, 0), "fill": None, "dashed": False}
    dashes = best.get("dashes") or ""
    dashed = dashes.strip() not in ("", "[] 0", "[ ] 0")
    vals = []
    if dashed:
        import re
        inner = dashes[dashes.find("[") + 1:dashes.find("]")] if "[" in dashes else ""
        vals = [float(v) for v in re.findall(r"[-+]?\d*\.?\d+", inner)]
    return {
        "width": best.get("width") or 0.0,
        "color": best.get("color"),
        "fill": best.get("fill"),
        "dashed": dashed,
        "dash": nearest_dash(vals, best.get("width")) if dashed else None,
    }


def add_line(page, p1, p2, width=0.75, color=(0, 0, 0), dashed=False):
    """dashed: False / True (kesikli) / desen adi (curve_math.DASH_STYLES)."""
    sh = page.new_shape()
    sh.draw_line(p1, p2)
    sh.finish(color=color, width=width, dashes=dash_string(dashed, width), closePath=False)
    sh.commit()


def add_ellipse(page, rect, width=0.75, color=(0, 0, 0), fill=None, dashed=False):
    sh = page.new_shape()
    sh.draw_oval(fitz.Rect(rect).normalize())
    sh.finish(color=color, fill=fill, width=width, dashes=dash_string(dashed, width))
    sh.commit()


def add_rect(page, rect, width=0.75, color=(0, 0, 0), fill=None, dashed=False):
    sh = page.new_shape()
    sh.draw_rect(fitz.Rect(rect).normalize())
    sh.finish(color=color, fill=fill, width=width, dashes=dash_string(dashed, width))
    sh.commit()
