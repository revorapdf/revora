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
    QProgressDialog, QApplication, QFrame, QSizePolicy
)
from PySide6.QtGui import QColor, QCursor, QPainter, QPen
from PySide6.QtCore import Qt, Signal, QCollator, QLocale, QSize, QEvent, QRectF

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


# arayuz dili -> Tesseract dil kodu (OCR penceresinde o dil varsayilan olur)
_UI_TO_OCR = {"tr": "tur", "en": "eng", "de": "deu", "fr": "fra", "es": "spa", "it": "ita",
              "pt": "por", "pl": "pol", "nl": "nld"}


def _ocr_names():
    """Tesseract dil kodu -> gorunen ad (arayuzun dilinde)."""
    return {"tur": _t("Türkçe"), "eng": _t("İngilizce"), "deu": _t("Almanca"), "fra": _t("Fransızca"),
            "spa": _t("İspanyolca"), "ita": _t("İtalyanca"), "por": _t("Portekizce"),
            "pol": _t("Lehçe"), "nld": _t("Felemenkçe")}


def ocr_installed():
    """Tesseract'ta KURULU dil paketlerinin kodlari (tessdata klasorundeki *.traineddata).
    Klasor okunamazsa bos liste."""
    import os
    try:
        td = os.environ.get("TESSDATA_PREFIX")
        if not td or not os.path.isdir(td):
            import fitz
            td = fitz.get_tessdata()
        ext = ".traineddata"
        return sorted(f[:-len(ext)] for f in os.listdir(td)
                      if f.endswith(ext) and f[:-len(ext)] not in ("osd", "equ"))
    except Exception:
        return []


def _ocr_ui(ui_lang=None):
    import i18n
    return _UI_TO_OCR.get((ui_lang or i18n.language()).split("-")[0], "eng")


def _ocr_have(installed=None):
    have, seen = [], set()
    for c in (ocr_installed() if installed is None else installed):
        if c not in seen:
            seen.add(c)
            have.append(c)
    return have


def ocr_choices(ui_lang=None, installed=None):
    """OCR penceresindeki dil secenekleri: [(gorunen ad, Tesseract dil dizgisi), ...].
    YALNIZ Tesseract'ta kurulu paketler (kurulu olmayani secmek tanimayi hata ile bitirir) ve,
    ikisi de kuruluysa, "arayuz dili + Ingilizce" birlesimi (karisik belgeler icin). Siralama:
    ekranda gorunen ada gore, arayuz dilinin alfabesiyle (Turkcede I / I ayri, Almancada o = o).
    Adi bilinmeyen paket kod adiyla gorunur. Hangisinin SECILI gelecegi ayri: bkz. ocr_default."""
    import i18n
    names = _ocr_names()
    ui = _ocr_ui(ui_lang)
    have = _ocr_have(installed)
    out = [(names.get(c, c), c) for c in have]
    if ui != "eng" and ui in have and "eng" in have:
        out.append((names[ui] + " + " + names["eng"], ui + "+eng"))
    coll = QCollator(QLocale((ui_lang or i18n.language()).replace("-", "_")))
    coll.setCaseSensitivity(Qt.CaseInsensitive)
    import functools
    out.sort(key=functools.cmp_to_key(lambda x, y: coll.compare(x[0], y[0]) or (x[1] > y[1]) - (x[1] < y[1])))
    return out


def ocr_default(ui_lang=None, installed=None):
    """Pencere acildiginda secili gelecek dil dizgisi (siralamadan bagimsiz): arayuz dili ve
    Ingilizce kuruluysa birlesimi; yalniz arayuz dili kuruluysa o; arayuz dilinin paketi yoksa
    Ingilizce; o da yoksa None (kullanici kurulu paketlerden secer)."""
    ui = _ocr_ui(ui_lang)
    have = _ocr_have(installed)
    if ui in have:
        return ui + "+eng" if ui != "eng" and "eng" in have else ui
    return "eng" if "eng" in have else None


def ocr_missing(ui_lang=None, installed=None):
    """Arayuz dilinin Tesseract paketi kurulu DEGILSE o dilin gorunen adi (pencerede uyari icin);
    kuruluysa None."""
    ui = _ocr_ui(ui_lang)
    return None if ui in _ocr_have(installed) else _ocr_names().get(ui, ui)


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
        choices = ocr_choices()
        for label, code in choices:
            self.lang.addItem(label, code)
        self.lang.setCurrentIndex(max(self.lang.findData(ocr_default()), 0))
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
        # arayuz dilinin paketi kurulu degilse (Almanca arayuz, Almanca paketi yok) acikca soyle:
        # yoksa kullanici neden kendi dilini listede goremedigini bilmez, Ingilizceyle tanitir
        missing = ocr_missing()
        self.note = None
        if not choices:
            self.note = QLabel(_t("Tesseract'ta kurulu dil paketi bulunamadı."))
        elif missing:
            self.note = QLabel(_t("Tesseract'ta {lang} dil paketi kurulu değil; bu dildeki belgelerde "
                                  "tanıma hatalı olabilir.", lang=missing))
        if self.note is not None:
            self.note.setWordWrap(True)
            v.addWidget(self.note)
        hint = QLabel(_t("Listede olmayan bir dil için Tesseract kurulumunu yeniden çalıştırıp "
                         "<b>Additional language data</b> altından o dili ekleyin."))
        hint.setObjectName("fieldLabel")
        hint.setWordWrap(True)
        v.addWidget(hint)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setEnabled(bool(choices))
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


# ---------------------------------------------------------------- parola
class PasswordDialog(QDialog):
    """Belgeye acma parolasi koy / degistir. Sonuc: self.password (bos olamaz)."""

    def __init__(self, parent, has_password=False):
        super().__init__(parent)
        self.setWindowTitle(_t("Parolayı değiştir") if has_password else _t("Parola koy"))
        self.password = None
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)
        info = QLabel(_t("Belge, yalnızca bu parolayı bilenler tarafından açılabilir. "
                         "Parola, belgeyi kaydettiğinizde geçerli olur."))
        info.setWordWrap(True)
        v.addWidget(info)
        form = QFormLayout()
        self.ed1, self.ed2 = QLineEdit(), QLineEdit()
        for e in (self.ed1, self.ed2):
            e.setEchoMode(QLineEdit.Password)
            e.setMinimumWidth(240)
        form.addRow(_t("Parola"), self.ed1)
        form.addRow(_t("Parola (tekrar)"), self.ed2)
        v.addLayout(form)
        self.chk_show = QCheckBox(_t("Parolayı göster"))
        self.chk_show.toggled.connect(lambda on: [e.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password)
                                                  for e in (self.ed1, self.ed2)])
        v.addWidget(self.chk_show)
        warn = QLabel(_t("Parolayı unutursanız belge AÇILAMAZ; kurtarmanın bir yolu yoktur."))
        warn.setObjectName("fieldLabel")
        warn.setWordWrap(True)
        v.addWidget(warn)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t("Parolayı ayarla"))
        bb.button(QDialogButtonBox.Cancel).setText(_t("Vazgeç"))
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def _apply(self):
        a, b = self.ed1.text(), self.ed2.text()
        if not a:
            QMessageBox.warning(self, _t("Uyarı"), _t("Bir parola yazın."))
            return
        if a != b:
            QMessageBox.warning(self, _t("Uyarı"), _t("İki parola aynı değil."))
            return
        self.password = a
        self.accept()


# ---------------------------------------------------------------- kucultme
class CompressDialog(QDialog):
    """Kucultme duzeyi sec. Sonuc: self.level ("light" / "medium" / "strong")."""

    LEVELS = (
        ("light", _t("Hafif"), _t("Resimlere dokunmaz; yalnızca dosyanın yapısını sıkıştırır. Kalite aynı kalır.")),
        ("medium", _t("Dengeli (önerilen)"), _t("Yüksek çözünürlüklü resimler 150 dpi'ye indirilir. "
                                                 "Ekranda ve yazıcıda iyi görünür.")),
        ("strong", _t("Güçlü"), _t("Resimler 96 dpi'ye indirilir. E-postayla göndermek için; "
                                    "yakınlaştırınca resimler bulanık görünür.")),
    )

    def __init__(self, parent, size_text=""):
        super().__init__(parent)
        self.setWindowTitle(_t("PDF sıkıştır"))
        self.level = "medium"
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(6)
        if size_text:
            head = QLabel(_t("Şu anki boyut: {size}", size=size_text))
            head.setObjectName("panelTitle")
            v.addWidget(head)
            v.addSpacing(6)
        self._group = QButtonGroup(self)
        for key, title, desc in self.LEVELS:
            rb = QRadioButton(title)
            rb.setChecked(key == self.level)
            rb.toggled.connect(lambda on, k=key: on and setattr(self, "level", k))
            self._group.addButton(rb)
            v.addWidget(rb)
            lab = QLabel(desc)
            lab.setObjectName("fieldLabel")
            lab.setWordWrap(True)
            lab.setContentsMargins(24, 0, 0, 6)
            v.addWidget(lab)
        note = QLabel(_t("Yazılar ve çizimler etkilenmez. Sıkıştırılmış belge seçeceğiniz adla kaydedilir; "
                         "açık kalan belge o olur ve geri alma geçmişi sıfırlanır."))
        note.setWordWrap(True)
        v.addSpacing(4)
        v.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t("Devam"))
        bb.button(QDialogButtonBox.Cancel).setText(_t("Vazgeç"))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.setMinimumWidth(440)


# ---------------------------------------------------------------- pencere yapi taslari
def _theme(key, default):
    """Gecerli temanin rengi (main.DARK); ana pencere yuklu degilse varsayilan."""
    import sys
    m = sys.modules.get("main") or sys.modules.get("__main__")
    try:
        return m.DARK[key]
    except Exception:
        return default


def section_label(text):
    lab = QLabel(text)
    lab.setObjectName("dlgSection")
    return lab


class FocusRing(QWidget):
    """KLAVYEYLE gezinirken odaktaki denetimin cevresinde ince halka (pencerenin ustunde, fareyi
    engellemeyen bir katman). Fareyle tiklayinca cikmaz: yalniz Tab / ok tuslariyla gelen odakta.
    Tek yerden: dugme, onay kutusu, bolmeli secim ve secim karti ayni gostergeyi alir (stil
    sayfasindaki ":focus" fare tiklamasinda da yanar ve secili / odakli ayrimini karistirir).
    owner: pencere. target_of(w): odaktaki denetim icin halkanin saracagi parca (ör. kartin tamami)."""

    KEYBOARD = (Qt.TabFocusReason, Qt.BacktabFocusReason, Qt.ShortcutFocusReason)

    def __init__(self, owner, target_of=None):
        super().__init__(owner)
        self._owner, self._target_of, self._target = owner, target_of, None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.hide()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.FocusIn and isinstance(obj, QWidget) and obj.window() is self._owner.window() \
                and obj is not self and self._owner.isAncestorOf(obj):
            if ev.reason() in self.KEYBOARD and not isinstance(obj, QLineEdit):
                self._show(obj)
            else:
                self.hide()
        elif t in (QEvent.FocusOut, QEvent.MouseButtonPress) and self.isVisible() and (
                obj is self._focus or t == QEvent.MouseButtonPress):
            self.hide()
        elif t in (QEvent.Resize, QEvent.Move) and self.isVisible() and obj is self._target:
            self._place()
        return False

    _focus = None

    def _show(self, w):
        self._focus = w
        self._target = (self._target_of(w) if self._target_of else None) or w
        self._place()
        self.show()
        self.raise_()

    def _place(self):
        t = self._target
        r = t.rect()
        if isinstance(t, (QCheckBox, QRadioButton)):          # (satiri degil, kutu + yazisini sar)
            r.setWidth(min(r.width(), t.sizeHint().width()))
        r = r.translated(t.mapTo(self._owner, t.rect().topLeft())).adjusted(-4, -3, 4, 3)
        self._radius = 13 if t.objectName() == "choiceCard" else 7     # (kartin kosesiyle es merkezli)
        self.setGeometry(r)

    _radius = 7

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(_theme("focus", "#5b9cf8")), 1.6))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), self._radius, self._radius)


class Segmented(QWidget):
    """Yan yana, biri secili dugmeler (bolmeli secim). buttons: secenek sirasiyla QPushButton.
    Hucreler ESIT genislikte: genislik yaziya gore degil, en uzun etiketin gerektirdigi kadar ve
    hepsinde ayni (kullanici 2026-10-13: "yazi boyuna gore hucreler buyuyup kuculuyor, duzensiz").
    En uzun etiket hangi dilde olursa olsun sigar; yer artarsa hucreler esit buyur."""

    changed = Signal(int)

    def __init__(self, labels, current=0):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.group = QButtonGroup(self)
        self.buttons = []
        for i, text in enumerate(labels):
            b = QPushButton(text)
            b.setObjectName("segL" if i == 0 else ("segR" if i == len(labels) - 1 else "segM"))
            b.setCheckable(True)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setChecked(i == current)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self.group.addButton(b, i)
            self.buttons.append(b)
            h.addWidget(b, 1)
        self.group.idClicked.connect(self.changed)
        self.equalize()

    def equalize(self):
        """Hucre genisligi = en genis etiketin istedigi (stil dolgusu dahil). -> o genislik"""
        for b in self.buttons:
            b.setMinimumWidth(0)
            b.ensurePolished()
        self.cell = max(b.sizeHint().width() for b in self.buttons) if self.buttons else 0
        for b in self.buttons:
            b.setMinimumWidth(self.cell)
        return self.cell

    def index(self):
        return self.group.checkedId()


class ChoiceCard(QFrame):
    """"Hangisi?" sorusunun bir secenegi: simge + baslik + tek satir aciklama, sagda secim isareti.
    Kartin HER yerine tiklanir. Yalniz bu secenege ait bir ayar varsa kartin icinde durur (add_inside)
    ve kart secili degilken pasiftir: ayarin neye ait oldugu ve su an gecerli olup olmadigi bir
    bakista gorulur."""

    def __init__(self, icon_name, title, desc):
        super().__init__()
        self.setObjectName("choiceCard")
        self.setAttribute(Qt.WA_Hover, True)
        self.setCursor(QCursor(Qt.PointingHandCursor))
        self._icon_name = icon_name
        self._inside = []
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(12)
        self.icon = QLabel()
        self.icon.setFixedSize(26, 26)
        self.icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top.addWidget(self.icon, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.title = QLabel(title)
        self.title.setObjectName("cardTitle")
        self.desc = QLabel(desc)
        self.desc.setObjectName("cardDesc")
        self.desc.setWordWrap(True)
        for lab in (self.title, self.desc):
            lab.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            col.addWidget(lab)
        top.addLayout(col, 1)
        self.radio = QRadioButton()                  # secim isareti + klavye (Tab, ok tuslari)
        self.radio.setCursor(QCursor(Qt.PointingHandCursor))
        # ekran okuyucu: isaretin yazisi yok, adi ve aciklamasi kartin basligi / aciklamasidir
        self.radio.setAccessibleName(title)
        self.radio.setAccessibleDescription(desc)
        self.setAccessibleName(title)
        top.addWidget(self.radio, 0, Qt.AlignVCenter)
        outer.addLayout(top)
        self._outer = outer
        self.radio.toggled.connect(self._sync)
        self._sync(False)

    def add_inside(self, widget):
        """Yalniz bu secenege ait ayar: aciklamanin altinda, kart secili degilken pasif."""
        row = QHBoxLayout()
        row.setContentsMargins(38, 0, 0, 0)          # (simge + bosluk: basligin hizasi)
        row.addWidget(widget)
        row.addStretch()
        self._outer.addLayout(row)
        self._inside.append(widget)
        widget.setEnabled(self.radio.isChecked())

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.radio.setChecked(True)
            self.radio.setFocus()
        super().mousePressEvent(ev)

    def _sync(self, on):
        for w in self._inside:
            w.setEnabled(on)
        for w in (self, self.title):
            w.setProperty("sel", "true" if on else "false")
            w.style().unpolish(w)
            w.style().polish(w)
        try:
            import qtawesome as qta
            col = _theme("accent", "#5b9cf8") if on else _theme("muted", "#8a8a8a")
            self.icon.setPixmap(qta.icon(self._icon_name, color=col).pixmap(QSize(26, 26)))
        except Exception:
            pass


class PageScopeBar(QWidget):
    """PageScope'un bolmeli dugmeli hali: Tum sayfalar | Bu sayfa (n) | Aralik + aralik kutusu.
    Kutu yalniz "Aralik" seciliyken etkin (pasifken soluk); secilince imlec kutuya gecer."""

    def __init__(self, current, count):
        super().__init__()
        self.current, self.count = current, count
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(10)
        self.seg = Segmented([_t("Tüm sayfalar"), _t("Bu sayfa ({n})", n=current + 1), _t("Aralık")])
        self.r_all, self.r_cur, self.r_rng = self.seg.buttons
        self.txt = QLineEdit()
        self.txt.setObjectName("scopeRange")
        self.txt.setPlaceholderText(_t("ör. 1-3, 5"))
        self.txt.setAccessibleName(_t("Aralık"))
        self.txt.setAccessibleDescription(_t("ör. 1-3, 5"))
        self.seg.setAccessibleName(_t("Sayfalar"))
        # DORT ESIT SUTUN: uc dugme + aralik kutusu ayni genislikte ve ayni boyda; satir pencerenin
        # icerik genisligini tam doldurur (saginda bosluk kalmaz, kartlarin kenarlariyla hizali).
        self.txt.setMinimumWidth(self.seg.cell)
        self.txt.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.txt.setFixedHeight(self.r_all.sizeHint().height())
        h.addWidget(self.seg, 3)
        h.addWidget(self.txt, 1)
        self.seg.group.buttonToggled.connect(self._sync)
        self._sync()

    def _sync(self, *_):
        on = self.r_rng.isChecked()
        self.txt.setEnabled(on)
        if on:
            self.txt.setFocus()

    def pages(self):
        if self.r_all.isChecked():
            return list(range(self.count))
        if self.r_cur.isChecked():
            return [self.current]
        return parse_page_range(self.txt.text(), self.count)


# ---------------------------------------------------------------- Excel'e aktar
class ExportExcelDialog(QDialog):
    """Excel'e aktarma secenekleri.
    Sonuc: pages(), whole_page, keep_layout, images, single_sheet, numbers, text_tables.

    Duzen (2026-10-13, kullanici: "sezgisel degil, karisik; gecersiz secenekler etkin gibi"):
    once ASIL karar - ne aktarilsin - uc buyuk kartla (mode: "page" / "layout" / "tables");
    sonra hangi sayfalar; en altta butun kiplerde ortak ayarlar. Yalniz bir kipe ait ayar o
    kartin icinde ("tablolar nereye" -> Yalnizca tablolar karti). O an gecerli olmayan her sey
    pasif ve soluk; pencere kip degisince boy degistirmez."""

    MODES = ("page", "layout", "tables")

    def __init__(self, parent, current_page, page_count):
        super().__init__(parent)
        self.setObjectName("ringDialog")             # (yerel odak cercevesi yerine FocusRing)
        self.setWindowTitle(_t("Excel'e aktar"))
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 18, 24, 18)
        v.setSpacing(8)

        # Ilk iki secenek de SAYFANIN TAMAMINI aktarir, ikisinde de hucreler duzenlenebilir; fark
        # yerlesimde. Basliklar farki, aciklamalar ortak yani soyler ("Sayfanin tamami; ...").
        v.addWidget(section_label(_t("Aktarım biçimi")))
        self.card_page = ChoiceCard(
            "mdi6.text-box-outline", _t("Okunaklı yerleşim"),
            _t("Sayfanın tamamı; içerik rahat okunan, düzenlenebilir hücrelere yerleşir."))
        # PDF yerlesimi: sutun / satir olculeri, yazi boyutlari ve baski ayarlari PDF'ten alinir
        # (pdf_tables.page_layout). Secili degilken eski, okunakli aktarim (page_sheet) calisir.
        self.card_layout = ChoiceCard(
            "mdi6.printer-outline", _t("PDF yerleşimini koru"),
            _t("Sayfanın tamamı; PDF'in ölçüleri ve baskı düzeniyle. Hücreler düzenlenebilir."))
        self.card_tables = ChoiceCard(
            "mdi6.table", _t("Yalnızca tablolar"),
            _t("Yalnız tablolardaki veriler; tablo dışındaki yazılar ve resimler alınmaz."))
        # ("tek sekmede": "tek sayfada" baski sayfasina sigdirmak diye okunabiliyordu)
        self.tables_seg = Segmented([_t("Her tablo ayrı sekmede"), _t("Tümü tek sekmede")])
        self.tables_seg.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)      # (iki esit hucre, yazi kadar)
        self.tables_seg.setAccessibleName(_t("Yalnızca tablolar"))
        self.r_tabs, self.r_one = self.tables_seg.buttons
        self.card_tables.add_inside(self.tables_seg)
        self.cards = dict(zip(self.MODES, (self.card_page, self.card_layout, self.card_tables)))
        g = QButtonGroup(self)
        for c in self.cards.values():
            g.addButton(c.radio)
            v.addWidget(c)
        self.card_page.radio.setChecked(True)

        v.addSpacing(10)
        v.addWidget(section_label(_t("Sayfalar")))
        self.scope = PageScopeBar(current_page, page_count)
        v.addWidget(self.scope)

        v.addSpacing(10)
        v.addWidget(section_label(_t("Seçenekler")))
        self.chk_img = QCheckBox(_t("Resimleri de aktar (logo, fotoğraf, grafik görüntüsü)"))
        self.chk_img.setChecked(True)
        self.chk_num = QCheckBox(_t("Sayıları sayı olarak aktar (toplanabilir, sıralanabilir)"))
        self.chk_num.setChecked(True)
        self.chk_text = QCheckBox(_t("Çizgisiz tabloları da ara (deneysel; yanlış sonuç verebilir)"))
        opts = QVBoxLayout()
        opts.setSpacing(9)
        opts.setContentsMargins(2, 2, 0, 0)
        for w in (self.chk_img, self.chk_num, self.chk_text):
            opts.addWidget(w)
        v.addLayout(opts)

        v.addSpacing(6)
        self.note = QLabel()
        self.note.setObjectName("dlgNote")           # (neyin AKTARILMADIGINI soyler: okunur olmali)
        self.note.setWordWrap(True)
        self.note.setMinimumHeight(self.note.fontMetrics().lineSpacing() * 2)
        self.note.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        v.addWidget(self.note)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText(_t("Aktar"))
        bb.button(QDialogButtonBox.Cancel).setText(_t("Vazgeç"))
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.setMinimumWidth(640)
        self._pages = []
        g.buttonToggled.connect(self._sync)
        self._sync()
        # klavye odagi: kartin isaretinde degil KARTIN cevresinde gosterilir
        by_radio = {c.radio: c for c in self.cards.values()}
        self.focus_ring = FocusRing(self, lambda w: by_radio.get(w))

    def _even_cards(self):
        """Kart aciklamalari ESIT yukseklikte: bir dilde biri iki satira inerse hepsine iki satirlik
        yer ayrilir -> ilk iki kart ayni boyda kalir (yoksa kartlar dilden dile duzensiz boylanir)."""
        descs = [c.desc for c in self.cards.values()]
        w = min(d.width() for d in descs)
        if w <= 0:
            return
        h = max(d.heightForWidth(w) for d in descs)
        if any(d.minimumHeight() != h for d in descs):
            for d in descs:
                d.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                d.setMinimumHeight(h)

    def showEvent(self, ev):
        super().showEvent(ev)
        self._even_cards()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._even_cards()

    @property
    def mode(self):
        return next((m for m, c in self.cards.items() if c.radio.isChecked()), "page")

    def set_mode(self, mode):
        self.cards[mode].radio.setChecked(True)

    def _sync(self, *_):
        whole = self.mode != "tables"
        self.chk_img.setEnabled(whole)               # (tablo kipinde resim alinmaz)
        self.note.setText(
            _t("Her PDF sayfası ayrı bir Excel sekmesi olur. Eğik filigran yazıları ve tablo dışındaki "
               "çizimler (çizgi, şekil) aktarılmaz.")
            if whole else "")

    def _apply(self):
        try:
            self._pages = self.scope.pages()
        except ValueError:
            self._pages = []
        if not self._pages:
            QMessageBox.warning(self, _t("Uyarı"), _t("Sayfa aralığı geçersiz. Örnek: 1-3, 5"))
            return
        self.accept()

    def pages(self):
        return list(self._pages)

    @property
    def whole_page(self):
        return self.mode != "tables"

    @property
    def keep_layout(self):
        return self.mode == "layout"

    @property
    def images(self):
        return self.chk_img.isChecked()

    @property
    def single_sheet(self):
        return self.r_one.isChecked()

    @property
    def numbers(self):
        return self.chk_num.isChecked()

    @property
    def text_tables(self):
        return self.chk_text.isChecked()
