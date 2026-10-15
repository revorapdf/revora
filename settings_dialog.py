"""
settings_dialog.py
------------------
Ayarlar penceresi: Dil, Klavye kisayollari, Hakkinda.
Soldaki listeden bolum secilir. (Tema secimi yok: program hep koyu tema.)
"""
import re
import sys
import unicodedata
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem, QComboBox,
    QStackedWidget, QWidget, QLabel, QRadioButton, QButtonGroup, QScrollArea, QPushButton,
    QLineEdit, QFrame, QSizePolicy
)
from PySide6.QtGui import QPixmap, QShortcut, QKeySequence, QPainter, QColor, QPen, QFont, QFontMetrics
from PySide6.QtCore import Qt, QSize, QRect, QRectF, QEvent
from i18n import _t

SITE_URL = "https://revorapdf.com"
SOURCE_URL = "https://github.com/revorapdf/revora"     # AGPL: kaynak kodun adresi
CONTACT_MAIL = "revorapdf@gmail.com"

THEMES = (("light", _t("Açık")), ("dark", _t("Koyu")), ("system", _t("Sistemle aynı (Windows ayarını izler)")))

def keys(*alts):
    """Bir satirin tuslari. Her secenek AYNI isin bir yolu: "Ctrl+Shift+Z" ya da parca demeti
    ("Ctrl", _t("Tekerlek")). Parcalar ayri tutulur: ekranda tus tus cizilir, aramada bulunur,
    macOS surumunde adlar tek yerden cevrilebilir."""
    return tuple(tuple(a.split("+")) if isinstance(a, str) else tuple(a) for a in alts)


def shortcut_groups():
    """Klavye kisayollari sayfasinin icerigi: (baslik, ((tuslar, eylem), ...)) gruplari.
    Kurallar: SATIR BASINA TEK EYLEM (ayni isin ikinci tusu ayni satirda "/" ile), kisa gruplar,
    fare hareketleri ayri gruplarda. Buradaki tuslar koddaki gercek kisayollarla kabul testinde
    karsilastirilir (main._build_shortcuts, markup_ui.KEY_TOOLS)."""
    wheel, drag, middle, arrows = _t("Tekerlek"), _t("Sürükle"), _t("Orta tuş"), _t("Oklar")
    click, dbl, right = _t("Tıkla"), _t("Çift tık"), _t("Sağ tık")
    return (
        (_t("Dosya"), (
            (keys("Ctrl+O"), _t("PDF aç")),
            (keys("Ctrl+S"), _t("Kaydet")),
            (keys("Ctrl+Shift+S"), _t("Farklı kaydet")),
            (keys("Ctrl+P"), _t("Yazdır")),
            (keys("Ctrl+,"), _t("Ayarlar")),
        )),
        (_t("Sekmeler"), (
            (keys("Ctrl+Tab"), _t("Sonraki sekme")),
            (keys("Ctrl+Shift+Tab"), _t("Önceki sekme")),
            (keys("Ctrl+W", "Ctrl+F4"), _t("Sekmeyi kapat")),
        )),
        (_t("Gezinme ve görünüm"), (
            (keys("PgUp"), _t("Önceki sayfa")),
            (keys("PgDn"), _t("Sonraki sayfa")),
            (keys("Ctrl+G"), _t("Sayfaya git (numara yaz, Enter)")),
            (keys("Ctrl+0"), _t("Sayfa genişliğine sığdır")),
            (keys("Ctrl+9"), _t("Tüm sayfayı sığdır")),
        )),
        (_t("Arama"), (
            (keys("Ctrl+F"), _t("Bul")),
            (keys("Ctrl+H"), _t("Bul ve değiştir")),
            (keys("F3", "Enter"), _t("Sonraki sonuç")),
            (keys("Shift+F3", "Shift+Enter"), _t("Önceki sonuç")),
        )),
        (_t("Düzenleme"), (
            (keys("Ctrl+Z"), _t("Geri al")),
            (keys("Ctrl+Y", "Ctrl+Shift+Z"), _t("Yinele")),
            (keys("Ctrl+D"), _t("Çoğalt")),
            (keys("Delete"), _t("Seçimi sil")),
            (keys((arrows,)), _t("Seçimi ince kaydır")),
            (keys(("Shift", arrows)), _t("Seçimi büyük adımla kaydır (5 kat)")),
        )),
        (_t("Düzenle: araçlar"), (
            (keys("V"), _t("Seç")),
            (keys("T"), _t("Yeni metin")),
            (keys("L"), _t("Çizgi")),
            (keys("K"), _t("Kutu")),
            (keys("D"), _t("Daire")),
            (keys("Ctrl+A"), _t("Sayfadaki tüm yazı ve şekilleri seç")),
        )),
        (_t("Düzenle: yazı"), (
            (keys("F2", "Enter"), _t("Yazıyı düzenle (tüm yazı seçili)")),
            (keys("Esc", "Ctrl+Enter"), _t("Düzenlemeyi bitir")),
            (keys("Ctrl+C"), _t("Yazıyı kopyala")),
            (keys("Ctrl+V"), _t("Yazıyı yapıştır (aynı görünümle)")),
        )),
        (_t("İşaretle: araçlar"), (
            (keys("V"), _t("Seç")),
            (keys("O"), _t("Ok")),
            (keys("L"), _t("Çizgi")),
            (keys("K"), _t("Kutu")),
            (keys("D"), _t("Daire")),
            (keys("N"), _t("Not")),
            (keys("P"), _t("Kalem")),
            (keys("H"), _t("Fosforlu kalem")),
            (keys("1"), _t("Numara")),
            (keys("E"), _t("Silgi")),
            (keys("M"), _t("Büyüteç")),
            (keys("B"), _t("Karart")),
            (keys("S"), _t("İmza ekle")),
            (keys("G"), _t("Görüntü ekle")),
        )),
        (_t("İşaretle: seçim ve not"), (
            (keys("F2", "Enter"), _t("Not yazısını düzenle")),
            (keys("Esc"), _t("Seçimi bırak · ikinci kez: Seç aracı")),
        )),
        (_t("Taşırken basılı tut"), (
            (keys("Shift"), _t("Yalnız yatay ya da dikey taşı")),
            (keys("Alt"), _t("Hizaya oturtmayı o an için aç / kapat")),
        )),
        (_t("Çizerken ve boyutlandırırken basılı tut"), (
            (keys("Shift"), _t("Ok/çizgi/kalem 45° adım · kare / tam daire · oranı koru")),
            (keys("Shift"), _t("Resim, görüntü ve imza: oranı bozarak boyutlandır")),
            (keys("Alt"), _t("Kutu, daire, karartma ve resim: merkezden çiz ve ölçekle")),
            (keys("Alt"), _t("Ok ve çizgi ucu: açı sabit, sadece uzunluk")),
        )),
        (_t("Fare: seçim ve görünüm"), (
            (keys(("Ctrl", wheel)), _t("Yakınlaştır / uzaklaştır")),
            (keys(("Ctrl", drag), (middle,)), _t("Sayfayı kaydır")),
            (keys((click,)), _t("Yazıyı, şekli ya da resmi seç")),
            (keys(("Shift", click)), _t("Seçime ekle / çıkar (yazı, şekil, resim birlikte)")),
            (keys((_t("Boşta sürükle"),)),
             _t("Alan seç: soldan sağa = tamamı içinde olanlar, sağdan sola = değenler")),
            (keys((drag,)), _t("Seçileni taşı")),
            (keys((dbl,)), _t("Yazıyı düzenle (imleç tıklanan harfte)")),
        )),
        (_t("Fare: çizim ve menüler"), (
            (keys(("Ctrl", drag)), _t("Nesnenin üstünden de yeni çizim başlat")),
            (keys((drag,)),
             _t("Fosforlu kalem: yazının üstünden başlarsan kelimelere oturur, boşta serbest çizer")),
            (keys((_t("Orta tutamaç"),)), _t("Çizgiyi / oku bük · çift tık: düzleştir")),
            (keys((dbl,)), _t("Not yazısını düzenle")),
            (keys((right,)), _t("Resmi kaydet · Resmi değiştir · Sil")),
            (keys((right,)), _t("Çoğalt, öne getir / arkaya gönder, düzleştir")),
        )),
    )


def _fold(text):
    """Arama icin sadelestirme: buyuk / kucuk harf ve aksan farki gozetilmez ("cizgi" = "Çizgi")."""
    text = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in text if not unicodedata.combining(c)).replace("ı", "i")


def _theme(key, default):
    """Gecerli gorunumun rengi (main.DARK); ana pencere yuklu degilse varsayilan."""
    m = sys.modules.get("main") or sys.modules.get("__main__")
    try:
        return m.DARK[key]
    except Exception:
        return default


class ShortcutRow(QWidget):
    """Bir kisayol satiri: solda eylem (uzunsa alt satira gecer), sagda tuslar tus tus
    [Ctrl] + [Y]  /  [Ctrl] + [Shift] + [Z]  (Gorunum sayfasiyla ayni duzen: ad solda, deger sagda).
    Satir TEK parcadir, yazi ve tuslar burada cizilir. Her tus ayri bir QLabel iken sayfa ~400
    parcaydi: acilmasi 280 ms suruyor, gorunum her degistiginde 250 ms ekliyordu."""
    PAD = 4              # satirin ust / alt boslugu
    GAP = 24             # yazi ile tuslar arasi
    CHIP_H = 22          # tusun yuksekligi
    CHIP_PAD = 8         # tus yazisinin iki yanindaki bosluk (kenarlik dahil)
    CHIP_MIN = 26        # tek harfli tuslar ayni genislikte
    SPACE = 5            # tus ile "+" arasi
    ALT = 8              # "/" ile iki yanindaki tuslar arasi
    _WRAP = Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignTop

    def __init__(self, alts, text, group):
        super().__init__()
        self.alts, self.text = alts, text
        self.keys_text = "  /  ".join(" + ".join(c) for c in alts)
        self.setAccessibleName(text)
        self.setAccessibleDescription(self.keys_text)
        sp = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        sp.setHeightForWidth(True)
        self.setSizePolicy(sp)
        self.hay = " ".join([_fold(text), _fold(group)] + [_fold(" ".join(c)) for c in alts])
        self.combos = ["+" + _fold("+".join(c)) + "+" for c in alts]
        self._items = None       # [(tur, yazi, genislik)]: tur = "key" | "sep"
        self._heights = {}       # yazi genisligi -> yazi yuksekligi (yerlesim ayni soruyu yuzlerce kez sorar)

    def matches(self, terms):
        """Butun terimler tutmali. "+" iceren terim TUS olarak aranir ve tusun tamamiyla eslesir
        ("ctrl+z", "Ctrl + Ziehen"i getirmez); digerleri eylem / grup / tus adinin icinde aranir."""
        for t in terms:
            if "+" in t:
                key = "+" + t.strip("+") + "+"
                if not any(key in c for c in self.combos):
                    return False
            elif t not in self.hay:
                return False
        return True

    # ------------------------------------------------------------ olcu
    def _chip_font(self):
        f = QFont(self.font())
        f.setPointSizeF(9)
        return f

    def _layout(self):
        """Tus takiminin parcalari ve toplam genisligi (yazi tipi degisince yeniden hesaplanir)."""
        if self._items is None:
            fm = QFontMetrics(self._chip_font())
            items = []
            for i, combo in enumerate(self.alts):
                if i:
                    items.append(("sep", "/", fm.horizontalAdvance("/") + 2 * self.ALT))
                for j, tok in enumerate(combo):
                    if j:
                        items.append(("sep", "+", fm.horizontalAdvance("+") + 2 * self.SPACE))
                    items.append(("key", tok, max(self.CHIP_MIN, fm.horizontalAdvance(tok) + 2 * self.CHIP_PAD)))
            self._items = items
            self._caps_w = sum(w for _k, _t, w in items)
        return self._items, self._caps_w

    def caps_width(self):
        return self._layout()[1]

    def text_width(self, width=None):
        return max(40, (self.width() if width is None else width) - self.caps_width() - self.GAP)

    def _text_height(self, width):
        tw = self.text_width(width)
        h = self._heights.get(tw)
        if h is None:
            h = QFontMetrics(self.font()).boundingRect(QRect(0, 0, tw, 100000), self._WRAP, self.text).height()
            self._heights[tw] = h
        return h

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return max(self._text_height(width), self.CHIP_H) + 2 * self.PAD

    def sizeHint(self):
        return QSize(self.caps_width() + self.GAP + 160, self.CHIP_H + 2 * self.PAD)

    def minimumSizeHint(self):
        return QSize(self.caps_width() + self.GAP + 120, self.CHIP_H + 2 * self.PAD)

    def changeEvent(self, ev):
        if ev.type() == QEvent.FontChange:           # (gorunum degisimi yazi tipini degistirmez: olcu ayni kalir)
            self._items = None
            self._heights.clear()
            self.updateGeometry()
        super().changeEvent(ev)

    # ------------------------------------------------------------ cizim
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        items, caps_w = self._layout()
        p.setFont(self.font())
        p.setPen(QColor(_theme("text2", "#b4b4b4")))
        p.drawText(QRect(0, 0, self.text_width(), self.height()),
                   Qt.TextWordWrap | Qt.AlignLeft | Qt.AlignVCenter, self.text)
        p.setFont(self._chip_font())
        x = self.width() - caps_w
        y = (self.height() - self.CHIP_H) / 2.0
        fill, line = QColor(_theme("surface2", "#262626")), QColor(_theme("border_input", "#3a3a3a"))
        ink, soft = QColor(_theme("text", "#ededed")), QColor(_theme("muted", "#7a7a7a"))
        for kind, tok, w in items:
            box = QRectF(x, y, w, self.CHIP_H)
            if kind == "key":
                p.setPen(QPen(line, 1))
                p.setBrush(fill)
                p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 5, 5)
                p.setPen(ink)
            else:
                p.setPen(soft)
            p.drawText(box, Qt.AlignCenter, tok)
            x += w


class _SearchEdit(QLineEdit):
    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.text():     # (once aramayi temizle; bos ise pencere kapanir)
            self.clear()
            return
        super().keyPressEvent(ev)


class ShortcutsPage(QWidget):
    """Klavye kisayollari: ustte arama, altinda kisa gruplar. Yalniz DIKEY kayar; uzun aciklama
    alt satira gecer. Arama eylem adinda, grup adinda ve tuslarda arar ("ctrl+z", "cizgi")."""
    GUTTER = 14          # tuslar ile kaydirma cubugu arasi

    def __init__(self, groups, icon_fn=None):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(12)
        self.search = _SearchEdit()
        self.search.setObjectName("keysSearch")
        self.search.setPlaceholderText(_t("Kısayol ara"))
        self.search.setAccessibleName(_t("Kısayol ara"))
        self.search.setClearButtonEnabled(True)
        if icon_fn is not None:
            self.search.addAction(icon_fn("mdi6.magnify", "#7a7a7a"), QLineEdit.LeadingPosition)
        self._top = QHBoxLayout()
        self._top.setContentsMargins(0, 0, 0, 0)
        self._top.addWidget(self.search)
        v.addLayout(self._top)

        inner = QWidget()
        inner.setObjectName("keysInner")
        iv = QVBoxLayout(inner)
        iv.setContentsMargins(0, 0, self.GUTTER, 12)
        iv.setSpacing(0)
        self.groups, self.rows = [], []
        for title, items in groups:
            box = QWidget()
            bv = QVBoxLayout(box)
            bv.setContentsMargins(0, 0, 0, 10)
            bv.setSpacing(0)
            line = QFrame()
            line.setObjectName("viewRowLine")
            line.setFixedHeight(1)
            bv.addWidget(line)
            head = QLabel(title)
            head.setObjectName("keysGroup")
            head.setContentsMargins(0, 12, 0, 4)
            bv.addWidget(head)
            rows = [ShortcutRow(alts, text, title) for alts, text in items]
            for r in rows:
                bv.addWidget(r)
            iv.addWidget(box)
            self.groups.append((box, line, head, rows))
            self.rows += rows
        self.empty = QLabel(_t("Eşleşen kısayol yok."))
        self.empty.setObjectName("fieldLabel")
        self.empty.setContentsMargins(0, 12, 0, 0)
        iv.addWidget(self.empty)
        iv.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setObjectName("keysScroll")
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)       # (yalniz dikey kayar)
        self.scroll.viewport().setObjectName("keysView")
        self.scroll.setWidget(inner)
        v.addWidget(self.scroll, 1)
        self._inner = iv
        self.scroll.verticalScrollBar().rangeChanged.connect(lambda *_: self._align())
        self.search.textChanged.connect(self.filter)
        self.filter("")

    def filter(self, text):
        terms = re.sub(r"\s*\+\s*", "+", _fold(text)).split()
        shown, first = 0, True
        for box, line, _head, rows in self.groups:
            n = 0
            for r in rows:
                hit = r.matches(terms)
                r.setVisible(hit)
                n += hit
            box.setVisible(n > 0)
            line.setVisible(n > 0 and not first)       # (ilk gorunen grubun ustunde cizgi yok)
            first = first and n == 0
            shown += n
        self.empty.setVisible(shown == 0)
        self.scroll.verticalScrollBar().setValue(0)
        return shown

    def _align(self):
        """Tuslarin ve arama kutusunun sag kenari AYNI hizada ve SABIT: kaydirma cubugu yalniz
        gerekince gorunur, gorunmedigi zaman (arama listeyi kisaltinca) yeri bos birakilir ->
        satirlar saga sola oynamaz."""
        bar = self.scroll.verticalScrollBar()
        extent = bar.sizeHint().width()
        free = extent if bar.maximum() == 0 else 0
        m = self._inner.contentsMargins()
        if m.right() != self.GUTTER + free:
            self._inner.setContentsMargins(m.left(), m.top(), self.GUTTER + free, m.bottom())
        if self._top.contentsMargins().right() != self.GUTTER + extent:
            self._top.setContentsMargins(0, 0, self.GUTTER + extent, 0)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._align()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._align()


class SettingsDialog(QDialog):
    def __init__(self, parent, theme_mode, on_theme, app_name, version, logo_path,
                 page="appearance", icon_fn=None,
                 language=None, on_language=None, on_restart=None, view=None, on_view=None):
        super().__init__(parent)
        self.icon_fn = icon_fn
        self.view, self.on_view = dict(view or {}), on_view
        self.language, self.on_language, self.on_restart = language, on_language, on_restart
        self.setWindowTitle(_t("Ayarlar"))
        self.resize(820, 540)
        self.on_theme = on_theme

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(214)
        self.nav.setIconSize(QSize(18, 18))
        self.stack = QStackedWidget()
        h.addWidget(self.nav)
        right = QVBoxLayout()
        right.setContentsMargins(24, 20, 24, 16)
        self.title = QLabel()
        self.title.setObjectName("panelTitle")
        right.addWidget(self.title)
        right.addSpacing(8)
        right.addWidget(self.stack, 1)
        # ("Kapat" dugmesi yok: ayarlar aninda uygulanir, pencere ustteki carpi ya da Esc ile kapanir)
        h.addLayout(right, 1)

        self._keys = []
        self._lazy = {}              # satir -> sayfayi kuran islev (agir sayfa: yalniz gorunurken var)
        self.keys_page = None
        if self.on_view is not None:
            self._add("view", _t("Görünüm"), "fa5s.columns", self._view_page())
        self._add("appearance", _t("Dil"), "fa5s.language", self._appearance(theme_mode))
        # ~400 parcalik sayfa: gorunum her degistiginde Qt gorunmeyen parcalari da yeniden
        # bicimlendirir (Gorunum sayfasindaki her tiklamaya ~250 ms ekliyordu). Yalniz acilinca
        # kurulur, baska sayfaya gecince kaldirilir.
        self._add("shortcuts", _t("Klavye kısayolları"), "fa5s.keyboard", QWidget(), lazy=self._make_keys)
        find = QShortcut(QKeySequence("Ctrl+F"), self)            # (Ayarlar'da Ctrl+F: kisayol aramasi)
        find.activated.connect(self._find_shortcut)
        self._add("about", _t("Hakkında"), "fa5s.info-circle", self._about(app_name, version, logo_path))
        self._nav_recolor()
        self.nav.currentRowChanged.connect(self._show)
        self.nav.setCurrentRow(self._keys.index(page) if page in self._keys else 0)

    def _make_keys(self):
        self.keys_page = ShortcutsPage(shortcut_groups(), self.icon_fn)
        return self.keys_page

    def _add(self, key, text, icon, widget, lazy=None):
        if lazy is not None:
            self._lazy[self.stack.count()] = lazy
        it = QListWidgetItem(text)
        self.__dict__.setdefault("_nav_icons", []).append((it, icon))
        it.setSizeHint(QSize(0, 38))
        self.nav.addItem(it)
        self.stack.addWidget(widget)
        self._keys.append(key)

    def _nav_recolor(self):
        """Soldaki basliklarin ikonlari yazilariyla AYNI renkte: secili satirda secim rengi (dolguda
        beyaz / koyu, konturde vurgu rengi) ve dolu bicim; digerlerinde notr. Gorunum ayari
        degisince yeniden cagrilir (ikonlar sabit kaliyor, altin dolguda beyaz ikon + siyah yazi
        oluyordu)."""
        if self.icon_fn is None:
            return
        import markup_bar
        from PySide6.QtGui import QIcon
        for it, name in getattr(self, "_nav_icons", []):
            normal = self.icon_fn(name, markup_bar.ICON_COLOR["dark"]).pixmap(QSize(36, 36))
            sel = markup_bar.icon(name, True).pixmap(QSize(36, 36), QIcon.Normal, QIcon.On)
            ico = QIcon()
            ico.addPixmap(normal, QIcon.Normal)
            ico.addPixmap(normal, QIcon.Active)
            ico.addPixmap(sel if not sel.isNull() else normal, QIcon.Selected)
            it.setIcon(ico)

    def _view_set(self, key, value):
        self.on_view(key, value)
        self._nav_recolor()

    def _swap(self, row, widget):
        old = self.stack.widget(row)
        self.stack.removeWidget(old)
        old.deleteLater()
        self.stack.insertWidget(row, widget)

    def _show(self, row):
        for r, make in self._lazy.items():
            if r == row and self.stack.widget(r).layout() is None:          # (bos yer tutucu: kur)
                self._swap(r, make())
            elif r != row and self.stack.widget(r).layout() is not None:    # (gorunmuyor: kaldir)
                self._swap(r, QWidget())
                self.keys_page = None
        self.stack.setCurrentIndex(row)
        self.title.setText(self.nav.item(row).text())

    def _find_shortcut(self):
        self.nav.setCurrentRow(self._keys.index("shortcuts"))
        self.keys_page.search.setFocus(Qt.ShortcutFocusReason)
        self.keys_page.search.selectAll()

    # ---------------------------------------------------------------- bolumler
    def _view_page(self):
        """Gorunum: her satir solda ad + aciklama, sagda denetim."""
        from PySide6.QtWidgets import QButtonGroup, QCheckBox, QFrame
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 6, 0, 0)
        v.setSpacing(0)

        def row(title, sub, control, last=False):
            h = QHBoxLayout()
            h.setContentsMargins(0, 12, 0, 12)
            tv = QVBoxLayout()
            tv.setSpacing(2)
            t = QLabel(title)
            t.setObjectName("viewRowTitle")
            d = QLabel(sub)
            d.setObjectName("fieldLabel")
            tv.addWidget(t)
            tv.addWidget(d)
            h.addLayout(tv, 1)
            h.addWidget(control, 0, Qt.AlignVCenter)
            v.addLayout(h)
            if not last:
                line = QFrame()
                line.setObjectName("viewRowLine")
                line.setFixedHeight(1)
                v.addWidget(line)

        from PySide6.QtGui import QPainter, QColor, QIcon, QPen
        cur = tuple(self.view.get("theme") or ("", "", ""))

        def chips(items, current, key):
            """Yan yana secenek dugmeleri; solundaki benek o secenegin rengini tanitir."""
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(6)
            grp = QButtonGroup(box)
            for k, text, dot in items:
                b = QPushButton(text)
                b.setObjectName("chip")
                b.setCheckable(True)
                b.setChecked(k == current)
                pm = QPixmap(28, 28)
                pm.fill(Qt.transparent)
                p = QPainter(pm)
                p.setRenderHint(QPainter.Antialiasing)
                p.setPen(QPen(QColor("#6a6a6a"), 2))
                p.setBrush(QColor(dot))
                p.drawEllipse(5, 5, 18, 18)
                p.end()
                pm.setDevicePixelRatio(2.0)
                b.setIcon(QIcon(pm))
                b.setIconSize(QSize(14, 14))
                b.clicked.connect(lambda _=False, v=k: self._view_set(key, v))
                grp.addButton(b)
                bl.addWidget(b)
            return box

        if self.view.get("backdrops"):
            row(_t("Zemin"), _t("Arayüzün arka plan tonu"), chips(self.view["backdrops"], cur[0], "backdrop"))
            row(_t("Seçim rengi"), _t("Seçili araç ve düğmelerin rengi"),
                chips(self.view["accents"], cur[1], "accent"))
            sbox = QWidget()
            sl2 = QHBoxLayout(sbox)
            sl2.setContentsMargins(0, 0, 0, 0)
            sl2.setSpacing(0)
            sgrp = QButtonGroup(sbox)
            styles = self.view["styles"]
            for i, (k, text) in enumerate(styles):
                b = QPushButton(text)
                b.setObjectName("segL" if i == 0 else "segR")
                b.setCheckable(True)
                b.setChecked(k == cur[2])
                b.clicked.connect(lambda _=False, v=k: self._view_set("style", v))
                sgrp.addButton(b)
                sl2.addWidget(b)
            row(_t("Seçim biçimi"), _t("Seçili öğenin çevresi mi çizilsin, içi mi dolsun"), sbox)

        seg = QWidget()
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.setSpacing(0)
        grp = QButtonGroup(seg)
        for name, text, key in (("segL", _t("Solda"), "left"), ("segR", _t("Sağda"), "right")):
            b = QPushButton(text)
            b.setObjectName(name)
            b.setCheckable(True)
            b.setChecked(self.view.get("thumbs_side", "right") == key)
            b.clicked.connect(lambda _=False, k=key: self.on_view("thumbs_side", k))
            grp.addButton(b)
            sl.addWidget(b)
        row(_t("Sayfalar paneli"), _t("Sayfa küçük resimlerinin duracağı taraf"), seg)
        dots = QCheckBox()
        dots.setChecked(bool(self.view.get("dots", True)))
        dots.toggled.connect(lambda on: self.on_view("dots", on))
        row(_t("Zemin noktaları"), _t("Sayfanın arkasındaki soluk nokta dokusu"), dots, last=True)
        v.addStretch()
        return w

    def _appearance(self, mode):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        # Tema secimi kaldirildi (2026-10-02, sadece koyu tema); geri gelirse THEMES'ten
        # QRadioButton'lar burada kurulup self.on_theme(k) cagrilir.
        if self.on_language is not None:
            import i18n
            self.cmb_lang = QComboBox()
            self.cmb_lang.setMaximumWidth(260)
            for code, name in i18n.available():
                self.cmb_lang.addItem(name, code)
            self.cmb_lang.setCurrentIndex(max(self.cmb_lang.findData(self.language or i18n.language()), 0))
            v.addWidget(self.cmb_lang)
            self.lang_note = QWidget()
            nl = QHBoxLayout(self.lang_note)
            nl.setContentsMargins(0, 2, 0, 0)
            note = QLabel(_t("Dil değişikliği program yeniden başlatılınca geçerli olur."))
            note.setObjectName("fieldLabel")
            nl.addWidget(note)
            b = QPushButton(_t("Şimdi yeniden başlat"))
            b.clicked.connect(lambda: self.on_restart and self.on_restart())
            nl.addWidget(b)
            nl.addStretch()
            v.addWidget(self.lang_note)
            self.lang_note.setVisible((self.language or i18n.language()) != i18n.language())
            self.cmb_lang.currentIndexChanged.connect(self._lang_changed)
        v.addStretch()
        return w

    def _lang_changed(self, _i):
        import i18n
        code = self.cmb_lang.currentData()
        self.on_language(code)
        self.lang_note.setVisible(code != i18n.language())

    def _about(self, app_name, version, logo_path):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        top = QHBoxLayout()
        logo = QLabel()
        pm = QPixmap(logo_path)
        if not pm.isNull():
            logo.setPixmap(pm.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(logo)
        tv = QVBoxLayout()
        name = QLabel(app_name)
        name.setStyleSheet("font-size: 18pt; font-weight: 600;")
        tv.addWidget(name)
        tv.addWidget(QLabel(_t("Sürüm {v}", v=version)))
        top.addLayout(tv)
        top.addStretch()
        v.addLayout(top)
        v.addSpacing(10)
        desc = QLabel(_t("PDF'teki yazıları orijinal yazı tipi, boyut ve renkleriyle düzenleyin; "
                      "tablo çizgilerini fareyle yönetin; işaretleme, sayfa, filigran ve form "
                      "işlemlerini tek programda yapın."))
        desc.setWordWrap(True)
        v.addWidget(desc)
        v.addSpacing(10)
        lic = QLabel(_t("© 2026 Revora PDF. Revora özgür yazılımdır: GNU AGPL-3.0 lisansıyla "
                        "dağıtılır ve hiçbir garanti verilmez. Kaynak kodu herkese açıktır."))
        lic.setWordWrap(True)
        v.addWidget(lic)
        links = QLabel(f'<a href="{SITE_URL}">revorapdf.com</a> &nbsp;·&nbsp; '
                       f'<a href="{SOURCE_URL}">{_t("Kaynak kodu (GitHub)")}</a> &nbsp;·&nbsp; '
                       f'<a href="mailto:{CONTACT_MAIL}">{CONTACT_MAIL}</a>')
        links.setOpenExternalLinks(True)
        links.setTextInteractionFlags(Qt.TextBrowserInteraction)
        v.addWidget(links)
        v.addSpacing(12)
        lab = QLabel(_t("Kullanılan açık kaynak bileşenler"))
        lab.setObjectName("settingsSection")
        v.addWidget(lab)
        comp = QLabel(_t("PyMuPDF / MuPDF — AGPL-3.0\n"
                      "Qt for Python (PySide6) — LGPL-3.0\n"
                      "Python — PSF lisansı\n"
                      "QtAwesome — MIT; ikonlar: Font Awesome (OFL 1.1), Material Design Icons (Apache 2.0), Phosphor (MIT)"))
        comp.setObjectName("fieldLabel")
        comp.setWordWrap(True)
        v.addWidget(comp)
        # lisans metinleri programin icinde (paketle gelen licenses/ klasoru; bkz. dialogs.LicensesDialog)
        lic_link = QLabel(f'<a href="#">{_t("Üçüncü taraf lisansları")}</a>')
        lic_link.setTextInteractionFlags(Qt.TextBrowserInteraction)
        lic_link.linkActivated.connect(lambda _h: self._show_licenses())
        v.addWidget(lic_link)
        v.addStretch()
        return w

    def _show_licenses(self):
        import os
        import title_bar
        from dialogs import LicensesDialog
        base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        title_bar.run_modal(LicensesDialog(self, os.path.join(base, "licenses")))
