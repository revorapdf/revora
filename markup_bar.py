"""
markup_bar.py
-------------
Isaretle modunun ShareX tarzi ust araç çubugu icin kucuk bilesenler:
- SwatchButton: renk kutucugu; tiklayinca hizli renk paleti (+ ozel renk)
- Popover: dugmenin altinda acilan kucuk ayar kutusu (disari tiklayinca kapanir)
- tool_button / toggle_button: ikonlu, kompakt dugmeler (secili halde beyaz ikon)

Renkler (0-1 arasi) liste/tuple olarak tasinir; ColorButton ile ayni arayuz:
.rgb, set_rgb(), changed(tuple) sinyali.
"""
# import sirasi kurali: PySide6, fitz'ten once (bu modul fitz kullanmiyor)
from PySide6.QtWidgets import (QToolButton, QFrame, QGridLayout, QVBoxLayout, QPushButton,
                               QColorDialog, QWidget, QHBoxLayout, QLabel, QLayout)
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QIcon, QBrush, QPolygonF, QPainterPath
from PySide6.QtCore import Qt, Signal, QSize, QRectF, QPoint, QPointF, QObject, QEvent, QTimer
from i18n import _t

try:
    import qtawesome as qta
except Exception:          # ikon kutuphanesi yoksa yazili dugme
    qta = None

PALETTE = [
    [0.863, 0.149, 0.149], [0.976, 0.451, 0.086], [0.980, 0.800, 0.082], [0.086, 0.639, 0.290],
    [0.024, 0.714, 0.831], [0.145, 0.388, 0.922], [0.486, 0.227, 0.929], [0.925, 0.282, 0.600],
    [0.0, 0.0, 0.0], [0.30, 0.30, 0.30], [0.62, 0.62, 0.62], [1.0, 1.0, 1.0],
]
PALETTE_NAMES = [_t("Kırmızı"), _t("Turuncu"), _t("Sarı"), _t("Yeşil"), _t("Turkuaz"), _t("Mavi"), _t("Mor"), _t("Pembe"),
                 _t("Siyah"), _t("Koyu gri"), _t("Gri"), _t("Beyaz")]
ICON_COLOR = {"light": "#3d424a", "dark": "#b4b4b4"}
ICON_ON = "#ffffff"          # secili (acik) dugmenin ikonu; temaya gore main.set_theme degistirir

# IKON AILESI: Phosphor (qtawesome ile gelir; "ph."). Kod eski adlari (mdi6 / fa5s) kullanmaya
# devam eder, burada Phosphor karsiligina cevrilir. Karsiligi olmayan ad oldugu gibi kalir.
# (qtawesome'daki Phosphor eski bir surum: imza, damga, tarama, ayirma ikonlari yok -> en yakini.)
PH = {
    "fa5s.arrow-down": "arrow-down", "fa5s.arrow-up": "arrow-up", "fa5s.check": "check", "fa5s.clipboard": "clipboard",
    "fa5s.columns": "columns", "fa5s.copy": "copy", "fa5s.cut": "scissors", "fa5s.eraser": "eraser",
    "fa5s.exchange-alt": "arrows-left-right", "fa5s.file": "file", "fa5s.file-image": "image",
    "fa5s.file-import": "file-arrow-down", "fa5s.file-pdf": "file-pdf", "fa5s.folder-open": "folder-open",
    "fa5s.image": "image", "fa5s.images": "image-square", "fa5s.info-circle": "info", "fa5s.keyboard": "keyboard",
    "fa5s.language": "translate", "fa5s.object-group": "selection-all", "fa5s.plus": "plus",
    "fa5s.redo": "arrow-clockwise", "fa5s.trash": "trash", "fa5s.trash-alt": "trash",
    "fa5s.undo": "arrow-counter-clockwise",
    "mdi6.arrow-collapse-horizontal": "arrows-in-line-horizontal", "mdi6.arrow-collapse-vertical": "arrows-in-line-vertical",
    "mdi6.arrow-expand-horizontal": "arrows-out-line-horizontal", "mdi6.arrow-top-right": "arrow-up-right",
    "mdi6.blur": "drop-half", "mdi6.box-shadow": "copy-simple", "mdi6.call-merge": "git-merge",
    "mdi6.call-split": "columns", "mdi6.checkbox-blank-outline": "square", "mdi6.chevron-down": "caret-down",
    "mdi6.chevron-left": "caret-left", "mdi6.chevron-right": "caret-right", "mdi6.chevron-up": "caret-up",
    "mdi6.circle-outline": "circle", "mdi6.clipboard-outline": "clipboard", "mdi6.close": "x",
    "mdi6.cog-outline": "gear-six", "mdi6.content-copy": "copy", "mdi6.content-save-edit-outline": "floppy-disk-back",
    "mdi6.content-save-outline": "floppy-disk", "mdi6.cursor-default-outline": "cursor", "mdi6.delete-outline": "trash",
    "mdi6.eraser": "eraser", "mdi6.file-outline": "files", "mdi6.file-pdf-box": "file-pdf",
    "mdi6.fit-to-page-outline": "frame-corners", "mdi6.folder-open-outline": "folder-open",
    "mdi6.form-textbox": "check-square-offset", "mdi6.format-align-center": "text-align-center",
    "mdi6.format-align-left": "text-align-left", "mdi6.format-align-right": "text-align-right",
    "mdi6.format-bold": "text-bolder", "mdi6.format-color-fill": "paint-bucket", "mdi6.format-italic": "text-italic",
    "mdi6.format-text": "text-t", "mdi6.format-text-variant-outline": "text-aa",
    "mdi6.image-multiple-outline": "image-square", "mdi6.image-outline": "image", "mdi6.image-plus-outline": "image",
    "mdi6.lock-open-variant-outline": "lock-simple-open", "mdi6.lock-outline": "lock-simple",
    "mdi6.magnify": "magnifying-glass", "mdi6.magnify-minus-outline": "magnifying-glass-minus",
    "mdi6.magnify-plus-outline": "magnifying-glass-plus", "mdi6.marker": "highlighter-circle",
    "mdi6.message-text-outline": "chat-text", "mdi6.minus": "line-segment",
    "mdi6.numeric-1-circle-outline": "number-circle-one", "mdi6.pencil-outline": "pencil-simple", "mdi6.plus": "plus",
    "mdi6.printer-outline": "printer", "mdi6.rectangle-outline": "rectangle", "mdi6.rotate-left": "arrow-counter-clockwise",
    "mdi6.rotate-right": "arrow-clockwise", "mdi6.signature-freehand": "pen-nib", "mdi6.square-edit-outline": "note-pencil",
    "mdi6.stamper": "stack-simple", "mdi6.table-arrow-right": "table", "mdi6.text-box-edit-outline": "note-pencil",
    "mdi6.text-box-plus-outline": "text-t", "mdi6.text-recognition": "text-aa", "mdi6.tray-arrow-down": "download-simple",
    "mdi6.watermark": "drop",
    "rv.magnet": "magnet-straight", "rv.undo": "arrow-u-up-left", "rv.redo": "arrow-u-up-right",
}
_PH_OK = {}


def ph_name(name):
    """Eski ikon adi -> ("ph.xxx", "ph.xxx-fill" | None). Phosphor'da yoksa (None, None)."""
    if name in _PH_OK:
        return _PH_OK[name]
    out = (None, None)
    key = name[3:] if name.startswith("ph.") else PH.get(name)
    if key and qta is not None:
        try:
            qta.icon("ph." + key)
            fill = None
            try:
                qta.icon("ph." + key + "-fill")
                fill = "ph." + key + "-fill"
            except Exception:
                pass
            out = ("ph." + key, fill)
        except Exception:
            pass
    _PH_OK[name] = out
    return out


def _magnet_pixmap(px, color):
    """At nali miknatis, 45 derece yatik: kutuplari sol-uste bakar (secim imleciyle ayni
    egim). Hazir ikon yazi tiplerindeki miknatis 18 px'te ya "U" harfi gibi duruyor ya da
    dondurulunce bulaniklasip kutudan tasiyordu; bu yuzden vektor olarak cizilir."""
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(px / 24, px / 24)                      # 24 birimlik kutuda ciz
    p.translate(12, 12)
    p.rotate(-45)
    p.scale(0.84, 0.84)                            # diger ikonlar gibi kenarda ~2 birim pay
    p.translate(-12, -12.05)
    pen = QPen(QColor(color), 4.6)
    pen.setCapStyle(Qt.FlatCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    r, top = 5.6, 8.4                              # yay yaricapi (eksen), govdenin ust ucu
    path = QPainterPath(QPointF(12 - r, top))
    path.lineTo(12 - r, 13)
    path.arcTo(QRectF(12 - r, 13 - r, 2 * r, 2 * r), 180, 180)
    path.lineTo(12 + r, top)
    p.drawPath(path)
    for x in (12 - r, 12 + r):                     # kutup uclari: govdeden ince boslukla ayri
        p.drawLine(QPointF(x, top - 5.2), QPointF(x, top - 1.8))
    p.end()
    return pm


def _undo_pixmap(px, color, redo=False):
    """Geri al / yinele: ince, egri govdeli ok (yinele = aynadaki yansimasi). Hazir ikonlar
    (fa5s, mdi6) dolu ve iri basli: yandaki ince sayfa oklarinin yaninda kaba duruyordu
    (kullanici: "gozumu tirmaliyor"). Cizgi kalinligi sayfa oklariyla ayni agirlikta."""
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(px / 24, px / 24)
    if redo:
        p.translate(24, 0)
        p.scale(-1, 1)
    p.translate(12, 12)
    p.scale(0.94, 0.94)
    p.translate(-12, -13)
    pen = QPen(QColor(color), 1.55)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    head = QPainterPath(QPointF(4, 8))             # ok basi: sol altta kucuk bir "L"
    head.lineTo(4, 13)
    head.lineTo(9, 13)
    p.drawPath(head)
    body = QPainterPath(QPointF(4, 13))            # govde: sola-asagi inen yay
    body.cubicTo(7.2, 9.4, 9.6, 8, 12.6, 8)
    body.arcTo(QRectF(12.6 - 7.4, 8, 14.8, 14.8), 90, -90)
    p.drawPath(body)
    p.end()
    return pm


# kendi cizdigimiz ikonlar: ad -> cizen islev(px, renk)
def _sidebar_pixmap(px, color):
    """Kenar menusunu ac / kapat: kose yuvarlak cerceve + solda dikey bolme cizgisi."""
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.scale(px / 24, px / 24)
    pen = QPen(QColor(color), 1.55)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QRectF(3.5, 4.5, 17, 15), 3.2, 3.2)
    p.drawLine(QPointF(9.5, 4.5), QPointF(9.5, 19.5))
    p.end()
    return pm


def _bold_pixmap(px, color):
    """Kalin "B": hazir ikon ailesindeki B (kalin hali bile) 18 px'te ince duruyor, "kalin"
    dugmesi oldugu anlasilmiyordu. Agir bir yazi tipinin B harfi vektor olarak cizilir."""
    from PySide6.QtGui import QFont
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    f = QFont()
    f.setFamilies(["Arial Black", "Segoe UI Black", "Arial"])
    f.setWeight(QFont.Black)
    f.setPixelSize(100)
    path = QPainterPath()
    path.addText(0, 0, f, "B")
    r = path.boundingRect()
    if r.height() <= 0:
        return pm
    k = px * 0.70 / r.height()                     # harf, kutunun %70'i kadar yuksek
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.translate(px / 2, px / 2)
    p.scale(k, k)
    p.translate(-r.center())
    p.fillPath(path, QColor(color))
    p.end()
    return pm


# hazir ikon yerine kendi cizimimizi kullanan eski adlar
_ALIAS = {"mdi6.format-bold": "rv.bold"}

_CUSTOM = {
    "rv.bold": _bold_pixmap,
    "rv.sidebar": _sidebar_pixmap,
    "rv.magnet": _magnet_pixmap,
    "rv.undo": lambda px, color: _undo_pixmap(px, color, False),
    "rv.redo": lambda px, color: _undo_pixmap(px, color, True),
}


def custom_icon(name, color, color_on=None, color_disabled=None):
    """`rv.` ile baslayan ad -> kendi cizimimiz (her ekran olceginde net). Bilinmeyen ad: None.
    color_on: secili (checked) hal; color_disabled: dugme devre disiyken (soluk)."""
    draw = _CUSTOM.get(name)
    if draw is None:
        return None
    ic = QIcon()
    for px in (16, 18, 20, 24, 27, 30, 36, 40, 45, 54, 60, 72, 80):   # %100-%400 ekran olcegi
        ic.addPixmap(draw(px, color), QIcon.Normal, QIcon.Off)
        if color_on is not None:
            on = draw(px, color_on)
            ic.addPixmap(on, QIcon.Normal, QIcon.On)
            ic.addPixmap(on, QIcon.Active, QIcon.On)
        if color_disabled is not None:
            ic.addPixmap(draw(px, color_disabled), QIcon.Disabled, QIcon.Off)
    return ic


def icon(name, dark=False, on_white=True):
    """Tema rengine uygun ikon; secili (checked) halde beyaz."""
    col = ICON_COLOR["dark" if dark else "light"]
    name = _ALIAS.get(name, name)
    ph, fill = (None, None) if name.startswith("rv.") else ph_name(name)
    if ph is not None:                             # Phosphor: secili halde DOLU bicim + vurgu rengi
        try:
            if on_white:
                return qta.icon(ph, color=col, color_disabled="#5a5a5a", on=fill or ph, color_on=ICON_ON,
                                active=ph, color_active=col, on_active=fill or ph, color_on_active=ICON_ON)
            return qta.icon(ph, color=col, color_disabled="#5a5a5a")
        except Exception:
            pass
    if name.startswith("rv."):                     # kendi cizdigimiz ikon (qtawesome'da yok)
        return custom_icon(name, col, ICON_ON if on_white else None) or QIcon()
    if qta is None:
        return QIcon()
    try:
        if on_white:
            return qta.icon(name, color=col, color_on=ICON_ON, color_active=col, color_on_active=ICON_ON)
        return qta.icon(name, color=col)
    except Exception:
        return QIcon()


class Popover(QFrame):
    """Dugmenin altinda acilan kucuk ayar kutusu (Qt.Popup: disari tiklayinca kapanir).
    Her acilista YENI kurulan kutu kapaninca kendini siler (keep=False): yoksa kapali kutular
    sahibinin cocugu olarak birikir (on ac-kapat = on kapali kutu + on surgu) ve her gorunum
    degisiminde yeniden bicimlendirilir. Bir kez kurulup yeniden gosterilen kutu: keep=True."""

    def __init__(self, parent=None, keep=False):
        super().__init__(parent, Qt.Popup | Qt.FramelessWindowHint)
        self.setObjectName("mkPopover")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self._keep = keep

    def hideEvent(self, ev):
        super().hideEvent(ev)
        if not self._keep:
            self.deleteLater()

    def show_under(self, w):
        self.adjustSize()
        p = w.mapToGlobal(QPoint(0, w.height() + 4))
        scr = w.screen().availableGeometry() if w.screen() else None
        if scr is not None and p.x() + self.width() > scr.right():
            p.setX(scr.right() - self.width())
        self.move(p)
        self.show()


class SwatchButton(QToolButton):
    """Renk kutucugu. Tiklayinca hizli palet acilir. glyph: kutucugun ustunde
    kucuk isaret ("A" = yazi rengi) ki hangi renk oldugu bir bakista anlasilsin."""
    changed = Signal(tuple)

    def __init__(self, rgb=(0, 0, 0), tip=_t("Renk"), glyph=None, parent=None):
        super().__init__(parent)
        self.setObjectName("mkSwatch")
        self.rgb = tuple(rgb)
        self.glyph = glyph
        self.setToolTip(tip)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(40, 32)
        self.setIconSize(QSize(30, 22))
        self.clicked.connect(self._open)
        self._paint()

    def set_rgb(self, rgb):
        self.rgb = tuple(rgb)
        self._paint()

    def _paint(self):
        dpr = self.devicePixelRatioF() if self.window() is not None else 1.0
        pm = QPixmap(int(30 * dpr), int(22 * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor.fromRgbF(*[min(1.0, max(0.0, v)) for v in self.rgb])
        p.setPen(QPen(QColor(0, 0, 0, 70), 1))
        p.setBrush(QBrush(c))
        p.drawRoundedRect(QRectF(1.5, 1.5, 19, 19), 4, 4)
        if self.glyph:
            p.setPen(QColor(255, 255, 255) if c.lightnessF() < 0.6 else QColor(20, 20, 20))
            f = p.font()
            f.setBold(True)
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(QRectF(1.5, 1.5, 19, 19), Qt.AlignCenter, self.glyph)
        # kucuk asagi ok: acilir oldugu anlasilsin
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(120, 125, 133))
        p.drawPolygon(QPolygonF([QPointF(23, 9), QPointF(29, 9), QPointF(26, 13)]))
        p.end()
        self.setIcon(QIcon(pm))

    def _open(self):
        self.build_popup().show_under(self)

    def build_popup(self):
        pop = Popover(self)
        lay = QVBoxLayout(pop)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.setSpacing(6)
        grid = QGridLayout()
        grid.setSpacing(4)
        for i, (col, name) in enumerate(zip(PALETTE, PALETTE_NAMES)):
            b = QToolButton()
            b.setObjectName("mkPaletteCell")
            b.setFixedSize(26, 26)
            b.setToolTip(name)
            qc = QColor.fromRgbF(*col)
            sel = all(abs(a - b_) < 0.01 for a, b_ in zip(col, self.rgb))
            b.setStyleSheet(f"QToolButton {{ background: {qc.name()}; border-radius: 5px;"
                            f" border: {'2px solid #2563eb' if sel else '1px solid rgba(0,0,0,0.25)'}; }}")
            b.clicked.connect(lambda _=False, c=col, p_=pop: (p_.close(), self._choose(c)))
            grid.addWidget(b, i // 6, i % 6)
        lay.addLayout(grid)
        more = QPushButton(_t("Özel renk…"))
        more.clicked.connect(lambda: (pop.close(), self._custom()))
        lay.addWidget(more)
        return pop

    def _custom(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.rgb), self.window(), _t("Renk seç"))
        if c.isValid():
            self._choose((c.redF(), c.greenF(), c.blueF()))

    def _choose(self, col):
        self.set_rgb(col)
        self.changed.emit(tuple(col))


def tool_button(name, tip, checkable=True, text=None, dark=False, size=34):
    b = QToolButton()
    b.setObjectName("mkTool")
    b.setCheckable(checkable)
    b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    b.setAutoRaise(True)
    ic_ = icon(name, dark)
    if not ic_.isNull():
        b.setIcon(ic_)
        b.setIconSize(QSize(18, 18))
    if text:
        b.setText(text)
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon if not ic_.isNull() else Qt.ToolButtonTextOnly)
    else:
        b.setFixedSize(size, size)
    b._icon_name = name
    return b


class _DropPlacer(QObject):
    """Sayi kutusunun sagindaki ▾ dugmesini kutu boyutlaninca yerine oturtur."""

    def __init__(self, spin, btn):
        super().__init__(spin)
        self.spin, self.btn = spin, btn

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show):
            h = self.spin.height()
            self.btn.setGeometry(self.spin.width() - 23, 3, 20, max(10, h - 6))
        return False


class _SliderFeed(QObject):
    """Acilir surgu -> sayi kutusu koprusu.

    Surgunun degeri kutuya HEMEN yazilmaz; "son deger" olarak tutulur ve olay dongusunun bir
    sonraki turunda bir kez uygulanir. Neden: kutunun degeri degisince calisan is agirdir (PDF
    nesnesi yeniden kurulur, sayfa cizilir). Windows'ta fare hareketleri arka arkaya gelirken
    Qt bekleyen cizimleri yapamaz (yerel iletiler bitmeden kendi olaylarina sira gelmez): is her
    fare hareketinde dogrudan yapilinca surgunun noktasi surukleme boyunca hic cizilmiyor, fareyi
    izlemiyordu. Fare hareketinin kendi isi artik bostur -> nokta her harekette cizilir; agir is
    aradaki bosluklarda, her seferinde yalniz SON degerle yapilir.

    Bekleyen deger kaybolmaz: fare birakilinca ve kutu kapaninca (disari tiklama, Esc, baska
    pencere) hemen uygulanir. begin / end: bir ayarlama oturumunun basi ve sonu (bir surukleme =
    bir geri-al adimi; kucuk resim gibi ertelenen isler sonda yapilir)."""

    def __init__(self, pop, slider, spin, scale, begin, end):
        super().__init__(pop)
        self.pop, self.s, self.spin, self.scale = pop, slider, spin, scale
        self.begin, self.end = begin, end
        self._pending = None
        self._open = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(0)
        self._timer.timeout.connect(self.flush)
        slider.valueChanged.connect(self._moved)
        slider.sliderReleased.connect(self.finish)
        pop.installEventFilter(self)

    def _moved(self, v):
        self._pending = v
        if not self._timer.isActive():
            self._timer.start()

    def flush(self):
        self._timer.stop()
        if self._pending is None:
            return
        v, self._pending = self._pending, None
        if not self._open:
            self._open = True
            if self.begin is not None:
                self.begin()
        self.spin.setValue(v / self.scale)
        # Kutunun isleyicisi ust seridi gizleyip gosterirse Qt, acik kutunun BEKLEYEN cizimini de
        # siler (gizlenen parcanin cocuklari arasinda bu pencere de var). O zaman yalniz sonraki
        # kucuk guncelleme (noktanin yeni yeri) cizilir, eski nokta ekranda kalirdi: cift nokta.
        self.pop.update()

    def finish(self):
        self.flush()
        if self._open:
            self._open = False
            if self.end is not None:
                self.end()

    def eventFilter(self, obj, ev):
        if obj is self.pop and ev.type() == QEvent.Hide:
            self.finish()
        return False


def attach_slider(spin, lo, hi, scale=1.0, dark=False, begin=None, end=None):
    """Ust seritteki sayi kutusu: kucuk yukari/asagi oklar yerine sagda ▾; tiklayinca
    kaydirmali surgu acilir. Deger yine yazilabilir, fare tekerlegiyle degisir.
    scale: surgunun tam sayi adimi = 1/scale (ör. 4 -> 0,25'lik adim).
    begin / end: surguyle ayarlama oturumunun basinda / sonunda cagrilir (bkz. _SliderFeed).
    Dondurur: ▾ dugmesi (tema degisince ikonu yeniden renklensin diye)."""
    from PySide6.QtWidgets import QAbstractSpinBox, QSlider
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    spin.setProperty("mkDrop", True)
    btn = QToolButton(spin)
    btn.setObjectName("mkSpinDrop")
    btn.setCursor(Qt.PointingHandCursor)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setAutoRaise(True)
    btn.setIcon(icon("mdi6.chevron-down", dark, on_white=False))
    btn.setIconSize(QSize(14, 14))
    btn._icon_name = "mdi6.chevron-down"
    btn._on_white = False
    spin.installEventFilter(_DropPlacer(spin, btn))

    def open_slider():
        pop = Popover(spin)
        lay = QHBoxLayout(pop)
        lay.setContentsMargins(12, 10, 12, 10)
        s = QSlider(Qt.Horizontal)
        s.setFixedSize(200, 22)          # yuvarlak tutamac ust/altta kesilmesin
        s.setRange(int(round(lo * scale)), int(round(hi * scale)))
        s.setValue(int(round(min(max(spin.value(), lo), hi) * scale)))
        pop.feed = _SliderFeed(pop, s, spin, scale, begin, end)
        lay.addWidget(s)
        pop.show_under(spin)
        s.setFocus()

    btn.clicked.connect(open_slider)
    return btn


def dash_icon(style, dark=False):
    """Kesikli desenin kucuk resmi (acilir listede gosterilir)."""
    import curve_math
    dpr = 2.0
    pm = QPixmap(int(46 * dpr), int(12 * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(ICON_COLOR["dark" if dark else "light"]))
    pen.setWidthF(2.0)
    pen.setCapStyle(Qt.FlatCap)
    arr = curve_math.dash_array(style, 1.0)
    if arr:
        pen.setDashPattern([max(0.3, v) for v in arr])   # birim: kalem kalinligi
    p.setPen(pen)
    p.drawLine(QPointF(2, 6), QPointF(44, 6))
    p.end()
    return QIcon(pm)


def dash_combo(dark=False, tip=_t("Kesikli çizgi deseni")):
    """Kesikli desen secimi (resimli). Veri: curve_math.DASH_STYLES anahtari."""
    import curve_math
    from PySide6.QtWidgets import QComboBox
    cb = QComboBox()
    cb.setObjectName("mkDash")
    cb.setIconSize(QSize(46, 12))
    cb.setFixedWidth(86)
    cb.setToolTip(tip)
    for i, (key, name, _) in enumerate(curve_math.DASH_STYLES):
        cb.addItem(dash_icon(key, dark), "", key)
        cb.setItemData(i, name, Qt.ToolTipRole)
    return cb


def fit_combo(cb, widen=0, only=None):
    """Acilan liste en uzun satirina gore genisler (ceviriler Turkceden uzun olabiliyor).
    widen > 0: sabit genislikli kutunun kendisi de, yazisi sigmiyorsa en cok widen px genisler;
    only: kutu genisligi icin bakilacak satirlar (verilmezse hepsi)."""
    cb.ensurePolished()
    fm = cb.fontMetrics()
    width = lambda rows: max((fm.horizontalAdvance(cb.itemText(i)) for i in rows), default=0) + 30
    need = width(range(cb.count()))
    if need > cb.view().minimumWidth():
        cb.view().setMinimumWidth(need)
    fixed = cb.maximumWidth()
    if widen and cb.minimumWidth() == fixed:
        need = width(only if only is not None else range(cb.count()))
        if need > fixed:
            cb.setFixedWidth(min(need, fixed + widen))


def recolor_dash_combo(cb, dark):
    for i in range(cb.count()):
        cb.setItemIcon(i, dash_icon(cb.itemData(i), dark))


def vsep(strong=False, breakable=True):
    """Ayirici. strong: ana gruplar arasi - UZUN menulerde belirgin kalin cizgi, kisa
    menulerde ince (bkz. WrapPill). breakable: menu sigmazsa ikinci satira buradan
    gecilebilir; gorunurlugunu baska kodun degistirdigi ayiricilarda False."""
    w = QWidget()
    w.setProperty("mkSepBox", True)
    w.setProperty("mkStrong", bool(strong))
    w.setProperty("mkBreak", bool(breakable))
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    w._line = QFrame()
    lay.addWidget(w._line)
    set_sep_strong(w, False)
    return w


def set_sep_strong(w, on):
    f = w._line
    name = "mkSepStrong" if on else "mkSep"
    if f.objectName() == name:
        return
    f.setObjectName(name)
    if on:
        f.setFixedSize(2, 24)
        w.layout().setContentsMargins(6, 0, 6, 0)
    else:
        f.setFixedSize(1, 22)
        w.layout().setContentsMargins(0, 0, 0, 0)
    f.style().unpolish(f)
    f.style().polish(f)


def _is_sep(w):
    return bool(w.property("mkSepBox"))


def _group_widgets(w):
    lay = w.layout() if w.property("mkGroup") else None
    if lay is None:
        return []
    return [lay.itemAt(i).widget() for i in range(lay.count()) if lay.itemAt(i).widget() is not None]


class WrapPill(QFrame):
    """Yuvarlak koseli serit (ShareX'teki gibi). Sigarsa tek satir; sigmazsa bir grup
    ayiricisindan ikinci satira kayar (iki satir da ortali, ayirici o noktada gizlenir).
    Uzun menulerde (STRONG_AT ve ustu ayar) ana grup ayiricilari kalinlasir; kisa
    menulerde ince kalir (her ayarin arasinda kalin cizgi gereksiz kalabalik)."""
    STRONG_AT = 14
    LINE_H = 36            # her satir ayni yukseklikte: menu degisince sayfa 1-2 px oynamasin

    def __init__(self):
        super().__init__()
        self.setObjectName("mkPill")
        self.setAttribute(Qt.WA_StyledBackground, True)
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(4)
        v.setSizeConstraint(QLayout.SetFixedSize)    # icerik kadar: gizlenen parcalarla daralir
        self._lines = []
        for k in range(2):
            h = QHBoxLayout()
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(3)
            if k == 0:                     # (bos ikinci satira konursa o da yer kaplardi)
                h.addStrut(self.LINE_H)
            h.addStretch()
            h.addStretch()
            v.addLayout(h)
            self._lines.append(h)
        self._items = []
        self._cut = None

    # QHBoxLayout gibi kullanilir (pill() bu nesneyi "layout" olarak da dondurur)
    def addWidget(self, w):
        self._items.append(w)
        h = self._lines[0]
        h.insertWidget(h.count() - 1, w)

    def wrapped(self):
        return self._cut is not None

    def _controls(self, w):
        if _is_sep(w):
            return 0
        kids = _group_widgets(w)
        if kids:
            return sum(self._controls(k) for k in kids if not k.isHidden())
        return 1

    def _seps(self, w):
        if _is_sep(w):
            return [w]
        return [k for k in _group_widgets(w) if _is_sep(k)]

    def _break_sep(self, w):
        if _is_sep(w):
            return w if w.property("mkBreak") else None
        kids = [k for k in _group_widgets(w) if not k.isHidden()]
        if kids and _is_sep(kids[0]) and kids[0].property("mkBreak"):
            return kids[0]
        return None

    def unwrap(self):
        """Tek satira don (gizlenen kirilma ayiricisi geri gelir). Gorunurlukler
        degismeden ONCE cagrilir; yoksa baska menude gizlenmesi gereken ayirici
        yanlislikla geri acilabilir."""
        self._unwrap()

    def _unwrap(self):
        if self._cut is not None:
            self._cut.show()
            self._cut = None
        h0, h1 = self._lines
        moved = [h1.itemAt(i).widget() for i in range(h1.count()) if h1.itemAt(i).widget() is not None]
        for w in moved:
            h1.removeWidget(w)
            h0.insertWidget(h0.count() - 1, w)

    def rewrap(self, avail):
        """avail: seridin kullanabilecegi en fazla genislik (px)."""
        self._unwrap()
        items = [w for w in self._items if not w.isHidden()]
        strong = sum(self._controls(w) for w in items) >= self.STRONG_AT
        for w in self._items:
            for sp in self._seps(w):
                set_sep_strong(sp, bool(sp.property("mkStrong")) and strong)
            # ayirici kalinlasinca ust parcalarin onbellekteki boyutu hemen yenilensin
            # (yoksa serit cercevesi bir sonraki olaya kadar dar kalir, icerik tasar)
            if w.layout() is not None:
                w.layout().invalidate()
            w.updateGeometry()
        gap = self._lines[0].spacing()
        widths = [w.sizeHint().width() for w in items]
        m = self.layout().contentsMargins()
        if sum(widths) + gap * (len(items) - 1) + m.left() + m.right() <= avail or len(items) < 2:
            return
        best = None
        for i in range(1, len(items)):
            sp = self._break_sep(items[i])
            if sp is None:
                continue
            a = sum(widths[:i]) + gap * (i - 1)
            b = sum(widths[i:]) + gap * (len(items) - i - 1) - sp.sizeHint().width()
            if best is None or max(a, b) < best[0]:
                best = (max(a, b), items[i], sp)
        if best is None:
            return
        _, first, sp = best
        h0, h1 = self._lines
        for w in self._items[self._items.index(first):]:
            h0.removeWidget(w)
            h1.insertWidget(h1.count() - 1, w)
        sp.hide()
        self._cut = sp


def pill():
    """Yuvarlak koseli arka planli serit; dondurur (serit, ekleme nesnesi)."""
    f = WrapPill()
    return f, f


def group():
    """Secenek satirinda birlikte gizlenip gosterilen parca."""
    w = QWidget()
    w.setProperty("mkGroup", True)
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(3)
    return w, lay


def small_label(text):
    l = QLabel(text)
    l.setObjectName("mkLabel")
    return l
