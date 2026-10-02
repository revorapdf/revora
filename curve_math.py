"""
curve_math.py
-------------
Cizgi bukme geometrisi (Cizgi/Kutu modundaki kalici cizgiler ve Isaretle
oklari ortak kullanir).

Mantik: cizgi her zaman duz cizilir. Ortadaki "bukme" tutamaci surukleninice
cizgi, uclardan ve O NOKTADAN gecen yumusak bir egriye (ikinci derece Bezier)
donusur. PDF'e kubik Bezier olarak yazilir ("m ... c"); tutamac noktasi
egrinin tam ortasi (t = 0.5) oldugu icin kubikten geri hesaplanabilir ->
kaydedip acinca da ayni tutamacla duzenlenir.
"""
import math
import fitz
from i18n import _t


# ---------------------------------------------------------------- kesikli cizgi desenleri
# (ad, [cizgi, bosluk, ...] pt olarak, 1 pt kalinlik icin). Kalin cizgide desen
# kalinlikla orantili buyur (yoksa kesikler cilız kalir).
DASH_STYLES = (
    ("dash_s", _t("Sık kesikli"), (2.0, 2.0)),
    ("dash_m", _t("Kesikli"), (4.0, 3.0)),
    ("dash_l", _t("Seyrek kesikli"), (8.0, 4.0)),
    ("dot", _t("Noktalı"), (1.0, 2.0)),
    ("dashdot", _t("Çizgi-nokta"), (6.0, 2.0, 1.0, 2.0)),
)
_DASH = {k: v for k, _, v in DASH_STYLES}


def dash_array(style, width):
    """Desen (pt). style: DASH_STYLES anahtari; True = varsayilan kesikli; bos = duz."""
    if not style:
        return None
    pat = _DASH.get(style if isinstance(style, str) else "dash_m", _DASH["dash_m"])
    k = max(1.0, float(width or 1.0))
    return [v * k for v in pat]


def dash_string(style, width):
    """PDF / PyMuPDF bicimi: '[4 3] 0' (duz cizgide None)."""
    arr = dash_array(style, width)
    if not arr:
        return None
    return "[" + " ".join(f"{v:.3g}" for v in arr) + "] 0"


def nearest_dash(values, width):
    """Dosyadaki desenin (pt) en yakin hazir karsiligi."""
    if not values:
        return None
    k = max(1.0, float(width or 1.0))
    norm = [v / k for v in values]
    best, bd = "dash_m", float("inf")
    for key, _, pat in DASH_STYLES:
        if len(pat) != len(norm) and not (len(norm) == 2 * len(pat) and list(pat) * 2 == norm):
            continue
        d = sum(abs(a - b) for a, b in zip(norm, pat))
        if d < bd:
            best, bd = key, d
    return best


def cubic_from_bend(a, m, b):
    """a->b egrisi m noktasindan (t=0.5) gecsin: kubik kontrol noktalari (c1, c2)."""
    a, m, b = fitz.Point(a), fitz.Point(m), fitz.Point(b)
    q = m * 2 - (a + b) * 0.5            # ikinci derece egrinin kontrol noktasi
    return a + (q - a) * (2 / 3), b + (q - b) * (2 / 3)


def bend_from_cubic(a, c1, c2, b):
    """Kubik egrinin orta noktasi (t=0.5) = bukme tutamacinin yeri."""
    return (fitz.Point(a) + fitz.Point(c1) * 3 + fitz.Point(c2) * 3 + fitz.Point(b)) / 8


def point_seg_dist(p, a, b):
    p, a, b = fitz.Point(p), fitz.Point(a), fitz.Point(b)
    dx, dy = b.x - a.x, b.y - a.y
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return abs(p - a)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2))
    return abs(p - fitz.Point(a.x + t * dx, a.y + t * dy))


def is_straight(a, m, b, tol):
    """Bukme noktasi duz cizgiye tol kadar yakinsa cizgi duz sayilir."""
    return m is None or point_seg_dist(m, a, b) <= tol


def symmetric(a, b, m):
    """Shift: bukme noktasini ortanin dik dogrultusuna kilitle (simetrik yay)."""
    a, b, m = fitz.Point(a), fitz.Point(b), fitz.Point(m)
    mid = (a + b) * 0.5
    d = b - a
    L = abs(d)
    if L < 1e-9:
        return m
    n = fitz.Point(-d.y / L, d.x / L)
    t = (m.x - mid.x) * n.x + (m.y - mid.y) * n.y
    return mid + n * t


def keep_angle(fixed, end, pt, min_len=1.0):
    """Alt: ucu, cizginin MEVCUT dogrultusunda tut (aci sabit, sadece uzunluk
    degisir). Sabit ucun oburu tarafina gecemez."""
    fixed, end, pt = fitz.Point(fixed), fitz.Point(end), fitz.Point(pt)
    u = unit(end - fixed)
    if u is None:
        return pt
    t = max(min_len, (pt.x - fixed.x) * u.x + (pt.y - fixed.y) * u.y)
    return fixed + u * t


def angle_deg(a, b):
    """a->b dogrultusunun acisi (ekranda yukari pozitif, 0-180)."""
    a, b = fitz.Point(a), fitz.Point(b)
    return math.degrees(math.atan2(-(b.y - a.y), b.x - a.x)) % 180


def carry(a0, b0, m0, a1, b1):
    """Uc noktalar (a0,b0) -> (a1,b1) tasininca bukme noktasini da ayni oranda
    dondur/olcekle: egrinin bicimi korunur."""
    if m0 is None:
        return None
    z0 = complex(b0[0] - a0[0], b0[1] - a0[1])
    z1 = complex(b1[0] - a1[0], b1[1] - a1[1])
    if abs(z0) < 1e-9:
        return fitz.Point(m0) + (fitz.Point(a1) - fitz.Point(a0))
    k = z1 / z0
    w = complex(m0[0] - a0[0], m0[1] - a0[1]) * k
    return fitz.Point(a1[0] + w.real, a1[1] + w.imag)


def sample(a, c1, c2, b, n=24):
    """Egrinin nokta dizisi (a dahil)."""
    a, c1, c2, b = fitz.Point(a), fitz.Point(c1), fitz.Point(c2), fitz.Point(b)
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(a * (u ** 3) + c1 * (3 * u * u * t) + c2 * (3 * u * t * t) + b * (t ** 3))
    return out


def bent_points(a, m, b, n=24):
    """a->b cizgisi (m bukme noktasi; None = duz) icin nokta dizisi."""
    if m is None:
        return [fitz.Point(a), fitz.Point(b)]
    c1, c2 = cubic_from_bend(a, m, b)
    return sample(a, c1, c2, b, n)


def unit(v):
    L = math.hypot(v.x, v.y)
    return fitz.Point(v.x / L, v.y / L) if L > 1e-9 else None
