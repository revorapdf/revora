"""
pdf_markup.py
-------------
Duzenlenebilir isaretlemeler: ok, elips/daire, kutu, not kutusu, buyutec,
bulanik alan, kalem (ink: serbest cizim / fosforlu kalem / imza), metin vurgusu
(texthl: gercek PDF Highlight/Underline/StrikeOut nesnesi), numara rozeti,
goruntu.

Her isaretleme TEK bir PDF isaretleme nesnesidir (Stamp annotation) ve gorunumunu
(appearance) BIZ cizeriz: nesne gecici bir sayfaya PyMuPDF'in cizim araclari ve
TextWriter ile cizilir, o sayfa bir Form XObject'e cevrilip nesnenin gorunumu
(/AP /N) yapilir. Neden: PDF'in hazir ok/metin kutusu nesnelerini MuPDF kendi
cizer - ok ucu boyutu kalinliktan hesaplaniyor (devasa), metin kutusu sadece 3
yerlesik fontu biliyor, golge/kontur yok, kenarlik kapaliyken bile ince cizgi
kaliyor. Kendi cizimimizle hepsi kontrolumuzde: Windows fontlari, golge, kontur,
yuvarlak koseli arka plan, istenen boyutta ok ucu. Nesne Adobe'de de tek parca
gorunur ve tasinabilir.

Ayarlar nesneye /RevoraData (JSON) olarak yazilir: {"id", "kind", "role": "main", "p"}.
Dosya kaydedilip yeniden acilinca da duzenlenebilir. Degisiklikte nesne silinip
ayni id ile yeniden kurulur. (Onceki surumun cok parcali nesneleri de okunur;
ilk duzenlemede yeni yonteme cevrilir.)
"""
import json
import math
import re
import fitz

from font_resolver import resolve_font_path, font_file_exists
from curve_math import cubic_from_bend, bent_points, unit, carry, dash_string
from i18n import _t

KEY = "RevoraData"
KINDS = ("arrow", "ellipse", "rect", "note", "magnifier", "blur", "ink", "texthl", "number", "image")
HL_STYLES = (("highlight", _t("Vurgu")), ("underline", _t("Altı çizili")), ("strike", _t("Üstü çizili")))
DERIVED = ("blur", "magnifier")   # sayfa icerigini gosterenler (sayfa degisince yenilenir; sira onemli)
KAPPA = 0.5522847498      # daireyi 4 Bezier egrisiyle cizmek icin
_fonts = {}


def _P(p):
    return fitz.Point(p[0], p[1])


# ---------------------------------------------------------------- dondurme
# Kutu, daire, bulanik alan ve not (sadece yazi kutusu) kendi merkezi etrafinda
# dondurulebilir. P["angle"]: ekranda SAAT YONUNDE derece. P["rect"] / not kutusu
# donmemis halini tutar; cizimde merkez etrafinda dondurulur.
ROTATABLE = ("rect", "ellipse", "blur", "note", "image")


def _dash(P):
    """Kesikli desen adi (kesikli degilse None). Eski kayitlarda desen yok: 'Kesikli'."""
    return (P.get("dash") or "dash_m") if P.get("dashed") else None


def angle_of(P):
    try:
        a = float(P.get("angle") or 0.0) % 360.0
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if abs(a) < 1e-6 or abs(a - 360.0) < 1e-6 else a


def rot_pt(p, c, deg):
    """p'yi c etrafinda deg derece (ekranda saat yonunde; y asagi) dondur."""
    p, c = _P(p) if not isinstance(p, fitz.Point) else p, _P(c) if not isinstance(c, fitz.Point) else c
    if not deg:
        return fitz.Point(p)
    a = math.radians(deg)
    ca, sa = math.cos(a), math.sin(a)
    dx, dy = p.x - c.x, p.y - c.y
    return fitz.Point(c.x + dx * ca - dy * sa, c.y + dx * sa + dy * ca)


def frame(kind, P):
    """Dondurulebilir nesnenin donmemis kutusu ve merkezi."""
    r = note_geometry(P)[0] if kind == "note" else fitz.Rect(P["rect"]).normalize()
    return r, fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)


def frame_corners(kind, P):
    r, c = frame(kind, P)
    a = angle_of(P)
    return [rot_pt(q, c, a) for q in (r.tl, r.tr, r.br, r.bl)]


def rotated_bounds(kind, P):
    """Donmus nesnenin eksene hizali sinir kutusu (daire icin tam hesap)."""
    r, c = frame(kind, P)
    a = angle_of(P)
    if not a:
        return fitz.Rect(r)
    if kind == "ellipse":
        rx, ry = r.width / 2, r.height / 2
        t = math.radians(a)
        hw = math.sqrt((rx * math.cos(t)) ** 2 + (ry * math.sin(t)) ** 2)
        hh = math.sqrt((rx * math.sin(t)) ** 2 + (ry * math.cos(t)) ** 2)
        return fitz.Rect(c.x - hw, c.y - hh, c.x + hw, c.y + hh)
    pts = frame_corners(kind, P)
    return fitz.Rect(min(q.x for q in pts), min(q.y for q in pts),
                     max(q.x for q in pts), max(q.y for q in pts))


def to_local(kind, P, p):
    """Sayfa noktasini nesnenin donmemis cercevesine cevir."""
    a = angle_of(P)
    if not a:
        return fitz.Point(p)
    return rot_pt(fitz.Point(p), frame(kind, P)[1], -a)


def note_font(P):
    """Not yazisinin fontu (Windows font dosyasi; yoksa yerlesik Helvetica)."""
    name = P.get("font") or "Arial"
    if P.get("italic"):
        name += " Italic"
    path, _, _, _ = resolve_font_path(name, force_bold=bool(P.get("bold")))
    if path not in _fonts:
        try:
            _fonts[path] = fitz.Font(fontfile=path) if font_file_exists(path) else fitz.Font("helv")
        except Exception:
            _fonts[path] = fitz.Font("helv")
    return _fonts[path]


# ---------------------------------------------------------------- geometri
def head_size(P, width=None):
    """Ok ucunun (boy, yari-genislik). Govdeden biraz buyuk: 2 pt'lik okta ~7 pt."""
    w = P.get("width", 1.5) if width is None else width
    L = (2.0 * w + 3.0) * P.get("head_scale", 1.0)
    return L, L * 0.45


def arrow_parts(a, b, width, heads, P):
    """Govde (baslangic, bitis) ve ok ucu ucgenleri. Govde ok ucunun tabanina kadar
    kisaltilir ki kalin cizgi ucun sivri kismindan disari tasmasin."""
    a, b = _P(a), _P(b)
    d = b - a
    L = math.hypot(d.x, d.y)
    if L < 1e-6:
        return (a, b), []
    u = fitz.Point(d.x / L, d.y / L)
    n = fitz.Point(-u.y, u.x)
    hl, hw = head_size(P, width)
    hl = min(hl, L * 0.6)
    tris = []
    s, e = a, b
    if heads in ("end", "both"):
        base = b - u * hl
        tris.append([b, base + n * hw, base - n * hw])
        e = b - u * (hl * 0.85)
    if heads in ("start", "both"):
        base = a + u * hl
        tris.append([a, base + n * hw, base - n * hw])
        s = a + u * (hl * 0.85)
    return (s, e), tris


def arrow_curve(P, width=None, heads=None):
    """Bukulmus ok (P["bend"] noktasindan gecer): govde kubik egri (s, c1, c2, e)
    ve ok ucu ucgenleri. Ok ucu egrinin uctaki yonune bakar; govde ucun
    tabanina kadar kisaltilir (duz oktaki gibi)."""
    width = P["width"] if width is None else width
    heads = P.get("head", "end") if heads is None else heads
    return curve_arrow(P["p1"], P["p2"], P["bend"], width, heads, P)


def note_leader(P):
    """Not kutusundan hedefe giden cizgi: (baslangic, hedef, bukme noktasi|None)
    ya da None (hedef yok / kutunun icinde). Bukuluyse cizgi kutudan bukme
    noktasina dogru cikar."""
    if not P.get("target"):
        return None
    box, c = frame("note", P)
    a = angle_of(P)
    bend = _P(P["bend"]) if P.get("bend") else None
    # kutu donukse kenar noktasi kutunun kendi cercevesinde bulunur, sonra dondurulur
    loc = (lambda q: rot_pt(q, c, -a)) if a else (lambda q: q)
    s = edge_point(box, loc(bend)) if bend is not None else None
    if s is None:
        s = edge_point(box, loc(_P(P["target"])))
    if s is None:
        return None
    if a:
        s = rot_pt(s, c, a)
    return s, _P(P["target"]), bend


def ld_order(ld):
    """note_leader sonucunu bent_points(a, m, b) sirasina cevir."""
    s, t, bend = ld
    return s, bend, t


def curve_arrow(a, b, bend, width, heads, P):
    A, B = _P(a), _P(b)
    c1, c2 = cubic_from_bend(A, bend, B)
    hl, hw = head_size(P, width)
    L = abs(B - A)
    hl = min(hl, max(L, 1e-6) * 0.6)
    tris = []
    s, e = A, B
    ue = unit(B - c2) or unit(B - A)
    us = unit(A - c1) or unit(A - B)
    if heads in ("end", "both") and ue is not None:
        n = fitz.Point(-ue.y, ue.x)
        base = B - ue * hl
        tris.append([B, base + n * hw, base - n * hw])
        e = B - ue * (hl * 0.85)
        c2 = c2 - ue * (hl * 0.85)
    if heads in ("start", "both") and us is not None:
        n = fitz.Point(-us.y, us.x)
        base = A - us * hl
        tris.append([A, base + n * hw, base - n * hw])
        s = A - us * (hl * 0.85)
        c1 = c1 - us * (hl * 0.85)
    return (s, c1, c2, e), tris


def arrow_points(P):
    """Okun govdesinin nokta dizisi (duz okta 2 nokta) - isabet/kutu hesabi icin."""
    return bent_points(P["p1"], P.get("bend"), P["p2"])


def note_geometry(P):
    """Not kutusunun (dis kutu, yazi alani, satir taban cizgileri). Kutu yaziya gore
    kendiliginden boyutlanir; sol-ust kose P["pos"]."""
    size = P["size"]
    f = note_font(P)
    lines = (P.get("text") or " ").split("\n")
    lh = size * 1.22
    w = max(f.text_length(l, fontsize=size) for l in lines) if lines else size
    asc = f.ascender if f.ascender > 0 else 0.9
    desc = -f.descender if f.descender < 0 else 0.22
    h = (len(lines) - 1) * lh + (asc + desc) * size
    boxed = bool(P.get("fill") or P.get("border"))
    pad = max(3.0, size * 0.45) if boxed else max(1.0, size * 0.12)
    x, y = P["pos"]
    box = fitz.Rect(x, y, x + w + 2 * pad, y + h + 2 * pad)
    inner = fitz.Rect(x + pad, y + pad, x + pad + w, y + pad + h)
    baselines = [inner.y0 + asc * size + k * lh for k in range(len(lines))]
    return box, inner, lines, baselines


def edge_point(box, target):
    """Kutu merkezinden hedefe giden dogrunun kutu kenarini kestigi nokta
    (hedef kutunun icindeyse None: ok cizilmez)."""
    t = _P(target)
    if box.contains(t):
        return None
    c = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
    dx, dy = t.x - c.x, t.y - c.y
    sx = (box.width / 2) / abs(dx) if dx else math.inf
    sy = (box.height / 2) / abs(dy) if dy else math.inf
    s = min(sx, sy)
    return fitz.Point(c.x + dx * s, c.y + dy * s)


# ---------------------------------------------------------------- kalem (ink)
# P = {"strokes": [[[x, y], ...], ...], "color", "width", "opacity",
#      "hl": fosforlu kalem (carpma karisimi: alttaki yazi soluklasmaz),
#      "sig": imza (son kullanilan ayarlari ayri tutulur)}
def ink_points(P):
    return [[_P(q) for q in st] for st in (P.get("strokes") or []) if st]


def ink_bounds(P):
    pts = [q for st in ink_points(P) for q in st]
    if not pts:
        return fitz.Rect()
    return fitz.Rect(min(q.x for q in pts), min(q.y for q in pts),
                     max(q.x for q in pts), max(q.y for q in pts))


def simplify_stroke(pts, eps):
    """Fare orneklerini sadelestir (Ramer-Douglas-Peucker): gereksiz noktalar
    atilir, sekil eps (pt) hassasiyetinde korunur."""
    pts = [_P(q) for q in pts]
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        best, bi = 0.0, None
        for k in range(i + 1, j):
            d = _seg_dist(pts[k], pts[i], pts[j])
            if d > best:
                best, bi = d, k
        if bi is not None and best > eps:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    return [q for q, k in zip(pts, keep) if k]


def smooth_points(pts, radius=1.0):
    """Fare orneklerindeki titremeyi ve piksel basamaklarini yumusat. Cizgi once
    esit araliklarla yeniden orneklenir, sonra her nokta cizgi boyunca +-radius
    (pt) mesafedeki komsularinin ortalamasi olur (iki gecis ~ ucgen agirlik).
    Nokta sayisina degil MESAFEYE bagli oldugu icin hizli/yavas cizimde ayni
    sonucu verir. Uclar sabit; uca yaklastikca pencere simetrik daralir."""
    pts = [_P(q) for q in pts]
    if len(pts) < 3 or radius <= 0:
        return pts
    step = radius / 4.0
    res = [pts[0]]
    carry_d = 0.0
    for i in range(1, len(pts)):
        a_, b_ = pts[i - 1], pts[i]
        L = abs(b_ - a_)
        t = step - carry_d
        while t <= L:
            res.append(a_ + (b_ - a_) * (t / L))
            t += step
        carry_d = L - (t - step) if L > 0 else carry_d + L
    if abs(res[-1] - pts[-1]) > 1e-6:
        res.append(pts[-1])
    if len(res) < 5:
        return res
    K = 4                                   # +-4 adim = +-radius
    for _ in range(2):
        n = len(res)
        out = [res[0]]
        for i in range(1, n - 1):
            k = min(K, i, n - 1 - i)
            sx = sum(res[j].x for j in range(i - k, i + k + 1))
            sy = sum(res[j].y for j in range(i - k, i + k + 1))
            out.append(fitz.Point(sx / (2 * k + 1), sy / (2 * k + 1)))
        out.append(res[-1])
        res = out
    return res


def smooth_segments(pts):
    """Noktalardan gecen yumusak egri: MERKEZCIL Catmull-Rom -> kubik Bezier
    parcalari [(p0, c1, c2, p1), ...]. Merkezcil tur, noktalar arasi mesafe
    degistiginde (hizli/yavas cizim) duz Catmull-Rom'un yaptigi tasmalari ve
    kucuk dugumleri yapmaz."""
    n = len(pts)
    out = []
    for i in range(n - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < n else p2
        d1, d2, d3 = abs(p1 - p0), abs(p2 - p1), abs(p3 - p2)
        if d2 < 1e-9:
            continue
        a1, a2, a3 = d1 ** 0.5, d2 ** 0.5, d3 ** 0.5
        if d1 < 1e-9:
            c1 = p1 + (p2 - p1) * (1 / 3)
        else:
            c1 = (p2 * d1 - p0 * d2 + p1 * (2 * d1 + 3 * a1 * a2 + d2)) * (1 / (3 * a1 * (a1 + a2)))
        if d3 < 1e-9:
            c2 = p2 - (p2 - p1) * (1 / 3)
        else:
            c2 = (p1 * d3 - p3 * d2 + p2 * (2 * d3 + 3 * a3 * a2 + d2)) * (1 / (3 * a3 * (a3 + a2)))
        out.append((p1, c1, c2, p2))
    return out


def scale_strokes(P, old, new):
    """Kalem cizimini old kutusundan new kutusuna olcekler (tutamacla boyutlandirma)."""
    sx = new.width / old.width if old.width > 1e-6 else 1.0
    sy = new.height / old.height if old.height > 1e-6 else 1.0
    return [[[new.x0 + (q[0] - old.x0) * sx, new.y0 + (q[1] - old.y0) * sy] for q in st]
            for st in P.get("strokes") or []]


# ---------------------------------------------------------------- metin vurgusu
def word_at(words, p, tol):
    """Noktanin uzerindeki kelimenin sirasi (yoksa None). words: extractWORDS ciktisi."""
    p = _P(p)
    for i, w in enumerate(words):
        if w[0] - tol <= p.x <= w[2] + tol and w[1] - tol <= p.y <= w[3] + tol:
            return i
    return None


def nearest_word(words, p):
    p = _P(p)
    best, bd = None, 1e18
    for i, w in enumerate(words):
        dx = max(w[0] - p.x, 0, p.x - w[2])
        dy = max(w[1] - p.y, 0, p.y - w[3])
        d = dx * dx + 4 * dy * dy          # satir disina cikmak daha pahali
        if d < bd:
            best, bd = i, d
    return best


def _visual_rows(words):
    """Kelimeleri GORSEL satirlara ayir (PDF'in kendi satir bilgisi tablolarda
    etiketi, degeri ve yan sutunu tek satir sayabiliyor). Her satir: kelimeler
    x'e gore sirali."""
    hs = sorted(w[3] - w[1] for w in words)
    med = hs[len(hs) // 2] if hs else 10.0
    rows = []
    for w in sorted(words, key=lambda w: (w[1] + w[3]) / 2):
        cy, h = (w[1] + w[3]) / 2, w[3] - w[1]
        if h > med * 2.5 and (w[2] - w[0]) < h:
            continue          # dikey (90 derece donuk) yazi: satirlari birbirine baglamasin
        if rows and abs(cy - rows[-1]["cy"]) <= min(h, rows[-1]["h"]) * 0.5:
            r = rows[-1]
            r["words"].append(w)
            r["cy"] = (r["cy"] * (len(r["words"]) - 1) + cy) / len(r["words"])
            r["h"] = max(r["h"], h)
        else:
            rows.append({"cy": cy, "h": h, "words": [w]})
    for r in rows:
        r["words"].sort(key=lambda w: w[0])
    return rows


def _segments(row):
    """Satiri buyuk bosluklardan hucrelere bol (tablo sutunlari / etiket-deger)."""
    gap = row["h"] * 1.2
    segs, cur = [], []
    for w in row["words"]:
        if cur and w[0] - cur[-1][2] > gap:
            segs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        segs.append(cur)
    return segs


def text_rects(words, i, j):
    """Baslangic (i) ve bitis (j) kelimeleri arasindaki metnin kutulari (hucre
    basina bir kutu). Secim geometrik: gorsel satirlar ve bosluklarla ayrilan
    hucreler. Tablo/form sayfalarinda yan sutun ya da satir etiketi secime
    karismaz; paragrafta satirlar tam secilir."""
    A, B = words[i], words[j]
    rows = _visual_rows(words)

    def row_of(w):
        for k, r in enumerate(rows):
            if any(x is w for x in r["words"]):
                return k
        return None

    if row_of(A) is None or row_of(B) is None:        # dikey yazi: sadece kendisi
        return [list(A[:4])] if A is B else []

    ra, rb = row_of(A), row_of(B)
    if (rb, B[0]) < (ra, A[0]):                 # yukari/sola suruklendiyse yer degistir
        A, B, ra, rb = B, A, rb, ra
    xa, xb = min(A[0], B[0]), max(A[2], B[2])
    out = []

    def add(ws):
        if ws:
            out.append([min(w[0] for w in ws), min(w[1] for w in ws),
                        max(w[2] for w in ws), max(w[3] for w in ws)])

    for k in range(ra, rb + 1):
        segs = _segments(rows[k])
        if ra == rb:
            for sg in segs:
                add([w for w in sg if w[0] >= A[0] - 0.5 and w[2] <= B[2] + 0.5])
        elif k == ra:
            sg = next(sg for sg in segs if any(w is A for w in sg))
            add([w for w in sg if w[0] >= A[0] - 0.5])
        elif k == rb:
            sg = next(sg for sg in segs if any(w is B for w in sg))
            add([w for w in sg if w[2] <= B[2] + 0.5])
        else:
            for sg in segs:
                if sg[0][0] <= xb and sg[-1][2] >= xa:
                    add(sg)
    return out


# ---------------------------------------------------------------- numara rozeti
def number_font():
    return note_font({"font": "Arial", "bold": True})


def number_text(P):
    return str(int(P.get("n", 1)))


# ---------------------------------------------------------------- buyutec
# Iki tur: "detail" (teknik resimdeki detay gorunumu: kaynak daire + baska yerde
# buyutulmus daire + baglanti cizgisi, istege bagli "A" / "DETAY A (2:1)" etiketi)
# ve "lens" (yerinde buyutec: dairenin icinde altindaki alan buyutulmus gorunur).
# Buyutulmus icerik sayfanin KENDI cizim komutlaridir (resim degil) -> vektor
# kalir, her yakinlastirmada keskin.
def mag_geometry(P):
    """(kaynak merkez S, kaynak yaricap rs, gosterim merkezi D, gosterim yaricapi R)"""
    z = max(1.0, float(P.get("zoom", 2.0)))
    S = _P(P["src"])
    if P.get("mode") == "lens":
        R = float(P["r"])
        return S, R / z, S, R
    rs = float(P["r"])
    return S, rs, _P(P["dst"]), rs * z


def zoom_text(z):
    s = f"{z:.2f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") + ":1"


def mag_font(P):
    return note_font({"font": P.get("label_font") or "Arial", "bold": P.get("label_bold", True),
                      "italic": P.get("label_italic", False)})


def mag_caption(P):
    """Buyuk dairenin altindaki yazi. Bos birakilirsa detayda otomatik "DETAY A";
    'Olcek' acikken sonuna (2:1) eklenir. Yerinde buyutecte sadece yazilan metin."""
    if not P.get("caption_on", True):
        return ""
    detail = P.get("mode") != "lens"
    lab = (P.get("label") or "").strip() if _label_on(P) else ""
    text = (P.get("caption") or "").strip()
    if not text and detail:
        text = _t("DETAY {lab}", lab=lab) if lab else ""
    if P.get("show_scale", True) and (text or detail):
        sc = zoom_text(float(P.get("zoom", 2.0)))
        text = f"{text} ({sc})" if text else sc
    return text


def _label_on(P):
    # eski kayitlarda label_on yok: harf varsa acik say
    return P.get("label_on", bool(P.get("label")))


def mag_labels(P):
    """Etiket yazilari ve sol-alt (taban) noktalari: [(metin, nokta, boyut)]."""
    S, rs, D, R = mag_geometry(P)
    size = float(P.get("label_size", 10.0))
    out = []
    lab = (P.get("label") or "").strip()
    if P.get("mode") != "lens" and lab and _label_on(P):
        a = rs * 0.7071 + size * 0.25
        out.append((lab, fitz.Point(S.x + a, S.y - a), size))
    cap = mag_caption(P)
    if cap:
        lines = cap.split("\n")
        f = mag_font(P)
        for k, line in enumerate(lines):
            w = f.text_length(line, fontsize=size)
            out.append((line, fitz.Point(D.x - w / 2, D.y + R + size * (1.35 + 1.2 * k)), size))
    return out


def _label_rect(text, o, size, P=None):
    f = mag_font(P or {})
    return fitz.Rect(o.x, o.y - size * 0.95, o.x + f.text_length(text, fontsize=size), o.y + size * 0.25)


def mag_connector(P):
    """Iki daireyi birlestiren cizgi (daireler ust uste biniyorsa None)."""
    if P.get("mode") == "lens":
        return None
    S, rs, D, R = mag_geometry(P)
    d = D - S
    L = math.hypot(d.x, d.y)
    if L <= rs + R + 1:
        return None
    u = fitz.Point(d.x / L, d.y / L)
    return S + u * rs, D - u * R


def mag_part(m, p, tol):
    """Tiklanan parca: 'dst' (buyuk daire), 'src' (kaynak daire) ya da 'all'."""
    S, rs, D, R = mag_geometry(m["p"])
    p = fitz.Point(p)
    if abs(p - D) <= R + tol:
        return "dst" if m["p"].get("mode") != "lens" else "all"
    if abs(p - S) <= rs + tol:
        return "src"
    return "all"


def _circle_ops(cx, cy, r):
    k = r * KAPPA
    return (f"{cx + r:.3f} {cy:.3f} m "
            f"{cx + r:.3f} {cy + k:.3f} {cx + k:.3f} {cy + r:.3f} {cx:.3f} {cy + r:.3f} c "
            f"{cx - k:.3f} {cy + r:.3f} {cx - r:.3f} {cy + k:.3f} {cx - r:.3f} {cy:.3f} c "
            f"{cx - r:.3f} {cy - k:.3f} {cx - k:.3f} {cy - r:.3f} {cx:.3f} {cy - r:.3f} c "
            f"{cx + k:.3f} {cy - r:.3f} {cx + r:.3f} {cy - k:.3f} {cx + r:.3f} {cy:.3f} c h")


def _inherited(doc, xref, key):
    """Sayfa agacindan miras alinabilen anahtar (Resources) - PDF dizesi olarak."""
    for _ in range(32):
        t, v = doc.xref_get_key(xref, key)
        if t not in ("null", None) and v:
            return v
        t, v = doc.xref_get_key(xref, "Parent")
        if t != "xref":
            return None
        xref = int(v.split()[0])
    return None


def page_signature(doc, pno):
    """Sayfa iceriginin parmak izi: degisince buyutec icerigi yenilenir."""
    import hashlib
    page = doc[pno]
    h = hashlib.md5(page.read_contents())
    h.update((_inherited(doc, page.xref, "Resources") or "").encode("latin-1", "replace"))
    return h.hexdigest()


def _page_form(doc, pno):
    """Sayfanin icerigini (su anki hali) bir Form XObject'e kopyalar."""
    page = doc[pno]
    data = page.read_contents()
    res = _inherited(doc, page.xref, "Resources") or "<<>>"
    x = doc.get_new_xref()
    doc.update_object(x, f"<</Type/XObject/Subtype/Form/BBox[-100000 -100000 100000 100000]"
                         f"/Resources {res}>>")
    doc.update_stream(x, b"q\n" + data + b"\nQ")
    return x


def _union(r, pts):
    for p in pts:
        r = fitz.Rect(min(r.x0, p.x), min(r.y0, p.y), max(r.x1, p.x), max(r.y1, p.y))
    return r


def bbox(m):
    P, k = m["p"], m["kind"]
    if k == "arrow":
        pts = arrow_points(P)
        return fitz.Rect(min(q.x for q in pts), min(q.y for q in pts),
                         max(q.x for q in pts), max(q.y for q in pts))
    if k == "note":
        r = rotated_bounds("note", P)
        ld = note_leader(P)
        return _union(r, bent_points(*ld_order(ld))) if ld is not None else r
    if k == "magnifier":
        return _mag_bbox(P)
    if k == "ink":
        return ink_bounds(P)
    if k == "texthl":
        rs = [fitz.Rect(r) for r in P.get("rects") or []]
        return fitz.Rect(min(r.x0 for r in rs), min(r.y0 for r in rs),
                         max(r.x1 for r in rs), max(r.y1 for r in rs)) if rs else fitz.Rect()
    if k == "number":
        c, rad = _P(P["pos"]), P.get("size", 18) / 2
        return fitz.Rect(c.x - rad, c.y - rad, c.x + rad, c.y + rad)
    return rotated_bounds(k, P)


def _mag_bbox(P):
    S, rs, D, R = mag_geometry(P)
    r = fitz.Rect(S.x - rs, S.y - rs, S.x + rs, S.y + rs) | fitz.Rect(D.x - R, D.y - R, D.x + R, D.y + R)
    for text, o, size in mag_labels(P):
        r |= _label_rect(text, o, size, P)
    return r


def _extent(kind, P):
    """Gorunumun tamami (ok ucu, kalinlik, golge, kontur dahil) - nesnenin kutusu."""
    if kind == "arrow":
        if P.get("bend"):
            _, tris = arrow_curve(P)
            pts = arrow_points(P)
        else:
            (s, e), tris = arrow_parts(P["p1"], P["p2"], P["width"], P.get("head", "end"), P)
            pts = [s, e]
        r = _union(fitz.Rect(pts[0], pts[0]), pts[1:] + [q for t in tris for q in t])
        m = P["width"] / 2 + 2
    elif kind == "note":
        r = rotated_bounds("note", P)
        ld = note_leader(P)
        if ld is not None:
            s, t, bend = ld
            if bend is not None:
                _, tris = curve_arrow(s, t, bend, P.get("arrow_width", 1.5), "end", P)
                pts = bent_points(s, bend, t)
            else:
                (a, b), tris = arrow_parts(s, t, P.get("arrow_width", 1.5), "end", P)
                pts = [a, b]
            r = _union(r, pts + [q for tr in tris for q in tr])
        m = P["size"] * 0.15 + P.get("border_width", 1) + 3
    elif kind == "magnifier":
        r = _mag_bbox(P)
        m = P.get("width", 1.5) / 2 + 4          # golge + kalinlik payi
    elif kind == "blur":
        return rotated_bounds("blur", P)
    elif kind == "ink":
        r = ink_bounds(P)
        m = P.get("width", 2) / 2 + 2
    elif kind in ("number", "image", "texthl"):
        r = bbox({"kind": kind, "p": P})
        m = 1.0
    else:
        r = rotated_bounds(kind, P)
        m = P["width"] / 2 + 2
    return fitz.Rect(r.x0 - m, r.y0 - m, r.x1 + m, r.y1 + m)


def _seg_dist(p, a, b):
    dx, dy = b.x - a.x, b.y - a.y
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(p.x - a.x, p.y - a.y)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2))
    return math.hypot(p.x - (a.x + t * dx), p.y - (a.y + t * dy))


def hit(m, p, tol):
    P, k = m["p"], m["kind"]
    p = fitz.Point(p)
    if k == "arrow":
        pts = arrow_points(P)
        return min(_seg_dist(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1)) \
            <= tol + P.get("width", 1) / 2
    if k == "note":
        box = note_geometry(P)[0]
        if (box + (-tol, -tol, tol, tol)).contains(to_local("note", P, p)):
            return True
        ld = note_leader(P)
        if ld is None:
            return False
        pts = bent_points(*ld_order(ld))
        return min(_seg_dist(p, pts[i], pts[i + 1]) for i in range(len(pts) - 1)) <= tol + 1
    if k == "magnifier":
        S, rs, D, R = mag_geometry(P)
        if abs(p - D) <= R + tol or abs(p - S) <= rs + tol:
            return True
        c = mag_connector(P)
        if c is not None and _seg_dist(p, c[0], c[1]) <= tol + 1:
            return True
        return any(_label_rect(t, o, s, P).contains(p) for t, o, s in mag_labels(P))
    if k == "ink":
        lim = tol + P.get("width", 2) / 2
        for st in ink_points(P):
            if len(st) == 1 and abs(p - st[0]) <= lim:
                return True
            if any(_seg_dist(p, st[i], st[i + 1]) <= lim for i in range(len(st) - 1)):
                return True
        return False
    if k == "texthl":
        return any((fitz.Rect(r) + (-tol, -tol, tol, tol)).contains(p) for r in P.get("rects") or [])
    if k == "number":
        return abs(p - _P(P["pos"])) <= P.get("size", 18) / 2 + tol
    if k == "image":
        return (fitz.Rect(P["rect"]).normalize() + (-tol, -tol, tol, tol)).contains(to_local(k, P, p))
    r = fitz.Rect(P["rect"]).normalize()
    p = to_local(k, P, p)
    if k in ("rect", "blur"):
        return (r + (-tol, -tol, tol, tol)).contains(p)
    rx, ry = max(r.width / 2, 0.5), max(r.height / 2, 0.5)
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    return ((p.x - cx) / (rx + tol)) ** 2 + ((p.y - cy) / (ry + tol)) ** 2 <= 1.0


def near_outline(m, p, tol):
    """Kutu/dairenin CIZGISINE yakin mi (ici degil). Cizim araci aciktayken
    dolgusuz sekillerin icine yeni cizim baslatilabilsin diye."""
    r = fitz.Rect(m["p"]["rect"]).normalize()
    p = to_local(m["kind"], m["p"], p)
    if m["kind"] == "rect":
        inner = r + (tol, tol, -tol, -tol)
        return (r + (-tol, -tol, tol, tol)).contains(p) and not (
            inner.width > 0 and inner.height > 0 and inner.contains(p))
    rx, ry = max(r.width / 2, 0.5), max(r.height / 2, 0.5)
    cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
    d = math.hypot((p.x - cx) / rx, (p.y - cy) / ry)
    return abs(d - 1.0) * min(rx, ry) <= tol


def moved(m, dx, dy, keep_target=True):
    """Ayni nesnenin (dx, dy) kaydirilmis ayarlari (yeni sozluk).
    keep_target: not kutusu tasininca okun gosterdigi nokta SABIT kalir."""
    P = json.loads(json.dumps(m["p"]))
    if m["kind"] == "texthl":                 # metne bagli: yerinden oynamaz
        return P
    if m["kind"] == "ink":
        P["strokes"] = [[[q[0] + dx, q[1] + dy] for q in st] for st in P.get("strokes") or []]
        return P
    note_bend = m["kind"] == "note" and keep_target and P.get("bend") and P.get("target")
    old_ld = note_leader(P) if note_bend else None
    keys = ("p1", "p2", "pos", "src", "dst") + (() if keep_target else ("target",)) \
        + (() if note_bend else ("bend",))
    for key in keys:
        if P.get(key):
            P[key] = [P[key][0] + dx, P[key][1] + dy]
    if note_bend and old_ld is not None:
        # kutu kayar, hedef sabit: egri yeni baslangic noktasina gore esnesin
        new_s = (note_leader(P) or old_ld)[0]
        mb = carry(old_ld[0], old_ld[1], old_ld[2], new_s, old_ld[1])
        P["bend"] = [mb.x, mb.y]
    if P.get("rect"):
        r = P["rect"]
        P["rect"] = [r[0] + dx, r[1] + dy, r[2] + dx, r[3] + dy]
    return P


# ---------------------------------------------------------------- okuma
def read_page(page):
    """Sayfadaki Revora isaretlemeleri, cizim sirasina gore (sonuncu en ustte):
    [{"id", "kind", "p", "xrefs"}]"""
    doc = page.parent
    found = {}
    for order, a in enumerate(page.annots()):
        t, v = doc.xref_get_key(a.xref, KEY)
        if t != "string":
            continue
        try:
            d = json.loads(v)
        except ValueError:
            continue
        m = found.setdefault(d.get("id"), {"id": d.get("id"), "kind": d.get("kind"),
                                           "p": None, "xrefs": [], "order": order})
        m["xrefs"].append(a.xref)
        m["order"] = max(m["order"], order)
        if d.get("role") == "main":
            m["p"] = d.get("p")
            m["sig"] = d.get("sig")
    out = [m for m in found.values() if m["p"] is not None and m["kind"] in KINDS]
    return sorted(out, key=lambda m: m["order"])


# ---------------------------------------------------------------- cizim
def _draw_arrow(page, T, a, b, color, width, heads, P, opacity, dashed=False):
    (s, e), tris = arrow_parts(a, b, width, heads, P)
    sh = page.new_shape()
    sh.draw_line(T(s), T(e))
    sh.finish(color=color, width=width, dashes=dash_string(dashed, width),
              stroke_opacity=opacity, closePath=False, lineCap=1 if not tris else 0)
    for tri in tris:
        sh.draw_polyline([T(q) for q in tri] + [T(tri[0])])
        sh.finish(color=None, fill=color, fill_opacity=opacity, closePath=True)
    sh.commit()


def _draw_curve_arrow(page, T, a, b, bend, color, width, heads, P, opacity, dashed=False):
    (s, c1, c2, e), tris = curve_arrow(a, b, bend, width, heads, P)
    sh = page.new_shape()
    sh.draw_bezier(T(s), T(c1), T(c2), T(e))
    sh.finish(color=color, width=width, dashes=dash_string(dashed, width),
              stroke_opacity=opacity, closePath=False, lineCap=1 if not tris else 0)
    for tri in tris:
        sh.draw_polyline([T(q) for q in tri] + [T(tri[0])])
        sh.finish(color=None, fill=color, fill_opacity=opacity, closePath=True)
    sh.commit()


def _draw_text(page, T, P, inner, lines, baselines, morph=None):
    f = note_font(P)
    size, op = P["size"], P.get("opacity", 1.0)

    def write(dx, dy, color, opacity):
        tw = fitz.TextWriter(page.rect)
        for line, by in zip(lines, baselines):
            if line.strip():
                o = T(fitz.Point(inner.x0 + dx, by + dy))
                tw.append((o.x, o.y), line, font=f, fontsize=size)
        tw.write_text(page, color=color, opacity=opacity, morph=morph)

    if P.get("shadow"):
        s = max(0.8, size * 0.08)
        write(s, s, (0, 0, 0), 0.35 * op)
    if P.get("outline"):
        d = max(0.5, size * 0.065)
        col = P.get("outline_color") or [0, 0, 0]
        for k in range(8):
            ang = k * math.pi / 4
            write(d * math.cos(ang), d * math.sin(ang), col, op)
    write(0, 0, P["text_color"], op)


def _render(page, kind, P, ext, img=None):
    """Nesneyi gecici sayfaya (ext kutusunun sol-ust kosesi 0,0 olacak sekilde) cizer."""
    ox, oy = ext.x0, ext.y0

    def T(p):
        p = _P(p) if not isinstance(p, fitz.Point) else p
        return fitz.Point(p.x - ox, p.y - oy)

    op = P.get("opacity", 1.0)
    if kind == "ink":
        sh = page.new_shape()
        w = P.get("width", 2.0)
        for st in ink_points(P):
            if len(st) == 1 or all(abs(q - st[0]) < 0.05 for q in st):
                sh.draw_circle(T(st[0]), max(w / 2, 0.3))       # tek nokta: yuvarlak iz
                sh.finish(color=None, fill=P["color"], fill_opacity=op)
                continue
            for a, c1, c2, b in smooth_segments(st):
                sh.draw_bezier(T(a), T(c1), T(c2), T(b))
            sh.finish(color=P["color"], width=w, stroke_opacity=op, closePath=False,
                      lineCap=1, lineJoin=1)
        sh.commit()
        return
    if kind == "number":
        c, rad = _P(P["pos"]), P.get("size", 18) / 2
        sh = page.new_shape()
        sh.draw_circle(T(c), rad)
        sh.finish(color=None, fill=P["color"], fill_opacity=op)
        sh.commit()
        f = number_font()
        text = number_text(P)
        fs = rad * 1.1
        w = f.text_length(text, fontsize=fs)
        if w > rad * 1.5:                           # 3+ basamak: sigdir
            fs *= rad * 1.5 / w
            w = f.text_length(text, fontsize=fs)
        tw = fitz.TextWriter(page.rect)
        o = T(fitz.Point(c.x - w / 2, c.y + fs * 0.36))   # rakam yuksekligi ~0.72 em: dikeyde ortala
        tw.append((o.x, o.y), text, font=f, fontsize=fs)
        tw.write_text(page, color=P.get("text_color") or [1, 1, 1], opacity=op)
        return
    if kind == "image":
        r = fitz.Rect(P["rect"]).normalize()
        if img:
            page.insert_image(fitz.Rect(T(r.tl), T(r.br)), stream=img, keep_proportion=False)
        return
    if kind == "magnifier":
        # sadece cizgiler + etiketler; buyutulmus icerigi _mag_form ekler
        S, rs, D, R = mag_geometry(P)
        col, w = P["color"], P["width"]
        sh = page.new_shape()
        if P.get("mode") != "lens":
            sh.draw_circle(T(S), rs)
            sh.finish(color=col, width=w, dashes=dash_string(_dash(P), P.get("width", 1)),
                      stroke_opacity=op)
            c = mag_connector(P)
            if c is not None:
                sh.draw_line(T(c[0]), T(c[1]))
                sh.finish(color=col, width=max(0.5, w * 0.8), stroke_opacity=op, closePath=False)
        sh.draw_circle(T(D), R)
        sh.finish(color=col, width=w, stroke_opacity=op)
        sh.commit()
        labels = mag_labels(P)
        if labels:
            tw = fitz.TextWriter(page.rect)
            f = mag_font(P)
            for text, o, size in labels:
                q = T(o)
                tw.append((q.x, q.y), text, font=f, fontsize=size)
            tw.write_text(page, color=P.get("label_color") or col, opacity=op)
    elif kind == "blur":
        if img:                                 # donukse goruntu zaten maskeli (disi saydam)
            b = rotated_bounds("blur", P)
            page.insert_image(fitz.Rect(T(b.tl), T(b.br)), stream=img, keep_proportion=False)
        else:                                   # siyah kutu (donukse egik dortgen)
            sh = page.new_shape()
            pts = [T(q) for q in frame_corners("blur", P)]
            sh.draw_polyline(pts + [pts[0]])
            sh.finish(color=None, fill=(0, 0, 0), closePath=True)
            sh.commit()
    elif kind == "arrow" and P.get("bend"):
        _draw_curve_arrow(page, T, P["p1"], P["p2"], P["bend"], P["color"], P["width"],
                          P.get("head", "end"), P, op, _dash(P))
    elif kind == "arrow":
        _draw_arrow(page, T, P["p1"], P["p2"], P["color"], P["width"], P.get("head", "end"), P, op,
                    _dash(P))
    elif kind in ("ellipse", "rect"):
        r0, c = frame(kind, P)
        r = fitz.Rect(T(r0.tl), T(r0.br))
        a = angle_of(P)
        sh = page.new_shape()
        (sh.draw_oval if kind == "ellipse" else sh.draw_rect)(r)
        # PyMuPDF'te ekranda saat yonu = eksi aci
        sh.finish(color=P["color"], fill=P.get("fill"), width=P["width"],
                  dashes=dash_string(_dash(P), P.get("width", 1)),
                  stroke_opacity=op, fill_opacity=op,
                  morph=(T(c), fitz.Matrix(-a)) if a else None)
        sh.commit()
    else:
        box, inner, lines, baselines = note_geometry(P)
        ld = note_leader(P)
        if ld is not None:
            s, t, bend = ld
            col = P.get("arrow_color") or P.get("border") or P["text_color"]
            if bend is not None:
                _draw_curve_arrow(page, T, s, t, bend, col, P.get("arrow_width", 1.5), "end", P, op)
            else:
                _draw_arrow(page, T, s, t, col, P.get("arrow_width", 1.5), "end", P, op)
        a = angle_of(P)
        c = fitz.Point((box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2)
        morph = (T(c), fitz.Matrix(-a)) if a else None      # sadece kutu + yazi doner
        if P.get("fill") or P.get("border"):
            sh = page.new_shape()
            sh.draw_rect(fitz.Rect(T(box.tl), T(box.br)), radius=0.12)
            sh.finish(color=P.get("border"), fill=P.get("fill"),
                      width=P.get("border_width", 1.0) if P.get("border") else 0,
                      stroke_opacity=op, fill_opacity=op, morph=morph)
            sh.commit()
        _draw_text(page, T, P, inner, lines, baselines, morph)


def _blur_image(doc, pno, P):
    """Bulanik alanin (henuz uygulanmamis) gorunumu: altindaki sayfanin islenmis
    goruntusu. pdf_blur Qt kullanir (uygulamada PySide6 zaten fitz'ten once yuklu)."""
    import pdf_blur
    if P.get("mode") == "solid":
        return None
    page = doc[pno]
    rot = page.rotation
    if rot:
        page.set_rotation(0)                  # koordinatlar donmemis sayfaya gore
    try:
        return pdf_blur.make_image(page, fitz.Rect(P["rect"]).normalize(), P["mode"], P["level"],
                                   angle=angle_of(P))
    finally:
        if rot:
            page.set_rotation(rot)


def _tmp_form(doc, kind, P, ext, W, H, img=None):
    """Nesneyi gecici bir sayfaya cizip o cizimden Form XObject yapar."""
    tmp = doc.new_page(-1, width=W, height=H)
    try:
        _render(tmp, kind, P, ext, img)
        tmp.clean_contents()
        cont = tmp.get_contents()
        data = doc.xref_stream(cont[0]) if cont else b""
        res = doc.xref_get_key(tmp.xref, "Resources")[1] or "<<>>"
        form = doc.get_new_xref()
        doc.update_object(form, f"<</Type/XObject/Subtype/Form/BBox[0 0 {W:.4f} {H:.4f}]"
                                f"/Resources {res}>>")
        doc.update_stream(form, data)
    finally:
        doc.delete_page(len(doc) - 1)
    return form


def derived_sig(doc, pno, kind):
    """Sayfadan turetilen nesnelerin (bulanik alan, buyutec) parmak izi. Degisince
    nesne yeniden kurulur. Buyutec bekleyen bulanik alanlari da icinde gosterdigi
    icin onlarin ayarlari da buyutecin parmak izine girer."""
    sig = page_signature(doc, pno)
    if kind == "magnifier":
        import hashlib
        blurs = [m["p"] for m in read_page(doc[pno]) if m["kind"] == "blur"]
        if blurs:
            sig = hashlib.md5((sig + json.dumps(blurs, sort_keys=True)).encode()).hexdigest()
    return sig


def _blur_forms(doc, pno):
    """Sayfadaki bekleyen bulanik alanlarin gorunum formlari: [(form xref, ext, W, H)]."""
    out = []
    for m in read_page(doc[pno]):
        if m["kind"] != "blur":
            continue
        t, v = doc.xref_get_key(m["xrefs"][0], "AP/N")
        if t != "xref":
            continue
        ext = _extent("blur", m["p"])
        out.append((int(v.split()[0]), ext, max(ext.width, 1.0), max(ext.height, 1.0)))
    return out


def _mag_form(doc, pno, P, ext, W, H):
    """Buyutec gorunumu: golge + beyaz daire + daireye kirpilmis, olceklenmis sayfa
    icerigi (+ ustundeki bekleyen bulanik alanlar) + cizgiler/etiketler.
    Dondurur: (form xref, parmak izi)."""
    page = doc[pno]
    TM = page.transformation_matrix
    sig = derived_sig(doc, pno, "magnifier")
    pf = _page_form(doc, pno)
    blurs = _blur_forms(doc, pno)
    del page                                  # gecici sayfa eklenecek: Page nesnesi bayatlar
    deco = _tmp_form(doc, "magnifier", P, ext, W, H)
    S, rs, D, R = mag_geometry(P)
    z = R / rs
    # sayfa (sol-ust) uzayi -> gorunum formu uzayi (sol-alt, ext'in kosesi 0,0)
    to_form = fitz.Matrix(1, 0, 0, 1, -ext.x0, -ext.y0) * fitz.Matrix(1, 0, 0, -1, 0, H)
    zoom_m = (fitz.Matrix(1, 0, 0, 1, -S.x, -S.y) * fitz.Matrix(z, 0, 0, z, 0, 0)
              * fitz.Matrix(1, 0, 0, 1, D.x, D.y) * to_form)
    M = TM * zoom_m
    c = D * to_form
    so = max(0.8, min(3.0, R * 0.03))
    disc = _circle_ops(c.x, c.y, R)
    cm = lambda m: f"{m.a:.6f} {m.b:.6f} {m.c:.6f} {m.d:.6f} {m.e:.4f} {m.f:.4f} cm"
    inner = f"q {cm(M)} /RvPg Do Q"
    xobjs = f"/RvPg {pf} 0 R/RvDeco {deco} 0 R"
    for k, (bx, bext, bw, bh) in enumerate(blurs):
        # bulanik alanin formu (sol-alt 0,0) -> sayfa (sol-ust) -> buyutulmus -> bu form
        Mb = fitz.Matrix(1, 0, 0, -1, 0, bh) * fitz.Matrix(1, 0, 0, 1, bext.x0, bext.y0) * zoom_m
        inner += f" q {cm(Mb)} /RvBl{k} Do Q"
        xobjs += f"/RvBl{k} {bx} 0 R"
    stream = (f"q /RvGs gs 0 0 0 rg {_circle_ops(c.x + so, c.y - so, R)} f Q\n"
              f"q 1 1 1 rg {disc} f Q\n"
              f"q {disc} W n {inner} Q\n/RvDeco Do\n")
    form = doc.get_new_xref()
    doc.update_object(form, f"<</Type/XObject/Subtype/Form/BBox[0 0 {W:.4f} {H:.4f}]"
                            f"/Resources<</XObject<<{xobjs}>>"
                            f"/ExtGState<</RvGs<</ca 0.2/CA 0.2>>>>>>>>")
    doc.update_stream(form, stream.encode("latin-1"))
    return form, sig


def _wrap_form(doc, inner, W, H, gs=None, cm=None):
    """Formu bir grafik durumu (opaklik / karisim modu) ve/veya donusum matrisiyle
    (goruntu dondurme) saran yeni form."""
    form = doc.get_new_xref()
    res = f"/XObject<</RvIn {inner} 0 R>>" + (f"/ExtGState<</RvG {gs}>>" if gs else "")
    doc.update_object(form, f"<</Type/XObject/Subtype/Form/BBox[0 0 {W:.4f} {H:.4f}]"
                            f"/Resources<<{res}>>>>")
    ops = "q "
    if cm is not None:
        ops += f"{cm.a:.6f} {cm.b:.6f} {cm.c:.6f} {cm.d:.6f} {cm.e:.4f} {cm.f:.4f} cm "
    if gs:
        ops += "/RvG gs "
    doc.update_stream(form, (ops + "/RvIn Do Q").encode("latin-1"))
    return form


def _build_text_markup(doc, pno, mid, P):
    """Metin vurgusu: GERCEK PDF isaretleme nesnesi (Adobe'de de vurgu / alti cizili /
    ustu cizili olarak gorunur, yorum listesinde cikar). Gorunumunu MuPDF cizer."""
    page = doc[pno]
    quads = [fitz.Rect(r).quad for r in P.get("rects") or []]
    if not quads:
        return
    fn = {"underline": page.add_underline_annot,
          "strike": page.add_strikeout_annot}.get(P.get("style"), page.add_highlight_annot)
    a = fn(quads)
    a.set_colors(stroke=P["color"])
    a.set_opacity(max(0.05, min(1.0, P.get("opacity", 0.5))))
    a.update()
    x = a.xref
    for key in ("Contents", "Popup"):
        if doc.xref_get_key(x, key)[0] != "null":
            doc.xref_set_key(x, key, "null")
    doc.xref_set_key(x, "F", "4")
    d = {"id": mid, "kind": "texthl", "role": "main", "p": P}
    doc.xref_set_key(x, KEY, fitz.get_pdf_str(json.dumps(d, ensure_ascii=True)))


def _xobject_refs(doc, x):
    t, v = doc.xref_get_key(x, "Resources")
    if t == "xref":
        t, v = doc.xref_get_key(int(v.split()[0]), "XObject")
    else:
        t, v = doc.xref_get_key(x, "Resources/XObject")
    if t == "xref":
        v = doc.xref_object(int(v.split()[0]), compressed=True)
    return [int(n) for n in re.findall(r"(\d+)\s+0\s+R", v or "")]


def image_bytes(doc, annot_xref):
    """Goruntu nesnesinin resmini (PNG) gorunum formundan geri cikarir - dosya
    kaydedilip yeniden acildiktan sonra tasima/boyutlandirma icin."""
    t, v = doc.xref_get_key(annot_xref, "AP/N")
    if t != "xref":
        return None
    todo, seen = [int(v.split()[0])], set()
    while todo:
        x = todo.pop(0)
        if x in seen or len(seen) > 20:
            continue
        seen.add(x)
        st = doc.xref_get_key(x, "Subtype")[1]
        if st == "/Image":
            pix = fitz.Pixmap(doc, x)
            sm = doc.xref_get_key(x, "SMask")
            if sm[0] == "xref":
                pix = fitz.Pixmap(pix, fitz.Pixmap(doc, int(sm[1].split()[0])))
            if pix.colorspace is not None and pix.colorspace.n > 3:
                pix = fitz.Pixmap(fitz.csRGB, pix)
            return pix.tobytes("png")
        if st == "/Form":
            todo += _xobject_refs(doc, x)
    return None


def build(doc, pno, mid, kind, P, img=None):
    """Nesneyi sayfaya kurar. DIKKAT: gecici sayfa ekleyip silindigi icin daha
    once alinmis Page nesneleri gecersiz olabilir; cagiran doc[pno] ile yeniden alsin.
    img: goruntu nesnesinin resmi (bytes)."""
    if kind == "texthl":
        _build_text_markup(doc, pno, mid, P)
        return
    ext = _extent(kind, P)
    W, H = max(ext.width, 1.0), max(ext.height, 1.0)
    sig = None
    if kind == "magnifier":
        form, sig = _mag_form(doc, pno, P, ext, W, H)
    elif kind == "blur":
        sig = derived_sig(doc, pno, "blur")
        form = _tmp_form(doc, kind, P, ext, W, H, _blur_image(doc, pno, P))
    elif kind == "image":
        # Resim once KENDI (donmemis) kutusunda bir forma cizilir, sonra o form merkez
        # etrafinda dondurulerek nesnenin (donmus sinir) kutusuna yerlestirilir. Kalite
        # kaybi yok. (Once donmus kutuya cizilirse resmin kutu disinda kalan uclari
        # dondurmeden ONCE kirpiliyordu: 90 derecede ust/alt kesiliyordu.)
        op = P.get("opacity", 1.0)
        a = angle_of(P)
        if not a:
            form = _tmp_form(doc, kind, P, ext, W, H, img)
            cm = None
        else:
            r0, c = frame("image", P)
            ext0 = fitz.Rect(r0.x0 - 1, r0.y0 - 1, r0.x1 + 1, r0.y1 + 1)
            W0, H0 = max(ext0.width, 1.0), max(ext0.height, 1.0)
            form = _tmp_form(doc, kind, P, ext0, W0, H0, img)
            # ic form (sol-alt 0,0, y yukari) -> sayfa (y asagi) -> merkez etrafinda
            # ekranda saat yonu -> dis form (sol-alt 0,0, y yukari)
            cm = (fitz.Matrix(1, 0, 0, -1, ext0.x0, ext0.y0 + H0)
                  * fitz.Matrix(1, 0, 0, 1, -c.x, -c.y) * fitz.Matrix(a) * fitz.Matrix(1, 0, 0, 1, c.x, c.y)
                  * fitz.Matrix(1, 0, 0, -1, -ext.x0, ext.y0 + H))
        if cm is not None or op < 0.999:
            op = max(0.05, op)
            form = _wrap_form(doc, form, W, H,
                              f"<</ca {op:.3f}/CA {op:.3f}>>" if op < 0.999 else None, cm)
    else:
        form = _tmp_form(doc, kind, P, ext, W, H)
        if kind == "ink" and P.get("hl"):
            # fosforlu kalem: carpma karisimi -> alttaki siyah yazi siyah kalir
            form = _wrap_form(doc, form, W, H, "<</BM/Multiply>>")
    page = doc[pno]
    a = page.add_stamp_annot(ext)
    x = a.xref
    # nesnenin kutusu: sayfa (sol-ust) uzayindan PDF uzayina (her sayfa donusunde dogru)
    r = ext * ~page.transformation_matrix
    doc.xref_set_key(x, "Rect", f"[{r.x0:.4f} {r.y0:.4f} {r.x1:.4f} {r.y1:.4f}]")
    doc.xref_set_key(x, "AP", f"<</N {form} 0 R>>")
    doc.xref_set_key(x, "Name", "/Revora")
    doc.xref_set_key(x, "F", "4")                     # yazdirirken de gorunsun
    _strip_comment(doc, x)
    d = {"id": mid, "kind": kind, "role": "main", "p": P}
    if sig:
        d["sig"] = sig                                # buyutec/bulanik: hangi sayfa icerigini gosteriyor
    # ensure_ascii: Turkce harfler \\uXXXX -> PDF dizesi saf ASCII kalir
    doc.xref_set_key(x, KEY, fitz.get_pdf_str(json.dumps(d, ensure_ascii=True)))


def _strip_comment(doc, x):
    """PyMuPDF'in damgaya kendiliginden ekledigi /Contents(Approved) ve kirmizi /C'yi
    kaldir: Edge/Adobe gibi goruntuleyiciler yorum metni olan her nesnenin yanina
    (bu renkte) bir yorum simgesi koyuyordu. Bizim nesnelerin yorumu yok."""
    for key in ("Contents", "C", "Popup"):
        if doc.xref_get_key(x, key)[0] != "null":
            doc.xref_set_key(x, key, "null")


def clean_page(page):
    """Eski surumle kaydedilmis dosyalardaki Revora nesnelerini temizle (acilista).
    Degisiklik yaptiysa True."""
    doc = page.parent
    changed = False
    for a in page.annots():
        x = a.xref
        if doc.xref_get_key(x, KEY)[0] != "string" or a.type[0] != fitz.PDF_ANNOT_STAMP:
            continue            # metin vurgusunun rengi /C'dir: dokunma
        if any(doc.xref_get_key(x, k)[0] != "null" for k in ("Contents", "C", "Popup")):
            _strip_comment(doc, x)
            changed = True
    return changed


def remove(page, xrefs):
    for x in xrefs:
        try:
            a = page.load_annot(x)
        except Exception:
            a = None
        if a is not None:
            page.delete_annot(a)
