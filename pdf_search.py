"""
pdf_search.py
-------------
Belgede yazi arama ve degistirme (Bul / Degistir cubugunun motoru).

- Arama motorun yazi listesinde (Span) yapilir, PyMuPDF'in search_for'unda DEGIL: bulunan
  yerin hangi yazi parcasinin hangi harfleri oldugu bilinmeli ki degistirilebilsin.
- Yalniz sayfada GORUNEN yazilar aranir (kirpilmis / sayfa disinda kalanlar haric).
- Ayni satirdaki bitisik parcalar birlestirilerek aranir: kalin etiket + duz deger gibi iki
  parcaya bolunmus ifade de bulunur. Boyle bir eslesme gosterilir ama DEGISTIRILEMEZ
  (Match.replaceable False): parcalarin her biri ayri yazi nesnesi, yerleri ayri.
- Buyuk / kucuk harf ayrimi kapaliyken Turkce I / ı / İ / i tek harf sayilir
  ("sinif", "SINIF" ve "SİNİF" birbirini bulur).
"""
import fitz

_DASHES = "­‐‑"         # yumusak tire, tire, bolunmez tire: klavyedeki "-" ile bulunsun
_SPACES = "               　\t"


def fold(text, case=False):
    """Karsilastirma bicimi. AYNI UZUNLUKTA dizi doner (harf sirasi = indeks; kaymaz)."""
    out = []
    for ch in text:
        if ch in _SPACES:
            out.append(" ")
        elif ch in _DASHES:
            out.append("-")
        elif case:
            out.append(ch)
        elif ch in "Iİıi":
            out.append("i")
        else:
            low = ch.lower()
            out.append(low if len(low) == 1 else ch)
    return "".join(out)


class Line:
    """Ayni satirda yan yana duran yazi parcalari, tek dizi olarak."""
    __slots__ = ("page", "text", "low", "parts")

    def __init__(self, page, text, parts):
        self.page = page
        self.text = fold(text, True)          # harf ayrimli arama icin
        self.low = fold(text, False)          # ayrimsiz arama icin
        self.parts = parts                    # [(Span, satirdaki baslangic indeksi)]


class Match:
    __slots__ = ("page", "line", "start", "end", "segs", "_quads")

    def __init__(self, page, line, start, end, segs):
        self.page, self.line, self.start, self.end = page, line, start, end
        self.segs = segs                      # [(Span, a, b)]: span.text[a:b]
        self._quads = None

    @property
    def replaceable(self):
        return len(self.segs) == 1

    @property
    def key(self):
        """Belgedeki sirasi (sayfa, satir, satir icindeki yer)."""
        return (self.page, self.line, self.start)


def page_lines(engine, pno):
    """Sayfanin gorunen yazilari -> [Line] (yukaridan asagi, soldan saga)."""
    spans = engine.visible_spans(pno)
    flat = sorted((s for s in spans if not s.rotated), key=lambda s: (s.origin[1], s.origin[0]))
    rows, cur, base = [], [], None
    for sp in flat:
        if cur and abs(sp.origin[1] - base) > max(1.5, sp.size * 0.45):
            rows.append(cur)
            cur = []
        if not cur:
            base = sp.origin[1]
        cur.append(sp)
    if cur:
        rows.append(cur)
    groups = []
    for row in rows:
        row.sort(key=lambda s: s.origin[0])
        g = [row[0]]
        for sp in row[1:]:
            # aralarinda belirgin bosluk olan parcalar ayri sutundur: ifade bir sutunun sonuyla
            # yandaki sutunun basini birlestirerek "bulunmasin"
            if sp.bbox.x0 - g[-1].bbox.x1 > max(6.0, sp.size * 1.5):
                groups.append(g)
                g = [sp]
            else:
                g.append(sp)
        groups.append(g)
    groups += [[s] for s in spans if s.rotated]           # egik yazi (filigran): tek basina
    lines = []
    for g in groups:
        text, parts = "", []
        for i, sp in enumerate(g):
            t = sp.text
            if (i and sp.bbox.x0 - g[i - 1].bbox.x1 > sp.size * 0.2
                    and not text.endswith(" ") and not t.startswith(" ")):
                text += " "
            parts.append((sp, len(text)))
            text += t
        lines.append(Line(pno, text, parts))
    return lines


def find_in_lines(lines, needle, case=False):
    """-> [Match], belge sirasinda. Eslesmeler ust uste binmez."""
    key = fold(needle, case)
    if not key.strip():
        return []
    out = []
    for li, ln in enumerate(lines):
        hay = ln.text if case else ln.low
        i = hay.find(key)
        while i >= 0:
            j = i + len(key)
            segs = []
            for sp, start in ln.parts:
                a, b = max(i, start), min(j, start + len(sp.text))
                if a < b:
                    segs.append((sp, a - start, b - start))
            if segs:
                out.append(Match(ln.page, li, i, j, segs))
            i = hay.find(key, j)
    return out


class Finder:
    """Bir belge icin arama onbellegi: sayfa satirlari (belge degisince atilir) ve yazi tipleri."""

    def __init__(self):
        self.engine = None
        self.version = None
        self._lines = {}
        self._fonts = {}

    def attach(self, engine):
        """Belge / surum degistiyse onbellegi at. -> degisti mi"""
        if engine is self.engine and engine.version == self.version:
            return False
        self.engine, self.version = engine, engine.version
        self._lines, self._fonts = {}, {}
        return True

    def touch(self, pages):
        """Yalniz bu sayfalar degisti (kendi degistirmemizden sonra): digerlerinin satirlari
        gecerli kalir - her degistirmede butun belge yeniden okunmasin."""
        self.version = self.engine.version
        for p in pages:
            self._lines.pop(p, None)

    def lines(self, pno):
        if pno not in self._lines:
            self._lines[pno] = page_lines(self.engine, pno)
        return self._lines[pno]

    def search(self, pno, needle, case=False):
        return find_in_lines(self.lines(pno), needle, case)

    # ---- eslesmenin sayfadaki yeri
    def _font(self, span):
        key = (span.font, span.is_bold)
        if key not in self._fonts:
            try:
                self._fonts[key] = self.engine._font_obj_for(self.engine.doc[span.page_num], span)[0]
            except Exception:
                self._fonts[key] = None
        return self._fonts[key]

    def quads(self, match):
        """Eslesmenin dortgenleri (parca basina bir tane; egik yazida egik). Harflerin yeri,
        yazi tipinin harf genisliklerinden ORANLANIR (parcanin gercek genisligine olceklenir)."""
        if match._quads is None:
            out = []
            for sp, a, b in match.segs:
                text = sp.text
                f0, f1 = a / max(len(text), 1), b / max(len(text), 1)
                font = self._font(sp)
                if font is not None:
                    try:
                        total = font.text_length(text, fontsize=sp.size)
                        if total > 0:
                            f0 = font.text_length(text[:a], fontsize=sp.size) / total
                            f1 = font.text_length(text[:b], fontsize=sp.size) / total
                    except Exception:
                        pass
                q = sp.quad()
                top, bot = q[1] - q[0], q[2] - q[3]
                out.append([q[0] + top * f0, q[0] + top * f1, q[3] + bot * f1, q[3] + bot * f0])
            match._quads = out
        return match._quads

    def bbox(self, match):
        pts = [p for q in self.quads(match) for p in q]
        return fitz.Rect(min(p.x for p in pts), min(p.y for p in pts), max(p.x for p in pts), max(p.y for p in pts))


def replace(engine, matches, new_text, progress=None):
    """Eslesmeleri new_text ile degistir (TEK geri-al adimi; sayfa basina tek gecis).
    -> (degisen sayisi, atlanan sayisi, degisen sayfalar, tam bulunamayan yazi tipi sayisi)
    Atlananlar: birden cok yazi parcasina bolunmus eslesmeler.
    progress(i, n): her sayfadan once cagrilir (uzun islemde ilerleme gostermek icin)."""
    by_page, skipped = {}, 0
    for m in matches:
        if not m.replaceable:
            skipped += 1
            continue
        sp, a, b = m.segs[0]
        by_page.setdefault(m.page, {}).setdefault(id(sp), (sp, []))[1].append((a, b))
    if not by_page:
        return 0, skipped, set(), 0
    done, inexact = 0, 0
    with engine.undo_batch():
        for i, pno in enumerate(sorted(by_page)):
            if progress is not None:
                progress(i, len(by_page))
            pairs = []
            for sp, ranges in by_page[pno].values():
                text = sp.text
                for a, b in sorted(ranges, reverse=True):     # sondan basa: indeksler kaymasin
                    text = text[:a] + new_text + text[b:]
                pairs.append((sp, text))
                done += len(ranges)
            inexact += engine.replace_texts(pno, pairs)
    return done, skipped, set(by_page), inexact
