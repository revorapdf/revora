"""
pdf_engine.py
-------------
PDF'i acar, metin span'lerini (yazi parcalarini) font/boyut/renk/opaklik/konum
bilgisiyle birlikte cikarir ve secilen bir span'i orijinal font ailesiyle
degistirir. Ayrica vektor cizim (cizgi/kutu), sayfa, filigran ve form
islemlerini yapar. Arayuzden bagimsizdir; basliksiz test edilebilir.
"""
import contextlib
import copy
import functools
import os
import math
import tempfile
import time
import fitz  # PyMuPDF
from font_resolver import resolve_font_path, font_file_exists, detect_style
from pdf_content import (remove_text_at, remove_texts_each, ensure_wrapped, text_blend_at,
                         text_blends_at, add_resource)
import pdf_paths
import pdf_images
from i18n import _t
import pdf_markup
import pdf_tounicode


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

    def run(self):
        """(taban cizgisinin basi, sonu) = (x, y, bitis_x, bitis_y). Yaziyi cizen operatorlerin
        TAMAMINI bulmak icin (bir yazi birden cok operatorle cizilmis olabilir: pdf_content._run)."""
        ox, oy = self.origin
        if self.rotated:
            q = self.quad()
            n = abs(q[1] - q[0])
        else:
            n = (self.bbox.x1 - ox) if self.direction[0] >= 0 else (ox - self.bbox.x0)
        return (ox, oy, ox + self.direction[0] * n, oy + self.direction[1] * n)

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
        self._quad = None
        if not first.rotated:
            bb = fitz.Rect(min(l.bbox.x0 for l in lines), min(l.bbox.y0 for l in lines),
                           max(l.bbox.x1 for l in lines), max(l.bbox.y1 for l in lines))
            origin = (bb.x0 if align != "left" else first.origin[0], first.origin[1])
            pitch = (lines[-1].origin[1] - lines[0].origin[1]) / (len(lines) - 1)
            self.length = bb.width
        else:
            # DONUK paragraf (2026-10-15; dondurulen iki satirli yazi dondurunce iki ayri satira
            # bolunuyordu): hesaplar yazinin kendi yonunde. u = yazinin yonu (d), v = ona dik
            # "asagi" (n); origin = ilk satirin taban cizgisinde paragrafin bas kenari.
            d = fitz.Point(first.direction)
            n = fitz.Point(-d.y, d.x)
            o = fitz.Point(first.origin)
            us = [(q - o).x * d.x + (q - o).y * d.y for l in lines for q in l.quad()[:2]]
            u0, u1 = min(us), max(us)
            vl = fitz.Point(lines[-1].origin) - o
            v_last = vl.x * n.x + vl.y * n.y
            asc = max(first.ascender, 0.5) * first.size
            desc = max(-first.descender, 0.1) * first.size
            self._quad = [o + d * u0 - n * asc, o + d * u1 - n * asc,
                          o + d * u1 + n * (v_last + desc), o + d * u0 + n * (v_last + desc)]
            bb = fitz.Rect(min(p.x for p in self._quad), min(p.y for p in self._quad),
                           max(p.x for p in self._quad), max(p.y for p in self._quad))
            start = o + d * u0
            origin = (start.x, start.y) if align != "left" else tuple(first.origin)
            pitch = v_last / (len(lines) - 1)
            self.length = u1 - u0
        super().__init__("\n".join(l.text for l in lines), bb, first.font, first.size, first.color,
                         first.page_num, origin,
                         first.direction, first.alpha, first.flags, first.ascender, first.descender)
        self.lines = lines
        self.align = align
        self.line_spacing = pitch / first.size if first.size else 1.2

    def quad(self):
        if self._quad is not None:
            return list(self._quad)
        r = self.bbox
        return [fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0),
                fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)]

    def hit(self, p, pad=1.5):
        return any(l.hit(p, pad) for l in self.lines)

    def moved(self, dx, dy):
        return Block([l.moved(dx, dy) for l in self.lines], self.align)


class Clip:
    """Kopyalanan secim: BELGEDEN BAGIMSIZ kopya (kaynak sonradan duzenlense ya da sekmesi
    kapansa da yapistirilabilir). PDFEditor.snapshot_selection uretir, paste_clip yazar.
    texts:  [(Span | Block, yazi tipi nesnesi, harf konumu tarifi, (boyut, aralik, olcek), karisim)]
    paths:  [cizim sozlugu (page.get_drawings ogesi, sayfa koordinati)]
    images: [(resim baytlari, maske baytlari | None, dortgen [4 nokta])]
    skipped: {"path": n, "image": n} - kopyalanamayan (kullaniciya soylenir).
    Koordinatlar kaynak sayfanin (dondurulmemis) sayfa koordinatidir."""

    def __init__(self, page_num, texts, paths, images, skipped, source=None):
        self.page_num, self.texts, self.paths, self.images = page_num, texts, paths, images
        self.skipped = skipped
        self.source = source                     # weakref.ref(PDFEditor) - "ayni belge mi" icin
        boxes = []
        for sp, *_ in texts:
            q = sp.quad()
            boxes.append(fitz.Rect(min(p.x for p in q), min(p.y for p in q), max(p.x for p in q), max(p.y for p in q)))
        boxes += [fitz.Rect(d["rect"]) for d in paths]
        boxes += [fitz.Rect(min(p.x for p in q), min(p.y for p in q), max(p.x for p in q), max(p.y for p in q))
                  for _, _, q in images]
        self.bbox = fitz.Rect(min(b.x0 for b in boxes), min(b.y0 for b in boxes),
                              max(b.x1 for b in boxes), max(b.y1 for b in boxes)) if boxes else fitz.Rect()

    def __len__(self):
        return len(self.texts) + len(self.paths) + len(self.images)

    @property
    def text(self):
        """Panoya giden duz metin: yazilar okuma sirasiyla (ustten alta, soldan saga)."""
        order = sorted(self.texts, key=lambda t: (round(t[0].bbox.y0 / 3.0), t[0].bbox.x0))
        return "\n".join(t[0].text.replace("\xa0", " ") for t in order)

    def first_size(self):
        return self.texts[0][0].size if self.texts else 10.0


class PasswordError(Exception):
    """Belge parola korumali: parola verilmedi (needed=True) ya da yanlis."""

    def __init__(self, needed):
        super().__init__("parola gerekli" if needed else "parola yanlis")
        self.needed = needed


def release_cache():
    """PDF kutuphanesinin (MuPDF) genel onbellegini bosaltir.

    Kutuphane cozdugu resimleri / yazi tiplerini yeniden kullanmak icin surec genelinde bir
    onbellekte tutar. Belge KAPANINCA o belgenin kayitlari kendiliginden silinmez ve onbellegin
    ust siniri yok: 69 MB'lik (resim agirlikli) belge her acilip kapandiginda ~60 MB kaliyor,
    30 turda 2 GB'a cikiyordu (yalniz kutuphaneyle de ayni - uygulama belgeyi tutmuyor). Daha
    sik gorulen hali: GERI AL / YINELE belgeyi kopyasindan yeniden kurar; her biri eski belgenin
    kayitlarini geride birakiyordu (12 geri al + yinele = 1,5 GB) - 2026-10-13.
    Yalniz bir belge BIRAKILDIGINDA cagrilir (bkz. PDFEditor.doc); duzenleme / yakinlastirma
    sirasinda cagrilmaz: o zaman acik belgenin her cizimi resimleri bastan cozerdi. Yalniz
    kapanan belgenin payini silmenin yolu yok (pdf_empty_store etkisiz; denendi): diger acik
    sekmelerin kayitlari da gider, ilk cizimlerinde yeniden olusur (olcum: SURUM_ONCESI_KONTROL)."""
    try:
        fitz.TOOLS.store_shrink(100)
    except Exception:
        pass


class RedactionError(Exception):
    """Bekleyen karartma uygulanamadi. Belge islemden onceki haline donduruldu (karartma hala
    beklemede); kayit yapilmadi."""


# Kucultme duzeyleri: (resimlerin bu cozunurlukten yuksek olanlari, hedef cozunurluk, JPEG kalitesi)
COMPRESS_LEVELS = {
    "light": None,                 # resimlere dokunma: yalniz yapi temizligi + sikistirma
    "medium": (160, 150, 75),      # ekranda ve yazicida iyi
    "strong": (110, 96, 60),       # e-posta icin: gozle gorulur ama okunur
}


class PDFEditor:
    MAX_UNDO = 30  # bellek sismesin diye geri-al gecmisi bu kadar snapshot tutar

    # Calisilan belge. Yerine BASKA bir belge konunca (geri al, yinele, hata sonrasi geri yukleme,
    # kayittan sonra yeniden acma) ya da None yapilinca (sekme kapandi) eski belge birakilir ve
    # kutuphanenin o belgeden kalan onbellegi bosaltilir (bkz. release_cache). Duzenlemeler belgeyi
    # DEGISTIRMEZ (ayni nesne): onlarda onbellege dokunulmaz.
    @property
    def doc(self):
        return self._doc

    @doc.setter
    def doc(self, new):
        old = self.__dict__.get("_doc")
        self._doc = new
        if old is not None and old is not new:
            del old
            release_cache()
    MAX_UNDO_BYTES = 400 * 1024 * 1024   # ... ve toplamda en cok bu kadar bayt (buyuk belgede adim azalir)
    GROUP_WINDOW = 2.0  # sn: ayni gruptaki islemler bu kadar arayla gelirse tek geri-al adimi

    def __init__(self):
        self.doc = None
        self.path = None
        self.suggested_path = None   # henuz kaydedilmemis belge (resimden acilan): onerilen ad
        self.undo_stack = []  # list of bytes snapshots
        self.redo_stack = []
        self.dirty = False
        self.password = None         # belgeyi ACMA parolasi (kaydederken ayni parolayla sifrelenir)
        self.restricted = False      # sahibi izinleri kisitlamis (acma parolasiz) belge: bkz. open
        self._path_cache = {}
        self._span_cache = {}
        self._raw_cache = {}         # sayfa -> {(x, y): harfler}  (bkz. _span_chars)
        self._k_cache = {}           # (yazi tipi, punto) -> (gercek boyut orani, yol)  (bkz. _look)
        self._look_memo = {}         # (sayfa, x, y) -> (harf araligi, yatay olcek): BIZIM dondurdugumuz yazi
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
        self._image_cache = {}
        self._path_cache = {}
        self._span_cache = {}
        self._raw_cache = {}
        self._vis_cache = {}
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
        self._push_calls = getattr(self, "_push_calls", 0) + 1     # (bkz. _tx_rollback)
        if getattr(self, "_batching", False):      # undo_batch icinde: kopya zaten alindi
            self.dirty = True
            self._invalidate()
            return
        now = time.monotonic()
        # (undo_hold: surguyle surukleme suruyor; fare basiliyken 2 sn duraklasa da ayni adim)
        if (group is not None and group == self._undo_group and self.undo_stack
                and (now - self._undo_group_t <= self.GROUP_WINDOW or getattr(self, "undo_hold", False))):
            self._undo_group_t = now
        else:
            self.undo_stack.append(self.doc.tobytes())
            if len(self.undo_stack) > self.MAX_UNDO:
                self.undo_stack.pop(0)
            # Her adim belgenin TAM kopyasi: 100 MB'lik bir taramada 30 adim ~3 GB ederdi (audit
            # 2026-10-12). Toplam boyut da sinirlanir; en yeni adim her zaman kalir.
            total = sum(len(b) for b in self.undo_stack)
            while total > self.MAX_UNDO_BYTES and len(self.undo_stack) > 1:
                total -= len(self.undo_stack.pop(0))
            self._undo_group = group
            self._undo_group_t = now
        self.redo_stack = []
        self.dirty = True
        self._invalidate()

    @contextlib.contextmanager
    def undo_batch(self, group=None):
        """Birden cok islemi TEK geri-al adiminda topla (toplu secimi tasima / silme):
            with engine.undo_batch():
                engine.move_paths(...); engine.move_span(...); engine.move_span(...)
        Belgenin kopyasi bir kez alinir; icerideki islemlerin kendi kopya almasi atlanir.
        group: bkz. _push_undo (ok tusuyla ard arda kaydirma tek adim olsun)."""
        st = self._tx_begin()
        self._push_undo(group)
        self._batching = True
        try:
            yield
        except BaseException as ex:            # ortasinda hata: basarili ilk adimlar dahil hepsi geri
            self._batching = False
            self._tx_rollback(st, ex)
            raise
        finally:
            self._batching = False

    # ---- YARIDA KALAN ISLEM (2026-10-13) ------------------------------------------------------
    # Duzenleme islemleri "eskiyi sil, yeniyi yaz" diye calisir. Yazma asamasi hata verirse belge
    # yarim kalirdi (eski yazi silinmis, yenisi yok) ve Kaydet bu hali dosyaya yazardi. Kural:
    # geri-al adimi acan (_push_undo cagiran) HER islem hata verirse belge ve geri-al / yinele
    # gecmisi islemden onceki haline AYNEN doner. Bunu islem basina yazmak gerekmez: sinifin
    # sonundaki dongu _push_undo cagiran butun yontemleri _atomic ile sarar (yeni eklenen islem de
    # kendiliginden korunur). Arayuz, on_rollback ile haberdar edilir.
    def _tx_begin(self):
        return (list(self.undo_stack), list(self.redo_stack), self.dirty, self._undo_group,
                self._undo_group_t, getattr(self, "_push_calls", 0))

    def _tx_rollback(self, st, error=None):
        """Belgeyi ve gecmisi _tx_begin anina dondurur. Islem geri-al adimi acmadan hata verdiyse
        (belgeye dokunmamistir) hicbir sey yapmaz. Geri yuklendiyse True."""
        undo0, redo0, dirty0, group0, group_t0, calls0 = st
        if getattr(self, "_push_calls", 0) == calls0 or not self.undo_stack:
            return False
        snapshot = self.undo_stack[-1]         # islemden onceki belge
        if undo0 and snapshot is undo0[-1]:
            # yeni kopya ALINMAMIS (ok tusuyla ard arda kaydirma ayni adimda birlesir): eldeki
            # kopya o grubun BASI. Belge oraya doner; kopya artik bugunku hal oldugu icin adim kalkar.
            undo0, group0 = undo0[:-1], None
        self.doc = fitz.open("pdf", snapshot)
        self.undo_stack, self.redo_stack = undo0, redo0
        self.dirty, self._undo_group, self._undo_group_t = dirty0, group0, group_t0
        self._invalidate()
        cb = getattr(self, "on_rollback", None)
        if cb is not None:
            try:
                cb(error)
            except Exception:
                pass
        return True

    @contextlib.contextmanager
    def _undo_guard(self, push=True):
        """Yarida hata verebilecek bir islem icin: hata olursa belge VE geri-al / yinele gecmisi
        islemden onceki haline AYNEN doner (islem hic baslamamis gibi), hata yukari gider.
            with self._undo_guard():        # geri-al adimi acar (push=False: acmaz)
                ...belgeyi degistir...
        Gecmisin yalniz uzunlugunu geri koymak yetmez: gecmis doluyken (MAX_UNDO / MAX_UNDO_BYTES)
        yeni adim en ESKI adimi dusurur; uzunluk ayni kalir ama eski adim gitmis, yerine ise
        yaramayan bir adim gelmis olur (2026-10-13). Bu yuzden listelerin kendisi saklanir
        (kopyalar ayni bayt nesnelerini gosterir: bellek harcamaz)."""
        undo0, redo0 = list(self.undo_stack), list(self.redo_stack)
        rest = (self.dirty, self._undo_group, self._undo_group_t)
        if push:
            self._push_undo()
        # (az once alinan geri-al kopyasi varsa o kullanilir: belge ikinci kez kopyalanmasin)
        pushed = bool(self.undo_stack) and (not undo0 or self.undo_stack[-1] is not undo0[-1])
        snapshot = self.undo_stack[-1] if pushed else self.doc.tobytes()
        try:
            yield
        except BaseException:
            self.doc = fitz.open("pdf", snapshot)
            self.undo_stack, self.redo_stack = undo0, redo0
            self.dirty, self._undo_group, self._undo_group_t = rest
            self._invalidate()
            raise

    # ---------- dosya islemleri ----------
    def open(self, path, password=None):
        """Parola korumali belgede password verilmezse / yanlissa PasswordError.
        Parola motorda saklanir: belge bellekte SIFRESIZ islenir (geri-al kopyalari dahil),
        kaydederken ayni parolayla yeniden sifrelenir -> koruma kendiliginden kalkmaz."""
        doc = fitz.open(path)
        locked = bool(doc.needs_pass)          # (dogrulamadan SONRA sorulursa hep False doner)
        if locked:
            if not password:
                doc.close()
                raise PasswordError(True)
            if not doc.authenticate(password):
                doc.close()
                raise PasswordError(False)
        # Eski surumle kaydedilmis belgelerde yazdigimiz metnin bosluk / tire kodlari yanlis
        # (bkz. pdf_tounicode). Sayfa okunmadan ONCE duzeltilir ki duzenleme kutusu ve arama da
        # dogru kodu gorsun; dosyaya ilk kayitta yansir (belge "degisti" sayilmaz).
        try:
            if doc.xref_length() < 200000:
                pdf_tounicode.repair(doc)
        except Exception:
            pass
        self.doc = doc
        self._k_cache, self._look_memo = {}, {}
        self.password = password if locked else None
        # Acma parolasi OLMAYAN ama sahibinin duzenleme / kopyalama izinlerini kisitladigi belge.
        # Sahip parolasini bilmedigimiz icin ayni korumayla yeniden kaydedemeyiz: kaydedilen
        # dosyada kisitlama OLMAZ. Arayuz kaydetmeden once sorar (audit 2026-10-12).
        self.restricted = (not locked) and bool((doc.metadata or {}).get("encryption"))
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
        self._k_cache, self._look_memo = {}, {}
        self.password = None
        self.restricted = False
        self.path = None
        self.suggested_path = suggested_path
        self.undo_stack = []
        self.redo_stack = []
        self._undo_group = None
        self.dirty = True
        self._invalidate()

    def page_count(self):
        return len(self.doc) if self.doc else 0

    def set_password(self, password):
        """Acma parolasini ayarla (None / bos: korumayi kaldir). Bir sonraki KAYITTA gecerli olur."""
        self.password = password or None
        self.dirty = True

    def _save_options(self, compress=None):
        """Kayit secenekleri: parola (AES-256) + kucultme duzeyine gore sikistirma."""
        opts = {"garbage": 4, "deflate": True}
        if compress:
            opts.update(deflate_images=True, deflate_fonts=True, use_objstms=1)
        if self.password:
            opts.update(encryption=fitz.PDF_ENCRYPT_AES_256, user_pw=self.password, owner_pw=self.password)
        return opts

    def _reopen(self, target):
        doc = fitz.open(target)
        if doc.needs_pass and self.password:
            doc.authenticate(self.password)
        return doc

    def save(self, path, compress=None):
        """Kaydeder. garbage=4 + deflate: tekrarli duzenlemelerden arta kalan
        olu nesneleri temizler ve dosyayi sikistirir -> cikti sismez.

        compress ("light" / "medium" / "strong", bkz. COMPRESS_LEVELS): KUCULTEREK kaydet.
        Yuksek cozunurluklu resimler dusurulup yeniden sikistirilir (yazi ve cizimlere
        dokunulmaz). Kayittan sonra calisilan belge kaydedilen dosyadan yeniden acilir (yoksa
        bellekteki buyuk hali bir sonraki "Kaydet"te dosyayi yine buyuturdu) ve geri-al
        gecmisi sifirlanir.

        Var olan bir dosyanin (acik belgenin kendisi dahil) uzerine yazarken
        once gecici dosyaya yazilir, sonra yerine konur: yarida kalan bir
        kayit orijinali bozmaz. (Eski artimli kayit, 'Farkli Kaydet' ya da
        geri-al sonrasi ayni dosyaya kaydederken hata veriyordu.)"""
        target = os.path.abspath(path)
        backed = bool(self.doc.name) and os.path.abspath(self.doc.name) == target

        # Bekleyen bulanik alanlar kaydederken KALICI uygulanir (alttaki icerik
        # silinir). Geri-al ile kayit oncesi duzenlenebilir hale donulebilir.
        # Hata olursa kayit durmali: bulaniklastirilmamis dosya yazilmasin.
        try:
            self.last_finalized = self.finalize_blurs()
        except Exception as ex:
            raise RedactionError(str(ex)) from ex
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
        # (kirpmadan ONCE: yazi tipi dosyasi henuz eksiksiz, hangi kodun hangi harf sekline gittigi
        # ondan okunur. Sonra okunamaz. Duzeltilmezse kaydedilen dosyadan kopyalanan / baska
        # programda aranan yazida bosluklar U+00A0, tireler U+00AD olur.)
        try:
            pdf_tounicode.repair(out)
        except Exception:
            pass
        try:
            out.subset_fonts()
        except Exception:
            pass

        level = COMPRESS_LEVELS.get(compress) if compress else None
        if level:
            thr, target_dpi, quality = level
            try:
                out.rewrite_images(dpi_threshold=thr, dpi_target=target_dpi, quality=quality)
            except Exception:
                pass                       # (resim islenemedi: en azindan yapi sikistirilir)
        opts = self._save_options(compress)

        # HER kayit once gecici dosyaya yazilir, basarili olunca hedefin yerine konur. Yeni bir
        # dosyaya dogrudan yazilirsa yarida kalan kayit (disk doldu) klasorde yarim / bozuk bir PDF
        # birakiyordu (2026-10-13).
        # Gecici dosya hedefle AYNI klasorde (yerine koyma tek adim olsun) ama BENZERSIZ adla:
        # eskiden hep "<ad>.pdf.tmp" idi; klasorde o adla bir dosya varsa ustune yazilip siliniyordu.
        existed = os.path.exists(target)
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(target) + ".", suffix=".tmp",
                                   dir=os.path.dirname(target))
        os.close(fd)
        try:
            out.save(tmp, **opts)
        except BaseException:
            try:
                os.remove(tmp)                     # (yarim yazilmis gecici dosya klasorde kalmasin)
            except OSError:
                pass
            raise
        finally:
            out.close()
        if not existed:
            try:
                os.replace(tmp, target)
            except BaseException:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
        else:
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
                    # gecici dosya parolayla SIFRELI yazildi: dogrulanmazsa calisma belgesi kilitli
                    # kalir, ne gorunur ne duzenlenir ne baska yere kaydedilir (audit 2026-10-12)
                    if self.doc.needs_pass and self.password:
                        self.doc.authenticate(self.password)
                    self._invalidate()
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            if backed:
                self.doc = self._reopen(target)
                self._invalidate()
        if compress and not (os.path.exists(target) and backed):
            # kucultulmus hali calisma belgesi olsun (bkz. docstring)
            try:
                self.doc.close()
            except Exception:
                pass
            self.doc = self._reopen(target)
            self._invalidate()
        if compress:
            self.undo_stack, self.redo_stack = [], []
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
    @staticmethod
    def _extract_dict(page, clip=False, raw=False):
        """Sayfanin kendi yazilari (isaretleme nesneleri haric), SAYFA DISINA TASANLAR DAHIL.

        MuPDF yazi cikarirken sayfa kutusunun disindaki harfleri atar (kirpma bayragi
        kapaliyken bile tamamen disarida kalanlari). Dondurulup ucu disari cikan yazi
        o zaman kirpik okunuyordu ("BETON DENEY RAPORU" -> "N DENEY RAPORU"): harfler
        bir sonraki tasimada kayboluyor, baslangic noktasi da kaydigi icin cerrahi silme
        tutmayip geometrik yedege dusuyor ve KOMSU YAZILARI siliyordu. Bu yuzden yazi
        sayfasi cok genis bir kutuyla kurulur (PyMuPDF'in hazir cagrisi buna izin vermiyor)."""
        # Yalniz YAZI gerekir: resim bloklari istenmez (TEXT_PRESERVE_IMAGES kapali). Acik kalinca
        # MuPDF sayfadaki her resmi de cozup sozluge koyuyordu; taranmis (tam sayfa resim + OCR
        # katmani) sayfada her okuma 150-230 ms suruyordu, simdi ~1 ms. Yazi, kutu ve harf sirasi
        # ayni (olculdu); cagiranlarin hicbiri resim bloklarina bakmiyor.
        base = fitz.TEXTFLAGS_DICT & ~fitz.TEXT_PRESERVE_IMAGES
        # clip: kirpma yolunun disinda kalan (gorunmeyen) harfler atilir - bkz. visible_spans
        flags = base if clip else base & ~fitz.TEXT_MEDIABOX_CLIP
        dl = page.get_displaylist(annots=False)
        try:
            mu = fitz.mupdf
            big = mu.FzRect(-20000, -20000, 20000, 20000)
            raw_page = mu.FzStextPage(big)
            opts = mu.FzStextOptions()
            opts.flags = flags
            dev = mu.fz_new_stext_device(raw_page, opts)
            mu.fz_run_display_list(dl.this, dev, mu.FzMatrix(), big, mu.FzCookie())
            mu.fz_close_device(dev)
            tp = fitz.TextPage(raw_page)
            return tp.extractRAWDICT() if raw else tp.extractDICT()
        except Exception:
            # (baska bir PyMuPDF surumu) eski yol: sayfa disindaki harfler okunmaz
            tp = dl.get_textpage(flags=flags)
            if not isinstance(tp, fitz.TextPage):      # bazi surumler ham nesne dondurur
                tp = fitz.TextPage(tp)
            return tp.extractRAWDICT() if raw else tp.extractDICT()

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
            d = self._extract_dict(page)
        finally:
            if rot:
                page.set_rotation(rot)
        spans = self._spans_from(d, page_num)
        self._span_cache[page_num] = spans
        return spans

    @staticmethod
    def _spans_from(d, page_num):
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
        return spans

    def visible_spans(self, page_num):
        """Sayfada GERCEKTEN gorunen yazilar (arama ve disa aktarim icin).
        get_spans duzenleme icin kirpma yolunun disinda kalan yazilari da okur. Bunlar goz gormez
        ama aramada "bulunur", Excel'de hucreye karisir: bir raporda kirpilmis "1,0" yazisi "25"
        ile ayni hucreye dusup "1.025" oluyordu. Burada sayfa kirpmaya UYARAK (TEXT_CLIP) okunur.
        Ayri bir okuma (tek gecis): get_spans ile karsilastirip elemek iki okuma + n^2 demekti,
        200 sayfalik belgede arama 14 sn suruyordu."""
        cache = self.__dict__.setdefault("_vis_cache", {})
        if page_num not in cache:
            page = self.doc[page_num]
            rot = page.rotation
            if rot:
                page.set_rotation(0)
            try:
                cache[page_num] = self._spans_from(self._extract_dict(page, clip=True), page_num)
            except Exception:
                cache[page_num] = self.get_spans(page_num)
            finally:
                if rot:
                    page.set_rotation(rot)
        return cache[page_num]

    def replace_texts(self, page_num, pairs):
        """Ayni sayfadaki yazilarin metnini TEK geciste degistir. pairs: [(Span, yeni metin)].
        Yazi yerinde (ayni taban noktasi, tip, boyut, renk) yeniden yazilir; boyut KUCULTULMEZ
        (uzun gelen yazi saga uzar). Bos metin: yazi silinir. -> tam bulunamayan yazi tipi sayisi.
        (apply_edit'i tek tek cagirmak her yazi icin sayfa akisini bastan tarar: move_spans'teki
        ayni sorun.)"""
        pairs = [(sp, text) for sp, text in pairs if text != sp.text]
        if not pairs:
            return 0
        self._push_undo()
        page = self.doc[page_num]
        spans = [sp for sp, _ in pairs]
        try:                                                     # akis degismeden: tek tarama
            blends = text_blends_at(self.doc, page, [sp.origin for sp in spans], clean=True)
        except Exception:
            blends = [None] * len(spans)
        self._remove_spans(page, spans)
        items, inexact, checked = [], 0, {}
        for (sp, text), blend in zip(pairs, blends):
            if not text.strip():
                continue
            new = copy.copy(sp)
            new.text = text
            items.append((sp.origin, new, blend))
            key = (sp.font, sp.is_bold)
            if key not in checked:
                checked[key] = self._font_obj_for(page, sp, force_bold=sp.is_bold)[1]
            inexact += 0 if checked[key] else 1
        if items:
            self._write_spans(page, items)
        self._invalidate()
        return inexact

    # paragraf: satir araligi (taban cizgileri arasi) / yazi boyutu bu araliktaysa
    # ayni paragraf olabilir. Form alanlari alt alta ~1,9 kat (ayri kalir), paragraf ~1,15.
    PARA_PITCH = (0.95, 1.6)

    def expand(self, span):
        """Span bir paragrafin satiriysa paragrafin tamamini (Block), degilse kendisini
        dondurur."""
        if span is None or isinstance(span, Block):
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
        # Hesaplar yazinin KENDI yonunde: "x" = yazinin yonu (d), "y" = ona dik (n). Yatay yazida
        # d = (1, 0): sayilar eskisinin aynisi (x = bbox.x0 / x1, y = taban cizgisi). Donuk yazida
        # (2026-10-15) ayni yondeki satirlar ayni kurallarla paragraf olur.
        rot = sp.rotated
        d = tuple(sp.direction) if rot else (1.0, 0.0)
        n = (-d[1], d[0])

        def kin(s):                                    # ayni yondeki yazi
            if not rot:
                return not s.rotated
            return abs(s.direction[0] - d[0]) < 0.01 and abs(s.direction[1] - d[1]) < 0.01

        def yv(s):                                     # taban cizgisinin "yuksekligi"
            return s.origin[0] * n[0] + s.origin[1] * n[1]

        ext_memo = {}

        def ext(s):                                    # satirin bas / son kenari, yazinin yonunde
            if not rot:
                return s.bbox.x0, s.bbox.x1
            got = ext_memo.get(id(s))
            if got is None:
                q = s.quad()
                a_, b_ = q[0].x * d[0] + q[0].y * d[1], q[1].x * d[0] + q[1].y * d[1]
                got = ext_memo[id(s)] = (min(a_, b_), max(a_, b_))
            return got
        same = [s for s in spans if kin(s) and s.font == sp.font and abs(s.size - size) < 0.05
                and s.color == sp.color and s.alpha == sp.alpha]

        def alone(s):
            """Satirda yapisik baska yazi parcasi yok (karisik bicimli satir paragrafa girmez)."""
            for o in spans:
                if o is s or not kin(o) or abs(yv(o) - yv(s)) > size * 0.3:
                    continue
                (s0, s1), (o0, o1) = ext(s), ext(o)
                gap = max(o0 - s1, s0 - o1)
                if gap < size * 0.6:
                    return False
            return True

        def aligned(a, b):
            (a0, a1), (b0, b1) = ext(a), ext(b)
            modes = []
            if abs(a0 - b0) <= 1.5:
                modes.append("left")
            if abs((a0 + a1) - (b0 + b1)) <= 3.0:
                modes.append("center")
            if abs(a1 - b1) <= 1.5:
                modes.append("right")
            return modes

        paths = None

        def separated(a, b):
            """Iki satirin arasinda satira paralel bir cizgi (tablo satiri) var mi."""
            nonlocal paths
            if paths is None:
                try:
                    if not rot:
                        paths = [(it.bbox.y0, it.bbox.x0, it.bbox.x1) for it in self.get_paths(pno)
                                 if it.bbox.height < 1.5]
                    else:                              # (donuk: cizimin noktalari yazinin yonunde)
                        paths = []
                        for it in self.get_paths(pno):
                            pts = [p for poly, _closed in it.polys for p in poly]
                            if not pts:
                                continue
                            vs = [p.x * n[0] + p.y * n[1] for p in pts]
                            if max(vs) - min(vs) < 1.5:
                                us = [p.x * d[0] + p.y * d[1] for p in pts]
                                paths.append((min(vs), min(us), max(us)))
                except Exception:
                    paths = []
            top, bot = sorted((a, b), key=yv)
            if not rot:
                y0, y1 = top.bbox.y1 - 0.8, bot.bbox.y0 + 0.8
            else:
                y0 = yv(top) + max(-top.descender, 0.1) * top.size - 0.8
                y1 = yv(bot) - max(bot.ascender, 0.5) * bot.size + 0.8
            x0, x1 = min(ext(a)[0], ext(b)[0]), max(ext(a)[1], ext(b)[1])
            return any(y0 <= py <= y1 and px0 < x1 and px1 > x0 for py, px0, px1 in paths)

        if not alone(sp):
            return None
        lo, hi = self.PARA_PITCH

        def grow(mode):
            """sp'den yukari ve asagi, HEP ayni hizada (mode) ve esit aralikli satirlari topla."""
            lines, pitch = [sp], None
            for down in (True, False):
                cur = sp
                while len(lines) < 60:
                    best, bd = None, None
                    for s in same:
                        if any(s is l for l in lines):
                            continue
                        dy = yv(s) - yv(cur)
                        if (dy > 0) != down or not (lo * size <= abs(dy) <= hi * size):
                            continue
                        if pitch is not None and abs(abs(dy) - pitch) > max(0.6, size * 0.08):
                            continue
                        if mode not in aligned(cur, s):
                            continue
                        if bd is None or abs(dy) < bd:
                            best, bd = s, abs(dy)
                    if best is None or not alone(best) or separated(cur, best):
                        break
                    pitch = pitch if pitch is not None else bd
                    lines.append(best)
                    cur = best
            return lines

        # Hiza modu ilk komsu ciftinden secilirdi; cift hem sola hem ortaya hizaliysa (kisa
        # satirlar) "sol" kazaniyor ve paragraf, HANGI SATIRDAN baslandigina gore degisiyordu:
        # "Beyan / Ed. / Slump / (S/mm)" hucresi ustten 4 satir (ortali), alttan 2 satir (sol)
        # cikiyor, toplu secimde iki paragraf birden gelip alt iki satir IKI KEZ yaziliyordu.
        # Simdi her mod denenir, en cok satiri veren secilir (esitlikte sol > orta > sag).
        lines, mode = [sp], "left"
        for m in ("left", "center", "right"):
            got = grow(m)
            if len(got) > len(lines):
                lines, mode = got, m
        if len(lines) < 2:
            return None
        lines.sort(key=yv)
        return Block(lines, mode)

    @staticmethod
    def unique_spans(spans):
        """Toplu secim icin: her SATIR en cok bir kez (ayni satir iki paragrafin icinde
        gelirse iki kez tasinir / yazilirdi). Buyuk paragraf onceliklidir; baska bir paragrafla
        kismen cakisanin yalnizca disarida kalan satirlari tek tek eklenir. Sira korunur."""
        def key(ln):
            return (ln.page_num, round(ln.origin[0], 2), round(ln.origin[1], 2), ln.text)

        def lines_of(sp):
            return sp.lines if isinstance(sp, Block) else [sp]
        order = sorted(range(len(spans)), key=lambda i: -len(lines_of(spans[i])))
        covered, keep = set(), {}
        for i in order:
            lns = lines_of(spans[i])
            ks = [key(ln) for ln in lns]
            if not any(k in covered for k in ks):
                keep[i] = [spans[i]]
                covered.update(ks)
            else:
                rest = [ln for ln, k in zip(lns, ks) if k not in covered]
                keep[i] = rest
                covered.update(key(ln) for ln in rest)
        return [sp for i in range(len(spans)) for sp in keep.get(i, [])]

    def spans_in_rect(self, page_num, rect, inside=False):
        """Alan cizerek secme. inside=False: rect'e DEGEN yazilar; inside=True: TAMAMI rect'in
        icinde kalanlar. Paragrafin bir satiri seciliyorsa paragrafin tamami gelir (inside'da
        paragrafin tamami icerideyse); her yazi bir kez."""
        rect = fitz.Rect(rect)
        rect.normalize()

        def box(sp):
            q = sp.quad()
            return fitz.Rect(min(p.x for p in q), min(p.y for p in q), max(p.x for p in q), max(p.y for p in q))
        out, seen = [], set()
        for s in self.get_spans(page_num):
            if not box(s).intersects(rect):
                continue
            e = self.expand(s)
            if inside and not rect.contains(box(e)):
                continue
            key = (round(e.origin[0], 2), round(e.origin[1], 2), e.text)
            if key not in seen:
                seen.add(key)
                out.append(e)
        return self.unique_spans(out)

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
        # (yazi tipi degistirilirken ozgun yazinin italikligi korunur; kalinlik "Kalin" kutusundan)
        italic = detect_style(span.font)[1] if font_override else None
        path, bold, italic, exact = resolve_font_path(base_font_name, force_bold=force_bold, force_italic=italic)

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
            fo, exact = fitz.Font("helv"), False          # (acilamadi: "tam bulundu" denmesin)
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
                    blend=None, track=1.0, stretch=1.0, wrapped=False):
        """Metni verilen taban cizgisine yazar. Cok satirli metinde (\\n)
        her satir bir oncekinin line_spacing*boyut kadar altina yazilir.
        direction yatay degilse (dondurulmus filigran vb.) tum blok o aciyla
        dondurulur. opacity < 1 ise yari saydam yazilir.
        align: 'left' / 'center' / 'right'. ref_width verilirse (duzenlenen eski
        yazinin genisligi) o genislik icinde hizalanir - saga dayalida SAG UC, ortalida
        orta sabit kalir; verilmezse origin yazinin basi / ortasi / sonu olur.
        wrapped: cagiran sayfayi bu yazimlardan once BIR KEZ sardi (ensure_wrapped); TextWriter'in
        ekledigi her parca kendi q / Q'su icinde oldugundan arada yeniden taramaya gerek yok."""
        if not wrapped:
            ensure_wrapped(self.doc, page)
        tw = fitz.TextWriter(page.rect)
        ox, oy = origin
        self._append_lines(tw, origin, text, font_obj, size, line_spacing, align, ref_width, track, stretch)
        dx, dy = direction
        angle = math.degrees(math.atan2(dy, dx))
        morph = None
        stretched = abs(stretch - 1.0) > 1e-3              # yatay gerdirilmis yazi (bkz. edit_look)
        if abs(angle) >= 0.01:                             # (once gerdir, sonra dondur)
            m = fitz.Matrix(-angle)
            morph = (fitz.Point(ox, oy), fitz.Matrix(stretch, 1) * m if stretched else m)
        elif stretched:
            morph = (fitz.Point(ox, oy), fitz.Matrix(stretch, 1))
        tw.write_text(page, color=color, opacity=max(0.0, min(1.0, opacity)),
                      morph=morph, overlay=overlay)
        if blend:
            self._apply_blend(page, blend, overlay)

    @staticmethod
    def _append_lines(tw, origin, text, font_obj, size, line_spacing=1.2, align="left", ref_width=None,
                      track=1.0, stretch=1.0):
        """Metnin satirlarini yaziciya (TextWriter) ekle; bos degilse True.
        track: harf araligi carpani (1'den farkliysa harfler tek tek, araliklari oranlanarak
        yazilir). stretch: yatay olcek; yaziyi CAGIRAN origin cevresinde olcekleyerek yazar,
        burada yalniz satir kaymalari ona gore duzeltilir."""
        ox, oy = origin
        lh = size * line_spacing
        any_ = False
        tracked = abs(track - 1.0) > 1e-3
        for k, line in enumerate(text.split("\n")):
            if line.strip():
                w = font_obj.text_length(line, fontsize=size) * track * stretch
                if align == "center":
                    off = ((ref_width - w) / 2) if ref_width is not None else -w / 2
                elif align == "right":
                    off = (ref_width - w) if ref_width is not None else -w
                else:
                    off = 0.0
                x = ox + off / stretch
                if tracked:
                    for ch in line:
                        tw.append((x, oy + k * lh), ch, font=font_obj, fontsize=size)
                        x += font_obj.text_length(ch, fontsize=size) * track
                else:
                    tw.append((x, oy + k * lh), line, font=font_obj, fontsize=size)
                any_ = True
        return any_

    @staticmethod
    def text_preview(text, font_obj, size, color, opacity=1.0, line_spacing=1.2, align="left",
                     ref_width=None, scale=1.0, origin_dev=None, angle=0.0, track=1.0, stretch=1.0):
        """Metni _write_text'in yazacagi GIBI (ayni font dosyasi, ayni hizalama, ayni satir
        araligi, ayni aci) saydam zeminli bir goruntuye cizer: yazarken canli onizleme.
        Ekrandaki ile kaydedilecek olan ayni motorla cizildiginden duzenlemeye girince yazi
        buyuyup kaymaz.
        Dondurur: (pixmap, ox, oy, box) - (ox, oy): origin'in goruntudeki yeri (px);
        box = (x0, y0, w, h): yazinin DONMEMIS kutusu, origin'e gore (px) - cerceve cizimi icin.
        Yazi bossa None.
        origin_dev: origin'in SAYFA goruntusundeki yeri (aygit pikseli, kesirli). Verilirse
        onizleme, origin ayni alt-piksel konumuna gelecek sekilde cizilir -> tam piksele
        yerlestirilince harf kenarlari sayfadaki cizimle ayni olur (gecis fark edilmez).
        angle: ekranda saat yonunde derece (span_angle ile ayni)."""
        lines = text.split("\n")
        if not any(l.strip() for l in lines):
            return None
        lh = size * line_spacing
        widths = [font_obj.text_length(l, fontsize=size) * track * stretch if l.strip() else 0.0 for l in lines]
        offs = []
        for w in widths:
            if align == "center":
                offs.append(((ref_width - w) / 2) if ref_width is not None else -w / 2)
            elif align == "right":
                offs.append((ref_width - w) if ref_width is not None else -w)
            else:
                offs.append(0.0)
        left = min(offs)
        right = max(o + w for o, w in zip(offs, widths))
        pad = size * 0.45 + 2.0                       # aksanlar / egik harfler kirpilmasin
        asc = max(font_obj.ascender, 0.8) * size
        desc = max(-font_obj.descender, 0.2) * size
        # donmemis kutu, origin'e gore (pay dahil)
        x0, y0 = left - pad, -(asc + pad)
        x1, y1 = right + pad, (len(lines) - 1) * lh + desc + pad
        rotated = abs(angle) >= 0.01
        if rotated:
            a = math.radians(angle)
            ca, sa = math.cos(a), math.sin(a)
            pts = [(x * ca - y * sa, x * sa + y * ca) for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
            bx0, by0 = min(q[0] for q in pts), min(q[1] for q in pts)
            bx1, by1 = max(q[0] for q in pts), max(q[1] for q in pts)
        else:
            bx0, by0, bx1, by1 = x0, y0, x1, y1
        ox, oy = -bx0, -by0
        W, H = bx1 - bx0, by1 - by0
        if origin_dev is not None:
            ox += ((origin_dev[0] - ox * scale) % 1.0) / scale
            oy += ((origin_dev[1] - oy * scale) % 1.0) / scale
            W += 1.0 / scale
            H += 1.0 / scale
        tmp = fitz.open()
        try:
            pg = tmp.new_page(width=max(W, 4), height=max(H, 4))
            tw = fitz.TextWriter(pg.rect)
            tracked = abs(track - 1.0) > 1e-3
            for k, (l, off) in enumerate(zip(lines, offs)):
                if l.strip():
                    x = ox + off / stretch
                    if tracked:                            # (_append_lines ile ayni kural)
                        for ch in l:
                            tw.append((x, oy + k * lh), ch, font=font_obj, fontsize=size)
                            x += font_obj.text_length(ch, fontsize=size) * track
                    else:
                        tw.append((x, oy + k * lh), l, font=font_obj, fontsize=size)
            stretched = abs(stretch - 1.0) > 1e-3
            morph = None
            if rotated:
                m = fitz.Matrix(-angle)
                morph = (fitz.Point(ox, oy), fitz.Matrix(stretch, 1) * m if stretched else m)
            elif stretched:
                morph = (fitz.Point(ox, oy), fitz.Matrix(stretch, 1))
            # (gecici belge, yalniz goruntu: Unicode tablosu duzeltmesi gereksiz - bkz. plain_write_text)
            pdf_tounicode.plain_write_text(tw, pg, color=color, opacity=max(0.0, min(1.0, opacity)), morph=morph)
            pix = pg.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=True)
        finally:
            tmp.close()
        m = max(0.0, pad - 4.0 / scale)                 # cerceve yaziya 4 px payla otursun
        box = ((x0 + m) * scale, (y0 + m) * scale, (x1 - x0 - 2 * m) * scale, (y1 - y0 - 2 * m) * scale)
        return pix, ox * scale, oy * scale, box

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

    def _blend_of(self, page, span, clean=False):
        """Yazinin orijinal karisim modu (duzenleyip yeniden yazarken korunur). clean: ardindan
        yazi silinecekse True (bkz. pdf_content.text_blend_at): akis islem basina bir kez taranir."""
        first = span.lines[0] if isinstance(span, Block) else span
        try:
            return text_blend_at(self.doc, page, first.origin, clean=clean)
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
        if remove_text_at(self.doc, page, target.run()):
            return
        self._redact_span(page, target)

    def _redact_span(self, page, target):
        """Yedek: geometrik redaction (arka plani koru). Donuk yazida eksen-hizali kutu cok
        buyuktur (kosegeni yazi olan dikdortgen: altindaki her seyi silerdi) -> sadece
        yazinin kendi seridi boyunca kucuk kareler."""
        if target.rotated:
            q = target.quad()
            a, b = (q[0] + q[3]) * 0.5, (q[1] + q[2]) * 0.5      # seridin orta cizgisi
            h = abs(q[3] - q[0])
            n = max(1, int(math.ceil(abs(b - a) / max(h * 0.5, 1.0))))
            for k in range(n + 1):
                c = a + (b - a) * (k / n)
                page.add_redact_annot(fitz.Rect(c.x - h * 0.3, c.y - h * 0.3,
                                                c.x + h * 0.3, c.y + h * 0.3), fill=None)
        else:
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
        blend = self._blend_of(page, span, clean=True)
        # (silmeden once: ozgun yazinin gercek boyu / harf sikligi sayfadan olculur)
        k, track, stretch = self.edit_look(span, font_override, force_bold) if new_text.strip() else (1.0, 1.0, 1.0)
        # Satir araligi ADLANDIRILAN boyutun katidir; yazi ise boyut * k ile yazilir (k = ozgunun
        # gercek harf boyu orani). Bolunmezse paragrafin alt satirlari her duzenlemede k kadar
        # yukari toplanir (wkhtmltopdf belgelerinde k = 0,90: 8 satirda 9 pt - gercek belge testi).
        line_spacing = line_spacing / k if k > 0 else line_spacing
        self._remove_span(page, span)

        if new_text.strip() == "":
            return True  # sadece silme islemi, yazilacak yeni metin yok

        size = (new_size if new_size else span.size) * k
        color = color_rgb if color_rgb else span.color_rgb()
        if opacity is None:
            opacity = span.opacity

        font_obj, exact = self._font_obj_for(page, span, force_bold, font_override)

        if autofit:
            size = self._fit_size(font_obj, new_text, span.bbox, size, span, track * stretch)

        # ONEMLI: tahmini bir taban cizgisi hesaplamiyoruz - PDF'in kendi
        # kaydettigi GERCEK taban cizgisini (origin) kullaniyoruz. Boylece
        # boyut/font degisse de metin hep ayni satirda kalir, asagi kaymaz.
        q = span.quad()
        old_w = abs(q[1] - q[0])              # eski yazinin genisligi (hizalama referansi)
        if isinstance(span, Block) and align == "left":
            align = span.align                # ortali / saga dayali paragraf oyle kalsin
        self._write_text(page, span.origin, new_text, font_obj, size,
                         color, span.direction, opacity, line_spacing,
                         align=align, ref_width=old_w if align != "left" else None, blend=blend,
                         track=track, stretch=stretch)
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

    # ---------- yaziyi GORUNUMUNU BOZMADAN yeniden yazma (tasima / cogaltma) ----------
    KEEP_TOL = 0.025     # dogal genislik gercekten bu orandan fazla sapiyorsa harf harf yazilir

    def _span_chars(self, span):
        """Yazinin harfleri ve her birinin sayfadaki taban noktasi: [(harf, x, y)]; bulunamazsa None.
        Sayfa basina TEK ayrintili okuma (onbellekte; icerik degisince atilir)."""
        pno = span.page_num
        table = self._raw_cache.get(pno)
        if table is None:
            page = self.doc[pno]
            rot = page.rotation
            if rot:
                page.set_rotation(0)
            try:
                d = self._extract_dict(page, raw=True)
            finally:
                if rot:
                    page.set_rotation(rot)
            table = {}
            for block in d.get("blocks", []):
                for line in block.get("lines", []):
                    for sp in line["spans"]:
                        key = (round(sp["origin"][0], 1), round(sp["origin"][1], 1))
                        table[key] = [(c["c"], c["origin"][0], c["origin"][1]) for c in sp["chars"]]
            self._raw_cache[pno] = table
        chars = table.get((round(span.origin[0], 1), round(span.origin[1], 1)))
        if not chars or "".join(c[0] for c in chars) != span.text:
            return None
        return chars

    _T_INK = bytes(1 if v < 160 else 0 for v in range(256))      # bos sayfada: murekkep mi
    _T_ANY = bytes(0 if v == 0 else 1 for v in range(256))       # iki goruntu farkli mi

    def _look(self, span, font_obj):
        """Bu yazi YENIDEN yazilirken ozgun gorunumu en iyi hangi yol veriyor -> (oran, yol).
        oran = harflerin gercek boyu / kayitli punto; yol:
          "chars"   harfler OZGUN konumlarina (wkhtmltopdf: harf araliklari yazi tipinin dogal
                    araligindan dar, kayitli punto da harflerden buyuk),
          "stretch" dogal aralikla ama YATAY gerdirilmis (FastReport: hucreye sigsin diye yazi
                    yatayda %127'ye acilmis; MuPDF puntoyu yatay olcekten verir, harfler basik),
          None      olagan yol (dogal aralik, kayitli punto) en az digerleri kadar iyi.
        Karar olcerek verilir: sayfanin gecici bir KOPYASINDA yazi kaldirilir; oncesi / sonrasi
        goruntunun farki yalniz o yazinin murekkebidir (tablo cizgisi, zemin karismaz). Uc aday
        bos bir sayfada ayni yere cizilir, murekkebi ozgune en cok benzeyen secilir.
        (yazi tipi, punto) basina bir kez olculur."""
        key = (span.font, round(span.size, 1))
        if key in self._k_cache:
            return self._k_cache[key]
        res = (1.0, None)
        try:
            res = self._measure_look(span, font_obj)
        except Exception:
            res = (1.0, None)
        self._k_cache[key] = res
        return res

    def _measure_look(self, span, font_obj):
        ox, oy = span.origin
        text, size = span.text, span.size
        nat = font_obj.text_length(text, fontsize=size)
        real = span.bbox.x1 - ox
        z = max(3.0, min(10.0, 90.0 / size))
        mat = fitz.Matrix(z, z)
        clip = fitz.Rect(span.bbox) + (-2, -size * 0.5, max(2.0, nat - real + 2), size * 0.3)
        tmp = fitz.open()
        try:
            tmp.insert_pdf(self.doc, from_page=span.page_num, to_page=span.page_num)
            pg = tmp[0]
            if pg.rotation:
                pg.set_rotation(0)
            rect = fitz.Rect(pg.rect)
            a = pg.get_pixmap(matrix=mat, clip=clip, colorspace=fitz.csGRAY, annots=False)
            if not remove_text_at(tmp, pg, span.run()):
                return 1.0, None
            b = pg.get_pixmap(matrix=mat, clip=clip, colorspace=fitz.csGRAY, annots=False)
        finally:
            tmp.close()
        if (a.width, a.height) != (b.width, b.height) or a.stride != a.width:
            return 1.0, None
        w, h, n = a.width, a.height, len(a.samples)
        x = int.from_bytes(a.samples, "big") ^ int.from_bytes(b.samples, "big")
        orig = x.to_bytes(n, "big").translate(self._T_ANY)
        mark = b"\x01"

        def top_of(mask):
            return next((y for y in range(h) if mark in mask[y * w:(y + 1) * w]), None)

        def draw(fn):
            """Adayi bos sayfada ayni yere ciz -> murekkep maskesi (olcusu tutmazsa None)."""
            t = fitz.open()
            try:
                bp = t.new_page(width=rect.width, height=rect.height)
                fn(bp)
                pm = bp.get_pixmap(matrix=mat, clip=clip, colorspace=fitz.csGRAY)
                return pm.samples.translate(self._T_INK) if (pm.width, pm.height, pm.stride) == (w, h, w) else None
            finally:
                t.close()

        def differ(mask):
            return bin(int.from_bytes(orig, "big") ^ int.from_bytes(mask, "big")).count("1")

        def plain(bp, fs=size, sx=1.0):
            tw = fitz.TextWriter(bp.rect)
            tw.append((ox, oy), text, font=font_obj, fontsize=fs)
            pdf_tounicode.plain_write_text(
                tw, bp, morph=(fitz.Point(ox, oy), fitz.Matrix(sx, 1)) if abs(sx - 1) > 1e-3 else None)

        m_plain = draw(plain)
        t_orig, t_plain = top_of(orig), (top_of(m_plain) if m_plain else None)
        if m_plain is None or t_orig is None or t_plain is None:
            return 1.0, None
        want, got = oy - (a.y + t_plain) / z, oy - (a.y + t_orig) / z
        if want <= 0.5:
            return 1.0, None
        k = got / want
        if not 0.5 <= k <= 1.5:
            return 1.0, None
        k = round(k, 3)
        score = {None: differ(m_plain)}
        nat_k = font_obj.text_length(text, fontsize=size * k)
        if nat_k > 0:
            m = draw(lambda bp: plain(bp, size * k, real / nat_k))
            if m is not None:
                score["stretch"] = differ(m)
        chars = self._span_chars(span)
        if chars:
            def by_char(bp):
                tw = fitz.TextWriter(bp.rect)
                for c, cx, cy in chars:
                    if c.strip():
                        tw.append((cx, cy), c, font=font_obj, fontsize=size * k)
                pdf_tounicode.plain_write_text(tw, bp)
            m = draw(by_char)
            if m is not None:
                score["chars"] = differ(m)
        best = min(score, key=score.get)
        if best is not None and score[best] > score[None] * 0.8:      # belirgin bicimde daha iyi degilse dokunma
            best = None
        return (k, best) if best is not None else (1.0, None)

    def edit_look(self, span, font_override=None, force_bold=None, font=None):
        """Yazinin ICERIGI duzenlenirken ozgun gorunumu korumak icin -> (boyut carpani, harf
        araligi carpani, yatay olcek); korunacak bir sey yoksa (1, 1, 1).
        Harf harf ya da yatayda gerdirilerek cizilmis yazilarda (bkz. _look) duzenlenen yazi
        dogal aralik ve kayitli puntoyla yazilinca buyuyor, harf aralari aciliyor, komsu
        satirlardan farkli gorunuyordu (kullanici, 2026-10-12). Yeni yazi ozgunun GERCEK boyunda
        ve AYNI siklikta yazilir: harf harf cizilmiste her harfin ilerlemesi ayni oranda
        daraltilir, gerdirilmiste ayni yatay olcek uygulanir. Boyut kutusundaki sayi belgenin
        kendi (kayitli) olceginde kalir; carpan ona uygulanir.
        Yalniz yazi tipi ve kalinlik DEGISTIRILMEDIYSE ve yazi tipi aynen bulunduysa.
        Onizleme (arayuz) ve apply_edit ayni degerleri kullanir. SILMEDEN ONCE cagrilmali.
        font: (yazi tipi nesnesi, aynen bulundu mu) - verilmezse burada yuklenir.
        DONUK yazida olcum yapilamaz (yatay yaziya gore kurulu): yazinin boyu dogal boyundan
        farkliysa harf araligi ayni oranda ayarlanir (boyut ve yatay olcek degismez). Bizim
        dondurdugumuz yazi zaten gercek boyunda yazildigi icin bu yeterli."""
        try:
            if font_override or (force_bold is not None and bool(force_bold) != span.is_bold):
                return 1.0, 1.0, 1.0
            lines = span.lines if isinstance(span, Block) else [span]
            if any(not ln.text.strip() for ln in lines):
                return 1.0, 1.0, 1.0
            font_obj, exact = font if font is not None else self._font_obj_for(
                self.doc[span.page_num], span, force_bold=span.is_bold)
            if not exact:
                return 1.0, 1.0, 1.0
            if any(ln.rotated for ln in lines):
                if isinstance(span, Block):
                    # donuk paragraf: satirlarin gercek boyu dogal boyundan DARSA ayni siklik korunur
                    nat = sum(font_obj.text_length(ln.text, fontsize=ln.size) for ln in lines)
                    real = sum(abs(ln.quad()[1] - ln.quad()[0]) for ln in lines)
                    r = real / nat if nat > 0 else 1.0
                    return (1.0, r, 1.0) if (0.4 <= r < 1.0 and abs(r - 1.0) > self.KEEP_TOL) else (1.0, 1.0, 1.0)
                q = span.quad()
                nat = font_obj.text_length(span.text, fontsize=span.size)
                real = abs(q[1] - q[0])
                if nat <= 0 or abs(real / nat - 1.0) <= self.KEEP_TOL:
                    return 1.0, 1.0, 1.0
                memo = self._look_memo.get(self._memo_key(span.page_num, span.origin))
                if memo is not None:                   # bizim dondurdugumuz yazi: nasil yazdiysak oyle
                    track, stretch = memo
                    # (gerdirilmis yazida MuPDF'in verdigi punto = harf boyu x kok(yatay olcek))
                    return (stretch ** -0.5 if abs(stretch - 1.0) > 1e-3 else 1.0), track, stretch
                # Bilinmeyen donuk yazi: DAR aralik korunur. Genis olan (harf arasi acik mi, yatayda
                # gerdirilmis mi ayirt edilemez) dogal aralikla yazilir: acik aralik kelimelerin
                # arasina sahte bosluk okutabiliyor.
                r = self._track_of(font_obj, span.text, span.size, real, nat, 1.0)
                return (1.0, r, 1.0) if 0.4 <= r < 1.0 else (1.0, 1.0, 1.0)
            nat = sum(font_obj.text_length(ln.text, fontsize=ln.size) for ln in lines)
            real = sum(ln.bbox.x1 - ln.origin[0] for ln in lines)
            if nat <= 0 or real <= 0 or abs(real / nat - 1.0) <= self.KEEP_TOL:
                return 1.0, 1.0, 1.0
            k, how = self._look(max(lines, key=lambda ln: len(ln.text.strip())), font_obj)
            if how is None:
                return 1.0, 1.0, 1.0
            if how == "chars":
                ln = lines[0] if len(lines) == 1 else None
                f = self._track_of(font_obj, ln.text, ln.size, real, nat, k) if ln is not None else real / (nat * k)
            else:
                f = real / (nat * k)
            if not 0.4 <= f <= 2.5:
                return 1.0, 1.0, 1.0
            return (k, f, 1.0) if how == "chars" else (k, 1.0, f)
        except Exception:
            return 1.0, 1.0, 1.0

    @staticmethod
    def _memo_key(pno, origin):
        return (pno, round(origin[0], 1), round(origin[1], 1))

    def _memo_look(self, pno, origin, track, stretch, rotated):
        """Donuk yazdigimiz yazinin harf araligini / yatay olcegini hatirla (bkz. edit_look)."""
        key = self._memo_key(pno, origin)
        if rotated and (abs(track - 1.0) > 1e-3 or abs(stretch - 1.0) > 1e-3):
            self._look_memo[key] = (track, stretch)
        else:
            self._look_memo.pop(key, None)

    @staticmethod
    def _track_of(font_obj, text, size, real, nat, k):
        """Harf araligi carpani. MuPDF yazinin boyunu "son harfin baslangici + son harfin DOGAL
        genisligi" diye verir; araliklari daraltilmis yazida son harfin payi daralmamis gorunur.
        Hesaba katilmazsa her yeniden yazista (dondur, tasi, duzenle ...) yazi ~%1 uzuyordu.
        Carpan, son harf disindaki ilerlemelerden hesaplanir."""
        t = text.rstrip() or text
        last = font_obj.text_length(t[-1], fontsize=size) if t else 0.0
        tail = font_obj.text_length(text[len(t):], fontsize=size) if len(t) < len(text) else 0.0
        body = nat - last - tail
        if body <= 0:
            return real / (nat * k)
        return (real - last - tail) / (body * k)

    def _keep_layout(self, span, font_obj, exact):
        """Yazi DEGISMEDEN yeniden yazilacaksa (tasima, cogaltma): satir basina bir tarif
        [("chars", boyut, [(harf, x, y)]) | ("stretch", boyut, yatay olcek, yazi, (x, y)), ...]
        ya da None = olagan yol (dogal aralikla, kayitli puntoyla).
        Yalniz yazi tipi AYNEN bulunduysa (baska yazi tipinin harfleri ozgune oturmaz) ve yazinin
        gercek genisligi dogal genisliginden farkliysa devreye girer; hangi yolun ozgune daha cok
        benzedigi olculur (bkz. _look). SILMEDEN ONCE cagrilmali (harf konumlari sayfadan okunur)."""
        if not exact:
            return None
        lines = span.lines if isinstance(span, Block) else [span]
        off = False
        for ln in lines:
            if ln.rotated or not ln.text.strip():
                return None
            nat = font_obj.text_length(ln.text, fontsize=ln.size)
            real = ln.bbox.x1 - ln.origin[0]
            if nat <= 0 or real <= 0:
                return None
            off = off or abs(real / nat - 1.0) > self.KEEP_TOL
        if not off:
            return None
        keep = []
        for ln in lines:
            k, how = self._look(ln, font_obj)
            if how == "chars":
                chars = self._span_chars(ln)
                if chars is None or any(c.strip() and not font_obj.has_glyph(ord(c)) for c, _, _ in chars):
                    return None
                keep.append(("chars", ln.size * k, chars))
            elif how == "stretch":
                nat_k = font_obj.text_length(ln.text, fontsize=ln.size * k)
                if nat_k <= 0:
                    return None
                keep.append(("stretch", ln.size * k, (ln.bbox.x1 - ln.origin[0]) / nat_k, ln.text, ln.origin))
            else:
                return None
        return keep

    def _write_keep(self, page, keep, dx, dy, font_obj, color, opacity=1.0, blend=None, tw=None):
        """_keep_layout tarifini (dx, dy) kaydirarak yaz. tw verilirse harf harf yazilanlar o ortak
        yaziciya eklenir (yazmayi cagiran yapar) -> eklendi mi; verilmezse burada yazilir."""
        ensure_wrapped(self.doc, page)
        opacity = max(0.0, min(1.0, opacity))
        own = tw is None
        if own:
            tw = fitz.TextWriter(page.rect)
        used = False
        for item in keep:
            if item[0] == "chars":
                for c, x, y in item[2]:
                    if c not in "\r\n":
                        tw.append((x + dx, y + dy), c, font=font_obj, fontsize=item[1])
                        used = True
            else:                                              # yatay gerdirilmis: kendi yazicisi + olcek
                _, fs, sx, text, (ox, oy) = item
                one = fitz.TextWriter(page.rect)
                one.append((ox + dx, oy + dy), text, font=font_obj, fontsize=fs)
                one.write_text(page, color=color, opacity=opacity, overlay=True,
                               morph=(fitz.Point(ox + dx, oy + dy), fitz.Matrix(sx, 1)))
                if blend:
                    self._apply_blend(page, blend, True)
        if own and used:
            tw.write_text(page, color=color, opacity=opacity, overlay=True)
            if blend:
                self._apply_blend(page, blend, True)
        return used

    def move_span(self, span: Span, dx, dy, group=None):
        """Var olan bir metni x/y yonunde kaydirir. Eski konumdan siler, yeni
        konuma ayni font/boyut/renk/opaklikla yeniden yazar ve guncel
        Span'i dondurur. group: bkz. _push_undo (ok tusu kaydirmalari)."""
        self._push_undo(group)
        page = self.doc[span.page_num]
        blend = self._blend_of(page, span, clean=True)
        font_obj, exact = self._font_obj_for(page, span, force_bold=span.is_bold)
        keep = self._keep_layout(span, font_obj, exact)        # (silmeden once: harf konumlari)
        k, track, stretch = (1.0, 1.0, 1.0) if keep is not None else self.edit_look(span, font=(font_obj, exact))
        self._remove_span(page, span)
        new = span.moved(dx, dy)
        if span.rotated and not isinstance(span, Block):
            self._look_memo.pop(self._memo_key(span.page_num, span.origin), None)
            self._memo_look(span.page_num, new.origin, track, stretch, True)
        if keep is not None:
            self._write_keep(page, keep, dx, dy, font_obj, span.color_rgb(), span.opacity, blend)
        else:
            self._write_text(page, new.origin, span.text, font_obj, span.size * k,
                             span.color_rgb(), span.direction, span.opacity,
                             blend=blend, track=track, stretch=stretch, **self._block_layout(span, k))
        return new

    # ---------- toplu islemler (birden cok yazi tek geciste) ----------
    def _remove_spans(self, page, spans):
        """Yazilari TEK taramada kaldir (paragraflar satirlarina acilir). Akista bulunamayan
        olursa onun icin geometrik yedege dusulur."""
        lines = [ln for sp in spans for ln in (sp.lines if isinstance(sp, Block) else [sp])]
        if not lines:
            return
        done = remove_texts_each(self.doc, page, [ln.run() for ln in lines])
        for ln, ok in zip(lines, done):
            if not ok:
                self._redact_span(page, ln)

    def _write_spans(self, page, items, keeps=None, looks=None, fonts=None):
        """items: [(taban noktasi, kaynak span, karisim modu)]. Ayni renk + opakliktaki duz
        yazilar TEK yaziciyla (tek icerik akisi, font bir kez gomulur) yazilir; donuk ya da
        karisim modlu olanlar tek tek (_write_text). keeps: items ile ayni sirada _keep_layout
        sonuclari (None = olagan yol). fonts: items ile ayni sirada yazi tipi nesneleri (kopyala /
        yapistir: kaynak belgede bulunmus olan; verilmezse burada, bu sayfaya gore bulunur)."""
        ensure_wrapped(self.doc, page)
        found, writers = {}, {}

        # AYNI satirdaki (ayni taban cizgisi, yazi tipi, boyut) iki ayri yazi ayni yaziciya
        # eklenirse MuPDF onlari TEK yazi komutunda birlestirir ("Ortam ... Beton"). Sonra
        # yalniz birini kaldirmak (tasima onizlemesi, tek yazi tasima / duzenleme) komutundan
        # yapilamaz: onizleme dusuyor, gercek islem geometrik yedege (redaction) dusup komsu
        # yazinin harflerini de siliyordu (2026-10-14). Satiri cakisan yazi baska yaziciya gider.
        def writer_for(base, rows):
            lst = writers.setdefault(base, [])
            for w_ in lst:
                if not (w_[2] & rows):
                    w_[2] |= rows
                    return w_
            w_ = [fitz.TextWriter(page.rect), False, set(rows)]
            lst.append(w_)
            return w_
        for n, (origin, sp, blend) in enumerate(items):
            if fonts is not None:
                fo = fonts[n]
            else:
                fk = (sp.font, sp.is_bold)
                if fk not in found:
                    found[fk] = self._font_obj_for(page, sp, force_bold=sp.is_bold)[0]
                fo = found[fk]
            layout = self._block_layout(sp, (looks[n] if looks else (1.0,))[0])
            keep = keeps[n] if keeps else None
            if keep is not None and blend:
                self._write_keep(page, keep, origin[0] - sp.origin[0], origin[1] - sp.origin[1], fo,
                                 sp.color_rgb(), sp.opacity, blend)
                continue
            if keep is not None:
                key = (tuple(round(c, 4) for c in sp.color_rgb()), round(max(0.0, min(1.0, sp.opacity)), 3))
                dy = origin[1] - sp.origin[1]
                tw = writer_for(key, {(id(fo), round(it[1], 2), round(c[2] + dy, 1))
                                      for it in keep if it[0] == "chars" for c in it[2][:1]})
                if self._write_keep(page, keep, origin[0] - sp.origin[0], origin[1] - sp.origin[1], fo,
                                    sp.color_rgb(), sp.opacity, None, tw[0]):
                    tw[1] = True
                continue
            k, track, stretch = looks[n] if looks else (1.0, 1.0, 1.0)      # (bkz. edit_look)
            if blend or abs(self.span_angle(sp)) >= 0.01 or abs(stretch - 1.0) > 1e-3:
                # (sayfa yukarida bir kez sarildi: her donuk yazida yeniden tarama yok - donmus
                #  tabloyu tasimak duz tablodan gozle gorulur yavasti, kullanici 2026-10-15)
                self._write_text(page, origin, sp.text, fo, sp.size * k, sp.color_rgb(), sp.direction,
                                 sp.opacity, blend=blend, track=track, stretch=stretch, wrapped=True, **layout)
                continue
            key = (tuple(round(c, 4) for c in sp.color_rgb()), round(max(0.0, min(1.0, sp.opacity)), 3))
            lh = sp.size * k * layout.get("line_spacing", 1.2)
            tw = writer_for(key, {(id(fo), round(sp.size * k, 2), round(origin[1] + j * lh, 1))
                                  for j, ln in enumerate(sp.text.split(chr(10))) if ln.strip()})
            if self._append_lines(tw[0], origin, sp.text, fo, sp.size * k, track=track, **layout):
                tw[1] = True
        for (color, opacity), lst in writers.items():
            for tw, used, _ in lst:
                if used:
                    tw.write_text(page, color=color, opacity=opacity, overlay=True)

    def move_spans(self, spans, dx, dy, group=None):
        """Birden cok yaziyi (ayni sayfada) TEK geciste kaydirir -> guncel Span'ler.
        move_span'i tek tek cagirmak her yazi icin sayfa akisini bastan tarayip yeniden
        yaziyordu (80 yazilik tabloda 10+ sn)."""
        spans = self.unique_spans(list(spans))   # (ayni satir iki kez gelirse iki kez YAZILIRDI: cogalma)
        if not spans:
            return []
        self._push_undo(group)
        page = self.doc[spans[0].page_num]
        try:                                                     # akis degismeden: tek tarama
            blends = text_blends_at(self.doc, page, [(sp.lines[0] if isinstance(sp, Block) else sp).origin
                                                     for sp in spans], clean=True)
        except Exception:
            blends = [None] * len(spans)
        keeps, looks, fonts = [], [], {}                         # (silmeden once: harf konumlari)
        for sp in spans:
            keep, look = None, (1.0, 1.0, 1.0)
            try:
                fk = (sp.font, sp.is_bold)
                if fk not in fonts:
                    fonts[fk] = self._font_obj_for(page, sp, force_bold=sp.is_bold)
                keep = self._keep_layout(sp, *fonts[fk])
                if keep is None:
                    look = self.edit_look(sp, font=fonts[fk])
            except Exception:
                keep, look = None, (1.0, 1.0, 1.0)
            keeps.append(keep)
            looks.append(look)
        self._remove_spans(page, spans)
        moved = [sp.moved(dx, dy) for sp in spans]
        for sp, new, look in zip(spans, moved, looks):
            if sp.rotated and not isinstance(sp, Block):
                self._look_memo.pop(self._memo_key(sp.page_num, sp.origin), None)
                self._memo_look(sp.page_num, new.origin, look[1], look[2], True)
        self._write_spans(page, [(n.origin, sp, bl) for n, sp, bl in zip(moved, spans, blends)], keeps, looks)
        self._invalidate()
        return moved

    def rotate_spans(self, spans, delta_deg, center, group=None):
        """Birden cok yaziyi (ayni sayfada) ORTAK bir merkez etrafinda delta_deg (ekranda saat yonu)
        dondurur: her yazi hem YERINI hem ACISINI degistirir, grup dagilmaz (yalniz acilari
        cevirmek yazilari kendi yerlerinde dondurur, tablo bozulurdu). Hepsi tek geciste silinir;
        her biri rotate_span gibi (ayni font / boyut / renk / opaklik / harf araligi / paragraf
        duzeni) yeni yerine yeni aciyla yazilir -> guncel Span'ler (verilen sirayla)."""
        spans = self.unique_spans(list(spans))
        if not spans:
            return []
        self._push_undo(group)
        page = self.doc[spans[0].page_num]
        c = fitz.Point(center)
        a = math.radians(delta_deg)
        ca, sa = math.cos(a), math.sin(a)

        def rot(p):
            dx, dy = p[0] - c.x, p[1] - c.y
            return (c.x + dx * ca - dy * sa, c.y + dx * sa + dy * ca)
        try:                                                     # akis degismeden: tek tarama
            blends = text_blends_at(self.doc, page, [(sp.lines[0] if isinstance(sp, Block) else sp).origin
                                                     for sp in spans], clean=True)
        except Exception:
            blends = [None] * len(spans)
        fonts, prep = {}, []                                     # (silmeden once: yazi tipi, gercek boyu)
        for sp in spans:
            fk = (sp.font, sp.is_bold)
            if fk not in fonts:
                fonts[fk] = self._font_obj_for(page, sp, force_bold=sp.is_bold)
            try:
                look = self.edit_look(sp, font=fonts[fk])
            except Exception:
                look = (1.0, 1.0, 1.0)
            prep.append((fonts[fk][0], look))
        self._remove_spans(page, spans)
        # Sayfa bir kez sarilir; her yazida yeniden sarma kontrolu butun akisi bastan tariyordu
        # (88 yazilik tabloda 3 sn; olculdu 2026-10-15)
        ensure_wrapped(self.doc, page)
        out = []
        for sp, blend, (font_obj, (k, track, stretch)) in zip(spans, blends, prep):
            dx, dy = sp.direction
            new_dir = (dx * ca - dy * sa, dx * sa + dy * ca)
            if abs(new_dir[1]) < 1e-9:              # tam yatay/dikey: kayan nokta hatasi birakma
                new_dir = (math.copysign(1.0, new_dir[0]), 0.0)
            elif abs(new_dir[0]) < 1e-9:
                new_dir = (0.0, math.copysign(1.0, new_dir[1]))
            new_origin = rot(sp.origin)
            self._write_text(page, new_origin, sp.text, font_obj, sp.size * k, sp.color_rgb(), new_dir,
                             sp.opacity, blend=blend, track=track, stretch=stretch, wrapped=True,
                             **self._block_layout(sp, k))
            if not isinstance(sp, Block):
                self._look_memo.pop(self._memo_key(sp.page_num, sp.origin), None)
                self._memo_look(sp.page_num, new_origin, track, stretch, abs(new_dir[1]) > 0.01)
            corners = [rot(p) for p in sp.quad()]
            bb = fitz.Rect(min(p[0] for p in corners), min(p[1] for p in corners),
                           max(p[0] for p in corners), max(p[1] for p in corners))
            out.append(Span(sp.text, bb, sp.font, sp.size * k, sp.color, sp.page_num, new_origin,
                            new_dir, sp.alpha, sp.flags, sp.ascender, sp.descender))
        self._invalidate()
        return out

    def delete_spans(self, spans):
        """Birden cok yaziyi (ayni sayfada) TEK geciste siler."""
        spans = list(spans)
        if not spans:
            return
        self._push_undo()
        self._remove_spans(self.doc[spans[0].page_num], spans)
        self._invalidate()

    def duplicate_span(self, span: Span, dx=0.0, dy=0.0, page_num=None):
        """Yazinin bir KOPYASINI (ayni font/boyut/renk/opaklik/aci) yazar; asli yerinde kalir.
        page_num verilirse o sayfaya (kopyala -> baska sayfada yapistir). Yeni Span'i dondurur."""
        self._push_undo()
        pno = span.page_num if page_num is None else page_num
        page = self.doc[pno]
        blend = None
        if 0 <= span.page_num < len(self.doc):
            try:
                blend = self._blend_of(self.doc[span.page_num], span)
            except Exception:
                blend = None
        font_obj, exact = self._font_obj_for(page, span, force_bold=span.is_bold)
        try:
            keep = self._keep_layout(span, font_obj, exact) if 0 <= span.page_num < len(self.doc) else None
        except Exception:
            keep = None
        new = span.moved(dx, dy)
        new.page_num = pno
        for ln in getattr(new, "lines", ()):
            ln.page_num = pno
        if keep is not None:
            self._write_keep(page, keep, dx, dy, font_obj, span.color_rgb(), span.opacity, blend)
        else:
            self._write_text(page, new.origin, span.text, font_obj, span.size,
                             span.color_rgb(), span.direction, span.opacity,
                             blend=blend, **self._block_layout(span))
        return new

    # ---------- kopyala / yapistir (secim, belgeden bagimsiz) ----------
    def snapshot_selection(self, page_num, spans=(), path_indices=(), image_indices=()):
        """Secimi BAGIMSIZ bir Clip olarak kopyala: yazilarin yazi tipi nesnesi, harf konumlari ve
        gorunumu, cizimlerin geometrisi + ayarlari, resimlerin verisi simdi alinir. Belgeye
        dokunulmaz. Kopyalanamayan ogeler clip.skipped'da sayilir (kullaniciya soylenir)."""
        import weakref
        page = self.doc[page_num]
        spans = self.unique_spans([sp for sp in spans if sp.page_num == page_num])
        texts, fonts = [], {}
        try:
            blends = text_blends_at(self.doc, page, [(sp.lines[0] if isinstance(sp, Block) else sp).origin
                                                     for sp in spans], clean=False)
        except Exception:
            blends = [None] * len(spans)
        for sp, blend in zip(spans, blends):
            fk = (sp.font, sp.is_bold)
            if fk not in fonts:
                fonts[fk] = self._font_obj_for(page, sp, force_bold=sp.is_bold)
            fo, exact = fonts[fk]
            try:
                keep = self._keep_layout(sp, fo, exact)
                look = (1.0, 1.0, 1.0) if keep is not None else self.edit_look(sp, font=(fo, exact))
            except Exception:
                keep, look = None, (1.0, 1.0, 1.0)
            texts.append((sp.moved(0.0, 0.0), fo, copy.deepcopy(keep), look, blend))
        skipped = {"path": 0, "image": 0}
        paths = []
        items = self.paths_by_index(page_num, sorted(set(path_indices)))
        if items:
            drawings = page.get_drawings()
            used = set()
            for it in items:
                want = "f" if not it.stroked else ("fs" if it.filled else "s")
                best, bd = None, 1.0
                for k, d in enumerate(drawings):
                    if k in used or d.get("type") != want:
                        continue
                    r = d["rect"]
                    dd = (abs(r.x0 - it.bbox.x0) + abs(r.y0 - it.bbox.y0)
                          + abs(r.x1 - it.bbox.x1) + abs(r.y1 - it.bbox.y1))
                    if dd < bd:
                        best, bd = k, dd
                if best is None or not drawings[best].get("items"):
                    skipped["path"] += 1
                    continue
                used.add(best)
                paths.append(copy.deepcopy(drawings[best]))
        images = []
        for it in self.images_by_index(page_num, sorted(set(image_indices))):
            try:
                if str(self.doc.xref_get_key(it.xref, "ImageMask")[1]).lower() == "true":
                    raise ValueError("stencil")              # rengi o anki dolgudan gelen maske resim
                info = self.doc.extract_image(it.xref)
                data = info["image"]
                mask = None
                if info.get("smask"):
                    mask = self.doc.extract_image(info["smask"])["image"]
                images.append((data, mask, [fitz.Point(p) for p in it.quad]))
            except Exception:
                skipped["image"] += 1
        return Clip(page_num, texts, paths, images, skipped, weakref.ref(self))

    def paste_clip(self, page_num, clip, dx=0.0, dy=0.0):
        """Clip'i (dx, dy) kaydirarak sayfaya yaz: TEK geri-al adimi; yarida hata olursa belge
        eski haline doner (bkz. _atomic). Sirayla cizimler, resimler, yazilar (kaynakta da yazilar
        genelde ustte). -> (yeni yazilar, yeni cizim sira no'lari, yeni resim sira no'lari)."""
        self._push_undo()
        page = self.doc[page_num]
        ensure_wrapped(self.doc, page)
        n_paths = len(self.get_paths(page_num)) if clip.paths else 0
        n_imgs = len(self.get_images(page_num)) if clip.images else 0
        if clip.paths:
            sh = page.new_shape()
            off = fitz.Point(dx, dy)
            for d in clip.paths:
                for it in d["items"]:
                    op = it[0]
                    if op == "l":
                        sh.draw_line(it[1] + off, it[2] + off)
                    elif op == "c":
                        sh.draw_bezier(it[1] + off, it[2] + off, it[3] + off, it[4] + off)
                    elif op == "re":
                        sh.draw_rect(fitz.Rect(it[1]) + (dx, dy, dx, dy))
                    elif op == "qu":
                        q = it[1]
                        sh.draw_quad(fitz.Quad(q.ul + off, q.ur + off, q.ll + off, q.lr + off))
                caps = d.get("lineCap") or (0,)
                sh.finish(color=d.get("color") if "s" in d["type"] else None,
                          fill=d.get("fill") if "f" in d["type"] else None,
                          width=d.get("width") or 0, dashes=d.get("dashes") or None,
                          closePath=bool(d.get("closePath")), even_odd=bool(d.get("even_odd")),
                          stroke_opacity=d.get("stroke_opacity", 1) if d.get("stroke_opacity") is not None else 1,
                          fill_opacity=d.get("fill_opacity", 1) if d.get("fill_opacity") is not None else 1,
                          lineCap=int(max(caps) if isinstance(caps, (tuple, list)) else caps),
                          lineJoin=int(d.get("lineJoin") or 0))
            sh.commit(overlay=True)
        for data, mask, quad in clip.images:
            want = [p + (dx, dy) for p in quad]
            box = fitz.Rect(min(p.x for p in want), min(p.y for p in want),
                            max(p.x for p in want), max(p.y for p in want))
            if box.width < 0.01 or box.height < 0.01:
                continue
            page.insert_image(box, stream=data, mask=mask, keep_proportion=False, overlay=True)
            self.__dict__.setdefault("_image_cache", {}).pop(page_num, None)
            new = self.get_images(page_num)[-1]
            src = [fitz.Point(p) for p in new.quad]
            D = _affine(src, want)                  # yerlestirilen dortgen -> asil dortgen (aci / ayna dahil)
            if D is not None:
                pdf_images._apply(self.doc, page, {new.index: D})
            self.__dict__.setdefault("_image_cache", {}).pop(page_num, None)
        moved = []
        if clip.texts:
            items, keeps, looks, fonts = [], [], [], []
            for sp, fo, keep, look, blend in clip.texts:
                new = sp.moved(dx, dy)
                new.page_num = page_num
                for ln in getattr(new, "lines", ()):
                    ln.page_num = page_num
                items.append((new.origin, sp, blend))
                keeps.append(keep)
                looks.append(look)
                fonts.append(fo)
                if sp.rotated and not isinstance(sp, Block):
                    self._memo_look(page_num, new.origin, look[1], look[2], True)
                moved.append(new)
            self._write_spans(page, items, keeps, looks, fonts=fonts)
        self._invalidate()
        paths = list(range(n_paths, len(self.get_paths(page_num)))) if clip.paths else []
        imgs = list(range(n_imgs, len(self.get_images(page_num)))) if clip.images else []
        return moved, paths, imgs

    @staticmethod
    def _block_layout(span, k=1.0):
        """Paragrafi yeniden yazarken satir araligi ve hizasi aynen korunsun. k: yazi boyut * k ile
        yaziliyorsa (bkz. edit_look) aralik k'ya bolunur ki satirlar yerinde kalsin."""
        if not isinstance(span, Block):
            return {}
        return {"line_spacing": span.line_spacing / (k if k and k > 0 else 1.0), "align": span.align,
                "ref_width": span.length if span.align != "left" else None}

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
        blend = self._blend_of(page, span, clean=True)
        font_obj, exact = self._font_obj_for(page, span, force_bold=span.is_bold)
        # (silmeden once) ozgunun gercek boyu / harf sikligi: dondurunce de ayni kalsin
        k, track, stretch = self.edit_look(span, font=(font_obj, exact))
        self._remove_span(page, span)
        self._write_text(page, new_origin, span.text, font_obj, span.size * k,
                         span.color_rgb(), new_dir, span.opacity, blend=blend, track=track, stretch=stretch,
                         **self._block_layout(span, k))
        if not isinstance(span, Block):
            self._look_memo.pop(self._memo_key(span.page_num, span.origin), None)
            self._memo_look(span.page_num, new_origin, track, stretch, abs(new_dir[1]) > 0.01)
        corners = [rot(p) for p in span.quad()]
        bb = fitz.Rect(min(p[0] for p in corners), min(p[1] for p in corners),
                       max(p[0] for p in corners), max(p[1] for p in corners))
        return Span(span.text, bb, span.font, span.size * k, span.color, span.page_num, new_origin,
                    new_dir, span.alpha, span.flags, span.ascender, span.descender)

    def rotation_preview(self, span, scale):
        """Dondurulurken gorunecek yazi: rotate_span'in YAZACAGI yazinin donmemis hali (ayni yazi
        tipi, boyut carpani, harf araligi, satir araligi, hiza) -> text_preview sonucu | None.
        Surukleme basinda BIR KEZ cizilir; arayuz her fare hareketinde yalniz cevirip koyar."""
        try:
            page = self.doc[span.page_num]
            font_obj, exact = self._font_obj_for(page, span, force_bold=span.is_bold)
            k, track, stretch = self.edit_look(span, font=(font_obj, exact))
            lay = self._block_layout(span, k)
            return self.text_preview(span.text, font_obj, span.size * k, span.color_rgb(), span.opacity,
                                     lay.get("line_spacing", 1.2), lay.get("align", "left"),
                                     lay.get("ref_width"), scale, track=track, stretch=stretch)
        except Exception:
            return None

    def _fit_size(self, font_obj, text, bbox, size, span=None, wf=1.0):
        """Yeni metin kutuya sigmiyorsa boyutu otomatik kucult (cok
        satirlida en uzun satira gore). wf: genislik carpani (harf sikligi x yatay olcek)."""
        box_width = bbox.x1 - bbox.x0
        if span is not None and span.rotated:
            q = span.quad()
            box_width = abs(q[1] - q[0])
        lines = [l for l in text.split("\n") if l.strip()] or [text]
        while size > 4:
            width = max(font_obj.text_length(l, fontsize=size) for l in lines) * wf
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

    # ---------- resim nesneleri (logo, fotograf, grafik) ----------
    BIG_IMAGE = 0.8      # sayfanin bu oranindan buyuk resim "zemin"dir (taranmis sayfa): secilmez

    def get_images(self, page_num):
        cache = self.__dict__.setdefault("_image_cache", {})
        if page_num not in cache:
            try:
                cache[page_num] = pdf_images.page_images(self.doc, self.doc[page_num])
            except Exception:
                cache[page_num] = []
        return cache[page_num]

    def _pickable_images(self, page_num):
        pr = self.doc[page_num].rect
        lim = self.BIG_IMAGE * abs(pr.width * pr.height)
        return [it for it in self.get_images(page_num) if abs(it.bbox.width * it.bbox.height) < lim]

    def image_at(self, page_num, x, y):
        """Noktadaki resim (ustteki oncelikli); sayfayi kaplayan zemin resmi haric."""
        base = self.doc[page_num].transformation_matrix
        pt = fitz.Point(x, y)
        for it in reversed(self._pickable_images(page_num)):
            if it.contains(pt, base):
                return it
        return None

    def images_by_index(self, page_num, indices):
        items = self.get_images(page_num)
        return [items[i] for i in indices if 0 <= i < len(items)]

    def images_in_rect(self, page_num, rect, touch=False):
        r = fitz.Rect(rect)
        r.normalize()
        out = []
        for it in self._pickable_images(page_num):
            b = it.bbox
            if touch:
                ok = b.x0 <= r.x1 and b.x1 >= r.x0 and b.y0 <= r.y1 and b.y1 >= r.y0
            else:
                ok = r.x0 <= b.x0 and b.x1 <= r.x1 and r.y0 <= b.y0 and b.y1 <= r.y1
            if ok:
                out.append(it)
        return out

    def move_images(self, page_num, indices, dx, dy, group=None):
        self._push_undo(group)
        pdf_images.move(self.doc, self.doc[page_num], list(indices), dx, dy)
        self._invalidate()

    def transform_images(self, page_num, indices, matrix, group=None):
        """Secili resimleri sayfa uzayinda matrix ile donusturur (toplu dondurme)."""
        self._push_undo(group)
        pdf_images.transform(self.doc, self.doc[page_num], list(indices), matrix)
        self._invalidate()

    def scale_image(self, page_num, index, old, new):
        self._push_undo()
        pdf_images.scale(self.doc, self.doc[page_num], index, old, new)
        self._invalidate()

    def delete_images(self, page_num, indices):
        self._push_undo()
        pdf_images.delete(self.doc, self.doc[page_num], list(indices))
        self._invalidate()

    def replace_image(self, page_num, index, path):
        """Resmi baska bir resim dosyasiyla degistir: ayni yere (oran korunarak) konur."""
        items = self.get_images(page_num)
        if not (0 <= index < len(items)):
            return False
        box = fitz.Rect(items[index].bbox)
        self._push_undo()
        page = self.doc[page_num]
        pdf_images.delete(self.doc, page, [index])
        ensure_wrapped(self.doc, page)
        page.insert_image(box, filename=path, keep_proportion=True, overlay=True)
        self._invalidate()
        return True

    def image_file(self, page_num, index):
        """Resmin ASIL verisi (kalite kaybi yok) -> (bytes, uzanti) | None."""
        items = self.get_images(page_num)
        if not (0 <= index < len(items)):
            return None
        try:
            d = self.doc.extract_image(items[index].xref)
            return d["image"], d.get("ext", "png")
        except Exception:
            return None

    def paths_in_rect(self, page_num, rect, touch=False):
        return pdf_paths.items_in_rect(self.get_paths(page_num), rect, touch)

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
                      color=None, group=None):
        """Secili cizimlerin stilini degistirir (tek geri-al adimi).
        group: art arda gelen kucuk degisiklikler (surguyle kalinlik) tek geri-al adimi (_push_undo).
        color: gorunen renk (konturluysa kontur, dolguluysa dolgu).
        Ince dolgulu seritlerde (Word/Excel tablo cizgileri) width seridin
        enini ayarlar. Uygulanamayan ayarlar icin kullaniciya gosterilecek
        notlarin listesini dondurur."""
        every = self.get_paths(page_num)               # sayfanin butun yollari (items bunlarin icinde)
        items = [every[i] for i in indices if 0 <= i < len(every)]
        if not items:
            return []
        self._push_undo(group)                         # (onbellekleri bosaltir: liste yukarida alindi)
        page = self.doc[page_num]
        edits = pdf_paths.restyle_items(self.doc, page, items, width, stroke, fill, dashed, color)
        notes = []
        fill_only = [it for it in items if not it.stroked]
        bars = [it for it in fill_only if pdf_paths.is_filled_bar(it)]
        if width is not None and bars:
            # akis degisti: yollari (sira numarasi sabit) yeniden ayristirip olcekle
            self._invalidate()
            every = None                               # (seridin geometrisi degisiyor: bastan ayristir)
            fresh = self.paths_by_index(page_num, [it.index for it in bars])
            pairs = [(it, pdf_paths.bar_thickness_matrix(it, width)) for it in fresh]
            pdf_paths.transform_each(self.doc, page, [(it, m) for it, m in pairs if m is not None])
        self._invalidate()
        if every is not None:
            # yalniz stil sarmali eklendi / guncellendi: yollar ayni, bayt konumlari kaydi.
            # Listeyi bastan ayristirmak yerine konumlar guncellenir (bkz. pdf_paths.shift_offsets).
            pdf_paths.shift_offsets(every, edits)
            self._path_cache[page_num] = every
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
        undo0, redo0, dirty0 = list(self.undo_stack), list(self.redo_stack), self.dirty
        with self._undo_guard():
            r = self._blur_apply(page_num, rect, mode, level)
        if r is None:            # alan sayfanin disinda / cok kucuk: degisiklik yok
            self.undo_stack, self.redo_stack, self.dirty = undo0, redo0, dirty0     # (gecmis aynen)
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

    @staticmethod
    def _convex_hit(a, b):
        """Iki disbukey cokgen kesisiyor mu (ayiran eksen testi). Noktalar (x, y)."""
        for poly in (a, b):
            n = len(poly)
            for i in range(n):
                (px, py), (qx, qy) = poly[i], poly[(i + 1) % n]
                nx, ny = qy - py, px - qx
                if nx == 0 and ny == 0:
                    continue
                pa = [nx * x + ny * y for x, y in a]
                pb = [nx * x + ny * y for x, y in b]
                if max(pa) < min(pb) or max(pb) < min(pa):
                    return False
        return True

    def _blur_split(self, sp, area):
        """Korunan yaziyi harflerine ayir -> (alana DEGMEYEN harfler, alana degenler); harf =
        (harf, x, y, kutu). Harf konumlari okunamazsa None (o yazi korunmaz: MuPDF siler).
        Kutu bilerek bol tutulur: suphede harf "alana degiyor" sayilir (yazi olarak geri yazilmaz)."""
        chars = self._span_chars(sp)
        if not chars:
            return None
        dx, dy = sp.direction
        n = math.hypot(dx, dy) or 1.0
        dx, dy = dx / n, dy / n
        ux, uy = dy, -dx                                   # yazinin "yukari" yonu (sayfada y asagi)
        asc = max(sp.ascender, 0.9) * sp.size * 1.1 + 0.5
        desc = max(-sp.descender, 0.25) * sp.size * 1.1 + 0.5
        end = sp.run()[2:4]
        clear, touch = [], []
        for i, (c, x, y) in enumerate(chars):
            ex, ey = (chars[i + 1][1], chars[i + 1][2]) if i + 1 < len(chars) else end
            if (ex - x) * dx + (ey - y) * dy < 0.2:        # (sifir genislik / geri adim: en az bir pay)
                ex, ey = x + dx * sp.size * 0.3, y + dy * sp.size * 0.3
            x0, y0, x1, y1 = x - dx * 0.5, y - dy * 0.5, ex + dx * 0.5, ey + dy * 0.5
            box = [(x0 + ux * asc, y0 + uy * asc), (x1 + ux * asc, y1 + uy * asc),
                   (x1 - ux * desc, y1 - uy * desc), (x0 - ux * desc, y0 - uy * desc)]
            (touch if self._convex_hit(box, area) else clear).append((c, x, y, box))
        return clear, touch

    def _glyph_writer(self, rect, sp, chars, font_obj):
        """Harfleri OZGUN konumlarina yazan yazici + donus (dondurulmus yazi icin)."""
        tw = fitz.TextWriter(rect)
        ox, oy = sp.origin
        angle = self.span_angle(sp)
        rot = abs(angle) >= 0.01
        a = math.radians(angle)
        ca, sa = math.cos(a), math.sin(a)
        used = False
        for c, x, y, _box in chars:
            if not c.strip():
                continue
            if rot:                                        # (yazici duz yazar, sonra origin cevresinde doner)
                rx, ry = x - ox, y - oy
                x, y = ox + rx * ca + ry * sa, oy - rx * sa + ry * ca
            tw.append((x, y), c, font=font_obj, fontsize=sp.size)
            used = True
        morph = (fitz.Point(ox, oy), fitz.Matrix(-angle)) if rot else None
        return (tw, morph) if used else (None, None)

    def _stamp_glyphs(self, page, sp, chars, font_obj, area):
        """Alana DEGEN harflerin alanin DISINDA kalan kismini RESIM olarak geri koy (filigranin dev
        harfi alanin disinda da kesilmis gorunmesin). Resimde alanin ici bosaltilir; yazi olarak
        hicbir sey geri yazilmaz -> alanin icindeki harf dosyadan OKUNAMAZ, kopyalanamaz."""
        from PySide6.QtGui import QImage, QPainter, QPolygonF, QColor
        from PySide6.QtCore import QPointF, QBuffer, QIODevice, Qt
        xs = [p[0] for ch in chars for p in ch[3]]
        ys = [p[1] for ch in chars for p in ch[3]]
        clip = fitz.Rect(min(xs) - 2, min(ys) - 2, max(xs) + 2, max(ys) + 2) & page.rect
        if clip.is_empty or clip.width < 1 or clip.height < 1:
            return
        z = max(1.0, min(4.0, (6_000_000 / (clip.width * clip.height)) ** 0.5))
        tmp = fitz.open()
        try:
            bp = tmp.new_page(width=page.rect.width, height=page.rect.height)
            tw, morph = self._glyph_writer(bp.rect, sp, chars, font_obj)
            if tw is None:
                return
            pdf_tounicode.plain_write_text(tw, bp, color=sp.color_rgb(), opacity=max(0.0, min(1.0, sp.opacity)),
                                           morph=morph)
            pm = bp.get_pixmap(matrix=fitz.Matrix(z, z), clip=clip, alpha=True)
            img = QImage(pm.samples, pm.width, pm.height, pm.stride, QImage.Format_RGBA8888_Premultiplied).copy()
            px, py = pm.x, pm.y
        finally:
            tmp.close()
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing, False)      # (kenar yumusatma alanin icinde iz birakmasin)
        p.setCompositionMode(QPainter.CompositionMode_Clear)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0))
        p.drawPolygon(QPolygonF([QPointF(x * z - px, y * z - py) for x, y in area]))
        p.end()
        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        img.save(buf, "PNG")
        page.insert_image(fitz.Rect(px / z, py / z, (px + img.width()) / z, (py + img.height()) / z),
                          stream=bytes(buf.data()), keep_proportion=False, overlay=True)

    def _blur_apply(self, pno, rect, mode, level, angle=0.0):
        """pdf_blur.apply + alana tasan filigran benzeri yazilarin gorunumunun korunmasi.

        GUVENLIK (audit 2026-10-12): eskiden boyle bir yazi silinmeden once kenara alinip sonra
        BUTUN olarak geri yaziliyordu -> karartilan kismi da dosyada yazi olarak kaliyor, kopyalanip
        okunabiliyordu. Artik:
          * alana DEGMEYEN harfler yazi olarak, ozgun konumlarina geri yazilir;
          * alana DEGEN harfler yazi olarak geri YAZILMAZ; yalniz alanin disinda kalan gorunen
            kismi resim olarak konur (alanin ici resimde bos).
        Yani dosyayi yeniden acip yazi cikarildiginda alanin icinde hicbir harf bulunmaz.
        Harf konumlari okunamayan ya da cerrahi kaldirilamayan yazi korunmaz (MuPDF alana degen
        harfi butun siler: goruntusu kesik kalabilir ama guvenli)."""
        import pdf_blur
        box = fitz.Rect(rect).normalize()
        area = [(p.x, p.y) for p in (pdf_blur.poly(box, angle) if angle else [box.tl, box.tr, box.br, box.bl])]
        plans = []
        for sp in self._blur_protected(pno, box, angle):
            try:
                plan = self._blur_split(sp, area)
            except Exception:
                plan = None
            if plan is not None:
                plans.append((sp, plan))
        done = []

        def before(page):
            for sp, plan in plans:
                blend = self._blend_of(page, sp, clean=True)
                if remove_text_at(self.doc, page, sp.run()):
                    done.append((sp, plan, blend))

        def after(page):
            for sp, (clear, touch), blend in done:
                font_obj = self._base14_font(sp)
                if font_obj is None:
                    font_obj, _ = self._font_obj_for(page, sp, force_bold=sp.is_bold)
                tw, morph = self._glyph_writer(page.rect, sp, clear, font_obj)
                if tw is not None:
                    ensure_wrapped(self.doc, page)
                    tw.write_text(page, color=sp.color_rgb(), opacity=max(0.0, min(1.0, sp.opacity)),
                                  morph=morph, overlay=True)
                    if blend:
                        self._apply_blend(page, blend, True)
                if touch:
                    try:
                        self._stamp_glyphs(page, sp, touch, font_obj, area)
                    except Exception:
                        pass                               # (resim konamadi: yalniz gorunum eksik kalir)

        return pdf_blur.apply(self.doc, pno, rect, mode, level, angle=angle,
                              before_redact=before if plans else None,
                              after_redact=after if plans else None)

    def finalize_blurs(self, page_num=None, mid=None, push_undo=True):
        """Bekleyen (duzenlenebilir) bulanik alanlari kalici uygula: nesne kalkar,
        alttaki yazi/cizim/resim silinir, bulanik goruntu sayfaya islenir.
        Kaydederken ve 'sayfaya isle'de otomatik cagrilir. Uygulanan sayi."""
        todo = [(p, m) for p, m in self.pending_blurs(page_num) if mid is None or m["id"] == mid]
        if not todo:
            return 0
        import pdf_blur      # sadece gerekince (Qt yukler; uygulamada PySide6 zaten once yuklu)
        # GUVENLIK (2026-10-13): isaret once kaldirilip sonra uygulaniyor. Uygulama yarida hata
        # verirse isaret gitmis, alttaki yazi durmus olurdu -> bir sonraki Kaydet "bekleyen
        # karartma yok" sanip gizlenecek yaziyi dosyaya yazardi. Hata olursa belge bu islem
        # baslamadan ONCEKI haline doner: karartma beklemede kalir, kayit yine reddedilir.
        # Geri-al / yinele gecmisi de aynen korunur (bkz. _undo_guard).
        with self._undo_guard(push_undo):
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
        # (hata olursa - karartma uygulanamadi / isleme yarida kaldi - belge ve gecmis eski haline doner)
        with self._undo_guard():
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
            # MuPDF her kelimeye SATIRIN dikey kutusunu verir. Satira tablo cizgisi "|" diye
            # karismissa kutu iki satir boyunda olur, yazi ise ustte durur: taban cizgisini kutunun
            # altina gore koymak kelimeyi bir satir asagiya yaziyordu (arama dogru kelimeyi bulup
            # alt satiri isaretliyordu; tablolu taramada tek gecen 91 kelimenin 9'u). Kutusu
            # yazisindan belirgin yuksek satirlarda yazinin yeri sayfa goruntusundeki murekkepten
            # bulunur: satirin BUTUN kelimeleri birlikte (hepsi ayni taban cizgisinde).
            lines = {}
            for wd in words:
                x0, y0, x1, y1, word = wd[:5]
                if y1 - y0 <= 0 or not word.strip():
                    continue
                unit = helv.text_length(word, fontsize=1.0)
                fit = (x1 - x0) / unit if unit > 0 else (y1 - y0) * 0.85     # genislige oturan boyut
                lines.setdefault(tuple(wd[5:7]), []).append((x0, y0, x1, y1, word, fit))
            ink = None                    # (sayfanin gri goruntusu: yalniz gerekirse, bir kez)
            for ws in lines.values():
                fits = sorted(w[5] for w in ws)
                fit_l = fits[len(fits) // 2]                                  # satirin harf boyu (ortanca)
                y0, y1 = min(w[1] for w in ws), max(w[3] for w in ws)
                h = y1 - y0
                base, tall = None, h > 1.8 * fit_l and not page.rotation
                if tall:
                    if ink is None:
                        ink = self._ocr_ink(page)
                    base = self._ocr_band(ink, [(w[0], w[2]) for w in ws], y0, y1, fit_l)
                for x0, wy0, x1, wy1, word, fit in ws:
                    wh = wy1 - wy0
                    if tall and base is not None:
                        tw.append((x0, base), word, font=helv, fontsize=min(fit, wh))
                    else:                 # kelimeyi tanindigi kutunun genisligine yay
                        tw.append((x0, wy1 - wh * 0.2), word, font=helv, fontsize=min(fit, wh * 1.2))
                    total += 1
            tw.write_text(page, render_mode=3)  # 3 = gorunmez metin
        return total

    _OCR_INK_DPI = 150
    _OCR_DARK = bytes(1 if v < 128 else 0 for v in range(256))

    def _ocr_ink(self, page):
        """Sayfanin gri goruntusu (genislik, yukseklik, satir uzunlugu, pt basina piksel, baytlar)."""
        pm = page.get_pixmap(dpi=self._OCR_INK_DPI, colorspace=fitz.csGRAY, alpha=False)
        return pm.width, pm.height, pm.stride, self._OCR_INK_DPI / 72.0, pm.samples

    def _ocr_band(self, ink, spans, y0, y1, fit):
        """spans [(x0, x1), ...] sutunlarinda, y0..y1 arasinda yazinin taban cizgisi (pt): harf boyu
        kadar yuksek, EN COK murekkep iceren yatay serit. Kutuyu boydan boya gecen dik cizgiler
        (tablo kenari) sayilmaz. Murekkep yoksa None."""
        w, h, stride, sc, data = ink
        py0, py1 = max(0, int(y0 * sc)), min(h, int(y1 * sc) + 1)
        n = py1 - py0
        if n < 3:
            return None
        cnt = [0] * n
        for x0, x1 in spans:
            px0, px1 = max(0, int(x0 * sc)), min(w, int(x1 * sc) + 1)
            if px1 - px0 < 2:
                continue
            rows = [data[y * stride + px0:y * stride + px1].translate(self._OCR_DARK) for y in range(py0, py1)]
            keep = [x for x in range(px1 - px0) if sum(r[x] for r in rows) < 0.8 * n]   # (dik cizgi degil)
            for k, r in enumerate(rows):
                cnt[k] += sum(r[x] for x in keep)
        band = max(2, min(n, int(round(fit * 0.72 * sc))))             # buyuk harf boyu ~ 0,72 em
        best, at, cur = -1, 0, sum(cnt[:band])
        for y in range(0, n - band + 1):
            if y:
                cur += cnt[y + band - 1] - cnt[y - 1]
            if cur > best:
                best, at = cur, y
        if best <= 0:
            return None
        return (py0 + at + band) / sc

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


def _affine(src, dst):
    """Uc noktayi (src[0], src[1], src[3]) dst'dekilere goturen fitz.Matrix | None (dejenere)."""
    (x0, y0), (x1, y1), (x3, y3) = (src[0].x, src[0].y), (src[1].x, src[1].y), (src[3].x, src[3].y)
    (u0, v0), (u1, v1), (u3, v3) = (dst[0].x, dst[0].y), (dst[1].x, dst[1].y), (dst[3].x, dst[3].y)
    S = fitz.Matrix(x1 - x0, y1 - y0, x3 - x0, y3 - y0, x0, y0)       # birim kare -> src
    T = fitz.Matrix(u1 - u0, v1 - v0, u3 - u0, v3 - v0, u0, v0)       # birim kare -> dst
    if abs(S.a * S.d - S.b * S.c) < 1e-9:
        return None
    return ~S * T


def _atomic(fn):
    """Islem hata verirse belge ve gecmis islemden onceki haline doner (bkz. PDFEditor._tx_rollback).
    Ic ice cagrilarda yalniz en distaki korur; undo_batch icindeyken geri yuklemeyi o yapar."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if getattr(self, "_tx_depth", 0) or self.doc is None:
            return fn(self, *args, **kwargs)
        st = self._tx_begin()
        self._tx_depth = 1
        try:
            return fn(self, *args, **kwargs)
        except BaseException as ex:
            if not getattr(self, "_batching", False):
                self._tx_rollback(st, ex)
            raise
        finally:
            self._tx_depth = 0
    wrapper._atomic = True
    return wrapper


# geri-al adimi acan butun islemler (su an 35): yeni eklenen de kendiliginden sarilir
for _name, _fn in list(vars(PDFEditor).items()):
    if (_name not in ("_push_undo", "undo_batch", "_undo_guard") and hasattr(_fn, "__code__")
            and "_push_undo" in _fn.__code__.co_names):
        setattr(PDFEditor, _name, _atomic(_fn))
del _name, _fn
