"""
font_resolver.py
-----------------
PDF'lerdeki gömülü fontlar genellikle "subset" edilmiştir; yani belgede
gecen harfler disinda glyph icermezler. Yeni metin yazarken eksik harfler
kare (□) olarak cikar.

Cozum: PDF'teki font adini (ör. "ABCDE+Tahoma-Bold") Windows'ta zaten
yuklu olan GERCEK font dosyasina esleriz (C:\\Windows\\Fonts\\tahoma.ttf).
Bu dosyalar TUM karakterleri icerir ve ayni font ailesi oldugu icin
gorunum orijinaliyle birebir ayni olur.
"""
import os
import re

WINDOWS_FONT_DIR = r"C:\Windows\Fonts"

# family_key -> (regular, bold, italic, bold_italic) dosya adlari
FONT_FAMILY_MAP = {
    "tahoma":        ("tahoma.ttf", "tahomabd.ttf", "tahoma.ttf", "tahomabd.ttf"),
    "arial":         ("arial.ttf", "arialbd.ttf", "ariali.ttf", "arialbi.ttf"),
    "arialnarrow":   ("arialn.ttf", "arialnb.ttf", "arialni.ttf", "arialnbi.ttf"),
    "calibri":       ("calibri.ttf", "calibrib.ttf", "calibrii.ttf", "calibriz.ttf"),
    "cambria":       ("cambria.ttc", "cambriab.ttf", "cambriai.ttf", "cambriaz.ttf"),
    "timesnewroman": ("times.ttf", "timesbd.ttf", "timesi.ttf", "timesbi.ttf"),
    "verdana":       ("verdana.ttf", "verdanab.ttf", "verdanai.ttf", "verdanaz.ttf"),
    "couriernew":    ("cour.ttf", "courbd.ttf", "couri.ttf", "courbi.ttf"),
    "segoeui":       ("segoeui.ttf", "segoeuib.ttf", "segoeuii.ttf", "segoeuiz.ttf"),
    "georgia":       ("georgia.ttf", "georgiab.ttf", "georgiai.ttf", "georgiaz.ttf"),
    "trebuchetms":   ("trebuc.ttf", "trebucbd.ttf", "trebucit.ttf", "trebucbi.ttf"),
    "comicsansms":   ("comic.ttf", "comicbd.ttf", "comic.ttf", "comicbd.ttf"),
}

# Bilinmeyen / bulunamayan fontlar icin son care
FALLBACK_FAMILY = "arial"


def _normalize(name: str) -> str:
    """'ABCDEF+Tahoma-Bold,Italic' -> 'tahoma' gibi sade bir anahtara indirger."""
    if "+" in name:
        name = name.split("+", 1)[1]
    name = name.lower()
    name = name.replace("-", "").replace(",", "").replace(" ", "")
    name = name.replace("mt", "").replace("psmt", "")
    for tag in ("bolditalic", "boldoblique", "bold", "italic", "oblique", "regular"):
        name = name.replace(tag, "")
    return name.strip()


def _match_family(key: str) -> str | None:
    """Sadelestirilmis font anahtarini ('arialnarrow') font ailesine esler.
    ONEMLI: aileleri UZUNDAN KISAYA sirali deneriz ki 'arialnarrow' anahtari,
    daha kisa ve genel olan 'arial'den ONCE eslessin. Eski kod ilk gordugu
    'arial'e dusuruyordu ve Arial Narrow'un dar gorunumu kayboluyordu."""
    families = sorted(FONT_FAMILY_MAP, key=len, reverse=True)
    # 1) tam/iceren eslesme: aile adi anahtarin icinde geciyor mu
    for family in families:
        if family in key:
            return family
    # 2) kisaltilmis PDF adlari icin ters yon (ör. "times" -> "timesnewroman"),
    #    saçma eslesmeleri onlemek icin en az 4 karakter sarti ile
    if len(key) >= 4:
        for family in families:
            if key in family:
                return family
    return None


def detect_style(name: str) -> tuple[bool, bool]:
    """Font adindan (bold, italic) bilgisini cikarir."""
    low = name.lower()
    bold = "bold" in low
    italic = "italic" in low or "oblique" in low
    return bold, italic


def _after_family(name, family):
    """Font adinin aile adindan sonraki kismi ('ABCD+SegoeUISemibold-Bold', 'Segoe UI Semibold'
    -> '-Bold'). Aile adi basta degilse adin tamami."""
    if "+" in name:
        name = name.split("+", 1)[1]
    fam = family.replace(" ", "").lower()
    compact = name.replace(" ", "")
    return compact[len(fam):] if compact.lower().startswith(fam) else name


def resolve_font_path(base_font_name: str, force_bold: bool = None,
                      force_italic: bool = None) -> tuple[str, bool, bool, bool]:
    """
    Verilen PDF font adina en uygun Windows font dosyasini bulur.
    force_bold / force_italic verilirse (True/False), adindan cikarilan bilgiyi gecersiz kilar.
    Return: (dosya_yolu, bold_mi, italic_mi, tam_eslesme_mi)
    Sira: (1) elle yazilmis tablonun ailesi tam olarak, (2) KURULU fontlardan (installed_fonts)
    ayni adli aile, (3) tablonun aileleriyle kismi eslesme (eski kural), (4) Arial (tam degil).
    Kurulu ailede istenen kalin / italik yuz yoksa normal yuz kullanilir ve tam = False olur
    (arayuz "en yakin font kullanildi" der; sessizce basariliymis gibi gosterilmez).
    """
    bold, italic = detect_style(base_font_name)
    key = _normalize(base_font_name)
    ent = installed_fonts().get(key) if key and key not in FONT_FAMILY_MAP else None
    if ent is not None:                     # kalin / italik: aile adindan SONRAKI kisimdan ("Segoe UI
        bold, italic = detect_style(_after_family(base_font_name, ent["name"]))   # Semibold" kalin degil)
    if force_bold is not None:
        bold = force_bold
    if force_italic is not None:
        italic = force_italic
    if key not in FONT_FAMILY_MAP:
        if ent is not None:
            faces = ent["faces"]
            want = (1 if bold else 0) + (2 if italic else 0)
            path = faces[want]
            if path is None:
                return faces[0], False, False, False
            return path, bold, italic, True
    matched_family = _match_family(key)

    exact = matched_family is not None
    if matched_family is None:
        matched_family = FALLBACK_FAMILY
        # Bulunamayan DAR yazi tipi (InterstateCondensed, ...Narrow, ...Compressed): Arial yerine Arial
        # Narrow (Office ile gelir). Arial'la duzenlenen satir ozgununden ~%20 genis cikiyordu.
        if re.search(r"condensed|narrow|compress", key) and os.path.exists(
                os.path.join(WINDOWS_FONT_DIR, FONT_FAMILY_MAP["arialnarrow"][0])):
            matched_family = "arialnarrow"

    regular, b, i, bi = FONT_FAMILY_MAP[matched_family]
    if bold and italic:
        fname = bi
    elif bold:
        fname = b
    elif italic:
        fname = i
    else:
        fname = regular

    path = os.path.join(WINDOWS_FONT_DIR, fname)
    return path, bold, italic, exact


# Kullanicinin acilir menuden secebilecegi font aileleri (goruntu adi -> anahtar)
FONT_DISPLAY_NAMES = [
    ("Tahoma", "Tahoma"),
    ("Arial", "Arial"),
    ("Calibri", "Calibri"),
    ("Cambria", "Cambria"),
    ("Times New Roman", "Times New Roman"),
    ("Verdana", "Verdana"),
    ("Courier New", "Courier New"),
    ("Segoe UI", "Segoe UI"),
    ("Georgia", "Georgia"),
    ("Trebuchet MS", "Trebuchet MS"),
    ("Comic Sans MS", "Comic Sans MS"),
]


def font_file_exists(path: str) -> bool:
    return os.path.isfile(path)


# ---------------------------------------------------------------- kurulu fontlar
# Yukaridaki tablo elle yazilmis 12 aile. Bilgisayarda kurulu OTEKI fontlar (kullaniciya ozel
# kurulanlar dahil) dosyanin kendisinden okunur: aile / bicim adi (name tablosu), gomme izni ve
# Turkce kod sayfasi (OS/2 tablosu). Listeye yalniz PDF'e yazilabilenler girer:
#   - gomulmesine izin verilen (fsType: "kisitli lisans", "yalniz bit eslem" ve "alt kume
#     yapilamaz" olanlar ALINMAZ - kaydederken font alt kume olarak gomulur);
#   - Turkce harfleri iceren (OS/2 kod sayfasi 1254; sembol / simge fontlari ALINMAZ);
#   - TrueType / OpenType dosyasi (.ttf .otf .ttc; .ttc'de yalniz ilk yuz - PyMuPDF digerini acamaz).
# Tarama BIR KEZ yapilir (ilk ihtiyacta; pencere acilinca arka planda isitilir).
import struct
import threading

USER_FONT_DIR = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts")
_STYLES = {"regular": 0, "normal": 0, "roman": 0, "bold": 1, "italic": 2, "oblique": 2,
           "bolditalic": 3, "boldoblique": 3}
_LOCK = threading.Lock()
TURKISH_SAMPLE = "ğüşıöçĞÜŞİÖÇ"
_FOUND = None          # aile anahtari (_normalize) -> {"name": gorunen ad, "faces": [4 yol | None]}
REJECTED = {}          # gorunen ad -> neden ("embed" / "glyphs") - rapor / test icin


def _font_files():
    seen, out = set(), []
    dirs = [WINDOWS_FONT_DIR, USER_FONT_DIR]
    try:                                            # kayit defterindeki kurulu font kayitlari
        import winreg
        for root, base in ((winreg.HKEY_LOCAL_MACHINE, WINDOWS_FONT_DIR), (winreg.HKEY_CURRENT_USER, USER_FONT_DIR)):
            try:
                k = winreg.OpenKey(root, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts")
            except OSError:
                continue
            i = 0
            while True:
                try:
                    _, val, _ = winreg.EnumValue(k, i)
                except OSError:
                    break
                i += 1
                if isinstance(val, str):
                    out.append(val if os.path.isabs(val) else os.path.join(base, val))
    except ImportError:
        pass
    for d in dirs:
        try:
            out += [os.path.join(d, f) for f in os.listdir(d)]
        except OSError:
            pass
    files = []
    for p in out:
        k = os.path.normcase(os.path.abspath(p))
        if k not in seen and p.lower().endswith((".ttf", ".otf", ".ttc")) and os.path.isfile(p):
            seen.add(k)
            files.append(p)
    return files


def read_font_info(path):
    """Font dosyasinin (ilk yuzunun) bilgisi -> {"family", "style", "fstype", "turkish", "cff"} | None.
    Yalniz gereken tablolar okunur (dosyanin tamami degil)."""
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            base = 0
            if head[:4] == b"ttcf":                      # koleksiyon: ilk yuz
                f.seek(12)
                base = struct.unpack(">I", f.read(4))[0]
                f.seek(base)
                head = f.read(12)
            if head[:4] not in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
                return None
            n = struct.unpack(">H", head[4:6])[0]
            tables = {}
            for _ in range(n):
                tag, _, off, ln = struct.unpack(">4sIII", f.read(16))
                tables[tag] = (off, ln)
            if b"name" not in tables or b"OS/2" not in tables:
                return None
            off, ln = tables[b"OS/2"]
            f.seek(off)
            os2 = f.read(min(ln, 96))
            fstype = struct.unpack(">H", os2[8:10])[0]
            version = struct.unpack(">H", os2[0:2])[0]
            turkish = version >= 1 and len(os2) >= 82 and bool(struct.unpack(">I", os2[78:82])[0] & (1 << 4))
            off, ln = tables[b"name"]
            f.seek(off)
            data = f.read(ln)
            glyphs = False
            if b"cmap" in tables:
                off, ln = tables[b"cmap"]
                f.seek(off)
                glyphs = _cmap_has(f.read(ln), TURKISH_SAMPLE)
        _, count, soff = struct.unpack(">HHH", data[:6])
        names = {}
        for i in range(count):
            pid, eid, lid, nid, l, o = struct.unpack(">HHHHHH", data[6 + 12 * i: 18 + 12 * i])
            if nid not in (1, 2):
                continue
            raw = data[soff + o: soff + o + l]
            if pid == 3 and lid == 0x409:
                rank, txt = 0, raw.decode("utf-16-be", "ignore")
            elif pid == 3:
                rank, txt = 1, raw.decode("utf-16-be", "ignore")
            elif pid == 1 and lid == 0:
                rank, txt = 2, raw.decode("mac_roman", "ignore")
            else:
                continue
            if nid not in names or rank < names[nid][0]:
                names[nid] = (rank, txt.strip())
        if 1 not in names:
            return None
        return {"family": names[1][1], "style": names.get(2, (0, "Regular"))[1], "fstype": fstype,
                "turkish": turkish and glyphs, "cff": b"CFF " in tables}
    except (OSError, struct.error, ValueError):
        return None


def _cmap_has(cmap, chars):
    """Fontun karakter tablosunda (cmap; Windows Unicode alt tablosu, bicim 4 ya da 12) bu harflerin
    HEPSINE glif var mi. Kod sayfasi bitini "Turkce" isaretleyip harfleri icermeyen (CAD) fontlar var."""
    try:
        n = struct.unpack(">H", cmap[2:4])[0]
        subs = {}
        for i in range(n):
            pid, eid, off = struct.unpack(">HHI", cmap[4 + 8 * i: 12 + 8 * i])
            subs[(pid, eid)] = off
        off = subs.get((3, 1)) or subs.get((0, 3)) or subs.get((3, 10)) or subs.get((0, 4))   # (Turkce harfler BMP'de: once bicim 4)
        if off is None:
            return False
        fmt = struct.unpack(">H", cmap[off:off + 2])[0]
        if fmt == 12:
            ng = struct.unpack(">I", cmap[off + 12:off + 16])[0]
            groups = [struct.unpack(">III", cmap[off + 16 + 12 * i: off + 28 + 12 * i]) for i in range(ng)]
            return all(any(a <= ord(c) <= b for a, b, _ in groups) for c in chars)
        if fmt != 4:
            return False
        seg = struct.unpack(">H", cmap[off + 6:off + 8])[0] // 2
        ends = struct.unpack(">%dH" % seg, cmap[off + 14: off + 14 + 2 * seg])
        p = off + 16 + 2 * seg
        starts = struct.unpack(">%dH" % seg, cmap[p: p + 2 * seg])
        deltas = struct.unpack(">%dh" % seg, cmap[p + 2 * seg: p + 4 * seg])
        ro_at = p + 4 * seg
        ranges = struct.unpack(">%dH" % seg, cmap[ro_at: ro_at + 2 * seg])
        for c in chars:
            u = ord(c)
            k = next((i for i in range(seg) if ends[i] >= u), None)
            if k is None or starts[k] > u:
                return False
            if ranges[k] == 0:
                g = (u + deltas[k]) & 0xFFFF
            else:
                at = ro_at + 2 * k + ranges[k] + 2 * (u - starts[k])
                g = struct.unpack(">H", cmap[at:at + 2])[0]
                g = (g + deltas[k]) & 0xFFFF if g else 0
            if g == 0:
                return False
        return True
    except (struct.error, IndexError):
        return False


def _scan():
    found, rejected = {}, {}
    for path in _font_files():
        info = read_font_info(path)
        if info is None:
            continue
        style = _STYLES.get(info["style"].lower().replace(" ", ""))
        family = info["family"] if style is not None else "%s %s" % (info["family"], info["style"])
        style = style or 0
        if info["fstype"] & 0x0302 or (info["fstype"] & 0x000F) == 0x0002:
            rejected[family] = "embed"                     # gomulmesine izin yok
            continue
        if not info["turkish"]:
            rejected[family] = "glyphs"                    # Turkce harfleri yok (sembol / simge fontu)
            continue
        key = _normalize(family)
        if not key:
            continue
        ent = found.setdefault(key, {"name": family, "faces": [None, None, None, None]})
        if ent["faces"][style] is None:
            ent["faces"][style] = path
    for ent in found.values():                         # normal yuzu olmayan aile: ilk bulunan yuz
        if ent["faces"][0] is None:
            ent["faces"][0] = next(p for p in ent["faces"] if p)
    return found, rejected


def installed_fonts():
    """Kurulu ve PDF'e yazilabilen aileler: {anahtar: {"name", "faces"}} (bir kez taranir)."""
    global _FOUND
    if _FOUND is None:
        with _LOCK:
            if _FOUND is None:
                found, rejected = _scan()
                REJECTED.update(rejected)
                _FOUND = found
    return _FOUND


def warm_up():
    """Taramayi arka planda baslat (pencere acildiktan sonra): ilk menu acilisi beklemesin."""
    threading.Thread(target=installed_fonts, daemon=True).start()


def menu_fonts():
    """Yazi tipi listesi: [(gorunen ad, anahtar)] - elle yazilmis aileler (dosyasi varsa) +
    kurulu olanlar, alfabetik. Anahtar resolve_font_path'e verilen addir."""
    out, keys = [], set()
    for display, key in FONT_DISPLAY_NAMES:
        fam = _match_family(_normalize(key))
        if fam is not None and font_file_exists(os.path.join(WINDOWS_FONT_DIR, FONT_FAMILY_MAP[fam][0])):
            out.append((display, key))
            keys.add(_normalize(key))
    for k, ent in installed_fonts().items():
        if k not in keys and k not in FONT_FAMILY_MAP:
            out.append((ent["name"], ent["name"]))
            keys.add(k)
    return sorted(out, key=lambda t: t[0].casefold())


_USABLE = {}


def font_usable(name, bold=False):
    """Bu ad PDF'e GERCEKTEN yazilabiliyor mu: dosyasi bulunuyor, PyMuPDF aciyor, Turkce harfleri
    var -> (True, "") | (False, neden). Sonuc onbellekte."""
    key = (name, bool(bold))
    if key not in _USABLE:
        path, _, _, exact = resolve_font_path(name, force_bold=bold)
        if not exact or not font_file_exists(path):
            _USABLE[key] = (False, "missing")
        else:
            try:
                import fitz
                fo = fitz.Font(fontfile=path)
                miss = [c for c in TURKISH_SAMPLE if not fo.has_glyph(ord(c))]
                _USABLE[key] = (False, "glyphs") if miss else (True, "")
            except Exception:
                _USABLE[key] = (False, "open")
    return _USABLE[key]
