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
import safe_write

try:                                       # (find_tables her cagrida konsola oneri yaziyor)
    fitz.no_recommend_layout()
except Exception:
    pass


class Cell:
    __slots__ = ("row", "col", "rowspan", "colspan", "text", "bold", "free",
                 "italic", "size", "color", "font", "align", "valign", "rotation", "border", "shrink")

    def __init__(self, row, col, rowspan, colspan, text, bold, free=False, look=None):
        self.row, self.col, self.rowspan, self.colspan, self.text, self.bold = row, col, rowspan, colspan, text, bold
        # free: cizgisiz bilgi blogundan ayrilmis parca (kenarliksiz, kaydirmasiz; saga tasar)
        self.free = free
        # gorunum (_look): size = Excel'deki punto (None: varsayilan 10), color = 0xRRGGBB (None: siyah),
        # font = yazi tipi ailesi (None: varsayilan), align / valign = hucre icindeki hiza
        self.italic, self.size, self.color, self.font, self.align, self.valign = False, None, None, None, None, None
        # (PDF duzeni kipi) rotation: dikey yazi (90 = asagidan yukari, -90 = yukaridan asagi); border: kenarlik
        # shrink: serbest yazi yerine siki oturuyor; hucresi genisletildi, sigmazsa Excel kucultur
        self.rotation, self.border, self.shrink = None, not free, False
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
        self.page_size = None          # kaynak sayfanin olcusu (en, boy; punto): Excel'de baski kagidi

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


def _real_cells(boxes):
    """Baska hucreleri ICINE ALAN kutu hucre degildir, atilir. Sayfada isaretleme (not kutusu,
    numara rozeti) varken find_tables butun tabloyu kaplayan bir "hucre" daha uretiyor; onun
    yazilari hem kendi hucrelerinde hem de serbest yazi olarak IKI KEZ aktariliyordu."""
    def area(b):
        return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])

    def holds(b, o):
        return (o is not b and b[0] - 1 <= o[0] and b[1] - 1 <= o[1] and o[2] <= b[2] + 1 and o[3] <= b[3] + 1
                and area(o) < area(b) * 0.9)
    return [b for b in boxes if not any(holds(b, o) for o in boxes)]


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


def _look(spans, base, box=None, lines=None, exact=False):
    """Yazilarin gorunumu -> Cell alanlari. PDF'te "ortala" diye bir bilgi YOKTUR; hiza, yazinin
    kutu icindeki yerinden cikarilir (box + lines verilirse).
    exact (PDF duzeni kipi): yazi boyutu govdeye oranlanmaz, PDF'teki punto AYNEN alinir."""
    out = {}
    if not spans:
        return out

    def top(key):                                  # harf sayisina gore baskin deger
        count = {}
        for sp in spans:
            count[key(sp)] = count.get(key(sp), 0) + max(1, len(sp.text.strip()))
        return max(count, key=count.get)

    ratio = top(lambda sp: round(sp.size * 2) / 2) / max(base, 1.0)
    if exact:
        out["size"] = float(max(1.0, top(lambda sp: round(sp.size * 2) / 2)))
    elif not 0.8 <= ratio <= 1.25:                 # govdeye yakin boyutlar tek boyut (6 / 7 punto karisimi)
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
        elif all(b < a * 0.6 for a, b in zip(left, right)) and max(right) - min(right) <= tol:
            # sag bosluk soldakinden belirgin kucuk ve satirlarin SAG kenari ayni hizada.
            # (Sag boslugun "kucuk" olmasi sart degil: faturalarda sayilar hucrenin sagina 8 pt
            # ic boslukla yaslanir; eski "3 pt'tan az" kurali bunlari SOLA yasliyordu.)
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
        boxes = _real_cells([c for c in t.cells if c])
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
        out[-1].page_size = (page.rect.width, page.rect.height)
    return out


# ---------------------------------------------------------------- tum sayfa
FILL_GAP = 26.0          # bu kadar puntodan uzun bos dikey aralik, ~14 punto araliklarla satirlara bolunur


def _pieces(line, keep_colon=False):
    """Bir yazi satirini, aralarinda belirgin bosluk olan parcalara ayir -> [(x0, yazi, kalin, yazilar)].
    Bastaki ":" atilir (etiket / deger yan yana hucrelere duser); keep_colon: atilmaz (PDF duzeni
    kipi gorunen hicbir seyi atmaz)."""
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
        if text.startswith(":") and not keep_colon:
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
        boxes = _real_cells([c for c in t.cells if c])
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
    sheet.images = []
    for bb, data in pics:                            # (satir, sutun, resim, gen, yuk, hucre icindeki yer 0-1)
        r, c = min(edge(ys, bb.y0), len(ys) - 2), col_of(bb.x0)
        fx = max(0.0, min((bb.x0 - xs[c]) / max(xs[c + 1] - xs[c], 1.0), 0.98))
        fy = max(0.0, min((bb.y0 - ys[r]) / max(ys[r + 1] - ys[r], 1.0), 0.98))
        sheet.images.append((r, c, data, bb.width, bb.height, fx, fy))
    sheet.page_size = (pr.width, pr.height)
    return sheet


# ---------------------------------------------------------------- PDF duzenini koru
# Tum sayfa aktariminin ikinci kipi (page_layout + _put_layout). Eski kip (page_sheet + _put) okunur
# olsun diye yaziyi 10 puntoya buyutur, sutunlari metne gore genisletir; resimler ise PDF'teki
# boyutunda kaldigi icin tabloya gore kuculur, sayfa oranlari bozulur, baski ayari da yoktur.
# Bu kipte olcu birimi PDF'in kendisidir:
#   - izgaranin sutun / satir sinirlari PDF PUNTOSU olarak tutulur ve Excel'e BASKIDA o olcuyu
#     verecek sekilde yazilir (karakter sayisindan tahmin edilmez). Excel %100 olcekte bile ekrandaki
#     olcuyle basmaz: sutun x 0,96, satir x 1,0245 (xlsx_writer.PRINT_X / PRINT_Y; gercek Excel'le
#     uc yazicida olculdu). Bu yuzden ekranda sayfa %4 genis, %2,4 kisa gorunur; BASKI dogrudur;
#   - yuksekligi olan HER satir yazilir (bos satirlar dahil; yoksa Excel onlara 15 punto verir);
#   - yazi PDF'teki boyutunda kalir; tek satirlik hucreler "sigdir" isaretlidir (Excel'in hucre ic
#     boslugu yuzunden sigmayan sayi "####" gorunmesin, yazi kirpilmasin). Cok satirli hucrede Excel
#     satirlari PDF'ten seyrek dizer: sigmiyorsa yazi boyu sigana kadar dusurulur (_fit_size);
#   - serbest yazi yerini neredeyse dolduruyorsa (tam genislikte paragraf satiri, bitisik etiket)
#     sagindaki bos sutunlarla birlestirilir + "sigdir": Excel'deki yazi tipi biraz genisse kesilmez;
#   - yeri dolu bir hucreye dusen yazi ATILMAZ, o hucrenin yazisina eklenir; bastaki ":" de atilmaz;
#   - resimler iki kosesinden hucrelere baglidir (twoCellAnchor): hucrelerle ayni olcekte basilir;
#   - kagit boyutu, yon, sol / ust kenar boslugu (icerigin sayfadaki yeri) ve yazdirma alani yazilir;
#     olcek %100'dur. Icerik yazicinin basamadigi kenara (5 mm) giriyorsa sutunlar / satirlar o kadar
#     (binde birkac) daraltilir - yoksa Excel ikinci sayfa acar. Sag / alt bosluk kucuk tutulur
#     (Excel'in A4 <-> Letter eslemesi kagidi degistirince icerik tasmasin);
#   - DIKEY yazi (90 derece: tablo yan basligi) hucreye dondurulmus yazi olarak aktarilir;
#   - EGIK yazi (filigran) hucreye sigmaz: aktarilmaz, AMA sessizce de kaybolmaz - metni
#     sheet.skipped'e yazilir, pencere kullaniciya soyler.
VERT_TOL = 2.0           # tam dikeyden bu kadar derece sapan yazi hala "dikey" sayilir
SNAP_LEFT = 3.0          # serbest yazi, solundaki sutun sinirina bu kadar yakinsa ona oturur (yeni sutun acilmaz)
PRINT_SLACK = 2.0        # yuvarlama payi (punto): icerik sayfanin disina tasip ikinci sayfa acmasin
TIGHT = 0.88             # serbest yazi, sagindaki bos yerin bu kadarini dolduruyorsa "siki" sayilir
PRINT_EDGE = 15.7        # yazicilarin basamadigi kenar (5 mm) + pay: icerik buraya girerse Excel ikinci sayfa acar


def _line_pt(size):
    """Excel'de (baskida) kaydirilmis yazinin bir satirinin yuksekligi, punto. Olculdu: 7 punto ->
    9,2; 7,5 punto -> 9,8. Yazi yuksekligi tam piksele yuvarlanir, bir piksel de aralik eklenir;
    kucuk yazida oran 1,3'u bulur (PDF'te satirlar cogu kez yazi boyundan bile sikidir)."""
    px = xlsx_writer.PX_PT
    return (math.ceil(1.15 * size / px - 1e-6) + 1) * px * xlsx_writer.PRINT_Y


def _fit_size(size, lines, room):
    """`lines` satir, `room` puntoluk hucreye sigan en buyuk yazi boyu (yarim punto adimla; en az 4)."""
    s = math.floor(size * 2 + 1e-6) / 2.0
    while s > 4.0 and lines * _line_pt(s) > room:
        s -= 0.5
    return min(size, s)


def split_rotated(engine, pno):
    """Gorunen yazilar -> (duz, dikey, aktarilmayan). Dikey: saga / sola TAM 90 derece donmus, opak
    yazi (tablo yan basligi, kenar notu). Aktarilmayan: egik ya da yari saydam donuk yazi (filigran)
    ve bas asagi (180 derece) yazi - Excel hucresinde karsiligi yok."""
    flat, vert, skipped = [], [], []
    for sp in engine.visible_spans(pno):
        if not sp.rotated:
            flat.append(sp)
            continue
        angle = math.degrees(math.atan2(sp.direction[1], sp.direction[0]))
        if abs(abs(angle) - 90.0) <= VERT_TOL and getattr(sp, "opacity", 1.0) >= 0.5:
            vert.append(sp)
        else:
            skipped.append(sp)
    return flat, vert, skipped


def _vertical(spans):
    """Dikey yazi parcalari -> (metin, aci). Asagidan yukari okunan yazida (aci 90) satirlar soldan
    saga dizilir; yukaridan asagi okunanda (aci -90) sagdan sola."""
    up = sum(1 for sp in spans if sp.direction[1] < 0) * 2 >= len(spans)
    cols = []
    for sp in sorted(spans, key=lambda s_: s_.origin[0]):
        if cols and abs(sp.origin[0] - cols[-1][0].origin[0]) <= max(1.5, sp.size * 0.45):
            cols[-1].append(sp)
        else:
            cols.append([sp])
    if not up:
        cols.reverse()
    lines = []
    for col in cols:
        col.sort(key=lambda s_: -s_.origin[1] if up else s_.origin[1])
        lines.append(" ".join(" ".join(_clean(sp.text).split()) for sp in col))
    return "\n".join(t for t in lines if t), (90 if up else -90)


def _vertical_groups(spans):
    """Tablo disindaki dikey yazilari yan yana duran satirlarina gore grupla -> [[Span, ...]]."""
    groups = []
    for sp in sorted(spans, key=lambda s_: (s_.bbox.x0, s_.bbox.y0)):
        for g in groups:
            last = g[-1]
            if (sp.bbox.x0 - last.bbox.x1 <= sp.size * 1.2 and sp.bbox.y0 < max(x.bbox.y1 for x in g)
                    and sp.bbox.y1 > min(x.bbox.y0 for x in g)):
                g.append(sp)
                break
        else:
            groups.append([sp])
    return groups


def page_layout(engine, pno, images=True, text_fallback=False):
    """SAYFANIN TAMAMI, PDF'TEKI OLCULERIYLE (bkz. yukaridaki not) -> TableData | None (bos sayfa).
    Ek alanlar: layout = {"xs", "ys" (izgara sinirlari, PDF puntosu), "page" (gen, yuk)},
    pictures = [(kutu, resim baytlari)], skipped = aktarilmayan egik yazilarin metinleri."""
    page = engine.doc[pno]
    pr = page.rect
    flat, vert, skipped = split_rotated(engine, pno)
    try:
        found = list(page.find_tables().tables)
        if not found and text_fallback:
            found = list(page.find_tables(strategy="text").tables)
    except Exception:
        found = []
    used, defs, free_lines = set(), [], []           # defs: (kutu, yazi, satirlar, yazilar, aci, kenarlik)
    for t in found:
        boxes = _real_cells([c for c in t.cells if c])
        if not boxes:
            continue
        txs = _bounds([b[0] for b in boxes] + [b[2] for b in boxes])
        for b in boxes:
            lines = _cell_lines(flat, b)
            for ln in lines:
                used.update(id(sp) for sp in ln)
            full = len(txs) > 3 and abs(b[0] - txs[0]) < 2 and abs(b[2] - txs[-1]) < 2
            if full and len(lines) >= 3 and any(len(_pieces(ln)) > 1 for ln in lines):
                free_lines += lines                  # cizgisiz bilgi blogu: satir satir serbest yazi
                continue
            inside = [sp for ln in lines for sp in ln]
            turned = [sp for sp in vert if id(sp) not in used
                      and b[0] - 0.5 <= (sp.bbox.x0 + sp.bbox.x1) / 2 <= b[2] + 0.5
                      and b[1] - 0.5 <= (sp.bbox.y0 + sp.bbox.y1) / 2 <= b[3] + 0.5]
            if turned and not inside:                # dikey baslik hucresi
                used.update(id(sp) for sp in turned)
                text, angle = _vertical(turned)
                defs.append((b, text, None, turned, angle, True))
                continue
            text = "\n".join(t_ for t_ in (_join(ln) for ln in lines) if t_)
            defs.append((b, text, lines, inside, None, True))
    free_lines += _cell_lines([sp for sp in flat if id(sp) not in used], (-1e6, -1e6, 1e6, 1e6))
    for g in _vertical_groups([sp for sp in vert if id(sp) not in used]):     # tablo disindaki dikey yazi
        text, angle = _vertical(g)
        box = (min(sp.bbox.x0 for sp in g), min(sp.bbox.y0 for sp in g),
               max(sp.bbox.x1 for sp in g), max(sp.bbox.y1 for sp in g))
        defs.append((box, text, None, g, angle, False))
    pics = []
    if images:
        for it in engine._pickable_images(pno):
            data = _picture(engine.doc, it.xref, it.bbox.width, it.bbox.height)
            if data:
                pics.append((fitz.Rect(it.bbox), data))
    if not defs and not free_lines and not pics:
        return None
    pieces = [(ln, _pieces(ln, keep_colon=True)) for ln in free_lines]
    pieces = [(ln, ps) for ln, ps in pieces if ps]

    # ---- sutun sinirlari (PDF puntosu): hucre kenarlari + serbest yazilarin sol kenarlari
    xs = _bounds([d[0][0] for d in defs] + [d[0][2] for d in defs], 2.0)
    for x in sorted([p_[0] for _, ps in pieces for p_ in ps]):
        if not any(-1.0 <= x - b <= SNAP_LEFT for b in xs):
            xs.append(x)
            xs.sort()
    right = max([d[0][2] for d in defs] + [bb.x1 for bb, _ in pics]
                + [max(sp.bbox.x1 for sp in ln) for ln, _ in pieces] + [xs[-1] if xs else 0.0])
    left = min([xs[0] if xs else right] + [bb.x0 for bb, _ in pics])
    if not xs or left < xs[0] - 1.0:
        xs.insert(0, max(0.0, left))
    if right > xs[-1] + 1.0:
        xs.append(right)
    if len(xs) < 2:
        xs.append(xs[0] + 40.0)
    # ---- satir sinirlari
    tops = [d[0][1] for d in defs] + [d[0][3] for d in defs]
    tops += [min(sp.bbox.y0 for sp in ln) for ln, _ in pieces]
    tops += [bb.y0 for bb, _ in pics]
    last = max([d[0][3] for d in defs] + [max(sp.bbox.y1 for sp in ln) for ln, _ in pieces]
               + [bb.y1 for bb, _ in pics])
    ys = _bounds(tops, 2.5)
    if not ys or last - ys[-1] > 2.5:
        ys.append(last)
    if len(ys) < 2:
        ys.append(ys[0] + 12.0)
    filled = [ys[0]]
    for y in ys[1:]:
        gap = y - filled[-1]
        if gap > FILL_GAP:                           # uzun bosluk: ara satirlar (Excel satiri en cok 409 punto)
            n = int(round(gap / 14.0))
            start = filled[-1]
            filled += [start + gap * k / n for k in range(1, n)]
        filled.append(y)
    ys = filled

    def at_or_before(bounds, v, slack):              # v'nin ait oldugu sinirin sirasi
        return max((i for i in range(len(bounds) - 1) if bounds[i] <= v + slack), default=0)

    cells, taken, bottoms, rights = [], set(), {}, {}
    base = _base_size(flat)
    for b, text, lines, inside, angle, border in defs:
        c0, c1 = _index(xs, b[0], 2.0), _index(xs, b[2], 2.0)
        r0, r1 = _index(ys, b[1], 2.5), _index(ys, b[3], 2.5)
        if c1 <= c0 or r1 <= r0:
            continue
        look = _look(inside, base, b, lines, exact=True)
        cell = Cell(r0, c0, r1 - r0, c1 - c0, text, bool(inside) and all(sp.is_bold for sp in inside), look=look)
        cell.border = border
        if angle:
            cell.rotation, cell.align, cell.valign = angle, "center", "center"
        cells.append(cell)
        taken.update((r, c) for r in range(r0, r1) for c in range(c0, c1))
    n_rows, n_cols = len(ys) - 1, len(xs) - 1
    for ln, ps in pieces:
        y0, y1 = min(sp.bbox.y0 for sp in ln), max(sp.bbox.y1 for sp in ln)
        r = at_or_before(ys, y0, 2.5)
        # satir, yazinin boyundan kisaysa (yan yana duran, birkac punto kayik satirlar) hucre alttaki
        # bos satirlarla birlestirilir: Excel yaziyi satir yuksekligine kirpar
        span = 1
        while r + span < n_rows and ys[r + span] < y1 - 0.75:
            span += 1
        for x, text, bold, group in ps:
            c = at_or_before(xs, x, 1.0)
            rs, cs = span, 1
            if rs > 1:                               # birlesik hucre saga TASMAZ: yazinin genisligini de kaplasin
                x1 = max(sp.bbox.x1 for sp in group)
                while c + cs < n_cols and xs[c + cs] < x1 + 1.0:
                    cs += 1
                if any((rr, cc) in taken for rr in range(r, r + rs) for cc in range(c, c + cs)):
                    rs, cs = 1, 1
            if (r, c) in taken:                      # yeri dolu: o hucrenin yazisina eklenir (ATILMAZ)
                prev = next((k for k in cells if k.row <= r < k.row + k.rowspan
                             and k.col <= c < k.col + k.colspan), None)
                if prev is not None:
                    below = (y0 + y1) / 2 >= bottoms.get(id(prev), y1) - 1.0     # alt satir mi, ayni satirin devami mi
                    prev.text += ("\n" if below else " ") + text
                    prev.bold = prev.bold and bold
                    bottoms[id(prev)] = max(bottoms.get(id(prev), y1), y1)
                    if id(prev) in rights:
                        rights[id(prev)] = max(rights[id(prev)], max(sp.bbox.x1 for sp in group))
                    while (prev.free and prev.row + prev.rowspan < n_rows and ys[prev.row + prev.rowspan] < y1 - 0.75
                           and not any((prev.row + prev.rowspan, cc) in taken
                                       for cc in range(prev.col, prev.col + prev.colspan))):
                        taken.update((prev.row + prev.rowspan, cc) for cc in range(prev.col, prev.col + prev.colspan))
                        prev.rowspan += 1
                continue
            cell = Cell(r, c, rs, cs, text, bold, free=True, look=_look(group, base, exact=True))
            cells.append(cell)
            bottoms[id(cell)] = y1
            rights[id(cell)] = max(sp.bbox.x1 for sp in group)
            taken.update((rr, cc) for rr in range(r, r + rs) for cc in range(c, c + cs))
    # Serbest yazi Excel'de saga, ilk dolu hucreye (ya da sayfanin kenarina) kadar tasar; otesi KESILIR.
    # Excel'deki yazi tipi PDF'tekinden biraz genisse, yerini PDF'te neredeyse dolduran yazi (tam
    # genislikte paragraf satiri, bitisik etiket) kesilir. Boyle yazinin hucresi sagdaki bos sutunlarla
    # birlestirilir ve "sigdir" isaretlenir: sigmazsa Excel kendisi kucultur.
    for cell in cells:
        if not cell.free or "\n" in cell.text or id(cell) not in rights:
            continue
        rows_ = range(cell.row, cell.row + cell.rowspan)
        end = cell.col + cell.colspan
        while end < n_cols and not any((rr, end) in taken for rr in rows_):
            end += 1
        if rights[id(cell)] - xs[cell.col] + 4.0 > (xs[end] - xs[cell.col]) * TIGHT:
            taken.update((rr, cc) for rr in rows_ for cc in range(cell.col, end))
            cell.colspan, cell.shrink = end - cell.col, True
    sheet = TableData(pno, 0, fitz.Rect(pr), n_rows, n_cols, cells, [xs[i + 1] - xs[i] for i in range(n_cols)])
    sheet.layout = {"xs": xs, "ys": ys, "page": (pr.width, pr.height)}
    sheet.pictures = pics
    seen, sheet.skipped = set(), []
    for sp in skipped:                               # (filigran her sayfada / iki satir: bir kez yazilsin)
        t_ = " ".join(_clean(sp.text).split())
        if t_ and t_ not in seen:
            seen.add(t_)
            sheet.skipped.append(t_)
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
    rows = _row_points(t, w)
    for i, pts in enumerate(rows):
        sh.height(top + i, pts)
    for c in t.cells:
        look = dict(bold=c.bold, italic=c.italic, size=c.size, color=c.color, font=c.font)
        if c.free:                                 # serbest yazi: kenarliksiz, kaydirmasiz (saga tasar)
            sh.set(top + c.row, c.col, c.text, border=False, **look)
            continue
        v = to_number(c.text, style) if numbers else None
        # hiza PDF'teki yerinden (_look); sayi icin "left" de acikca yazilir (Excel sayiyi saga yaslar)
        align = c.align if (v is not None or c.align != "left") else None
        # sayi PDF'teki gibi gorunsun: "1.016,74" -> 1.016,74 (bicimsiz "1016,74" gorunuyordu; gercek
        # Excel 2024 ile karsilastirildi, 2026-10-15)
        sh.set(top + c.row, c.col, c.text if v is None else v, align=align, valign=c.valign,
               numfmt=number_format(c.text, style) if v is not None else None, **look)
        if c.rowspan > 1 or c.colspan > 1:
            sh.merge(top + c.row, c.col, top + c.row + c.rowspan - 1, c.col + c.colspan - 1)
    for r, c, data, wpt, hpt, fx, fy in getattr(t, "images", ()):
        # resim hucrenin sol-ustune degil, PDF'te hucre icinde durdugu ORANA yerlestirilir
        # (genis bir sutunun sagindaki kase sola yapisiyor, yazinin ustune biniyordu)
        sh.image(top + r, c, data, wpt, hpt, dx_pt=fx * xlsx_writer.col_points(sh.widths.get(c, w[c])),
                 dy_pt=fy * rows[r])
    return top + t.n_rows


def number_format(text, style="tr"):
    """Sayiya cevrilen yazinin GORUNUMUNU koruyan Excel bicimi ("1.016,74" -> "#,##0.00", "2,360" ->
    "0.000") | None (tam sayi: bicim gerekmez). Bicimde ayraclar hep "," (binlik) ve "." (ondalik)
    yazilir; Excel kullanicinin bolge ayarina gore gosterir."""
    t = text.strip().replace("−", "-").lstrip("+-")
    first, second = (("tr", _TR), ("en", _EN)) if style == "tr" else (("en", _EN), ("tr", _TR))
    for name, rx in (first, second):
        if rx.match(t):
            if (_AMBIG_TR if name == "tr" else _AMBIG_EN).match(t) and name != style:
                continue
            dec, grp = (",", ".") if name == "tr" else (".", ",")
            decimals = len(t.rsplit(dec, 1)[1]) if dec in t else 0
            head = "#,##0" if grp in t else "0"
            return head + ("." + "0" * decimals if decimals else "") if (decimals or grp in t) else None
    return None


def _steps(bounds, unit):
    """Sinirlar (punto) -> birimin tam katlarindaki konumlar (kumulatif yuvarlama: toplam kaymaz;
    her aralik en az bir birim)."""
    out = [0]
    for b in bounds[1:]:
        out.append(max(out[-1] + 1, int(round((b - bounds[0]) / unit))))
    return out


def _put_layout(sh, t, style, numbers):
    """page_layout modelini PDF'teki olculeriyle yaz: sutun / satir olculeri, yazi boyutlari, resim
    yerleri ve baski ayarlari (bkz. "PDF duzenini koru" notu)."""
    xs, ys = t.layout["xs"], t.layout["ys"]
    px = xlsx_writer.PX_PT
    ux, uy = px * xlsx_writer.PRINT_X, px * xlsx_writer.PRINT_Y   # bir pikselin BASKIDAKI olcusu (punto)
    # ---- kagit ve icerigin sayfadaki yeri
    w, h = t.layout["page"]
    name, code, landscape, exact = xlsx_writer.paper_for(w, h)
    if not exact:                                     # standart olmayan sayfa: kagidin kendi olculeri
        pw, ph = next((pp[2], pp[3]) for pp in xlsx_writer.PAPERS if pp[1] == code)
        w, h = (ph, pw) if landscape else (pw, ph)
    left, top = max(0.0, xs[0]), max(0.0, ys[0])
    # Icerik yazicinin basamadigi kenara giriyorsa Excel ikinci sayfa acar: sutunlar / satirlar o kadar
    # (binde birkac) daraltilir. Belirgin sigmiyorsa (kagit sayfadan kucuk) tek sayfaya sigdirilir.
    kx = min(1.0, (w - max(left, PRINT_EDGE) - PRINT_EDGE) / max(1.0, xs[-1] - xs[0]))
    ky = min(1.0, (h - max(top, PRINT_EDGE) - PRINT_EDGE) / max(1.0, ys[-1] - ys[0]))
    fit = min(kx, ky) < 0.9
    if fit:
        kx = ky = 1.0
        left = top = 0.0
    X, Y = _steps(xs, ux / kx), _steps(ys, uy / ky)   # piksel konumlari

    def place(v, bounds, steps):
        """PDF konumu -> (aralik no, araligin basindan EKRAN puntosu olarak kayma). Kayma baskida
        hucreyle birlikte olceklenir (olculdu): araligin icindeki ORAN korunur. Aralik sonuna tam
        oturan uc bir piksel iceride tutulur (resim bir sonraki sutuna / satira tasmis sayilmasin)."""
        i = max((k for k in range(len(bounds) - 1) if bounds[k] <= v + 0.01), default=0)
        size = (steps[i + 1] - steps[i]) * px
        part = (v - bounds[i]) / max(0.01, bounds[i + 1] - bounds[i])
        return i, max(0.0, min(part * size, size - px))

    for i in range(t.n_cols):
        sh.width_px(i, X[i + 1] - X[i])
    for i in range(t.n_rows):
        sh.height_exact(i, (Y[i + 1] - Y[i]) * px)
    for c in t.cells:
        look = dict(bold=c.bold, italic=c.italic, size=c.size, color=c.color, font=c.font)
        if c.free and "\n" not in c.text:             # serbest yazi: kenarliksiz, ustte, saga tasar
            sh.set(c.row, c.col, c.text, border=False, valign="top", shrink=c.shrink, **look)
        elif c.free:                                  # (ust uste dusen serbest satirlar: bkz. page_layout)
            sh.set(c.row, c.col, c.text, border=False, valign="top", wrap=True, **look)
        else:
            multi = "\n" in c.text or bool(c.rotation)
            if multi and not c.rotation and c.size:   # Excel satirlari PDF'ten seyrek dizer: sigmazsa yazi kirpilir
                look["size"] = _fit_size(c.size, c.text.count("\n") + 1, (Y[c.row + c.rowspan] - Y[c.row]) * uy)
            v = to_number(c.text, style) if (numbers and not multi) else None
            sh.set(c.row, c.col, c.text if v is None else v, border=c.border, align=c.align or "left",
                   valign=c.valign or "center", wrap=multi, shrink=not multi, rotation=c.rotation,
                   numfmt=number_format(c.text, style) if v is not None else None, **look)
        if c.rowspan > 1 or c.colspan > 1:
            sh.merge(c.row, c.col, c.row + c.rowspan - 1, c.col + c.colspan - 1)
    for bb, data in t.pictures:                       # resim: iki kosesinden hucrelere bagli (ayni olcek)
        (c, dx), (r, dy) = place(bb.x0, xs, X), place(bb.y0, ys, Y)
        (c1, dx1), (r1, dy1) = place(bb.x1, xs, X), place(bb.y1, ys, Y)
        sh.image(r, c, data, bb.width, bb.height, dx_pt=dx, dy_pt=dy, end=(r1, c1, dx1, dy1))
    # ---- baski: kagit, yon, icerigin sayfadaki yeri (kenar bosluklari), yazdirma alani
    cw, ch = X[-1] * ux, Y[-1] * uy                   # icerigin BASKIDAKI olcusu
    # Icerigin yerini SOL / UST bosluk ve hucre olculeri belirler. Sag / alt bosluk yalniz "buradan
    # otesi basilmaz" der: genis tutulursa, Excel kagidi kendisi degistirdiginde (A4 <-> Letter
    # eslemesi; bolge ayarina gore varsayilan ACIK) icerik sigmaz ve ikinci sayfa acilir.
    sh.page = {"paper": code, "landscape": landscape, "left": left, "top": top,
               "right": min(PRINT_EDGE, w - left - cw - PRINT_SLACK),
               "bottom": min(PRINT_EDGE, h - top - ch - PRINT_SLACK),
               "area": (0, 0, t.n_rows - 1, t.n_cols - 1), "fit": fit}
    sh.grid = False
    sh.all_rows = True
    t.paper = (name, exact, fit)


EXCEL_MARGINS = (50.4, 50.4, 54.0, 54.0)   # Excel'in olagan kenar bosluklari (sol, sag, ust, alt; punto)


def _print_to_width(sh, page_size, landscape_page=None, one_page=False):
    """Okunakli yerlesim / Yalnizca tablolar: baskida BUTUN SUTUNLAR bir sayfa genisligine sigar, boyu
    gerektigi kadar sayfaya akar. Ayar yokken Excel tek PDF sayfasini 4-8 sayfaya, tabloyu ortadan
    bolerek basiyordu (gercek Excel 2024 ile olculdu, 2026-10-15). Kagit kaynak PDF'inki; yon kaynak
    sayfaninki, tablo kagidin dikey genisligine ancak cok kuculerek sigiyorsa yatay.
    one_page (okunakli yerlesim: bir sekme = bir PDF sayfasi; ayri sekmedeki tek tablo): sayfa boyu da sigar - Excel'in satirlari
    PDF'teki satirlardan biraz yuksek, sekme kagidi %10-20 tasip ikinci sayfaya bir iki satir
    birakiyordu. Boyuna sigdirmak yazilari eninkinden belirgin kucultecekse yalniz ene sigdirilir."""
    w, h = page_size or (595.28, 841.89)
    _name, code, landscape, _exact = xlsx_writer.paper_for(w, h)
    pw, ph = next((pp[2], pp[3]) for pp in xlsx_writer.PAPERS if pp[1] == code)   # (dikey olculer)
    left, right, top, bottom = EXCEL_MARGINS
    # Excel'in sutun genisligi birimiyle (bkz. xlsx_writer.width_for_px) icerigin eni, punto
    content = sum(int((256 * sh.widths[c] + 18) / 256 * 7) * 0.75 for c in sh.widths)
    if landscape_page is not None:
        landscape = landscape_page
    elif not landscape and content > (pw - left - right) * 1.25:
        landscape = True                          # (genis tablo: dikeyde cok kuculurdu)
    fit = "width"
    if one_page:
        if landscape:
            pw, ph = ph, pw
        rows = max(sh.heights, default=-1) + 1
        tall = sum(sh.heights.get(r, 15.0) for r in range(rows))
        by_w = min(1.0, (pw - left - right) / max(content, 1.0))
        by_h = (ph - top - bottom) / max(tall, 1.0)
        if by_h >= 0.75 * by_w:
            fit = True
    sh.page = {"paper": code, "landscape": landscape, "left": left, "right": right, "top": top,
               "bottom": bottom, "fit": fit}


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
        _print_to_width(sh, tables[0].page_size if tables else None)
    else:
        for t in tables:
            per_page[t.page] = per_page.get(t.page, 0) + 1
            sh = wb.sheet(sheet_label.format(p=t.page + 1, t=per_page[t.page]))
            _put(sh, t, 0, style, numbers)
            _print_to_width(sh, t.page_size, one_page=True)
    with safe_write.Writer() as w:         # gecici dosyaya; yarida kalirsa var olan dosya bozulmaz
        wb.save(w.path(path))
    return len(tables)


def write_xlsx_pages(path, sheets, numbers=True, sheet_label="Sayfa {p}"):
    """TUM SAYFA. sheets: [page_sheet sonucu]; her PDF sayfasi bir Excel sayfasi (sekme) olur.
    Yazilan sayfa sayisini dondurur."""
    wb = xlsx_writer.Workbook()
    style = decimal_style([c.text for t in sheets for c in t.cells if not c.free]) if numbers else "tr"
    for t in sheets:
        if getattr(t, "layout", None):               # "PDF duzenini koru" (page_layout)
            _put_layout(wb.sheet(sheet_label.format(p=t.page + 1)), t, style, numbers)
        else:
            sh = wb.sheet(sheet_label.format(p=t.page + 1))
            _put(sh, t, 0, style, numbers)
            ps = t.page_size
            _print_to_width(sh, ps, landscape_page=(ps[0] > ps[1] + 0.5) if ps else None, one_page=True)
    with safe_write.Writer() as w:         # gecici dosyaya; yarida kalirsa var olan dosya bozulmaz
        wb.save(w.path(path))
    return len(sheets)
