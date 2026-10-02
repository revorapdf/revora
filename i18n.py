"""
i18n.py
-------
Cok dil destegi.

Kaynak dil Turkce: arayuzdeki her metin _t("Turkce metin") ile yazilir. Secili
dilin dosyasinda (locales/<dil>.json, {"Turkce metin": "ceviri"}) karsiligi varsa
o gosterilir, yoksa Turkcesi -> eksik ceviri hicbir seyi bozmaz.
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
import sys

SOURCE = "tr-TR"
# (kod, dilin kendi dilindeki adi) - listede dosyasi olmayanlar gosterilmez
LANGUAGES = (("tr-TR", "Türkçe"), ("en-US", "English"), ("de-DE", "Deutsch"),
             ("fr-FR", "Français"), ("es-ES", "Español"))

_lang = SOURCE
_table = {}


def locales_dir():
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, "locales")


def available():
    """Secilebilecek diller: kaynak dil + ceviri dosyasi olanlar."""
    return [(c, n) for c, n in LANGUAGES
            if c == SOURCE or os.path.isfile(os.path.join(locales_dir(), c + ".json"))]


def set_language(code):
    """Dili sec; dosya yoksa / bozuksa kaynak dilde kalir. Secilen dili dondurur."""
    global _lang, _table
    _lang, _table = SOURCE, {}
    if code and code != SOURCE:
        try:
            with open(os.path.join(locales_dir(), code + ".json"), encoding="utf-8") as f:
                data = json.load(f)
            _table = {k: v for k, v in data.items() if isinstance(v, str) and v and not k.startswith("@")}
            _lang = code
        except (OSError, ValueError):
            pass
    return _lang


def language():
    return _lang


def qt_code():
    """Qt'nin kendi ceviri dosyasi icin kisa kod (qtbase_tr.qm -> 'tr')."""
    return _lang.split("-")[0]


def _t(text, **kw):
    s = _table.get(text, text)
    if kw:
        try:
            return s.format(**kw)
        except (KeyError, IndexError, ValueError):
            return text.format(**kw)        # ceviride yer tutucu hatasi: kaynagi goster
    return s
