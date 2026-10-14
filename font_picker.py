"""
font_picker.py
--------------
Duzenle panelindeki yazi tipi kutusu: elle yazilmis aileler + bilgisayarda KURULU fontlar
(font_resolver.menu_fonts; yalniz PDF'e yazilabilenler). Liste kalabalik oldugu icin kutuya
yazarak aranir (adin herhangi bir yerinde gecen, buyuk / kucuk harf fark etmez).

- Kurulu fontlar ilk acilista (ya da kutuya ilk odaklanildiginda) eklenir; tarama bir kez yapilir
  ve pencere acildiktan sonra arka planda baslar (font_resolver.warm_up).
- Ilk satir "Otomatik (orijinal)" (veri None): degismedi.
- Secilen font PDF'e yazilamiyorsa (dosya acilmiyor, Turkce harfleri yok) secilmez, onceki secim
  geri gelir ve rejected(ad, neden) sinyali gider - sessizce baska fontla yazilmaz.
"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QCompleter

import font_resolver


class FontCombo(QComboBox):
    rejected = Signal(str, str)

    def __init__(self, auto_text, parent=None):
        super().__init__(parent)
        self._filled = False
        self._last = 0
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.NoInsert)
        self.addItem(auto_text, None)
        for display, key in font_resolver.FONT_DISPLAY_NAMES:
            self.addItem(display, key)
        comp = QCompleter(self.model(), self)
        comp.setFilterMode(Qt.MatchContains)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setCompletionMode(QCompleter.PopupCompletion)
        self.setCompleter(comp)
        comp.activated[str].connect(self._picked_text)
        self.lineEdit().editingFinished.connect(self._typed)
        self.currentIndexChanged.connect(self._check)

    # ---- kurulu fontlari ekle (bir kez)
    def fill(self):
        if self._filled:
            return
        self._filled = True
        cur = self.currentData()
        self.blockSignals(True)
        try:
            while self.count() > 1:
                self.removeItem(1)
            for display, key in font_resolver.menu_fonts():
                self.addItem(display, key)
            # acilan liste / arama onerileri en uzun ada gore (kutu dar: 'Franklin Gothic Medi...')
            fm = self.view().fontMetrics()
            wide = max(fm.horizontalAdvance(self.itemText(k)) for k in range(self.count())) + 36
            self.view().setMinimumWidth(wide)
            self.completer().popup().setMinimumWidth(wide)
            i = self.findData(cur) if cur is not None else 0
            self.setCurrentIndex(i if i >= 0 else 0)
            self._last = self.currentIndex()
        finally:
            self.blockSignals(False)

    def showPopup(self):
        self.fill()
        super().showPopup()

    def focusInEvent(self, ev):
        self.fill()
        super().focusInEvent(ev)

    def findData(self, data, *a):
        i = super().findData(data, *a)
        if i < 0 and data is not None and not self._filled:
            self.fill()
            i = super().findData(data, *a)
        return i

    # ---- arama
    def _picked_text(self, text):
        i = self.findText(text, Qt.MatchFixedString)
        if i >= 0:
            self.setCurrentIndex(i)

    def _typed(self):
        """Yazilan ad listede yoksa (yarim / yanlis yazim) kutu secili fontun adina doner."""
        text = self.lineEdit().text().strip()
        i = self.findText(text, Qt.MatchFixedString) if text else -1
        if i >= 0 and i != self.currentIndex():
            self.setCurrentIndex(i)
        elif self.lineEdit().text() != self.itemText(self.currentIndex()):
            self.lineEdit().setText(self.itemText(self.currentIndex()))

    # ---- secilen font gercekten yazilabiliyor mu
    def _check(self, i):
        key = self.itemData(i)
        if key is not None:
            ok, why = font_resolver.font_usable(key)
            if not ok:
                self.blockSignals(True)
                self.setCurrentIndex(self._last if 0 <= self._last < self.count() else 0)
                self.blockSignals(False)
                self.rejected.emit(self.itemText(i), why)
                return
        self._last = i
