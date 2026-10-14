"""
safe_write.py
-------------
Diske dosya yazan HER yer buradan gecer (Birlestir, Bol, resim / fotograf kaydetme,
resimlerden PDF, Excel'e aktarma, secili resmi kaydetme). Iki guvence:

1) GUVENLI YAZMA: icerik once hedefle AYNI klasorde, benzersiz adli gecici bir dosyaya yazilir;
   is basariyla bitince hedefin yerine konur. Yarida kalan is (disk doldu, cizim hata verdi)
   var olan dosyayi BOZMAZ, klasorde yarim dosya BIRAKMAZ. Birden cok dosya yazan islerde
   (Bol, sayfalari resim olarak kaydet) ya hepsi yerine konur ya hicbiri.

       with safe_write.Writer() as w:
           doc.save(w.path(hedef), garbage=3, deflate=True)     # gecici yola yazilir
           w.write(baska_hedef, veri)                           # bayt verisi

   Eskiden: Birlestir hedefe dogrudan yaziyordu (disk dolunca var olan PDF 16 baytlik yarim
   dosyaya donuyordu); resim kaydetme hedefi once ACIP bosaltiyor, sonra goruntuyu hazirliyordu
   (hazirlama hata verince eski resim 0 bayt kaliyordu) - 2026-10-13.

2) ACIK BELGE: hedef, programda bir sekmede acik olan dosyaysa yazilmaz (TargetInUse). Yoksa
   diskteki dosya degisir, sekme eski halini gostermeye devam eder; o sekmede Kaydet de yeni
   dosyayi ezer. Pencereler isi baslatmadan once blocked() ile sorar; Writer yine de denetler.

Acik dosyalarin listesi pencereden gelir (open_files). Bu modul PySide6'yi YUKLEMEZ (motor
modulleri de kullanir; "PySide6, fitz'ten once" kurali bozulmasin) - blocked() kutuyu gosterirken
gec yukler.
"""
import os
import tempfile

from i18n import _t

# pencere atar: su an sekmelerde acik dosyalarin yollarini veren islev
open_files = lambda: ()


class TargetInUse(Exception):
    """Hedef dosya programda bir sekmede acik."""

    def __init__(self, path):
        super().__init__(_t("Bu dosya şu anda bir sekmede açık:\n{path}\n\n"
                            "Başka bir ad seçin ya da önce o sekmeyi kapatın.", path=path))
        self.path = path


def key(path):
    """Ayni dosyayi gosteren yollar ayni anahtari verir (buyuk / kucuk harf, kisayol, goreli yol)."""
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def in_use(path, ignore=None):
    """path bir sekmede acik mi. ignore: sayilmayacak yol (belgenin KENDI dosyasina kaydetmesi)."""
    k = key(path)
    if ignore and key(ignore) == k:
        return False
    try:
        return any(p and key(p) == k for p in open_files())
    except Exception:
        return False


def blocked(parent, paths):
    """Hedeflerden biri bir sekmede aciksa kullaniciya soyler ve True doner (is baslatilmaz)."""
    for p in ([paths] if isinstance(paths, str) else paths):
        if in_use(p):
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(parent, _t("Kaydedilemedi"), str(TargetInUse(p)))
            return True
    return False


class Writer:
    """Bir ya da birkac dosyayi guvenli yazar (bkz. modul aciklamasi). with blogu hata ile biterse
    hicbir hedefe dokunulmaz, gecici dosyalar silinir."""

    def __init__(self, check_open=True):
        self.check_open = check_open
        self._items = []                       # [(gecici, hedef)]

    def path(self, target):
        """Hedef icin yazilacak GECICI yol (ayni klasorde). Hedef bir sekmede aciksa TargetInUse."""
        target = os.path.abspath(target)
        if self.check_open and in_use(target):
            raise TargetInUse(target)
        fd, tmp = tempfile.mkstemp(prefix=os.path.basename(target) + ".", suffix=".tmp",
                                   dir=os.path.dirname(target))
        os.close(fd)
        self._items.append((tmp, target))
        return tmp

    def write(self, target, data):
        with open(self.path(target), "wb") as f:
            f.write(data)

    def _discard(self):
        for tmp, _ in self._items:
            try:
                os.remove(tmp)
            except OSError:
                pass
        self._items = []

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if et is not None:
            self._discard()
            return False
        if len(self._items) == 1:              # tek dosya: yerine koyma zaten tek adim
            tmp, target = self._items[0]
            try:
                os.replace(tmp, target)
            except BaseException:
                self._discard()
                raise
            self._items = []
            return False
        # COK DOSYA: hata yerine koyma asamasinda da olabilir (hedeflerden biri baska programda acik;
        # kilit is surerken de olusabilir - onceden bakmak yetmez). Her hedefin eski hali is bitene
        # kadar kenarda tutulur; bir tasima basarisiz olursa daha once yerine konanlar ESKI haline
        # doner, yeni olusturulanlar kalkar. (Eskiden oncekiler yeni haliyle kaliyordu: Bol'de
        # 1. parca yenilenmis, 2. eski, 3. yok - 2026-10-13.)
        done = []                              # [(hedef, eski halinin yedegi | None)]
        try:
            for tmp, target in self._items:
                backup = None
                if os.path.exists(target):
                    fd, backup = tempfile.mkstemp(prefix=os.path.basename(target) + ".", suffix=".bak",
                                                  dir=os.path.dirname(target))
                    os.close(fd)
                    try:
                        os.replace(target, backup)             # eski hali kenara (kilitliyse burada durur)
                    except BaseException:
                        os.remove(backup)
                        raise
                try:
                    os.replace(tmp, target)
                except BaseException:
                    if backup is not None:
                        os.replace(backup, target)             # bu hedefin eski hali yerine
                    raise
                done.append((target, backup))
        except BaseException:
            for target, backup in reversed(done):
                try:
                    if backup is not None:
                        os.replace(backup, target)             # eski hali geri
                    else:
                        os.remove(target)                      # is oncesinde yoktu
                except OSError:
                    pass
            self._discard()
            raise
        for _, backup in done:
            if backup is not None:
                try:
                    os.remove(backup)
                except OSError:
                    pass
        self._items = []
        return False
