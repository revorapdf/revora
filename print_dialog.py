"""
print_dialog.py
---------------
Yazdir penceresi (Ctrl+P): solda ayarlar, sagda canli onizleme. Windows'un yazici penceresinin
yerine (kullanici, 2026-10-14: "bizim temamiza uygun, Edge'deki gibi onizlemeli bir yazdirma").

Duzen: ayarlar SOLDA (ana penceredeki sol menuyle ayni yerlesim mantigi: kumanda solda, belge
sagda); onizleme sagda, calisma alaninin noktali zemininde, her kagit kendi gercek boyu, yazicinin
basamadigi kenar payi ve secilen yon / olcek / renkle. Altta "Windows yazdirma penceresi" baglantisi
(surucunun kendi ayarlari gerektiginde).

Kagidin yerlesimi tek yerde (plan): onizleme ve baski AYNI hesabi kullanir.
    Yon "Otomatik": her sayfa kendi yonundeki kagida (yatay sayfa yan yatirilarak basilir)
    "Dikey" / "Yatay": kagit sabit, sayfa donmeden sigdirilir
    Olcek "Sayfaya sigdir": basilabilir alana orani korunarak; "Gercek boyut": 1 pt = 1 pt, ortali
"""
import math

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout, QLabel, QComboBox, QSpinBox, QCheckBox,
                               QLineEdit, QPushButton, QScrollArea, QWidget, QFrame, QSizePolicy, QMessageBox,
                               QApplication)
from PySide6.QtGui import QColor, QPainter, QImage, QPixmap, QPageSize, QPageLayout, QCursor
from PySide6.QtCore import Qt, QRectF, QPointF, QSizeF, QTimer, Signal, QSize, QMarginsF
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo

import fitz

from i18n import _t
import dialogs

LEFT_W = 340                 # ayar sutununun genisligi (uzun cevirilerde icerige gore buyur)
SHEET_MAX = 760              # onizlemede bir kagidin en genis hali (mantiksal px)
GAP = 28                     # onizlemede kagitlar arasi


# ---------------------------------------------------------------- yerlesim (onizleme + baski ortak)
def plan(page_w, page_h, paper_w, paper_h, margins, orient, fit):
    """Bir PDF sayfasinin kagida yerlesimi, PUNTO cinsinden.
    page_w/h: sayfa; paper_w/h: kagit (yazicidaki yonuyle); margins: (sol, ust, sag, alt) basilamayan pay.
    orient: "auto" | "portrait" | "landscape"; fit: True = sigdir, False = gercek boyut.
    Dondurur: (kagit_g, kagit_y, alan QRectF, hedef QRectF, dondur)
      kagit / alan / hedef: sayfanin DIK goruldugu kagit duzleminde (onizleme bunu cizer);
      dondur: baskida sayfa kagida 90 derece yan yatirilarak basilir (kagit yazicida baska yonde)."""
    pw, ph = paper_w, paper_h
    l, t, r, b = margins
    paper_land = pw > ph
    if orient == "auto":
        want_land = page_w > page_h
    else:
        want_land = orient == "landscape"
    turn = orient == "auto" and want_land != paper_land
    if orient != "auto" and want_land != paper_land:      # (sabit yon: kagidin kendisi o yonde)
        pw, ph = ph, pw
        l, t, r, b = t, r, b, l
    if turn:
        # sayfa kagida saat yonunde yan yatirilarak basilir; dik gorunum = kagit saat yonunun tersine
        # cevrilmis: yazicidaki ust pay solda, sag pay ustte, alt pay sagda, sol pay altta
        pw, ph = ph, pw
        l, t, r, b = t, r, b, l
    area = QRectF(l, t, max(1.0, pw - l - r), max(1.0, ph - t - b))
    k = min(area.width() / page_w, area.height() / page_h) if fit else 1.0
    w, h = page_w * k, page_h * k
    tgt = QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h)
    return pw, ph, area, tgt, turn


def render(page, w_px, h_px, gray, rotate=False):
    """Sayfanin goruntusu (w_px x h_px, donmeden once). gray: siyah-beyaz."""
    sx = w_px / page.rect.width
    sy = h_px / page.rect.height
    mat = fitz.Matrix(sx, sy)
    if rotate:
        mat = mat.prerotate(90)
    cs = fitz.csGRAY if gray else fitz.csRGB
    pix = page.get_pixmap(matrix=mat, alpha=False, colorspace=cs)
    fmt = QImage.Format_Grayscale8 if gray else QImage.Format_RGB888
    return QImage(pix.samples, pix.width, pix.height, pix.stride, fmt).copy()


# ---------------------------------------------------------------- onizleme
class _Sheet(QWidget):
    """Onizlemede bir kagit: beyaz kagit + golge, basilamayan kenar (cok ince), sayfanin goruntusu.
    Goruntu GORUNUNCE cizilir ve saklanir (yuzlerce sayfalik belgede de pencere hemen acilir)."""

    def __init__(self, view, idx):
        super().__init__()
        self.view, self.idx = view, idx
        self._img = None
        self._key = None

    def paintEvent(self, ev):
        v = self.view
        spec = v.specs[self.idx]
        pno, (pw, ph, area, tgt, _turn) = spec
        W, H = self.width(), self.height()
        k = (W - 2) / pw
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        sheet = QRectF(1, 1, pw * k, ph * k)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 70))
        p.drawRoundedRect(sheet.translated(0, 2), 2, 2)
        p.setBrush(QColor("#ffffff"))
        p.drawRect(sheet)
        dpr = self.devicePixelRatioF()
        tw, th = max(1, round(tgt.width() * k * dpr)), max(1, round(tgt.height() * k * dpr))
        key = (pno, tw, th, v.gray, v.gen)
        if key != self._key:
            try:
                self._img = render(v.doc[pno], tw, th, v.gray)
                self._img.setDevicePixelRatio(dpr)
            except Exception:
                self._img = None
            self._key = key
        clip = QRectF(1 + area.x() * k, 1 + area.y() * k, area.width() * k, area.height() * k)
        if self._img is not None:
            p.save()
            p.setClipRect(clip)
            p.drawImage(QRectF(1 + tgt.x() * k, 1 + tgt.y() * k, tgt.width() * k, tgt.height() * k), self._img)
            p.restore()
        p.end()


class Preview(QScrollArea):
    """Secilen sayfalarin kagitlari alt alta; kagit genisligi pencereye gore (en cok SHEET_MAX)."""

    def __init__(self, doc, colors):
        super().__init__()
        self.setObjectName("printPreview")
        self.doc = doc
        self._colors = colors
        self.specs = []
        self.gray = False
        self.gen = 0
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        self.body.setObjectName("printPreviewBody")
        self.lay = QVBoxLayout(self.body)
        self.lay.setContentsMargins(GAP, GAP, GAP, GAP)
        self.lay.setSpacing(6)
        self.setWidget(self.body)
        self._sheets = []
        self._labels = []
        self._tile = None
        self.viewport().installEventFilter(self)

    def eventFilter(self, obj, ev):
        from PySide6.QtCore import QEvent
        if obj is self.viewport() and ev.type() == QEvent.Paint:
            c = self._colors()
            d = obj.devicePixelRatioF()
            key = (c.get("bg"), c.get("dot"), d)
            if self._tile is None or self._tile[0] != key:
                tile = QPixmap(int(20 * d), int(20 * d))
                tile.setDevicePixelRatio(d)
                tile.fill(QColor(c.get("bg", "#0e0e0e")))
                tp = QPainter(tile)
                tp.setRenderHint(QPainter.Antialiasing)
                tp.setPen(Qt.NoPen)
                tp.setBrush(QColor(c.get("dot", "#202020")))
                tp.drawEllipse(QPointF(10, 10), 1.1, 1.1)
                tp.end()
                self._tile = (key, tile)
            p = QPainter(obj)
            p.drawTiledPixmap(obj.rect(), self._tile[1])
            p.end()
        elif obj is self.viewport() and ev.type() == QEvent.Resize:
            QTimer.singleShot(0, self._size_sheets)
        return False

    def set_specs(self, specs, gray):
        """specs: [(sayfa no, plan(...))]. Kagit sayisi degismediyse parcalar yeniden kullanilir."""
        self.specs, self.gray = specs, gray
        self.gen += 1
        while len(self._sheets) < len(specs):
            i = len(self._sheets)
            s = _Sheet(self, i)
            lab = QLabel()
            lab.setObjectName("printPageNo")
            lab.setAlignment(Qt.AlignCenter)
            self.lay.addWidget(s, 0, Qt.AlignHCenter)
            self.lay.addWidget(lab, 0, Qt.AlignHCenter)
            self.lay.addSpacing(GAP - 10)
            self._sheets.append(s)
            self._labels.append(lab)
        for i, (s, lab) in enumerate(zip(self._sheets, self._labels)):
            on = i < len(specs)
            s.setVisible(on)
            lab.setVisible(on)
            if on:
                lab.setText(str(specs[i][0] + 1))
        self._size_sheets()
        for s in self._sheets[:len(specs)]:
            s.update()

    def _size_sheets(self):
        avail = max(160, self.viewport().width() - 2 * GAP - 4)
        vis_h = max(200, self.viewport().height() - 2 * GAP - 24)
        for s, (_pno, (pw, ph, *_rest)) in zip(self._sheets, self.specs):
            # her kagit gorunen alana BUTUNUYLE sigar: kaydirdikca kagit kagit ilerlenir
            k = min(avail, SHEET_MAX) / pw
            k = min(k, vis_h / ph)
            s.setFixedSize(int(pw * k) + 2, int(ph * k) + 4)


# ---------------------------------------------------------------- pencere
class PrintDialog(QDialog):
    """Sonuc (kabul edilince): printer() - ayarlanmis QPrinter; pages(); options() -> dict
    (orient, fit, gray, copies, collate). use_system: kullanici Windows penceresini istedi."""

    def __init__(self, parent, doc, current_page, doc_name="", colors=None):
        super().__init__(parent)
        self.setObjectName("ringDialog")
        self.setWindowTitle(_t("Yazdır"))
        self.doc = doc
        self.current = current_page
        self.count = doc.page_count
        self.doc_name = doc_name
        self._colors = colors or (lambda: {})
        self.use_system = False
        self._pages = []
        self._printer = None
        # yazici surucusune sormak pahali (QPrinter kurmak ilk seferde ~0,4 sn, kagit degistirmek ~75 ms):
        # yazici nesnesi yazici basina, kagit olculeri (yazici, kagit) basina BIR KEZ alinir; yon / renk /
        # olcek tiklamalari surucuye hic sormaz (plan() hesaplar)
        self._qprinters = {}
        self._geo = {}
        self._loaded = None                          # ayrintilari yuklenmis yazici adi

        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- sol: ayarlar
        side = QWidget()
        side.setObjectName("printSide")
        side.setMinimumWidth(LEFT_W)
        side.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        v = QVBoxLayout(side)
        v.setContentsMargins(22, 16, 22, 18)
        v.setSpacing(6)

        v.addWidget(dialogs.section_label(_t("Yazıcı")))
        self.cmb_printer = QComboBox()
        self.cmb_printer.setAccessibleName(_t("Yazıcı"))
        self.printers = QPrinterInfo.availablePrinters()
        default = QPrinterInfo.defaultPrinterName()
        for info in self.printers:
            self.cmb_printer.addItem(info.printerName())
        if not self.printers:
            self.cmb_printer.addItem(_t("Yazıcı bulunamadı"))
            self.cmb_printer.setEnabled(False)
        else:
            names = [i.printerName() for i in self.printers]
            self.cmb_printer.setCurrentIndex(names.index(default) if default in names else 0)
        v.addWidget(self.cmb_printer)

        v.addSpacing(10)
        v.addWidget(dialogs.section_label(_t("Kopya")))
        row = QHBoxLayout()
        row.setSpacing(14)
        self.spin_copies = QSpinBox()
        self.spin_copies.setRange(1, 999)
        self.spin_copies.setAccessibleName(_t("Kopya"))
        self.spin_copies.setFixedWidth(96)
        self.chk_collate = QCheckBox(_t("Harmanla"))
        self.chk_collate.setChecked(True)
        self.chk_collate.setToolTip(_t("Açıkken kopyalar sırayla basılır: 1, 2, 3 · 1, 2, 3"))
        row.addWidget(self.spin_copies)
        row.addWidget(self.chk_collate)
        row.addStretch()
        v.addLayout(row)

        v.addSpacing(10)
        v.addWidget(dialogs.section_label(_t("Sayfalar")))
        self.seg_pages = dialogs.Segmented([_t("Tüm sayfalar"), _t("Bu sayfa ({n})", n=current_page + 1),
                                            _t("Aralık")])
        self.seg_pages.setAccessibleName(_t("Sayfalar"))
        v.addWidget(self.seg_pages)
        self.txt_range = QLineEdit()
        self.txt_range.setObjectName("scopeRange")
        self.txt_range.setPlaceholderText(_t("ör. 1-3, 5"))
        self.txt_range.setAccessibleName(_t("Aralık"))
        v.addWidget(self.txt_range)

        v.addSpacing(10)
        v.addWidget(dialogs.section_label(_t("Yön")))
        self.seg_orient = dialogs.Segmented([_t("Otomatik"), _t("Dikey"), _t("Yatay")])
        self.seg_orient.setAccessibleName(_t("Yön"))
        self.seg_orient.buttons[0].setToolTip(_t("Her sayfa kendi yönünde: yatay sayfalar kâğıda yan yatırılarak basılır"))
        v.addWidget(self.seg_orient)

        v.addSpacing(10)
        v.addWidget(dialogs.section_label(_t("Renk")))
        self.seg_color = dialogs.Segmented([_t("Renkli"), _t("Siyah-beyaz")])
        self.seg_color.setAccessibleName(_t("Renk"))
        v.addWidget(self.seg_color)

        v.addSpacing(10)
        v.addWidget(dialogs.section_label(_t("Ölçek")))
        self.seg_scale = dialogs.Segmented([_t("Sayfaya sığdır"), _t("Gerçek boyut")])
        self.seg_scale.setAccessibleName(_t("Ölçek"))
        self.seg_scale.buttons[1].setToolTip(_t("Büyütmeden, küçültmeden (%100); kâğıda sığmayan kısım kesilir"))
        v.addWidget(self.seg_scale)

        v.addSpacing(10)
        v.addWidget(dialogs.section_label(_t("Kâğıt")))
        self.cmb_paper = QComboBox()
        self.cmb_paper.setAccessibleName(_t("Kâğıt"))
        v.addWidget(self.cmb_paper)
        self.lb_duplex = dialogs.section_label(_t("Çift taraflı"))
        self.cmb_duplex = QComboBox()
        self.cmb_duplex.setAccessibleName(_t("Çift taraflı"))
        v.addSpacing(10)
        v.addWidget(self.lb_duplex)
        v.addWidget(self.cmb_duplex)

        v.addStretch(1)
        self.btn_system = QPushButton(_t("Windows yazdırma penceresiyle yazdır…"))
        self.btn_system.setObjectName("linkButton")
        self.btn_system.setCursor(QCursor(Qt.PointingHandCursor))
        self.btn_system.setToolTip(_t("Yazıcı sürücüsünün kendi ayarları gerektiğinde"))
        v.addWidget(self.btn_system, 0, Qt.AlignLeft)
        v.addSpacing(8)
        self.lb_total = QLabel()
        self.lb_total.setObjectName("dlgNote")
        v.addWidget(self.lb_total)
        v.addSpacing(6)
        import title_bar
        self.btn_print = QPushButton(_t("Yazdır"))
        self.btn_cancel = QPushButton(_t("Vazgeç"))
        bb = title_bar.action_buttons(self.btn_print, self.btn_cancel)
        bb.accepted.connect(self._accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

        line = QFrame()
        line.setObjectName("printDivider")
        line.setFixedWidth(1)

        # ---- sag: onizleme
        self.preview = Preview(doc, self._colors)
        root.addWidget(side)
        root.addWidget(line)
        root.addWidget(self.preview, 1)

        self.resize(1120, 760)
        self.setMinimumSize(880, 600)

        # ---- baglantilar
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(150)                 # (aralik yazilirken her harfte yeniden cizme)
        self._timer.timeout.connect(self._refresh)
        self.cmb_printer.currentIndexChanged.connect(self._printer_changed)
        self.spin_copies.valueChanged.connect(self._refresh_total)
        for seg in (self.seg_orient, self.seg_color, self.seg_scale):
            seg.changed.connect(lambda _=None: self._refresh())
        self.seg_pages.changed.connect(self._pages_mode)
        self.txt_range.textEdited.connect(lambda _=None: self._timer.start())
        self.cmb_paper.currentIndexChanged.connect(lambda _=None: self._refresh())
        self.cmb_duplex.currentIndexChanged.connect(self._refresh_total)
        self.btn_system.clicked.connect(self._system)
        self.focus_ring = dialogs.FocusRing(self)
        self.cmb_paper.addItem(QPageSize(QPageSize.A4).name(), QPageSize.A4)
        self.cmb_duplex.setVisible(False)
        self.lb_duplex.setVisible(False)
        self._pages_mode(0)                          # (onizleme hemen: A4; yazici ayrintilari acilinca)
        self._first = True

    def showEvent(self, ev):
        super().showEvent(ev)
        self.btn_print.setFocus()                    # (yazici listesi odakta mavi cerceveyle acilmasin)
        if self._first:                              # pencere once gorunur, yazici ayrintilari hemen ardindan
            self._first = False
            QTimer.singleShot(40, self._printer_changed)     # (ilk kare cizildikten sonra)

    # ---- yazici
    def _info(self):
        i = self.cmb_printer.currentIndex()
        return self.printers[i] if 0 <= i < len(self.printers) else None

    def _qprinter(self):
        info = self._info()
        name = info.printerName() if info else ""
        pr = self._qprinters.get(name)
        if pr is None:
            pr = QPrinter(info, QPrinter.HighResolution) if info else QPrinter(QPrinter.HighResolution)
            self._qprinters[name] = pr
        return pr

    def _printer_changed(self, *_):
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._load_printer()
        finally:
            QApplication.restoreOverrideCursor()
        self._refresh()

    def _load_printer(self):
        info = self._info()
        self._loaded = info.printerName() if info else ""
        self.cmb_paper.blockSignals(True)
        self.cmb_duplex.blockSignals(True)
        try:
            prev = self.cmb_paper.currentData()
            self.cmb_paper.clear()
            sizes = info.supportedPageSizes() if info else []
            if not sizes:
                sizes = [QPageSize(QPageSize.A4)]
            default = info.defaultPageSize().id() if info else QPageSize.A4
            for ps in sizes:
                self.cmb_paper.addItem(ps.name(), ps.id())
            ids = [ps.id() for ps in sizes]
            want = prev if prev in ids else (default if default in ids else ids[0])
            self.cmb_paper.setCurrentIndex(ids.index(want))
            # renk: yalniz siyah-beyaz basan yazicida "Renkli" secilemez
            modes = info.supportedColorModes() if info else []
            color_ok = QPrinter.Color in modes
            self.seg_color.buttons[0].setEnabled(color_ok)
            if not color_ok:
                self.seg_color.buttons[1].setChecked(True)
                self.seg_color.setToolTip(_t("Bu yazıcı yalnız siyah-beyaz basar"))
            else:
                self.seg_color.setToolTip("")
            # cift taraf: yazici destekliyorsa
            self.cmb_duplex.clear()
            dmodes = info.supportedDuplexModes() if info else []
            opts = [(QPrinter.DuplexNone, _t("Tek taraflı"))]
            if QPrinter.DuplexLongSide in dmodes:
                opts.append((QPrinter.DuplexLongSide, _t("Uzun kenardan çevir")))
            if QPrinter.DuplexShortSide in dmodes:
                opts.append((QPrinter.DuplexShortSide, _t("Kısa kenardan çevir")))
            for mode, text in opts:
                self.cmb_duplex.addItem(text, mode)
            many = len(opts) > 1
            self.cmb_duplex.setVisible(many)
            self.lb_duplex.setVisible(many)
        finally:
            self.cmb_paper.blockSignals(False)
            self.cmb_duplex.blockSignals(False)
        self.btn_print.setEnabled(info is not None)

    def _make_printer(self):
        """Secilen yazici + kagit + renk + kopya + cift taraf ile kurulmus QPrinter (yon: Otomatik'te
        yazicinin dik kagidi; sayfalar plan() ile gerekirse yan yatirilir)."""
        pr = self._qprinter()
        pr.setDocName(self.doc_name or "Revora")
        pid = self.cmb_paper.currentData()
        if pid is not None:
            pr.setPageSize(QPageSize(pid))
        o = self.orient()
        pr.setPageOrientation(QPageLayout.Landscape if o == "landscape" else QPageLayout.Portrait)
        pr.setColorMode(QPrinter.GrayScale if self.gray() else QPrinter.Color)
        d = self.cmb_duplex.currentData()
        if d is not None:
            pr.setDuplex(d)
        pr.setCopyCount(self.spin_copies.value())
        pr.setCollateCopies(self.chk_collate.isChecked())
        return pr

    # ---- secimler
    def orient(self):
        return ("auto", "portrait", "landscape")[max(0, self.seg_orient.index())]

    def fit(self):
        return self.seg_scale.index() != 1

    def gray(self):
        return self.seg_color.index() == 1

    def _pages_mode(self, idx):
        on = idx == 2
        self.txt_range.setEnabled(on)
        if on:
            self.txt_range.setFocus()
        self._refresh()

    def _selected_pages(self):
        i = self.seg_pages.index()
        if i == 0:
            return list(range(self.count))
        if i == 1:
            return [self.current]
        return dialogs.parse_page_range(self.txt_range.text(), self.count)

    def paper_geometry(self):
        """(kagit_g, kagit_y, (sol, ust, sag, alt)) punto - yazicinin DIK kagidi ve basilamayan pay.
        Yazici ayrintilari henuz yuklenmediyse A4, paysiz (acilistaki ilk an). Yon plan()'da."""
        pid = self.cmb_paper.currentData()
        if self._loaded is None or pid is None:
            ps = QPageSize(QPageSize.A4).size(QPageSize.Point)
            return ps.width(), ps.height(), (0.0, 0.0, 0.0, 0.0)
        key = (self._loaded, pid)
        g = self._geo.get(key)
        if g is None:
            pr = self._qprinter()
            pr.setPageSize(QPageSize(pid))
            pr.setPageOrientation(QPageLayout.Portrait)
            lay = pr.pageLayout()
            full = lay.fullRect(QPageLayout.Point)
            paint = lay.paintRect(QPageLayout.Point)
            m = (paint.left() - full.left(), paint.top() - full.top(), full.right() - paint.right(),
                 full.bottom() - paint.bottom())
            g = (full.width(), full.height(), tuple(max(0.0, x) for x in m))
            self._geo[key] = g
        return g

    def _refresh(self):
        try:
            pages = self._selected_pages()
            bad = False
        except ValueError:
            pages, bad = [], True
        self.txt_range.setProperty("bad", bool(bad and self.txt_range.text().strip()))
        self.txt_range.style().unpolish(self.txt_range)
        self.txt_range.style().polish(self.txt_range)
        self._pages_now = pages
        pw, ph, m = self.paper_geometry()
        o, fit = self.orient(), self.fit()
        specs = []
        for pno in pages:
            r = self.doc[pno].rect
            specs.append((pno, plan(r.width, r.height, pw, ph, m, o, fit)))
        self.preview.set_specs(specs, self.gray())
        self._refresh_total()

    def _refresh_total(self, *_):
        n = len(getattr(self, "_pages_now", []))
        c = self.spin_copies.value()
        self.chk_collate.setEnabled(c > 1)
        sides = 2 if self.cmb_duplex.currentData() not in (None, QPrinter.DuplexNone) else 1
        sheets = math.ceil(n / sides) * c
        self.lb_total.setText(_t("{n} sayfa · {k} kâğıt", n=n * c, k=sheets) if n else
                              _t("Sayfa aralığı geçersiz. Örnek: 1-3, 5"))
        self.btn_print.setEnabled(bool(n) and self._info() is not None)

    # ---- sonuc
    def _accept(self):
        try:
            self._pages = self._selected_pages()
        except ValueError:
            self._pages = []
        if not self._pages:
            QMessageBox.warning(self, _t("Uyarı"), _t("Sayfa aralığı geçersiz. Örnek: 1-3, 5"))
            return
        self._printer = self._make_printer()
        self.accept()

    def _system(self):
        """Windows'un yazici penceresi (surucu ayarlari): bu pencerenin secimleriyle onceden doldurulur."""
        self._printer = self._make_printer()
        try:
            self._pages = self._selected_pages()
        except ValueError:
            self._pages = list(range(self.count))
        self.use_system = True
        self.accept()

    def printer(self):
        return self._printer

    def pages(self):
        return list(self._pages)

    def options(self):
        return {"orient": self.orient(), "fit": self.fit(), "gray": self.gray(),
                "copies": self.spin_copies.value(), "collate": self.chk_collate.isChecked()}


def print_pages(doc, printer, pages, opts, progress=None):
    """Sayfalari yaziciya ciz (plan() ile; onizlemeyle ayni yerlesim). Dondurur: basilan sayfa sayisi
    (kopyalar dahil degil) ya da None (yazici baslatilamadi). progress(i, n) -> False: iptal.
    Kopyalar: surucu kopya basabiliyorsa ona birakilir (setCopyCount), yoksa sayfalar elle tekrarlanir."""
    orient, fit, gray = opts.get("orient", "auto"), opts.get("fit", True), opts.get("gray", False)
    copies = max(1, int(opts.get("copies", 1)))
    seq = list(pages)
    if copies > 1 and not printer.supportsMultipleCopies():
        printer.setCopyCount(1)
        if opts.get("collate", True):
            seq = seq * copies
        else:
            seq = [p for p in seq for _ in range(copies)]
    painter = QPainter()
    if not painter.begin(printer):
        return None
    dpi = max(72, min(printer.resolution(), 300))           # 300 dpi yeter; bellek sisirmesin
    done = 0
    try:
        lay = printer.pageLayout()
        for i, pno in enumerate(seq):
            if progress is not None and progress(i, len(seq)) is False:
                break
            if i and not printer.newPage():
                break
            page = doc[pno]
            vp = painter.viewport()                           # basilabilir alan (yazici pikseli)
            full = lay.fullRect(QPageLayout.Point)
            paint = lay.paintRect(QPageLayout.Point)
            m = (paint.left() - full.left(), paint.top() - full.top(), full.right() - paint.right(),
                 full.bottom() - paint.bottom())
            # kagit yazicida zaten secilen yonde: plan'a "sabit yon" diye o kagidi ver
            o = orient if orient == "auto" else ("landscape" if full.width() > full.height() else "portrait")
            pw, ph, area, tgt, turn = plan(page.rect.width, page.rect.height, full.width(), full.height(),
                                           tuple(max(0.0, x) for x in m), o, fit)
            px_per_pt = vp.width() / max(1.0, paint.width())
            if turn:
                # dik duzlemdeki hedef -> yazici duzlemi, saat yonunde 90 derece: alan icinde
                # (x, y, gen, yuk) -> (alan_yuk - y - yuk, x, yuk, gen)  (alan_yuk: dik alanin yuksekligi)
                x0 = (tgt.x() - area.x()) * px_per_pt
                y0 = (tgt.y() - area.y()) * px_per_pt
                w_, h_ = tgt.width() * px_per_pt, tgt.height() * px_per_pt
                ah = area.height() * px_per_pt
                rect = QRectF(vp.x() + (ah - y0 - h_), vp.y() + x0, h_, w_)
                img = render(page, max(1, round(w_ * dpi / printer.resolution())),
                             max(1, round(h_ * dpi / printer.resolution())), gray, rotate=True)
            else:
                rect = QRectF(vp.x() + (tgt.x() - area.x()) * px_per_pt, vp.y() + (tgt.y() - area.y()) * px_per_pt,
                              tgt.width() * px_per_pt, tgt.height() * px_per_pt)
                img = render(page, max(1, round(rect.width() * dpi / printer.resolution())),
                             max(1, round(rect.height() * dpi / printer.resolution())), gray)
            painter.save()
            painter.setClipRect(vp)
            painter.drawImage(rect, img)
            painter.restore()
            done += 1
    finally:
        painter.end()
    return done
