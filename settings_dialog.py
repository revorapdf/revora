"""
settings_dialog.py
------------------
Ayarlar penceresi: Dil, Klavye kisayollari, Hakkinda, Destek.
Soldaki listeden bolum secilir. (Tema secimi yok: program hep koyu tema.)
"""
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QGridLayout, QListWidget, QListWidgetItem, QComboBox,
    QStackedWidget, QWidget, QLabel, QRadioButton, QButtonGroup, QScrollArea, QPushButton
)
from PySide6.QtGui import QPixmap
from PySide6.QtCore import Qt, QSize
from i18n import _t

SITE_URL = "https://revorapdf.com"
SOURCE_URL = "https://github.com/revorapdf/revora"     # AGPL: kaynak kodun adresi
CONTACT_MAIL = "revorapdf@gmail.com"

THEMES = (("light", _t("Açık")), ("dark", _t("Koyu")), ("system", _t("Sistemle aynı (Windows ayarını izler)")))

# (baslik, None) = bolum basligi; (tus, aciklama) = satir
GENERAL_SHORTCUTS = (
    (_t("Genel"), None),
    ("Ctrl + O", _t("PDF aç")),
    ("Ctrl + S", _t("Kaydet")),
    ("Ctrl + Shift + S", _t("Farklı kaydet")),
    ("Ctrl + Z", _t("Geri al")),
    ("Ctrl + Y  /  Ctrl + Shift + Z", _t("Yinele")),
    ("PgUp / PgDn", _t("Önceki / sonraki sayfa")),
    (_t("Ctrl + tekerlek"), _t("Yakınlaştır / uzaklaştır")),
    ("Ctrl + 0", _t("Sayfa genişliğine sığdır")),
    (_t("Ctrl + sürükle / orta tuş"), _t("Sayfayı kaydır")),
    ("Ctrl + ,", _t("Ayarlar")),
    (_t("Metin"), None),
    (_t("Tıkla + sürükle"), _t("Yazıyı taşı (Shift: sadece yatay/dikey)")),
    (_t("Çift tık / F2 / Enter"), _t("Yazıyı sayfanın üstünde düzenle")),
    ("Esc / Ctrl + Enter", _t("Düzenlemeyi bitir")),
    (_t("Oklar (+Shift)"), _t("İnce kaydırma (5 kat)")),
    ("Delete", _t("Seçili yazıyı sil")),
    (_t("Çizgi / Kutu"), None),
    ("V  L  K  D", _t("Seç · Çizgi · Kutu · Daire")),
    (_t("Shift + tık"), _t("Seçime ekle / çıkar")),
    (_t("Boşta sürükle"), _t("Kutu içine alınanları seç")),
    ("Ctrl + A", _t("Sayfadaki tüm çizgileri seç")),
    (_t("Shift (çizerken)"), _t("45° adım · kare / tam daire · oranı koru")),
    (_t("Alt (çizgi ucu)"), _t("Açı sabit, sadece uzunluk")),
    ("Delete", _t("Seçimi sil")),
)


def shortcuts_page(sections):
    inner = QWidget()
    g = QGridLayout(inner)
    g.setContentsMargins(4, 4, 12, 12)
    g.setHorizontalSpacing(24)
    g.setVerticalSpacing(5)
    row = 0
    for k, desc in sections:
        if desc is None:
            t = QLabel(k)
            t.setObjectName("settingsSection")
            g.addWidget(t, row, 0, 1, 2)
        else:
            kl = QLabel(k)
            kl.setObjectName("keyCap")
            g.addWidget(kl, row, 0)
            g.addWidget(QLabel(desc), row, 1)
        row += 1
    g.setColumnStretch(1, 1)
    g.setRowStretch(row, 1)
    sc = QScrollArea()
    sc.setWidgetResizable(True)
    sc.setFrameShape(QScrollArea.NoFrame)
    sc.setWidget(inner)
    return sc


class SettingsDialog(QDialog):
    def __init__(self, parent, theme_mode, on_theme, app_name, version, logo_path,
                 markup_shortcuts=(), page="appearance", icon_fn=None,
                 language=None, on_language=None, on_restart=None):
        super().__init__(parent)
        self.icon_fn = icon_fn
        self.language, self.on_language, self.on_restart = language, on_language, on_restart
        self.setWindowTitle(_t("Ayarlar"))
        self.resize(760, 520)
        self.on_theme = on_theme

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("settingsNav")
        self.nav.setFixedWidth(190)
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
        close = QPushButton(_t("Kapat"))
        close.clicked.connect(self.accept)
        br = QHBoxLayout()
        br.addStretch()
        br.addWidget(close)
        right.addLayout(br)
        h.addLayout(right, 1)

        self._keys = []
        self._add("appearance", _t("Dil"), "fa5s.language", self._appearance(theme_mode))
        self._add("shortcuts", _t("Klavye kısayolları"), "fa5s.keyboard",
                  shortcuts_page(GENERAL_SHORTCUTS + tuple(
                      [(_t("İşaretle"), None)] + [x for x in markup_shortcuts if x[1] is not None])))
        self._add("about", _t("Hakkında"), "fa5s.info-circle", self._about(app_name, version, logo_path))
        self._add("support", _t("Destek ol"), "fa5s.heart", self._support())
        self.nav.currentRowChanged.connect(self._show)
        self.nav.setCurrentRow(self._keys.index(page) if page in self._keys else 0)

    def _add(self, key, text, icon, widget):
        it = QListWidgetItem(text)
        if self.icon_fn is not None:
            it.setIcon(self.icon_fn(icon, "#6b7280"))
        it.setSizeHint(QSize(0, 38))
        self.nav.addItem(it)
        self.stack.addWidget(widget)
        self._keys.append(key)

    def _show(self, row):
        self.stack.setCurrentIndex(row)
        self.title.setText(self.nav.item(row).text())

    # ---------------------------------------------------------------- bolumler
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
                      "QtAwesome ve Font Awesome / Material Design ikonları — MIT / OFL"))
        comp.setObjectName("fieldLabel")
        v.addWidget(comp)
        v.addStretch()
        return w

    def _support(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        t = QLabel(_t("Yakında."))
        t.setObjectName("fieldLabel")
        v.addWidget(t)
        v.addStretch()
        return w
