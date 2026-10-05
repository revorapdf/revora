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

WS = b" \t\r\n\f\0"
DELIM = b"()<>[]{}/%"
IDENT = (1, 0, 0, 1, 0, 0)


def _matmul(m1, m2):
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1*a2 + b1*c2, a1*b2 + b1*d2,
            c1*a2 + d1*c2, c1*b2 + d1*d2,
            e1*a2 + f1*c2 + e2, e1*b2 + f1*d2 + f2)


def _tokenize(data: bytes):
    """Icerik akisini token'lara ayirir. Her token: {kind, start, end, val}.
    kind: number/string/hexstring/name/array/op."""
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


def _scan(data: bytes, base, ctm0=IDENT):
    """find_show_ops'un genel hali: (metin_operatorleri, Do_cagrilari).
    ctm0: akisin baslangic donusumu (form nesnesi icin: formun /Matrix'i x
    cagrildigi yerdeki CTM). Do cagrilari: [{name, tok:(start,end), ctm}]."""
    ba, bb, bc, bd, be, bf = tuple(base)
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
        if op == b"q":
            ctm_stack.append(ctm)
            gs_stack.append(gs)
        elif op == b"Q":
            if ctm_stack:
                ctm = ctm_stack.pop()
            if gs_stack:
                gs = gs_stack.pop()
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
                            "operand": {"start": operand["start"],
                                        "end": operand["end"]}})
        elif op == b"Do" and idx > 0 and toks[idx - 1]["kind"] == "name":
            nt = toks[idx - 1]
            dos.append({"name": nt["val"][1:].decode("latin-1"),
                        "tok": (nt["start"], nt["end"]), "ctm": ctm})
        nums = []
    return out, dos


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
    depth = under = 0
    dirty = False
    for t in _tokenize(data):
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
    if dirty or depth or under:
        data = b"q\n" * (under + 1) + data + b"\nQ" * depth + b"\nQ\n"
        doc.update_stream(xref, data)


def remove_text_at(doc, page, origin, tol=2.0):
    """origin (sol-ust sayfa koordinati) konumundaki metin gosterme
    operatorunu bulur ve operandini bosaltir (metin cizilmez, baska
    HICBIR sey degismez). Basarili olursa True.

    Once tum icerik akislarini tek akista birlestirir (clean_contents)
    ki cok-akisli sayfalarda da tek yerde duzenleyelim."""
    page.clean_contents()
    xrefs = page.get_contents()
    if not xrefs:
        return False
    xref = xrefs[0]
    data = doc.xref_stream(xref)
    base = page.transformation_matrix
    ops, dos = _scan_cached(data, base)

    best, bd = _nearest(ops, origin)
    if best is not None and bd <= tol:
        _blank(doc, xref, data, best)
        return True

    # Sayfanin kendi akisinda yok: metin bir Form XObject icinde olabilir
    # (Adobe'nin "Filigran ekle"si filigrani boyle koyar). Onlara in.
    try:
        found = _search_forms(doc, page, base, dos, origin, tol)
    except Exception:
        return False
    if found is None:
        return False
    chain, op = found
    try:
        target = _privatize_chain(doc, page, chain)
    except Exception:
        # _Skip ya da beklenmedik yapi: cokme yerine geometrik yedege dus.
        # (_copy_form sirasi: once kopya, sonra kaynak adi, en son akistaki ad;
        # yarida kalirsa en fazla sahipsiz bir kopya kalir, kayitta temizlenir.)
        return False
    _blank(doc, target, doc.xref_stream(target), op)
    return True


# ---------------------------------------------------------------- form nesneleri
class _Skip(Exception):
    """Guvenli sekilde duzenlenemeyen yapi: geometrik yedege dus."""


_SCAN_CACHE = {}


def _scan_cached(data, base):
    """_scan (Python'da yavas) sonucunu akisin icerigine gore hatirlar: ayni akis
    ikinci kez taranmaz (surukleme onizlemesi + asil tasima ayni akisi tarar)."""
    key = (hashlib.md5(data).digest(), tuple(base))
    hit = _SCAN_CACHE.get(key)
    if hit is None:
        hit = _scan(data, base)
        if len(_SCAN_CACHE) >= 6:
            _SCAN_CACHE.pop(next(iter(_SCAN_CACHE)))
        _SCAN_CACHE[key] = hit
    return hit


def warm_scan(doc, pno):
    """Sayfanin (birlestirilmis) akisini onceden tara. Asil belgeye dokunmaz:
    birlestirme belgenin kopyasinda yapilir (sonuc ayni bytelar)."""
    try:
        live = doc[pno]                        # karisim modu sorgusu (text_blend_at) canli akisi tarar
        _scan_cached(live.read_contents(), live.transformation_matrix)
        tmp = type(doc)("pdf", doc.tobytes())
        try:
            page = tmp[pno]
            page.clean_contents()
            xrefs = page.get_contents()
            if xrefs:
                _scan_cached(tmp.xref_stream(xrefs[0]), page.transformation_matrix)
        finally:
            tmp.close()
    except Exception:
        pass


def remove_texts_at(doc, page, origins, tol=2.0):
    """Birden cok metin (paragrafin satirlari) tek taramada: hepsi sayfanin kendi
    akisindaysa operandlari sondan basa bosaltilir. Degilse tek tek remove_text_at."""
    page.clean_contents()
    xrefs = page.get_contents()
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
        found.append(best)
    seen = set()
    for op in sorted(found, key=lambda op: op["operand"]["start"], reverse=True):
        st, en = op["operand"]["start"], op["operand"]["end"]
        if st in seen:
            continue
        seen.add(st)
        data = data[:st] + (b"[]" if op["op"] == "TJ" else b"()") + data[en:]
    doc.update_stream(xref, data)
    return True


def remove_texts_each(doc, page, origins, tol=2.0):
    """Birden cok metni TEK taramada kaldir -> her biri icin kaldirildi mi ([bool]).
    Sayfanin kendi akisindakilerin operandlari sondan basa bosaltilir (akis bir kez
    okunur, bir kez yazilir). Orada bulunamayanlar (form nesnesi icindeki yazi) tek tek
    remove_text_at ile denenir. Toplu tasima / silme icin: yazi basina ayri tarama, 80
    yazilik bir tabloda 10+ saniye suruyordu."""
    page.clean_contents()
    xrefs = page.get_contents()
    if not xrefs:
        return [False] * len(origins)
    xref = xrefs[0]
    data = doc.xref_stream(xref)
    ops, _ = _scan_cached(data, page.transformation_matrix)
    hits = []
    for o in origins:
        best, bd = _nearest(ops, o)
        hits.append(best if (best is not None and bd <= tol) else None)
    seen = set()
    for op in sorted((h for h in hits if h is not None), key=lambda op: op["operand"]["start"], reverse=True):
        st, en = op["operand"]["start"], op["operand"]["end"]
        if st in seen:
            continue
        seen.add(st)
        data = data[:st] + (b"[]" if op["op"] == "TJ" else b"()") + data[en:]
    if seen:
        doc.update_stream(xref, data)
    return [True if h is not None else bool(remove_text_at(doc, page, o, tol)) for o, h in zip(origins, hits)]


def _nearest(ops, origin):
    ox, oy = origin
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
                return link, best
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


def text_blend_at(doc, page, origin, tol=2.0, _cache=None):
    """origin'deki metin operatorunun karisim modu (sayfanin kendi akisinda).
    _cache: ad -> karisim modu (ayni sayfada art arda sorgularda paylasilir). Operatorun
    "gs" listesi o ana kadarki TUM gs adlarini tasir (yuzlerce, cogu ayni ad): her biri
    icin belgeye sormak tek yazida ~50 ms, 130 yazilik toplu tasimada 7 sn tutuyordu."""
    ops = find_show_ops(page.read_contents(), page.transformation_matrix)
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


def text_blends_at(doc, page, origins, tol=2.0):
    """Birden cok metnin karisim modu (akis ve kaynak sozlugu bir kez okunur)."""
    cache = {}
    return [text_blend_at(doc, page, o, tol, cache) for o in origins]


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
