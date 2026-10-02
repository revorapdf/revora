"""
pdf_engine.py
-------------
PDF'i acar, metin span'lerini (yazi parcalarini) font/boyut/renk/opaklik/konum
bilgisiyle birlikte cikarir ve secilen bir span'i orijinal font ailesiyle
degistirir. Ayrica vektor cizim (cizgi/kutu), sayfa, filigran ve form
islemlerini yapar. Arayuzden bagimsizdir; basliksiz test edilebilir.
"""
import os
import math
import time
import fitz  # PyMuPDF
from font_resolver import resolve_font_path, font_file_exists
from pdf_content import remove_text_at, ensure_wrapped, text_blend_at, add_resource
import pdf_paths
from i18n import _t
import pdf_markup


class Span:
    def __init__(self, text, bbox, font, size, color, page_num, origin, direction=(1, 0),
                 alpha=255, flags=0, ascender=0.9, descender=-0.25):
        self.text = text
        self.bbox = fitz.Rect(bbox)
        self.font = font
        self.size = size
        self.color = color
        self.page_num = page_num
        self.origin = tuple(origin)  # PDF'in kendi kaydettigi GERCEK taban cizgisi
        self.direction = tuple(direction)  # yazi yonu (cos, sin) - dondurulmus (filigran) metin icin
        self.alpha = alpha           # 0-255; filigranlar genelde yari saydam (ör. 51 = %20)
        self.flags = flags
        self.ascender = ascender
        self.descender = descender

    def color_rgb(self):
        c = self.color
        return ((c >> 16 & 255) / 255, (c >> 8 & 255) / 255, (c & 255) / 255)

    @property
    def opacity(self):
        return self.alpha / 255.0

    @property
    def is_bold(self):
        return bool(self.flags & 16) or "bold" in self.font.lower()

    @property
    def rotated(self):
        return abs(self.direction[1]) > 0.01

    def quad(self):
        """Metnin sayfadaki gercek dortgeni (dondurulmus metinde egik).
        Yatay metinde bbox'in kendisi."""
        if not self.rotated:
            r = self.bbox
            return [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0),
                    fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)]
        dx, dy = self.direction
        d = fitz.Point(dx, dy)
        n = fitz.Point(-dy, dx)                 # metnin "asagi" yonu
        asc = max(self.ascender, 0.5) * self.size
        desc = max(-self.descender, 0.1) * self.size
        h = asc + desc
        c, s = abs(dx), abs(dy)
        # eksen-hizali bbox'tan metin uzunlugunu geri hesapla
        if c >= s:
            L = (self.bbox.width - h * s) / c
        else:
            L = (self.bbox.height - h * c) / s
        L = max(L, self.size * 0.5)
        o = fitz.Point(self.origin)
        top, bot = o - n * asc, o + n * desc
        return [top, top + d * L, bot + d * L, bot]

    def hit(self, p, pad=1.5):
        if not self.rotated:
            r = self.bbox
            return (r.x0 - pad) <= p.x <= (r.x1 + pad) and (r.y0 - pad) <= p.y <= (r.y1 + pad)
        q = self.quad()
        d = fitz.Point(self.direction)
        n = fitz.Point(-d.y, d.x)
        rel = fitz.Point(p) - q[0]
        u = rel.x * d.x + rel.y * d.y
        v = rel.x * n.x + rel.y * n.y
        L = abs(q[1] - q[0])
        h = abs(q[3] - q[0])
        return -pad <= u <= L + pad and -pad <= v <= h + pad

    def area(self):
        q = self.quad()
        return abs(q[1] - q[0]) * abs(q[3] - q[0])

    def moved(self, dx, dy):
        return Span(self.text, fitz.Rect(self.bbox) + (dx, dy, dx, dy), self.font, self.size,
                    self.color, self.page_num, (self.origin[0] + dx, self.origin[1] + dy),
                    self.direction, self.alpha, self.flags, self.ascender, self.descender)


class Block(Span):
    """Birden cok satirdan olusan paragraf. PDF'te "paragraf" kaydi yoktur (her satir
    ayri cizilir); ayni font/boyut/renkte, hizali ve duzenli aralikli, aralarinda
    tablo cizgisi olmayan ardisik satirlar tek parca sayilir. Span gibi davranir:
    metin satirlari \n ile birlesik, origin = (sol kenar, ilk satirin taban cizgisi),
    bbox = satirlarin birlesimi. Duzenleme/tasima/silme tum satirlara uygulanir."""

    def __init__(self, lines, align="left"):
        first = lines[0]
        bb = fitz.Rect(min(l.bbox.x0 for l in lines), min(l.bbox.y0 for l in lines),
                       max(l.bbox.x1 for l in lines), max(l.bbox.y1 for l in lines))
        super().__init__("\n".join(l.text for l in lines), bb, first.font, first.size, first.color,
                         first.page_num, (bb.x0 if align != "left" else first.origin[0], first.origin[1]),
                         first.direction, first.alpha, first.flags, first.ascender, first.descender)
        self.lines = lines
        self.align = align
        pitch = (lines[-1].origin[1] - lines[0].origin[1]) / (len(lines) - 1)
        self.line_spacing = pitch / first.size if first.size else 1.2

    def quad(self):
        r = self.bbox
        return [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0),
                fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)]

    def hit(self, p, pad=1.5):
        return any(l.hit(p, pad) for l in self.lines)

    def moved(self, dx, dy):
        return Block([l.moved(dx, dy) for l in self.lines], self.align)


class PDFEditor:
    MAX_UNDO = 30  # bellek sismesin diye geri-al gecmisi bu kadar snapshot tutar
    GROUP_WINDOW = 2.0  # sn: ayni gruptaki islemler bu kadar arayla gelirse tek geri-al adimi

    def __init__(self):
        self.doc = None
        self.path = None
        self.suggested_path = None   # henuz kaydedilmemis belge (resimden acilan): onerilen ad
        self.undo_stack = []  # list of bytes snapshots
        self.redo_stack = []
        self.dirty = False
        self._path_cache = {}
        self._span_cache = {}
        self._markup_cache = {}
        self._word_cache = {}
        self.version = 0
        self._undo_group = None
        self._undo_group_t = 0.0
        self._mid_seq = 0
        self.last_finalized = 0     # son kayitta kalici uygulanan bulanik alan sayisi

    def _invalidate(self):
        """Sayfa icerigi degisti: onbellege alinmis span/cizim listelerini at."""
        self.version = getattr(self, "version", 0) + 1   # arayuz onbellekleri icin
        self._path_cache = {}
        self._span_cache = {}
        self._markup_cache = {}
        self._word_cache = {}

    def _push_undo(self, group=None):
        """Bir islem oncesi belgenin anlik kopyasini geri-al yiginina koyar.
        Yigin MAX_UNDO'yu asinca en eski kopyayi atar (sinirsiz bellek buyumesini onler).

        group: ard arda gelen kucuk islemleri (ok tusuyla kaydirma) TEK geri-al
        adiminda birlestirmek icin. Ayni grup GROUP_WINDOW icinde tekrar gelirse
        yeni kopya alinmaz. Eskiden her ok basisi ayri adimdi: 30 basis tum
        gecmisi silip gercek duzenlemeleri geri alinamaz yapiyordu (ve her
        basista tum PDF kopyalandigi icin yavasti)."""
        now = time.monotonic()
        if (group is not None and group == self._undo_group and self.undo_stack
                and now - self._undo_group_t <= self.GROUP_WINDOW):
            self._undo_group_t = now
        else:
            self.undo_stack.append(self.doc.tobytes())
            if len(self.undo_stack) > self.MAX_UNDO:
                self.undo_stack.pop(0)
            self._undo_group = group
            self._undo_group_t = now
        self.redo_stack = []
        self.dirty = True
        self._invalidate()

    # ---------- dosya islemleri ----------
    def open(self, path):
        self.doc = fitz.open(path)
        self.path = path
        self.suggested_path = None
        self.undo_stack = []
        self.redo_stack = []
        self._undo_group = None
        # eski surumun nesnelerindeki yorum simgesi alanlarini temizle; varsa
        # belge "degisti" sayilir ki kaydedince dosya da duzelsin
        cleaned = False
        for page in self.doc:
            try:
                cleaned = pdf_markup.clean_page(page) or cleaned
            except Exception:
                pass
        self.dirty = cleaned
        self._invalidate()

    def open_doc(self, doc, suggested_path):
        """Bellekte olusturulmus belgeyi ac (ör. resimden PDF): henuz dosyasi yok,
        kaydederken suggested_path onerilir; degismis sayilir."""
        self.doc = doc
        self.path = None
        self.suggested_path = suggested_path
        self.undo_stack = []
        self.redo_stack = []
        self._undo_group = None
        self.dirty = True
        self._invalidate()

    def page_count(self):
        return len(self.doc) if self.doc else 0

    def save(self, path):
        """Kaydeder. garbage=4 + deflate: tekrarli duzenlemelerden arta kalan
        olu nesneleri temizler ve dosyayi sikistirir -> cikti sismez.

        Var olan bir dosyanin (acik belgenin kendisi dahil) uzerine yazarken
        once gecici dosyaya yazilir, sonra yerine konur: yarida kalan bir
        kayit orijinali bozmaz. (Eski artimli kayit, 'Farkli Kaydet' ya da
        geri-al sonrasi ayni dosyaya kaydederken hata veriyordu.)"""
        target = os.path.abspath(path)
        backed = bool(self.doc.name) and os.path.abspath(self.doc.name) == target

        # Bekleyen bulanik alanlar kaydederken KALICI uygulanir (alttaki icerik
        # silinir). Geri-al ile kayit oncesi duzenlenebilir hale donulebilir.
        # Hata olursa kayit durmali: bulaniklastirilmamis dosya yazilmasin.
        self.last_finalized = self.finalize_blurs()
        # buyutecler sayfanin guncel halini gostersin (silinen/bulaniklastirilan
        # icerigin eski kopyasi buyutecin icinde dosyaya gitmesin) - hata olursa
        # kayit durur (sessizce eski kopyayla yazmaktansa)
        self.sync_derived()

        # ONEMLI: kayit, belgenin bir KOPYASI uzerinden yapilir. subset_fonts() ve
        # garbage=4 bellekteki belgeyi degistirir (fontlar kirpilir, nesne
        # numaralari yeniden dagitilir) ama PyMuPDF'in "bu font zaten eklendi"
        # onbellegi eski numaralari tutar -> kaydettikten sonraki her duzenleme
        # yaziyi kirpilmis fonta ya da BASKA bir nesneye (logo cizimi vb.) baglayip
        # bozuk harf / tuhaf isaretler uretiyordu. Calisilan belgeye dokunmuyoruz.
        out = fitz.open("pdf", self.doc.tobytes())
        # Metin yazarken Windows fontlari EKSIKSIZ gomuluyor (font basina ~1 MB);
        # sadece kullanilan harfleri birakinca dosya orijinalden bile kucuk kaliyor.
        # MuPDF'in kendi ozelligi; basarisiz olursa kaydi engellemesin.
        try:
            out.subset_fonts()
        except Exception:
            pass

        if not os.path.exists(target):
            out.save(target, garbage=4, deflate=True)
            out.close()
        else:
            tmp = target + ".tmp"
            out.save(tmp, garbage=4, deflate=True)
            out.close()
            if backed:
                self.doc.close()   # Windows'ta acik dosyanin uzerine yazilamaz
            try:
                os.replace(tmp, target)
            except Exception:
                # Dosya degistirilemedi (ör. Adobe'de acik, kilitli). ONEMLI:
                # eskiden burada diskteki ORIJINAL yeniden aciliyordu ve
                # uygulamadaki tum duzenlemeler sessizce kayboluyordu.
                # Duzenlemelerin tam hali tmp'de; belgeyi oradan bellege al.
                if backed:
                    with open(tmp, "rb") as f:
                        self.doc = fitz.open("pdf", f.read())
                    self._invalidate()
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            if backed:
                self.doc = fitz.open(target)
                self._invalidate()
        self.path = target
        self.suggested_path = None
        self.dirty = False

    # ---------- goruntuleme ----------
    def render_page(self, page_num, zoom=2.0):
        page = self.doc[page_num]
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix  # .samples / .width / .height -> QImage'e cevrilecek

    def display_matrix(self, page_num):
        """Sayfa (dondurulmemis) koordinatlarini ekranda gorunen
        (dondurulmus) koordinatlara ceviren matris."""
        return self.doc[page_num].rotation_matrix

    # ---------- metin span'leri ----------
    def get_spans(self, page_num):
        if page_num in self._span_cache:
            return self._span_cache[page_num]
        page = self.doc[page_num]
        # Sadece SAYFANIN KENDI yazilari: get_text() isaretleme nesnelerinin (not
        # kutusu vb.) yazilarini da okur; onlar Metin modunda secilip icerik akisi
        # yontemiyle "duzenlenmeye" calisilmamali (Isaretle modunun isi). Goruntu
        # listesi annots=False ile olusturulunca disarida kalirlar. Koordinatlar
        # PyMuPDF'in get_textpage'i gibi dondurulmemis sayfaya gore (rotation 0).
        rot = page.rotation
        if rot:
            page.set_rotation(0)
        try:
            tp = page.get_displaylist(annots=False).get_textpage(flags=fitz.TEXTFLAGS_DICT)
            if not isinstance(tp, fitz.TextPage):      # bazi surumler ham nesne dondurur
                tp = fitz.TextPage(tp)
            d = tp.extractDICT()
        finally:
            if rot:
                page.set_rotation(rot)
        spans = []
        for block in d.get("blocks", []):
            for line in block.get("lines", []):
                direction = line.get("dir", (1, 0))
                for sp in line["spans"]:
                    if sp["text"].strip() == "":
                        continue
                    spans.append(Span(sp["text"], sp["bbox"], sp["font"],
                                      sp["size"], sp["color"], page_num,
                                      sp["origin"], direction,
                                      sp.get("alpha", 255), sp.get("flags", 0),
                                      sp.get("ascender", 0.9), sp.get("descender", -0.25)))
        self._span_cache[page_num] = spans
        return spans

    # paragraf: satir araligi (taban cizgileri arasi) / yazi boyutu bu araliktaysa
    # ayni paragraf olabilir. Form alanlari alt alta ~1,9 kat (ayri kalir), paragraf ~1,15.
    PARA_PITCH = (0.95, 1.6)

    def expand(self, span):
        """Span bir paragrafin satiriysa paragrafin tamamini (Block), degilse kendisini
        dondurur."""
        if span is None or span.rotated or isinstance(span, Block):
            return span
        key = (span.page_num, span.origin, span.text)
        cache = self.__dict__.setdefault("_block_cache", {})
        if cache.get("_v") != getattr(self, "version", 0):
            cache.clear()
            cache["_v"] = getattr(self, "version", 0)
        if key not in cache:
            cache[key] = self._block_for(span)
        return cache[key] or span

    def _block_for(self, sp):
        pno, size = sp.page_num, sp.size
        if size <= 0:
            return None
        spans = self.get_spans(pno)
        same = [s for s in spans if not s.rotated and s.font == sp.font and abs(s.size - size) < 0.05
                and s.color == sp.color and s.alpha == sp.alpha]

        def alone(s):
            """Satirda yapisik baska yazi parcasi yok (karisik bicimli satir paragrafa girmez)."""
            for o in spans:
                if o is s or o.rotated or abs(o.origin[1] - s.origin[1]) > size * 0.3:
                    continue
                gap = max(o.bbox.x0 - s.bbox.x1, s.bbox.x0 - o.bbox.x1)
                if gap < size * 0.6:
                    return False
            return True

        def aligned(a, b):
            modes = []
            if abs(a.bbox.x0 - b.bbox.x0) <= 1.5:
                modes.append("left")
            if abs((a.bbox.x0 + a.bbox.x1) - (b.bbox.x0 + b.bbox.x1)) <= 3.0:
                modes.append("center")
            if abs(a.bbox.x1 - b.bbox.x1) <= 1.5:
                modes.append("right")
            return modes

        paths = None

        def separated(a, b):
            """Iki satirin arasinda yatay bir cizgi (tablo satiri) var mi."""
            nonlocal paths
            if paths is None:
                try:
                    paths = [it for it in self.get_paths(pno) if it.bbox.height < 1.5]
                except Exception:
                    paths = []
            top, bot = sorted((a, b), key=lambda s: s.origin[1])
            y0, y1 = top.bbox.y1 - 0.8, bot.bbox.y0 + 0.8
            x0, x1 = min(a.bbox.x0, b.bbox.x0), max(a.bbox.x1, b.bbox.x1)
            return any(y0 <= it.bbox.y0 <= y1 and it.bbox.x0 < x1 and it.bbox.x1 > x0 for it in paths)

        if not alone(sp):
            return None
        lo, hi = self.PARA_PITCH
        lines, mode, pitch = [sp], None, None
        for down in (True, False):
            cur = sp
            while len(lines) < 60:
                best, bd = None, None
                for s in same:
                    if any(s is l for l in lines):
                        continue
                    dy = s.origin[1] - cur.origin[1]
                    if (dy > 0) != down or not (lo * size <= abs(dy) <= hi * size):
                        continue
                    if pitch is not None and abs(abs(dy) - pitch) > max(0.6, size * 0.08):
                        continue
                    m = aligned(cur, s)
                    if mode is not None:
                        m = [x for x in m if x == mode]
                    if not m:
                        continue
                    if bd is None or abs(dy) < bd:
                        best, bd, bm = s, abs(dy), m[0]
                if best is None or not alone(best) or separated(cur, best):
                    break
                mode = mode or bm
                pitch = pitch if pitch is not None else bd
                lines.append(best)
                cur = best
        if len(lines) < 2:
            return None
        lines.sort(key=lambda s: s.origin[1])
        return Block(lines, mode or "left")

    def find_span_at(self, page_num, pdf_x, pdf_y):
        """Verilen noktadaki span'i bulur. Birden fazla span ust uste
        biniyorsa (ör. tablo yazisi + dev filigran) EN KUCUK olan secilir;
        dondurulmus filigran da artik egik dortgeniyle test edilir, yani
        kocaman eksen-hizali kutusu tiklamalari calmaz."""
        p = fitz.Point(pdf_x, pdf_y)
        hits = [sp for sp in self.get_spans(page_num) if sp.hit(p)]
        if not hits:
            return None
        return self.expand(min(hits, key=lambda s: s.area()))

    # ---------- font cozumleme ----------
    def _get_font_for(self, page, span: Span, force_bold=None, font_override=None):
        """Return (fontname, fontfile_path_or_None, fontbuffer_or_None, exact)"""
        base_font_name = font_override if font_override else span.font
        path, bold, italic, exact = resolve_font_path(base_font_name, force_bold=force_bold)

        if font_file_exists(path):
            fontname = f"F{abs(hash(path)) % 100000}"
            return fontname, path, None, exact

        # Windows font klasoru yoksa (ör. gelistirme ortami) PDF'in
        # kendi gomulu (subset) fontuna dus - eksik karakterler kare cikabilir.
        fontname, buffer = self._embedded_fallback(page, span)
        return fontname, None, buffer, False

    def _embedded_fallback(self, page, span: Span):
        target_xref = None
        for f in page.get_fonts(full=True):
            xref, ext, ftype, basefont, name, encoding, ref = f
            if basefont == span.font:
                target_xref = xref
                break
        if target_xref is None:
            return "helv", None  # PyMuPDF dahili fontu, son care
        _, _, _, content = self.doc.extract_font(target_xref)
        fontname = f"E{target_xref}"
        return fontname, content

    def _font_obj_for(self, page, span: Span, force_bold=None, font_override=None):
        _, fontfile, fontbuffer, exact = self._get_font_for(
            page, span, force_bold, font_override)
        try:
            fo = fitz.Font(fontfile=fontfile, fontbuffer=fontbuffer) \
                if (fontfile or fontbuffer) else fitz.Font("helv")
        except Exception:
            fo = fitz.Font("helv")
        return fo, exact

    @staticmethod
    def _font_from_hint(font_hint, bold):
        path, _, _, exact = resolve_font_path(font_hint, force_bold=bold)
        try:
            fo = fitz.Font(fontfile=path) if font_file_exists(path) else fitz.Font("helv")
        except Exception:
            fo, exact = fitz.Font("helv"), False
        return fo, exact

    # ---------- yardimcilar: metin cizme ----------
    def _write_text(self, page, origin, text, font_obj, size, color, direction=(1, 0),
                    opacity=1.0, line_spacing=1.2, overlay=True, align="left", ref_width=None,
                    blend=None):
        """Metni verilen taban cizgisine yazar. Cok satirli metinde (\\n)
        her satir bir oncekinin line_spacing*boyut kadar altina yazilir.
        direction yatay degilse (dondurulmus filigran vb.) tum blok o aciyla
        dondurulur. opacity < 1 ise yari saydam yazilir.
        align: 'left' / 'center' / 'right'. ref_width verilirse (duzenlenen eski
        yazinin genisligi) o genislik icinde hizalanir - saga dayalida SAG UC, ortalida
        orta sabit kalir; verilmezse origin yazinin basi / ortasi / sonu olur."""
        ensure_wrapped(self.doc, page)
        tw = fitz.TextWriter(page.rect)
        ox, oy = origin
        lh = size * line_spacing
        for k, line in enumerate(text.split("\n")):
            if line.strip():
                w = font_obj.text_length(line, fontsize=size)
                if align == "center":
                    off = ((ref_width - w) / 2) if ref_width is not None else -w / 2
                elif align == "right":
                    off = (ref_width - w) if ref_width is not None else -w
                else:
                    off = 0.0
                tw.append((ox + off, oy + k * lh), line, font=font_obj, fontsize=size)
        dx, dy = direction
        angle = math.degrees(math.atan2(dy, dx))
        morph = None
        if abs(angle) >= 0.01:
            morph = (fitz.Point(ox, oy), fitz.Matrix(-angle))
        tw.write_text(page, color=color, opacity=max(0.0, min(1.0, opacity)),
                      morph=morph, overlay=overlay)
        if blend:
            self._apply_blend(page, blend, overlay)

    def _apply_blend(self, page, blend, overlay=True):
        """Az once yazilan metnin akisini karisim moduyla sar (orijinal yazi ör.
        /BM /Multiply ile ciziliyorsa: filigranin kirmizisi alttaki siyah yaziyi
        boyamaz). TextWriter karisim modu desteklemiyor."""
        xs = page.get_contents()
        if not xs:
            return
        x = xs[-1] if overlay else xs[0]
        gsx = self.doc.get_new_xref()
        self.doc.update_object(gsx, f"<</Type/ExtGState/BM/{blend}>>")
        name = f"RvBM{gsx}"
        try:
            add_resource(self.doc, page.xref, "ExtGState", name, f"{gsx} 0 R")
        except Exception:
            return                              # (miras alinan kaynak vb.) karisimsiz kalir
        data = self.doc.xref_stream(x)
        self.doc.update_stream(x, b"q /" + name.encode() + b" gs\n" + data + b"\nQ\n")

    def _blend_of(self, page, span):
        """Yazinin orijinal karisim modu (duzenleyip yeniden yazarken korunur)."""
        first = span.lines[0] if isinstance(span, Block) else span
        try:
            return text_blend_at(self.doc, page, first.origin)
        except Exception:
            return None

    def _remove_span(self, page, target: Span):
        """Hedef metni sayfadan kaldirir.

        ONCE cerrahi yontem: metnin icerik akisindaki kendi cizim operatorunu
        konumundan bulup bosaltir -> altindaki/ustundeki (filigran vb.) HICBIR
        yaziya dokunmaz, arka plan hic bozulmaz, cift goruntu olmaz.

        Operator bulunamazsa (nadir) redaction'a duser: images/graphics=NONE
        ile sadece metni kaldirir (arka plani korur), ama bu geometrik oldugu
        icin tam ust uste binen komsu metni de silebilir."""
        if isinstance(target, Block):
            for line in target.lines:
                self._remove_span(page, line)
            return
        if remove_text_at(self.doc, page, target.origin):
            return
        # yedek: geometrik redaction (arka plani koru)
        page.add_redact_annot(target.bbox, fill=None)
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_NONE)

    # ---------- duzenleme ----------
    def apply_edit(self, span: Span, new_text, new_size=None, color_rgb=None,
                   force_bold=None, autofit=True, font_override=None,
                   opacity=None, line_spacing=1.2, align="left"):
        """Secili span'i kaldirir, yeni metni ayni fontla yerine yazar.
        new_text bos ise (silme islemi) sadece eski metin kaldirilir.
        opacity verilmezse orijinalin opakligi korunur (filigran yari
        saydam kalir). Metin \\n iceriyorsa cok satirli yazilir."""
        self._push_undo()

        page = self.doc[span.page_num]
        blend = self._blend_of(page, span)
        self._remove_span(page, span)

        if new_text.strip() == "":
            return True  # sadece silme islemi, yazilacak yeni metin yok

        size = new_size if new_size else span.size
        color = color_rgb if color_rgb else span.color_rgb()
        if opacity is None:
            opacity = span.opacity

        font_obj, exact = self._font_obj_for(page, span, force_bold, font_override)

        if autofit:
            size = self._fit_size(font_obj, new_text, span.bbox, size, span)

        # ONEMLI: tahmini bir taban cizgisi hesaplamiyoruz - PDF'in kendi
        # kaydettigi GERCEK taban cizgisini (origin) kullaniyoruz. Boylece
        # boyut/font degisse de metin hep ayni satirda kalir, asagi kaymaz.
        q = span.quad()
        old_w = abs(q[1] - q[0])              # eski yazinin genisligi (hizalama referansi)
        if isinstance(span, Block) and align == "left":
            align = span.align                # ortali / saga dayali paragraf oyle kalsin
        self._write_text(page, span.origin, new_text, font_obj, size,
                         color, span.direction, opacity, line_spacing,
                         align=align, ref_width=old_w if align != "left" else None, blend=blend)
        return exact

    # ---------- bos alana yeni metin ekleme ----------
    def insert_text_new(self, page_num, x, y, text, fontsize=11,
                        color_rgb=(0, 0, 0), font_hint="Arial", bold=False,
                        opacity=1.0, line_spacing=1.2, align="left"):
        """Sayfada bos bir alana sifirdan yeni metin ekler. (x,y) tiklanan
        noktadir ve ilk satirin taban cizgisi olarak kullanilir; align'a gore
        yazinin basi / ortasi / sonu o noktadadir."""
        self._push_undo()
        page = self.doc[page_num]
        font_obj, exact = self._font_from_hint(font_hint, bold)
        self._write_text(page, (x, y), text, font_obj, fontsize, color_rgb,
                         (1, 0), opacity, line_spacing, align=align)
        return exact

    def move_span(self, span: Span, dx, dy, group=None):
        """Var olan bir metni x/y yonunde kaydirir. Eski konumdan siler, yeni
        konuma ayni font/boyut/renk/opaklikla yeniden yazar ve guncel
        Span'i dondurur. group: bkz. _push_undo (ok tusu kaydirmalari)."""
        self._push_undo(group)
        page = self.doc[span.page_num]
        blend = self._blend_of(page, span)
        self._remove_span(page, span)
        font_obj, _ = self._font_obj_for(page, span, force_bold=span.is_bold)
        new = span.moved(dx, dy)
        self._write_text(page, new.origin, span.text, font_obj, span.size,
                         span.color_rgb(), span.direction, span.opacity,
                         blend=blend, **self._block_layout(span))
        return new

    @staticmethod
    def _block_layout(span):
        """Paragrafi yeniden yazarken satir araligi ve hizasi aynen korunsun."""
        if not isinstance(span, Block):
            return {}
        return {"line_spacing": span.line_spacing, "align": span.align,
                "ref_width": span.bbox.width if span.align != "left" else None}

    @staticmethod
    def span_angle(span):
        """Yazinin acisi: ekranda SAAT YONUNDE derece (yatay yazi = 0)."""
        return math.degrees(math.atan2(span.direction[1], span.direction[0]))

    @staticmethod
    def span_center(span):
        q = span.quad()
        return fitz.Point(sum(p.x for p in q) / 4, sum(p.y for p in q) / 4)

    def rotate_span(self, span: Span, delta_deg, group=None):
        """Metni kendi merkezi etrafinda delta_deg (ekranda saat yonu) dondurur:
        eskisi cerrahi olarak kaldirilir, ayni font/boyut/renk/opaklikla yeni
        aciyla yazilir. Guncel Span'i dondurur."""
        self._push_undo(group)
        page = self.doc[span.page_num]
        c = self.span_center(span)
        a = math.radians(delta_deg)
        ca, sa = math.cos(a), math.sin(a)

        def rot(p):
            dx, dy = p[0] - c.x, p[1] - c.y
            return (c.x + dx * ca - dy * sa, c.y + dx * sa + dy * ca)

        dx, dy = span.direction
        new_dir = (dx * ca - dy * sa, dx * sa + dy * ca)
        if abs(new_dir[1]) < 1e-9:              # tam yatay/dikey: kayan nokta hatasi birakma
            new_dir = (math.copysign(1.0, new_dir[0]), 0.0)
        elif abs(new_dir[0]) < 1e-9:
            new_dir = (0.0, math.copysign(1.0, new_dir[1]))
        new_origin = rot(span.origin)
        blend = self._blend_of(page, span)
        self._remove_span(page, span)
        font_obj, _ = self._font_obj_for(page, span, force_bold=span.is_bold)
        self._write_text(page, new_origin, span.text, font_obj, span.size,
                         span.color_rgb(), new_dir, span.opacity, blend=blend, **self._block_layout(span))
        corners = [rot(p) for p in span.quad()]
        bb = fitz.Rect(min(p[0] for p in corners), min(p[1] for p in corners),
                       max(p[0] for p in corners), max(p[1] for p in corners))
        return Span(span.text, bb, span.font, span.size, span.color, span.page_num, new_origin,
                    new_dir, span.alpha, span.flags, span.ascender, span.descender)

    def _fit_size(self, font_obj, text, bbox, size, span=None):
        """Yeni metin kutuya sigmiyorsa boyutu otomatik kucult (cok
        satirlida en uzun satira gore)."""
        box_width = bbox.x1 - bbox.x0
        if span is not None and span.rotated:
            q = span.quad()
            box_width = abs(q[1] - q[0])
        lines = [l for l in text.split("\n") if l.strip()] or [text]
        while size > 4:
            width = max(font_obj.text_length(l, fontsize=size) for l in lines)
            if width <= box_width:
                break
            size -= 0.25
        return size

    # ---------- vektor cizimler (cizgi / kutu / sekil) ----------
    def get_paths(self, page_num):
        if page_num not in self._path_cache:
            page = self.doc[page_num]
            self._path_cache[page_num] = pdf_paths.parse_paths(self.doc, page)
        return self._path_cache[page_num]

    def path_at(self, page_num, x, y, tol=3.0):
        page = self.doc[page_num]
        return pdf_paths.hit_test(self.get_paths(page_num), (x, y), tol,
                                  page.rect * page.derotation_matrix)

    def paths_in_rect(self, page_num, rect):
        return pdf_paths.items_in_rect(self.get_paths(page_num), rect)

    def paths_by_index(self, page_num, indices):
        items = self.get_paths(page_num)
        return [items[i] for i in indices if 0 <= i < len(items)]

    def path_style(self, page_num, index):
        items = self.get_paths(page_num)
        it = items[index]
        st = pdf_paths.style_of(self.doc[page_num], it)
        if not it.stroked:
            # sadece dolgulu: gorunen renk dolgu rengidir; ince seritte
            # (Word/Excel tablo cizgisi) kalinlik = seridin eni
            st["filled_only"] = True
            st["color"] = st.get("fill") or st.get("color")
            if pdf_paths.is_filled_bar(it):
                st["width"] = min(abs(it.bbox.width), abs(it.bbox.height))
        return st

    def transform_paths(self, page_num, indices, matrix, group=None):
        """Secili cizimleri sayfa uzayinda matrix ile donusturur (tasima,
        olcekleme). Sira numaralari (indeks) degismez."""
        items = self.paths_by_index(page_num, indices)
        if not items:
            return
        self._push_undo(group)
        pdf_paths.transform_items(self.doc, self.doc[page_num], items, matrix)

    def move_paths(self, page_num, indices, dx, dy, group=None):
        self.transform_paths(page_num, indices, fitz.Matrix(1, 0, 0, 1, dx, dy), group)

    def scale_paths(self, page_num, indices, old_bbox, new_bbox):
        """Secimi old_bbox'tan new_bbox'a olcekler (tutamacla boyutlandirma)."""
        o, n = fitz.Rect(old_bbox), fitz.Rect(new_bbox)
        sx = n.width / o.width if o.width > 1e-6 else 1.0
        sy = n.height / o.height if o.height > 1e-6 else 1.0
        m = fitz.Matrix(1, 0, 0, 1, -o.x0, -o.y0) * fitz.Matrix(sx, 0, 0, sy, 0, 0) \
            * fitz.Matrix(1, 0, 0, 1, n.x0, n.y0)
        self.transform_paths(page_num, indices, m)

    def set_line_points(self, page_num, index, p1, p2, bend=None):
        """Cizginin uclari (ve bukme noktasi: None = duz cizgi)."""
        items = self.paths_by_index(page_num, [index])
        if not items:
            return
        self._push_undo()
        pdf_paths.set_line_points(self.doc, self.doc[page_num], items[0], p1, p2, bend)
        self._invalidate()

    def delete_paths(self, page_num, indices):
        items = self.paths_by_index(page_num, indices)
        if not items:
            return
        self._push_undo()
        pdf_paths.delete_items(self.doc, self.doc[page_num], items)

    def restyle_paths(self, page_num, indices, width=None, stroke=None, fill=None, dashed=None,
                      color=None):
        """Secili cizimlerin stilini degistirir (tek geri-al adimi).
        color: gorunen renk (konturluysa kontur, dolguluysa dolgu).
        Ince dolgulu seritlerde (Word/Excel tablo cizgileri) width seridin
        enini ayarlar. Uygulanamayan ayarlar icin kullaniciya gosterilecek
        notlarin listesini dondurur."""
        items = self.paths_by_index(page_num, indices)
        if not items:
            return []
        self._push_undo()
        page = self.doc[page_num]
        pdf_paths.restyle_items(self.doc, page, items, width, stroke, fill, dashed, color)
        notes = []
        fill_only = [it for it in items if not it.stroked]
        bars = [it for it in fill_only if pdf_paths.is_filled_bar(it)]
        if width is not None and bars:
            # akis degisti: yollari (sira numarasi sabit) yeniden ayristirip olcekle
            self._invalidate()
            fresh = self.paths_by_index(page_num, [it.index for it in bars])
            pairs = [(it, pdf_paths.bar_thickness_matrix(it, width)) for it in fresh]
            pdf_paths.transform_each(self.doc, page, [(it, m) for it, m in pairs if m is not None])
        self._invalidate()
        others = len(fill_only) - len(bars)
        if dashed and fill_only:
            notes.append(_t("dolgulu çizimlere kesikli stil uygulanamaz"))
        if width is not None and others:
            notes.append(_t("{n} dolgulu şeklin kalınlığı olmaz, yalnızca rengi değişti", n=others))
        return notes

    def add_line(self, page_num, p1, p2, width=0.75, color=(0, 0, 0), dashed=False):
        """Yeni cizgi ekler; eklenen cizginin indeksini dondurur."""
        self._push_undo()
        page = self.doc[page_num]
        ensure_wrapped(self.doc, page)
        pdf_paths.add_line(page, p1, p2, width, color, dashed)
        self._invalidate()
        return len(self.get_paths(page_num)) - 1

    def add_ellipse(self, page_num, rect, width=0.75, color=(0, 0, 0), fill=None, dashed=False):
        """Yeni daire/elips (sayfaya kalici cizim) ekler; indeksini dondurur."""
        self._push_undo()
        page = self.doc[page_num]
        ensure_wrapped(self.doc, page)
        pdf_paths.add_ellipse(page, rect, width, color, fill, dashed)
        self._invalidate()
        return len(self.get_paths(page_num)) - 1

    def add_rect(self, page_num, rect, width=0.75, color=(0, 0, 0), fill=None, dashed=False):
        self._push_undo()
        page = self.doc[page_num]
        ensure_wrapped(self.doc, page)
        pdf_paths.add_rect(page, rect, width, color, fill, dashed)
        self._invalidate()
        return len(self.get_paths(page_num)) - 1

    # ---------- isaretlemeler (ok, elips, kutu, not) - duzenlenebilir annotation ----------
    def get_markups(self, page_num):
        if page_num not in self._markup_cache:
            self._markup_cache[page_num] = pdf_markup.read_page(self.doc[page_num])
        return self._markup_cache[page_num]

    def markup(self, page_num, mid):
        for m in self.get_markups(page_num):
            if m["id"] == mid:
                return m
        return None

    def markup_at(self, page_num, x, y, tol=3.0):
        """Noktadaki en ustteki isaretlemenin id'si (yoksa None)."""
        for m in reversed(self.get_markups(page_num)):
            if pdf_markup.hit(m, (x, y), tol):
                return m["id"]
        return None

    def add_markup(self, page_num, kind, params, img=None):
        """img: goruntu nesnesinin resmi (bytes); tasima/boyutlandirmada tekrar
        kullanilmak uzere saklanir."""
        self._push_undo()
        self._mid_seq += 1
        mid = int(time.time() * 1000) % 1_000_000_000 * 100 + self._mid_seq % 100
        if img is not None:
            self._img_store()[mid] = img
        pdf_markup.build(self.doc, page_num, mid, kind, params, img)
        self._invalidate()
        return mid

    def _img_store(self):
        if not hasattr(self, "_images"):
            self._images = {}
        return self._images

    def markup_image(self, page_num, mid):
        """Goruntu nesnesinin resmi: bellekten, yoksa (dosya yeniden acildiysa)
        nesnenin gorunumunden cikarilir."""
        store = self._img_store()
        if mid not in store:
            m = self.markup(page_num, mid)
            if m is None:
                return None
            data = pdf_markup.image_bytes(self.doc, m["xrefs"][0])
            if data is None:
                return None
            store[mid] = data
        return store[mid]

    def get_words(self, page_num):
        """Sayfanin KENDI kelimeleri (isaretleme yazilari haric), okuma sirasinda:
        [(x0, y0, x1, y1, kelime, blok, satir, sira), ...] - donmemis sayfa uzayinda."""
        if page_num not in self._word_cache:
            page = self.doc[page_num]
            rot = page.rotation
            if rot:
                page.set_rotation(0)
            try:
                tp = page.get_displaylist(annots=False).get_textpage()
                if not isinstance(tp, fitz.TextPage):
                    tp = fitz.TextPage(tp)
                words = list(tp.extractWORDS())
                # egik (filigran) ve dikey yazilarin eksen-hizali kutusu kocaman: yazi
                # vurgusu onlara "oturmasin" (o bolgede serbest fosforlu kalem calissin)
                hs = sorted(w[3] - w[1] for w in words)
                med = hs[len(hs) // 2] if hs else 10.0
                self._word_cache[page_num] = [w for w in words if w[3] - w[1] <= med * 2.5]
            finally:
                if rot:
                    page.set_rotation(rot)
        return self._word_cache[page_num]

    def next_number(self, page_num):
        """Numara araci: sayfadaki en buyuk numaranin bir fazlasi."""
        ns = [int(m["p"].get("n", 0)) for m in self.get_markups(page_num) if m["kind"] == "number"]
        return max(ns) + 1 if ns else 1

    def delete_markups(self, page_num, mids):
        """Birden cok isaretlemeyi tek geri-al adimiyla siler (silgi)."""
        ms = [m for m in self.get_markups(page_num) if m["id"] in set(mids)]
        if not ms:
            return 0
        self._push_undo()
        page = self.doc[page_num]
        for m in ms:
            pdf_markup.remove(page, m["xrefs"])
        self._invalidate()
        return len(ms)

    def update_markup(self, page_num, mid, params, group=None):
        """Isaretlemeyi yeni ayarlarla yeniden kurar (ayni id). group: art arda
        kucuk degisiklikler (yazi yazma, ok tusu, stil) tek geri-al adimi olsun."""
        m = self.markup(page_num, mid)
        if m is None:
            return
        img = self.markup_image(page_num, mid) if m["kind"] == "image" else None
        self._push_undo(group)
        pdf_markup.remove(self.doc[page_num], m["xrefs"])
        pdf_markup.build(self.doc, page_num, mid, m["kind"], params, img)
        self._invalidate()

    def markup_to_back(self, page_num, mid):
        """Isaretlemeyi en alta al (sayfanin /Annots listesinde basa)."""
        m = self.markup(page_num, mid)
        if m is None:
            return False
        page = self.doc[page_num]
        t, v = self.doc.xref_get_key(page.xref, "Annots")
        holder, key = page.xref, "Annots"
        if t == "xref":                       # liste ayri bir nesnede
            holder = int(v.split()[0])
            v = self.doc.xref_object(holder, compressed=True)
            key = None
        elif t != "array":
            return False
        import re
        refs = re.findall(r"(\d+)\s+0\s+R", v)
        mine = [r for r in refs if int(r) in m["xrefs"]]
        if not mine or refs[:len(mine)] == mine:
            return False
        order = mine + [r for r in refs if r not in mine]
        arr = "[" + " ".join(f"{r} 0 R" for r in order) + "]"
        self._push_undo()
        if key is None:
            self.doc.update_object(holder, arr)
        else:
            self.doc.xref_set_key(holder, key, arr)
        self._invalidate()
        return True

    def delete_markup(self, page_num, mid):
        m = self.markup(page_num, mid)
        if m is None:
            return
        self._push_undo()
        pdf_markup.remove(self.doc[page_num], m["xrefs"])
        self._invalidate()

    def blur_region(self, page_num, rect, mode="blur", level=5):
        """Alani HEMEN guvenli bulaniklastir (alttaki icerik dosyadan silinir).
        pdf_blur Qt kullanir; arayuzden bagimsiz testte QApplication gerekir."""
        import pdf_blur      # (uygulamada PySide6 zaten fitz'ten once yuklu)
        self._push_undo()
        r = self._blur_apply(page_num, rect, mode, level)
        if r is None:            # alan sayfanin disinda / cok kucuk: degisiklik yok
            self.undo_stack.pop()
            return None
        self._invalidate()
        self.sync_derived(page_num)
        return r

    def pending_blurs(self, page_num=None):
        pages = range(self.page_count()) if page_num is None else [page_num]
        return [(pno, m) for pno in pages for m in self.get_markups(pno) if m["kind"] == "blur"]

    def _blur_protected(self, pno, rect, angle=0.0):
        """Bulanik alana degen ama alanin DISINA da tasan filigran benzeri yazilar
        (egik, yari saydam ya da sayfadaki tipik yazidan cok buyuk). MuPDF silerken
        alana degen harfi BUTUN olarak siler: filigranin dev harfleri alanin
        disinda da kesiliyordu. Bunlar silmeden once kenara alinip sonra aynen
        geri yazilir. (Tamamen alanin icindeki yazi korunmaz: normal silinir.)"""
        import pdf_blur
        spans = self.get_spans(pno)
        if not spans:
            return []
        sizes = sorted(s.size for s in spans)
        med = sizes[len(sizes) // 2]
        pts = pdf_blur.poly(rect, angle) if angle else [rect.tl, rect.tr, rect.br, rect.bl]
        ax0, ay0 = min(p.x for p in pts), min(p.y for p in pts)
        ax1, ay1 = max(p.x for p in pts), max(p.y for p in pts)

        def inside(p):                       # disbukey alan poligonu
            sign = 0
            for i in range(len(pts)):
                a, b = pts[i], pts[(i + 1) % len(pts)]
                c = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x)
                if abs(c) < 1e-9:
                    continue
                if sign == 0:
                    sign = 1 if c > 0 else -1
                elif (c > 0) != (sign > 0):
                    return False
            return True

        out = []
        for s in spans:
            if not (s.rotated or s.alpha < 255 or s.size >= 2.5 * med):
                continue
            b = s.bbox
            if b.x1 < ax0 or b.x0 > ax1 or b.y1 < ay0 or b.y0 > ay1:
                continue                     # alana degmiyor
            if all(inside(p) for p in s.quad()):
                continue                     # tamamen alanin icinde: silinmeli
            out.append(s)
        return out

    @staticmethod
    def _base14_font(span):
        """Yazi PDF'in 14 standart fontundan biriyle (Helvetica, Times, Courier) yazilmissa
        ve tum harfleri o fontta varsa ayni yerlesik font: MuPDF birebir ayni cizer
        (Windows'taki en yakin fontla yeniden yazinca harf kenarlari hafifce degisiyordu)."""
        name = span.font.split("+")[-1].lower().replace(" ", "")
        fam = next((f for f in ("helvetica", "times", "courier") if f in name), None)
        if fam is None:
            return None
        bold = span.is_bold
        ital = "italic" in name or "oblique" in name
        code = {"helvetica": ("helv", "hebo", "heit", "hebi"), "times": ("tiro", "tibo", "tiit", "tibi"),
                "courier": ("cour", "cobo", "coit", "cobi")}[fam][(1 if bold else 0) + (2 if ital else 0)]
        try:
            f = fitz.Font(code)
        except Exception:
            return None
        if all(ch.isspace() or f.has_glyph(ord(ch)) for ch in span.text):
            return f
        return None

    def _blur_apply(self, pno, rect, mode, level, angle=0.0):
        """pdf_blur.apply + alana tasan filigranlarin korunmasi: goruntu alinir ->
        filigran satiri cerrahi olarak kaldirilir -> MuPDF alanin altini siler ->
        filigran aynen geri yazilir -> bulanik goruntu ustune konur (alanin icinde
        filigran bulanik gorunur, disinda hic bozulmaz). Cerrahi kaldirilamayan
        satir korunmaz (eski davranis): yedek geometrik silme filigranin dev
        kutusundaki her seyi silebilirdi."""
        import pdf_blur
        keep = self._blur_protected(pno, fitz.Rect(rect).normalize(), angle)
        done = []

        def before(page):
            for sp in keep:
                blend = self._blend_of(page, sp)
                if remove_text_at(self.doc, page, sp.origin):
                    done.append((sp, blend))

        def after(page):
            for sp, blend in done:
                font_obj = self._base14_font(sp)
                if font_obj is None:
                    font_obj, _ = self._font_obj_for(page, sp, force_bold=sp.is_bold)
                self._write_text(page, sp.origin, sp.text, font_obj, sp.size,
                                 sp.color_rgb(), sp.direction, sp.opacity, blend=blend)

        return pdf_blur.apply(self.doc, pno, rect, mode, level, angle=angle,
                              before_redact=before if keep else None,
                              after_redact=after if keep else None)

    def finalize_blurs(self, page_num=None, mid=None, push_undo=True):
        """Bekleyen (duzenlenebilir) bulanik alanlari kalici uygula: nesne kalkar,
        alttaki yazi/cizim/resim silinir, bulanik goruntu sayfaya islenir.
        Kaydederken ve 'sayfaya isle'de otomatik cagrilir. Uygulanan sayi."""
        todo = [(p, m) for p, m in self.pending_blurs(page_num) if mid is None or m["id"] == mid]
        if not todo:
            return 0
        import pdf_blur      # sadece gerekince (Qt yukler; uygulamada PySide6 zaten once yuklu)
        if push_undo:
            self._push_undo()
        for pno, m in todo:
            pdf_markup.remove(self.doc[pno], m["xrefs"])
            P = m["p"]
            self._blur_apply(pno, fitz.Rect(P["rect"]), P.get("mode", "blur"), P.get("level", 5),
                           angle=pdf_markup.angle_of(P))
        self._invalidate()
        self.sync_derived(page_num)
        return len(todo)

    def sync_derived(self, page_num=None):
        """Buyutecler ve bekleyen bulanik alanlar sayfa iceriginin KOPYASINI
        gosterir. Sayfa degistiyse (metin duzenleme, silme, bulaniklastirma...)
        onlari yeniden kur: hem guncel gorunsunler hem de silinmis icerik bir
        buyutecin icinde dosyada kalmasin. Once bulaniklar, sonra buyutecler
        (buyutec bulaniklari da gosterir). Geri-al adimi acmaz (turetilmis veri).
        Degisen sayfa sayisi."""
        if not self.doc:
            return 0
        pages = range(self.page_count()) if page_num is None else [page_num]
        changed = 0
        for pno in pages:
            touched = False
            for kind in pdf_markup.DERIVED:
                items = [m for m in self.get_markups(pno) if m["kind"] == kind]
                if not items:
                    continue
                sig = pdf_markup.derived_sig(self.doc, pno, kind)
                for m in items:
                    if m.get("sig") != sig:
                        pdf_markup.remove(self.doc[pno], m["xrefs"])
                        pdf_markup.build(self.doc, pno, m["id"], kind, m["p"])
                        touched = True
                self._markup_cache.pop(pno, None)
            if touched:
                changed += 1
        return changed

    sync_magnifiers = sync_derived

    def flatten_markups(self):
        """Tum isaretlemeleri sayfaya kalici isler (artik nesne olarak
        duzenlenemez; karsi taraf da degistiremez). Form alanlarina dokunmaz."""
        self._push_undo()
        # bulanik alanlar once GERCEKTEN uygulanmali; yoksa bake sadece goruntuyu
        # sayfaya yapistirir, alttaki yazi dosyada kalir
        self.finalize_blurs(push_undo=False)
        self.doc.bake(annots=True, widgets=False)
        self._invalidate()

    # ---------- sayfa islemleri ----------
    def rotate_page(self, page_num, delta):
        self._push_undo()
        page = self.doc[page_num]
        page.set_rotation((page.rotation + delta) % 360)

    def delete_page(self, page_num):
        if self.page_count() <= 1:
            return False
        self._push_undo()
        self.doc.delete_page(page_num)
        return True

    def insert_blank_page(self, at):
        """at konumuna (0 = en basa) bos sayfa ekler; boyut komsu sayfadan."""
        self._push_undo()
        ref = self.doc[min(max(at - 1, 0), self.page_count() - 1)]
        r = ref.rect * ref.derotation_matrix
        self.doc.new_page(at, width=abs(r.width), height=abs(r.height))

    def insert_pdf_pages(self, path, at):
        """Baska bir PDF'in tum sayfalarini at konumuna ekler; eklenen
        sayfa sayisini dondurur."""
        src = fitz.open(path)
        try:
            self._push_undo()
            n = len(src)
            self.doc.insert_pdf(src, start_at=at)
            return n
        finally:
            src.close()

    def insert_doc_pages(self, src, at):
        """Bellekteki bir belgenin (ör. resimlerden olusturulan) sayfalarini at konumuna
        ekler (tek geri-al adimi); eklenen sayfa sayisini dondurur."""
        self._push_undo()
        n = len(src)
        self.doc.insert_pdf(src, start_at=at)
        return n

    def duplicate_page(self, page_num):
        self._push_undo()
        # fullcopy_page(kaynak, to): 'to' sayfasinin ONUNE kopyalar; son sayfada
        # onune konacak sayfa yok -> -1 (en sona). (Eskiden son sayfada hata veriyordu.)
        to = page_num + 1 if page_num + 1 < len(self.doc) else -1
        self.doc.fullcopy_page(page_num, to)

    def move_page(self, src, dst):
        """src sayfasini, sonuc listesinde dst konumuna gelecek sekilde tasir."""
        if src == dst:
            return
        self._push_undo()
        # PyMuPDF move_page(pno, to): to'dan ONCEYE koyar; -1 = en sona
        if dst >= self.page_count() - 1:
            self.doc.move_page(src, -1)
        elif dst > src:
            self.doc.move_page(src, dst + 1)
        else:
            self.doc.move_page(src, dst)

    # ---------- filigran ekleme ----------
    def add_watermark(self, text, pages, fontsize=60, color=(1, 0, 0), opacity=0.2,
                      angle=45, font_hint="Arial", bold=True, overlay=True):
        """Secili sayfalarin ortasina, verilen aciyla (saat yonunun tersi,
        ekranda gorunen) yari saydam filigran yazar. Cok satir desteklenir."""
        self._push_undo()
        font_obj, _ = self._font_from_hint(font_hint, bold)
        lines = [l for l in text.split("\n")] or [text]
        lh = fontsize * 1.2
        for pno in pages:
            page = self.doc[pno]
            ensure_wrapped(self.doc, page)
            r = page.rect * page.derotation_matrix   # dondurulmemis sayfa
            c = fitz.Point((r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2)
            tw = fitz.TextWriter(page.rect)
            y0 = c.y - (len(lines) - 1) * lh / 2 + fontsize * 0.35
            for k, line in enumerate(lines):
                w = font_obj.text_length(line, fontsize=fontsize)
                tw.append((c.x - w / 2, y0 + k * lh), line, font=font_obj, fontsize=fontsize)
            # ekranda gorunen aci = sayfanin kendi donusu de hesaba katilarak
            tw.write_text(page, color=color, opacity=opacity, overlay=overlay,
                          morph=(c, fitz.Matrix(angle + page.rotation)))

    # ---------- form alanlari ----------
    def get_form_fields(self):
        fields = []
        for page in self.doc:
            for w in page.widgets():
                fields.append({
                    "page": page.number, "xref": w.xref, "name": w.field_name or "",
                    "label": w.field_label or "", "type": w.field_type,
                    "type_name": w.field_type_string, "value": w.field_value,
                    "choices": list(w.choice_values or []),
                    "on_state": w.on_state() if w.field_type in (
                        fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON) else None,
                    "rect": fitz.Rect(w.rect),
                    "readonly": bool(w.field_flags & 1),
                })
        return fields

    def set_form_values(self, values):
        """values: {(page, xref): yeni_deger}. Hepsi tek geri-al adimi."""
        if not values:
            return
        self._push_undo()
        for page in self.doc:
            for w in page.widgets():
                key = (page.number, w.xref)
                if key not in values:
                    continue
                v = values[key]
                if w.field_type in (fitz.PDF_WIDGET_TYPE_CHECKBOX,
                                    fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                    w.field_value = w.on_state() if v else "Off"
                else:
                    w.field_value = v
                w.update()

    # ---------- OCR (taranmis sayfalar) ----------
    @staticmethod
    def ocr_available():
        try:
            fitz.get_tessdata()
            return True
        except Exception:
            return False

    def ocr_pages(self, pages, language="tur+eng", dpi=300, progress=None):
        """Taranmis (resim) sayfalardaki yaziyi Tesseract ile tanir ve
        GORUNMEZ bir metin katmani olarak ekler: sayfa ayni gorunur ama
        metin secilebilir, aranabilir, kopyalanabilir olur.
        Tanima yapilan kelime sayisini dondurur."""
        self._push_undo()
        total = 0
        helv = fitz.Font("helv")
        for i, pno in enumerate(pages):
            if progress:
                progress(i, len(pages))
            page = self.doc[pno]
            tp = page.get_textpage_ocr(language=language, dpi=dpi, full=True)
            words = page.get_text("words", textpage=tp)
            if not words:
                continue
            ensure_wrapped(self.doc, page)
            tw = fitz.TextWriter(page.rect)
            for x0, y0, x1, y1, word, *_ in words:
                h = y1 - y0
                if h <= 0 or not word.strip():
                    continue
                size = h * 0.85
                w = helv.text_length(word, fontsize=size)
                # kelimeyi tanindigi kutunun genisligine yay
                if w > 0:
                    size = min(size * (x1 - x0) / w, h * 1.2)
                tw.append((x0, y1 - h * 0.2), word, font=helv, fontsize=size)
                total += 1
            tw.write_text(page, render_mode=3)  # 3 = gorunmez metin
        return total

    # ---------- geri al / yinele ----------
    def undo(self):
        if not self.undo_stack:
            return False
        self._undo_group = None
        self.redo_stack.append(self.doc.tobytes())
        data = self.undo_stack.pop()
        self.doc = fitz.open("pdf", data)
        self._invalidate()
        self.dirty = True
        return True

    def redo(self):
        if not self.redo_stack:
            return False
        self._undo_group = None
        self.undo_stack.append(self.doc.tobytes())
        data = self.redo_stack.pop()
        self.doc = fitz.open("pdf", data)
        self._invalidate()
        self.dirty = True
        return True
