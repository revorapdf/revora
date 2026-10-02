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


def resolve_font_path(base_font_name: str, force_bold: bool = None) -> tuple[str, bool, bool, bool]:
    """
    Verilen PDF font adina en uygun Windows font dosyasini bulur.
    force_bold verilirse (True/False), adindan cikarilan bold bilgisini gecersiz kilar.
    Return: (dosya_yolu, bold_mi, italic_mi, tam_eslesme_mi)
    """
    bold, italic = detect_style(base_font_name)
    if force_bold is not None:
        bold = force_bold
    key = _normalize(base_font_name)
    matched_family = _match_family(key)

    exact = matched_family is not None
    if matched_family is None:
        matched_family = FALLBACK_FAMILY

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
