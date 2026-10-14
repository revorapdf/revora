"""
find_bar.py
-----------
Bul / Degistir: tuvalin ustunde YUZEN, tasinabilir panel (FindBar) ve ana pencereye eklenen
davranis (FindMixin). Arama motoru: pdf_search.

Duzen (kullanicinin gorsel referansi, 2026-10-14 - iki kivrimli sekme, belge sekmeleri gibi):
    ⠿ |   Bul   /  Degistir   ‾|  ×        <- ust serit: secili sekme govdeyle kesintisiz birlesir,
                                            secili olmayan koyu seritte kalir; tutamak ve kapat alanlari esit
    Bul       [....................]   ↑  ↓
    Sununla   [....................]    Aa        <- yalniz Degistir sekmesinde (Bul sekmesinde Aa sonuc satirinda)
              3 / 18 · belgede                    <- sonuc, kutularin sol kenarindan baslar
    Kapsam    [ ▯ Sayfa  ][ ▱ Belge  ]            <- esit genislik; ikisi birlikte kutu genisliginde
              [ Degistir ][ Tumunu   ]            <- Degistir Sayfa'nin, Tumunu Belge'nin altinda
Sekme degisince genislik, sol-ust kose, ust serit ve Bul satiri yerinde kalir; panel yalniz asagi uzar.
Tasima: tutamak ve seritteki bos yerlerden (sekmeler / kapat / kutular / dugmeler tasimaz); alan =
gorunen belge calisma alani (sol menunun sagi, ust arac cubugunun alti, en uste kadar). Cift tik = ilk yer.
Ctrl+F kapaliyken Bul sekmesini acar (acikken sekmeyi zorlamaz, yalniz arama kutusuna odaklanir); Ctrl+H
Degistir sekmesini acar, Sununla kutusuna odaklanir. Kapsam hem aramaya hem "Tumunu"ye uygulanir:
"Degistir" vurgulanan TEK eslesmeyi, "Tumunu" + Sayfa gorunen sayfadakileri, "Tumunu" + Belge
acik belgenin butun sayfalarindakileri degistirir (diger sekmeler degil).
Sol menudeki Bul kutusu ile ayni aramayi paylasir (metin, kapsam, harf ayrimi, siradaki sonuc).
"""
import time

from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel, QLineEdit,
                               QToolButton, QPushButton, QButtonGroup, QWidget, QProgressDialog, QSizePolicy)
from PySide6.QtGui import QColor, QPainter, QPen, QCursor, QPainterPath, QFontMetrics
from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect, QRectF, QSize, QEvent

from i18n import _t
import markup_bar
import pdf_search

ROW_H = 30
PANEL_W = 380           # panelin en az genisligi (mantiksal px; uzun cevirilerde icerige gore buyur)
HEAD_H = 40             # ust serit (sekmeler) yuksekligi
GRIP_W = 38             # serit uclarinda tutamak / kapat alani (ikisi esit)
OUTER_R = 12.0          # panelin dis kose yaricapi (diger yuzen seritlerle ayni)
PAD = 14                # ic kenar boslugu
RIGHT_W = 64            # sag denetim alani (oklar / Aa) - sabit, ortali
CASE_W = 40
PAIR_GAP = 8            # Sayfa / Belge ve Degistir / Tumunu arasindaki pay (ayni: dugmeler ust uste)
FIELD_MIN = 200
MARGIN = 12              # panelin ilk yeri: tuval alaninin sol / ust kenarindan bosluk (mantiksal px)
SLICE_MS = 12            # arka planda sayfa taramasina her turda ayrilan sure (arayuz donmasin)
HIT_FILL = QColor("#ffe066")         # eslesmeler (carpma kipinde: yazi okunur kalir)
CUR_FILL = QColor("#ffa94d")         # siradaki eslesme
CUR_LINE = QColor("#e8590c")


class _FindEdit(QLineEdit):
    """Arama / degistirme kutusu: Enter sonraki (degistirme kutusunda: vurgulananI degistir),
    Shift+Enter onceki, Esc kapat."""
    enter = Signal(bool)                 # shift basili mi
    escape = Signal()

    def __init__(self):
        super().__init__()
        self.setFixedHeight(ROW_H)
        self.setClearButtonEnabled(False)

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.enter.emit(bool(ev.modifiers() & Qt.ShiftModifier))
        elif ev.key() == Qt.Key_Escape:
            self.escape.emit()
        else:
            super().keyPressEvent(ev)


class _Head(QWidget):
    """Ust serit: solda tasima tutamagi, ortada iki ESIT sekme (Bul / Degistir), sagda kapat. Tutamak
    ve seridin bos yerlerinden surukleyince panel tasinir, cift tik ilk yerine dondurur. Sekmeler ve
    kapat kendi olaylarini alir (surukleme baslatmaz)."""
    dragged = Signal(QPoint)             # panelin yeni sol-ust kosesi (ust parcanin koordinati)
    reset = Signal()

    def __init__(self, panel):
        super().__init__(panel)
        self.panel = panel
        self._grab = None
        self._tab_press = None           # (sekme, basilan genel nokta) - sekmeden tasima icin
        self._tab_drag = False
        self.setCursor(QCursor(Qt.OpenHandCursor))
        self.setToolTip(_t("Sürükleyerek taşıyın; çift tıklayınca ilk yerine döner."))

    def watch_tab(self, tab):
        """Sekmeye basili tutup surukleyince de panel tasinir; kipirdamadan birakmak sekmeyi secer.
        Surukleme baslayinca tiklama yutulur (sekme degismez)."""
        tab.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        # (hizli ikinci basis Windows'ta CIFT TIK olarak gelir: o da basistir - yoksa tasima baslamaz ya da
        #  onceki basisin kalan degerleriyle yanlis mesafe tasir; gercek fareyle olculdu)
        if t in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick) and ev.button() == Qt.LeftButton:
            gp = ev.globalPosition().toPoint()
            self._tab_press = (obj, gp, gp - self.panel.mapToGlobal(QPoint(0, 0)))
            self._tab_drag = False
        elif t == QEvent.MouseMove and self._tab_press and self._tab_press[0] is obj and ev.buttons() & Qt.LeftButton:
            gp = ev.globalPosition().toPoint()
            if not self._tab_drag and (gp - self._tab_press[1]).manhattanLength() >= QApplication.startDragDistance():
                self._tab_drag = True
                obj.setDown(False)
                obj.setCursor(QCursor(Qt.ClosedHandCursor))
            if self._tab_drag:
                self.dragged.emit(self.panel.from_global(gp - self._tab_press[2]))
                return True
        elif t == QEvent.MouseButtonRelease and self._tab_press and self._tab_press[0] is obj:
            dragged = self._tab_drag
            self._tab_press, self._tab_drag = None, False
            if dragged:
                obj.setDown(False)
                obj.setCursor(QCursor(Qt.PointingHandCursor))
                return True
        return False

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._grab = ev.globalPosition().toPoint() - self.panel.mapToGlobal(QPoint(0, 0))
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            ev.accept()
        else:
            super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._grab is not None and ev.buttons() & Qt.LeftButton:
            self.dragged.emit(self.panel.from_global(ev.globalPosition().toPoint() - self._grab))
            ev.accept()
        else:
            super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._grab is not None:
            self._grab = None
            self.setCursor(QCursor(Qt.OpenHandCursor))
            ev.accept()
        else:
            super().mouseReleaseEvent(ev)

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.reset.emit()
            ev.accept()


def _mix(a, b, t):
    """Iki rengin karisimi (t: b'nin payi)."""
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t))


def tab_path(r, active_left, outer_r, top_r=10.0, flare=10.0, d=6.0):
    """Etkin sekmenin bicimi (belge sekmeleriyle ayni dil: title_bar.TabStrip._tab_path). Disa bakan
    kenar DUZ ve panelin dis kosesiyle ayni yaricapta yuvarlak; ice bakan kenar hafif egik iner, ust
    kosesi yuvarlak, altta yumusak bir kavisle alttaki yuzeye akar. r: sekmenin dikdortgeni."""
    L, R, top, b = float(r.left()), float(r.right()), float(r.top()), float(r.bottom())
    n = (d * d + (b - top) ** 2) ** 0.5
    ux, uy = d / n, (top - b) / n                  # egik kenar boyunca birim vektor (yukari)
    p = QPainterPath()
    if active_left:                                # sol duz (panelin kenari), sag egik + kavis
        p.moveTo(L, b)
        p.lineTo(L, top + outer_r)
        p.quadTo(L, top, L + outer_r, top)
        p.lineTo(R - d - top_r, top)
        p.quadTo(R - d, top, R - d + ux * top_r, top - uy * top_r)
        p.lineTo(R - ux * flare, b + uy * flare)
        p.quadTo(R, b, R + flare, b)
    else:                                          # sag duz, sol egik + kavis
        p.moveTo(L - flare, b)
        p.quadTo(L, b, L + ux * flare, b + uy * flare)
        p.lineTo(L + d - ux * top_r, top - uy * top_r)
        p.quadTo(L + d, top, L + d + top_r, top)
        p.lineTo(R - outer_r, top)
        p.quadTo(R, top, R, top + outer_r)
        p.lineTo(R, b)
    p.closeSubpath()
    return p


class FindBar(QFrame):
    """Bul / Degistir paneli. Ust seritte iki sekme; etkin sekme alttaki yuzeyle kesintisiz birlesir
    (paintEvent ciziyor), edilgen sekme daha koyu seritte geride kalir. Icerik izgarasi:
        etiket | kutu (Bul ve Sununla AYNI sol / sag kenar) | sag denetim alani (sabit, ortali)
    Kapsam (Sayfa / Belge) ve islem (Degistir / Tumunu) dugmeleri esit genislikte, ikisi birlikte
    kutu genisligi kadar: Degistir Sayfa'nin, Tumunu Belge'nin altinda. Aa sag denetim alaninda,
    oklarin hemen altinda (Bul: sonuc satirinda, Degistir: Sununla satirinda)."""
    changed = Signal()                   # aranan yazi degisti (yazarken kisa bekleme)
    option_changed = Signal()            # kapsam / harf duyarliligi degisti (beklemeden)
    step = Signal(int)                   # +1 sonraki, -1 onceki
    replace_one = Signal()
    replace_all = Signal()
    closed = Signal()
    moved = Signal(QPoint)               # kullanici tasidi (yeni sol-ust, ust parcanin koordinati)
    reset_pos = Signal()                 # serit bos yerinde / tutamakta cift tik
    grown = Signal()                     # sekme degisti, boyu degisti (yer yeniden denetlensin)

    def __init__(self, parent, dark=True):
        super().__init__(parent)
        # AYRI KUCUK PENCERE (ana pencerenin sahipligi altinda: hep onun ustunde, gorev cubugunda yok,
        # ana pencere kuculunce o da gizlenir). Ana pencerenin icinde kayan bir parca iken her
        # tasimada altindan cikan yer ile panel ayni pencerede yeniden ciziliyordu; Windows ekrani
        # bu guncellemenin ortasinda yenileyince panelin yeni girdigi serit bir kare geriden geliyordu
        # (kullanici 2026-10-15, videoda her karede; programin hazirladigi goruntu hep dogruydu).
        # Ayri pencerede tasima yalniz bir yer degisikligidir: hicbir sey yeniden cizilmez.
        # Yer bilgisi yine ust parcanin (tuval sutunu) koordinatinda tutulur: place() / local_pos().
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)      # (yuvarlak koseler saydam)
        self.setObjectName("findPanel")
        self._dark = dark
        self._colors = {}
        self._icons = []                 # (dugme, ikon adi) - tema degisince yeniden boyanir
        self._replacing = None
        v = QVBoxLayout(self)
        v.setContentsMargins(PAD, HEAD_H + 12, PAD, PAD)
        v.setSpacing(0)

        def icon_btn(name, tip, acc, size=28):
            b = markup_bar.tool_button(name, tip, False, None, dark, size=size)
            b.setObjectName("findIcon")
            b.setFocusPolicy(Qt.NoFocus)
            b.setAccessibleName(acc)
            self._icons.append((b, name))
            return b

        def label(text):
            lb = QLabel(text)
            lb.setObjectName("findLabel")
            return lb

        def button(name, text, tip, checkable=False, icon=None):
            # QPushButton: simge + yazi dugmenin ORTASINDA (QToolButton simgeli yaziyi sola yasliyordu)
            b = QPushButton()
            b.setAutoDefault(False)
            b.setObjectName(name)
            b.setText(text)
            b.setToolTip(tip)
            b.setAccessibleName(text)
            b.setCheckable(checkable)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setFocusPolicy(Qt.TabFocus)
            b.setFixedHeight(ROW_H)
            b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)     # (genislik yalniz esit paydan)
            f = b.font()
            f.setKerning(False)          # (Segoe UI "Tü" kerning cifti: ü'nun noktalari T'nin koluna giriyordu)
            b.setFont(f)
            if icon:
                b.setIconSize(QSize(15, 15))
                self._icons.append((b, icon))
            return b

        # ---- ust serit: tutamak | Bul | Degistir | kapat
        self.head = _Head(self)
        self.grip = QLabel(self.head)
        # (tutamak etiketi fare olayini kabul etmez: olay ALTTAKI sekmeye degil, ebeveyne - seride - gecer,
        #  surukleme / cift tik serit isi olur)
        self.grip.setAlignment(Qt.AlignCenter)
        self.tab_find = QToolButton(self.head)
        self.tab_repl = QToolButton(self.head)
        for t, text in ((self.tab_find, _t("Bul")), (self.tab_repl, _t("Değiştir"))):
            t.setObjectName("findTab")
            t.setText(text)
            t.setCheckable(True)
            t.setAccessibleName(text)
            t.setCursor(QCursor(Qt.PointingHandCursor))
            t.setFocusPolicy(Qt.TabFocus)
        drag_tip = _t("Basılı tutup sürükleyerek paneli taşıyabilirsiniz.")
        self.tab_find.setToolTip(_t("Bul") + " (Ctrl+F)\n" + drag_tip)
        self.tab_repl.setToolTip(_t("Değiştir") + " (Ctrl+H)\n" + drag_tip)
        tabs = QButtonGroup(self)
        tabs.setExclusive(True)
        tabs.addButton(self.tab_find)
        tabs.addButton(self.tab_repl)
        self.btn_more = self.tab_repl                  # (eski ad: magaza betikleri "Degistir"i acar)
        self.btn_close = icon_btn("ph.x", _t("Kapat") + " (Esc)", _t("Kapat"), size=26)
        self.btn_close.setParent(self.head)

        # ---- izgara
        g = QGridLayout()
        g.setContentsMargins(0, 0, 0, 0)
        g.setHorizontalSpacing(10)
        g.setVerticalSpacing(8)
        self.lb_find = label(_t("Bul"))
        self.ed_find = _FindEdit()
        self.ed_find.setAccessibleName(_t("Bul"))
        self.ed_find.setPlaceholderText(_t("Aranacak metin"))
        self.btn_prev = icon_btn("ph.caret-up", _t("Önceki eşleşme") + " (Shift+Enter)", _t("Önceki eşleşme"))
        self.btn_next = icon_btn("ph.caret-down", _t("Sonraki eşleşme") + " (Enter)", _t("Sonraki eşleşme"))
        arrows = QWidget()
        al = QHBoxLayout(arrows)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(4)
        al.addWidget(self.btn_prev)
        al.addWidget(self.btn_next)
        self._arrows = arrows
        g.addWidget(self.lb_find, 0, 0)
        g.addWidget(self.ed_find, 0, 1)
        g.addWidget(arrows, 0, 2, Qt.AlignCenter)

        self.lb_repl = label(_t("Şununla"))
        self.ed_repl = _FindEdit()
        self.ed_repl.setAccessibleName(_t("Şununla değiştir"))
        self.ed_repl.setPlaceholderText(_t("Yeni metin (boş: siler)"))
        g.addWidget(self.lb_repl, 1, 0)
        g.addWidget(self.ed_repl, 1, 1)

        self.btn_case = QToolButton()
        self.btn_case.setObjectName("findCase")
        self.btn_case.setText("Aa")
        self.btn_case.setCheckable(True)
        self.btn_case.setFixedSize(CASE_W, ROW_H - 4)
        self.btn_case.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_case.setFocusPolicy(Qt.TabFocus)
        self.btn_case.setToolTip(_t("Büyük/küçük harfe duyarlı"))
        self.btn_case.setAccessibleName(_t("Büyük/küçük harfe duyarlı"))

        self.status = QLabel()
        self.status.setObjectName("findStatus")
        self.status.setAccessibleName(_t("Arama sonucu"))
        self.status.setMinimumHeight(ROW_H - 4)
        f = self.status.font()
        f.setKerning(False)                            # ("Tüm": dugmelerdeki gibi T-ü cifti)
        self.status.setFont(f)
        g.addWidget(self.status, 2, 1)

        self.lb_scope = label(_t("Kapsam"))
        self.btn_this = button("findScope", _t("Sayfa"), _t("Yalnız görüntülenen sayfada ara ve değiştir"),
                               True, "ph.file")
        self.btn_doc = button("findScope", _t("Belge"), _t("Açık belgenin bütün sayfalarında ara ve değiştir"),
                              True, "ph.files")
        self.btn_doc.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.btn_this)
        grp.addButton(self.btn_doc)
        sc = QHBoxLayout()
        sc.setContentsMargins(0, 0, 0, 0)
        sc.setSpacing(PAIR_GAP)
        sc.addWidget(self.btn_this, 1)
        sc.addWidget(self.btn_doc, 1)
        g.addWidget(self.lb_scope, 3, 0)
        g.addLayout(sc, 3, 1)

        self.btn_one = button("findPrimary", _t("Değiştir"), _t("Vurgulanan eşleşmeyi değiştir"))
        self.btn_all = button("findSecondary", _t("Tümünü"), "")
        self.w_repl = QWidget()                        # islem dugmeleri (Degistir sekmesi)
        ar = QHBoxLayout(self.w_repl)
        ar.setContentsMargins(0, 0, 0, 0)
        ar.setSpacing(PAIR_GAP)                        # (kapsam dugmeleriyle ayni pay: ayni yatay konum)
        ar.addWidget(self.btn_one, 1)
        ar.addWidget(self.btn_all, 1)
        g.addWidget(self.w_repl, 4, 1)
        g.setColumnStretch(1, 1)
        g.setColumnMinimumWidth(2, RIGHT_W)
        self.grid = g
        self.ed_find.setMinimumWidth(FIELD_MIN)
        v.addLayout(g)

        self.ed_find.textChanged.connect(lambda _=None: self.changed.emit())
        self.btn_case.toggled.connect(lambda _=None: self.option_changed.emit())
        self.btn_doc.toggled.connect(self._scope_changed)
        self.ed_find.enter.connect(lambda shift: self.step.emit(-1 if shift else 1))
        self.ed_repl.enter.connect(lambda shift: self.step.emit(-1) if shift else self.replace_one.emit())
        self.ed_find.escape.connect(self.closed.emit)
        self.ed_repl.escape.connect(self.closed.emit)
        self.btn_prev.clicked.connect(lambda: self.step.emit(-1))
        self.btn_next.clicked.connect(lambda: self.step.emit(1))
        self.btn_close.clicked.connect(self.closed.emit)
        self.tab_find.clicked.connect(lambda: self.set_replace(False))
        self.tab_repl.clicked.connect(lambda: self.set_replace(True))
        self.btn_one.clicked.connect(self.replace_one.emit)
        self.btn_all.clicked.connect(self.replace_all.emit)
        self.head.dragged.connect(self.moved.emit)
        self.head.watch_tab(self.tab_find)
        self.head.watch_tab(self.tab_repl)
        self.head.reset.connect(self.reset_pos.emit)
        self.recolor(dark)
        self.set_replace(False, focus=False)
        self._scope_changed()

    # ---- gorunum
    def _fit_columns(self):
        """Yazi kutulari ve dugmeler panelin TAM ORTASINDA: soldaki etiket sutunu ile sagdaki denetim
        sutunu (oklar / Aa) AYNI genislikte (kullanici 2026-10-15: "hizalama sola yakin, ortalayalim").
        Etiketler blok olarak saga kayar (kendi aralarinda sola yasli kalir, kutuya uzakliklari ayni);
        uzun cevirilerde etiket sutunu buyurse sag sutun da ayni olcude buyur. Bul ve Sununla kutulari
        ayni sol kenardan baslar, sekme degisince kaymaz; uzun cevirilerde de kesilmez."""
        w = 0
        labels = (self.lb_find, self.lb_repl, self.lb_scope)
        for lb in labels:
            lb.ensurePolished()
            w = max(w, lb.fontMetrics().horizontalAdvance(lb.text()))
        right = max(RIGHT_W, self._arrows.sizeHint().width(), CASE_W)
        side = max(w + 2, right)
        for lb in labels:
            lb.setContentsMargins(side - (w + 2), 0, 0, 0)
        self.grid.setColumnMinimumWidth(0, side)
        self.grid.setColumnMinimumWidth(2, side)
        f = self.tab_find.font()
        f.setPointSizeF(9.5)
        tw = max(QFontMetrics(f).horizontalAdvance(t.text()) for t in (self.tab_find, self.tab_repl))
        self.setMinimumWidth(max(PANEL_W, 2 * (GRIP_W + tw + 40)))

    def showEvent(self, ev):
        self._fit_columns()
        super().showEvent(ev)

    def resizeEvent(self, ev):
        """Ust serit: iki ESIT sekme (her biri seridin yarisi); uclarda ESIT genislikte tutamak ve kapat."""
        super().resizeEvent(ev)
        W = self.width()
        self.head.setGeometry(0, 0, W, HEAD_H)
        mid = W // 2
        # sekme dugmeleri cizilen sekmenin tamami (yazi gorunen sekmenin ORTASINDA; eskiden tutamak ve
        # kapat alanlari dugmeden dusuluyordu, yazi ice kayik duruyordu); tutamak ve kapat ustte
        self.tab_find.setGeometry(0, 0, mid, HEAD_H)
        self.tab_repl.setGeometry(mid, 0, W - mid, HEAD_H)
        self.grip.setGeometry(0, 0, GRIP_W, HEAD_H)
        cs = self.btn_close.width()
        self.btn_close.move(W - GRIP_W + (GRIP_W - cs) // 2, (HEAD_H - cs) // 2)
        self.grip.raise_()
        self.btn_close.raise_()

    def _icon(self, name, dark):
        """Panelin renk takimindan ikon: secili hali dugmenin yazi rengi (on_icon; ortak ikonda acik
        temada da beyazdi - acik mavi zeminde kayboluyordu), pasif hali temanin soluk rengi (ortak
        ikonda sabit koyu gri - acik temada oklar pasifken etkin gibi gorunuyordu)."""
        c = self._colors
        ph, fill = markup_bar.ph_name(name)
        if not c or ph is None or markup_bar.qta is None:
            return markup_bar.icon(name, dark)
        col = markup_bar.ICON_COLOR["dark" if dark else "light"]
        on = c.get("on_icon", markup_bar.ICON_ON)
        try:
            return markup_bar.qta.icon(ph, color=col, color_disabled=c.get("disabled", "#5a5a5a"),
                                       on=fill or ph, color_on=on, active=ph, color_active=col,
                                       on_active=fill or ph, color_on_active=on)
        except Exception:
            return markup_bar.icon(name, dark)

    def recolor(self, dark, colors=None):
        """Tema degisti: ikonlar ve panel cizim renkleri."""
        self._dark = dark
        if colors:
            self._colors = dict(colors)
        for b, name in self._icons:
            ic_ = self._icon(name, dark)
            if not ic_.isNull():
                b.setIcon(ic_)
        self.grip.setPixmap(markup_bar.icon("ph.dots-six-vertical", dark).pixmap(QSize(14, 14)))
        self.update()

    def paintEvent(self, ev):
        """Panel: dis cerceve (yuvarlak koseler), koyu ust serit, etkin sekme + alttaki yuzey TEK
        parca (kesintisiz). Sinir cizgisi YALNIZ dis kenarda; sekmeyi renk farki ayirir (kullanici,
        2026-10-14: sekmelerin altindaki cizgi kalksin)."""
        c = self._colors
        surface = QColor(c.get("surface", "#2c2c2c"))
        strip = _mix(surface, c.get("bg", "#1b1b1b"), 0.55)
        line = QColor(c.get("border_input", "#3a3a3a"))
        W, H = float(self.width()), float(self.height())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        outer = QPainterPath()
        outer.addRoundedRect(QRectF(0.5, 0.5, W - 1.0, H - 1.0), OUTER_R, OUTER_R)
        p.fillPath(outer, strip)
        mid = W / 2.0
        left = not self.replacing()
        tab = QRectF(0.5, 0.5, mid - 0.5, HEAD_H - 0.5) if left else QRectF(mid, 0.5, W - 1.0 - mid, HEAD_H - 0.5)
        body = QPainterPath()
        body.addRect(QRectF(0.5, HEAD_H, W - 1.0, H - HEAD_H))
        face = body.united(tab_path(tab, left, OUTER_R)).intersected(outer)
        p.fillPath(face, surface)
        p.setPen(QPen(line, 1.0))
        p.drawPath(outer)
        p.end()

    # ---- yer (ust parcanin koordinati; panel ayri pencere oldugu icin ekrana cevrilir)
    def place(self, pt):
        g = self.parentWidget().mapToGlobal(pt)
        if self.pos() != g:
            self.move(g)

    def local_pos(self):
        return self.parentWidget().mapFromGlobal(self.pos())

    def from_global(self, gp):
        return self.parentWidget().mapFromGlobal(gp)

    # ---- durum
    def needle(self):
        return self.ed_find.text()

    def replacement(self):
        return self.ed_repl.text()

    def case(self):
        return self.btn_case.isChecked()

    def all_pages(self):
        return self.btn_doc.isChecked()

    def replacing(self):
        return bool(self._replacing)

    def set_replace(self, on, focus=True):
        """Bul (on=False) / Degistir (on=True) sekmesi. Panel yalniz ASAGI dogru buyur / kucukur:
        genislik, ust-sol kose, ust serit ve Bul satiri yerinde kalir. Yazilanlar, kapsam ve harf
        duyarliligi korunur."""
        on = bool(on)
        (self.tab_repl if on else self.tab_find).setChecked(True)
        if on == self._replacing:
            if on and focus:
                self.ed_repl.setFocus()
            return
        self._replacing = on
        fw = QApplication.focusWidget()
        if not on and (focus or (fw is not None and self.isAncestorOf(fw))):
            # (gizlenen Sununla kutusundaki odak Qt'de siradaki dugmeye - "Sayfa" - kayiyor, odak
            #  cercevesi orada mavi kaliyordu: odak once arama kutusuna)
            self.ed_find.setFocus()
        try:
            self.lb_repl.setVisible(on)
            self.ed_repl.setVisible(on)
            self.w_repl.setVisible(on)
            # Aa oklarin hemen altinda: Bul sekmesinde sonuc satirinda, Degistir'de Sununla satirinda
            self.grid.addWidget(self.btn_case, 1 if on else 2, 2, Qt.AlignCenter)
            self.layout().activate()
            self.resize(max(self.minimumWidth(), self.width()), self.sizeHint().height())
        finally:
            self.setUpdatesEnabled(True)
        self.update()
        if on and focus:
            self.ed_repl.setFocus()
        self.grown.emit()

    def _scope_changed(self, *_):
        self.btn_all.setToolTip(_t("Belgedeki bütün eşleşmeleri değiştir") if self.all_pages()
                                else _t("Bu sayfadaki bütün eşleşmeleri değiştir"))
        self.option_changed.emit()

    def set_state(self, text, total, none=False):
        """Sonuc satiri ("3 / 18 · belgede", "Bu sayfada sonuc yok") ve dugmelerin etkinligi."""
        self.status.setText(text)
        self.status.setProperty("none", bool(none))
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        for b in (self.btn_prev, self.btn_next, self.btn_one, self.btn_all):
            b.setEnabled(total > 0)

    def focus_find(self):
        self.ed_find.setFocus()
        self.ed_find.selectAll()


class FindMixin:
    """MainWindow'a eklenir. Beklenenler: engine, canvas, scroll, thumbs, current_page, goto_page,
    after_edit, status, _finish_edits, _clear_selection, _update_thumb, _update_title, _refresh_panel."""

    def _build_find_bar(self, parent):
        self.find_bar = FindBar(parent, getattr(self, "dark", True))
        self.find_bar.hide()
        self._fx_finder = pdf_search.Finder()
        self._fx_matches = {}            # sayfa -> [Match]
        self._fx_pending = []            # henuz taranmamis sayfalar
        self._fx_cur = None              # siradaki eslesme
        self._fx_query = None            # (aranan, harf ayrimi, tum sayfalar, sayfa)
        self._fx_restart_queued = False
        self._fx_inline = False          # sol menudeki kutudan araniyor (genis cubuk kapali olabilir)
        self._fx_pos = None              # kullanicinin tasidigi yer (bu oturum); None = ilk yer
        self._fx_busy = False            # degistirme suruyor: araya arama / yeniden tarama girmesin
        self._fx_typing = QTimer(self)
        self._fx_typing.setSingleShot(True)
        self._fx_typing.setInterval(120)
        self._fx_typing.timeout.connect(self._find_restart)
        self._fx_worker = QTimer(self)
        self._fx_worker.setInterval(0)
        self._fx_worker.timeout.connect(self._find_work)
        b = self.find_bar
        b.changed.connect(self._fx_typing.start)
        # (kapsam / Aa tiklamasi yazmak degil: 120 ms bekleme yok - kullanici, 2026-10-14: ipucu gec degisiyordu)
        b.option_changed.connect(lambda: self._find_restart())
        b.step.connect(self.find_step)
        b.replace_one.connect(self.find_replace_one)
        b.replace_all.connect(self.find_replace_all)
        b.closed.connect(self.find_close)
        b.ed_find.textEdited.connect(self._find_sync_side)
        b.moved.connect(self._find_moved)
        self._fx_move_timer = QTimer(self)   # (surukleme: panel ekranin yenilenme hizinda tasinir)
        self._fx_move_timer.setSingleShot(True)
        self._fx_move_timer.timeout.connect(self._find_move_now)
        self._fx_moved_at = 0.0
        b.reset_pos.connect(self._find_reset_pos)
        b.grown.connect(self._place_find_bar)

    # ---- ac / kapat / yer
    def find_open(self, replace=False):
        """Ctrl+F (replace=False): kapaliysa KOMPAKT Bul acilir; aciksa (genisletilmis olsa da)
        yalniz arama kutusuna odaklanir - Degistir bolumu kapanmaz. Ctrl+H (replace=True):
        genisletilmis acilir, degistirme kutusuna odaklanir. Sol menude ayni arama yapilmissa
        bastan kurulmaz (siradaki sonuc korunur)."""
        if not self.engine.doc or self.scroll.isHidden():
            return
        b = self.find_bar
        if b.isHidden():
            b.set_replace(bool(replace), focus=False)
        elif replace:
            b.set_replace(True, focus=False)
        b.show()
        self._place_find_bar()
        b.raise_()
        b.activateWindow()                   # (ayri pencere: yazi kutusu klavyeyi alsin)
        if replace:
            b.ed_repl.setFocus()
            b.ed_repl.selectAll()
        else:
            b.focus_find()
        if self._find_same_query():
            self._find_refresh()
        else:
            self._find_restart()

    def _find_same_query(self):
        """Kurulu arama, cubuktaki ayarlarla ve bu belgeyle AYNI mi (yeniden kurmaya gerek yok)."""
        q, b = self._fx_query, self.find_bar
        return bool(q) and q[0] == b.needle() and q[1] == b.case() and q[2] == b.all_pages() \
            and (q[2] or q[3] == self.current_page) and not self._find_stale() and not self._fx_typing.isActive()

    def _find_sync_side(self, text):
        """Genis cubukta yazilan, sol menudeki kutuda da gorunsun."""
        side = getattr(self, "btn_find", None)
        if side is not None and hasattr(side, "set_hint") and side.text() != text:
            side.setText(text)
        self._fx_inline = bool(text.strip())

    def find_close(self, keep_focus=False):
        self.find_bar.hide()
        self._fx_inline = False
        side = getattr(self, "btn_find", None)
        if side is not None and hasattr(side, "set_hint"):
            if not keep_focus:
                side.clear()
            side.set_hint("Ctrl+F")
        if self.find_bar.ed_find.text() and not keep_focus:
            self.find_bar.ed_find.blockSignals(True)
            self.find_bar.ed_find.clear()
            self.find_bar.ed_find.blockSignals(False)
        self._fx_worker.stop()
        self._fx_typing.stop()
        self._fx_matches, self._fx_pending, self._fx_cur, self._fx_query = {}, [], None, None
        self._find_badges_update()
        self.canvas.update()
        if not keep_focus:
            self.canvas.setFocus()

    def find_active(self):
        """Arama acik mi: genis cubuk gorunuyor YA DA sol menudeki kutuda aranan bir sey var."""
        return getattr(self, "find_bar", None) is not None and (
            not self.find_bar.isHidden() or getattr(self, "_fx_inline", False))

    def _find_area(self):
        """Panelin durabilecegi alan (ust parcanin koordinati): GORUNEN belge calisma alani - kaydirma
        alaninin gorunen kismi (kaydirma cubuklari haric). Ust parca (tuval sutunu) zaten sol menunun
        sagi ve ust arac cubugunun alti; ust kenar dogrudan bu alanin ust kenari.
        (HATA, 2026-10-14: ust kenara tuvalin ic ust payi - canvas.pad_top, yuzen seritler icin sayfanin
        USTUNE ayrilan bosluk - bir kez daha ekleniyordu: panel calisma alaninin en ustune tasinamiyor,
        y = 68'de duruyordu. pad_top belgenin icerik payidir, gorunen alanin yasak bolgesi degil.)"""
        vp = self.scroll.viewport()
        return QRect(vp.mapTo(self.find_bar.parentWidget(), QPoint(0, 0)), vp.size())

    def _find_default_pos(self):
        """Ilk yer: tuval alaninin sol-ustu (sol menunun hemen sagi), ust seritlerin altinda."""
        a = self._find_area()
        return QPoint(a.left() + MARGIN, a.top() + MARGIN)

    def _find_clamp(self, pt):
        """Panel alanin icinde kalsin. Normalde ust kenar sabit; sigmiyorsa gerektigi kadar
        yukari / sola alinir (pencere kuculunce, panel genisleyince erisilebilir kalir)."""
        a, b = self._find_area(), self.find_bar
        x = min(pt.x(), a.right() + 1 - b.width())
        y = min(pt.y(), a.bottom() + 1 - b.height())
        return QPoint(max(a.left(), x), max(a.top(), y))

    def _place_find_bar(self):
        b = getattr(self, "find_bar", None)
        if b is None:
            return
        if self.find_active() and (self.engine.doc is None or self.scroll.isHidden()):
            self.find_close()
            return
        if b.isHidden():
            return
        b.resize(max(PANEL_W, b.sizeHint().width()), b.sizeHint().height())
        b.place(self._find_clamp(self._fx_pos if self._fx_pos is not None else self._find_default_pos()))
        b.raise_()

    def _find_moved(self, pt):
        """Baslik suruklendi: yalniz panel kayar (belge cizilmez, arama yeniden calismaz). Kullanicinin
        biraktigi yer bu oturum icin hatirlanir (kapatip acinca ayni yerde).

        Panel ekranin bir yenilenmesinde EN COK BIR KEZ, farenin son konumuna tasinir. Fare saniyede
        yuzlerce konum gonderir; her biri ayri bir ekran guncellemesi olunca Windows ekrani bu
        guncellemelerin ortasinda yeniliyor, panelin yeni girdigi serit bir kare geriden geliyordu
        (kullanici, 2026-10-15: "sol taraf kesiliyor gibi, birakinca duzeliyor"; videoda her karede,
        ekran goruntusunde hic gorunmuyordu). Programin hazirladigi ve pencereye aktardigi goruntu
        her olcumde dogruydu; hareketler seyreklesince sorun kayboldu."""
        self._fx_pos = self._find_clamp(pt)
        if self._fx_move_timer.isActive():
            return                               # (siradaki karede son konum kullanilir)
        gap = self._find_frame_gap()
        wait = gap - (time.monotonic() - self._fx_moved_at)
        if wait <= 0:
            self._find_move_now()
        else:
            self._fx_move_timer.start(max(1, int(wait * 1000 + 0.5)))

    def _find_frame_gap(self):
        """Ekranin iki yenilenmesi arasi (sn): 60 Hz'de 16,7 ms, 144 Hz'de 6,9 ms."""
        scr = self.find_bar.screen()
        hz = scr.refreshRate() if scr is not None else 60.0
        return 1.0 / (hz if 30.0 <= hz <= 360.0 else 60.0)

    def _find_move_now(self):
        self._fx_move_timer.stop()
        self._fx_moved_at = time.monotonic()
        if self._fx_pos is not None and self.find_bar.local_pos() != self._fx_pos:
            self.find_bar.place(self._fx_pos)

    def _find_reset_pos(self):
        """Baslikta cift tik: ilk yerine."""
        self._fx_pos = None
        self._place_find_bar()

    # ---- arama
    def _find_restart(self, after=None):
        """Aramayi bastan kur. after: (sayfa, y, x, harf sirasi) - siradaki eslesme bundan SONRAKI olsun
        (degistirmeden sonra ayni yerde kalmamak icin); verilmezse acik sayfadaki ilk eslesme."""
        self._fx_restart_queued = False
        if self._fx_busy:
            return
        self._fx_typing.stop()
        self._fx_worker.stop()
        self._fx_matches, self._fx_pending, self._fx_cur = {}, [], None
        if not self.find_active():
            return
        b = self.find_bar
        if not self.engine.doc:
            self.find_close()
            return
        self._fx_finder.attach(self.engine)
        needle = b.needle()
        cp, n = self.current_page, self.engine.page_count()
        self._fx_query = (needle, b.case(), b.all_pages(), cp)
        if needle.strip():
            self._fx_matches[cp] = self._fx_finder.search(cp, needle, b.case())
            if b.all_pages():
                self._fx_pending = list(range(cp + 1, n)) + list(range(cp))
                self._fx_worker.start()
            if after is not None:
                if self._fx_pending:
                    self._find_finish()
                self._fx_cur = self._find_first_after(after)
            elif self._fx_matches[cp]:
                self._fx_cur = self._fx_matches[cp][0]
        self._find_refresh()
        if self._fx_cur is not None:
            self._find_show(self._fx_cur)

    def _find_work(self):
        t0 = time.monotonic()
        needle, case = self._fx_query[0], self._fx_query[1]
        while self._fx_pending and (time.monotonic() - t0) * 1000 < SLICE_MS:
            p = self._fx_pending.pop(0)
            self._fx_matches[p] = self._fx_finder.search(p, needle, case)
        if not self._fx_pending:
            self._fx_worker.stop()
        self._find_refresh()

    def _find_finish(self):
        """Kalan sayfalari hemen tara (ileri / geri / tumunu degistir oncesi)."""
        if not self._fx_pending:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            needle, case = self._fx_query[0], self._fx_query[1]
            for p in self._fx_pending:
                self._fx_matches[p] = self._fx_finder.search(p, needle, case)
            self._fx_pending = []
            self._fx_worker.stop()
        finally:
            QApplication.restoreOverrideCursor()

    def _find_list(self):
        """Kapsamdaki eslesmeler, belge sirasinda."""
        if not self._fx_query:
            return []
        if not self._fx_query[2]:
            return list(self._fx_matches.get(self.current_page, ()))
        return [m for p in sorted(self._fx_matches) for m in self._fx_matches[p]]

    @staticmethod
    def _find_pos(m, shift=0):
        sp, a, _b = m.segs[0]
        return (m.page, round(sp.origin[1]), sp.origin[0], a + shift)

    def _find_first_after(self, pos):
        lst = self._find_list()
        for m in lst:
            if self._find_pos(m) >= pos:
                return m
        return lst[0] if lst else None

    def _find_refresh(self):
        """Durum: "3 / 18 · belgede" (siradaki sonuc + kapsam, ayni sayiyi tekrarlamadan),
        siradaki yoksa "Belgede 18 eslesme", hic yoksa "Belgede sonuc yok". Sol menudeki kutunun
        sagindaki sayac kisa bicimi gosterir ("3 / 18")."""
        b = self.find_bar
        lst = self._find_list()
        total, more = len(lst), "…" if self._fx_pending else ""
        doc = b.all_pages()
        idx = next((i for i, m in enumerate(lst) if m is self._fx_cur), None) if self._fx_cur is not None else None
        if not b.needle().strip():                    # (bos satir yerine: nerede aranacagi)
            short = ""
            text = _t("Tüm belgede aranacak") if doc else _t("Yalnız bu sayfada aranacak")
        elif idx is not None:
            short = f"{idx + 1} / {total}{more}"
            text = short + " · " + (_t("belgede") if doc else _t("bu sayfada"))
        elif total or more:
            short = f"{total}{more}"
            text = (_t("Belgede {n} eşleşme", n=short) if doc else _t("Bu sayfada {n} eşleşme", n=short))
        else:
            short = _t("Sonuç yok")
            text = _t("Belgede sonuç yok") if doc else _t("Bu sayfada sonuç yok")
        none = bool(b.needle().strip()) and not total and not more
        b.set_state(text, total, none=none)
        side = getattr(self, "btn_find", None)
        if side is not None and hasattr(side, "set_hint"):        # sol menudeki kutunun sayaci
            side.set_hint(short or "Ctrl+F", none=none)
        self._find_badges_update()
        # (vurgu yokken ve onceden de yokken belgeyi yeniden cizme: buyuk sayfada sonuc satiri / ipucu
        #  belgenin cizimini beklemesin)
        drawn = bool(lst) or self._fx_cur is not None
        if drawn or getattr(self, "_fx_drawn", True):
            self.canvas.update()
        self._fx_drawn = drawn

    def _find_badges_update(self):
        counts = {p: len(ms) for p, ms in self._fx_matches.items() if ms} if self.find_active() else {}
        if not (self._fx_query and self._fx_query[2]):
            counts = {}                               # "Bu sayfa": sol listede rozet yok
        if counts != getattr(self, "_find_badges", {}):
            self._find_badges = counts
            self.thumbs.update()

    def _find_page_changed(self):
        """goto_page sonrasi: "Bu sayfa" kapsaminda arama yeni sayfa icin yenilenir."""
        if not self.find_active() or not self._fx_query:
            return
        if not self._fx_query[2]:
            self._find_restart()
        else:
            self._find_refresh()

    # ---- gezinme
    def find_step(self, delta=1):
        if not self.find_active():
            self.find_open()
            return
        if self._fx_typing.isActive() or self._find_stale():
            self._find_restart()
        self._find_finish()
        lst = self._find_list()
        if not lst:
            return
        cur = self._fx_cur
        idx = next((i for i, m in enumerate(lst) if m is cur), None)
        if idx is None:                               # siradaki yok: acik sayfadan itibaren ilk / onceki
            here = (self.current_page, -1e9, -1e9, 0)
            if delta > 0:
                m = self._find_first_after(here)
            else:
                before = [x for x in lst if self._find_pos(x) < here]
                m = before[-1] if before else lst[-1]
        else:
            m = lst[(idx + delta) % len(lst)]
        self._fx_cur = m
        self._find_show(m)
        self._find_refresh()

    def _find_show(self, m):
        """Eslesmenin sayfasina git, gorunur alana getir (cubugun altinda kalmasin)."""
        if m.page != self.current_page:
            self.goto_page(m.page)
        r = self.canvas.rect_px(self._fx_finder.bbox(m))
        vp = self.scroll.viewport()
        c = r.center()
        self.scroll.ensureVisible(int(c.x()), int(c.y()), min(220, vp.width() // 3), min(180, vp.height() // 3))
        bar = self.find_bar
        top_left = self.canvas.mapTo(bar.parentWidget(), QPoint(int(r.left()), int(r.top())))
        hit = QRect(top_left.x(), top_left.y(), int(r.width()) + 1, int(r.height()) + 1)
        if not bar.isHidden() and hit.intersects(bar.geometry().adjusted(-8, 0, 8, 8)):
            sb = self.scroll.verticalScrollBar()
            sb.setValue(sb.value() - (bar.geometry().bottom() + 16 - hit.top()))
        self.canvas.update()

    def _find_stale(self):
        f = self._fx_finder
        return f.engine is not self.engine or f.version != self.engine.version

    # ---- cizim (paint_overlay'den)
    def _paint_find(self, p, cv):
        if not self.find_active() or self._fx_busy:
            return
        if self._find_stale():                        # belge degisti (duzenleme, geri al, sekme): yenile
            if not self._fx_restart_queued:
                self._fx_restart_queued = True
                QTimer.singleShot(0, self._find_restart)
            return
        ms = self._fx_matches.get(self.current_page)
        if not ms:
            return
        # Eslesmelerin ekrandaki sekilleri saklanir; her cizimde yalniz YENIDEN CIZILEN alana dusenler
        # cizilir. Eskiden her cizimde sayfadaki butun eslesmeler (beton raporunda ~190) yeniden
        # hesaplanip ciziliyordu: tuval cizimi 0,1 ms yerine ~9 ms suruyordu, paneli surukleyince
        # altinda kalan yer gec yeneleniyordu (kullanici, 2026-10-15).
        key = (id(ms), len(ms), self.current_page, cv.zoom, cv.pad_top, tuple(cv.disp))
        cache = getattr(self, "_fx_shapes", None)
        if cache is None or cache[0] != key:
            shapes = []
            for m in ms:
                polys = [cv.poly_px(q) for q in self._fx_finder.quads(m)]
                box = QRectF()
                for pl in polys:
                    box = box.united(pl.boundingRect())
                shapes.append((m, polys, box.adjusted(-2, -2, 2, 2)))
            cache = self._fx_shapes = (key, shapes)
        area = QRectF(getattr(cv, "paint_rect", None) or cv.rect())
        cur = self._fx_cur
        p.save()
        p.setPen(Qt.NoPen)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        for m, polys, box in cache[1]:
            if box.intersects(area):
                p.setBrush(CUR_FILL if m is cur else HIT_FILL)
                for pl in polys:
                    p.drawPolygon(pl)
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if cur is not None and cur.page == self.current_page:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(CUR_LINE, 1.5))
            for q in self._fx_finder.quads(cur):
                p.drawPolygon(cv.poly_px(q))
        p.restore()

    def _find_badge(self, info):
        """Sol listedeki sayfa icin eslesme sayisi (paint_thumb'a)."""
        if info.get("lifted"):
            return 0
        return getattr(self, "_find_badges", {}).get(info["number"] - 1, 0)

    # ---- degistirme
    def _find_apply(self, matches, new_text):
        self._finish_edits()
        self._clear_selection()
        prog = None
        if len({m.page for m in matches}) > 10:       # cok sayfa: ilerleme goster
            prog = QProgressDialog(_t("Değiştiriliyor..."), "", 0, 100, self)
            prog.setCancelButton(None)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(400)

        def tick(i, n):
            if prog is not None:
                prog.setMaximum(n)
                prog.setValue(i)

        # ilerleme penceresi olaylari isletir: o sirada tuval boyanir, "belge degisti" diye arama
        # yeniden kurulmaya kalkar (yarim belge taranir, onbellek degistirmenin ortasinda atilir)
        self._fx_busy = True
        self._fx_typing.stop()
        self._fx_worker.stop()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            done, skipped, pages, inexact = pdf_search.replace(self.engine, matches, new_text, tick)
        finally:
            QApplication.restoreOverrideCursor()
            if prog is not None:
                prog.setValue(prog.maximum())
            self._fx_busy = False
        if not done:
            return done, skipped, pages, inexact
        self._fx_finder.touch(pages)
        for p in sorted(pages):
            if p != self.current_page:
                try:
                    self.engine.sync_magnifiers(p)
                except Exception:
                    pass
                self._update_thumb(p)
        if self.current_page in pages:
            self.after_edit()
        else:
            self._update_title()
            self._refresh_panel()
        return done, skipped, pages, inexact

    def find_replace_one(self):
        if not self.find_active():
            return
        if self._fx_typing.isActive() or self._find_stale():
            self._find_restart()
        m = self._fx_cur
        if m is None or not any(x is m for x in self._find_list()):
            self.find_step(1)                         # ilk basis: once eslesmeyi goster
            return
        if not m.replaceable:
            self.status(_t("Bu eşleşme birden çok yazı parçasına bölünmüş; değiştirilemedi. Elle düzenleyin."))
            self.find_step(1)
            return
        new = self.find_bar.replacement()
        after = self._find_pos(m, len(new))
        done, _skipped, _pages, inexact = self._find_apply([m], new)
        if done:
            self.status(_t("Değiştirildi.") + self._find_font_note(inexact))
        self._find_restart(after=after)

    def find_replace_all(self):
        if not self.find_active():
            return
        if self._fx_typing.isActive() or self._find_stale():
            self._find_restart()
        self._find_finish()
        lst = self._find_list()
        if not lst:
            return
        doc = self.find_bar.all_pages()
        done, skipped, pages, inexact = self._find_apply(lst, self.find_bar.replacement())
        if done and not doc:
            msg = _t("Bu sayfada {n} eşleşme değiştirildi.", n=done)
        elif done and len(pages) > 1:
            msg = _t("Belgede {n} eşleşme değiştirildi ({p} sayfada).", n=done, p=len(pages))
        elif done:
            msg = _t("Belgede {n} eşleşme değiştirildi.", n=done)
        else:
            msg = _t("Değiştirilen yer olmadı.")
        if skipped:
            msg += " " + _t("{n} eşleşme birden çok yazı parçasına bölünmüş olduğu için atlandı.", n=skipped)
        self.status(msg + self._find_font_note(inexact))
        self._find_restart()

    @staticmethod
    def _find_font_note(inexact):
        return (" " + _t("{n} yerde yazı tipi tam bulunamadı, en yakını kullanıldı.", n=inexact)) if inexact else ""
