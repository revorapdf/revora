"""
i18n.py
-------
Cok dil destegi.

Kaynak dil Turkce: arayuzdeki her metin _t("Turkce metin") ile yazilir. Secili
dilin dosyasinda (locales/<dil>.json, {"Turkce metin": "ceviri"}) karsiligi varsa
o gosterilir. Yoksa - ya da cevirinin yer tutuculari kaynakla tutmuyorsa - INGILIZCESI,
o da yoksa Turkcesi: Almanca arayuzde eksik bir satir Turkce degil Ingilizce gorunur.
(Turkce ve Ingilizce seciliyken donulecek tek yer kaynak metindir.)
Degisken iceren metinler yer tutuculu yazilir: _t("{n} sayfa eklendi", n=5).
(Metni f-string ile birlestirmeyin: baska dillerde kelime sirasi farkli.)

Dil, arayuz modulleri YUKLENMEDEN once set_language ile secilir (modul
seviyesindeki sabitler yuklenirken cevrilir); degisiklik yeniden baslatinca
gecerli olur. Bu modul PySide6 import ETMEZ: motor modulleri de kullanir ve
"PySide6, fitz'ten once" kurali bozulmasin.

Ad neden _t: kodda "_" kullanilmayan degisken olarak her yerde geciyor
(path, _ = ...); ayni fonksiyonda _("...") cagrisi o zaman cokerdi.
"""
import json
import os
import re
import string
import sys
import unicodedata

SOURCE = "tr-TR"
FALLBACK = "en-US"        # secili dilde cevirisi olmayan metin bu dilde gosterilir
# (kod, dilin kendi dilindeki adi) - listede dosyasi olmayanlar gosterilmez; ada gore alfabetik
LANGUAGES = (("de-DE", "Deutsch"), ("en-US", "English"), ("es-ES", "Español"),
             ("fr-FR", "Français"), ("it-IT", "Italiano"), ("nl-NL", "Nederlands"),
             ("pl-PL", "Polski"), ("pt-BR", "Português (Brasil)"), ("tr-TR", "Türkçe"))

_lang = SOURCE
_table = {}               # secili dilin cevirileri
_chain = []               # sirayla bakilan tablolar: [secili dil, Ingilizce]
_PH = re.compile(r"\{\w*\}")


def locales_dir():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "locales")


def _name_key(name):
    """Dil adlarini siralamak icin: aksan ve buyuk / kucuk harf farki sayilmaz (Español, E altinda)."""
    return "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).casefold()


def available():
    """Secilebilecek diller: kaynak dil + ceviri dosyasi olanlar; kendi adlarina gore alfabetik
    (Deutsch, English, Español, Français, Italiano, Nederlands, Polski, Português, Türkçe)."""
    return sorted(((c, n) for c, n in LANGUAGES
                   if c == SOURCE or os.path.isfile(os.path.join(locales_dir(), c + ".json"))),
                  key=lambda cn: _name_key(cn[1]))


def match(tag):
    """Windows dil etiketine ('de-AT', 'pt_PT', 'tr') uyan secilebilir dil; yoksa None.
    Once tam kod, sonra yalniz dil kismi (de-AT -> de-DE)."""
    tag = (tag or "").replace("_", "-").lower()
    codes = [c for c, _ in available()]
    for c in codes:
        if c.lower() == tag:
            return c
    for c in codes:
        if tag and c.lower().split("-")[0] == tag.split("-")[0]:
            return c
    return None


def resolve(saved, system=()):
    """Acilista kullanilacak dil. Kayitli tercih GECERLIYSE (secilebilir bir dil) o; degilse
    Windows'un dil listesindeki ilk desteklenen dil (de-AT -> Almanca, pt-PT -> Portekizce); o da
    yoksa Ingilizce. Kayitli ayara dokunmaz: yalniz bu acilis icin karar verir."""
    codes = [c for c, _ in available()]
    if saved in codes:
        return saved
    for tag in system or ():
        m = match(tag)
        if m:
            return m
    return FALLBACK if FALLBACK in codes else SOURCE


def _usable(key, val):
    """Ceviri kullanilabilir mi: bos degil, {yer tutucular} kaynakla ayni ve bicimi duzgun."""
    if not isinstance(val, str) or not val:
        return False
    if "{" not in key and "{" not in val and "}" not in val:
        return True
    if sorted(_PH.findall(key)) != sorted(_PH.findall(val)):
        return False
    try:
        list(string.Formatter().parse(val))          # "{n" gibi kapanmamis ayrac
    except ValueError:
        return False
    return True


def _load(code):
    """Dil dosyasi -> {kaynak metin: ceviri}; yalniz kullanilabilir satirlar. Dosya yok / bozuksa None."""
    try:
        with open(os.path.join(locales_dir(), code + ".json"), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return {k: v for k, v in data.items() if not k.startswith("@") and _usable(k, v)}
    except (OSError, ValueError):
        return None


def set_language(code):
    """Dili sec. Secilen dilin dosyasi yok / bozuksa Ingilizce, o da yoksa kaynak dil (Turkce).
    Turkce disindaki dillerde eksik ya da yer tutucusu hatali satirlar Ingilizcesinden tamamlanir.
    Gecerli olan dili dondurur."""
    global _lang, _table, _chain
    _lang, _table, _chain = SOURCE, {}, []
    if code and code != SOURCE:
        sel = _load(code)
        en = sel if code == FALLBACK else _load(FALLBACK)
        if sel is not None:
            _lang, _table = code, sel
            _chain = [sel] + ([en] if en is not None and en is not sel else [])
        elif en is not None:
            _lang, _table, _chain = FALLBACK, en, [en]
    return _lang


def language():
    return _lang


def qt_code():
    """Qt'nin kendi ceviri dosyasi icin kisa kod (qtbase_tr.qm -> 'tr')."""
    return _lang.split("-")[0]


def _t(text, **kw):
    for table in _chain:                    # secili dil, sonra Ingilizce
        s = table.get(text)
        if s is None:
            continue
        if not kw:
            return s
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            continue                        # (yer tutucu hatasi: siradaki dile bak)
    return text.format(**kw) if kw else text
