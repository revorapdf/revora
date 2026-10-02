"""
dialogs.py
----------
Filigran ekleme, form doldurma ve OCR pencereleri. Motor (PDFEditor)
uzerinden calisir; tum islemler tek adimda geri alinabilir.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit, QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QColorDialog,
    QRadioButton, QButtonGroup, QDialogButtonBox, QScrollArea, QWidget, QMessageBox,
    QProgressDialog, QApplication
)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt, Signal

from font_resolver import FONT_DISPLAY_NAMES
from i18n import _t


def parse_page_range(text, page_count):
    """'1-3, 5, 8-' -> [0, 1, 2, 4, 7, 8, ...] (0 tabanli). Hatalida ValueError."""
    pages = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            a = int(a) if a.strip() else 1
            b = int(b) if b.strip() else page_count
        else:
            a = b = int(part)
        if a < 1 or b > page_count or a > b:
            raise ValueError(part)
        pages.extend(range(a - 1, b))
    if not pages:
        raise ValueError(text)
    return sorted(set(pages))


class PageScope(QWidget):
    """Tum sayfalar / bu sayfa / aralik secimi."""

    def __init__(self, current, count):
        super().__init__()
        self.current, self.count = current, count
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.r_all = QRadioButton(_t("Tüm sayfalar"))
        self.r_cur = QRadioButton(_t("Bu sayfa ({n})", n=current + 1))
        self.r_rng = QRadioButton(_t("Aralık:"))
        self.txt = QLineEdit()
        self.txt.setPlaceholderText(_t("ör. 1-3, 5"))
        self.txt.setMaximumWidth(110)
        self.r_all.setChecked(True)
        g = QButtonGroup(self)
        for r in (self.r_all, self.r_cur, self.r_rng):
            g.addButton(r)
            h.addWidget(r)
        h.addWidget(self.txt)
        h.addStretch()
        self.txt.textEdited.connect(lambda _: self.r_rng.setChecked(True))

    def pages(self):
        if self.r_all.isChecked():
            return list(range(self.count))
        if self.r_cur.isChecked():
            return [self.current]
        return parse_page_range(self.txt.text(), self.count)


class ColorButton(QPushButton):
    """Secili rengi kendi zemininde gosteren renk secme butonu."""
    changed = Signal(tuple)

    def __init__(self, rgb=(0, 0, 0)):
        super().__init__()
        self.rgb = rgb
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        c = QColor.fromRgbF(*self.rgb)
        fg = "#000" if c.lightnessF() > 0.55 else "#fff"
        self.setText(c.name().upper())
        self.setStyleSheet(f"QPushButton {{ background: {c.name()}; color: {fg}; }}")

    def set_rgb(self, rgb):
        self.rgb = tuple(rgb)
        self._paint()

    def _pick(self):
        c = QColorDialog.getColor(QColor.fromRgbF(*self.rgb), self, _t("Renk seç"))
        if c.isValid():
            self.set_rgb((c.redF(), c.greenF(), c.blueF()))
            self.changed.emit(self.rgb)


# ---------------------------------------------------------------- filigran
class WatermarkDialog(QDialog):
    def __init__(self, parent, engine, current_page):
        super().__init__(parent)
        self.setWindowTitle(_t("Filigran Ekle"))
        self.engine = engine
        self.resize(460, 0)
        v = QVBoxLayout(self)

        form = QFormLayout()
        self.txt = QTextEdit()
        self.txt.setPlainText("TASLAK")
        self.txt.setFixedHeight(60)
        form.addRow(_t("Metin"), self.txt)

        self.font = QComboBox()
        for name, key in FONT_DISPLAY_NAMES:
            self.font.addItem(name, key)
        self.font.setCurrentIndex(max(self.font.findData("Arial"), 0))
        self.bold = QCheckBox(_t("Kalın"))
        self.bold.setChecked(True)
        fr = QHBoxLayout()
        fr.addWidget(self.font, 1)
        fr.addWidget(self.bold)
        form.addRow(_t("Yazı tipi"), fr)

        self.size = QDoubleSpinBox()
        self.size.setRange(6, 400)
        self.size.setValue(72)
        self.angle = QSpinBox()
        self.angle.setRange(-180, 180)
        self.angle.setValue(45)
        self.angle.setSuffix("°")
        sr = QHBoxLayout()
        sr.addWidget(QLabel(_t("Boyut")))
        sr.addWidget(self.size)
        sr.addSpacing(12)
        sr.addWidget(QLabel(_t("Açı")))
        sr.addWidget(self.angle)
        form.addRow("", sr)

        self.color = ColorButton((0.85, 0.1, 0.1))
        self.opacity = QSpinBox()
        self.opacity.setRange(1, 100)
        self.opacity.setValue(20)
        self.opacity.setSuffix(" %")
        cr = QHBoxLayout()
        cr.addWidget(self.color, 1)
        cr.addWidget(QLabel(_t("Opaklık")))
        cr.addWidget(self.opacity)
        form.addRow(_t("Renk"), cr)

        self.front = QCheckBox(_t("İçeriğin önünde (kapalıysa arkasında; beyaz zeminli sayfalarda görünmeyebilir)"))
        self.front.setChecked(True)
        form.addRow("", self.front)
        self.scope = PageScope(current_page, engine.page_count())
        form.addRow(_t("Sayfalar"), self.scope)
        v.addLayout(form)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t("Filigranı ekle"))
        bb.button(QDialogButtonBox.Cancel).setText(_t("Vazgeç"))
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _apply(self):
        text = self.txt.toPlainText().strip("\n")
        if not text.strip():
            QMessageBox.warning(self, _t("Uyarı"), _t("Filigran metnini yazın."))
            return
        try:
            pages = self.scope.pages()
        except ValueError:
            QMessageBox.warning(self, _t("Uyarı"), _t("Sayfa aralığı geçersiz. Örnek: 1-3, 5"))
            return
        self.engine.add_watermark(
            text, pages, fontsize=self.size.value(), color=self.color.rgb,
            opacity=self.opacity.value() / 100, angle=self.angle.value(),
            font_hint=self.font.currentData(), bold=self.bold.isChecked(),
            overlay=self.front.isChecked())
        self.accept()


# ---------------------------------------------------------------- form
class FormDialog(QDialog):
    def __init__(self, parent, engine):
        super().__init__(parent)
        self.setWindowTitle(_t("Form Doldur"))
        self.engine = engine
        self.resize(520, 520)
        self.editors = {}
        v = QVBoxLayout(self)
        fields = engine.get_form_fields()
        v.addWidget(QLabel(_t("{n} form alanı bulundu. Değerleri girip \"Uygula\"ya basın "
                              "(geri alınabilir).", n=len(fields))))

        inner = QWidget()
        form = QFormLayout(inner)
        import fitz
        for f in fields:
            key = (f["page"], f["xref"])
            t = f["type"]
            if t in (fitz.PDF_WIDGET_TYPE_CHECKBOX, fitz.PDF_WIDGET_TYPE_RADIOBUTTON):
                w = QCheckBox()
                w.setChecked(f["value"] not in (None, "", "Off", False))
                getter = w.isChecked
            elif t in (fitz.PDF_WIDGET_TYPE_COMBOBOX, fitz.PDF_WIDGET_TYPE_LISTBOX):
                w = QComboBox()
                w.setEditable(t == fitz.PDF_WIDGET_TYPE_COMBOBOX)
                w.addItems([c if isinstance(c, str) else c[-1] for c in f["choices"]])
                if f["value"]:
                    w.setCurrentText(str(f["value"]))
                getter = w.currentText
            elif t == fitz.PDF_WIDGET_TYPE_TEXT:
                w = QLineEdit(str(f["value"] or ""))
                getter = w.text
            else:
                continue  # imza / buton alanlari doldurulmaz
            w.setEnabled(not f["readonly"])
            name = f["label"] or f["name"] or f"alan {f['xref']}"
            form.addRow(f"s.{f['page'] + 1} · {name}", w)
            self.editors[key] = (getter, f["value"])

        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(inner)
        v.addWidget(sc, 1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t("Uygula"))
        bb.button(QDialogButtonBox.Cancel).setText(_t("Vazgeç"))
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _apply(self):
        values = {}
        for key, (getter, old) in self.editors.items():
            val = getter()
            if isinstance(val, bool):
                if val != (old not in (None, "", "Off", False)):
                    values[key] = val
            elif str(val) != str(old or ""):
                values[key] = val
        self.engine.set_form_values(values)
        self.accept()


# ---------------------------------------------------------------- OCR
TESSERACT_HELP = (
    _t("OCR (taranmış sayfadaki yazıyı tanıma) için ücretsiz <b>Tesseract</b> "
    "programı gerekiyor ve bu bilgisayarda kurulu değil.<br><br>"
    "Kurulum:<br>"
    "1. <a href='https://github.com/UB-Mannheim/tesseract/wiki'>"
    "github.com/UB-Mannheim/tesseract/wiki</a> adresinden Windows kurulum "
    "dosyasını indirin.<br>"
    "2. Kurulumda <b>Additional language data</b> altından <b>Turkish</b>'i "
    "işaretleyin.<br>"
    "3. Kurulumdan sonra programı kapatıp yeniden açın.<br><br>"
    "Farklı bir klasöre kurduysanız <code>TESSDATA_PREFIX</code> ortam "
    "değişkenini <code>...\\Tesseract-OCR\\tessdata</code> olarak ayarlayın.")
)


def ensure_tesseract_env():
    """Tesseract varsayilan klasordeyse PyMuPDF'in bulabilmesi icin
    TESSDATA_PREFIX'i ayarlar."""
    import os
    if os.environ.get("TESSDATA_PREFIX"):
        return
    for base in (r"C:\Program Files\Tesseract-OCR", r"C:\Program Files (x86)\Tesseract-OCR",
                 os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR")):
        td = os.path.join(base, "tessdata")
        if os.path.isdir(td):
            os.environ["TESSDATA_PREFIX"] = td
            if base not in os.environ.get("PATH", ""):
                os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")
            return


class OcrDialog(QDialog):
    def __init__(self, parent, engine, current_page):
        super().__init__(parent)
        self.setWindowTitle(_t("OCR — Taranmış Sayfayı Metne Çevir"))
        self.engine = engine
        self.result_words = None
        v = QVBoxLayout(self)
        info = QLabel(
            _t("Taranmış (resim) sayfalardaki yazı tanınır ve sayfanın görünümü "
            "değişmeden altına <b>görünmez bir metin katmanı</b> eklenir. "
            "Böylece metin seçilebilir, aranabilir ve kopyalanabilir olur."))
        info.setWordWrap(True)
        v.addWidget(info)
        form = QFormLayout()
        self.lang = QComboBox()
        self.lang.addItem(_t("Türkçe + İngilizce"), "tur+eng")
        self.lang.addItem(_t("Türkçe"), "tur")
        self.lang.addItem(_t("İngilizce"), "eng")
        form.addRow(_t("Dil"), self.lang)
        self.dpi = QSpinBox()
        self.dpi.setRange(150, 600)
        self.dpi.setValue(300)
        self.dpi.setSuffix(" dpi")
        form.addRow(_t("Çözünürlük"), self.dpi)
        self.scope = PageScope(current_page, engine.page_count())
        self.scope.r_cur.setChecked(True)
        form.addRow(_t("Sayfalar"), self.scope)
        v.addLayout(form)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t("Tanımayı başlat"))
        bb.button(QDialogButtonBox.Cancel).setText(_t("Vazgeç"))
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _apply(self):
        try:
            pages = self.scope.pages()
        except ValueError:
            QMessageBox.warning(self, _t("Uyarı"), _t("Sayfa aralığı geçersiz. Örnek: 1-3, 5"))
            return
        prog = QProgressDialog(_t("Yazı tanınıyor..."), None, 0, len(pages), self)
        prog.setWindowModality(Qt.WindowModal)
        prog.setMinimumDuration(0)

        def step(i, n):
            prog.setValue(i)
            prog.setLabelText(_t("Sayfa {i} / {n} tanınıyor...", i=i + 1, n=n))
            QApplication.processEvents()

        try:
            self.result_words = self.engine.ocr_pages(
                pages, language=self.lang.currentData(), dpi=self.dpi.value(), progress=step)
        except Exception as e:
            prog.close()
            QMessageBox.critical(self, _t("OCR hatası"),
                                 _t("Tanıma başarısız oldu:\n{e}\n\nSeçilen dil paketi "
                                    "(ör. Türkçe) Tesseract'a kurulu olmayabilir.", e=e))
            return
        prog.setValue(len(pages))
        self.accept()
