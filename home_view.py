"""
home_view.py
------------
Acilis ekrani: PDF acik degilken tuvalin yerinde gorunur.
  - Hizli islemler: PDF ac, Resimlerden PDF, Birlestir, Ayir (var olan ozellikler, gorunur olsun)
  - Son dosyalar: ilk sayfanin kucuk resmi + ad; tek tikla acilir (kaldigi sayfadan)
Sol kenardaki sayfa listesi duzenine dokunmaz (kullanici: "Home/Recent/Tools kenar menusu
istemiyoruz"). Son dosyalar yalnizca bu bilgisayarda (QSettings) tutulur.
"""
import os

from PySide6.QtCore import Qt, Signal, QSize, QTimer, QRectF
from PySide6.QtGui import QColor, QPainter, QPixmap, QImage, QPainterPath, QFontMetrics, QCursor
from PySide6.QtWidgets import (QWidget, QFrame, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QScrollArea, QMenu, QSizePolicy, QToolButton)

import fitz
from i18n import _t

MAX_SHOWN = 8
THUMB_H = 150

QSS = """
#homeRoot, #homeInner { background: transparent; }
#homeTitle { font-size: 21pt; font-weight: 500; color: #f2f4f8; }
#homeSub { font-size: 10.5pt; color: #8f959d; }
#homeSection { font-size: 8.5pt; font-weight: 600; color: #6f7680; letter-spacing: 1.5px; }
#homeLink { color: #9aa0a6; border: none; background: transparent; font-size: 9pt; padding: 2px 4px; }
#homeLink:hover { color: #e6e8eb; }
#homeGear { border: none; border-radius: 10px; background: transparent; padding: 8px; }
#homeGear:hover { background: #24262b; }
/* duz tasarim: kenarlik yok, tek ton yuzey; uzerine gelince bir ton acilir */
#homeCard, #homeRecent { background: #1d1e22; border: 1px solid #1d1e22; border-radius: 16px; }
#homeCard:hover, #homeRecent:hover { background: #26282d; border-color: #26282d; }
#homeCard:focus, #homeRecent:focus { border-color: #4b6ea8; }
#homeCardTitle { font-size: 11pt; font-weight: 600; color: #eef0f4; background: transparent; }
#homeCardSub { font-size: 9pt; color: #8f959d; background: transparent; }
#homeIcon { border-radius: 12px; }
#homeKey { color: #8f959d; background: transparent; border: 1px solid #3a3d44;
           border-radius: 6px; padding: 2px 7px; font-size: 8.5pt; }
#homeThumb { background: #17181b; border-top-left-radius: 15px; border-top-right-radius: 15px; }
#homeRecentName { font-size: 10pt; font-weight: 600; color: #e6e8eb; background: transparent; }
#homeRecentSub { font-size: 8.5pt; color: #7d848f; background: transparent; }
#homeEmpty { border: 1px dashed #34373e; border-radius: 16px; background: transparent; }
#homeEmptyText { color: #7d848f; font-size: 10pt; background: transparent; }
#homeTip { color: #5f666f; font-size: 9pt; }
"""


class _Card(QFrame):
    """Tiklanabilir kart (fare + klavye: Enter / Bosluk)."""
    clicked = Signal()

    def __init__(self, name):
        super().__init__()
        self.setObjectName(name)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self.setFocusPolicy(Qt.TabFocus)
        self.setAttribute(Qt.WA_Hover, True)

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
        else:
            super().keyPressEvent(ev)


class ActionCard(_Card):
    def __init__(self, icon_fn, icon_name, color, title, sub, primary=False, key=None):
        super().__init__("homeCard")
        self.setProperty("primary", "true" if primary else "false")
        self.setMinimumHeight(122)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(18, 17, 18, 17)
        v.setSpacing(3)
        tile = QLabel()
        tile.setObjectName("homeIcon")
        tile.setFixedSize(42, 42)
        tile.setAlignment(Qt.AlignCenter)
        c = QColor(color)
        # tek vurgu: yalnizca birincil kartin ikon zemini renkli, digerleri notr
        tile.setStyleSheet(f"background: rgba({c.red()},{c.green()},{c.blue()},0.16);" if primary
                           else "background: rgba(255,255,255,0.06);")
        tile.setPixmap(icon_fn(icon_name, color).pixmap(QSize(22, 22)))
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.addWidget(tile)
        top.addStretch()
        if key:                               # klavye kisayolu etiketi (sag ust)
            k = QLabel(key)
            k.setObjectName("homeKey")
            k.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            top.addWidget(k, 0, Qt.AlignTop)
        v.addLayout(top)
        v.addSpacing(9)
        t = QLabel(title)
        t.setObjectName("homeCardTitle")
        s = QLabel(sub)
        s.setObjectName("homeCardSub")
        s.setWordWrap(True)
        v.addWidget(t)
        v.addWidget(s)
        v.addStretch()
        for w in (tile, t, s):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)


class _Elided(QLabel):
    """Sigmayan metni ortadan kisaltan etiket (dosya adinin sonu / uzantisi gorunsun)."""

    def __init__(self, text, mode=Qt.ElideMiddle):
        super().__init__()
        self._full, self._mode = text, mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setToolTip(text)

    def set_full(self, text):
        self._full = text
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        fm = QFontMetrics(self.font())
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(self._full, self._mode, self.width()))

    def sizeHint(self):
        return QSize(60, QFontMetrics(self.font()).height() + 2)

    minimumSizeHint = sizeHint


class _Thumb(QWidget):
    """Kartin ust kismi: ilk sayfanin kucuk resmi (ortali, hafif golgeli)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("homeThumb")
        self.setFixedHeight(THUMB_H)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.pm = None
        self.icon = None

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        r = QRectF(self.rect())
        clip.addRoundedRect(r.adjusted(0, 0, 0, 16), 15, 15)     # sadece ust koseler yuvarlak
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor("#17181b"))
        if self.pm is not None:
            sz = self.pm.deviceIndependentSize()
            x = (self.width() - sz.width()) / 2
            y = 14.0
            p.fillRect(QRectF(x + 1, y + 2, sz.width(), sz.height()), QColor(0, 0, 0, 90))
            p.drawPixmap(int(x), int(y), self.pm)
        elif self.icon is not None:
            pm = self.icon.pixmap(QSize(40, 40))
            p.drawPixmap((self.width() - 40) // 2, (self.height() - 40) // 2, pm)


class RecentCard(_Card):
    remove = Signal(str)
    reveal = Signal(str)

    def __init__(self, path, icon_fn):
        super().__init__("homeRecent")
        self.path = path
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)
        v = QVBoxLayout(self)
        v.setContentsMargins(1, 1, 1, 12)
        v.setSpacing(0)
        self.thumb = _Thumb()
        self.thumb.icon = icon_fn("mdi6.file-pdf-box", "#5b6270")
        v.addWidget(self.thumb)
        v.addSpacing(10)
        box = QVBoxLayout()
        box.setContentsMargins(13, 0, 13, 0)
        box.setSpacing(1)
        self.name = _Elided(os.path.basename(path))
        self.name.setObjectName("homeRecentName")
        self.sub = _Elided(os.path.basename(os.path.dirname(path)) or os.path.dirname(path), Qt.ElideRight)
        self.sub.setObjectName("homeRecentSub")
        box.addWidget(self.name)
        box.addWidget(self.sub)
        v.addLayout(box)
        self.setToolTip(path)
        for w in (self.name, self.sub):
            w.setAttribute(Qt.WA_TransparentForMouseEvents, True)

    def set_info(self, pm, pages, locked=False):
        folder = os.path.basename(os.path.dirname(self.path)) or os.path.dirname(self.path)
        if locked:
            self.sub.set_full(_t("Parola korumalı") + " · " + folder)
        elif pages:
            self.sub.set_full(_t("{n} sayfa", n=pages) + " · " + folder)
        if pm is not None:
            self.thumb.pm = pm
            self.thumb.update()

    def _menu(self, pos):
        m = QMenu(self)
        a_open = m.addAction(_t("Aç"))
        a_dir = m.addAction(_t("Klasörünü göster"))
        m.addSeparator()
        a_rm = m.addAction(_t("Listeden kaldır"))
        a = m.exec(self.mapToGlobal(pos))
        if a is a_open:
            self.clicked.emit()
        elif a is a_dir:
            self.reveal.emit(self.path)
        elif a is a_rm:
            self.remove.emit(self.path)


def render_thumb(path, dpr=1.0, max_w=150, max_h=THUMB_H - 22):
    """(pixmap | None, sayfa sayisi, parola_korumali). Hata olursa (None, 0, False)."""
    try:
        doc = fitz.open(path)
    except Exception:
        return None, 0, False
    try:
        if doc.needs_pass:
            return None, 0, True
        n = len(doc)
        if n == 0:
            return None, 0, False
        page = doc[0]
        r = page.rect
        k = min(max_w / max(r.width, 1), max_h / max(r.height, 1)) * dpr
        pix = page.get_pixmap(matrix=fitz.Matrix(k, k), alpha=False)
        img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
        pm = QPixmap.fromImage(img)
        pm.setDevicePixelRatio(dpr)
        return pm, n, False
    except Exception:
        return None, 0, False
    finally:
        doc.close()


class HomeView(QScrollArea):
    """actions: [(icon, renk, baslik, alt yazi, cagri, birincil, kisayol | None)]
    recent_fn() -> [yol, ...] (en yeni basta); open_fn(yol); remove_fn(yol | None=hepsi)"""

    def __init__(self, icon_fn, logo_path, actions, recent_fn, open_fn, remove_fn, reveal_fn,
                 settings_fn=None):
        super().__init__()
        self.icon_fn, self.recent_fn, self.open_fn = icon_fn, recent_fn, open_fn
        self.remove_fn, self.reveal_fn = remove_fn, reveal_fn
        self.setObjectName("homeRoot")
        self.setFrameShape(QFrame.NoFrame)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.viewport().setAutoFillBackground(False)
        self.setStyleSheet(QSS)
        self._cache = {}                 # yol -> (mtime, pixmap, sayfa, kilitli)
        self._cards = []
        self._queue = []

        inner = QWidget()
        inner.setObjectName("homeInner")
        self.setWidget(inner)
        outer = QHBoxLayout(inner)
        outer.setContentsMargins(28, 0, 28, 0)
        outer.addStretch(1)
        col = QWidget()
        col.setMaximumWidth(940)
        col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        outer.addWidget(col, 100)
        outer.addStretch(1)
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 52, 0, 40)
        v.setSpacing(0)

        head = QHBoxLayout()
        head.setSpacing(14)
        logo = QLabel()
        pm = QPixmap(logo_path)
        if not pm.isNull():
            dpr = self.devicePixelRatioF()
            pm = pm.scaled(int(46 * dpr), int(46 * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            pm.setDevicePixelRatio(dpr)
            logo.setPixmap(pm)
        head.addWidget(logo, 0, Qt.AlignVCenter)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        t = QLabel("Revora PDF")
        t.setObjectName("homeTitle")
        s = QLabel(_t("Bir PDF açın ya da aşağıdan bir işlem seçin."))
        s.setObjectName("homeSub")
        tv.addWidget(t)
        tv.addWidget(s)
        head.addLayout(tv, 1)
        if settings_fn is not None:            # acilista ust serit yok: Ayarlar burada
            gear = QToolButton()
            gear.setObjectName("homeGear")
            gear.setIcon(icon_fn("mdi6.cog-outline", "#9aa0a6"))
            gear.setIconSize(QSize(20, 20))
            gear.setCursor(QCursor(Qt.PointingHandCursor))
            gear.setToolTip(_t("Ayarlar (Ctrl+,)"))
            gear.clicked.connect(lambda: settings_fn())
            head.addWidget(gear, 0, Qt.AlignTop)
        v.addLayout(head)
        v.addSpacing(38)

        v.addWidget(self._section(_t("HIZLI İŞLEMLER")))
        v.addSpacing(12)
        self.act_grid = QGridLayout()
        self.act_grid.setSpacing(14)
        self.act_cards = []
        for icon, color, title, sub, fn, primary, key in actions:
            c = ActionCard(icon_fn, icon, color, title, sub, primary, key)
            c.clicked.connect(fn)
            self.act_cards.append(c)
        v.addLayout(self.act_grid)
        v.addSpacing(38)

        rh = QHBoxLayout()
        rh.addWidget(self._section(_t("SON DOSYALAR")))
        rh.addStretch()
        self.btn_clear = QToolButton()
        self.btn_clear.setObjectName("homeLink")
        self.btn_clear.setText(_t("Listeyi temizle"))
        self.btn_clear.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_clear.clicked.connect(lambda: (self.remove_fn(None), self.refresh()))
        rh.addWidget(self.btn_clear)
        v.addLayout(rh)
        v.addSpacing(12)
        self.rec_grid = QGridLayout()
        self.rec_grid.setSpacing(14)
        v.addLayout(self.rec_grid)

        self.empty = QFrame()
        self.empty.setObjectName("homeEmpty")
        self.empty.setMinimumHeight(132)
        el = QVBoxLayout(self.empty)
        el.setAlignment(Qt.AlignCenter)
        ei = QLabel()
        ei.setPixmap(icon_fn("mdi6.tray-arrow-down", "#5b6270").pixmap(QSize(30, 30)))
        ei.setAlignment(Qt.AlignCenter)
        et = QLabel(_t("Açtığınız dosyalar burada görünecek.\n"
                       "Bir PDF ya da resmi pencereye sürükleyip bırakabilirsiniz."))
        et.setObjectName("homeEmptyText")
        et.setAlignment(Qt.AlignCenter)
        el.addWidget(ei)
        el.addSpacing(6)
        el.addWidget(et)
        v.addWidget(self.empty)

        v.addSpacing(22)
        self.tip = QLabel(_t("İpucu: PDF ve resim dosyalarını pencereye sürükleyip bırakarak da açabilirsiniz."))
        self.tip.setObjectName("homeTip")
        v.addWidget(self.tip)
        v.addStretch(1)

        self._cols = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._load_next)
        self.refresh()

    @staticmethod
    def _section(text):
        l = QLabel(text)
        l.setObjectName("homeSection")
        return l

    # ---------------------------------------------------------------- icerik
    def refresh(self):
        """Son dosyalar listesini yeniden kur (ekran her gosterildiginde)."""
        for c in self._cards:
            self.rec_grid.removeWidget(c)
            c.setParent(None)
            c.deleteLater()
        self._cards = []
        paths = [p for p in self.recent_fn() if os.path.isfile(p)][:MAX_SHOWN]
        for p in paths:
            c = RecentCard(p, self.icon_fn)
            c.clicked.connect(lambda p=p: self.open_fn(p))
            c.remove.connect(lambda p: (self.remove_fn(p), self.refresh()))
            c.reveal.connect(self.reveal_fn)
            self._cards.append(c)
        has = bool(self._cards)
        self.empty.setVisible(not has)
        self.btn_clear.setVisible(has)
        self.tip.setVisible(has)             # bos durumda ayni ipucu kutunun icinde yaziyor
        self._cols = 0
        self._reflow()
        self._queue = list(self._cards)
        self._timer.start(0)

    def _load_next(self):
        """Kucuk resimler tek tek, arayuz donmadan (her biri ayri olay dongusu turunda)."""
        while self._queue:
            c = self._queue.pop(0)
            try:
                mt = os.path.getmtime(c.path)
            except OSError:
                continue
            hit = self._cache.get(c.path)
            if hit is None or hit[0] != mt:
                pm, n, locked = render_thumb(c.path, self.devicePixelRatioF())
                hit = self._cache[c.path] = (mt, pm, n, locked)
                c.set_info(hit[1], hit[2], hit[3])
                self._timer.start(0)         # bir tane cizdik: sira digerinde
                return
            c.set_info(hit[1], hit[2], hit[3])

    # ---------------------------------------------------------------- yerlesim
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._reflow()

    def showEvent(self, ev):
        super().showEvent(ev)
        self._reflow()

    def _reflow(self):
        w = self.viewport().width()
        cols = 4 if w >= 860 else (3 if w >= 660 else 2)
        if cols == self._cols:
            return
        self._cols = cols
        acols = 4 if cols >= 3 else 2
        for grid, cards, n in ((self.act_grid, self.act_cards, acols), (self.rec_grid, self._cards, cols)):
            for c in cards:
                grid.removeWidget(c)
            for k in range(8):
                grid.setColumnStretch(k, 0)
            for i, c in enumerate(cards):
                grid.addWidget(c, i // n, i % n)
            for k in range(n):
                grid.setColumnStretch(k, 1)
