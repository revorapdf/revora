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


def font_alias(page):
    """Yazi tipi kaynak adlari -> yazi tipinin ASIL adi (alt kume oneki atilmis, kucuk harf), KAP
    basina: {0: sayfanin kendi adlari, form_xref: o formun adlari}. Ayni ad ayni kapta farkli yazi
    tiplerine gidiyorsa None (belirsiz: sikiya bakilir). (GMC Inspire PDF'inde sayfadaki /F0 kalin
    yazi tipi, formlardaki /F0 ince yazi tipi.)"""
    out = {}
    try:
        fonts = page.get_fonts(full=True)
    except Exception:
        return out
    for f in fonts:
        base, name, owner = f[3] or "", f[4] or "", f[6] if len(f) > 6 else 0
        if not name:
            continue
        base = (base.split("+", 1)[1] if len(base) > 7 and base[6] == "+" else base).lower()
        key = b"/" + name.encode("latin-1", "replace")
        m = out.setdefault(owner or 0, {})
        if key in m and m[key] != base:
            m[key] = None
        else:
            m[key] = base
    return out


def _same_look(a, b, alias):
    """Iki operatorun gorunumu ayni mi: renk ve boyut ayni, yazi tipi ya ayni kaynak ya da AYNI ASIL
    yazi tipine giden iki kaynak (GMC Inspire PDF'leri her Turkce harfi ayni yazi tipinin ikinci, CID
    kodlu kopyasiyla yaziyor: "L" /F, "u" /F2, "tfen" /F - MuPDF hepsini tek yazi okur)."""
    if a == b:
        return True
    if not alias or a is None or b is None or a[1] != b[1] or a[0] is None or b[0] is None:
        return False
    (na, sa), (nb, sb) = a[0], b[0]
    if abs((sa or 0) - (sb or 0)) > 0.01:
        return False
    fa, fb = alias.get(na), alias.get(nb)
    return fa is not None and fa == fb


def _run(ops, first, origin, tol=2.0, alias=None):
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
        if op.get("follows") and _same_look(op.get("look"), first.get("look"), alias):
            # Yeni konum verilmeden, onceki parcanin BITTIGI yerden devam ediyor (yeri hesaplanamaz:
            # harf genislikleri bilinmiyor) ve gorunumu ayni: ayni yazinin devami. GMC Inspire PDF'i
            # Turkce harfte yazi tipini degistirip konum vermeden devam ediyor ("b" /F, "o" /F2, "lumunu"
            # /F ...); eskiden ilk Turkce harfte duruluyor, satirin kalani silinmiyordu (duzenlenen
            # paragraf eskisinin ustune yaziliyordu).
            out.append(op)
            continue
        if not op["direct"]:
            px, py = op["origin"][0] - ox, op["origin"][1] - oy
            along, across = px * ux + py * uy, abs(py * ux - px * uy)
            if not _same_look(op.get("look"), first.get("look"), alias) or across > tol                     or not (0.5 < along < length - 0.25):
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
    moved = True             # son gosterme operatorunden beri yazi konumu yeniden verildi mi (bkz. _run)
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
            moved = True
        elif op == b"Tm" and len(nums) >= 6:
            Tm = tuple(nums[-6:])
            Tlm = Tm
            moved = True
        elif op == b"Td" and len(nums) >= 2:
            Tlm = _matmul((1, 0, 0, 1, nums[-2], nums[-1]), Tlm)
            Tm = Tlm
            moved = True
        elif op == b"TD" and len(nums) >= 2:
            leading = -nums[-1]
            Tlm = _matmul((1, 0, 0, 1, nums[-2], nums[-1]), Tlm)
            Tm = Tlm
            moved = True
        elif op == b"TL" and len(nums) >= 1:
            leading = nums[-1]
        elif op == b"T*":
            Tlm = _matmul((1, 0, 0, 1, 0, -leading), Tlm)
            Tm = Tlm
            moved = True
        elif op in (b"Tj", b"'", b'"', b"TJ"):
            if op in (b"'", b'"'):
                Tlm = _matmul((1, 0, 0, 1, 0, -leading), Tlm)
                Tm = Tlm
                moved = True
            full = _matmul(Tm, ctm)
            x, y = full[4], full[5]
            origin = (ba * x + bc * y + be, bb * x + bd * y + bf)
            operand = last_arr if op == b"TJ" else last_str
            if operand is not None:
                out.append({"origin": origin, "op": op.decode(), "gs": gs,     # zincir
                            "i": len(out), "direct": since == 0 and bool(out), "look": look,
                            "follows": not moved and bool(out),
                            "operand": {"start": operand["start"],
                                        "end": operand["end"]}})
            since = 0
            moved = False
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

    alias = font_alias(page)
    best, bd = _nearest(ops, origin)
    if best is not None and bd <= tol:
        _blank_all(doc, xref, data, _run(ops, best, origin, tol, alias.get(0)))
        return True

    # Sayfanin kendi akisinda yok: metin bir Form XObject icinde olabilir
    # (Adobe'nin "Filigran ekle"si filigrani boyle koyar). Onlara in.
    try:
        found = _search_forms(doc, page, base, dos, origin, tol, alias=alias)
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
    alias = font_alias(page)
    found = []
    for o in origins:
        best, bd = _nearest(ops, o)
        if best is None or bd > tol:
            return all(remove_text_at(doc, page, q, tol) for q in origins)
        found.extend(_run(ops, best, o, tol, alias.get(0)))
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
    alias = font_alias(page)
    hits = []
    for o in origins:
        best, bd = _nearest(ops, o)
        hits.append(best if (best is not None and bd <= tol) else None)
    _blank_all(doc, xref, data, [op for o, h in zip(origins, hits) if h is not None for op in _run(ops, h, o, tol, alias.get(0))])
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


def _search_forms(doc, page, base, dos, origin, tol, depth=4, alias=None):
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
                return link, _run(ops, best, origin, tol, (alias or {}).get(fx))
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



# ---------------------------------------------------------------- formu sayfaya acma ("zarfi ac")
_RES_CATS = ("Font", "XObject", "ExtGState", "ColorSpace", "Pattern", "Shading", "Properties")
_PAINT = {b"f", b"F", b"f*", b"S", b"s", b"B", b"B*", b"b", b"b*"}


def _dict_keys(text):
    """PDF sozluk metninin ('<< /A 1 0 R /B << ... >> >>') UST duzey anahtarlari (sirayla)."""
    keys, i, n = [], 0, len(text)
    i = text.find("<<")
    if i < 0:
        return keys
    i += 2

    def skip_ws(j):
        while j < n and text[j] in " \t\r\n\f\x00":
            j += 1
        return j

    def skip_value(j):
        j = skip_ws(j)
        if text.startswith("<<", j):
            depth = 0
            while j < n:
                if text.startswith("<<", j):
                    depth += 1
                    j += 2
                elif text.startswith(">>", j):
                    depth -= 1
                    j += 2
                    if depth == 0:
                        return j
                elif text[j] == "(":
                    j = skip_string(j)
                else:
                    j += 1
            return j
        if text[j:j + 1] == "[":
            depth = 0
            while j < n:
                c = text[j]
                if c == "[":
                    depth += 1
                elif c == "]":
                    depth -= 1
                    if depth == 0:
                        return j + 1
                elif c == "(":
                    j = skip_string(j) - 1
                j += 1
            return j
        if text[j:j + 1] == "(":
            return skip_string(j)
        m = re.match(r"\d+\s+\d+\s+R", text[j:])           # dolayli nesne: "12 0 R"
        if m:
            return j + m.end()
        m = re.match(r"/?[^\s/<>\[\]()]+|/", text[j:])
        return j + (m.end() if m else 1)

    def skip_string(j):
        depth = 0
        while j < n:
            c = text[j]
            if c == "\\":
                j += 2
                continue
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    return j + 1
            j += 1
        return j

    while True:
        i = skip_ws(i)
        if i >= n or text.startswith(">>", i):
            return keys
        m = re.match(r"/([^\s/<>\[\]()]+)", text[i:])
        if not m:
            return keys
        keys.append(m.group(1))
        i = skip_value(i + m.end())


def _res_entries(doc, xref, prefix):
    """xref nesnesinin <prefix>Resources sozlugunden {kategori: {ad: deger metni}}; kaynak
    sozlugu yoksa None (miras alir)."""
    kind, val = doc.xref_get_key(xref, prefix + "Resources")
    if kind == "null":
        return None
    if kind == "xref":
        holder, pre = _ref_xref(val), ""
    else:
        holder, pre = xref, prefix + "Resources/"
    out = {}
    for cat in _RES_CATS:
        kind, val = doc.xref_get_key(holder, pre + cat)
        if kind == "xref":
            h2, p2 = _ref_xref(val), ""
            names = list(doc.xref_get_keys(h2))
        elif kind == "dict":
            h2, p2 = holder, pre + cat + "/"
            names = _dict_keys(val)
        else:
            continue
        ent = {}
        for nm in names:
            k2, v2 = doc.xref_get_key(h2, p2 + nm)
            if k2 == "xref":
                ent[nm] = v2
            elif k2 in ("dict", "array", "name", "int", "float", "bool"):
                ent[nm] = v2
        if ent:
            out[cat] = ent
    return out


def _has_paint(data):
    return any(t["kind"] == "op" and t["val"] in _PAINT for t in tokens(data))


def _form_paints(doc, fx, depth=4):
    """Formda ya da ICINDEKI formlarda (ic ice zarf: PyMuPDF'in show_pdf_page'i, bazi araclar) cizim
    (boyanan yol) var mi."""
    body = doc.xref_stream(fx)
    if body and _has_paint(body):
        return True
    if depth <= 1:
        return False
    for val in ((_res_entries(doc, fx, "") or {}).get("XObject") or {}).values():
        try:
            cx = _ref_xref(val)
        except Exception:
            continue
        if doc.xref_get_key(cx, "Subtype") == ("name", "/Form") and _form_paints(doc, cx, depth - 1):
            return True
    return False


def inline_forms(doc, page):
    """ZARFI AC: sayfanin akisindan DOGRUDAN cagrilan ve icinde cizim (boyanan yol) olan Form
    XObject'lerin icerigi sayfa akisina acilir: "/Ad Do" yerine "q <Matrix> cm <BBox> re W n <formun
    akisi> Q". Formun kaynaklari sayfanin kaynaklarina eklenir; ayni ad baska nesneye gidiyorsa ad
    degistirilir (formun akisinda da). Gorunum degismez. Neden: cizim duzenleme (pdf_paths) yalniz
    sayfanin kendi akisini okur; HTML -> PDF araclari (HiQPdf: e-Arsiv faturasi) sayfanin TAMAMINI
    bir formun icine koyuyor, cizgiler secilemiyordu. Formun kendisi silinmez (baska sayfa / yer
    kullaniyor olabilir). -> acilan cagri sayisi (0: dokunulmadi)."""
    xref = single_stream(doc, page)
    if xref is None:
        return 0
    forms = {}
    for fx, name, invoker, _bbox in page.get_xobjects():
        if invoker == 0 and doc.xref_get_key(fx, "Subtype") == ("name", "/Form"):
            forms[("/" + name).encode("latin-1", "replace")] = fx
    if not forms:
        return 0
    data = doc.xref_stream(xref)
    toks = tokens(data)
    calls = [(toks[i - 1], t) for i, t in enumerate(toks)
             if i > 0 and t["kind"] == "op" and t["val"] == b"Do" and toks[i - 1]["kind"] == "name"
             and toks[i - 1]["val"] in forms]
    if not calls:
        return 0
    contents = {}
    for nt, _do in calls:
        fx = forms[nt["val"]]
        if fx not in contents:
            body = doc.xref_stream(fx)
            contents[fx] = body if body and _form_paints(doc, fx) else None
    calls = [(nt, do) for nt, do in calls if contents[forms[nt["val"]]] is not None]
    if not calls:
        return 0
    page_res = _res_entries(doc, page.xref, "")
    if page_res is None:
        raise _Skip()                                  # (kaynaklar miras: eklemek mirasi golgeler)
    used = {nm for ent in page_res.values() for nm in ent}
    # Sayfanin akisinda gecen her ad da DOLU: kaynaklarda tanimsiz bir ada (bozuk ama goruntuleyicilerin
    # idare ettigi PDF) formun kaynagini eklemek sayfanin kendi yazisini o kaynaga baglardi.
    used |= {t["val"][1:].decode("latin-1", "replace") for t in toks if t["kind"] == "name"}
    new_body = {}
    for fx in {forms[nt["val"]] for nt, _d in calls}:
        body = contents[fx]
        fres = _res_entries(doc, fx, "") or {}
        rename = {}
        for cat, ent in fres.items():
            have = page_res.get(cat, {})
            for nm, val in ent.items():
                if have.get(nm) == val:
                    continue                           # (ayni ad, ayni nesne: zaten var)
                if nm in used or nm in rename:
                    new = rename.get(nm)
                    if new is None:
                        k = 1
                        while "%sf%d" % (nm, k) in used:
                            k += 1
                        new = rename[nm] = "%sf%d" % (nm, k)
                        used.add(new)
                    add_resource(doc, page.xref, cat, new, val)
                    page_res.setdefault(cat, {})[new] = val
                else:
                    add_resource(doc, page.xref, cat, nm, val)
                    page_res.setdefault(cat, {})[nm] = val
                    used.add(nm)
        if rename:                                     # formun akisinda ad degistir (sondan basa)
            parts, last = [], 0
            for t in tokens(body):
                if t["kind"] == "name":
                    nm = t["val"][1:].decode("latin-1", "replace")
                    if nm in rename:
                        parts.append(body[last:t["start"]])
                        parts.append(b"/" + rename[nm].encode("latin-1"))
                        last = t["end"]
            parts.append(body[last:])
            body = b"".join(parts)
        M = _form_matrix(doc, fx)
        kind, bb = doc.xref_get_key(fx, "BBox")
        clip = b""
        if kind == "array":
            try:
                x0, y0, x1, y1 = (float(v) for v in bb.strip("[]").split())
                clip = b"%g %g %g %g re W n\n" % (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            except ValueError:
                clip = b""
        new_body[fx] = (b"q\n%g %g %g %g %g %g cm\n" % tuple(M)) + clip + body + b"\nQ"
    parts, last = [], 0
    for nt, do in calls:
        parts.append(data[last:nt["start"]])
        parts.append(new_body[forms[nt["val"]]])
        last = do["end"]
    parts.append(data[last:])
    doc.update_stream(xref, b"".join(parts))
    return len(calls)


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
