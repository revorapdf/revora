"""
pdf_content.py
--------------
Icerik akisi (content stream) seviyesinde CERRAHI metin kaldirma.

Neden gerekli: PyMuPDF'in redaction'i GEOMETRIKTIR - bir dikdortgene degen
TUM metni siler. Bir fligran (ör. sayfayi capraz kaplayan dev kirmizi yazi)
silmek istendiginde, onun kocaman kutusuna denk gelen tum tablo/metin de
zarar goruyordu.

Buradaki cozum: silinecek metnin, PDF icerik akisindaki kendi cizim
operatorunu (Tj/TJ/'/") KONUMUNDAN bulup sadece onun operandini bosaltmak.
Boylece altindaki/ustundeki hicbir yaziya dokunmadan yalnizca o metin gider.
"""
import hashlib
import re

WS = b" \t\r\n\f\0"
_WS_SET = frozenset(WS)
DELIM = b"()<>[]{}/%"
IDENT = (1, 0, 0, 1, 0, 0)


def _matmul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1*a2 + b1*c2, a1*b2 + b1*d2,
            c1*a2 + d1*c2, c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2, e1*b2 + f1*d2 + f2)


_RE_WS = re.compile(rb"[ \t\r\n\f\0]+")
_RE_WORD = re.compile(rb"[^ \t\r\n\f\0()<>\[\]{}/%]+")
_RE_EOL = re.compile(rb"[\r\n]")
_RE_STR = re.compile(rb"[\\()]")
_RE_ARR = re.compile(rb"[(\[\]]")
_RE_NUM = re.compile(rb"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)\Z")


def _skip_string(data, i, n):
    """"(" den SONRAKI konumdan baslar; dengeli kapanisin ardini dondurur (kacis: \\ + 1 bayt).
    Kapanmiyorsa _tokenize_ref ile ayni yerde durur (n, ya da son bayt \\ ise n + 1)."""
    depth = 1
    while i < n and depth > 0:
        m = _RE_STR.search(data, i)
        if m is None:
            return n
        k = m.start()
        ch = data[k]
        if ch == 0x5C:
            i = k + 2
            continue
        depth += 1 if ch == 0x28 else -1
        i = k + 1
    return i


def _tokenize(data: bytes):
    """Icerik akisini token'lara ayirir. Her token: {kind, start, end, val}.
    kind: number/string/hexstring/name/array/op.

    _tokenize_ref ile BIREBIR ayni listeyi uretir (kabul testi ikisini karsilastirir); fark hiz:
    o bayt bayt ilerler (61 KB'lik akis ~60 ms), bu arama islerini duzenli ifadelere birakir.
    Her duzenlemede akis en az bir kez ayristirildigi icin tasima / duzenleme suresinin
    yarisindan fazlasi burada geciyordu."""
    i, n = 0, len(data)
    toks = []
    add = toks.append
    ws, word, num = _RE_WS.match, _RE_WORD.match, _RE_NUM.match
    while i < n:
        c = data[i]
        if c in _WS_SET:
            i = ws(data, i).end()
            continue
        if c == 0x25:  # % yorum satiri
            m = _RE_EOL.search(data, i)
            i = n if m is None else m.start()
            continue
        if c == 0x28:  # ( literal string
            j = i
            i = _skip_string(data, i + 1, n)
            add({"kind": "string", "start": j, "end": i, "val": data[j:i]})
            continue
        if c == 0x3C:  # <
            if data[i+1:i+2] == b"<":
                add({"kind": "op", "start": i, "end": i+2, "val": b"<<"})
                i += 2
                continue
            j = i
            k = data.find(b">", i)
            i = (n if k == -1 else k) + 1
            add({"kind": "hexstring", "start": j, "end": i, "val": data[j:i]})
            continue
        if c == 0x3E and data[i+1:i+2] == b">":
            add({"kind": "op", "start": i, "end": i+2, "val": b">>"})
            i += 2
            continue
        if c == 0x5B:  # [ dizi (TJ operandi) - tumunu ham al
            j = i
            i += 1
            depth = 1
            while i < n and depth > 0:
                m = _RE_ARR.search(data, i)
                if m is None:
                    i = n
                    break
                k = m.start()
                ch = data[k]
                if ch == 0x28:
                    i = _skip_string(data, k + 1, n)
                    continue
                depth += 1 if ch == 0x5B else -1
                i = k + 1
            add({"kind": "array", "start": j, "end": i, "val": data[j:i]})
            continue
        if c == 0x2F:  # / isim
            j = i
            m = word(data, i + 1)
            i = i + 1 if m is None else m.end()
            add({"kind": "name", "start": j, "end": i, "val": data[j:i]})
            continue
        m = word(data, i)      # sayi ya da operator
        if m is None:          # (tek basina ayrac: ) > ] { })
            i += 1
            continue
        j, i = i, m.end()
        raw = m.group()
        if num(raw) is not None:
            add({"kind": "number", "start": j, "end": i, "val": raw})
            continue
        try:
            float(raw)
            add({"kind": "number", "start": j, "end": i, "val": raw})
        except ValueError:
            add({"kind": "op", "start": j, "end": i, "val": raw})
            if raw == b"ID":
                # satir ici resim: ikili veriyi token'lamaya calisma, EI'ya atla
                k = data.find(b"EI", i + 1)
                while k != -1 and not (data[k-1:k] in WS and
                                       (k + 2 >= n or data[k+2:k+3] in WS)):
                    k = data.find(b"EI", k + 1)
                i = n if k == -1 else k + 2
    return toks


def _tokenize_ref(data: bytes):
    """_tokenize'in ilk, bayt bayt ilerleyen hali: yalniz KARSILASTIRMA icin (testler)."""
    i, n = 0, len(data)
    toks = []
    while i < n:
        c = data[i:i+1]
        if c in WS:
            i += 1
            continue
        if c == b"%":  # yorum satiri
            while i < n and data[i:i+1] not in b"\r\n":
                i += 1
            continue
        if c == b"(":  # literal string (dengeli parantez + kacis)
            j = i
            i += 1
            depth = 1
            while i < n and depth > 0:
                ch = data[i:i+1]
                if ch == b"\\":
                    i += 2
                    continue
                if ch == b"(":
                    depth += 1
                elif ch == b")":
                    depth -= 1
                i += 1
            toks.append({"kind": "string", "start": j, "end": i, "val": data[j:i]})
            continue
        if c == b"<":
            if data[i+1:i+2] == b"<":
                toks.append({"kind": "op", "start": i, "end": i+2, "val": b"<<"})
                i += 2
                continue
            j = i
            while i < n and data[i:i+1] != b">":
                i += 1
            i += 1
            toks.append({"kind": "hexstring", "start": j, "end": i, "val": data[j:i]})
            continue
        if c == b">" and data[i+1:i+2] == b">":
            toks.append({"kind": "op", "start": i, "end": i+2, "val": b">>"})
            i += 2
            continue
        if c == b"[":  # dizi (TJ operandi) - tumunu ham al
            j = i
            i += 1
            depth = 1
            while i < n and depth > 0:
                ch = data[i:i+1]
                if ch == b"(":  # icindeki string'i atla
                    i += 1
                    d2 = 1
                    while i < n and d2 > 0:
                        cc = data[i:i+1]
                        if cc == b"\\":
                            i += 2
                            continue
                        if cc == b"(":
                            d2 += 1
                        elif cc == b")":
                            d2 -= 1
                        i += 1
                    continue
                if ch == b"[":
                    depth += 1
                elif ch == b"]":
                    depth -= 1
                i += 1
            toks.append({"kind": "array", "start": j, "end": i, "val": data[j:i]})
            continue
        if c == b"/":  # isim
            j = i
            i += 1
            while i < n and data[i:i+1] not in WS and data[i:i+1] not in DELIM:
                i += 1
            toks.append({"kind": "name", "start": j, "end": i, "val": data[j:i]})
            continue
        # sayi ya da operator
        j = i
        while i < n and data[i:i+1] not in WS and data[i:i+1] not in DELIM:
            i += 1
        if i == j:
            i += 1
            continue
        raw = data[j:i]
        try:
            float(raw)
            toks.append({"kind": "number", "start": j, "end": i, "val": raw})
        except ValueError:
            toks.append({"kind": "op", "start": j, "end": i, "val": raw})
            if raw == b"ID":
                # satir ici resim: ikili veriyi token'lamaya calisma, EI'ya atla
                k = data.find(b"EI", i + 1)
                while k != -1 and not (data[k-1:k] in WS and
                                       (k + 2 >= n or data[k+2:k+3] in WS)):
                    k = data.find(b"EI", k + 1)
                i = n if k == -1 else k + 2
    return toks


_SHOW_OPS = (b"Tj", b"TJ", b"'", b'"')
# harf / kelime araligi gibi, yazinin YERINI degistirmeyen ayarlar: iki gosterme operatoru arasinda
# bunlar varsa ikincisi yine "araya komut girmeden cizilmis" sayilir
_SPACING_OPS = (b"Tc", b"Tw", b"Tz", b"TL", b"Ts")


def _run(ops, first, origin, tol=2.0):
    """origin'deki yaziyi cizen operatorlerin TAMAMI (akis sirasiyla).

    first: origin'e en yakin operator (yazinin basi). Bir yazi tek operatorle cizilmek zorunda
    degil: wkhtmltopdf her HARFI ayri Tj ile, aralarinda TD ile cizer; Google Dokumanlar her
    KELIMEYI ayri BT ... ET icinde. MuPDF bunlari tek yazi (span) olarak verir; yalniz ilk
    operatoru bosaltinca yazinin geri kalani sayfada kaliyordu (kullanici: "basligi tasiyorum,
    eski yerinde yalniz N gidiyor").

    origin 4'lu ise (x, y, bitis_x, bitis_y) = yazinin taban cizgisi. Ilk operatorden sonra,
    AKISTA ARDISIK gelenlerden su ikisinden birini saglayanlar ayni yazinin devami sayilir:
      * araya hic komut girmeden cizilmis (ayni konumdan devam eder: yeri hesaplanamaz ama
        yazi tipi / renk degismedigi icin ayni yazidir), YA DA
      * yazi tipi, boyutu ve rengi AYNI, yeri de (yeniden konumlandigi icin kesin bilinir)
        taban cizgisinin ustunde ve yazinin boyunun icinde. Satir icinde yazi tipi / renk
        degisince MuPDF'in ayirdigi SONRAKI yazi bu yazinin kutusuna biraz tasabilir (bosluk
        payi): gorunumu farkli oldugu icin alinmaz.
    Ilk uymayan operatorde durulur: baska yerdeki, ust uste binen yaziya (filigran vb.)
    dokunulmaz. origin 2'li ise eskisi gibi yalniz ilk operator."""
    out = [first]
    if len(origin) < 4 or "i" not in first:
        return out
    ox, oy, ex, ey = origin[:4]
    dx, dy = ex - ox, ey - oy
    length = (dx * dx + dy * dy) ** 0.5
    if length < 1e-6:
        return out
    ux, uy = dx / length, dy / length
    for k in range(first["i"] + 1, len(ops)):
        op = ops[k]
        if not op["direct"]:
            px, py = op["origin"][0] - ox, op["origin"][1] - oy
            along, across = px * ux + py * uy, abs(py * ux - px * uy)
            if op.get("look") != first.get("look") or across > tol or not (0.5 < along < length - 0.25):
                break
        out.append(op)
    return out


def _blank_all(doc, xref, data, ops):
    """Operatorlerin operandlarini bosalt (sondan basa: onceki konumlar kaymaz)."""
    key0 = _key(data)
    seen = set()
    for op in sorted(ops, key=lambda o: o["operand"]["start"], reverse=True):
        st, en = op["operand"]["start"], op["operand"]["end"]
        if st in seen:
            continue
        seen.add(st)
        data = data[:st] + (b"[]" if op["op"] == "TJ" else b"()") + data[en:]
    if seen:
        # Yalniz operandlar bosaldi: q / Q yapisi AYNI. Bir sonraki adim (yeni yaziyi yazmadan once
        # ensure_wrapped) bu akisi yeniden ayristirmasin diye sarma bilgisi yeni icerige aktarilir.
        info = _WRAP_CACHE.get(key0)
        if info is not None:
            _remember_wrap(_key(data), info)
        doc.update_stream(xref, data)
    return data


def find_show_ops(data: bytes, base):
    """Her metin gosterme operatorunun sayfa (sol-ust) origin'ini ve
    operand byte araligini dondurur:
    [{origin:(x,y), op:'Tj', operand:{start,end,kind}}, ...]

    base: icerik (PDF kullanici) uzayindan sayfa uzayina donusum; cagiran
    page.transformation_matrix verir. Eskiden (x, sayfa_yuksekligi - y)
    kullaniliyordu; bu, 90/270 derece dondurulmus sayfalarda yanlis
    sonuc veriyor ve cerrahi silme hic eslesme bulamiyordu (pdf_paths ile
    ayni donusumu kullanmak her donuste dogru)."""
    return _scan_cached(data, base)[0]


_TOK_CACHE = {}       # akisin ozeti -> token listesi (SALT OKUNUR: cagiranlar degistirmez)
_WRAP_CACHE = {}      # akisin ozeti -> (acik q sayisi, eslesmeyen Q sayisi, q disinda komut var mi)


def _key(data):
    return hashlib.md5(data).digest()


def tokens(data, key=None):
    """_tokenize(data), akisin icerigine gore hatirlanarak. Ayni akis bir islem icinde birkac yerde
    gerekir (metin operatorleri, cizimler, resimler, sarma denetimi): hepsi ayni listeyi paylasir.
    Donen liste ve icindeki sozlukler DEGISTIRILMEZ."""
    key = key or _key(data)
    hit = _TOK_CACHE.get(key)
    if hit is None:
        hit = _tokenize(data)
        if len(_TOK_CACHE) >= 3:
            _TOK_CACHE.pop(next(iter(_TOK_CACHE)))
        _TOK_CACHE[key] = hit
    return hit


def _wrap_info(toks):
    """ensure_wrapped'in karari icin: (kapanmamis q, eslesmeyen Q, q / Q disinda komut var mi)."""
    depth = under = 0
    dirty = False
    for t in toks:
        if t["kind"] != "op":
            continue
        v = t["val"]
        if v == b"q":
            depth += 1
        elif v == b"Q":
            if depth > 0:
                depth -= 1
            else:
                under += 1      # eslesmeyen Q: bizim q'yu yutmasin diye fazladan q
        elif depth == 0:
            dirty = True
    return depth, under, dirty


def _remember_wrap(key, info):
    if len(_WRAP_CACHE) >= 16:
        _WRAP_CACHE.pop(next(iter(_WRAP_CACHE)))
    _WRAP_CACHE[key] = info


def _scan(data: bytes, base, ctm0=IDENT, toks=None):
    """find_show_ops'un genel hali: (metin_operatorleri, Do_cagrilari).
    ctm0: akisin baslangic donusumu (form nesnesi icin: formun /Matrix'i x
    cagrildigi yerdeki CTM). Do cagrilari: [{name, tok:(start,end), ctm}]."""
    ba, bb, bc, bd, be, bf = tuple(base)
    if toks is None:
        toks = _tokenize(data)
    ctm = ctm0
    ctm_stack = []
    gs = ()                  # etkin grafik durumlari (ExtGState adlari, sirayla): ayarlar
    gs_stack = []            # birikir -> karisim modu daha onceki bir gs'ten gelebilir
    dos = []
    Tm = IDENT
    Tlm = IDENT
    leading = 0.0
    nums = []
    last_str = None
    last_arr = None
    out = []
    since = 0                # son gosterme operatorunden beri gorulen komut sayisi (bkz. _run)
    look = (None, None)      # gecerli (yazi tipi + boyut, dolgu rengi): q / Q ile saklanir, geri gelir
    look_stack = []
    for idx, t in enumerate(toks):
        k = t["kind"]
        if k == "number":
            nums.append(float(t["val"]))
            continue
        if k in ("string", "hexstring"):
            last_str = t
            nums = []
            continue
        if k == "array":
            last_arr = t
            nums = []
            continue
        if k != "op":
            nums = []
            continue
        op = t["val"]
        if op not in _SHOW_OPS and op not in _SPACING_OPS:
            since += 1
        if op == b"q":
            ctm_stack.append(ctm)
            gs_stack.append(gs)
            look_stack.append(look)
        elif op == b"Q":
            if ctm_stack:
                ctm = ctm_stack.pop()
            if gs_stack:
                gs = gs_stack.pop()
            if look_stack:
                look = look_stack.pop()
        elif op == b"Tf" and nums:
            name = next((toks[j]["val"] for j in range(idx - 1, max(idx - 4, -1), -1)
                         if toks[j]["kind"] == "name"), None)
            look = ((name, nums[-1]), look[1])
        elif op in (b"rg", b"g", b"k", b"sc", b"scn"):
            look = (look[0], (op, tuple(nums)))
        elif op == b"cs" and idx > 0 and toks[idx - 1]["kind"] == "name":
            look = (look[0], (op, toks[idx - 1]["val"]))
        elif op == b"gs" and idx > 0 and toks[idx - 1]["kind"] == "name":
            gs = gs + (toks[idx - 1]["val"][1:].decode("latin-1"),)
        elif op == b"cm" and len(nums) >= 6:
            ctm = _matmul(tuple(nums[-6:]), ctm)
        elif op == b"BT":
            Tm = IDENT
            Tlm = IDENT
        elif op == b"Tm" and len(nums) >= 6:
            Tm = tuple(nums[-6:])
            Tlm = Tm
        elif op == b"Td" and len(nums) >= 2:
            Tlm = _matmul((1, 0, 0, 1, nums[-2], nums[-1]), Tlm)
            Tm = Tlm
        elif op == b"TD" and len(nums) >= 2:
            leading = -nums[-1]
            Tlm = _matmul((1, 0, 0, 1, nums[-2], nums[-1]), Tlm)
            Tm = Tlm
        elif op == b"TL" and len(nums) >= 1:
            leading = nums[-1]
        elif op == b"T*":
            Tlm = _matmul((1, 0, 0, 1, 0, -leading), Tlm)
            Tm = Tlm
        elif op in (b"Tj", b"'", b'"', b"TJ"):
            if op in (b"'", b'"'):
                Tlm = _matmul((1, 0, 0, 1, 0, -leading), Tlm)
                Tm = Tlm
            full = _matmul(Tm, ctm)
            x, y = full[4], full[5]
            origin = (ba * x + bc * y + be, bb * x + bd * y + bf)
            operand = last_arr if op == b"TJ" else last_str
            if operand is not None:
                out.append({"origin": origin, "op": op.decode(), "gs": gs,     # zincir
                            "i": len(out), "direct": since == 0 and bool(out), "look": look,
                            "operand": {"start": operand["start"],
                                        "end": operand["end"]}})
            since = 0
        elif op == b"Do" and idx > 0 and toks[idx - 1]["kind"] == "name":
            nt = toks[idx - 1]
            dos.append({"name": nt["val"][1:].decode("latin-1"),
                        "tok": (nt["start"], nt["end"]), "ctm": ctm})
        nums = []
    return out, dos


_CLEANED = set()      # clean_contents'in URETTIGI akislarin ozetleri (bkz. clean_page)


def clean_page(doc, page):
    """page.clean_contents() + icerik akislarinin listesi; az once temizlenmis ve o zamandan beri
    DEGISMEMIS tek akisi yeniden temizlemez.

    Neden: bir duzenlemede once yazinin karisim modu sorulur, sonra yazi silinir. Ikisi de ayni
    (temizlenmis) akisa bakarsa akis bir kez taranir. Temizligi iki kez calistirmak ise bazi
    belgelerde (wkhtmltopdf) ikinci seferde FARKLI baytlar uretir: tarama onbellegi iskalanir,
    akis yeniden ayristirilirdi."""
    xrefs = page.get_contents()
    if len(xrefs) == 1 and _key(doc.xref_stream(xrefs[0])) in _CLEANED:
        return xrefs
    page.clean_contents()
    xrefs = page.get_contents()
    if xrefs:
        if len(_CLEANED) >= 32:
            _CLEANED.clear()
        _CLEANED.add(_key(doc.xref_stream(xrefs[0])))
    return xrefs


def single_stream(doc, page):
    """Sayfanin icerik akislari birden fazlaysa tek akista birlestirir ve
    o akisin xref'ini dondurur (byte-seviyesi duzenleme tek akis ister)."""
    xrefs = page.get_contents()
    if len(xrefs) != 1:
        page.clean_contents()
        xrefs = page.get_contents()
    return xrefs[0] if xrefs else None


def ensure_wrapped(doc, page):
    """Sayfaya yeni bir sey (metin/cizgi) eklemeden once cagrilmali.

    Bazi PDF'ler grafik durumunu (koordinat donusumu 'cm', renk, opaklik,
    kirpma) q/Q disinda degistirip geri almiyor. Ornek: beton raporundaki
    filigran akisi sayfayi 35 derece dondurup oyle birakiyor -> sonradan
    eklenen metin de donmus koordinatla cizilip sayfa DISINA dusuyordu
    (gorunmez metin), ya da filigranin kirmizi rengini/opakligini miras
    aliyordu. Cozum: mevcut icerigi 'q ... Q' ile sarmak; boylece eklenen
    her sey temiz (varsayilan) grafik durumuyla baslar."""
    xref = single_stream(doc, page)
    if xref is None:
        return
    data = doc.xref_stream(xref)
    key = _key(data)
    info = _WRAP_CACHE.get(key)          # (az once taranan / operandi bosaltilan akis: yeniden ayristirma yok)
    if info is None:
        info = _wrap_info(tokens(data, key))
        _remember_wrap(key, info)
    depth, under, dirty = info
    if dirty or depth or under:
        data = b"q\n" * (under + 1) + data + b"\nQ" * depth + b"\nQ\n"
        doc.update_stream(xref, data)
        _remember_wrap(_key(data), (0, 0, False))      # (sarilmis hali dengeli: bir daha sarilmaz)


def remove_text_at(doc, page, origin, tol=2.0):
    """origin (sol-ust sayfa koordinati) konumundaki metin gosterme
    operatorunu bulur ve operandini bosaltir (metin cizilmez, baska
    HICBIR sey degismez). Basarili olursa True.

    Once tum icerik akislarini tek akista birlestirir (clean_contents)
    ki cok-akisli sayfalarda da tek yerde duzenleyelim."""
    xrefs = clean_page(doc, page)
    if not xrefs:
        return False
    xref = xrefs[0]
    data = doc.xref_stream(xref)
    base = page.transformation_matrix
    ops, dos = _scan_cached(data, base)

    best, bd = _nearest(ops, origin)
    if best is not None and bd <= tol:
        _blank_all(doc, xref, data, _run(ops, best, origin, tol))
        return True

    # Sayfanin kendi akisinda yok: metin bir Form XObject icinde olabilir
    # (Adobe'nin "Filigran ekle"si filigrani boyle koyar). Onlara in.
    try:
        found = _search_forms(doc, page, base, dos, origin, tol)
    except Exception:
        return False
    if found is None:
        return False
    chain, run = found
    try:
        target = _privatize_chain(doc, page, chain)
    except Exception:
        # _Skip ya da beklenmedik yapi: cokme yerine geometrik yedege dus.
        # (_copy_form sirasi: once kopya, sonra kaynak adi, en son akistaki ad;
        # yarida kalirsa en fazla sahipsiz bir kopya kalir, kayitta temizlenir.)
        return False
    _blank_all(doc, target, doc.xref_stream(target), run)
    return True


# ---------------------------------------------------------------- form nesneleri
class _Skip(Exception):
    """Guvenli sekilde duzenlenemeyen yapi: geometrik yedege dus."""


_SCAN_CACHE = {}


def _scan_cached(data, base):
    """_scan (Python'da yavas) sonucunu akisin icerigine gore hatirlar: ayni akis
    ikinci kez taranmaz (surukleme onizlemesi + asil tasima ayni akisi tarar)."""
    dk = _key(data)
    key = (dk, tuple(base))
    hit = _SCAN_CACHE.get(key)
    if hit is None:
        toks = tokens(data, dk)
        hit = _scan(data, base, toks=toks)
        if dk not in _WRAP_CACHE:                  # (ayni gecisten: ensure_wrapped tekrar ayristirmasin)
            _remember_wrap(dk, _wrap_info(toks))
        if len(_SCAN_CACHE) >= 6:
            _SCAN_CACHE.pop(next(iter(_SCAN_CACHE)))
        _SCAN_CACHE[key] = hit
    return hit


_CLEAN_OF = {}        # ham (canli) akisin ozeti -> ayni sayfanin TEMIZLENMIS akisinin ozeti (bkz. warm_scan)


def _ops_for_query(page):
    """Yalniz SORGU icin metin operatorleri (belgeye dokunmadan). On tarama bu sayfanin temiz
    kopyasini taradiysa o sonuc kullanilir: operatorler ve "gs" adlari aynidir, ham akisi ayrica
    ayristirmak gerekmez. Yoksa canli akis taranir (eski davranis)."""
    raw = page.read_contents()
    base = page.transformation_matrix
    ck = _CLEAN_OF.get(_key(raw))
    if ck is not None:
        hit = _SCAN_CACHE.get((ck, tuple(base)))
        if hit is not None:
            return hit[0]
    return find_show_ops(raw, base)


def warm_scan(doc, pno):
    """Sayfanin (birlestirilmis) akisini onceden tara. Asil belgeye dokunmaz:
    birlestirme belgenin kopyasinda yapilir (sonuc ayni bytelar).

    Tek tarama: bir islem (tasi / duzenle / sil) once sayfayi temizler, karisim modunu da silmeyi de
    o temiz akistan yapar; surukleme onizlemesinin sorgusu da ayni sonucu kullanir (_ops_for_query).
    Eskiden ham akis ayrica taraniyordu: her secimde iki ayristirma. Ayni icerik icin ikinci kez
    cagrilirsa hicbir sey yapmaz (kopya da cikarilmaz)."""
    try:
        live = doc[pno]
        base = tuple(live.transformation_matrix)
        raw = live.read_contents()
        rk = _key(raw)
        ck = _CLEAN_OF.get(rk)
        if ck is not None and (ck, base) in _SCAN_CACHE:
            return
        if rk in _CLEANED and len(live.get_contents()) == 1:      # zaten temiz tek akis: kopya gereksiz
            _scan_cached(raw, base)
            _CLEAN_OF[rk] = rk
            return
        tmp = type(doc)("pdf", doc.tobytes())
        try:
            page = tmp[pno]
            page.clean_contents()
            xrefs = page.get_contents()
            if xrefs:
                data = tmp.xref_stream(xrefs[0])
                _scan_cached(data, page.transformation_matrix)
                if len(_CLEAN_OF) >= 16:
                    _CLEAN_OF.clear()
                _CLEAN_OF[rk] = _key(data)
        finally:
            tmp.close()
    except Exception:
        pass


def remove_texts_at(doc, page, origins, tol=2.0):
    """Birden cok metin (paragrafin satirlari) tek taramada: hepsi sayfanin kendi
    akisindaysa operandlari sondan basa bosaltilir. Degilse tek tek remove_text_at."""
    xrefs = clean_page(doc, page)
    if not xrefs:
        return False
    xref = xrefs[0]
    data = doc.xref_stream(xref)
    ops, _ = _scan_cached(data, page.transformation_matrix)
    found = []
    for o in origins:
        best, bd = _nearest(ops, o)
        if best is None or bd > tol:
            return all(remove_text_at(doc, page, q, tol) for q in origins)
        found.extend(_run(ops, best, o, tol))
    _blank_all(doc, xref, data, found)
    return True


def remove_texts_each(doc, page, origins, tol=2.0):
    """Birden cok metni TEK taramada kaldir -> her biri icin kaldirildi mi ([bool]).
    Sayfanin kendi akisindakilerin operandlari sondan basa bosaltilir (akis bir kez
    okunur, bir kez yazilir). Orada bulunamayanlar (form nesnesi icindeki yazi) tek tek
    remove_text_at ile denenir. Toplu tasima / silme icin: yazi basina ayri tarama, 80
    yazilik bir tabloda 10+ saniye suruyordu."""
    xrefs = clean_page(doc, page)
    if not xrefs:
        return [False] * len(origins)
    xref = xrefs[0]
    data = doc.xref_stream(xref)
    ops, _ = _scan_cached(data, page.transformation_matrix)
    hits = []
    for o in origins:
        best, bd = _nearest(ops, o)
        hits.append(best if (best is not None and bd <= tol) else None)
    _blank_all(doc, xref, data, [op for o, h in zip(origins, hits) if h is not None for op in _run(ops, h, o, tol)])
    return [True if h is not None else bool(remove_text_at(doc, page, o, tol)) for o, h in zip(origins, hits)]


def _nearest(ops, origin):
    ox, oy = origin[0], origin[1]            # (origin 4'lu de olabilir: bkz. _run)
    best, bd = None, 1e9
    for o in ops:
        dd = ((o["origin"][0] - ox) ** 2 + (o["origin"][1] - oy) ** 2) ** 0.5
        if dd < bd:
            bd, best = dd, o
    return best, bd


def _blank(doc, xref, data, op):
    """Metin operatorunun operandini bosalt (metin cizilmez, baska hicbir sey degismez)."""
    s, e = op["operand"]["start"], op["operand"]["end"]
    repl = b"[]" if op["op"] == "TJ" else b"()"
    doc.update_stream(xref, data[:s] + repl + data[e:])


def _form_matrix(doc, fx):
    kind, val = doc.xref_get_key(fx, "Matrix")
    if kind != "array":
        return IDENT
    try:
        nums = [float(v) for v in val.strip("[]").split()]
        return tuple(nums) if len(nums) == 6 else IDENT
    except ValueError:
        return IDENT


def _search_forms(doc, page, base, dos, origin, tol, depth=4):
    """Sayfanin cagirdigi Form XObject'lerde (ic ice dahil) origin'deki metni
    arar. Bulursa ([(kap, ad_token, form_xref), ...], operator) dondurur;
    kap 0 = sayfanin kendisi."""
    names = {}
    for fx, name, invoker, _bbox in page.get_xobjects():
        names[(invoker, name)] = fx

    def walk(container, calls, chain, level):
        for do in calls:
            fx = names.get((container, do["name"]))
            if fx is None or doc.xref_get_key(fx, "Subtype") != ("name", "/Form"):
                continue
            ctm = _matmul(_form_matrix(doc, fx), do["ctm"])
            ops, sub = _scan(doc.xref_stream(fx), base, ctm)
            link = chain + [(container, do["tok"], fx)]
            best, bd = _nearest(ops, origin)
            if best is not None and bd <= tol:
                return link, _run(ops, best, origin, tol)
            if level > 1:
                r = walk(fx, sub, link, level - 1)
                if r:
                    return r
        return None

    return walk(0, dos, [], depth)


def _users(doc, fx):
    """Form nesnesinin belgede kac yerden (sayfa ya da baska form) cagrildigi."""
    return sum(1 for pg in doc for x in pg.get_xobjects() if x[0] == fx)


def _privatize_chain(doc, page, chain):
    """Zincirdeki PAYLASILAN form nesnelerini bu sayfaya ozel kopyalar ve
    duzenlenecek son formun xref'ini dondurur.

    ONEMLI: ayni form nesnesini birden cok sayfa kullaniyorsa (filigranlarda
    yaygin) dogrudan duzenlemek metni TUM sayfalardan siler. Kopyalayip
    cagiran yerdeki adi kopyaya yonlendirince sadece bu sayfa degisir.
    Kopya akisi orijinalle byte byte ayni oldugu icin taranan konumlar gecerli kalir."""
    cur = 0
    for container, tok, fx in chain:
        # kap bu dongude kopyalanmis olabilir: token konumlari kopyada da ayni
        if _users(doc, fx) > 1:
            fx = _copy_form(doc, page, cur, tok, fx)
        cur = fx
    return cur


def _ref_xref(val):
    """'12 0 R' -> 12"""
    return int(val.split()[0])


def add_xobject(doc, holder, name, ref):
    add_resource(doc, holder, "XObject", name, ref)


def add_resource(doc, holder, cat, name, ref):
    """holder (sayfa ya da form xref'i) kaynaklarina /<cat>/<name> ekler (cat:
    XObject, ExtGState ...).

    PyMuPDF'in xref_set_key'i yol dolayli nesneden geciyorsa ("/Resources
    12 0 R" - gercek PDF'lerde cok yaygin) 'path has indirects' hatasi verir;
    burada referanslar adim adim izlenip anahtar dogru nesneye yazilir.
    Paylasilan bir kaynak sozlugune YENI ve benzersiz bir ad eklemek diger
    sayfalari etkilemez."""
    kind, val = doc.xref_get_key(holder, "Resources")
    if kind == "null":
        raise _Skip()   # kaynaklar miras aliniyor: sayfaya sozluk eklemek mirasi gölgeler
    if kind == "xref":
        container, prefix = _ref_xref(val), ""
    else:
        container, prefix = holder, "Resources/"
    kind, val = doc.xref_get_key(container, prefix + cat)
    if kind == "xref":
        doc.xref_set_key(_ref_xref(val), name, ref)
    elif kind == "dict":
        doc.xref_set_key(container, prefix + cat + "/" + name, ref)
    else:
        doc.xref_set_key(container, prefix + cat, f"<</{name} {ref}>>")


def extgstate_blend(doc, page, name):
    """Sayfa kaynaklarindaki /ExtGState/<name> nesnesinin /BM degeri ('Multiply',
    'Normal' ...); nesnede BM yoksa / bulunamazsa None."""
    import re
    if not name:
        return None
    try:
        kind, val = doc.xref_get_key(page.xref, "Resources")
        if kind == "xref":
            container, prefix = _ref_xref(val), ""
        elif kind == "dict":
            container, prefix = page.xref, "Resources/"
        else:
            return None
        kind, val = doc.xref_get_key(container, prefix + "ExtGState")
        if kind == "xref":
            kind, val = doc.xref_get_key(_ref_xref(val), name)
        elif kind == "dict":
            kind, val = doc.xref_get_key(container, prefix + "ExtGState/" + name)
        else:
            return None
        if kind == "xref":
            val = doc.xref_object(_ref_xref(val), compressed=True)
        elif kind != "dict":
            return None
        m = re.search(r"/BM\s*\[?\s*/(\w+)", val)
        return m.group(1) if m else None
    except Exception:
        return None


def text_blend_at(doc, page, origin, tol=2.0, _cache=None, clean=False):
    """origin'deki metin operatorunun karisim modu (sayfanin kendi akisinda).
    _cache: ad -> karisim modu (ayni sayfada art arda sorgularda paylasilir). Operatorun
    "gs" listesi o ana kadarki TUM gs adlarini tasir (yuzlerce, cogu ayni ad): her biri
    icin belgeye sormak tek yazida ~50 ms, 130 yazilik toplu tasimada 7 sn tutuyordu.
    clean: cagiran HEMEN ARDINDAN bu yaziyi silecekse True verir -> sayfa simdi temizlenir ve
    sorgu, silmenin de kullanacagi akisi tarar (tek tarama; yoksa ham ve temiz akis ayri ayri
    ayristirilirdi). Yalniz sorgu icin (surukleme onizlemesi) False: belgeye dokunulmaz."""
    if clean:
        xrefs = clean_page(doc, page)
        ops = find_show_ops(doc.xref_stream(xrefs[0]) if xrefs else b"", page.transformation_matrix)
    else:
        ops = _ops_for_query(page)
    op, d = _nearest(ops, origin)
    if op is None or d > tol:
        return None
    cache = {} if _cache is None else _cache
    for name in reversed(op.get("gs") or ()):      # en son BM tanimlayan gecerli
        if name not in cache:
            cache[name] = extgstate_blend(doc, page, name)
        bm = cache[name]
        if bm is not None:
            return None if bm in ("Normal", "Compatible") else bm
    return None


def text_blends_at(doc, page, origins, tol=2.0, clean=False):
    """Birden cok metnin karisim modu (akis ve kaynak sozlugu bir kez okunur). clean: bkz.
    text_blend_at."""
    cache = {}
    return [text_blend_at(doc, page, o, tol, cache, clean) for o in origins]


def _copy_form(doc, page, container, tok, fx):
    holder = page.xref if container == 0 else container
    new = doc.get_new_xref()
    doc.update_object(new, "<<>>")
    doc.xref_copy(fx, new)
    name = f"RvF{new}"
    add_xobject(doc, holder, name, f"{new} 0 R")
    sx = single_stream(doc, page) if container == 0 else container
    data = doc.xref_stream(sx)
    s, e = tok
    doc.update_stream(sx, data[:s] + b"/" + name.encode() + data[e:])
    return new
