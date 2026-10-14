"""Gomulen yazi tiplerinin "harf -> Unicode" tablosunu (ToUnicode) duzeltir.

Sorun: MuPDF bir yazi tipini belgeye gomerken her harf sekli (glyph) icin TEK bir Unicode kodu yazar.
Yazi tipinde ayni sekli paylasan birden cok kod varsa (bosluk ile bolunemez bosluk, tire ile "yumusak
tire", noktali virgul ile Yunan soru isareti ...) SONUNCUSUNU secer. Sonuc: Revora'nin yazdigi yazi
ekranda dogru gorunur ama dosyadan kopyalaninca / baska programda araninca bosluklar U+00A0, tireler
U+00AD (Word'de gorunmez!), Segoe UI'de parantezler U+0000 olarak gelir (gercek belge testi,
2026-10-12). Burada tablo, klavyeden yazilan kod one alinarak yeniden kurulur.

Iki yol:
  * Yazi tipinin kendisi belgede EKSIKSIZ duruyorsa (bizim yeni gomdugumuz; kaydetmeden once) hangi
    kodun hangi sekle gittigi yazi tipinden okunur: kesin.
  * Okunamiyorsa (onceden kirpilmis: eski Revora surumunun kaydettigi dosya) yalniz birkac zararsiz
    cift degistirilir, o da tabloda "dogru" kod hic yoksa.
"""
import hashlib
import re
import fitz

# klavyeden yazilan / belgede beklenen kodlar (ayni sekli paylasan baska kod yerine bunlar yazilir)
_PREFER = list(range(0x20, 0x7F)) + [0xA5, 0xAF, 0xB7, 0x2019]
# yazi tipi okunamazsa: (yanlis yazilan, olmasi gereken)
_FALLBACK = ((0x00A0, 0x0020), (0x00AD, 0x002D), (0x2010, 0x002D), (0x2011, 0x002D), (0x037E, 0x003B))

_TOK = re.compile(rb"<([0-9A-Fa-f\s]*)>|(\[)|(\])|(beginbfchar|endbfchar|beginbfrange|endbfrange)")
_HEAD = (b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n"
         b"/CIDSystemInfo <</Registry(Adobe)/Ordering(UCS)/Supplement 0>> def\n"
         b"/CMapName /Adobe-Identity-UCS def\n/CMapType 2 def\n"
         b"1 begincodespacerange\n<0000> <FFFF>\nendcodespacerange\n")
_TAIL = b"endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n"


def _parse(data):
    """ToUnicode akisi -> {glyph no: hedef (hex dizgi, buyuk harf)}. Cozulemezse None."""
    out, mode, buf, arr = {}, None, [], None
    for m in _TOK.finditer(data):
        hx, lb, rb, kw = m.groups()
        if kw:
            mode = {b"beginbfchar": "char", b"beginbfrange": "range"}.get(kw)
            buf, arr = [], None
            continue
        if mode is None:
            continue
        if lb:
            arr = []
            continue
        if rb:
            if mode != "range" or len(buf) != 2 or arr is None:
                return None
            lo, hi = int(buf[0], 16), int(buf[1], 16)
            for k, t in enumerate(arr[:hi - lo + 1]):
                out[lo + k] = t
            buf, arr = [], None
            continue
        h = re.sub(rb"\s", b"", hx).decode("ascii").upper()
        if arr is not None:
            arr.append(h)
            continue
        buf.append(h)
        if mode == "char" and len(buf) == 2:
            out[int(buf[0], 16)] = buf[1]
            buf = []
        elif mode == "range" and len(buf) == 3:
            lo, hi, start = int(buf[0], 16), int(buf[1], 16), buf[2]
            if hi < lo or hi - lo > 0xFFFF or not start:
                return None
            base, width = int(start, 16), len(start)
            for k in range(hi - lo + 1):
                out[lo + k] = ("%0*X" % (width, base + k))
            buf = []
    return out


def _build(mapping):
    items = sorted(mapping.items())
    parts = [_HEAD]
    for i in range(0, len(items), 100):
        chunk = items[i:i + 100]
        parts.append(b"%d beginbfchar\n" % len(chunk))
        parts.append(b"".join(b"<%04X> <%s>\n" % (g, t.encode("ascii")) for g, t in chunk))
        parts.append(b"endbfchar\n")
    parts.append(_TAIL)
    return b"".join(parts)


def _ref(doc, xref, key):
    t, v = doc.xref_get_key(xref, key)
    if t == "xref":
        return int(v.split()[0])
    return None


def _font_program(doc, xref):
    """Type0 yazi tipinin gomulu dosyasi (fitz.Font) ya da None."""
    t, v = doc.xref_get_key(xref, "DescendantFonts")
    m = re.search(r"(\d+) 0 R", v or "")
    if not m:
        return None
    desc = int(m.group(1))
    t, v = doc.xref_get_key(desc, "CIDToGIDMap")
    if t == "xref":                      # (ozel esleme: glyph no = CID varsayimi tutmaz)
        return None
    fd = _ref(doc, desc, "FontDescriptor")
    if not fd:
        return None
    ff = _ref(doc, fd, "FontFile2") or _ref(doc, fd, "FontFile3")
    if not ff:
        return None
    if _ref(doc, fd, "FontFile3") and doc.xref_get_key(ff, "Subtype")[1] != "/OpenType":
        return None                      # (ciplak CFF: icinde harf tablosu yok)
    try:
        font = fitz.Font(fontbuffer=doc.xref_stream(ff))
        return font if font.has_glyph(0x41) and font.has_glyph(0x20) else None
    except Exception:
        return None


def _agrees(font, mapping):
    """Tablodaki glyph numaralari yazi tipinin kendi numaralariyla ayni mi (CID = glyph no)?
    Harf ve rakamlarda denenir: bunlar sekil paylasmaz, tablo ile yazi tipi birebir tutmali.
    Tutmuyorsa (baska programin kendi numaralamasi) yazi tipine GUVENILMEZ."""
    ok = n = 0
    for gid, t in mapping.items():
        if len(t) != 4:
            continue
        cp = int(t, 16)
        if 0x30 <= cp <= 0x39 or 0x41 <= cp <= 0x5A or 0x61 <= cp <= 0x7A:
            n += 1
            ok += font.has_glyph(cp) == gid
    return n >= 5 and ok == n


# Ayni yazi tipi icin sonuc hep aynidir: MuPDF tabloyu yazi tipinden uretir, biz de ayni yazi tipinden
# duzeltiriz. Anahtar = (tablonun ozeti, yazi tipinin adi, gomulu dosyanin boyu); deger = duzeltilmis
# tablo ya da b"" (degisecek bir sey yok). Olmadan her yazmada yazi tipi dosyasi (1 MB) yeniden
# yuklenip 3000+ satirlik tablo yeniden cozuluyordu: yazma basina ~17 ms.
_CACHE = {}
_CACHE_MAX = 64


def _font_id(doc, xref):
    """(yazi tipinin adi, gomulu dosyasinin boyu): onbellek anahtarinin yazi tipi kismi."""
    name = doc.xref_get_key(xref, "BaseFont")[1]
    size = ""
    m = re.search(r"(\d+) 0 R", doc.xref_get_key(xref, "DescendantFonts")[1] or "")
    if m:
        fd = _ref(doc, int(m.group(1)), "FontDescriptor")
        ff = fd and (_ref(doc, fd, "FontFile2") or _ref(doc, fd, "FontFile3"))
        if ff:
            size = doc.xref_get_key(ff, "Length1")[1] + "/" + doc.xref_get_key(ff, "Length")[1]
    return name, size


def repair(doc, first=1):
    """first numarali nesneden itibaren Type0 / Identity-H yazi tiplerinin ToUnicode tablosunu duzeltir.
    Degistirilen tablo sayisini dondurur. Hata olursa o yazi tipi atlanir (kayit engellenmez)."""
    fixed = 0
    done = set()
    for xref in range(max(1, first), doc.xref_length()):
        try:
            if doc.xref_get_key(xref, "Subtype")[1] != "/Type0":
                continue
            if doc.xref_get_key(xref, "Encoding")[1] != "/Identity-H":
                continue
            tu = _ref(doc, xref, "ToUnicode")
            if not tu or tu in done:
                continue
            done.add(tu)
            raw = doc.xref_stream(tu) or b""
            key = (hashlib.md5(raw).digest(),) + _font_id(doc, xref)
            hit = _CACHE.get(key)
            if hit is not None:
                if hit:
                    doc.update_stream(tu, hit)
                    fixed += 1
                continue
            mapping = _parse(raw)
            if not mapping:
                continue
            changed = False
            font = _font_program(doc, xref)
            if font is not None and not _agrees(font, mapping):
                font = None
            if font is not None:
                for cp in _PREFER:
                    gid = font.has_glyph(cp)
                    want = "%04X" % cp
                    if gid and gid in mapping and mapping[gid] != want:
                        mapping[gid] = want
                        changed = True
            else:
                have = set(mapping.values())
                for bad, good in _FALLBACK:
                    b, g = "%04X" % bad, "%04X" % good
                    if b in have and g not in have:
                        for gid, t in mapping.items():
                            if t == b:
                                mapping[gid] = g
                                changed = True
                        have.add(g)
            if len(_CACHE) >= _CACHE_MAX:
                _CACHE.clear()
            _CACHE[key] = _build(mapping) if changed else b""
            if changed:
                doc.update_stream(tu, _CACHE[key])
                fixed += 1
        except Exception:
            continue
    return fixed


# ---------------------------------------------------------------------------------------------
# KIRPILMIS SAYFA (CropBox != MediaBox) - 2026-10-13
# PyMuPDF'in TextWriter.write_text'i, sayfa USTTEN ya da ALTTAN kirpilmissa yaziyi yanlis
# yukseklige yazar (1.28.2): kirpma kaydirmasi olarak kirpma kutusunun UST boslugunu kullanir,
# oysa PDF'te y asagidan yukari sayildigi icin ALT bosluk gerekir. Ust ve alt bosluk esitse
# (kirpilmamis sayfa dahil) fark yoktur; degilse yazi (alt bosluk - ust bosluk) kadar kayar:
# alttan 200 pt kirpilmis sayfada (150, 150)'ye yazilan yazi (150, 350)'ye gidiyordu - duzenlenen,
# tasinan, yeni eklenen her yazi (sayfanin gorunen alaninin disina da dusebilir). Cizim ve
# isaretleme etkilenmez (onlar page.transformation_matrix ile yazilir).
# Duzeltme: kutuphanenin kullanacagi kaydirma ile DOGRU kaydirma (sayfanin kendi donusum matrisi)
# arasindaki fark, write_text'e ek bir oteleme olarak verilir. Fark sifirsa (kirpilmamis ve yanlari
# esit kirpilmis sayfalar) kutuphane HIC degistirilmeden cagrilir.
_CROP_BUG = None          # kutuphanede hata var mi (ilk kirpilmis sayfada bir kez denenir)
_ARGS = ("color", "opacity", "overlay", "morph", "matrix", "render_mode", "oc")


def _lib_misplaces(orig):
    """Kutuphane kirpilmis sayfada yaziyi kaydiriyor mu: bellekte kucuk bir denemeyle olcer.
    (Ileride duzeltilmis bir surumle calisirsak duzeltmeyi iki kez uygulamayalim.)"""
    try:
        d = fitz.open()
        pg = d.new_page(width=200, height=300)
        pg.set_cropbox(fitz.Rect(0, 0, 200, 200))            # alttan 100 kirpik
        tw = fitz.TextWriter(pg.rect)
        tw.append((50, 50), "x", fontsize=10)
        orig(tw, pg)
        y = [s["origin"][1] for b in pg.get_text("dict")["blocks"] if b["type"] == 0
             for ln in b["lines"] for s in ln["spans"]]
        d.close()
        return bool(y) and abs(y[0] - 50) > 1.0
    except Exception:
        return False


def crop_shift(tw, page):
    """Kirpilmis sayfada write_text'in yaziyi koyacagi yer ile dogru yer arasindaki fark
    (PDF birimi; (0, 0): duzeltme gerekmez)."""
    try:
        # Kirpma kutusu (PyMuPDF: sol-ust koseli, medya kutusunun ustune gore) ve medya kutusu sayfa
        # dondurulse de AYNI kalir; hesap bu yuzden dort sayfa yonunde de gecerli. (Sayfanin
        # transformation_matrix'i ise dondurulmus sayfada kirpmayi hesaba katmiyor: kullanilmaz.)
        cb, mb = page.cropbox, page.mediabox
        top = cb.y0                                          # ustten kirpilan
        bottom = mb.height - cb.height - top                 # alttan kirpilan
        # kutuphane sayfanin sol ust kosesini PDF uzayinda  y = kirpma yuksekligi + UST bosluk  diye
        # koyar; dogrusu  medya yuksekligi - ust bosluk  = kirpma yuksekligi + ALT bosluk.
        dy = bottom - top
        return (0.0, dy) if abs(dy) > 1e-4 else (0.0, 0.0)
    except Exception:
        return 0.0, 0.0


def _placed(orig):
    """orig (PyMuPDF'in write_text'i) -> kirpilmis sayfada da dogru yere yazan surumu."""
    def write_text(self, page, *args, **kwargs):
        global _CROP_BUG
        dx, dy = crop_shift(self, page)
        if not dx and not dy:
            return orig(self, page, *args, **kwargs)
        if _CROP_BUG is None:
            _CROP_BUG = _lib_misplaces(orig)
        if not _CROP_BUG:
            return orig(self, page, *args, **kwargs)
        kw = dict(zip(_ARGS, args))
        kw.update(kwargs)
        morph, matrix = kw.pop("morph", None), kw.pop("matrix", None)
        if morph is not None:                                # (kutuphanenin morph -> matris cevirisi)
            pt = morph[0] * self.ictm
            fix = fitz.Matrix(1, 1).pretranslate(pt.x, pt.y)
            matrix = ~fix * morph[1] * fix
        shift = fitz.Matrix(1, 0, 0, 1, dx, dy)
        kw["matrix"] = (matrix * shift) if matrix is not None else shift
        return orig(self, page, **kw)
    return write_text


def install():
    """fitz.TextWriter.write_text'i sarar: (1) kirpilmis sayfada yazi dogru yere yazilir (yukaridaki
    not); (2) yazi belgeye yazilir yazilmaz, o cagrida gomulen yeni yazi tiplerinin tablosu
    duzeltilir. Neden burada: MuPDF bir yazi tipini ilk okudugunda (goruntuleme / metin okuma)
    tablosunu onbellege alir; duzeltme o andan ONCE yapilmazsa acik belgede etkisiz kalir (dosyaya
    kaydedince duzelir ama yeniden duzenlerken kutuda tire gorunmez). Programda metin yazan
    onbesten fazla yer var; hepsi bu tek noktadan gecer."""
    global plain_write_text
    tw = fitz.TextWriter
    if getattr(tw.write_text, "_revora", False):
        return
    orig = _placed(tw.write_text)
    plain_write_text = orig

    def write_text(self, page, *args, **kwargs):
        doc = getattr(page, "parent", None)
        try:
            n0 = doc.xref_length()
        except Exception:
            n0 = None
        out = orig(self, page, *args, **kwargs)
        if n0 is not None:
            try:
                if doc.xref_length() > n0:
                    repair(doc, first=n0)
            except Exception:
                pass
        return out
    write_text._revora = True
    tw.write_text = write_text


def plain_write_text(tw, page, *args, **kwargs):
    """Duzeltmesiz yazma: yalniz GORUNTU uretmek icin kurulan gecici belgelerde (canli yazma
    onizlemesi, gorunum olcumu, karartma damgasi) kullanilir. Harf -> Unicode tablosu piksellere
    etki etmez; orada duzeltmek her tusta yazi tipini yeniden yukleyip tabloyu yeniden kurmak
    demekti (onizleme 3 ms yerine 20 ms). GERCEK belgeye yazan yerler bunu KULLANMAZ.
    (install() bu adi PyMuPDF'in ozgun write_text'ine baglar.)"""
    return tw.write_text(page, *args, **kwargs)


install()
