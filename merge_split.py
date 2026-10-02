"""
merge_split.py
--------------
PDF Birleştir ve PDF Ayır pencereleri. Metin/cizim duzenleme kodundan
bagimsizdir. Renkler uygulamanin paletinden (acik/koyu tema) okunur; ana
penceredeki #primary / #toolbtn buton stilleri burada da gecerlidir.
"""
import os
import subprocess

# import sirasi kurali: PySide6 fitz'ten once
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QFileDialog, QMessageBox, QAbstractItemView, QWidget, QScrollArea, QFrame, QSizePolicy,
    QStyledItemDelegate, QStyle, QStackedWidget, QAbstractButton, QApplication
)
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QPen, QPalette, QFont, QFontMetrics
from PySide6.QtCore import Qt, QSize, QRectF, QPointF, Signal
import fitz
from reorder_view import ReorderView
from i18n import _t

try:
    import qtawesome as qta
except Exception:
    qta = None

DANGER = "#e5484d"
PART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#14b8a6"]


# ---------------------------------------------------------------- yardimcilar
def _pal():
    return QApplication.palette()


def _color(role):
    return _pal().color(role)


def _icon(name, color):
    if qta is None:
        return None
    try:
        return qta.icon(name, color=QColor(color).name())
    except Exception:
        return None


def _btn(text, icon=None, obj=None, tip=None):
    b = QPushButton(text)
    if obj:
        b.setObjectName(obj)
    if icon is not None:
        b.setIcon(icon)
    if tip:
        b.setToolTip(tip)
    b.setCursor(Qt.PointingHandCursor)
    return b


def _muted_label(text=""):
    l = QLabel(text)
    l.setStyleSheet(f"color: {_color(QPalette.PlaceholderText).name()};")
    return l


def _header(title, subtitle):
    w = QWidget()
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(3)
    t = QLabel(title)
    t.setStyleSheet("font-size: 15pt; font-weight: 600;")
    s = _muted_label(subtitle)
    s.setWordWrap(True)
    v.addWidget(t)
    v.addWidget(s)
    return w


def _separator():
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background: {_color(QPalette.Midlight).name()};")
    return line


def _fmt_size(n):
    if n < 1024 * 1024:
        return f"{max(1, round(n / 1024))} KB"
    return f"{n / 1024 / 1024:.1f} MB".replace(".", ",")


def _pdf_paths(mime):
    return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(".pdf")]


def render_page_pixmap(doc, index, height, dpr=1.0):
    """Sayfanin kucuk resmi (yuksek DPI ekranda net olsun diye dpr ile)."""
    page = doc[index]
    zoom = height * dpr / page.rect.height
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888).copy()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def make_stack_pixmap(thumb, page_count, offset=5):
    """Cok sayfali dosyalar icin arkada 'yigin' efekti (arka kartlar gercek
    sayfanin soluk kopyasi)."""
    d = thumb.devicePixelRatio()
    t = QPixmap(thumb)
    t.setDevicePixelRatio(1.0)            # cizerken piksel piksel
    w, h = t.width(), t.height()
    o = round(offset * d)
    canvas = QPixmap(w + o, h + o)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    edge = QColor(150, 150, 150)
    if page_count > 1:
        if page_count > 2:
            p.setOpacity(0.35)
            p.drawPixmap(o // 2, o // 2, t)
            p.setOpacity(1.0)
            p.setPen(QPen(edge.lighter(125)))
            p.drawRect(o // 2, o // 2, w - 1, h - 1)
        p.setOpacity(0.6)
        p.drawPixmap(o, 0, t)
        p.setOpacity(1.0)
        p.setPen(QPen(edge.lighter(115)))
        p.drawRect(o, 0, w - 1, h - 1)
    p.drawPixmap(0, o, t)
    p.setPen(QPen(edge))
    p.drawRect(0, o, w - 1, h - 1)
    p.end()
    canvas.setDevicePixelRatio(d)
    return canvas


def reveal(path):
    """Dosyayi (secili olarak) ya da klasoru Gezgin'de gosterir."""
    try:
        if os.path.isdir(path):
            os.startfile(path)
        else:
            subprocess.Popen(f'explorer /select,"{os.path.normpath(path)}"')
    except Exception:
        pass


def done_box(parent, title, text, reveal_path):
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Information)
    box.setText(text)
    show = box.addButton(_t("Klasörde göster"), QMessageBox.ActionRole)
    box.addButton(_t("Tamam"), QMessageBox.AcceptRole)
    box.exec()
    if box.clickedButton() is show:
        reveal(reveal_path)


class DropZone(QFrame):
    """Bos durum: 'buraya surukleyin ya da secin' alani."""
    filesDropped = Signal(list)
    clicked = Signal()

    def __init__(self, title, subtitle, button_text, multi=True, exts=(".pdf",), icon="fa5s.file-pdf"):
        super().__init__()
        self.multi = multi
        self.exts = tuple(exts)            # kabul edilen dosya turleri (resimlerden PDF: resimler)
        self.setObjectName("dropzone")
        self.setAcceptDrops(True)
        self.setMinimumHeight(230)
        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(10)
        ic = _icon(icon, _color(QPalette.Highlight))
        if ic is not None:
            lab = QLabel()
            lab.setPixmap(ic.pixmap(46, 46))
            lab.setAlignment(Qt.AlignCenter)
            v.addWidget(lab)
        t = QLabel(title)
        t.setAlignment(Qt.AlignCenter)
        t.setStyleSheet("font-size: 12pt; font-weight: 600;")
        v.addWidget(t)
        s = _muted_label(subtitle)
        s.setAlignment(Qt.AlignCenter)
        v.addWidget(s)
        b = _btn(button_text, _icon("fa5s.folder-open", "#ffffff"), "primary")
        b.clicked.connect(self.clicked)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(b)
        row.addStretch()
        v.addSpacing(4)
        v.addLayout(row)
        self._hot(False)

    def _hot(self, on):
        acc = _color(QPalette.Highlight)
        border = acc if on else _color(QPalette.Mid)
        a = 30 if on else 0
        self.setStyleSheet(
            f"QFrame#dropzone {{ border: 2px dashed {border.name()}; border-radius: 12px;"
            f" background: rgba({acc.red()}, {acc.green()}, {acc.blue()}, {a}); }}")

    def _paths(self, mime):
        return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(self.exts)]

    def dragEnterEvent(self, e):
        if self._paths(e.mimeData()):
            e.acceptProposedAction()
            self._hot(True)

    def dragLeaveEvent(self, e):
        self._hot(False)

    def dropEvent(self, e):
        self._hot(False)
        paths = self._paths(e.mimeData())
        if paths:
            self.filesDropped.emit(paths if self.multi else paths[:1])
            e.acceptProposedAction()


# ---------------------------------------------------------------- PDF Birlestir
def paint_merge_card(p, r, item, info):
    """ReorderView icin dosya karti: sira rozeti (birlesik dosyadaki yeri; surukleme
    sirasinda canli guncellenir), kucuk resim, ad, sayfa/boyut, surukleme tutamaci.
    item: {"path", "name", "thumb", "pages", "size"}"""
    p.save()
    pal = _pal()
    acc = pal.color(QPalette.Highlight)
    sel, hov, lifted = info["selected"], info["hover"], info["lifted"]
    r = QRectF(r)
    p.setPen(QPen(acc if sel else pal.color(QPalette.Mid if hov else QPalette.Midlight),
                  1.5 if sel else 1.0))
    p.setBrush(pal.color(QPalette.AlternateBase))   # acikta beyaz, koyuda zeminden bir ton acik
    p.drawRoundedRect(r, 10, 10)
    if sel or hov:
        tint = QColor(acc)
        tint.setAlpha(22 if lifted else (40 if sel else 14))
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(r, 10, 10)

    b = QRectF(r.left() + 14, r.center().y() - 12, 24, 24)
    p.setPen(Qt.NoPen)
    p.setBrush(acc)
    p.drawEllipse(b)
    f = QFont(p.font())
    f.setBold(True)
    p.setFont(f)
    p.setPen(pal.color(QPalette.HighlightedText))
    p.drawText(b, Qt.AlignCenter, str(info["number"]))

    x = b.right() + 14
    pm = item.get("thumb")
    if isinstance(pm, QPixmap) and not pm.isNull():
        sz = pm.deviceIndependentSize()
        p.drawPixmap(QPointF(x, r.center().y() - sz.height() / 2), pm)
        x += sz.width() + 14

    right = r.right() - 34
    fm = QFontMetrics(f)
    p.setPen(pal.color(QPalette.Text))
    tr = QRectF(x, r.center().y() - 20, max(10, right - x), 20)
    p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter,
               fm.elidedText(item.get("name", ""), Qt.ElideMiddle, int(tr.width())))
    f.setBold(False)
    p.setFont(f)
    p.setPen(pal.color(QPalette.PlaceholderText))
    p.drawText(QRectF(x, r.center().y() + 1, tr.width(), 20), Qt.AlignLeft | Qt.AlignVCenter,
               item.get("info") or _t("{n} sayfa · {size}", n=item.get('pages'), size=item.get('size')))

    p.setPen(Qt.NoPen)                     # surukleme tutamaci (2x3 nokta)
    p.setBrush(acc if lifted else pal.color(QPalette.PlaceholderText))
    gx, gy = r.right() - 22, r.center().y() - 8
    for row in range(3):
        for col in range(2):
            p.drawEllipse(QPointF(gx + col * 6, gy + row * 8), 1.6, 1.6)
    p.restore()


class MergeDialog(QDialog):
    """Birden fazla PDF'i, kullanicinin belirledigi sirayla tek dosyada birlestirir."""

    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle(_t("PDF Birleştir"))
        self.resize(660, 580)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(14)
        v.addWidget(_header(_t("PDF Birleştir"),
                            _t("Dosyaları ekleyin ve sürükleyerek sıralayın. Listede üstte olan, "
                            "birleşik dosyada önce gelir.")))

        self.stack = QStackedWidget()
        self.zone = DropZone(_t("PDF dosyalarını buraya sürükleyin"),
                             _t("ya da bilgisayarınızdan seçin (birden fazla seçebilirsiniz)"),
                             _t("Dosya ekle"))
        self.zone.clicked.connect(self.add_files)
        self.zone.filesDropped.connect(self.add_paths)
        # iOS tarzi siralama: tutulan kart kalkar, birakilacak yerde bosluk acilir
        self.view = ReorderView(80, paint_merge_card, spacing=8, margin=3, accept_files=True)
        self.view.filesDropped.connect(self.add_paths)
        self.view.deleteRequested.connect(self.remove_selected)
        self.view.currentChanged.connect(lambda _: self._update())
        self.view.moved.connect(lambda *_: self._update())
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget { background: transparent;"
                                       " border: none; }")
        self.list_scroll.setWidget(self.view)
        self.stack.addWidget(self.zone)
        self.stack.addWidget(self.list_scroll)
        v.addWidget(self.stack, 1)

        txt = _color(QPalette.WindowText)
        self.toolbar = QWidget()
        tb = QHBoxLayout(self.toolbar)
        tb.setContentsMargins(0, 0, 0, 0)
        tb.setSpacing(4)
        self.btn_add = _btn(_t("Dosya ekle"), _icon("fa5s.plus", txt))
        self.btn_up = _btn("", _icon("fa5s.arrow-up", txt), "toolbtn", _t("Yukarı taşı"))
        self.btn_down = _btn("", _icon("fa5s.arrow-down", txt), "toolbtn", _t("Aşağı taşı"))
        self.btn_remove = _btn("", _icon("fa5s.trash-alt", DANGER), "toolbtn", _t("Listeden kaldır (Delete)"))
        for b, fallback in ((self.btn_up, "▲"), (self.btn_down, "▼"), (self.btn_remove, _t("Kaldır"))):
            if b.icon().isNull():
                b.setText(fallback)
        self.btn_add.clicked.connect(self.add_files)
        self.btn_up.clicked.connect(lambda: self.move_item(-1))
        self.btn_down.clicked.connect(lambda: self.move_item(1))
        self.btn_remove.clicked.connect(self.remove_selected)
        tb.addWidget(self.btn_add)
        tb.addStretch()
        tb.addWidget(self.btn_up)
        tb.addWidget(self.btn_down)
        tb.addWidget(self.btn_remove)
        v.addWidget(self.toolbar)

        v.addWidget(_separator())
        ft = QHBoxLayout()
        self.lbl_sum = _muted_label()
        ft.addWidget(self.lbl_sum)
        ft.addStretch()
        cancel = _btn(_t("Vazgeç"))
        cancel.clicked.connect(self.reject)
        self.btn_merge = _btn(_t("Birleştir ve kaydet"), _icon("fa5s.object-group", "#ffffff"), "primary")
        self.btn_merge.clicked.connect(self.do_merge)
        ft.addWidget(cancel)
        ft.addWidget(self.btn_merge)
        v.addLayout(ft)

        if initial and os.path.isfile(initial):
            self.add_paths([initial])
        self._update()

    # ---- liste ----
    def add_files(self):
        start = os.path.dirname(self._path(0)) if self.view.count() else ""
        paths, _ = QFileDialog.getOpenFileNames(self, _t("PDF Ekle"), start, _t("PDF Dosyaları (*.pdf)"))
        if paths:
            self.add_paths(paths)

    def add_paths(self, paths):
        skipped = []
        dpr = self.devicePixelRatioF()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for path in paths:
                name = os.path.splitext(os.path.basename(path))[0]
                try:
                    doc = fitz.open(path)
                except Exception:
                    skipped.append(_t("{name} (açılamadı)", name=name))
                    continue
                try:
                    if doc.needs_pass:
                        skipped.append(_t("{name} (parola korumalı)", name=name))
                        continue
                    n = len(doc)
                    thumb = make_stack_pixmap(render_page_pixmap(doc, 0, 58, dpr), n)
                finally:
                    doc.close()
                self.view.add_item({"path": path, "name": name, "thumb": thumb, "pages": n,
                                    "size": _fmt_size(os.path.getsize(path))})
        finally:
            QApplication.restoreOverrideCursor()
        self._update()
        if skipped:
            QMessageBox.warning(self, _t("Eklenemedi"), _t("Şu dosyalar eklenemedi:\n\n") + "\n".join(skipped))

    def move_item(self, direction):
        row = self.view.current
        new_row = row + direction
        if row < 0 or not (0 <= new_row < self.view.count()):
            return
        self.view.move(row, new_row)          # kart yeni yerine kayarak gider
        self.view.ensure_visible(new_row)
        self._update()

    def remove_selected(self):
        if self.view.current >= 0:
            self.view.remove(self.view.current)
            self._update()

    def _path(self, i):
        return self.view.item(i)["path"]

    def _update(self):
        n = self.view.count()
        self.stack.setCurrentIndex(1 if n else 0)
        self.toolbar.setVisible(n > 0)   # bos durumda ortadaki alan yeterli
        row = self.view.current
        self.btn_up.setEnabled(row > 0)
        self.btn_down.setEnabled(0 <= row < n - 1)
        self.btn_remove.setEnabled(row >= 0)
        self.btn_merge.setEnabled(n >= 2)
        if n == 0:
            self.lbl_sum.setText("")
        elif n == 1:
            self.lbl_sum.setText(_t("Birleştirmek için en az bir PDF daha ekleyin."))
        else:
            pages = sum(self.view.item(i)["pages"] for i in range(n))
            self.lbl_sum.setText(_t("{n} dosya · toplam {pages} sayfa", n=n, pages=pages))

    # ---- birlestir ----
    def do_merge(self):
        count = self.view.count()
        if count < 2:
            return
        start = os.path.join(os.path.dirname(self._path(0)), "birlesik.pdf")
        out_path, _ = QFileDialog.getSaveFileName(self, _t("Birleştirilmiş PDF'i Kaydet"), start,
                                                  _t("PDF Dosyaları (*.pdf)"))
        if not out_path:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            merged = fitz.open()
            for i in range(count):
                src = fitz.open(self._path(i))
                merged.insert_pdf(src)
                src.close()
            merged.save(out_path, garbage=3, deflate=True)
            total = len(merged)
            merged.close()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _t("Hata"), _t("Birleştirme sırasında hata oluştu:\n{e}", e=e))
            return
        QApplication.restoreOverrideCursor()
        done_box(self, _t("Birleştirildi"),
                 _t("{n} dosya birleştirildi ({total} sayfa):\n{path}", n=count, total=total, path=out_path), out_path)
        self.accept()


# ---------------------------------------------------------------- PDF Ayir
class DividerButton(QAbstractButton):
    """Iki sayfa arasindaki kesim noktasi.
    Secili degil: gri kesikli cizgi + gri makas. Uzerine gelince: mavi.
    Secili: dolu mavi cizgi, mavi makas, hafif mavi zemin."""

    def __init__(self, gap_index, toggle_callback):
        super().__init__()
        self.gap_index = gap_index
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(_t("Burada kes"))
        self.setFixedWidth(34)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._hover = False
        self._ic_off = _icon("fa5s.cut", _color(QPalette.PlaceholderText))
        self._ic_on = _icon("fa5s.cut", _color(QPalette.Highlight))
        self.toggled.connect(lambda checked: toggle_callback(gap_index, checked))

    def sizeHint(self):
        return QSize(34, 140)

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = _pal()
        acc = pal.color(QPalette.Highlight)
        on, hot = self.isChecked(), self._hover
        r = QRectF(self.rect()).adjusted(3, 2, -3, -2)
        tint = QColor(acc)
        tint.setAlpha(44 if on else 22)
        if on or hot:
            p.setPen(Qt.NoPen)
            p.setBrush(tint)
            p.drawRoundedRect(r, 9, 9)
        cx = r.center().x()
        pen = QPen(acc if (on or hot) else pal.color(QPalette.Mid), 2.5 if on else 1.5)
        pen.setStyle(Qt.SolidLine if on else Qt.DashLine)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(cx, r.top() + 8), QPointF(cx, r.bottom() - 8))
        # makasin arkasi: cizgi ikonun ustunden gecmesin
        s = 16
        disc = QRectF(cx - s / 2 - 4, r.center().y() - s / 2 - 4, s + 8, s + 8)
        p.setPen(Qt.NoPen)
        p.setBrush(pal.color(QPalette.Window))
        p.drawEllipse(disc)
        if on or hot:
            p.setBrush(tint)
            p.drawEllipse(disc)
        icon = self._ic_on if (on or hot) else self._ic_off
        if icon is not None:
            p.drawPixmap(QPointF(cx - s / 2, r.center().y() - s / 2), icon.pixmap(s, s))
        else:
            p.setPen(acc if (on or hot) else pal.color(QPalette.PlaceholderText))
            p.drawText(disc, Qt.AlignCenter, "✂")
        p.end()


class PageThumb(QWidget):
    """Ayir penceresindeki sayfa: kucuk resim, hangi parcaya dustugunu gosteren
    renkli serit ve sayfa numarasi."""

    def __init__(self, pixmap, page_num):
        super().__init__()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 2)
        v.setSpacing(6)
        size = pixmap.deviceIndependentSize().toSize()
        img = QLabel()
        img.setPixmap(pixmap)
        img.setFixedSize(size + QSize(2, 2))
        img.setAlignment(Qt.AlignCenter)
        img.setStyleSheet(f"border: 1px solid {_color(QPalette.Mid).name()}; background: white;")
        v.addWidget(img)
        self.bar = QFrame()
        self.bar.setFixedSize(size.width() + 2, 4)
        v.addWidget(self.bar)
        num = _muted_label(str(page_num))
        num.setAlignment(Qt.AlignCenter)
        v.addWidget(num)

    def set_part(self, k):
        self.bar.setStyleSheet(f"background: {PART_COLORS[k % len(PART_COLORS)]}; border-radius: 2px;")


class SplitDialog(QDialog):
    """Tek bir PDF'i, sayfalari yan yana gorup istenilen yerlerden (birden fazla
    olabilir) kesip birden cok dosyaya boler."""

    THUMB_HEIGHT = 150

    def __init__(self, parent=None, initial=None):
        super().__init__(parent)
        self.setWindowTitle(_t("PDF Ayır"))
        self.resize(900, 560)
        self.src_path = None
        self.page_count = 0
        self.cuts = set()           # gap index'leri (sayfa i ile i+1 arasi = gap i)
        self.thumbs = []
        self.dividers = []

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(14)
        v.addWidget(_header(_t("PDF Ayır"),
                            _t("Sayfaların arasındaki makasa tıklayarak nereden bölüneceğini seçin. "
                            "Her parça ayrı bir PDF dosyası olur.")))

        self.stack = QStackedWidget()
        self.zone = DropZone(_t("Bölmek istediğiniz PDF'i buraya sürükleyin"),
                             _t("ya da bilgisayarınızdan seçin"), _t("PDF seç"), multi=False)
        self.zone.clicked.connect(self.choose_file)
        self.zone.filesDropped.connect(lambda ps: self.load(ps[0]))
        self.stack.addWidget(self.zone)
        self.stack.addWidget(self._build_content())
        v.addWidget(self.stack, 1)

        v.addWidget(_separator())
        ft = QHBoxLayout()
        self.lbl_sum = _muted_label()
        ft.addWidget(self.lbl_sum)
        ft.addStretch()
        cancel = _btn(_t("Vazgeç"))
        cancel.clicked.connect(self.reject)
        self.btn_split = _btn(_t("Böl ve kaydet"), _icon("fa5s.cut", "#ffffff"), "primary")
        self.btn_split.clicked.connect(self.do_split)
        ft.addWidget(cancel)
        ft.addWidget(self.btn_split)
        v.addLayout(ft)

        self.setAcceptDrops(True)
        if initial and os.path.isfile(initial):
            self.load(initial)
        self._update()

    def _build_content(self):
        txt = _color(QPalette.WindowText)
        w = QWidget()
        cv = QVBoxLayout(w)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(12)

        chip = QFrame()
        chip.setObjectName("filechip")
        chip.setStyleSheet(
            f"QFrame#filechip {{ border: 1px solid {_color(QPalette.Midlight).name()};"
            f" border-radius: 10px; background: {_color(QPalette.Base).name()}; }}")
        ch = QHBoxLayout(chip)
        ch.setContentsMargins(12, 8, 8, 8)
        ic = _icon("fa5s.file-pdf", _color(QPalette.Highlight))
        if ic is not None:
            il = QLabel()
            il.setPixmap(ic.pixmap(20, 20))
            ch.addWidget(il)
        self.lbl_file = QLabel("")
        self.lbl_file.setStyleSheet("font-weight: 600;")
        self.lbl_pages = _muted_label()
        ch.addWidget(self.lbl_file)
        ch.addWidget(self.lbl_pages)
        ch.addStretch()
        change = _btn(_t("Başka dosya"), _icon("fa5s.exchange-alt", txt), "toolbtn")
        change.clicked.connect(self.choose_file)
        ch.addWidget(change)
        cv.addWidget(chip)

        qa = QHBoxLayout()
        qa.setSpacing(6)
        self.btn_every = _btn(_t("Her sayfayı ayrı dosya yap"), _icon("fa5s.columns", txt))
        self.btn_clear = _btn(_t("Kesimleri temizle"), _icon("fa5s.eraser", txt))
        self.btn_every.clicked.connect(lambda: self._set_all(True))
        self.btn_clear.clicked.connect(lambda: self._set_all(False))
        qa.addWidget(self.btn_every)
        qa.addWidget(self.btn_clear)
        qa.addStretch()
        cv.addLayout(qa)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFixedHeight(self.THUMB_HEIGHT + 72)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.strip_widget = QWidget()
        self.strip_widget.setStyleSheet("background: transparent;")
        self.strip_layout = QHBoxLayout(self.strip_widget)
        self.strip_layout.setContentsMargins(2, 2, 2, 2)
        self.strip_layout.setSpacing(0)
        self.scroll.setWidget(self.strip_widget)
        cv.addWidget(self.scroll)

        self.lbl_parts = QLabel("")
        self.lbl_parts.setWordWrap(True)
        self.lbl_parts.setTextFormat(Qt.RichText)
        cv.addWidget(self.lbl_parts)
        cv.addStretch()
        return w

    # ---- dosya ----
    def dragEnterEvent(self, e):
        if _pdf_paths(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = _pdf_paths(e.mimeData())
        if paths:
            self.load(paths[0])

    def choose_file(self):
        start = os.path.dirname(self.src_path) if self.src_path else ""
        path, _ = QFileDialog.getOpenFileName(self, _t("PDF Seç"), start, _t("PDF Dosyaları (*.pdf)"))
        if path:
            self.load(path)

    def load(self, path):
        try:
            doc = fitz.open(path)
        except Exception as e:
            QMessageBox.critical(self, _t("Hata"), _t("Dosya açılamadı:\n{e}", e=e))
            return
        try:
            if doc.needs_pass:
                QMessageBox.warning(self, _t("Parola korumalı"), _t("Bu PDF parola korumalı; önce parolayı kaldırın."))
                return
            if len(doc) < 2:
                QMessageBox.warning(self, _t("Uyarı"), _t("Bu PDF sadece 1 sayfa, ayrılamaz."))
                return
            self.src_path = path
            self.page_count = len(doc)
            self.cuts = set()
            while self.strip_layout.count():
                child = self.strip_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.thumbs, self.dividers = [], []
            dpr = self.devicePixelRatioF()
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                for i in range(self.page_count):
                    th = PageThumb(render_page_pixmap(doc, i, self.THUMB_HEIGHT, dpr), i + 1)
                    self.thumbs.append(th)
                    self.strip_layout.addWidget(th)
                    if i < self.page_count - 1:
                        d = DividerButton(i, self.toggle_cut)
                        self.dividers.append(d)
                        self.strip_layout.addWidget(d)
                self.strip_layout.addStretch(1)   # az sayfada sola yaslansin
            finally:
                QApplication.restoreOverrideCursor()
        finally:
            doc.close()
        self.lbl_file.setText(os.path.basename(path))
        self.lbl_pages.setText(_t("· {n} sayfa · {size}", n=self.page_count, size=_fmt_size(os.path.getsize(path))))
        self.stack.setCurrentIndex(1)
        self._update()

    # ---- kesimler ----
    def toggle_cut(self, gap_index, checked):
        if checked:
            self.cuts.add(gap_index)
        else:
            self.cuts.discard(gap_index)
        self._update()

    def _set_all(self, on):
        for d in self.dividers:
            d.blockSignals(True)
            d.setChecked(on)
            d.blockSignals(False)
        self.cuts = set(range(self.page_count - 1)) if on else set()
        self._update()

    def _segments(self):
        gaps = sorted(self.cuts)
        bounds = [0] + [g + 1 for g in gaps] + [self.page_count]
        return [(bounds[i], bounds[i + 1] - 1) for i in range(len(bounds) - 1)]

    def _update(self):
        if not self.src_path:
            self.stack.setCurrentIndex(0)
            self.lbl_sum.setText("")
            self.btn_split.setEnabled(False)
            return
        segs = self._segments()
        for k, (a, b) in enumerate(segs):
            for i in range(a, b + 1):
                self.thumbs[i].set_part(k)
        self.btn_split.setEnabled(len(segs) >= 2)
        self.btn_clear.setEnabled(bool(self.cuts))
        self.btn_every.setEnabled(len(self.cuts) < self.page_count - 1)
        if len(segs) < 2:
            mut = _color(QPalette.PlaceholderText).name()
            self.lbl_parts.setText(f"<span style='color:{mut}'>"
                                   + _t("Henüz kesim yok — sayfaların arasındaki makasa tıklayın.") + "</span>")
            self.lbl_sum.setText(_t("{n} sayfa", n=self.page_count))
            return
        parts = []
        for k, (a, b) in enumerate(segs):
            col = PART_COLORS[k % len(PART_COLORS)]
            rng = _t("s. {a}", a=a + 1) if a == b else _t("s. {a}–{b}", a=a + 1, b=b + 1)
            parts.append(f"<span style='color:{col}'>■</span>&nbsp;<b>" + _t("{k}. parça", k=k + 1) + "</b>"
                         + "&nbsp;·&nbsp;" + _t("{rng} ({n} sayfa)", rng=rng, n=b - a + 1))
        self.lbl_parts.setText("&nbsp;&nbsp;&nbsp;&nbsp; ".join(parts))
        self.lbl_sum.setText(_t("{n} sayfa → {m} dosya", n=self.page_count, m=len(segs)))

    # ---- bol ----
    def do_split(self):
        segs = self._segments()
        if len(segs) < 2:
            return
        out_dir = QFileDialog.getExistingDirectory(self, _t("Kayıt klasörünü seçin"),
                                                   os.path.dirname(self.src_path))
        if not out_dir:
            return
        base = os.path.splitext(os.path.basename(self.src_path))[0]
        targets = [os.path.join(out_dir, f"{base}_{i}.pdf") for i in range(1, len(segs) + 1)]
        existing = [t for t in targets if os.path.exists(t)]
        if existing:
            r = QMessageBox.question(
                self, _t("Dosyalar zaten var"),
                _t("{n} dosya bu klasörde zaten var ve üzerine yazılacak:\n\n", n=len(existing))
                + "\n".join(os.path.basename(t) for t in existing[:6])
                + ("\n..." if len(existing) > 6 else "") + _t("\n\nDevam edilsin mi?"))
            if r != QMessageBox.Yes:
                return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            src = fitz.open(self.src_path)
            for (a, b), out_path in zip(segs, targets):
                part = fitz.open()
                part.insert_pdf(src, from_page=a, to_page=b)
                part.save(out_path, garbage=3, deflate=True)
                part.close()
            src.close()
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _t("Hata"), _t("Ayırma sırasında hata oluştu:\n{e}", e=e))
            return
        QApplication.restoreOverrideCursor()
        done_box(self, _t("Ayrıldı"),
                 _t("{n} dosya kaydedildi:\n\n", n=len(targets)) + "\n".join(os.path.basename(t) for t in targets)
                 + _t("\n\nKlasör: {path}", path=out_dir), out_dir)
        self.accept()
