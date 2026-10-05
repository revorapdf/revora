"""
pdf_tables.py
-------------
PDF sayfalarindaki TABLOLARI bulur ve Excel'e doker.

- Tablo bulma: PyMuPDF'in find_tables'i (cizgili tablolar: "lines"; istenirse cizgisiz
  tablolar icin "text" yedegi). Birlesik hucreler hucre kutularindan cikarilir.
- Hucre yazisi: find_tables'in kendi metni DEGIL, motorun yazi listesi (Span). Sebep:
  sayfayi kaplayan egik filigranin harfleri hucre kutularinin icine dusuyor ve tabloya
  "HA", "KED" gibi parcalar karisiyordu; donuk yazilar burada elenir.
- Sayilar: "1.016,74" (TR) ve "1,016.74" (EN) bicimleri taninir; belgede hangisi baskinsa
  belirsiz olanlar ("1.234") ona gore yorumlanir. Sayi olmayan her sey yazi kalir.
"""
import math
import re
import fitz

import xlsx_writer

try:                                       # (find_tables her cagrida konsola oneri yaziyor)
    fitz.no_recommend_layout()
except Exception:
    pass


class Cell:
    __slots__ = ("row", "col", "rowspan", "colspan", "text", "bold", "free",
                 "italic", "size", "color", "font", "align", "valign")

    def __init__(self, row, col, rowspan, colspan, text, bold, free=False, look=None):
        self.row, self.col, self.rowspan, self.colspan, self.text, self.bold = row, col, rowspan, colspan, text, bold
        # free: cizgisiz bilgi blogundan ayrilmis parca (kenarliksiz, kaydirmasiz; saga tasar)
        self.free = free
        # gorunum (_look): size = Excel'deki punto (None: varsayilan 10), color = 0xRRGGBB (None: siyah),
        # font = yazi tipi ailesi (None: varsayilan), align / valign = hucre icindeki hiza
        self.italic, self.size, self.color, self.font, self.align, self.valign = False, None, None, None, None, None
        for k, v in (look or {}).items():
            setattr(self, k, v)

    @property
    def scale(self):
        """Yazinin varsayilan 10 puntoya orani (genislik / yukseklik hesaplari icin)."""
        return (self.size or 10.0) / 10.0


class TableData:
    def __init__(self, page, index, bbox, n_rows, n_cols, cells, col_widths):
        self.page, self.index, self.bbox = page, index, bbox
        self.n_rows, self.n_cols, self.cells, self.col_widths = n_rows, n_cols, cells, col_widths

    def filled(self):
        return sum(1 for c in self.cells if c.text.strip())


def _bounds(values, tol=1.5):
    """Yakin degerleri tek sinirda topla -> sirali sinir listesi."""
    out = []
    for v in sorted(values):
        if not out or v - out[-1] > tol:
            out.append(v)
    return out


def _index(bounds, v, tol=1.5):
    for i, b in enumerate(bounds):
        if abs(b - v) <= tol:
            return i
    return min(range(len(bounds)), key=lambda i: abs(bounds[i] - v))


def _visible_spans(engine, pno):
    """Aktarilacak yazilar: sayfada gercekten gorunenler (bkz. PDFEditor.visible_spans), egik
    olanlar (filigran) haric."""
    return [s for s in engine.visible_spans(pno) if not s.rotated]


# ---------------------------------------------------------------- gorunum (boyut, renk, hiza)
_FAMILIES = (("times", "Times New Roman"), ("nimbusrom", "Times New Roman"), ("liberationserif", "Times New Roman"),
             ("arial", "Arial"), ("helvetica", "Arial"), ("nimbussan", "Arial"), ("liberationsans", "Arial"),
             ("calibri", "Calibri"), ("cambria", "Cambria"), ("couriernew", "Courier New"), ("courier", "Courier New"),
             ("verdana", "Verdana"), ("tahoma", "Tahoma"), ("georgia", "Georgia"), ("segoeui", "Segoe UI"),
             ("garamond", "Garamond"), ("trebuchet", "Trebuchet MS"), ("consolas", "Consolas"),
             ("palatino", "Palatino Linotype"), ("bookantiqua", "Book Antiqua"), ("centurygothic", "Century Gothic"))


def _family(name):
    """PDF'teki yazi tipi adi ("ABCDEF+TimesNewRomanPS-BoldMT") -> Excel'de bilinen aile adi | None.
    Taninmayan tip varsayilanda kalir (rastgele bir ad yazilirsa Excel yedek tipe duser)."""
    n = re.sub(r"^[A-Z]{6}\+", "", name or "").lower().replace(" ", "").replace("-", "").replace(",", "")
    for key, family in _FAMILIES:
        if key in n:
            return family
    return None


def _base_size(spans):
    """Sayfanin GOVDE yazi boyutu: en cok harfin yazildigi boyut. Excel'de 10 punto olur; digerleri
    ona oranla buyur / kuculur (PDF'te govde cogu zaman 6-7 punto: aynen aktarilsa okunmaz)."""
    count = {}
    for sp in spans:
        k = round(sp.size * 2) / 2
        count[k] = count.get(k, 0) + len(sp.text.strip())
    return max(count, key=count.get) if count else 10.0


def _look(spans, base, box=None, lines=None):
    """Yazilarin gorunumu -> Cell alanlari. PDF'te "ortala" diye bir bilgi YOKTUR; hiza, yazinin
    kutu icindeki yerinden cikarilir (box + lines verilirse)."""
    out = {}
    if not spans:
        return out

    def top(key):                                  # harf sayisina gore baskin deger
        count = {}
        for sp in spans:
            count[key(sp)] = count.get(key(sp), 0) + max(1, len(sp.text.strip()))
        return max(count, key=count.get)

    ratio = top(lambda sp: round(sp.size * 2) / 2) / max(base, 1.0)
    if not 0.8 <= ratio <= 1.25:                   # govdeye yakin boyutlar tek boyut (6 / 7 punto karisimi)
        out["size"] = float(max(7, min(round(10 * ratio), 26)))
    color = int(top(lambda sp: sp.color & 0xFFFFFF))
    r, g, b = color >> 16 & 255, color >> 8 & 255, color & 255
    if max(r, g, b) >= 48 and 0.299 * r + 0.587 * g + 0.114 * b < 225:
        out["color"] = color                       # (siyaha yakin: otomatik; beyaza yakin: zemin aktarilmadigi icin siyah)
    out["italic"] = all(sp.flags & 2 for sp in spans)
    out["font"] = _family(top(lambda sp: sp.font))
    if box is not None and lines:
        x0, y0, x1, y1 = box
        left = [min(sp.bbox.x0 for sp in ln) - x0 for ln in lines]
        right = [x1 - max(sp.bbox.x1 for sp in ln) for ln in lines]
        tol = max(1.5, (x1 - x0) * 0.06)
        if max(left) > 3.0 and all(abs(a - b) <= tol for a, b in zip(left, right)):
            out["align"] = "center"                # her satirin iki yanindaki bosluk esit
        elif max(left) > 3.0 and all(b <= max(3.0, tol) and a > b for a, b in zip(left, right)):
            out["align"] = "right"
        else:
            out["align"] = "left"
        above = min(sp.bbox.y0 for sp in lines[0]) - y0
        below = y1 - max(sp.bbox.y1 for sp in lines[-1])
        if abs(above - below) <= max(2.0, (y1 - y0) * 0.15):
            out["valign"] = "center"
        else:
            out["valign"] = "bottom" if below < above else "top"
    return out


def _clean(text):
    return text.replace("\xa0", " ").replace("\xad", "-")


def _cell_lines(spans, box):
    """Kutunun icindeki (merkezi iceride) yazilar, satir satir: [[Span, ...], ...] (soldan saga)."""
    x0, y0, x1, y1 = box
    inside = []
    for sp in spans:
        cx, cy = (sp.bbox.x0 + sp.bbox.x1) / 2, (sp.bbox.y0 + sp.bbox.y1) / 2
        if x0 - 0.5 <= cx <= x1 + 0.5 and y0 - 0.5 <= cy <= y1 + 0.5:
            inside.append(sp)
    if not inside:
        return []
    inside.sort(key=lambda s: (s.origin[1], s.origin[0]))
    lines, cur, base = [], [], None
    for sp in inside:
        if base is not None and abs(sp.origin[1] - base) > max(1.5, sp.size * 0.45):
            lines.append(cur)
            cur = []
        cur.append(sp)
        base = sp.origin[1] if len(cur) == 1 else base
    lines.append(cur)
    for ln in lines:
        ln.sort(key=lambda s: s.origin[0])
    return lines


def _join(parts):
    """Ayni satirdaki yazi parcalarini birlestir (aralarinda bosluk varsa bir bosluk)."""
    s = ""
    for i, sp in enumerate(parts):
        t = _clean(sp.text)
        if i and sp.bbox.x0 - parts[i - 1].bbox.x1 > sp.size * 0.2 and not s.endswith(" ") and not t.startswith(" "):
            s += " "
        s += t
    return " ".join(s.split())


def _explode(spans, box, xs):
    """Cizgisiz bilgi blogu (tablonun TUM genisligini kaplayan, cok satirli tek hucre):
    "ETIKET : deger    ETIKET : deger" duzeni PDF'te cizgisizdir, tek hucreye yigilirdi.
    Her yazi satiri ayri bir Excel satiri olur; satirdaki parcalar (aralarinda belirgin bosluk
    olanlar) baslangic x'lerine gore tablonun SUTUNLARINA oturtulur. Tek basina ":" atilir.
    Donus: [(satir_no, sutun, yazi, kalin)] ya da None (ayrilacak bir sey yok)."""
    lines = _cell_lines(spans, box)
    if len(lines) < 3:
        return None
    out, split_any = [], False
    for k, ln in enumerate(lines):
        groups, cur = [], [ln[0]]
        for sp in ln[1:]:
            if sp.bbox.x0 - cur[-1].bbox.x1 > max(4.0, sp.size * 0.9):     # belirgin bosluk: yeni parca
                groups.append(cur)
                cur = [sp]
            else:
                cur.append(sp)
        groups.append(cur)
        placed = {}
        for g in groups:
            text = _join(g)
            if text.startswith(":"):               # ": deger" -> "deger" (iki nokta etiketle deger arasindaki ayirac)
                text = text[1:].strip()
            if not text:
                continue
            x = g[0].bbox.x0
            col = max((i for i in range(len(xs) - 1) if xs[i] <= x + 0.5), default=0)
            if col in placed:                      # ayni sutuna dusen iki parca: yan yana
                placed[col] = (placed[col][0] + " " + text, placed[col][1] and all(s.is_bold for s in g),
                               placed[col][2] + g)
            else:
                placed[col] = (text, all(s.is_bold for s in g), list(g))
        if len(placed) > 1:
            split_any = True
        out += [(k, col, text, bold, group) for col, (text, bold, group) in sorted(placed.items())]
    return (out, len(lines)) if split_any else None


def page_tables(engine, pno, text_fallback=False):
    """Sayfadaki tablolar -> [TableData]. text_fallback: cizgili tablo yoksa cizgisiz ara."""
    page = engine.doc[pno]
    spans = _visible_spans(engine, pno)
    found = []
    try:
        found = list(page.find_tables().tables)
        if not found and text_fallback:
            found = list(page.find_tables(strategy="text").tables)
    except Exception:
        found = []
    out = []
    base = _base_size(spans)
    for t in found:
        boxes = [c for c in t.cells if c]
        if not boxes:
            continue
        xs = _bounds([b[0] for b in boxes] + [b[2] for b in boxes])
        ys = _bounds([b[1] for b in boxes] + [b[3] for b in boxes])
        if len(xs) < 2 or len(ys) < 2:
            continue
        cells, seen, blocks = [], set(), []
        n_cols = len(xs) - 1
        for b in boxes:
            c0, c1 = _index(xs, b[0]), _index(xs, b[2])
            r0, r1 = _index(ys, b[1]), _index(ys, b[3])
            if c1 <= c0 or r1 <= r0 or (r0, c0) in seen:
                continue
            seen.add((r0, c0))
            parts = _explode(spans, b, xs) if (c0 == 0 and c1 == n_cols and n_cols >= 3) else None
            if parts is not None:                  # cizgisiz bilgi blogu: satirlara / sutunlara ayrilir
                blocks.append((r0, r1 - r0, parts))
                continue
            lines = _cell_lines(spans, b)
            inside = [sp for ln in lines for sp in ln]
            text = "\n".join(t_ for t_ in (_join(ln) for ln in lines) if t_)
            cells.append(Cell(r0, c0, r1 - r0, c1 - c0, text, bool(inside) and all(sp.is_bold for sp in inside),
                              look=_look(inside, base, b, lines)))
        n_rows = len(ys) - 1
        for r0, span, (parts, n_lines) in sorted(blocks, key=lambda x: -x[0]):     # alttan uste: kayma karismasin
            grow = max(0, n_lines - span)
            for c in cells:
                if c.row > r0:
                    c.row += grow
            for k, col, text, bold, group in parts:
                cells.append(Cell(r0 + k, col, 1, 1, text, bold, free=True, look=_look(group, base)))
            n_rows += grow
        if not any(c.text.strip() for c in cells):
            continue
        widths = [xs[i + 1] - xs[i] for i in range(len(xs) - 1)]
        out.append(TableData(pno, len(out), fitz.Rect(t.bbox), n_rows, n_cols, cells, widths))
    return out


# ---------------------------------------------------------------- tum sayfa
FILL_GAP = 26.0          # bu kadar puntodan uzun bos dikey aralik, ~14 punto araliklarla satirlara bolunur


def _pieces(line):
    """Bir yazi satirini, aralarinda belirgin bosluk olan parcalara ayir -> [(x0, yazi, kalin, yazilar)]."""
    groups, cur = [], [line[0]]
    for sp in line[1:]:
        if sp.bbox.x0 - cur[-1].bbox.x1 > max(4.0, sp.size * 0.9):
            groups.append(cur)
            cur = [sp]
        else:
            cur.append(sp)
    groups.append(cur)
    out = []
    for g in groups:
        text = _join(g)
        if text.startswith(":"):
            text = text[1:].strip()
        if text:
            out.append((g[0].bbox.x0, text, all(s.is_bold for s in g), g))
    return out


IMAGE_DPI = 220          # Excel'e giden resim, gosterildigi boyuta gore bundan yogun olmaz


def _picture(doc, xref, width_pt=0.0, height_pt=0.0):
    """Resmin Excel'e gomulecek baytlari (JPEG ya da PNG) | None.
    - Saydam olmayan JPEG fotograf OLDUGU GIBI aktarilir: yeniden sikistirilmaz (kalite kaybi
      yok, dosya kucuk kalir). Saydamlik maskesi tamamen opaksa yok sayilir.
    - Saydam ya da JPEG olmayan resim PNG olur (maske uygulanmis, CMYK ise RGB'ye cevrilmis).
    - Sayfada gosterildigi boyuta gore IMAGE_DPI'dan cok daha yogun resim kucultulur
      (Excel dosyasi gereksiz sismesin)."""
    try:
        try:
            info = doc.extract_image(xref)
        except Exception:
            info = {}
        pix = fitz.Pixmap(doc, xref)
        mask = None
        smask = info.get("smask") or 0
        if smask and not pix.alpha:
            try:
                mask = fitz.Pixmap(doc, smask)
                if min(mask.samples) == 255:       # tamamen opak maske: saydamlik yok
                    mask = None
            except Exception:
                mask = None
        over = 1.0
        if width_pt > 0 and height_pt > 0:
            over = min(pix.width / (width_pt / 72.0), pix.height / (height_pt / 72.0)) / IMAGE_DPI
        opaque = mask is None and not pix.alpha
        if (opaque and over <= 1.25 and info.get("ext") in ("jpeg", "jpg") and info.get("bpc") == 8
                and info.get("colorspace") in (1, 3) and info.get("image")):
            return bytes(info["image"])
        if mask is not None:
            try:
                pix = fitz.Pixmap(pix, mask)
            except Exception:
                pass
        if pix.colorspace is not None and pix.colorspace.n > 3:      # CMYK -> RGB
            pix = fitz.Pixmap(fitz.csRGB, pix)
        if over > 1.25:
            pix = fitz.Pixmap(pix, max(1, round(pix.width / over)), max(1, round(pix.height / over)))
        if opaque and info.get("ext") in ("jpeg", "jpg") and pix.colorspace is not None and pix.colorspace.n in (1, 3):
            return pix.tobytes("jpeg", jpg_quality=90)
        return pix.tobytes("png")
    except Exception:
        return None


def page_sheet(engine, pno, images=True, text_fallback=False):
    """SAYFANIN TAMAMI tek bir Excel sayfasi olarak: tablolar, tablo disindaki yazilar ve
    resimler sayfadaki yerlesimiyle. -> TableData (ek alanlar: images, row_pt) | None (bos sayfa).

    Yontem: sayfa icin ORTAK bir izgara kurulur. Sutun sinirlari tum tablolarin sutun
    sinirlarinin birlesimidir; satir sinirlari tablo satirlari + her yazi satirinin ustu +
    resimlerin ustudur (uzun bosluklar ara satirlarla doldurulur ki resim, altindaki icerigin
    ustune binmesin). Her sey bu izgaraya oturtulur: tablo hucresi gerekirse birkac sutunu /
    satiri kaplar (birlesik), serbest yazi baslangic x'ine denk gelen sutuna yazilir."""
    page = engine.doc[pno]
    pr = page.rect
    spans = _visible_spans(engine, pno)
    try:
        found = list(page.find_tables().tables)
        if not found and text_fallback:
            found = list(page.find_tables(strategy="text").tables)
    except Exception:
        found = []
    used, cell_defs, free_lines = set(), [], []
    for t in found:
        boxes = [c for c in t.cells if c]
        if not boxes:
            continue
        txs = _bounds([b[0] for b in boxes] + [b[2] for b in boxes])
        for b in boxes:
            lines = _cell_lines(spans, b)
            for ln in lines:
                used.update(id(sp) for sp in ln)
            full = len(txs) > 3 and abs(b[0] - txs[0]) < 2 and abs(b[2] - txs[-1]) < 2
            if full and len(lines) >= 3 and any(len(_pieces(ln)) > 1 for ln in lines):
                free_lines += lines                  # cizgisiz bilgi blogu: satir satir serbest yazi
                continue
            text = "\n".join(t_ for t_ in (_join(ln) for ln in lines) if t_)
            cell_defs.append((b, text, lines))
    rest = [sp for sp in spans if id(sp) not in used]
    free_lines += _cell_lines(rest, (-1e6, -1e6, 1e6, 1e6))
    pics = []
    if images:
        for it in engine._pickable_images(pno):
            data = _picture(engine.doc, it.xref, it.bbox.width, it.bbox.height)
            if data:
                pics.append((it.bbox, data))
    if not cell_defs and not free_lines and not pics:
        return None

    # ---- sutun sinirlari
    xs = _bounds([b[0] for b, _, _ in cell_defs] + [b[2] for b, _, _ in cell_defs], 2.0)
    if len(xs) < 2:                                  # tablo yok: yazilarin ve resimlerin sol kenarlari sutun olur
        xs = _bounds([p[0] for ln in free_lines for p in _pieces(ln)] + [bb.x0 for bb, _ in pics], 8.0)[:24]
        xs = (xs or [0.0]) + [max(pr.width, (xs[-1] if xs else 0) + 40)]
    # ---- satir sinirlari
    tops = [b[1] for b, _, _ in cell_defs] + [b[3] for b, _, _ in cell_defs]
    tops += [min(sp.bbox.y0 for sp in ln) for ln in free_lines]
    tops += [bb.y0 for bb, _ in pics]
    last = max([b[3] for b, _, _ in cell_defs] + [max(sp.bbox.y1 for sp in ln) for ln in free_lines]
               + [bb.y1 for bb, _ in pics])
    ys = _bounds(tops, 2.5)
    if not ys or last - ys[-1] > 2.5:
        ys.append(last)
    filled = [ys[0]]
    for y in ys[1:]:
        gap = y - filled[-1]
        if gap > FILL_GAP:
            n = int(round(gap / 14.0))
            base = filled[-1]
            filled += [base + gap * k / n for k in range(1, n)]
        filled.append(y)
    ys = filled

    def col_of(x):
        return max((i for i in range(len(xs) - 1) if xs[i] <= x + 1.0), default=0)

    def edge(bounds, v):                             # v'nin ait oldugu sinirin sirasi
        return max((i for i in range(len(bounds)) if bounds[i] <= v + 1e-6), default=0)

    cells = []
    base = _base_size(spans)
    for b, text, lines in cell_defs:
        c0, c1 = edge(xs, b[0]), edge(xs, b[2])
        r0, r1 = edge(ys, b[1]), edge(ys, b[3])
        if c1 > c0 and r1 > r0:
            inside = [sp for ln in lines for sp in ln]
            cells.append(Cell(r0, c0, r1 - r0, c1 - c0, text, bool(inside) and all(sp.is_bold for sp in inside),
                              look=_look(inside, base, b, lines)))
    taken = {}
    for ln in free_lines:
        r = min(edge(ys, min(sp.bbox.y0 for sp in ln)), len(ys) - 2)
        for x, text, bold, group in _pieces(ln):
            key = (r, col_of(x))
            if key in taken:                         # ayni hucreye dusen iki parca: yan yana
                taken[key].text += " " + text
                taken[key].bold = taken[key].bold and bold
            else:
                taken[key] = Cell(r, key[1], 1, 1, text, bold, free=True, look=_look(group, base))
                cells.append(taken[key])
    sheet = TableData(pno, 0, fitz.Rect(pr), len(ys) - 1, len(xs) - 1, cells,
                      [xs[i + 1] - xs[i] for i in range(len(xs) - 1)])
    sheet.row_pt = [ys[i + 1] - ys[i] for i in range(len(ys) - 1)]
    sheet.images = [(min(edge(ys, bb.y0), len(ys) - 2), col_of(bb.x0), data, bb.width, bb.height) for bb, data in pics]
    return sheet


# ---------------------------------------------------------------- sayilar
_TR = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+(,\d+)?$|^[+-]?\d+,\d+$")        # 1.016,74  /  32,2
_EN = re.compile(r"^[+-]?\d{1,3}(,\d{3})+(\.\d+)?$|^[+-]?\d+\.\d+$")        # 1,016.74  /  32.2
_INT = re.compile(r"^[+-]?\d+$")
_AMBIG_TR = re.compile(r"^[+-]?\d{1,3}(\.\d{3})+$")                         # 1.234 : TR'de 1234, EN'de 1,234
_AMBIG_EN = re.compile(r"^[+-]?\d{1,3}(,\d{3})+$")                          # 1,234 : EN'de 1234, TR'de 1,234


def decimal_style(texts):
    """Belgede hangi ondalik bicimi baskin? "tr" (virgul) ya da "en" (nokta)."""
    tr = en = 0
    for t in texts:
        t = t.strip()
        if re.match(r"^[+-]?\d+,\d{1,2}$|^[+-]?\d{1,3}(\.\d{3})+,\d+$", t):
            tr += 1
        elif re.match(r"^[+-]?\d+\.\d{1,2}$|^[+-]?\d{1,3}(,\d{3})+\.\d+$", t):
            en += 1
    return "en" if en > tr else "tr"


def to_number(text, style="tr"):
    """Hucre yazisi sayiysa sayi (int / float), degilse None. Basta sifir olan kodlar
    ("0123"), 15 haneden uzun sayilar ve tarih / saat gibi seyler yazi kalir."""
    t = text.strip().replace("−", "-")
    if not t or "\n" in t or len(t) > 24:
        return None
    digits = re.sub(r"\D", "", t)
    if not digits or len(digits) > 15:
        return None
    if _INT.match(t):
        if len(digits) > 1 and digits[0] == "0":
            return None
        return int(t)
    first, second = (("tr", _TR), ("en", _EN)) if style == "tr" else (("en", _EN), ("tr", _TR))
    for name, rx in (first, second):
        if rx.match(t):
            ambiguous = (_AMBIG_TR if name == "tr" else _AMBIG_EN).match(t)
            if ambiguous and name != style:
                continue
            s = t.replace(".", "").replace(",", ".") if name == "tr" else t.replace(",", "")
            try:
                v = float(s)
            except ValueError:
                return None
            return int(v) if v.is_integer() and "." not in s else v
    return None


# ---------------------------------------------------------------- Excel
LINE_PT = 13.0          # 10 punto yazinin satir yuksekligi (Excel'in varsayilani 12,75)


FREE_WIDEN = 16.0        # serbest yazi sigsin diye sutunlara en cok bu kadar karakter eklenir


def _col_chars(t):
    """Sutun genislikleri (karakter). PDF'teki genislik oranlari korunur, ama PDF'te yazi
    cogu zaman 6-7 puntoyken Excel'de 10 punto: tek sutunluk hucrelerdeki EN UZUN satir
    sigacak kadar genisletilir (yoksa "1716827" kirpilip "17168" gorunur, basliklar
    "ETİKE / T" diye bolunur). Uzun yazilar 40 karakterde kaydirilir."""
    w = [max(4.0, pw / 5.2) for pw in t.col_widths]
    for c in sorted((c for c in t.cells if c.text and not c.free), key=lambda c: c.colspan):
        longest = max(len(ln) for ln in c.text.split("\n")) * c.scale
        if c.colspan == 1:
            w[c.col] = max(w[c.col], min(longest * 1.2 + 2.0, 40.0))
        elif c.rowspan == 1 and longest <= 24:
            # birkac dar sutuna yayilan KISA hucre (sayi, kod): sigmiyorsa eksigi sutunlara dagit
            have = sum(w[c.col:c.col + c.colspan])
            lack = longest * 1.2 + 2.0 - have
            if lack > 0:
                for i in range(c.col, c.col + c.colspan):
                    w[i] += lack / c.colspan
    # serbest yazi (tum sayfa aktariminda tablo disindaki yazilar) saga tasar; ama ayni satirda
    # sagindaki ilk dolu hucre onu KESER ("12.06.2020" + "09:58" -> "12.06.20"). Araya sigmiyorsa
    # aradaki sutunlar az miktarda genisletilir (cok uzun yazi icin tabloyu bozmamak adina yapilmaz).
    taken = {}
    for c in t.cells:
        if c.free:
            if c.text:
                taken.setdefault(c.row, set()).add(c.col)
        else:
            for r in range(c.row, c.row + c.rowspan):
                taken.setdefault(r, set()).update(range(c.col, c.col + c.colspan))
    for c in sorted((c for c in t.cells if c.free and c.text), key=lambda c: (c.row, c.col)):
        nxt = min((k for k in taken.get(c.row, ()) if k > c.col), default=None)
        if nxt is None:
            continue
        lack = len(c.text) * 1.15 * c.scale + 1.0 - sum(w[c.col:nxt])
        if 0 < lack <= FREE_WIDEN:
            for i in range(c.col, nxt):
                w[i] += lack / (nxt - c.col)
    return w


def _row_points(t, w):
    """Satir yukseklikleri (punto): hucredeki satir sayisina (kaydirma dahil) gore."""
    need = [LINE_PT] * t.n_rows                   # (punto; buyuk yazi daha yuksek satir ister)
    spanning = []
    for c in t.cells:
        if not c.text:
            continue
        if c.free:                                # serbest yazi: tek satir, kendi boyutu kadar
            need[c.row] = max(need[c.row], LINE_PT * c.scale)
            continue
        avail = max(1.0, sum(w[c.col:c.col + c.colspan]) - 2.0)
        lines = sum(max(1, math.ceil(len(ln) * 1.15 * c.scale / avail)) for ln in c.text.split("\n"))
        if c.rowspan == 1:
            need[c.row] = max(need[c.row], lines * LINE_PT * c.scale)
        else:
            spanning.append((c, lines * LINE_PT * c.scale))
    for c, points in spanning:                    # cok satira yayilan hucre: eksik kalan son satira
        have = sum(need[c.row:c.row + c.rowspan])
        if points > have:
            need[c.row + c.rowspan - 1] += points - have
    out = [n + 2.0 for n in need]
    base = getattr(t, "row_pt", None)                 # tum sayfa: PDF'teki satir araligindan kisa olmasin
    if base:
        out = [max(o, min(p, 120.0)) for o, p in zip(out, base)]
    return out


def _put(sh, t, top, style, numbers):
    """Tabloyu (ya da tum sayfa modelini) sayfaya, top satirindan baslayarak yaz -> sonraki bos satir."""
    w = _col_chars(t)
    for i, chars in enumerate(w):
        sh.width(i, max(sh.widths.get(i, 0), chars))
    for i, pts in enumerate(_row_points(t, w)):
        sh.height(top + i, pts)
    for c in t.cells:
        look = dict(bold=c.bold, italic=c.italic, size=c.size, color=c.color, font=c.font)
        if c.free:                                 # serbest yazi: kenarliksiz, kaydirmasiz (saga tasar)
            sh.set(top + c.row, c.col, c.text, border=False, **look)
            continue
        v = to_number(c.text, style) if numbers else None
        # hiza PDF'teki yerinden (_look); sayi icin "left" de acikca yazilir (Excel sayiyi saga yaslar)
        align = c.align if (v is not None or c.align != "left") else None
        sh.set(top + c.row, c.col, c.text if v is None else v, align=align, valign=c.valign, **look)
        if c.rowspan > 1 or c.colspan > 1:
            sh.merge(top + c.row, c.col, top + c.row + c.rowspan - 1, c.col + c.colspan - 1)
    for r, c, data, wpt, hpt in getattr(t, "images", ()):
        sh.image(top + r, c, data, wpt, hpt)
    return top + t.n_rows


def write_xlsx(path, tables, single_sheet=False, numbers=True, page_label="Sayfa {p} - Tablo {t}",
               sheet_label="S{p} Tablo {t}", all_label="Tablolar"):
    """YALNIZ TABLOLAR. tables: [TableData]. single_sheet: hepsi tek sayfada alt alta (aralarinda
    baslik satiri); degilse her tablo kendi sekmesinde. numbers: sayilar sayi hucresi olsun.
    Yazilan tablo sayisini dondurur."""
    wb = xlsx_writer.Workbook()
    style = decimal_style([c.text for t in tables for c in t.cells]) if numbers else "tr"
    per_page = {}
    if single_sheet:
        sh, row = wb.sheet(all_label), 0
        for t in tables:
            per_page[t.page] = per_page.get(t.page, 0) + 1
            sh.set(row, 0, page_label.format(p=t.page + 1, t=per_page[t.page]), title=True)
            row = _put(sh, t, row + 1, style, numbers) + 1
    else:
        for t in tables:
            per_page[t.page] = per_page.get(t.page, 0) + 1
            sh = wb.sheet(sheet_label.format(p=t.page + 1, t=per_page[t.page]))
            _put(sh, t, 0, style, numbers)
    wb.save(path)
    return len(tables)


def write_xlsx_pages(path, sheets, numbers=True, sheet_label="Sayfa {p}"):
    """TUM SAYFA. sheets: [page_sheet sonucu]; her PDF sayfasi bir Excel sayfasi (sekme) olur.
    Yazilan sayfa sayisini dondurur."""
    wb = xlsx_writer.Workbook()
    style = decimal_style([c.text for t in sheets for c in t.cells if not c.free]) if numbers else "tr"
    for t in sheets:
        _put(wb.sheet(sheet_label.format(p=t.page + 1)), t, 0, style, numbers)
    wb.save(path)
    return len(sheets)
