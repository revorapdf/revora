"""
Revora — PDF Düzenleyici - main.py
-----------------------------------
Calistirmak icin: python main.py [dosya.pdf]  (ya da run.bat)
"""
import sys
import os
import math
import json
# ============================================================================
# ONEMLI - IMPORT SIRASI: PySide6, fitz'ten (PyMuPDF) ONCE yuklenmeli!
# Ters sirada (once fitz) Windows'ta ortak DLL cakismasi yuzunden uygulama
# aninda cokuyor (access violation, 0xC0000005) - pencere hic acilmaz.
# ============================================================================
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QPushButton, QLineEdit,
    QTextEdit, QVBoxLayout, QHBoxLayout, QGridLayout, QSplitter, QScrollArea, QFileDialog,
    QDoubleSpinBox, QSpinBox, QCheckBox, QMessageBox, QGroupBox, QButtonGroup,
    QComboBox, QMenu, QListWidget, QListWidgetItem, QAbstractItemView, QFrame, QToolButton,
    QSpacerItem, QSizePolicy
)
from PySide6.QtGui import (QImage, QPixmap, QPainter, QPen, QColor, QCursor, QIcon,
                           QFont, QPalette, QPolygonF, QBrush, QKeySequence, QShortcut,
                           QPainterPath, QTextCharFormat, QTextCursor, QTextBlockFormat)
from PySide6.QtCore import (Qt, QRect, QRectF, QPointF, QPoint, QSize, QSettings, QTimer, QObject, QEvent,
                            QEventLoop, Signal)

# DIL: arayuz modulleri (modul seviyesindeki sabitleriyle) yuklenmeden ONCE secilmeli
import i18n


def _default_language():
    """Kayitli dil yoksa (Store kurulumu, ilk acilis): Windows Turkce ise Turkce,
    degilse Ingilizce. (Inno kurulumu secilen dili kayda yazar, o oncelikli.)"""
    from PySide6.QtCore import QLocale
    langs = QLocale.system().uiLanguages()
    return i18n.SOURCE if langs and langs[0].lower().startswith("tr") else "en-US"


# (REVORA_LANG ortam degiskeni: test / deneme icin kayitli ayari ezer)
i18n.set_language(os.environ.get("REVORA_LANG")
                  or QSettings("PdfEdit", "PdfEdit").value("language", "", type=str)
                  or _default_language())
from i18n import _t

import fitz
from pdf_engine import PDFEditor, PasswordError
from merge_split import MergeDialog, SplitDialog
from font_resolver import FONT_DISPLAY_NAMES
from dialogs import (WatermarkDialog, FormDialog, OcrDialog, ColorButton,
                     TESSERACT_HELP, ensure_tesseract_env)
from reorder_view import ReorderView
from markup_ui import MarkupMixin, _EditorKeys
import curve_math
import markup_bar
import drag_ghost
import image_tools
import home_view
import title_bar
import win_frame
import pdf_content
import pdf_paths
import pdf_images
from find_bar import FindMixin

APP_NAME = "Revora"
APP_TITLE = _t("Revora — PDF Düzenleyici")



def resource_path(*parts):
    """Paketle gelen dosyalarin (logo vb.) yolu. Exe'de PyInstaller bunlari
    sys._MEIPASS altina acar; kaynaktan calisirken proje klasorudur."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


def _read_version():
    """Surum TEK yerde: VERSION dosyasi (kurulum betigi Revora.iss de oradan okur)."""
    try:
        with open(resource_path("VERSION"), encoding="utf-8") as f:
            return f.read().strip() or "?"
    except OSError:
        return "?"


APP_VERSION = _read_version()


# --- ikonlar (opsiyonel: qtawesome kurulu degilse yaziyla calisir) ---
try:
    import qtawesome as qta
    HAS_QTA = True
except Exception:
    HAS_QTA = False


ICON_DISABLED = "#555961"      # devre disi dugme / menu ogesi ikonu: belirgin bicimde soluk


def ic(name, color="#aeb3bb"):
    """Ikon dondurur: `rv.` ile baslayanlar kendi cizimimiz (markup_bar.custom_icon),
    digerleri qtawesome (yoksa bos QIcon). Devre disi hali hep soluk (ICON_DISABLED):
    geri al / yinele gibi dugmelerde "su an yapilamaz" bilgisi ikonun kendisinden okunur."""
    if name.startswith("rv."):
        return markup_bar.custom_icon(name, color, color_disabled=ICON_DISABLED) or QIcon()
    if HAS_QTA:
        try:
            return qta.icon(name, color=color, color_disabled=ICON_DISABLED)
        except Exception:
            return QIcon()
    return QIcon()


# ---------------------------------------------------------------------------
# Tema paletleri (acik / koyu). Ayni QSS sablonu, iki renk seti.
# ---------------------------------------------------------------------------
LIGHT = {
    # soguk mavi-gri: bembeyaz yerine hafif tonlu zemin -> beyaz PDF sayfasi one cikar,
    # mavi vurgu rengiyle uyumlu (kullanicinin sectigi palet, 2026-10-01)
    "bg": "#eef0fc", "surface": "#f7f8fc", "surface2": "#f0f3fc",
    "border": "#d8dfef", "border_input": "#cfd6e8",
    "text": "#1f2328", "text2": "#4b5058", "muted": "#6b7280",
    "accent": "#2563eb", "accent_hover": "#1d4ed8", "accent_press": "#1b46c2",
    "accent_text": "#ffffff",
    "btn_hover": "#eef0fc", "btn_press": "#e3e7f6",
    "tool_hover": "#e9edf9", "tool_press": "#dfe5f5",
    "sel": "#dbe4fb", "sel_text": "#1f2328",
    "danger": "#dc2626", "danger_border": "#f0b4b4",
    "danger_border_hover": "#e79a9a", "danger_bg": "#fdecec",
    "readonly": "#f0f3fc", "input": "#fbfcfe", "menu_hover": "#eef0fc",
    "scroll": "#c6cee0", "scroll_hover": "#aeb8cf", "disabled": "#b0b4ba",
}
DARK = {
    "bg": "#17181b", "surface": "#26282c", "surface2": "#202225",
    "border": "#33363c", "border_input": "#3c3f46",
    "text": "#e6e8eb", "text2": "#c4c8d0", "muted": "#9aa0a6",
    "accent": "#3b82f6", "accent_hover": "#5a97f7", "accent_press": "#2f6fe0",
    "accent_text": "#ffffff",
    "btn_hover": "#2f3238", "btn_press": "#33373d",
    "tool_hover": "#2f3238", "tool_press": "#33373d",
    "sel": "#2b3a57", "sel_text": "#e6e8eb",
    "danger": "#f07171", "danger_border": "#6e3a3a",
    "danger_border_hover": "#8a4747", "danger_bg": "#3a2627",
    "readonly": "#202225", "input": "#1e2024", "menu_hover": "#2f3238",
    "scroll": "#4a4d54", "scroll_hover": "#5b5f67", "disabled": "#6b6f77",
}

_TEMPLATE = """
QWidget { font-family: "Segoe UI", "Segoe UI Variable", Arial, sans-serif;
          font-size: 10pt; color: %(text)s; }
QMainWindow, #central, QDialog { background: %(bg)s; }

QLabel#hint { color: %(muted)s; padding: 8px 2px; }
QLabel#panelTitle { color: %(text)s; font-size: 11pt; font-weight: 600; }
QLabel#fieldLabel { color: %(muted)s; font-size: 9pt; }
QLabel#settingsSection { color: %(text)s; font-weight: 600; padding-top: 8px; }
QLabel#keyCap { color: %(text2)s; font-weight: 600; }
QListWidget#settingsNav { background: %(surface2)s; border: none; border-right: 1px solid %(border)s;
                          padding: 8px 6px; outline: none; }
QListWidget#settingsNav::item { color: %(text2)s; padding: 4px 8px; border-radius: 6px; }
QListWidget#settingsNav::item:selected { background: %(sel)s; color: %(sel_text)s; }

QPushButton { background: %(surface)s; border: 1px solid %(border_input)s; border-radius: 6px;
              padding: 6px 12px; color: %(text2)s; }
QPushButton:hover { background: %(btn_hover)s; }
QPushButton:pressed { background: %(btn_press)s; }
QPushButton:disabled { color: %(disabled)s; background: %(bg)s; }

QPushButton#primary { background: %(accent)s; border: 1px solid %(accent)s; color: %(accent_text)s;
                      font-weight: 600; padding: 8px 12px; }
QPushButton#primary:hover { background: %(accent_hover)s; }
QPushButton#primary:pressed { background: %(accent_press)s; }
QPushButton#primary:disabled { background: %(border_input)s; border-color: %(border_input)s;
                               color: %(disabled)s; }

QPushButton#danger { color: %(danger)s; border-color: %(danger_border)s; background: %(surface)s; }
QPushButton#danger:hover { background: %(danger_bg)s; border-color: %(danger_border_hover)s; }

QPushButton#toolbtn { background: transparent; border: none; border-radius: 6px;
                      padding: 6px 8px; color: %(text2)s; }
QPushButton#toolbtn:hover { background: %(tool_hover)s; }
QPushButton#toolbtn:pressed { background: %(tool_press)s; }
QPushButton#toolbtn::menu-indicator { image: none; }
QPushButton#toolbtnSlim { background: transparent; border: none; border-radius: 6px; padding: 6px 1px;
                          color: %(text2)s; }
QPushButton#toolbtnSlim:hover { background: %(tool_hover)s; }
QPushButton#toolbtnSlim:pressed { background: %(tool_press)s; }
QPushButton#toolbtnSlim::menu-indicator { image: none; }
/* sayfa "3 / 40": yazilabilir kutu ile toplam AYNI tur kutu (ayni cerceve, ayni ic bosluk)
   -> yazi satiri her ekran olceginde ayni hizada */
QLineEdit#pageEdit, QLineEdit#pageTotal { background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 3px 2px; color: %(text2)s; }
QLineEdit#pageTotal { padding-left: 0px; padding-right: 0px; }
QLineEdit#pageEdit { padding-right: 0px; }
QLineEdit#pageEdit:hover { border-color: %(border_input)s; }
QLineEdit#pageEdit:focus { background: %(input)s; border-color: %(accent)s; color: %(text)s; }
QLineEdit#pageEdit:disabled, QLineEdit#pageTotal:disabled { color: %(disabled)s; }

QPushButton#segL, QPushButton#segM, QPushButton#segR {
    background: %(surface)s; border: 1px solid %(border_input)s; padding: 6px 12px; color: %(text2)s; }
QPushButton#segL { border-top-right-radius: 0; border-bottom-right-radius: 0;
                   border-top-left-radius: 6px; border-bottom-left-radius: 6px; }
QPushButton#segM { border-left: none; border-right: none; border-radius: 0; }
QPushButton#segR { border-top-left-radius: 0; border-bottom-left-radius: 0;
                   border-top-right-radius: 6px; border-bottom-right-radius: 6px; }
QPushButton#segL:checked, QPushButton#segM:checked, QPushButton#segR:checked {
    background: %(accent)s; color: %(accent_text)s; border-color: %(accent)s; }
QPushButton#segM:checked { border-left: 1px solid %(accent)s; border-right: 1px solid %(accent)s; }
QPushButton#segL:disabled, QPushButton#segM:disabled, QPushButton#segR:disabled {
    background: transparent; color: %(disabled)s; border-color: %(border)s; }
QPushButton#segM:disabled { border-left: none; border-right: none; }

QLineEdit, QTextEdit, QComboBox, QDoubleSpinBox, QSpinBox {
    background: %(input)s; border: 1px solid %(border_input)s; border-radius: 6px; padding: 5px 8px;
    color: %(text)s; selection-background-color: %(accent)s; selection-color: %(accent_text)s; }
QLineEdit:focus, QTextEdit:focus, QComboBox:focus, QDoubleSpinBox:focus { border-color: %(accent)s; }
QLineEdit[readOnly="true"] { background: %(readonly)s; color: %(muted)s; }
/* acilir liste hep kutunun ALTINDA acilsin (secili oge kutunun ustune hizalanip yukari tasmasin) */
QComboBox { combobox-popup: 0; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(%(arrow_combo)s); width: 10px; height: 10px; }
/* sayi kutusu oklari: tema kendi cizer (yoksa stil yuzunden bos gorunuyordu) */
QAbstractSpinBox { padding-right: 20px; }
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {
    subcontrol-origin: border; width: 16px; border: none; background: transparent; margin-right: 3px; }
QAbstractSpinBox::up-button { subcontrol-position: top right; margin-top: 3px; }
QAbstractSpinBox::down-button { subcontrol-position: bottom right; margin-bottom: 3px; }
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {
    background: %(tool_hover)s; border-radius: 3px; }
QAbstractSpinBox::up-arrow { image: url(%(arrow_up)s); width: 9px; height: 9px; }
QAbstractSpinBox::down-arrow { image: url(%(arrow_down)s); width: 9px; height: 9px; }
/* ust seritteki kutular: oklar yerine sagda sürgü acan ▾ */
QAbstractSpinBox[mkDrop="true"] { padding-right: 22px; }
QToolButton#mkSpinDrop { background: transparent; border: none; border-radius: 4px; }
QToolButton#mkSpinDrop:hover { background: %(tool_hover)s; }
QSlider:horizontal { min-height: 22px; }   /* tutamac (16 px) ust/altta kesilmesin */
QSlider::groove:horizontal { height: 4px; background: %(border_input)s; border-radius: 2px; }
QSlider::sub-page:horizontal { background: %(accent)s; border-radius: 2px; }
QSlider::handle:horizontal { background: %(surface)s; border: 2px solid %(accent)s; width: 12px;
    height: 12px; margin: -6px 0; border-radius: 8px; }
QComboBox QAbstractItemView { border: 1px solid %(border_input)s; background: %(surface)s;
    color: %(text)s; selection-background-color: %(accent)s; selection-color: %(accent_text)s; outline: none; }

QGroupBox { border: 1px solid %(border)s; border-radius: 8px; margin-top: 16px;
            background: %(surface)s; padding: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: %(muted)s; }

QCheckBox { spacing: 7px; }

#topbar { background: %(surface)s; border-bottom: 1px solid %(border)s; }
#inspector { background: %(surface)s; border-left: 1px solid %(border)s; }

QSplitter::handle { background: %(border)s; }
QScrollArea { border: none; background: %(bg)s; }
QScrollArea#inspectorScroll { background: %(surface)s; }

QScrollArea#thumbs { background: %(surface2)s; border: none; border-right: 1px solid %(border)s; }
#thumbsHead { background: %(surface2)s; border-right: 1px solid %(border)s; }
QScrollArea#thumbs > QWidget { background: %(surface2)s; }

QStatusBar { background: %(surface)s; border-top: 1px solid %(border)s; color: %(muted)s; }
QStatusBar QLabel { color: %(muted)s; }

QMenu { background: %(surface)s; border: 1px solid %(border_input)s; border-radius: 8px; padding: 4px;
        color: %(text)s; }
QMenu::item { padding: 6px 24px 6px 12px; border-radius: 6px; }
QMenu::item:selected { background: %(menu_hover)s; }

/* Isaretle: ShareX tarzi ust cubuk */
#canvasColumn { background: %(bg)s; }
#mkBarHost { background: transparent; }
QFrame#mkPill { background: %(surface)s; border: 1px solid %(border)s; border-radius: 10px; }
QToolButton#mkTool, QToolButton#mkToolDanger { background: transparent; border: none;
    border-radius: 7px; padding: 4px; color: %(text2)s; }
QToolButton#mkTool:hover, QToolButton#mkToolDanger:hover { background: %(tool_hover)s; }
QToolButton#mkTool:pressed { background: %(tool_press)s; }
QToolButton#mkTool:checked { background: %(accent)s; color: %(accent_text)s; }
QToolButton#mkTool:disabled { background: transparent; }
QToolButton#mkZoomPct { background: transparent; border: none; border-radius: 6px;
                        color: %(text2)s; font-size: 8.5pt; padding: 3px 2px; min-width: 34px; }
QToolButton#mkZoomPct:hover { background: %(tool_hover)s; }
QFrame#mkZoomSep { background: %(border)s; border: none; margin: 2px 4px; }
QToolButton#mkToolDanger:hover { background: %(danger_bg)s; }
QToolButton#mkSwatch { background: transparent; border: none; border-radius: 7px; padding: 2px; }
QToolButton#mkSwatch:hover { background: %(tool_hover)s; }
QFrame#mkSep { background: %(border)s; margin: 0 4px; }
QFrame#mkSepStrong { background: %(muted)s; border-radius: 1px; }
QLabel#mkLabel { color: %(muted)s; padding: 0 6px; }
QFrame#mkPopover { background: %(surface)s; border: 1px solid %(border_input)s; border-radius: 10px; }
QFrame#mkPill QComboBox, QFrame#mkPill QDoubleSpinBox, QFrame#mkPill QSpinBox { padding: 3px 6px; }
/* Bul / Degistir cubugu */
QFrame#mkPill QLineEdit { padding: 3px 8px; border-radius: 7px; }
QLabel#findCount { color: %(muted)s; font-size: 9pt; background: transparent; border: none; }
QLabel#findCount[none="true"] { color: %(danger)s; }
QToolButton#findBtn { background: %(tool_hover)s; border: none; border-radius: 7px; padding: 3px 12px;
                      color: %(text)s; }
QToolButton#findBtn:hover { background: %(border_input)s; }
QToolButton#findBtn:disabled { color: %(disabled)s; }
QToolButton#findSeg { background: transparent; border: none; border-radius: 7px; padding: 2px 10px;
                      color: %(muted)s; font-size: 9pt; }
QToolButton#findSeg:hover { background: %(tool_hover)s; }
QToolButton#findSeg:checked { background: %(tool_press)s; color: %(text)s; }
QTextEdit#mkInlineText, QTextEdit#mkInlineEdit { background: rgba(255, 255, 255, 245);
    border: 2px solid %(accent)s; border-radius: 4px; padding: 2px; }
QTextEdit#mkInlineEdit { background: #ffffff; }   /* opak: alttaki orijinal yazi golge yapmasin */
/* canli duzenleme: kutu GORUNMEZ (yazi PDF motoruyla sayfaya cizilir); sadece imlec + secim */
QTextEdit#mkInlineLive { background: transparent; border: none; padding: 0px; color: #111111;
    selection-background-color: rgba(59, 130, 246, 110); selection-color: transparent; }
QTextEdit#mkInlineText { color: #111111; }

/* Kaydirma cubugu: GORUNEN tutamac 8 px (eskiden 6), TUTULAN alan 12 px. Tutamacin cevresinde
   2 px gorunmez kenarlik var (background-clip: padding): ince gorunur ama fareyle yakalamasi
   kolay. (Karsilastirma: macOS ~7 px, ustune gelince 11; Windows 11 ~6-8; klasik Windows 17.) */
QScrollBar:vertical { background: transparent; width: 12px; margin: 0px; }
QScrollBar::handle:vertical { background: %(scroll)s; border: 2px solid transparent; border-radius: 6px;
                              background-clip: padding; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: %(scroll_hover)s; }
QScrollBar:horizontal { background: transparent; height: 12px; margin: 0px; }
QScrollBar::handle:horizontal { background: %(scroll)s; border: 2px solid transparent; border-radius: 6px;
                                background-clip: padding; min-width: 36px; }
QScrollBar::handle:horizontal:hover { background: %(scroll_hover)s; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
/* sol sayfa paneli dar: orada gorunen tutamac 6 px (8 kalin duruyordu), tutulan alan yine 12 px */
QScrollArea#thumbs QScrollBar::handle:vertical { border: 3px solid transparent; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }
"""


def _arrow_images(dark):
    """Tema renginde kucuk ok resimleri (QSS url() ile kullanilir); gecici klasore yazilir."""
    import tempfile
    col = "#c4c8d0" if dark else "#4b5058"
    d = os.path.join(tempfile.gettempdir(), "revora_ui")
    os.makedirs(d, exist_ok=True)
    out = {}
    for key, name in (("arrow_up", "mdi6.chevron-up"), ("arrow_down", "mdi6.chevron-down"),
                      ("arrow_combo", "mdi6.chevron-down")):
        path = os.path.join(d, f"{key}_{'d' if dark else 'l'}.png")
        if not os.path.exists(path):
            try:
                import qtawesome as qta
                qta.icon(name, color=col).pixmap(32, 32).save(path)
            except Exception:
                pass
        out[key] = path.replace("\\", "/")
    return out


def build_style(dark):
    return _TEMPLATE % {**(DARK if dark else LIGHT), **_arrow_images(dark)}


def build_palette(dark):
    """Stil sablonuyla ayrica QPalette de ayarlariz; boylece ozel stillenmemis
    widget'lar (ör. PDF Ayır'daki kaydırma alani, dialog zeminleri) de temaya
    uyar, beyaz kalmaz."""
    p = DARK if dark else LIGHT
    pal = QPalette()
    win = QColor(p["bg"]); base = QColor(p["input"]); surf = QColor(p["surface"])
    txt = QColor(p["text"]); mut = QColor(p["muted"])
    pal.setColor(QPalette.Window, win)
    pal.setColor(QPalette.WindowText, txt)
    pal.setColor(QPalette.Base, base)
    pal.setColor(QPalette.AlternateBase, surf)
    pal.setColor(QPalette.Text, txt)
    pal.setColor(QPalette.Button, surf)
    pal.setColor(QPalette.ButtonText, txt)
    pal.setColor(QPalette.ToolTipBase, surf)
    pal.setColor(QPalette.ToolTipText, txt)
    pal.setColor(QPalette.PlaceholderText, mut)
    pal.setColor(QPalette.Highlight, QColor(p["accent"]))
    pal.setColor(QPalette.HighlightedText, QColor(p["accent_text"]))
    pal.setColor(QPalette.Link, QColor(p["accent"]))
    # kenarlik tonlari: Birlestir/Ayir pencereleri renklerini buradan okur
    # (ayarlanmazsa Qt'nin acik gri varsayilanlari koyu temada da kalir)
    pal.setColor(QPalette.Light, surf)
    pal.setColor(QPalette.Midlight, QColor(p["border"]))
    pal.setColor(QPalette.Mid, QColor(p["border_input"]))
    pal.setColor(QPalette.Dark, QColor(p["scroll"]))
    return pal


def pix_to_qimage(pix):
    img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
    return img.copy()


ACCENT = QColor(37, 99, 235)
TEXT_SEL = QColor(230, 50, 50)
INSERT_COL = QColor(40, 170, 90)
GUIDE_COL = QColor(236, 72, 153)     # akilli kilavuz cizgisi (secim kirmizisi ve vurgu mavisinden ayri)
HANDLE_PX = 4.5       # tutamac yari-genisligi (ekran pikseli)
DRAG_START_PX = 4     # bu kadar oynamadan surukleme baslamaz (yanlislikla tasimayi onler)
SNAP_PX = 7           # yapisma mesafesi (ekran pikseli)
MAX_RENDER_PIXELS = 40_000_000
MIN_ZOOM, MAX_ZOOM = 0.25, 8.0   # %25 - %800

HANDLE_CURSORS = {
    "tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
    "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
    "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
    "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor,
    "p1": Qt.CrossCursor, "p2": Qt.CrossCursor, "bend": Qt.PointingHandCursor,
}
BEND_SNAP_PX = 5   # bukme tutamaci duz cizgiye bu kadar (ekran px) yaklasinca cizgi duzlesir


def _proj(p, a, b):
    """p noktasinin a-b dogru parcasi uzerindeki en yakin noktasi."""
    dx, dy = b.x - a.x, b.y - a.y
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return fitz.Point(a)
    t = max(0.0, min(1.0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / L2))
    return fitz.Point(a.x + t * dx, a.y + t * dy)


class _Resized(QObject):
    """Boyut degisince (tuval alani / goruntu alani) cagri yapar."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Show):
            self.fn()
        return False


class _GeomWatch(QObject):
    """Izlenen seritlerin boyutu/konumu/gorunurlugu degisince (gercek ekranda bu bazen
    yerlesimden sonra olur) cagriyi olaylar bittikten sonra BIR KEZ yapar."""

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self._pending = False

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Resize, QEvent.Move, QEvent.Show, QEvent.Hide) and not self._pending:
            self._pending = True
            QTimer.singleShot(0, self._run)
        return False

    def _run(self):
        self._pending = False
        self.fn()


class PDFCanvas(QWidget):
    """PDF sayfasini gosterir; fare/klavye olaylarini PDF koordinatina
    cevirip pencereye iletir; secim/surukleme katmanini her karede
    pencerenin paint_overlay'i ile ustune cizer (sayfa yeniden
    render edilmeden akici surukleme)."""

    PLACEHOLDER = (_t("Başlamak için üstteki \"Aç\" butonuna tıklayın\n"
                   "ya da bir PDF dosyasını buraya sürükleyip bırakın"))

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.zoom = 1.5
        self.dpr = 1.0
        self._pix = None
        self.disp = fitz.Identity       # sayfa -> ekran (sayfa donusu)
        self.derot = fitz.Identity      # ekran -> sayfa
        self.bg = None                  # surukleme: nesnesiz sayfa goruntusu (yoksa asil sayfa)
        self.ghost = None               # surukleme: (nesnenin goruntusu, sol-ust sayfa noktasi, kirpma cokgeni|None)
        self._panning = False
        self.pad_top = 0                # ustte suzulen arac seritleri icin bos pay (px)
        self.pad_bottom = 12            # sayfanin altinda kucuk bosluk (sayfa kenara yapismasin)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(500, 500)

    # ---- goruntu ----
    def has_page(self):
        return self._pix is not None

    def set_page(self, qimg, dpr, disp, derot):
        self._pix = QPixmap.fromImage(qimg)
        self._pix.setDevicePixelRatio(dpr)
        self.bg = self.ghost = None
        self.dpr, self.disp, self.derot = dpr, disp, derot
        self.setFixedSize(QSize(round(qimg.width() / dpr),
                                round(qimg.height() / dpr) + self.pad_top + self.pad_bottom))
        self.update()

    def set_pad_top(self, px):
        px = int(px)
        if px != self.pad_top:
            self.pad_top = px
            if self._pix is not None:
                sz = self._pix.deviceIndependentSize()
                self.setFixedSize(QSize(round(sz.width()), round(sz.height()) + px + self.pad_bottom))
            self.update()

    def clear_page(self):
        self._pix = None
        self.setMinimumSize(500, 500)
        self.setMaximumSize(16777215, 16777215)
        self.update()

    # ---- koordinat ----
    def to_px(self, p):
        q = fitz.Point(p) * self.disp
        return QPointF(q.x * self.zoom, q.y * self.zoom + self.pad_top)

    def to_pdf(self, pos):
        return fitz.Point(pos.x() / self.zoom, (pos.y() - self.pad_top) / self.zoom) * self.derot

    def poly_px(self, pts, matrix=None):
        if matrix is not None:
            pts = [fitz.Point(p) * matrix for p in pts]
        return QPolygonF([self.to_px(p) for p in pts])

    def rect_px(self, r):
        r = fitz.Rect(r)
        a, b = self.to_px(r.tl), self.to_px(r.br)
        return QRectF(a, b).normalized()

    def crop(self, rectf):
        d = self.dpr
        pm = self._pix.copy(QRect(int(rectf.x() * d), int((rectf.y() - self.pad_top) * d),
                                  int(rectf.width() * d) + 1, int(rectf.height() * d) + 1))
        pm.setDevicePixelRatio(d)
        return pm

    # ---- cizim ----
    def paintEvent(self, ev):
        p = QPainter(self)
        if self._pix is None:
            p.setRenderHint(QPainter.Antialiasing)
            pen = QPen(QColor("#8b9096"))
            pen.setStyle(Qt.DashLine)
            pen.setWidth(2)
            p.setPen(pen)
            r = self.rect().adjusted(20, 20, -20, -20)
            p.drawRoundedRect(r, 10, 10)
            p.setPen(QColor("#9aa0a6"))
            p.drawText(r, Qt.AlignCenter, self.PLACEHOLDER)
            p.end()
            return
        # nesnesiz arka plan yalnizca surukleme surerken (iptal edilen suruklemede kalmasin)
        bg = self.bg if self.bg is not None and (getattr(self.win, "drag", None)
                                                 or self.win.editing_live()) else self._pix
        p.drawPixmap(0, self.pad_top, bg)
        p.setRenderHint(QPainter.Antialiasing)
        self.win.paint_overlay(p, self)
        p.end()

    # ---- fare ----
    def mousePressEvent(self, ev):
        pan = ev.button() == Qt.MiddleButton or (
            ev.button() == Qt.LeftButton and ev.modifiers() & Qt.ControlModifier)
        if pan:
            self._panning = True
            self.setCursor(QCursor(Qt.ClosedHandCursor))
            self.win.on_pan_start(ev.globalPosition())
            return
        self.setFocus()
        if not self._pix:
            return
        pt = self.to_pdf(ev.position())
        if ev.button() == Qt.LeftButton:
            self.win.canvas_press(pt, ev.position(), ev.modifiers())
        elif ev.button() == Qt.RightButton:
            self.win.canvas_context(pt, ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        if self._panning:
            self.win.on_pan_move(ev.globalPosition())
            return
        if self._pix:
            self.win.canvas_move(self.to_pdf(ev.position()), ev.position(), ev.modifiers(),
                                 bool(ev.buttons() & Qt.LeftButton))

    def mouseReleaseEvent(self, ev):
        if self._panning:
            self._panning = False
            self.win.update_cursor()
            return
        if ev.button() == Qt.LeftButton and self._pix:
            self.win.canvas_release(self.to_pdf(ev.position()), ev.position(), ev.modifiers())

    def mouseDoubleClickEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._pix:
            self.win.canvas_double(self.to_pdf(ev.position()))

    def leaveEvent(self, ev):
        self.win.canvas_leave()

    def keyPressEvent(self, ev):
        if not self.win.canvas_key(ev):
            super().keyPressEvent(ev)

    def wheelEvent(self, ev):
        if ev.modifiers() & Qt.ControlModifier:
            self.win.on_wheel_zoom(ev.angleDelta().y(), ev.position())
            ev.accept()
        else:
            super().wheelEvent(ev)


THUMB_H = 104         # sol listedeki sayfa kucuk resminin yuksekligi (px)
THUMBS_W = 140        # sol listenin genisligi (uzerine gelince 4 dugme sigsin)


def paint_thumb(p, r, pix, info, badge=0):
    """Sol listede bir sayfa (ReorderView karti): kucuk resim + sayfa numarasi.
    Numara, surukleme sirasinda sayfanin birakilinca alacagi yeni sirayi gosterir.
    badge: aramada bu sayfadaki eslesme sayisi (0: rozet yok)."""
    pal = QApplication.palette()
    acc = pal.color(QPalette.Highlight)
    box = QRectF(r).adjusted(4, 1, -4, -1)
    if info["selected"] or info["hover"]:
        tint = QColor(acc)
        tint.setAlpha(22 if info["lifted"] else (46 if info["selected"] else 16))
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(box, 8, 8)
    area = QRectF(box.x() + 6, box.y() + 5, box.width() - 12, THUMB_H)
    sz = pix.deviceIndependentSize()
    s = min(area.width() / sz.width(), area.height() / sz.height(), 1.0)
    w, h = sz.width() * s, sz.height() * s
    target = QRectF(area.center().x() - w / 2, area.y() + (area.height() - h) / 2, w, h)
    p.drawPixmap(target, pix, QRectF(pix.rect()))
    sel = info["selected"]
    pen = QPen(acc if sel else pal.color(QPalette.Mid))
    pen.setWidthF(2.0 if sel else 1.0)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    p.drawRect(target.adjusted(-0.5, -0.5, 0.5, 0.5))
    f = QFont(p.font())
    f.setBold(sel)
    p.setFont(f)
    p.setPen(pal.color(QPalette.Text) if sel else pal.color(QPalette.PlaceholderText))
    if not info.get("actions"):       # uzerine gelince numaranin yerinde dugmeler var
        p.drawText(QRectF(box.x(), area.bottom() + 3, box.width(), 18), Qt.AlignCenter, str(info["number"]))
    if badge:                         # arama: sayfadaki eslesme sayisi (kucuk resmin sag ust kosesi)
        text = str(badge) if badge < 1000 else "999+"
        f.setBold(True)
        f.setPointSizeF(max(7.0, f.pointSizeF() - 1.5))
        p.setFont(f)
        w = max(18.0, p.fontMetrics().horizontalAdvance(text) + 10.0)
        pill = QRectF(target.right() - w + 5, target.top() - 5, w, 16)
        p.setPen(Qt.NoPen)
        p.setBrush(acc)
        p.drawRoundedRect(pill, 8, 8)
        p.setPen(QColor("#ffffff"))
        p.drawText(pill, Qt.AlignCenter, text)


class _PageEdit(QLineEdit):
    """Ust seritteki sayfa numarasi kutusu: tiklayinca tumu secilir, Enter gider, Esc vazgecer."""
    submitted = Signal(str)                     # Enter: yazilan numara
    cancelled = Signal(bool)                    # vazgecildi (True: Esc ile -> odak tuvale donsun)
    focused = Signal()                          # tiklandi / Ctrl+G: kutu genislesin

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxLength(6)
        self.returnPressed.connect(lambda: self.submitted.emit(self.text()))

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focused.emit()
        QTimer.singleShot(0, self.selectAll)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.cancelled.emit(False)              # yarim birakildi: gecerli sayfa numarasina don

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.cancelled.emit(True)
            return
        if e.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_PageUp, Qt.Key_PageDown) or e.text().isdigit() \
                or e.key() in (Qt.Key_Backspace, Qt.Key_Delete, Qt.Key_Left, Qt.Key_Right, Qt.Key_Home, Qt.Key_End,
                               Qt.Key_Return, Qt.Key_Enter, Qt.Key_Tab) or e.modifiers() & Qt.ControlModifier:
            super().keyPressEvent(e)            # (harf yazilamaz: yalnizca rakam)


class _PageTotal(QLineEdit):
    """ "/ 40" kismi: salt okunur, ama tiklaninca sayfa kutusu acilir (tek alan gibi davranir;
    tek haneli sayfada kutu 15 px: yalnizca ona tiklamak zor olurdu)."""
    clicked = Signal()

    def mousePressEvent(self, e):
        self.clicked.emit()


class _DocTab:
    """Bir sekme: belgenin motoru + o belgeye ait gorunum (sayfa, yakinlik, kaydirma)."""

    def __init__(self, engine):
        self.engine = engine
        self.page = 0
        self.zoom = None              # None: ilk gosterimde genislige sigdirilir
        self.scroll = (0, 0)
        self.thumbs = None            # kucuk resimler: sekmeye donunce yeniden cizilmesin
        self.thumbs_ver = -1


class MainWindow(QMainWindow, MarkupMixin, FindMixin):
    def __init__(self):
        super().__init__()
        self.resize(1280, 840)
        self.setAcceptDrops(True)

        # Sekmeler: her belge kendi PDFEditor'unda (belge, geri-al gecmisi, "degisti" bayragi).
        # self.engine HER ZAMAN gecerli sekmenin motorudur; baslangic ekraninda bos motor.
        # Boylece kodun geri kalani (self.engine.doc ...) sekmelerden habersiz calisir.
        self._home_engine = PDFEditor()
        self.engine = self._home_engine
        self.tabs = []                # [_DocTab]
        self.tab_idx = -1             # -1 = baslangic ekrani
        self._frameless = False
        self.current_page = 0
        self.mode = "text"            # "text" | "shape" | "insert"
        self.shape_tool = "select"    # "select" | "line" | "rect"
        self.current_span = None
        self.hover_span = None
        self.sel_spans = []           # TOPLU secim: 2+ yazi (tek yazi secimi current_span'dir)
        self.sel_images = []          # secili resimlerin sira numaralari (toplu secimin parcasi)
        self.hover_image = None
        self.sel_paths = []           # secili cizimlerin indeksleri
        self.hover_path = None
        self.pending_insert = None    # (sayfa, x, y)
        self.selected_color = None    # metin: None = orijinal renk
        self.drag = None
        self._press_pos = None
        self._snap_pt = None
        self._insert_size = 11.0      # yeni metin boyutu (secili metinden devralinmaz)
        self._overwrite_ok = set()
        self._neutral_icons = []      # tema degisince yeniden renklenecek ikonlar
        self._nudge_token = 0         # ok tusu kaydirma grubu (tiklama/secim degisince artar)

        self._settings = QSettings("PdfEdit", "PdfEdit")
        # 2026-10-02: sadece koyu tema (kullanici: acik arayuz goz aliyor). Acik tema kodu
        # (build_style/build_palette dark=False, set_theme_mode) geri donus icin duruyor;
        # Ayarlar'da tema secimi yok, kayitli eski "theme" degeri yok sayilir.
        self.theme_mode = "dark"
        self.dark = True
        # yeni cizimler icin son kullanilan cizgi stili (kapatip acinca da hatirlanir)
        self.shape_style = self.load_style_setting(
            "shape_style", {"width": 0.75, "color": [0.0, 0.0, 0.0], "dashed": False, "dash": "dash_m"})
        self._shape_loading = False

        self._build_ui()
        self._build_shortcuts()
        self.apply_theme(self.dark)
        try:    # "Sistemle ayni": Windows'ta acik/koyu degisince takip et (Qt 6.5+)
            QApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme)
        except Exception:
            pass
        self._refresh_panel()
        self._update_title()
        # Windows'un baslik seridi yerine kendi seridimiz (bkz. win_frame.py). Kurulurken
        # gelen ilk cerceve mesajlari da islensin diye bayrak ONCE acilir.
        self._frameless = win_frame.ACTIVE
        self._frameless = win_frame.setup(self)
        if not self._frameless:
            for b in self.titlebar.buttons:
                b.hide()
        else:
            try:    # baska olcekli ekrana tasininca cerceve yeniden hesaplansin
                self.windowHandle().screenChanged.connect(lambda *_: win_frame.refresh(self))
            except Exception:
                pass
        self._update_frame_border()

    # ======================================================== pencere cercevesi
    def nativeEvent(self, event_type, message):
        if self._frameless:
            try:
                done, result = win_frame.native_event(self, message, self._is_caption)
            except Exception:
                done = False
            if done:
                return True, result
        return super().nativeEvent(event_type, message)

    def toggle_maximized(self):
        if self._frameless:
            win_frame.toggle_max(self)
        elif self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def _is_caption(self, pos):
        """pos (pencere koordinati) baslik seridinin bos, surukleme alaninda mi?"""
        tb = getattr(self, "titlebar", None)
        return tb is not None and tb.isVisible() and tb.is_caption(tb.mapFrom(self, pos))

    def changeEvent(self, ev):
        if ev.type() == QEvent.WindowStateChange and getattr(self, "titlebar", None) is not None:
            self.titlebar.set_maximized(self.isMaximized())
            self._update_frame_border()
        super().changeEvent(ev)

    def _update_frame_border(self):
        """Windows 10: pencere normal boyuttayken 1 piksel kenarlik (ekrani kaplayinca yok)."""
        on = self._frameless and win_frame.needs_border() and not self.isMaximized()
        m = 1 if on else 0
        if self.contentsMargins().left() != m:
            self.setContentsMargins(m, m, m, m)
        self._frame_border = on

    def paintEvent(self, ev):
        super().paintEvent(ev)
        if getattr(self, "_frame_border", False):
            p = QPainter(self)
            p.setPen(QColor((DARK if self.dark else LIGHT)["border_input"]))
            p.drawRect(self.rect().adjusted(0, 0, -1, -1))
            p.end()

    # ---- ikinci kez calistirilinca (Gezgin'de PDF'e cift tik): dosya BU pencerede sekme olur
    def open_from_other_instance(self, paths):
        if QApplication.activeModalWidget() is not None:     # bir soru / pencere acik: bitince
            QTimer.singleShot(600, lambda: self.open_from_other_instance(paths))
            return
        if self._frameless:
            win_frame.restore_and_raise(self)
        else:
            self.showNormal() if self.isMinimized() else None
            self.raise_()
            self.activateWindow()
        for p in paths:
            if isinstance(p, str) and os.path.isfile(p):
                self.open_pdf(p)

    # ======================================================== UI kurulumu
    def _sep(self):
        w = QWidget()
        w.setFixedWidth(1)
        w.setFixedHeight(26)
        w.setStyleSheet("background:#8b909640;")
        return w

    def _tool_btn(self, fa, fallback, tip, checkable=False, text=None, size=16):
        b = QPushButton()
        b.setObjectName("toolbtn")
        b.setCheckable(checkable)
        b.setToolTip(tip)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        icon = ic(fa, "#3d424a")
        if not icon.isNull():
            b.setIcon(icon)
            b.setIconSize(QSize(size, size))
            if text:
                b.setText(" " + text if size > 16 else "  " + text)
            self._neutral_icons.append((b, fa))
        else:
            b.setText(text if text else fallback)
        return b

    def _make_seg(self, objn, fa, text, tip):
        b = QPushButton(text)
        b.setObjectName(objn)
        b.setCheckable(True)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        b.setToolTip(tip)
        icon = ic(fa, "#4b5058")
        if not icon.isNull():
            b.setIcon(icon)
            b.setIconSize(QSize(16, 16))
            self._neutral_icons.append((b, fa))
        return b

    def _bar_btn(self, icon_name, tip, checkable=True):
        """Ust seritteki kompakt ikon dugmesi (tema degisince ikonu yeniden renklenir)."""
        b = markup_bar.tool_button(icon_name, tip, checkable, None, self.dark)
        self._mk_bar_buttons.append(b)
        return b

    def _field(self, text):
        l = QLabel(text)
        l.setObjectName("fieldLabel")
        return l

    def _build_ui(self):
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        # en ustte: sekmeler + pencere dugmeleri (Windows'un baslik seridi yerine)
        self.titlebar = title_bar.TitleBar(resource_path("assets", "revora.png"), self,
                                           own_buttons=win_frame.ACTIVE)
        strip = self.titlebar.strip
        strip.currentChanged.connect(self.switch_tab)
        strip.closeRequested.connect(self.close_tab)
        strip.moved.connect(self._tab_moved)
        strip.newRequested.connect(lambda: self.open_pdf())
        strip.contextRequested.connect(self._tab_context)
        root.addWidget(self.titlebar)
        self.topbar = self._build_topbar()
        root.addWidget(self.topbar)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # --- sol: sayfa kucuk resimleri ---
        # iOS tarzi siralama: tutulan sayfa kalkar, birakilacak yerde bosluk acilir.
        # Odak almaz (focusable=False): ok tuslari tuvalde metni tasimaya devam etsin.
        self.thumbs = ReorderView(THUMB_H + 26,
                                  lambda p, r, pix, info: paint_thumb(p, r, pix, info, self._find_badge(info)),
                                  spacing=4, margin=6, focusable=False)
        self.thumbs.setToolTip(_t("Sürükleyerek sıralayın · sağ tık: tüm sayfa işlemleri"))
        # uzerine gelince kucuk resmin alt kenarinda cikan dugmeler
        self.thumbs.set_actions([("add", "fa5s.plus", _t("Arkasına boş sayfa ekle"), False),
                                 ("rotl", "fa5s.undo", _t("Sola döndür"), False),
                                 ("rotr", "fa5s.redo", _t("Sağa döndür"), False),
                                 ("del", "fa5s.trash-alt", _t("Sayfayı sil"), True)],
                                ic, center_y=6 + THUMB_H)
        self.thumbs.actionTriggered.connect(self._thumb_action)
        self.thumbs.currentChanged.connect(self._on_thumb_changed)
        self.thumbs.moved.connect(lambda s, d: self.move_page_to(s, d, view_done=True))
        self.thumbs.contextRequested.connect(self._thumb_context)
        self.thumbs_scroll = QScrollArea()
        self.thumbs_scroll.setObjectName("thumbs")
        self.thumbs_scroll.setWidgetResizable(True)
        self.thumbs_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.thumbs_scroll.setWidget(self.thumbs)
        # ustte: cogalt / bos sayfa / PDF'ten sayfa (gecerli sayfaya gore)
        head = QWidget()
        head.setObjectName("thumbsHead")
        hh = QHBoxLayout(head)
        hh.setContentsMargins(6, 6, 6, 4)
        hh.setSpacing(2)
        self.btn_pg_dup = self._tool_btn("fa5s.copy", "⧉", _t("Bu sayfayı çoğalt"))
        self.btn_pg_blank = self._tool_btn("fa5s.plus", "+", _t("Arkasına boş sayfa ekle"))
        self.btn_pg_import = self._tool_btn("fa5s.file-import", "⤓", _t("Arkasına başka PDF'ten sayfa ekle"))
        self.btn_pg_dup.clicked.connect(lambda: self._page_op("dup", self.current_page))
        self.btn_pg_blank.clicked.connect(lambda: self._page_op("blank", self.current_page + 1))
        self.btn_pg_import.clicked.connect(lambda: self._page_op("import", self.current_page + 1))
        hh.addStretch()
        for b in (self.btn_pg_dup, self.btn_pg_blank, self.btn_pg_import):
            hh.addWidget(b)
        hh.addStretch()
        pane = self.thumbs_pane = QWidget()
        pane.setObjectName("thumbsPane")
        pane.setFixedWidth(THUMBS_W)
        pv = QVBoxLayout(pane)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pv.addWidget(head)
        pv.addWidget(self.thumbs_scroll, 1)
        splitter.addWidget(pane)

        # --- orta: tuval ---
        self.canvas = PDFCanvas(self)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.canvas)
        self.scroll.setWidgetResizable(False)
        self.scroll.setAlignment(Qt.AlignCenter)
        # Arac/ayar seritleri sayfanin USTUNDE suzulur (ayri bant yok): sayfa kaydirilinca
        # seritlerin altindan gecer. Seritlerin disindaki bos alan fareyi engellemez (mask).
        center = QWidget()
        center.setObjectName("canvasColumn")
        cl = QVBoxLayout(center)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(self.scroll, 1)
        # acilis ekrani: PDF acik degilken tuvalin yerinde (hizli islemler + son dosyalar)
        self.home = home_view.HomeView(
            ic, resource_path("assets", "revora.png"),
            [("mdi6.folder-open-outline", "#7fb0ff", _t("PDF aç"),
              _t("Düzenle, işaretle, imzala"), lambda: self.open_pdf(), True, "Ctrl+O"),
             ("mdi6.image-multiple-outline", "#c9cdd6", _t("Resimlerden PDF"),
              _t("Fotoğraf ve taramaları tek PDF yap"), lambda: self.open_images_to_pdf(), False, None),
             ("mdi6.call-merge", "#c9cdd6", _t("PDF birleştir"),
              _t("Birden çok dosyayı tek PDF yap"), self.open_merge_dialog, False, None),
             ("mdi6.call-split", "#c9cdd6", _t("PDF ayır"),
              _t("Sayfaları ayrı dosyalara böl"), self.open_split_dialog, False, None)],
            self._recent_files, self.open_pdf, self._forget_recent, self._reveal_in_folder,
            self.open_settings)
        cl.addWidget(self.home, 1)
        self.home.hide()
        bar = self._build_markup_bar()
        bar.setParent(center)
        self._build_zoom_pill(center)
        self._build_find_bar(center)
        self._bar_placer = _Resized(self._place_bar_overlay)
        center.installEventFilter(self._bar_placer)
        self.scroll.viewport().installEventFilter(self._bar_placer)
        self._seg_placer = _GeomWatch(self._place_mode_seg)     # modlar tuvalin ortasina hizali
        center.installEventFilter(self._seg_placer)
        self.topbar.installEventFilter(self._seg_placer)
        splitter.addWidget(center)

        # --- sag panel: artik gosterilmiyor. Kontrolleri burada kurulup ust seritlere
        # tasinir (_build_mode_bars); tum modlar ayni ust seritleri kullanir. ---
        self.inspector = self._build_inspector()
        splitter.addWidget(self.inspector)
        self.inspector.hide()
        self._build_mode_bars()
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([THUMBS_W, 800, 350])

        # --- durum cubugu ---
        self.lbl_coords = QLabel("")
        self.lbl_fileinfo = QLabel("")
        self.statusBar().addPermanentWidget(self.lbl_coords)
        self.statusBar().addPermanentWidget(self.lbl_fileinfo)
        self.status(_t("Hazır — başlamak için bir PDF açın."))

    def _build_zoom_pill(self, parent):
        """Tuvalin sag altinda yuzen yakinlastirma denetimi (dikey): + / %deger / - / tum
        sayfa / genislik. Ust seridi sadelestirir; sayfanin ustunde durur, yer kaplamaz."""
        self.zoom_pill = QFrame(parent)
        self.zoom_pill.setObjectName("mkPill")
        v = QVBoxLayout(self.zoom_pill)
        v.setContentsMargins(4, 4, 4, 4)
        v.setSpacing(2)
        self.btn_zoom_in = self._bar_btn("mdi6.magnify-plus-outline", _t("Yakınlaştır (Ctrl+tekerlek)"), False)
        self.lbl_zoom = QToolButton()
        self.lbl_zoom.setObjectName("mkZoomPct")
        self.lbl_zoom.setCursor(QCursor(Qt.PointingHandCursor))
        self.lbl_zoom.setToolTip(_t("Gerçek boyut (%100)"))
        self.btn_zoom_out = self._bar_btn("mdi6.magnify-minus-outline", _t("Uzaklaştır (Ctrl+tekerlek)"), False)
        self.btn_fit_page = self._bar_btn("mdi6.fit-to-page-outline", _t("Tüm sayfayı sığdır (Ctrl+9)"), False)
        self.btn_fit = self._bar_btn("mdi6.arrow-expand-horizontal", _t("Sayfa genişliğine sığdır (Ctrl+0)"), False)
        self.btn_zoom_in.clicked.connect(lambda: self.set_zoom(self.canvas.zoom * 1.2))
        self.btn_zoom_out.clicked.connect(lambda: self.set_zoom(self.canvas.zoom / 1.2))
        self.lbl_zoom.clicked.connect(lambda: self.set_zoom(1.0))
        self.btn_fit_page.clicked.connect(self.fit_to_page)
        self.btn_fit.clicked.connect(self.fit_to_width)
        line = QFrame()
        line.setObjectName("mkZoomSep")
        line.setFixedHeight(1)
        for w in (self.btn_zoom_in, self.lbl_zoom, self.btn_zoom_out, line, self.btn_fit_page, self.btn_fit):
            v.addWidget(w, 0, Qt.AlignHCenter if w is not line else Qt.Alignment())
        self.zoom_pill.hide()

    def _place_zoom_pill(self):
        pill = getattr(self, "zoom_pill", None)
        if pill is None:
            return
        has = self.engine.doc is not None and not self.scroll.isHidden()
        pill.setVisible(has)
        if not has:
            return
        pill.adjustSize()
        g = self.scroll.geometry()
        # YERI SABIT: kaydirma cubuklari cikinca / kaybolunca oynamaz (kullanici: yakinlastirinca
        # sola ve yukari kayiyordu). Cubuklara hep yer birakilir: cubuk varken ona 14 px,
        # yokken kenara 14 + cubuk kalinligi kadar uzak.
        vsb, hsb = self.scroll.verticalScrollBar(), self.scroll.horizontalScrollBar()
        x = g.right() - pill.width() - 14 - vsb.sizeHint().width()
        y = g.bottom() - pill.height() - 14 - hsb.sizeHint().height()
        pill.move(max(0, x), max(0, y))
        pill.raise_()

    def _build_topbar(self):
        """Ust serit, uc bolge (kullaniciyla konusuldu, 2026-10-05):
          SOL  : belge islemleri  - kaydet (+ acilir menu), geri al / yinele, sayfa gezinme
          ORTA : modlar           - Metin | Cizgi/Kutu | Isaretle (tuvalin ortasina hizali:
                                    hemen altindaki yuzen arac seritleriyle ayni eksende)
          SAG  : araclar          - Sayfa, PDF Islemleri, Ayarlar
        "Ac" dugmesi yok: sekme seridindeki "+" ve Ctrl+O ayni isi yapiyor."""
        bar = QWidget()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(2)

        # ---------------- SOL: kaydet + geri al / yinele + sayfa
        self.btn_save = self._tool_btn("mdi6.content-save-outline", _t("Kaydet"), _t("Kaydet (Ctrl+S)"), size=20)
        self.btn_save.clicked.connect(self.save_pdf)
        save_menu = QMenu(self)
        save_menu.addAction(ic("mdi6.content-save-outline"), _t("Kaydet\tCtrl+S"), self.save_pdf)
        save_menu.addAction(ic("mdi6.content-save-edit-outline"), _t("Farklı kaydet...\tCtrl+Shift+S"), self.save_pdf_as)
        save_menu.addAction(ic("mdi6.arrow-collapse-vertical"), _t("Küçülterek kaydet..."), self.save_compressed)
        save_menu.addSeparator()
        save_menu.addAction(ic("mdi6.table-arrow-right"), _t("Excel'e aktar..."), self.export_excel)
        save_menu.addAction(ic("mdi6.image-outline"), _t("Sayfayı resim olarak kaydet..."), self.export_pages_dialog)
        save_menu.addAction(ic("mdi6.image-multiple-outline"), _t("Fotoğrafları çıkar (kalite kaybı olmadan)..."),
                            self.extract_photos_dialog)
        save_menu.addAction(ic("mdi6.clipboard-outline"), _t("Sayfayı panoya resim olarak kopyala"), self.copy_page_image)
        save_menu.addSeparator()
        save_menu.addAction(ic("mdi6.printer-outline"), _t("Yazdır...\tCtrl+P"), self.print_pdf)
        self.btn_save_more = self._tool_btn("mdi6.chevron-down", "▾", _t("Kaydetme ve dışa aktarma seçenekleri"), size=14)
        self.btn_save_more.setObjectName("toolbtnSlim")
        self.btn_save_more.setMenu(save_menu)
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_save_more)
        h.addSpacing(6)
        # (kendi cizimimiz: hazir ikonlar yandaki ince sayfa oklarinin yaninda kaba duruyordu)
        self.btn_undo = self._tool_btn("rv.undo", "↶", _t("Geri al (Ctrl+Z)"), size=20)
        self.btn_redo = self._tool_btn("rv.redo", "↷", _t("Yinele (Ctrl+Y)"), size=20)
        self.btn_undo.clicked.connect(self.undo_change)
        self.btn_redo.clicked.connect(self.redo_change)
        h.addWidget(self.btn_undo)
        h.addWidget(self.btn_redo)
        h.addSpacing(6)
        h.addWidget(self._sep())
        h.addSpacing(6)

        # sayfa: < [3] / 30 >  - sayi kutusuna yazip Enter: o sayfaya git (Ctrl+G kutuya gecer)
        self.btn_prev = self._tool_btn("mdi6.chevron-left", "◀", _t("Önceki sayfa (PgUp)"), size=20)
        self.ed_page = _PageEdit(self)
        self.ed_page.setObjectName("pageEdit")
        self.ed_page.setAlignment(Qt.AlignRight | Qt.AlignVCenter)    # rakam hep "/" isaretine yasli
        self.ed_page.setToolTip(_t("Sayfaya git: numarayı yazıp Enter'a basın (Ctrl+G)"))
        self.ed_page.submitted.connect(self._goto_typed_page)
        self.ed_page.cancelled.connect(self._page_box_cancelled)
        self.ed_page.focused.connect(self._show_page_number)
        # "/ 40": etiket degil, salt okunur AYNI tur kutu. Etiketle yazi 1 px asagida ve sikisik
        # duruyordu (kullanici: "gozumu tirmaliyor"); ayni kutu = ayni yazi satiri.
        self.lbl_page = _PageTotal()
        self.lbl_page.setObjectName("pageTotal")
        self.lbl_page.setReadOnly(True)
        self.lbl_page.setFocusPolicy(Qt.NoFocus)
        self.lbl_page.setContextMenuPolicy(Qt.NoContextMenu)
        self.lbl_page.setToolTip(self.ed_page.toolTip())
        self.lbl_page.clicked.connect(self.focus_page_box)
        self.lbl_page.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.btn_next = self._tool_btn("mdi6.chevron-right", "▶", _t("Sonraki sayfa (PgDn)"), size=20)
        self.btn_prev.clicked.connect(lambda: self.change_page(-1))
        self.btn_next.clicked.connect(lambda: self.change_page(1))
        # ODAK: ilk sayfaya gelince "onceki" oku devre disi kalir; Qt odagi siradaki denetime
        # (sayfa kutusuna) atiyor, kutu da kendini secili gosteriyordu (kullanici: "geri giderken
        # 1 gelince secili oluyor"). Oklar odak almaz (tuvalde kalir); kutu yalnizca tiklayinca /
        # Ctrl+G ile odak alir, Tab sirasinda ya da odak aktariminda degil.
        for b in (self.btn_prev, self.btn_next, self.btn_undo, self.btn_redo):
            b.setFocusPolicy(Qt.NoFocus)
        self.ed_page.setFocusPolicy(Qt.ClickFocus)
        pg = QHBoxLayout()                     # (kendi icinde bosluksuz: araliklar hesapli)
        pg.setContentsMargins(0, 0, 0, 0)
        pg.setSpacing(0)
        pg.addWidget(self.ed_page)
        pg.addWidget(self.lbl_page)
        h.addWidget(self.btn_prev)
        h.addLayout(pg)
        h.addWidget(self.btn_next)

        # ---------------- ORTA: modlar (yerlesimde degil: _place_mode_seg tuvalin ortasina koyar)
        # "Yeni metin" ayri mod dugmesi degil: Metin'in arac satirinda (Sec | Yeni metin).
        # Ic durum yine self.mode == "text" / "insert".
        # DUZENLE = eski "Metin" + "Sekil" (2026-10-05): sayfada ZATEN olan yazi ve cizimler tek
        # modda; Sec araci tiklanan neyse onu secer, birlikte tasinir. Ic durum hala
        # self.mode == "text" / "insert" / "shape" (secime gore kendiliginden degisir).
        self.btn_mode_text = self._make_seg("segL", "mdi6.square-edit-outline", _t("Düzenle"),
                                            _t("Sayfadaki yazıları, şekilleri ve resimleri seç, taşı, düzenle, sil; "
                                               "yeni yazı, çizgi, kutu ekle"))
        self.btn_mode_markup = self._make_seg("segR", "mdi6.marker", _t("İşaretle"),
                                              _t("Ok, daire, kutu ve not kutusu ekle (sonradan da "
                                              "düzenlenebilir)"))
        self.btn_mode_text.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in (self.btn_mode_text, self.btn_mode_markup):
            grp.addButton(b)
        self.btn_mode_text.clicked.connect(lambda: self.set_mode("text"))
        self.btn_mode_markup.clicked.connect(lambda: self.set_mode("markup"))
        seg = QHBoxLayout()
        seg.setContentsMargins(0, 0, 0, 0)
        seg.setSpacing(0)
        seg.addWidget(self.btn_mode_text)
        seg.addWidget(self.btn_mode_markup)
        seg_w = self.mode_seg = QWidget(bar)
        seg_w.setLayout(seg)
        seg_w.adjustSize()
        # sol ve sag bolge arasinda modlara yer ayiran bosluk (serit bundan daha dar olamaz)
        self._seg_gap = QSpacerItem(seg_w.sizeHint().width() + 32, 0, QSizePolicy.MinimumExpanding,
                                    QSizePolicy.Minimum)
        h.addItem(self._seg_gap)

        # ---------------- SAG: sayfa menusu, PDF islemleri, ayarlar
        self.btn_find = self._tool_btn("mdi6.magnify", _t("Bul"), _t("Bul ve değiştir (Ctrl+F)"), size=20)
        self.btn_find.clicked.connect(lambda: self.find_close() if self.find_active() else self.find_open())
        h.addWidget(self.btn_find)
        self.btn_page = self._tool_btn("mdi6.file-outline", _t("Sayfa"), _t("Sayfa işlemleri"), text=_t("Sayfa"), size=18)
        self.btn_page.clicked.connect(
            lambda: self._page_menu(self.current_page).exec(
                self.btn_page.mapToGlobal(self.btn_page.rect().bottomLeft())))
        h.addWidget(self.btn_page)

        # ("PDF Islemleri" cok genel bir addi: programin tamami zaten PDF islemi -> "Araclar")
        self.btn_more = self._tool_btn("mdi6.toolbox-outline", _t("Araçlar"),
                                       _t("Birleştir, ayır, filigran, form, OCR"), text=_t("Araçlar"), size=18)
        menu = QMenu(self)
        menu.addAction(ic("mdi6.call-merge"), _t("PDF Birleştir"), self.open_merge_dialog)
        menu.addAction(ic("mdi6.call-split"), _t("PDF Ayır"), self.open_split_dialog)
        menu.addAction(ic("mdi6.image-multiple-outline"), _t("Resimlerden PDF oluştur..."), self.open_images_to_pdf)
        menu.addSeparator()
        menu.addAction(ic("mdi6.watermark"), _t("Filigran ekle..."), self.open_watermark_dialog)
        menu.addAction(ic("mdi6.form-textbox"), _t("Form doldur..."), self.open_form_dialog)
        menu.addAction(ic("mdi6.text-recognition"), _t("OCR — taranmış sayfayı metne çevir..."), self.open_ocr_dialog)
        menu.addSeparator()
        menu.addAction(ic("mdi6.stamper"), _t("İşaretlemeleri sayfaya işle..."), self.flatten_markups_dialog)
        menu.addSeparator()
        self._act_pw_set = menu.addAction(ic("mdi6.lock-outline"), _t("Parola koy..."), self.set_password_dialog)
        self._act_pw_del = menu.addAction(ic("mdi6.lock-open-variant-outline"), _t("Parolayı kaldır"), self.remove_password)

        def _pw_menu():
            has = bool(self.engine.doc is not None and self.engine.password)
            self._act_pw_set.setText(_t("Parolayı değiştir...") if has else _t("Parola koy..."))
            self._act_pw_del.setVisible(has)
        menu.aboutToShow.connect(_pw_menu)
        self.btn_more.setMenu(menu)
        h.addWidget(self.btn_more)

        self.btn_settings = self._tool_btn("mdi6.cog-outline", _t("Ayarlar"), _t("Ayarlar (Ctrl+,)"), size=20)
        self.btn_settings.clicked.connect(self.open_settings)
        h.addWidget(self.btn_settings)
        return bar

    def _place_mode_seg(self):
        """Mod dugmelerini TUVALIN ortasina hizala (altindaki yuzen arac seritleriyle ayni
        eksen); sol / sag bolgeye binmeyecek sekilde ayrilan bosluga sigdir."""
        seg = getattr(self, "mode_seg", None)
        if seg is None or self.topbar.isHidden():
            return
        gap = self._seg_gap.geometry()
        w, hh = seg.sizeHint().width(), seg.sizeHint().height()
        vp = self.scroll.viewport()                        # yuzen seritler de buna gore ortalanir
        cx = vp.mapTo(self.centralWidget(), QPoint(vp.width() // 2, 0)).x() if vp.isVisible() \
            else self.topbar.width() // 2
        x = max(gap.left() + 16, min(cx - w // 2, gap.right() - 16 - w))
        seg.setGeometry(x, (self.topbar.height() - hh) // 2, w, hh)
        seg.raise_()

    def _goto_typed_page(self, text):
        """Sayfa kutusuna yazilan numaraya git; gecersizse kutu eski degerine doner."""
        n = self.engine.page_count()
        try:
            want = int(text.strip())
        except ValueError:
            want = None
        if want is not None and n:
            self.goto_page(max(1, min(want, n)) - 1)
        self._show_page_number()
        self.canvas.setFocus()

    def _page_box_cancelled(self, by_escape):
        if by_escape:
            self.canvas.setFocus()              # (odak cikinca kutu kendiliginden eski degerine doner)
        else:
            self._show_page_number()

    PAGE_SEP = "\u2009\u2009\u2009"   # "/" ile toplam arasi (ince bosluklar; olcumle ayarlandi)
    PAGE_EDIT_PAD = 0              # yazilabilir kutunun solundaki ek pay
    PAGE_TOTAL_PAD = 2             # toplamin sagindaki ek pay

    def _show_page_number(self):
        n = self.engine.page_count()
        if not self.ed_page.hasFocus():
            self.ed_page.setText(str(self.current_page + 1) if n else "")
        # "3 / 40": rakam - egik cizgi - toplam arasi ESIT bosluk (PAGE_GAP ekran pikseli)
        total = f"/{self.PAGE_SEP}{n}" if n else ""
        self.lbl_page.setText(total)
        # ilk / son sayfada o yondeki ok soluk (geri al / yinele ile ayni dil)
        self.btn_prev.setEnabled(n > 0 and self.current_page > 0)
        self.btn_next.setEnabled(n > 0 and self.current_page < n - 1)
        fm = self.ed_page.fontMetrics()
        # Kutu, gosterirken yazdigi rakam kadar genis (seridin sol-sag dengesi bozulmasin);
        # tiklaninca en uzun sayfa numarasi sigacak kadar acilir.
        # ic pay: solda cerceve 1 + QSS 2 + Qt'nin yazi payi 2 = 5, sagda 1 + 0 + 2 = 3
        shown = "0" * len(str(n)) if self.ed_page.hasFocus() else (self.ed_page.text() or "0")
        # Rakamlarin sag boslugu farkli ("1" genis, "7" / "8" dar): "/" isaretine uzaklik hep
        # ayni olsun diye fark, kutunun sag yazi payina eklenir.
        last = (self.ed_page.text() or "0")[-1]
        extra = max(0, max(fm.rightBearing(c) for c in "0123456789") - fm.rightBearing(last))
        self.ed_page.setTextMargins(0, 0, extra, 0)
        self.ed_page.setFixedWidth(fm.horizontalAdvance(shown) + 8 + extra + self.PAGE_EDIT_PAD)
        self.lbl_page.setFixedWidth(fm.horizontalAdvance(total) + 6 + self.PAGE_TOTAL_PAD)

    def focus_page_box(self):
        if self.engine.doc is not None:
            self.ed_page.setFocus()
            self.ed_page.selectAll()

    def _build_inspector(self):
        panel = QWidget()
        panel.setObjectName("inspector")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(16, 16, 16, 16)
        outer.setSpacing(12)

        self.lbl_panel_title = QLabel(_t("Düzenle"))
        self.lbl_panel_title.setObjectName("panelTitle")
        outer.addWidget(self.lbl_panel_title)

        self.lbl_hint = QLabel("")
        self.lbl_hint.setObjectName("hint")
        self.lbl_hint.setWordWrap(True)
        outer.addWidget(self.lbl_hint)

        # ---------------- metin ----------------
        self.w_selected = QWidget()
        sv = QVBoxLayout(self.w_selected)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(4)
        sv.addWidget(self._field(_t("Seçili metin")))
        self.txt_selected = QLineEdit()
        self.txt_selected.setReadOnly(True)
        sv.addWidget(self.txt_selected)
        outer.addWidget(self.w_selected)

        self.w_new = QWidget()
        nv = QVBoxLayout(self.w_new)
        nv.setContentsMargins(0, 0, 0, 0)
        nv.setSpacing(4)
        self.lbl_new = self._field(_t("Yeni metin"))
        nv.addWidget(self.lbl_new)
        self.txt_new = QTextEdit()
        self.txt_new.setAcceptRichText(False)
        self.txt_new.setFixedHeight(110)
        self.txt_new.setPlaceholderText(_t("Enter: yeni satır · Ctrl+Enter: uygula"))
        self.txt_new.textChanged.connect(self.canvas.update)
        nv.addWidget(self.txt_new)
        outer.addWidget(self.w_new)

        self.settings_box = QGroupBox(_t("Yazı ayarları"))
        sl = QGridLayout(self.settings_box)
        sl.setHorizontalSpacing(10)
        sl.setVerticalSpacing(4)
        self.spin_size = QDoubleSpinBox()
        self.spin_size.setRange(1, 400)
        self.spin_size.setValue(11)
        self.combo_font = QComboBox()
        self.combo_font.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo_font.setMinimumContentsLength(8)
        self.combo_font.addItem(_t("Otomatik (orijinal)"), None)
        for display_name, key in FONT_DISPLAY_NAMES:
            self.combo_font.addItem(display_name, key)
        self.spin_opacity = QSpinBox()
        self.spin_opacity.setRange(1, 100)
        self.spin_opacity.setValue(100)
        self.spin_opacity.setSuffix(" %")
        self.spin_opacity.setToolTip(_t("Saydamlık. Filigranlar genelde %20-30 civarındadır; "
                                     "düzenlerken orijinal değer korunur."))
        self.spin_spacing = QDoubleSpinBox()
        self.spin_spacing.setRange(0.8, 4.0)
        self.spin_spacing.setSingleStep(0.1)
        self.spin_spacing.setValue(1.2)
        self.spin_spacing.setToolTip(_t("Çok satırlı metinde satırlar arası mesafe (yazı boyutunun katı)"))
        sl.addWidget(self._field(_t("Boyut")), 0, 0)
        sl.addWidget(self._field(_t("Yazı tipi")), 0, 1)
        sl.addWidget(self.spin_size, 1, 0)
        sl.addWidget(self.combo_font, 1, 1)
        sl.addWidget(self._field(_t("Opaklık")), 2, 0)
        sl.addWidget(self._field(_t("Satır aralığı")), 2, 1)
        sl.addWidget(self.spin_opacity, 3, 0)
        sl.addWidget(self.spin_spacing, 3, 1)
        self.chk_bold = self._bar_btn("mdi6.format-bold", _t("Kalın"))
        self.chk_autofit = self._bar_btn("mdi6.arrow-collapse-horizontal",
                                         _t("Kutuya sığdır: yeni metin eski yerinden genişse boyutu küçültür"))
        sl.addWidget(self.chk_bold, 4, 0)
        sl.addWidget(self.chk_autofit, 4, 1)
        sl.addWidget(self._field(_t("Yazı rengi")), 5, 0)
        self.btn_color = markup_bar.SwatchButton((0, 0, 0), _t("Yazı rengi"), glyph="A")
        self.btn_color.changed.connect(self._on_text_color)
        sl.addWidget(self.btn_color, 6, 0, 1, 2)
        # dondurme: 90 sola / aci / 90 saga (tutamac: yazinin ustundeki yuvarlak nokta)
        sl.addWidget(self._field(_t("Döndür (saat yönünde)")), 7, 0, 1, 2)
        self.w_text_rot = QWidget()
        rl = QHBoxLayout(self.w_text_rot)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(4)
        self.btn_text_rot_l = self._bar_btn("mdi6.rotate-left", _t("90° sola döndür"), checkable=False)
        self.spin_text_angle = QSpinBox()
        self.spin_text_angle.setRange(-180, 180)
        self.spin_text_angle.setWrapping(True)
        self.spin_text_angle.setSuffix("°")
        self.spin_text_angle.setToolTip(_t("Açıyı yazıp Enter'a basın · tutamaçla döndürürken Shift: 15° adım"))
        self.btn_text_rot_r = self._bar_btn("mdi6.rotate-right", _t("90° sağa döndür"), checkable=False)
        rl.addWidget(self.btn_text_rot_l)
        rl.addWidget(self.spin_text_angle, 1)
        rl.addWidget(self.btn_text_rot_r)
        sl.addWidget(self.w_text_rot, 8, 0, 1, 2)
        self.btn_text_rot_l.clicked.connect(lambda: self._rotate_text_by(-90))
        self.btn_text_rot_r.clicked.connect(lambda: self._rotate_text_by(90))
        self.spin_text_angle.editingFinished.connect(self._text_angle_entered)
        # Surgu (▾) ve fare tekerlegi CANLI dondursun, TUTAMACLA dondurmedeki gibi akici:
        # deger degistikce sadece ONIZLEME cizilir (yazinin kendisi yeni aciyla; PDF'e
        # dokunulmaz), degisim durunca (300 ms) tek seferde uygulanir. Her ara degerde
        # gercekten dondurmek (PDF'i yeniden yaz + sayfayi ciz) surguyu takiltiyordu.
        # Elle yazarken her rakamda degil Enter'da uygulansin diye klavye takibi kapali.
        self.spin_text_angle.setKeyboardTracking(False)
        self._text_angle_busy = False
        self._text_angle_timer = QTimer(self)
        self._text_angle_timer.setSingleShot(True)
        self._text_angle_timer.setInterval(300)
        self._text_angle_timer.timeout.connect(self._text_angle_commit)
        self.spin_text_angle.valueChanged.connect(self._text_angle_live)
        sl.setColumnStretch(1, 1)
        for w in (self.spin_size, self.spin_opacity, self.spin_spacing):
            w.valueChanged.connect(self.canvas.update)
        self.combo_font.currentIndexChanged.connect(self.canvas.update)
        self.chk_bold.toggled.connect(self.canvas.update)
        outer.addWidget(self.settings_box)

        self.btn_apply = QPushButton(_t("Değişikliği uygula"))
        self.btn_apply.setObjectName("primary")
        self.btn_apply.setToolTip("Ctrl+Enter")
        ap_icon = ic("fa5s.check", "#ffffff")
        if not ap_icon.isNull():
            self.btn_apply.setIcon(ap_icon)
        self.btn_apply.clicked.connect(self.apply_change)
        outer.addWidget(self.btn_apply)

        self.btn_delete = QPushButton(_t("Seçili metni sil"))
        self.btn_delete.setObjectName("danger")
        del_icon = ic("fa5s.trash", "#dc2626")
        if not del_icon.isNull():
            self.btn_delete.setIcon(del_icon)
        self.btn_delete.setToolTip(_t("Kısayol: Delete tuşu. Alttaki/üstteki yazılara dokunmaz."))
        self.btn_delete.clicked.connect(self.delete_selected)
        outer.addWidget(self.btn_delete)

        # ---------------- cizgi / kutu ----------------
        self.w_tools = QWidget()
        tl = QHBoxLayout(self.w_tools)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.setSpacing(0)
        self.btn_tool_select = self._bar_btn("mdi6.cursor-default-outline", _t("Seç / taşı  (V)"))
        self.btn_tool_line = self._bar_btn("mdi6.minus", _t("Çizgi  (L)"))
        self.btn_tool_rect = self._bar_btn("mdi6.rectangle-outline", _t("Kutu  (K)"))
        self.btn_tool_ellipse = self._bar_btn("mdi6.circle-outline", _t("Daire  (D)"))
        self.btn_tool_select.setChecked(True)
        tg = QButtonGroup(self)
        tg.setExclusive(True)
        for b, t in ((self.btn_tool_select, "select"), (self.btn_tool_line, "line"),
                     (self.btn_tool_rect, "rect"), (self.btn_tool_ellipse, "ellipse")):
            tg.addButton(b)
            tl.addWidget(b)
            b.clicked.connect(lambda _=False, t=t: self.set_shape_tool(t))
        # arac dugmeleri basligin hemen altinda, aciklamanin USTUNDE: aciklama
        # araca gore 1-4 satir degistigi icin altta kalinca dugmeleri itiyordu
        outer.insertWidget(outer.indexOf(self.lbl_hint), self.w_tools)

        self.sel_box = QGroupBox(_t("Seçim"))
        gl = QGridLayout(self.sel_box)
        gl.setHorizontalSpacing(10)
        gl.setVerticalSpacing(4)
        self.lbl_sel_info = QLabel("")
        self.lbl_sel_info.setWordWrap(True)
        gl.addWidget(self.lbl_sel_info, 0, 0, 1, 2)
        self.coord_labels = []
        self.coord_spins = []
        for i in range(4):
            lab = self._field("")
            sp = QDoubleSpinBox()
            sp.setRange(-5000, 5000)
            sp.setDecimals(2)
            sp.setSingleStep(0.5)
            self.coord_labels.append(lab)
            self.coord_spins.append(sp)
            r, c = 1 + (i // 2) * 2, i % 2
            gl.addWidget(lab, r, c)
            gl.addWidget(sp, r + 1, c)
        self.btn_coord_apply = QPushButton(_t("Konumu uygula"))
        self.btn_coord_apply.clicked.connect(self.apply_coords)
        gl.addWidget(self.btn_coord_apply, 5, 0, 1, 2)
        # (sel_box, stil kutusunun ALTINA eklenir - asagiya bak)

        self.style_box = QGroupBox(_t("Çizgi stili"))
        stl = QGridLayout(self.style_box)
        stl.setHorizontalSpacing(10)
        stl.setVerticalSpacing(4)
        stl.addWidget(self._field(_t("Kalınlık (pt)")), 0, 0)
        stl.addWidget(self._field(_t("Renk")), 0, 1)
        self.spin_width = QDoubleSpinBox()
        self.spin_width.setRange(0.05, 50)
        self.spin_width.setDecimals(2)
        self.spin_width.setSingleStep(0.25)
        self.spin_width.setValue(0.75)
        self.btn_line_color = markup_bar.SwatchButton((0, 0, 0), _t("Çizgi rengi"))
        stl.addWidget(self.spin_width, 1, 0)
        stl.addWidget(self.btn_line_color, 1, 1)
        self.chk_dashed = self._bar_btn("mdi6.format-line-style", _t("Kesikli çizgi"))
        self.cmb_dash = markup_bar.dash_combo(self.dark)
        stl.addWidget(self.chk_dashed, 2, 0, 1, 2)
        self._show_shape_style()
        self.spin_width.valueChanged.connect(self._on_shape_style_edit)
        self.btn_line_color.changed.connect(self._on_shape_style_edit)
        self.chk_dashed.toggled.connect(self._on_shape_style_edit)
        self.cmb_dash.currentIndexChanged.connect(self._on_shape_style_edit)
        self.btn_style_apply = QPushButton(_t("Stili seçime uygula"))
        self.btn_style_apply.clicked.connect(self.apply_path_style)
        stl.addWidget(self.btn_style_apply, 3, 0, 1, 2)
        note = QLabel(_t("Yeni çizilen çizgiler de bu stili kullanır."))
        note.setObjectName("fieldLabel")
        note.setWordWrap(True)
        stl.addWidget(note, 4, 0, 1, 2)
        stl.setColumnStretch(1, 1)
        outer.addWidget(self.style_box)
        # hep gorunen stil kutusu ustte, sadece secimde cikan koordinat kutusu altta:
        # secim yapinca kalici ogeler yerinden kaymasin
        outer.addWidget(self.sel_box)

        self.btn_shape_delete = QPushButton(_t("Seçimi sil"))
        self.btn_shape_delete.setObjectName("danger")
        if not del_icon.isNull():
            self.btn_shape_delete.setIcon(del_icon)
        self.btn_shape_delete.setToolTip(_t("Kısayol: Delete"))
        self.btn_shape_delete.clicked.connect(self.delete_selected)
        outer.addWidget(self.btn_shape_delete)

        outer.addStretch()

        scroll = QScrollArea()
        scroll.setObjectName("inspectorScroll")
        scroll.setWidgetResizable(True)
        scroll.setWidget(panel)
        scroll.setMinimumWidth(330)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        return scroll

    def _build_mode_bars(self):
        """Metin / Yeni metin / Cizgi-Kutu icin ust seritler (Isaretle'deki gibi).
        Kontroller sag panelde kurulmustu; buraya tasinir (sag panel gizli)."""
        row1, row2 = self._bar_rows

        def compact(w, width, tip=None):
            w.setFixedWidth(width)
            if tip:
                w.setToolTip(tip)
            return w

        # ---- Cizgi / Kutu: araclar
        # (Sekil'in ayri arac seridi YOK: cizim araclari Duzenle'nin seridinde. Eski "Sec"
        # dugmesi gizli duruyor - set_shape_tool onu isaretliyor.)
        self.sh_tools_pill, l1 = markup_bar.pill()
        l1.addWidget(self.btn_tool_select)
        row1.insertWidget(row1.count() - 1, self.sh_tools_pill)
        # ---- Cizgi / Kutu: ayarlar (secim varken aninda secime uygulanir)
        self.sh_opts_pill, l2 = markup_bar.pill()
        compact(self.spin_width, 94, _t("Kalınlık (pt)"))
        self.spin_width.setSuffix(" pt")
        self._slider(self.spin_width, 0.25, 10, 4)
        for w in (self.spin_width, self.btn_line_color, self.chk_dashed, self.cmb_dash):
            l2.addWidget(w)
        # (koordinat kutulari bilerek yok: kullanici icin kafa karistirici)
        self.sh_del_sep = markup_bar.vsep(True, breakable=False)
        l2.addWidget(self.sh_del_sep)
        self.btn_sh_delete = self._bar_btn("mdi6.delete-outline", _t("Sil (Delete)"), checkable=False)
        self.btn_sh_delete.setObjectName("mkToolDanger")
        self.btn_sh_delete.clicked.connect(self.delete_selected)
        l2.addWidget(self.btn_sh_delete)
        row2.insertWidget(row2.count() - 1, self.sh_opts_pill)

        # ---- Metin: araclar (Sec / duzenle | Yeni metin) - diger modlardaki gibi 1. satir
        self.tx_tools_pill, ltt = markup_bar.pill()
        self.btn_tx_select = self._bar_btn(
            "mdi6.cursor-default-outline",
            _t("Seç  (V) — yazıya, şekle ya da resme tıklayın; Shift + tık ya da alan çizerek birden çok seçin"))
        self.btn_tx_new = self._bar_btn("mdi6.text-box-plus-outline", _t("Yeni metin ekle  (T)"))
        self.btn_tx_select.setChecked(True)
        ttg = QButtonGroup(self)
        ttg.setExclusive(True)
        for b, m in ((self.btn_tx_select, "text"), (self.btn_tx_new, "insert")):
            ttg.addButton(b)
            ltt.addWidget(b)
            b.clicked.connect(lambda _=False, m=m: self.set_mode(m))
        for b in (self.btn_tool_line, self.btn_tool_rect, self.btn_tool_ellipse):   # cizim araclari
            ttg.addButton(b)               # (ayni grupta: hep TEK arac isaretli)
            ltt.addWidget(b)
        # akilli kilavuzlar: tasirken diger yazilarin hizasina oturt (Alt: o an icin tersi)
        ltt.addWidget(markup_bar.vsep())
        # (ikon: markup_bar'da cizilen egik miknatis - hazir ikonlar "U" gibi / kesik duruyordu)
        self.btn_tx_snap = self._bar_btn(
            "rv.magnet", _t("Hizaya oturt: taşırken diğer yazıların hizasına yapışır "
                                 "(Alt basılıyken geçici olarak tersi)"))
        self.text_snap = self._settings.value("text_snap", True, type=bool)
        self.btn_tx_snap.setChecked(self.text_snap)
        self.btn_tx_snap.toggled.connect(self._set_text_snap)
        ltt.addWidget(self.btn_tx_snap)
        row1.insertWidget(row1.count() - 1, self.tx_tools_pill)

        # ---- Metin: yazi ayarlari (secili metin / yeni metin) - 2. satir
        self.tx_opts_pill, lt = markup_bar.pill()
        compact(self.combo_font, 150, _t("Yazı tipi"))
        compact(self.spin_size, 96, _t("Yazı boyutu"))
        self.spin_size.setSuffix(" pt")
        compact(self.spin_opacity, 80, _t("Opaklık"))
        compact(self.spin_spacing, 86, _t("Satır aralığı (yazı boyutunun katı)"))
        self.spin_spacing.setPrefix("↕ ")
        self._slider(self.spin_size, 4, 96, 2)
        self._slider(self.spin_opacity, 1, 100, 1)
        self._slider(self.spin_spacing, 0.8, 4.0, 10)
        # hizalama: sola / ortaya / saga (mevcut yazi degisince hangi ucu sabit kalsin;
        # yeni metinde tiklanan nokta yazinin basi / ortasi / sonu)
        self.align_btns = {}
        ag = QButtonGroup(self)
        ag.setExclusive(True)
        for key, icon_name, tip in (("left", "mdi6.format-align-left", _t("Sola dayalı")),
                                    ("center", "mdi6.format-align-center", _t("Ortalı")),
                                    ("right", "mdi6.format-align-right", _t("Sağa dayalı"))):
            b = self._bar_btn(icon_name, tip)
            ag.addButton(b)
            b.clicked.connect(lambda _=False, k=key: self._set_text_align(k))
            self.align_btns[key] = b
        self.text_align = self._settings.value("text_align", "left", type=str)
        if self.text_align not in self.align_btns:
            self.text_align = "left"
        self.align_btns[self.text_align].setChecked(True)
        # gruplar (kalin ayirici): yazi gorunumu || paragraf (satir araligi, hiza, sigdir)
        # || aci || duzenle/sil. Dondurme oklari yok: aci kutusu (▾ surgu) yeterli.
        for w in (self.combo_font, self.spin_size, self.chk_bold, self.btn_color, self.spin_opacity,
                  markup_bar.vsep(True), self.spin_spacing, self.align_btns["left"],
                  self.align_btns["center"], self.align_btns["right"], self.chk_autofit):
            lt.addWidget(w)
        self.tx_rot_box, lr = markup_bar.group()
        lr.addWidget(markup_bar.vsep(True))
        compact(self.spin_text_angle, 82)
        self._slider(self.spin_text_angle, -180, 180, 1)
        lr.addWidget(self.spin_text_angle)
        lt.addWidget(self.tx_rot_box)
        self.tx_edit_box, le = markup_bar.group()
        le.addWidget(markup_bar.vsep(True))
        self.btn_tx_edit = self._bar_btn("mdi6.pencil-outline", _t("Yazıyı sayfada düzenle (çift tık / F2)"),
                                         checkable=False)
        self.btn_tx_edit.clicked.connect(lambda: self._text_edit_begin())
        self.btn_tx_delete = self._bar_btn("mdi6.delete-outline", _t("Sil (Delete)"), checkable=False)
        self.btn_tx_delete.setObjectName("mkToolDanger")
        self.btn_tx_delete.clicked.connect(self.delete_selected)
        le.addWidget(self.btn_tx_edit)
        le.addWidget(self.btn_tx_delete)
        lt.addWidget(self.tx_edit_box)
        row2.insertWidget(row2.count() - 1, self.tx_opts_pill)

        # ayar degisince: secili metne / secili cizgilere ANINDA uygula (kisa gecikmeyle)
        self._text_loading = False
        self._text_style_timer = QTimer(self)
        self._text_style_timer.setSingleShot(True)
        self._text_style_timer.setInterval(450)
        self._text_style_timer.timeout.connect(self._apply_text_style)
        for w in (self.spin_size, self.spin_opacity, self.spin_spacing):
            w.valueChanged.connect(self._on_text_style)
        self.combo_font.currentIndexChanged.connect(self._on_text_style)
        self.chk_bold.toggled.connect(self._on_text_style)
        self.btn_color.changed.connect(self._on_text_style)
        self._shape_style_timer = QTimer(self)
        self._shape_style_timer.setSingleShot(True)
        self._shape_style_timer.setInterval(350)
        self._shape_style_timer.timeout.connect(self._apply_shape_style_now)

        # metin yazma kutusu: sayfanin USTUNDE (notlardaki gibi); sag panelde yazmak yok
        self.txt_new.setParent(self.canvas)
        # (mkInlineEdit: renk QSS'ten degil paletten - yazi kendi rengiyle gorunsun)
        self.txt_new.setObjectName("mkInlineEdit")
        self.txt_new.setMinimumHeight(0)
        self.txt_new.setMaximumHeight(16777215)
        self.txt_new.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_new.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_new.setPlaceholderText(_t("Yazın…"))
        self.txt_new.hide()
        self._tx_live = False                  # yazarken yaziyi PDF motoru mu ciziyor (bkz. _tx_begin_live)
        self._tx_box = False
        self._tx_live_cache = None
        self._tx_font_cache = {}
        self._tx_editor_keys = _EditorKeys(self, self._inline_text_done)
        self.txt_new.installEventFilter(self._tx_editor_keys)
        self._apply_editor_align()
        self.txt_new.textChanged.connect(self._position_text_editor)

        self.cmb_dash.setVisible(self.chk_dashed.isChecked())     # desen listesi: sadece kesikliyken
        for w in (self.sh_tools_pill, self.sh_opts_pill, self.tx_tools_pill, self.tx_opts_pill):
            w.hide()
        # satir yukseklikleri sabit: hangi mod/serit gorunurse gorunsun sayfa kaymaz
        pills = [(self.w_mk_tools, self.sh_tools_pill, self.tx_tools_pill),
                 (self.w_mk_options, self.sh_opts_pill, self.tx_opts_pill)]
        self._bar_row_base_h = [max(p.sizeHint().height() for p in group) for group in pills]
        for rc, h in zip(self._bar_row_widgets, self._bar_row_base_h):
            rc.setFixedHeight(h)
        self._bar_row_pills = pills
        # gorunur alan (maske) seritlerin GERCEK boyutunu izlesin: menu degisince serit
        # buyurse maske eski boyutta kalip yuvarlak koseleri / kenarligi kirpmasin
        self._bar_geom_watch = _GeomWatch(self._update_bar_mask)
        for group in pills:
            for p in group:
                p.installEventFilter(self._bar_geom_watch)
        for rc in self._bar_row_widgets:         # satir kayarsa serit de kayar (kendi Move'u olmadan)
            rc.installEventFilter(self._bar_geom_watch)
        # sayfanin ustundeki bos pay: iki satirin tamami (mod degisince sayfa kaymasin)
        m = self.mk_bar_host.layout().contentsMargins()
        self._bar_full_h = (m.top() + m.bottom() + self.mk_bar_host.layout().spacing()
                            + sum(rc.height() for rc in self._bar_row_widgets))

    def _set_text_align(self, key):
        self.text_align = key
        try:
            self._settings.setValue("text_align", key)
        except Exception:
            pass
        self._apply_editor_align()
        self._position_text_editor()
        self.canvas.update()

    def _apply_editor_align(self):
        opt = self.txt_new.document().defaultTextOption()
        opt.setAlignment({"left": Qt.AlignLeft, "center": Qt.AlignHCenter,
                          "right": Qt.AlignRight}[self.text_align])
        self.txt_new.document().setDefaultTextOption(opt)

    # ---------------- ust serit: aninda uygula ----------------
    def _on_text_style(self, *_):
        if self._text_loading:
            return
        if self.txt_new.isVisible():               # yazarken ayar degisti: kutu da uysun
            self._tx_editor_color()
        if self.mode == "insert":
            self._position_text_editor()
            self.canvas.update()
        elif self.mode == "text" and self.current_span is not None and not self.txt_new.isVisible():
            self._text_style_timer.start()
        elif self.txt_new.isVisible():
            self._position_text_editor()

    def _apply_text_style(self):
        if self.mode == "text" and self.current_span is not None and not self.txt_new.isVisible():
            self.apply_change()

    def _apply_shape_style_now(self):
        if self.mode == "shape" and self.sel_paths:
            self.apply_path_style()

    # ---------------- sayfa ustunde metin yazma ----------------
    def _text_edit_begin(self, select_all=True, at=None):
        """Secili metni (Metin modu) ya da yeni metni (Yeni metin modu) sayfanin
        ustunde duzenle.
        at (sayfa noktasi): CIFT TIK - imlec tiklanan harfin yanina konur, secim yapilmaz
        (uzun cumlede tek harf duzeltmek icin; kutu yazinin tam ustunde oldugundan tiklanan
        yer harfe birebir denk gelir). at yoksa (F2 / Enter / kalem dugmesi) select_all:
        tum yazi secili gelir, yazinca tamamen degisir (tarih / sayi degistirmek icin)."""
        if self.mode == "text":
            sp = self.current_span
            if sp is None:
                return
            self._text_loading = True
            try:
                self.txt_new.setPlainText(sp.text.replace("\xa0", " "))
            finally:
                self._text_loading = False
        elif self.mode != "insert" or self.pending_insert is None:
            return
        self.txt_new.show()
        self._tx_begin_live()
        self._tx_editor_color()
        self._position_text_editor()
        self.txt_new.raise_()
        self.txt_new.setFocus()
        ed = self.txt_new
        sp = self.current_span if self.mode == "text" else None
        if at is not None and sp is not None and not sp.rotated:
            pos = self.canvas.to_px(at)
            vp = ed.viewport()
            local = QPoint(int(pos.x()) - ed.x() - vp.x(), int(pos.y()) - ed.y() - vp.y())
            local.setY(max(1, min(local.y(), vp.height() - 2)))
            ed.setTextCursor(ed.cursorForPosition(local))
        elif at is not None:
            cur = ed.textCursor()
            cur.movePosition(QTextCursor.End)
            ed.setTextCursor(cur)
        elif select_all:
            ed.selectAll()
        self.canvas.update()

    # ------------------------------------------------ canli (WYSIWYG) duzenleme
    def editing_live(self):
        return getattr(self, "_tx_live", False) and self.txt_new.isVisible()

    def _tx_begin_live(self):
        """Yazarken gorunen yaziyi Qt degil PDF MOTORU cizsin (text_preview): ekrandaki,
        kaydedilecek olanin aynisi olur - duzenlemeye girince yazi buyuyup kaymaz, beyaz
        kutu yok, alttaki filigran / cizgiler gorunur. QTextEdit gorunmez kalir (yazisi
        saydam); sadece klavye, imlec ve secim icin. Orijinal yazi duzenleme boyunca
        sayfadan kaldirilir (suruklemedeki nesnesiz arka plan: canvas.bg).
        DONUK YAZI: sayfadaki yazi yine canli ve KENDI ACISIYLA cizilir; ama yazma kutusu
        yatay ve gorunur kalir (_tx_box), yazinin ustune degil yanina konur - egik / ters
        yaziyi yerinde yazmak zor, imlec ve secim de egik calismaz.
        Donuk sayfa / arka plan uretilemezse eski yonteme (sadece opak kutu) dusulur."""
        ed = self.txt_new
        live = False
        self._tx_live_cache = None
        self._tx_font_cache = {}
        try:
            flat = self.engine.doc[self.current_page].rotation == 0
        except Exception:
            flat = False
        self._tx_live = False
        self._tx_box = False                  # canli + ayri yatay yazma kutusu (donuk yazi)
        if flat and self.mode == "text" and self.current_span is not None:
            self._ghost_end()
            self._ghost_text(self.current_span)
            live = self.canvas.bg is not None
            self._tx_box = live and self.current_span.rotated
        elif flat and self.mode == "insert" and self.pending_insert is not None:
            live = True
        self._tx_live = live
        name = "mkInlineLive" if live and not self._tx_box else "mkInlineEdit"
        if ed.objectName() != name:
            ed.setObjectName(name)
            ed.style().unpolish(ed)
            ed.style().polish(ed)             # (yazi tipini sifirlar; _position_text_editor yeniden kurar)
        ed.setLineWrapMode(QTextEdit.NoWrap)  # yazi asla kendiliginden alt satira gecmez

    def _tx_end_live(self):
        if getattr(self, "_tx_live", False):
            self._tx_live = False
            self._tx_live_cache = None
            self._ghost_end()

    def _tx_spacing(self):
        """Satir araligi: kutudaki deger; ama kullanici degistirmediyse paragrafin GERCEK
        araligi. Kutu iki ondaliga yuvarlar (1,2083 -> 1,21): yuvarlanmis degerle yazilinca
        alt satirlar her duzenlemede azicik kayiyordu."""
        v = self.spin_spacing.value()
        sp = self.current_span if self.mode == "text" else None
        real = getattr(sp, "line_spacing", None)
        if real and abs(round(real, 2) - v) < 0.005:
            return real
        return v

    def _tx_params(self):
        """Yazilan metnin NASIL yazilacagi (apply_change / engine.apply_edit ile ayni kurallar)."""
        eng = self.engine
        text = self.txt_new.toPlainText()
        choice, bold = self.combo_font.currentData(), self.chk_bold.isChecked()
        cache = self.__dict__.setdefault("_tx_font_cache", {})
        if self.mode == "text" and self.current_span is not None:
            sp = self.current_span
            key = ("t", id(sp), choice, bold)
            if key not in cache:
                cache[key] = eng._font_obj_for(eng.doc[sp.page_num], sp, bold, choice)[0]
            fo = cache[key]
            size = self.spin_size.value() or sp.size
            if self.chk_autofit.isChecked() and text.strip():
                size = eng._fit_size(fo, text, sp.bbox, size, sp)
            q = sp.quad()
            align = self.text_align
            if hasattr(sp, "lines") and align == "left":
                align = sp.align
            return {"font": fo, "key": key, "size": size, "color": self.selected_color or sp.color_rgb(),
                    "align": align, "ref": abs(q[1] - q[0]) if align != "left" else None,
                    "origin": fitz.Point(sp.origin), "angle": eng.span_angle(sp) if sp.rotated else 0.0}
        if self.mode == "insert" and self.pending_insert is not None:
            key = ("i", choice, bold)
            if key not in cache:
                cache[key] = eng._font_from_hint(choice or "Arial", bold)[0]
            _, x, y = self.pending_insert
            return {"font": cache[key], "key": key, "size": self.spin_size.value(),
                    "color": self.selected_color or (0, 0, 0), "align": self.text_align, "ref": None,
                    "origin": fitz.Point(x, y), "angle": 0.0}
        return None

    def _tx_live_pix(self):
        """(pixmap, x, y, box): x, y = goruntunun sol-ustu, sayfa goruntusune gore mantiksal
        piksel; box = yazinin donmemis kutusu (origin'e gore, mantiksal px); onbellekli.
        Yazi bossa None."""
        P = self._tx_params()
        if P is None:
            return None
        cv = self.canvas
        text = self.txt_new.toPlainText()
        scale = cv.zoom * cv.dpr
        opacity, spacing = self.spin_opacity.value() / 100, self._tx_spacing()
        dev = (P["origin"].x * scale, P["origin"].y * scale)     # origin, sayfa goruntusunde (px)
        key = (text, round(P["size"], 3), tuple(P["color"]), opacity, spacing, P["align"], P["ref"],
               P["key"], round(scale, 4), round(dev[0] % 1.0, 3), round(dev[1] % 1.0, 3),
               round(P["angle"], 3))
        c = getattr(self, "_tx_live_cache", None)
        if c is not None and c[0] == key:
            return c[1]
        res = self.engine.text_preview(text, P["font"], P["size"], P["color"], opacity, spacing,
                                       P["align"], P["ref"], scale, origin_dev=dev, angle=P["angle"])
        out = None
        if res is not None:
            pix, ox, oy, box = res
            img = QImage(pix.samples, pix.width, pix.height, pix.stride,
                         QImage.Format_RGBA8888_Premultiplied).copy()
            pm = QPixmap.fromImage(img)
            pm.setDevicePixelRatio(cv.dpr)
            # sol-ust kose sayfa goruntusunde TAM piksele denk gelir (origin_dev sayesinde)
            out = (pm, round(dev[0] - ox) / cv.dpr, round(dev[1] - oy) / cv.dpr,
                   tuple(v / cv.dpr for v in box))
        self._tx_live_cache = (key, out)
        return out

    def _paint_tx_live(self, p, cv):
        P = self._tx_params()
        if P is None:
            return
        res = self._tx_live_pix()
        if res is None:
            return
        pm, x, y, box = res                    # sayfa goruntusunun sol-ustune gore (mantiksal px)
        p.drawPixmap(QPointF(x, y + cv.pad_top), pm)
        # duzenlendigini belli eden ince cerceve (kutu / arka plan degil); yaziyla ayni acida
        o = cv.to_px(P["origin"])
        p.save()
        p.translate(o)
        p.rotate(P["angle"])
        p.setPen(self._pen(ACCENT, 1, Qt.SolidLine, 150))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(QRectF(*box), 3, 3)
        p.restore()

    def _tx_editor_color(self):
        """Yazma kutusundaki yazi, PDF'teki yazinin KENDI renginde gorunsun.

        Renk metnin bicimi olarak verilir: stil sayfasiyla verilince Qt setFont'u yok
        sayiyor, paletle verilince genel QSS "QTextEdit { color }" paleti eziyor.
        DIKKAT: textChanged icinden (yazarken) CAGIRMA - belge degisirken bicim
        degistirmek Qt'yi cokertiyor. Sadece duzenleme baslarken / renk secilince."""
        ed = self.txt_new
        if self.mode == "text" and self.current_span is not None:
            color = self.selected_color or self.current_span.color_rgb()
        else:
            color = self.selected_color or (0, 0, 0)
        # cok acik renkli yazi beyaz kutuda gorunmez: o zaman koyu goster
        lum = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        col = QColor.fromRgbF(*color) if lum < 0.72 else QColor("#111111")
        if getattr(self, "_tx_live", False) and not getattr(self, "_tx_box", False):
            col = QColor(0, 0, 0, 0)          # yaziyi PDF motoru ciziyor; kutudaki yazi gorunmez
        fmt = QTextCharFormat()
        fmt.setForeground(col)
        # satir araligi: PDF'teki ile AYNI (yazi boyutu x "Satir araligi"). Qt'nin kendi
        # araligi daha dar: cok satirli yazida kutu kisa kaliyor, alttaki satir ve secim
        # cercevesi kutunun altindan tasiyordu.
        bf = QTextBlockFormat()
        bf.setLineHeight(self._tx_line_px(), QTextBlockFormat.FixedHeight.value)
        ed.blockSignals(True)
        try:
            cur = QTextCursor(ed.document())
            cur.select(QTextCursor.Document)
            cur.mergeCharFormat(fmt)
            cur.mergeBlockFormat(bf)
            ed.mergeCurrentCharFormat(fmt)        # bundan sonra yazilanlar da ayni renkte
        finally:
            ed.blockSignals(False)

    def _tx_box_px(self):
        """Donuk yazinin ayri yazma kutusunda yazi boyutu (ekran px): gercek boyuta yakin ama
        hep okunakli."""
        sp = self.current_span
        size = (self.spin_size.value() or (sp.size if sp is not None else 11))
        return max(14.0, min(24.0, size * self.canvas.zoom))

    def _tx_line_px(self):
        """Yazma kutusunda bir satirin yuksekligi (ekran px) = boyut x satir araligi x zoom."""
        if self.mode == "text" and self.current_span is not None:
            size = self.spin_size.value() or self.current_span.size
        else:
            size = self.spin_size.value()
        if getattr(self, "_tx_box", False):        # donuk yazi: ayri kutu, okunakli sabit boyut
            return self._tx_box_px() * 1.3
        if getattr(self, "_tx_live", False):       # canli: gercek boyut (otomatik sigdirma dahil)
            P = self._tx_params()
            if P is not None:
                return max(1.0, P["size"] * self.canvas.zoom) * max(0.5, self._tx_spacing())
        return max(6.0, size * self.canvas.zoom) * max(0.5, self._tx_spacing())

    def _position_text_editor(self):
        """Yazma kutusunu, ICINDEKI yazinin taban cizgisi ve baslangici PDF'teki yaziyla
        CAKISACAK sekilde yerlestir (duzenlemeye girince yazi buyuyup kaymasin).

        Eskiden kutu yazinin cercevesine gore kabaca (-6, -6) konuyordu: kenarlik + ic bosluk
        + belge payi hesaba katilmadigi icin yazi birkac piksel kayiyor, boyut 11-60 px'e
        sikistirildigi ve tam piksele yuvarlandigi icin de buyuyup kuculuyordu."""
        if not self.txt_new.isVisible():
            return
        cv = self.canvas
        ed = self.txt_new
        rotated = False
        if self.mode == "text" and self.current_span is not None:
            sp = self.current_span
            q = sp.quad()
            size = self.spin_size.value() or sp.size
            fam = self.combo_font.currentText() if self.combo_font.currentData() else self._preview_family(sp.font)
            rotated = sp.rotated
            o = cv.to_px(fitz.Point(sp.origin))
            length = abs(q[1] - q[0]) * cv.zoom               # yazinin ekrandaki uzunlugu
            if rotated:                                       # donuk yazi: kutu yatay, cercevenin sol ustunde
                r = cv.rect_px(fitz.Rect(min(p.x for p in q), min(p.y for p in q),
                                         max(p.x for p in q), max(p.y for p in q)))
        elif self.mode == "insert" and self.pending_insert is not None:
            _, x, y = self.pending_insert
            size = self.spin_size.value()
            fam = self.combo_font.currentText() if self.combo_font.currentData() else "Arial"
            o = cv.to_px((x, y))
            length = 0.0
        else:
            return
        box = getattr(self, "_tx_box", False)
        live = getattr(self, "_tx_live", False) and not box
        P = self._tx_params() if live else None
        if P is not None:
            size = P["size"]                                  # (otomatik sigdirma dahil)
        px = max(6.0, size * cv.zoom) if not live else max(1.0, size * cv.zoom)
        if box:
            px = self._tx_box_px()
        f = QFont(fam)
        f.setPointSizeF(px * 72.0 / max(1, ed.logicalDpiY()))  # kesirli boyut: PDF ile ayni olcek
        f.setHintingPreference(QFont.PreferNoHinting)         # genislikler PDF cizimi gibi dogrusal
        f.setKerning(False)                                   # PDF harf ciftlerini yaklastirmaz (AV, LT...):
                                                              # acik kalirsa kutudaki yazi birkac px dar durur
        f.setBold(self.chk_bold.isChecked())
        ed.setFont(f)
        doc = ed.document()
        if doc.documentMargin() != 2:
            doc.setDocumentMargin(2)
        fm = ed.fontMetrics()
        lines = (ed.toPlainText() or " ").split(chr(10))
        if P is not None:
            # Qt'nin harf genislikleri (ozellikle kucuk boyutta, tam piksele yuvarlandigi icin)
            # PDF motorununkinden farkli: imlec ve secim harflerin tam yerine gelsin diye
            # kutunun harf araligi oranlanir (gorunmeyen yazi, gorunenle ayni genislikte).
            longest = max(lines, key=len)
            qt_w = fm.horizontalAdvance(longest)
            pdf_w = P["font"].text_length(longest, fontsize=size) * cv.zoom if longest.strip() else 0
            if qt_w > 2 and pdf_w > 2:
                f.setLetterSpacing(QFont.PercentageSpacing, 100.0 * pdf_w / qt_w)
                ed.setFont(f)
                fm = ed.fontMetrics()
        text_w = max(fm.horizontalAdvance(l) for l in lines)
        w = int((max(text_w, 120) if box else max(length, text_w)) + max(28, px * 1.2) + 12)
        line_px = self._tx_line_px()
        h = int(math.ceil(line_px * max(1, len(lines)) + 2 * doc.documentMargin() + 10))
        ed.resize(w, h)
        if rotated:
            if box:
                # yazinin USTUNE degil yanina: cercevesinin hemen ustune, sigmazsa altina
                x = int(max(4, min(r.x(), cv.width() - w - 4)))
                y = int(r.y() - h - 12)
                if y < cv.pad_top + 4:
                    y = int(r.bottom() + 12)
                ed.move(x, y)
            else:
                ed.move(int(r.x()) - 6, int(r.y()) - 6)
            return
        # Kutunun icinde ilk satirin yeri HESAPLA bulunur (kenarlik + ic bosluk = gorunum
        # alaninin kaymasi, + belge payi, + yazi tipinin cikis yuksekligi). Belgenin
        # yerlesimine (QTextLayout / setTextWidth) burada DOKUNULMAZ: bu fonksiyon yazarken
        # textChanged icinden de cagrilir; o sirada yerlesimi zorlamak Qt'yi cokertiyor.
        vp = ed.viewport().geometry()
        m = doc.documentMargin()
        first_w = fm.horizontalAdvance(lines[0]) if lines else 0
        # sabit satir yuksekliginde Qt fazladan boslugu satirin USTUNE koyar: taban cizgisi
        # satir kutusunun altindan "inis" kadar yukarida
        base_y = vp.y() + m + line_px - fm.descent()
        if self.text_align == "center":
            left = vp.x() + (vp.width() - first_w) / 2
        elif self.text_align == "right":
            left = vp.x() + vp.width() - m - first_w
        else:
            left = vp.x() + m
        right = left + first_w
        # hizalamaya gore sabit nokta: sola = yazinin basi, ortali = ortasi, saga = sonu
        if self.text_align == "center":
            x = (o.x() + length / 2) - (left + right) / 2
        elif self.text_align == "right":
            x = (o.x() + length) - right
        else:
            x = o.x() - left
        ed.move(int(round(x)), int(round(o.y() - base_y)))

    def _inline_text_done(self):
        """Yazma kutusu kapaniyor (Esc / Ctrl+Enter / baska yere tiklama): uygula."""
        self._text_angle_commit()     # (mod / sayfa degisimi oncesi de buradan gecer)
        if not self.txt_new.isVisible():
            return
        self.txt_new.hide()
        self._tx_live = False                  # (arka plan asagida, degisiklik uygulaninca kalkar)
        self.canvas.setFocus()
        text = self.txt_new.toPlainText()
        if self.mode == "text" and self.current_span is not None:
            if text != self.current_span.text.replace("\xa0", " "):
                self.apply_change()
        elif self.mode == "insert" and self.pending_insert is not None:
            if text.strip():
                self.apply_change()
            else:
                self.pending_insert = None
        self._tx_live_cache = None
        self._ghost_end()
        self.canvas.update()

    def _build_shortcuts(self):
        def sc(keys, fn, widget=None):
            s = QShortcut(QKeySequence(keys), widget or self)
            if widget is not None:
                s.setContext(Qt.WidgetShortcut)
            s.activated.connect(fn)

        sc("Ctrl+O", self.open_pdf)
        sc("Ctrl+S", self.save_pdf)
        sc("Ctrl+Shift+S", self.save_pdf_as)
        sc("Ctrl+Z", self.undo_change)
        sc("Ctrl+Y", self.redo_change)
        sc("Ctrl+Shift+Z", self.redo_change)
        sc("PgUp", lambda: self.change_page(-1))
        sc("PgDown", lambda: self.change_page(1))
        sc("Ctrl+0", self.fit_to_width)
        sc("Ctrl+9", self.fit_to_page)
        sc("Ctrl+P", self.print_pdf)
        sc("Ctrl+G", self.focus_page_box)
        sc("Ctrl+F", self.find_open)
        sc("Ctrl+H", lambda: self.find_open(True))
        sc("F3", lambda: self.find_step(1))
        sc("Shift+F3", lambda: self.find_step(-1))
        sc("Ctrl+W", lambda: self.close_tab())
        sc("Ctrl+F4", lambda: self.close_tab())
        sc("Ctrl+Tab", lambda: self.step_tab(1))
        sc("Ctrl+Shift+Tab", lambda: self.step_tab(-1))
        sc("Ctrl+,", self.open_settings)
        sc("Ctrl+Return", self._inline_text_done, self.txt_new)
        sc("Ctrl+Enter", self._inline_text_done, self.txt_new)

    # ======================================================== tema
    def apply_theme(self, dark):
        self.dark = dark
        app = QApplication.instance()
        app.setPalette(build_palette(dark))
        app.setStyleSheet(build_style(dark))
        icol = "#c4c8d0" if dark else "#3d424a"
        for b, fa in self._neutral_icons:
            icon = ic(fa, icol)
            if not icon.isNull():
                b.setIcon(icon)
        # ColorButton'lar kendi renklerini tasir; temadan etkilenmesinler
        for b in (self.btn_color, self.btn_line_color) + self._mk_color_buttons():
            b.set_rgb(b.rgb)
        self._mk_recolor_icons()
        self.titlebar.set_colors(DARK if dark else LIGHT)
        # iletisim kutulari da kendi basligimizla acilir (Ayarlar, soru kutulari ...)
        title_bar.DialogChrome.ensure(app, DARK if dark else LIGHT)
        self.thumbs.update()          # kartlar renklerini paletten ciziminde okur
        try:
            self._settings.setValue("dark", dark)
        except Exception:
            pass

    @staticmethod
    def _resolve_dark(mode):
        if mode == "system":
            try:
                return QApplication.styleHints().colorScheme() == Qt.ColorScheme.Dark
            except Exception:
                return False
        return mode == "dark"

    def set_theme_mode(self, mode):
        self.theme_mode = mode
        try:
            self._settings.setValue("theme", mode)
        except Exception:
            pass
        dark = self._resolve_dark(mode)
        if dark != self.dark:
            self.apply_theme(dark)

    def _on_system_scheme(self, *_):
        if self.theme_mode == "system":
            dark = self._resolve_dark("system")
            if dark != self.dark:
                self.apply_theme(dark)

    def open_settings(self, page="appearance"):
        from settings_dialog import SettingsDialog
        from markup_ui import SHORTCUTS
        self._settings_dlg = SettingsDialog(
            self, self.theme_mode, self.set_theme_mode, APP_NAME, APP_VERSION,
            resource_path("assets", "revora.png"), SHORTCUTS,
            page=page if isinstance(page, str) else "appearance", icon_fn=ic,
            language=self._settings.value("language", i18n.language(), type=str),
            on_language=lambda code: self._settings.setValue("language", code),
            on_restart=self.restart_app)
        self._settings_dlg.exec()
        self._settings_dlg = None

    def restart_app(self):
        """Programi yeniden baslat (dil degisikligi icin). Kaydedilmemis degisiklik
        varsa once sorulur; kayitli belge yeniden acilir."""
        if not self._confirm_close_all():
            return
        from PySide6.QtCore import QProcess
        paths, active = [], 0
        for i, t in enumerate(self.tabs):         # kayitli belgeler ayni sirayla yeniden acilir
            if t.engine.path and os.path.isfile(t.engine.path):
                if i == self.tab_idx:
                    active = len(paths)
                paths.append(t.engine.path)
            t.engine.dirty = False                # soruldu; kapanirken tekrar sorulmasin
        if getattr(sys, "frozen", False):
            prog, args = sys.executable, []
        else:
            prog, args = sys.executable, [os.path.abspath(__file__)]   # nasil baslatildiysa
        args += paths
        if len(paths) > 1:
            args.append(f"--tab={active}")
        args.append("--new")                      # (bu pencereye "dosya yolla" demesin: kapaniyor)
        srv = getattr(QApplication.instance(), "_single_server", None)
        if srv is not None:
            srv.close()
        ok = QProcess.startDetached(prog, args)
        if isinstance(ok, tuple):
            ok = ok[0]
        if not ok:
            QMessageBox.warning(self, _t("Uyarı"), _t("Program yeniden başlatılamadı; lütfen kapatıp açın."))
            return
        if getattr(self, "_settings_dlg", None) is not None:
            self._settings_dlg.accept()
        QApplication.quit()

    # ======================================================== durum / panel
    def status(self, msg):
        self.statusBar().showMessage(msg)

    def _doc_name(self):
        p = self.engine.path or getattr(self.engine, "suggested_path", None)
        return os.path.basename(p) if p and self.engine.doc is not None else ""

    def _update_title(self):
        name = self._doc_name()
        dirty = " •" if (self.engine.doc is not None and self.engine.dirty) else ""
        self.setWindowTitle(f"{name}{dirty} — {APP_NAME}" if name else APP_TITLE)
        self._sync_tabs()
        has = self.engine.doc is not None
        self.btn_undo.setEnabled(has and bool(self.engine.undo_stack))
        self.btn_redo.setEnabled(has and bool(self.engine.redo_stack))
        for b in (self.btn_pg_dup, self.btn_pg_blank, self.btn_pg_import,
                  self.btn_save, self.btn_save_more, self.btn_page, self.ed_page,
                  self.btn_zoom_in, self.btn_zoom_out, self.btn_fit, self.btn_fit_page, self.mode_seg):
            b.setEnabled(has)
        self._show_page_number()               # (onceki / sonraki sayfa oklari da orada)

    def _refresh_panel(self):
        """Ust seritler: hangi mod aciksa onun araclari (1. satir) ve ayarlari (2. satir).
        Sag panel yok; bilgi yazisi yok. Satir yukseklikleri sabit (sayfa kaymaz)."""
        self._refresh_bars()
        self._settle_bars()
        self._show_home(self.engine.doc is None)

    def _show_home(self, on):
        """PDF acik degilken acilis ekrani; sol sayfa paneli ve tuval gizlenir."""
        if on == (not self.home.isHidden()):
            return                             # zaten o durumda
        if on:
            self.home.refresh()
        self.scroll.setVisible(not on)
        self.thumbs_pane.setVisible(not on)
        # acilista ust serit de yok (hepsi belge isteyen dugmeler); Ayarlar acilis ekraninin
        # sag ustunde. Kisayollar (Ctrl+O, Ctrl+,) calismaya devam eder.
        self.topbar.setVisible(not on)
        self.home.setVisible(on)

    def _settle_bars(self):
        """Seritlerde parca gizlenip gosterilince boyut + ortalama HEMEN yeniden hesaplansin
        (yoksa daralan serit bir sonraki olaya kadar eski yerinde, ortadan kaymis kaliyor)."""
        for p in (self.w_mk_tools, self.w_mk_options, self.sh_tools_pill, self.sh_opts_pill,
                  self.tx_tools_pill, self.tx_opts_pill):
            if p.isVisibleTo(self.mk_bar_host):
                p.layout().activate()
        # bos satir gizlenir (ör. ayar seridi yokken ikinci satir yer tutmaz)
        for rc, group in zip(self._bar_row_widgets, getattr(self, "_bar_row_pills", ())):
            rc.setVisible(any(not p.isHidden() for p in group))   # (satir gizliyken isVisibleTo hep False)
        for rc in self._bar_row_widgets:
            rc.layout().activate()
        self._place_bar_overlay()
        # ekranda bazi boyutlar bir sonraki olayda kesinlesir (ikinci satira kayan menu
        # kesik / yarim kalmasin): olaylardan sonra bir kez daha yerlestir
        if not getattr(self, "_bar_settle_pending", False):
            self._bar_settle_pending = True
            QTimer.singleShot(0, self._settle_bars_later)

    def _settle_bars_later(self):
        self._bar_settle_pending = False
        for p in (self.w_mk_options, self.sh_opts_pill, self.tx_opts_pill):
            if p.isVisibleTo(self.mk_bar_host):
                p.layout().activate()
        self._place_bar_overlay()

    def _place_bar_overlay(self):
        """Suzulen seritleri tuval alaninin ustune yerlestir; sadece seritlerin
        kendisi fareyi yakalasin (aradaki bos alan sayfaya gecer)."""
        host = getattr(self, "mk_bar_host", None)
        if host is None:
            return
        vp = self.scroll.viewport()
        self._wrap_bars(vp.width())
        host.layout().activate()
        h = host.sizeHint().height()
        host.setGeometry(0, 0, vp.width(), h)
        host.layout().setGeometry(host.rect())
        self._update_bar_mask()
        host.raise_()
        has = self.engine.doc is not None
        self.canvas.set_pad_top(getattr(self, "_bar_full_h", 0) + 6 if has else 0)
        self._place_zoom_pill()
        self._place_find_bar()
        self._place_mode_seg()                 # ust seritteki modlar ayni eksende kalsin

    def _update_bar_mask(self):
        """Sadece seritlerin kendisi fareyi yakalasin / gorunsun (aradaki bos alan sayfaya gecer)."""
        host = getattr(self, "mk_bar_host", None)
        if host is None:
            return
        from PySide6.QtGui import QRegion
        region = QRegion()
        for group in getattr(self, "_bar_row_pills", ()):
            for p in group:
                if p.isVisibleTo(host):
                    region = region.united(QRegion(QRect(p.mapTo(host, QPoint(0, 0)), p.size())))
        if region.isEmpty():
            region = QRegion(0, 0, 1, 1)        # bos maske "maske yok" demek olurdu
        if host.mask() != region:
            host.setMask(region)

    def _wrap_bars(self, width):
        """Sigmayan serit (dar pencere / uzun menu) grup ayiricisindan ikinci satira kayar;
        o satirin yuksekligi ve sayfanin ustundeki pay buna gore buyur."""
        pills = getattr(self, "_bar_row_pills", ())
        if not pills:
            return
        m = self.mk_bar_host.layout().contentsMargins()
        avail = max(200, width - m.left() - m.right() - 8)
        for rc, group, base in zip(self._bar_row_widgets, pills, self._bar_row_base_h):
            h = base           # tek satirli seritler ayni yukseklikte (WrapPill.LINE_H): sayfa kaymaz
            for p in group:
                if not p.isHidden():
                    p.rewrap(avail)
                    p.layout().activate()
                    h = max(h, p.sizeHint().height())
            if rc.height() != h or rc.maximumHeight() != h:
                rc.setFixedHeight(h)
            rc.layout().activate()
        # sayfanin ustundeki pay TEK satirlik seritlere gore: uzun menu ikinci satira
        # kayinca sayfa zıplamasin (ikinci satir sayfanin ustunde suzulur)
        hm = self.mk_bar_host.layout()
        one = self.w_mk_tools.sizeHint().height()       # tek satirlik serit yuksekligi
        single = [max(base, one) for base in self._bar_row_base_h]
        self._bar_full_h = m.top() + m.bottom() + hm.spacing() + sum(single)

    def _refresh_bars(self):
        for group in getattr(self, "_bar_row_pills", ()):
            for p in group:
                p.unwrap()                     # gorunurlukler degismeden once tek satira
        has_doc = self.engine.doc is not None
        self.inspector.hide()
        self._mk_hide_panel()
        for w in (self.sh_tools_pill, self.sh_opts_pill, self.tx_tools_pill, self.tx_opts_pill):
            w.hide()
        self.mk_bar_host.setVisible(has_doc)
        if not has_doc:
            return
        if self.mode == "markup":
            self._markup_refresh_panel()
            return
        if self.mode == "shape":
            self.tx_tools_pill.show()          # (tek arac seridi: Duzenle)
            sel = bool(self.sel_paths)
            # Sec araci + secim yok: gosterecek ayar yok (bosa tiklayinca / silince kalkar)
            self.sh_opts_pill.setVisible(sel or self.shape_tool != "select")
            if not sel and self.shape_tool != "select":
                self._show_shape_style()      # cizim araci: son kullanilan (secilenin degil)
            self.sh_del_sep.setVisible(sel)
            self.btn_sh_delete.setVisible(sel)
            return
        self.tx_tools_pill.show()             # Metin: arac satiri (Sec | Yeni metin) hep gorunur
        if self.mode == "insert":
            self.tx_opts_pill.show()
            self.chk_autofit.hide()
            self.tx_rot_box.hide()
            self.tx_edit_box.hide()
            return
        # sec araci: bir metin secilince ayarlari cikar
        has = self.current_span is not None
        self.tx_opts_pill.setVisible(has)
        self.chk_autofit.show()
        self.tx_rot_box.show()
        self.tx_edit_box.show()

    # ======================================================== dosya
    # ======================================================== sekmeler
    def _tab_label(self, eng):
        p = eng.path or eng.suggested_path
        return os.path.basename(p) if p else _t("Adsız")

    def _sync_tabs(self):
        """Sekme basliklari / "degisti" noktalari / secili sekme = gercek durum."""
        strip = self.titlebar.strip
        for i, t in enumerate(self.tabs):
            e = t.engine
            strip.set_tab(i, self._tab_label(e), e.path or self._tab_label(e), bool(e.dirty))
        strip.set_current(self.tab_idx)

    def _finish_edits(self):
        """Yarim kalan duzenlemeleri uygula (sayfada yazilan metin, bekleyen aci onizlemesi)."""
        if self.engine.doc is not None:
            self._inline_text_done()
            self._text_angle_commit()

    def _leave_tab(self):
        """Gecerli sekmeden ayrilmadan once: duzenlemeleri bitir, gorunumunu sakla."""
        if not (0 <= self.tab_idx < len(self.tabs)):
            return
        self._finish_edits()
        self._remember_page()
        self._clear_selection()
        t = self.tabs[self.tab_idx]
        t.page = self.current_page
        t.zoom = self.canvas.zoom
        t.scroll = (self.scroll.horizontalScrollBar().value(), self.scroll.verticalScrollBar().value())
        t.thumbs = [self.thumbs.item(i) for i in range(self.thumbs.count())]
        t.thumbs_ver = t.engine.version

    def _activate(self, i):
        """i. sekmeyi goster (-1: baslangic ekrani). Onceki sekmeden _leave_tab ile cikilmis olmali."""
        self.tab_idx = i
        self.engine = self.tabs[i].engine if i >= 0 else self._home_engine
        # belgeye bagli onbellekler: anahtarlari sayfa + belge surumu, baska belgeyle cakisabilir
        self._mk_loaded = None
        self._blur_cache = self._mag_cache = None
        self._tx_live_cache = None
        self.__dict__.pop("_img_prev_cache", None)
        self.canvas.clear_page()
        self.titlebar.strip.set_current(i)
        if i < 0:
            self.current_page = 0
            self.lbl_fileinfo.setText("")
            self.lbl_coords.setText("")
            self._refresh_panel()
            self._update_title()
            return
        t = self.tabs[i]
        n = self.engine.page_count()
        self.current_page = max(0, min(t.page, n - 1))
        # acilis ekrani kapanip tuval + sol panel yerlesmeden olcek hesaplanirsa (genislige
        # sigdir) tuval hala gizli/dar olculur -> sayfa yarim boyutta acilirdi
        was_home = not self.home.isHidden()
        self._show_home(False)
        if was_home:
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)
        if t.thumbs is not None and t.thumbs_ver == self.engine.version and len(t.thumbs) == n:
            self.thumbs.set_items(t.thumbs, self.current_page)
            self.thumbs.ensure_visible(self.current_page)
        else:
            self._populate_thumbnails()
        if t.zoom is None:
            self.fit_to_width()
        else:
            self.canvas.zoom = t.zoom
            self.render_current_page()
            hs, vs = t.scroll

            def restore(tab=t):                   # kaydirma araliklari yerlesimden sonra kesinlesir
                if 0 <= self.tab_idx < len(self.tabs) and self.tabs[self.tab_idx] is tab:
                    self.scroll.horizontalScrollBar().setValue(hs)
                    self.scroll.verticalScrollBar().setValue(vs)
            restore()
            QTimer.singleShot(0, restore)
        self._refresh_panel()
        self._update_title()

    def switch_tab(self, i):
        if i == self.tab_idx or not (-1 <= i < len(self.tabs)):
            return
        self._leave_tab()
        self._activate(i)

    def step_tab(self, delta):
        """Sonraki / onceki belge sekmesi (Ctrl+Tab / Ctrl+Shift+Tab)."""
        if self.tabs:
            cur = self.tab_idx if self.tab_idx >= 0 else (-1 if delta > 0 else 0)
            self.switch_tab((cur + delta) % len(self.tabs))

    def close_tab(self, i=None):
        """Sekmeyi kapat (i verilmezse gecerli olan). Kaydedilmemis degisiklik varsa sorar.
        Kapandiysa True."""
        if i is None or isinstance(i, bool):
            i = self.tab_idx
        if not (0 <= i < len(self.tabs)):
            return False
        if i == self.tab_idx:
            self._finish_edits()                  # (sorudan ONCE: belgeyi "degisti" yapabilir)
        t = self.tabs[i]
        if t.engine.dirty:
            self.switch_tab(i)                    # neyin soruldugu gorunsun
            r = self._ask_unsaved()
            if r == "save":
                if not self.save_pdf():
                    return False
            elif r != "discard":
                return False
            i = self.tabs.index(t)
        cur = self.tab_idx
        if i == cur:
            self._leave_tab()
        del self.tabs[i]
        self.titlebar.strip.remove_tab(i)
        if i == cur:                              # sagdaki komsu, yoksa soldaki, o da yoksa baslangic
            self._activate(min(i, len(self.tabs) - 1))
        else:
            if i < cur:
                self.tab_idx = cur - 1
            self._sync_tabs()
        try:                                      # dosya kilidi ve bellek birakilsin
            t.engine.doc.close()
        except Exception:
            pass
        t.engine.doc = None
        t.engine.undo_stack, t.engine.redo_stack = [], []
        t.thumbs = None
        return True

    def close_other_tabs(self, keep):
        for t in [t for t in self.tabs if t is not keep]:
            if not self.close_tab(self.tabs.index(t)):
                break

    def _tab_moved(self, src, dst):
        """Sekme surukleyerek siralandi (serit kendi listesini guncelledi)."""
        if 0 <= src < len(self.tabs) and 0 <= dst < len(self.tabs):
            self.tabs.insert(dst, self.tabs.pop(src))
            self.tab_idx = self.titlebar.strip.current

    def _tab_context(self, i, global_pos):
        if not (0 <= i < len(self.tabs)):
            return
        t = self.tabs[i]
        menu = QMenu(self)
        menu.addAction(_t("Sekmeyi kapat\tCtrl+W"), lambda: self.close_tab(self.tabs.index(t)))
        a = menu.addAction(_t("Diğer sekmeleri kapat"), lambda: self.close_other_tabs(t))
        a.setEnabled(len(self.tabs) > 1)
        if t.engine.path:
            menu.addSeparator()
            menu.addAction(_t("Klasörde göster"), lambda: self._reveal_in_folder(t.engine.path))
        menu.exec(global_pos)

    # ======================================================== dosya
    def _confirm_close_all(self):
        """Kaydedilmemis her sekme icin sor (o sekme gosterilerek). Hepsi icin devam
        edilebilirse True; biri iptal edilirse False."""
        self._finish_edits()
        for t in list(self.tabs):
            if t in self.tabs and t.engine.dirty:
                self.switch_tab(self.tabs.index(t))
                r = self._ask_unsaved()
                if r == "save":
                    if not self.save_pdf():
                        return False
                elif r != "discard":
                    return False
        return True

    def _ask_unsaved(self):
        """Kaydet / Kaydetme / Iptal sorusu: 'save' | 'discard' | 'cancel'.
        Qt'nin Turkce cevirisi "Discard" dugmesine "At" diyor (anlasilmiyor);
        Windows/Office'teki gibi "Kaydetme" yazilir."""
        box = QMessageBox(QMessageBox.Question, _t("Kaydedilmemiş değişiklikler"),
                          _t("Belgede kaydedilmemiş değişiklikler var. Kaydetmek ister misiniz?"),
                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        box.button(QMessageBox.Discard).setText(_t("Kaydetme"))
        box.setDefaultButton(QMessageBox.Save)
        box.exec()
        clicked = box.clickedButton()
        if clicked == box.button(QMessageBox.Save):
            return "save"
        if clicked == box.button(QMessageBox.Discard):
            return "discard"
        return "cancel"

    def open_pdf(self, path=None):
        """PDF'i (ya da resmi) YENI SEKMEDE acar; zaten aciksa o sekmeye gecer.
        path verilmezse dosya secme penceresi cikar (birden cok dosya secilebilir)."""
        if not path or not isinstance(path, str):       # (dugmenin clicked sinyali False yollar)
            paths, _ = QFileDialog.getOpenFileNames(
                self, _t("PDF Aç"), self._last_open_path(),
                _t("PDF ve resimler (*.pdf {p})", p=image_tools.IMAGE_PATTERN) + ";;"
                + _t("PDF Dosyaları (*.pdf)") + ";;" + image_tools.image_filter())
            for q in paths:
                self._open_path(q)
            return
        self._open_path(path)

    def _open_path(self, path):
        is_img = image_tools.is_image(path)
        if not is_img:                                  # zaten acik: o sekmeye gec
            key = os.path.normcase(os.path.abspath(path))
            for i, t in enumerate(self.tabs):
                if t.engine.path and os.path.normcase(os.path.abspath(t.engine.path)) == key:
                    self.switch_tab(i)
                    return True
        eng = PDFEditor()
        try:
            if is_img:                          # resim: tek sayfalik PDF'e cevrilip acilir
                doc, skipped = image_tools.images_to_pdf([path], "image")
                if not len(doc):
                    raise ValueError(skipped[0][1] if skipped else path)
                eng.open_doc(doc, os.path.splitext(path)[0] + ".pdf")
            else:
                pw = None
                while True:                     # parola korumali: dogru girilene / vazgecilene kadar sor
                    try:
                        eng.open(path, pw)
                        break
                    except PasswordError as pe:
                        pw = self._ask_password(os.path.basename(path), wrong=not pe.needed)
                        if pw is None:
                            return False
        except Exception as e:
            QMessageBox.critical(self, _t("Açılamadı"),
                                 _t("Bu PDF açılamadı (bozuk ya da desteklenmeyen dosya):\n{e}", e=e))
            return False
        self._leave_tab()
        tab = _DocTab(eng)
        tab.page = self._last_page_of(path)    # bu dosyada en son bakilan sayfa (liste dolarken
        self._remember_open(path)              # 1. sayfaya donulup ezilmeden once okunur)
        self.tabs.append(tab)
        self.titlebar.strip.add_tab(self._tab_label(eng), eng.path or "", bool(eng.dirty))
        self._activate(len(self.tabs) - 1)
        self.status(_t("Açıldı: {name}", name=os.path.basename(path)))
        return True

    # ---- parola
    def _ask_password(self, name, wrong=False):
        """Parola korumali belgeyi acmak icin parola sor -> yazi | None (vazgecildi)."""
        from PySide6.QtWidgets import QInputDialog, QDialog
        dlg = QInputDialog(self)
        dlg.setWindowTitle(_t("Parola korumalı PDF"))
        dlg.setLabelText((_t("Parola yanlış, yeniden deneyin.") + "\n\n" if wrong else "")
                         + _t("“{name}” parola korumalı.\nAçmak için parolayı girin:", name=name))
        dlg.setTextEchoMode(QLineEdit.Password)
        dlg.setOkButtonText(_t("Aç"))
        dlg.setCancelButtonText(_t("Vazgeç"))
        if dlg.exec() != QDialog.Accepted:
            return None
        return dlg.textValue()

    def set_password_dialog(self):
        if not self._need_doc():
            return
        from dialogs import PasswordDialog
        dlg = PasswordDialog(self, has_password=bool(self.engine.password))
        if dlg.exec() and dlg.password:
            self.engine.set_password(dlg.password)
            self._update_title()
            self.render_current_page()
            self.status(_t("Parola ayarlandı. Belgeyi kaydettiğinizde geçerli olur."))

    def remove_password(self):
        if not self.engine.doc or not self.engine.password:
            return
        r = QMessageBox.question(self, _t("Parolayı kaldır"),
                                 _t("Belgenin parola koruması kaldırılsın mı?\nKaydettikten sonra belge parolasız açılır."),
                                 QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self.engine.set_password(None)
        self._update_title()
        self.render_current_page()
        self.status(_t("Parola kaldırıldı. Belgeyi kaydettiğinizde geçerli olur."))

    # ---- Excel'e aktar (tum sayfa / yalniz tablolar)
    def export_excel(self):
        self._finish_edits()
        if not self.engine.doc:
            return False
        from PySide6.QtWidgets import QDialog, QProgressDialog
        from dialogs import ExportExcelDialog
        import pdf_tables
        title = _t("Excel'e aktar")
        dlg = ExportExcelDialog(self, self.current_page, self.engine.page_count())
        if dlg.exec() != QDialog.Accepted:
            return False
        pages, whole = dlg.pages(), dlg.whole_page
        prog = None
        if len(pages) > 2:
            prog = QProgressDialog(_t("Sayfalar hazırlanıyor..."), _t("İptal"), 0, len(pages), self)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(300)
        found = []
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            for i, pno in enumerate(pages):
                if prog is not None:
                    prog.setValue(i)
                    if prog.wasCanceled():
                        return False
                if whole:
                    sh = pdf_tables.page_sheet(self.engine, pno, images=dlg.images, text_fallback=dlg.text_tables)
                    if sh is not None:
                        found.append(sh)
                else:
                    found += pdf_tables.page_tables(self.engine, pno, text_fallback=dlg.text_tables)
        finally:
            QApplication.restoreOverrideCursor()
            if prog is not None:
                prog.setValue(len(pages))
        if not found:
            QMessageBox.information(
                self, title,
                _t("Seçilen sayfalarda aktarılacak yazı ya da resim bulunamadı.\n\nTaranmış (resim) sayfalarda önce OCR gerekir.")
                if whole else
                _t("Seçilen sayfalarda tablo bulunamadı.\n\nTablonun çizgileri yoksa \"Çizgisiz tabloları da ara\" "
                   "seçeneğini deneyin. Taranmış (resim) sayfalarda önce OCR gerekir."))
            return False
        start = os.path.splitext(self._export_base() or "belge")[0] + ".xlsx"
        path, _ = QFileDialog.getSaveFileName(self, title, start, _t("Excel dosyası (*.xlsx)"))
        if not path:
            return False
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            if whole:
                n = pdf_tables.write_xlsx_pages(path, found, numbers=dlg.numbers, sheet_label=_t("Sayfa {p}"))
                msg = _t("{n} sayfa Excel'e aktarıldı.", n=n)
            else:
                n = pdf_tables.write_xlsx(path, found, single_sheet=dlg.single_sheet, numbers=dlg.numbers,
                                          page_label=_t("Sayfa {p} - Tablo {t}"), sheet_label=_t("S{p} Tablo {t}"),
                                          all_label=_t("Tablolar"))
                msg = _t("{n} tablo aktarıldı.", n=n)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            QMessageBox.critical(self, _t("Kaydedilemedi"),
                                 _t("Dosya kaydedilemedi (başka bir programda açık olabilir):\n{e}", e=e))
            return False
        QApplication.restoreOverrideCursor()
        self.status(msg + "  " + path)
        box = QMessageBox(QMessageBox.Information, title, msg + "\n" + path, QMessageBox.NoButton, self)
        b_open = box.addButton(_t("Dosyayı aç"), QMessageBox.AcceptRole)
        b_show = box.addButton(_t("Klasörde göster"), QMessageBox.ActionRole)
        box.addButton(_t("Kapat"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_open:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        elif box.clickedButton() is b_show:
            self._reveal_in_folder(path)
        return True

    # ---- kucultme
    @staticmethod
    def _size_text(n):
        return f"{n / 1048576:.1f} MB".replace(".", ",") if n >= 1048576 else f"{max(1, round(n / 1024))} KB"

    def save_compressed(self):
        """Kucultulmus kopya kaydet: resimlerin cozunurlugu dusurulur, yapi sikistirilir."""
        self._finish_edits()
        if not self.engine.doc:
            return False
        from PySide6.QtWidgets import QDialog
        from dialogs import CompressDialog
        src = self.engine.path
        try:
            before = os.path.getsize(src) if src and os.path.isfile(src) else len(self.engine.doc.tobytes())
        except Exception:
            before = 0
        dlg = CompressDialog(self, self._size_text(before) if before else "")
        if dlg.exec() != QDialog.Accepted:
            return False
        start = (os.path.splitext(src)[0] + "_kucuk.pdf") if src else (self.engine.suggested_path or "")
        path, _ = QFileDialog.getSaveFileName(self, _t("Küçülterek kaydet"), start, _t("PDF Dosyaları (*.pdf)"))
        if not path:
            return False
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = self._do_save(path, compress=dlg.level)
        finally:
            QApplication.restoreOverrideCursor()
        if not ok:
            return False
        self._overwrite_ok.add(os.path.abspath(path))
        self._add_recent(path)
        self._clear_selection()
        self._populate_thumbnails()
        self._update_title()
        after = os.path.getsize(path)
        if before and after < before:
            msg = _t("{a} → {b}  (%{p} küçüldü)", a=self._size_text(before), b=self._size_text(after),
                     p=round(100 * (before - after) / before))
        else:
            msg = _t("Boyut: {b}. Bu belge zaten sıkıştırılmış; daha fazla küçülmedi.", b=self._size_text(after))
        QMessageBox.information(self, _t("Küçülterek kaydet"), msg)
        return True

    # ---- son acilan klasor / dosya basina son sayfa (kapatip acinca da hatirlanir)
    def _last_open_path(self):
        try:
            p = self._settings.value("last_open_file", "", type=str)
        except Exception:
            p = ""
        if p and os.path.exists(p):
            return p                           # iletisim kutusu o klasorde, dosya secili acilir
        d = os.path.dirname(p) if p else ""
        return d if d and os.path.isdir(d) else ""

    def _last_pages(self):
        try:
            data = json.loads(self._settings.value("last_pages", "{}", type=str) or "{}")
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _last_page_of(self, path):
        try:
            return int(self._last_pages().get(os.path.normcase(os.path.abspath(path)), 0))
        except (TypeError, ValueError):
            return 0

    def _remember_open(self, path):
        try:
            self._settings.setValue("last_open_file", os.path.abspath(path))
        except Exception:
            pass
        if not image_tools.is_image(path):     # resim: henuz kaydedilmemis belge, listeye girmez
            self._add_recent(path)

    # ---- son dosyalar (acilis ekrani). Yalnizca bu bilgisayarda, QSettings'te.
    RECENT_MAX = 12

    def _recent_files(self):
        try:
            data = json.loads(self._settings.value("recent_files", "[]", type=str) or "[]")
            return [p for p in data if isinstance(p, str)] if isinstance(data, list) else []
        except Exception:
            return []

    def _add_recent(self, path):
        path = os.path.abspath(path)
        key = os.path.normcase(path)
        items = [path] + [p for p in self._recent_files() if os.path.normcase(p) != key]
        try:
            self._settings.setValue("recent_files", json.dumps(items[:self.RECENT_MAX]))
        except Exception:
            pass

    def _forget_recent(self, path=None):
        """Listeden bir dosyayi (path) ya da hepsini (None) cikar. Dosyalara dokunmaz."""
        items = [] if path is None else [p for p in self._recent_files()
                                         if os.path.normcase(p) != os.path.normcase(path)]
        try:
            self._settings.setValue("recent_files", json.dumps(items))
        except Exception:
            pass

    def _reveal_in_folder(self, path):
        from PySide6.QtCore import QProcess, QUrl
        from PySide6.QtGui import QDesktopServices
        if sys.platform == "win32" and os.path.isfile(path):
            QProcess.startDetached("explorer", ["/select,", os.path.normpath(path)])
        else:
            QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path)))

    def _remember_page(self):
        path = self.engine.path if self.engine.doc else None
        if not path:
            return
        data = self._last_pages()
        key = os.path.normcase(os.path.abspath(path))
        data.pop(key, None)
        data[key] = self.current_page
        while len(data) > 50:                  # en eski kayitlar dusurulur
            data.pop(next(iter(data)))
        try:
            self._settings.setValue("last_pages", json.dumps(data))
        except Exception:
            pass

    def save_pdf(self):
        """Acik dosyanin uzerine kaydeder (ilk seferde onay ister)."""
        self._text_angle_commit()     # bekleyen aci onizlemesi
        if not self.engine.doc:
            return False
        path = self.engine.path
        if not path:
            return self.save_pdf_as()
        if path not in self._overwrite_ok:
            r = QMessageBox.question(
                self, _t("Üzerine kaydet"),
                _t("Değişiklikler orijinal dosyanın üzerine yazılsın mı?\n{path}\n\n"
                   "Orijinali korumak için \"Farklı kaydet\"i seçin.", path=path),
                QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel, QMessageBox.Yes)
            if r == QMessageBox.No:
                return self.save_pdf_as()
            if r != QMessageBox.Yes:
                return False
            self._overwrite_ok.add(path)
        return self._do_save(path)

    def save_pdf_as(self):
        self._text_angle_commit()     # bekleyen aci onizlemesi
        if not self.engine.doc:
            return False
        start = self.engine.path or ""
        if start:
            base, ext = os.path.splitext(start)
            start = base + "_duzenlenmis" + ext
        elif getattr(self.engine, "suggested_path", None):
            start = self.engine.suggested_path          # resimden acilan belge: resmin adi .pdf
        path, _ = QFileDialog.getSaveFileName(self, _t("Farklı Kaydet"), start, _t("PDF Dosyaları (*.pdf)"))
        if not path:
            return False
        if self._do_save(path):
            self._overwrite_ok.add(os.path.abspath(path))
            self._add_recent(path)
            return True
        return False

    # ======================================================== yazdirma
    def print_pdf(self):
        """Yazdir (Ctrl+P): Windows'un yazici penceresi; tumu / gecerli sayfa / aralik."""
        self._inline_text_done()               # (bekleyen aci onizlemesini de uygular)
        if not self.engine.doc:
            return
        from PySide6.QtPrintSupport import QPrinter, QPrintDialog
        from PySide6.QtWidgets import QDialog
        printer = QPrinter(QPrinter.HighResolution)
        printer.setDocName(self._doc_name() or APP_NAME)
        n = self.engine.page_count()
        dlg = QPrintDialog(printer, self)
        dlg.setWindowTitle(_t("Yazdır"))
        dlg.setOption(QPrintDialog.PrintPageRange, True)
        dlg.setOption(QPrintDialog.PrintCurrentPage, True)
        dlg.setMinMax(1, n)
        if dlg.exec() != QDialog.Accepted:
            return
        rng = printer.printRange()
        if rng == QPrinter.PageRange and printer.fromPage() > 0:
            pages = list(range(printer.fromPage() - 1, min(printer.toPage(), n)))
        elif rng == QPrinter.CurrentPage:
            pages = [self.current_page]
        else:
            pages = list(range(n))
        done = self._print_pages(printer, pages)
        if done:
            self.status(_t("{n} sayfa yazıcıya gönderildi.", n=done))

    def _print_pages(self, printer, pages):
        """Sayfalari yaziciya ciz: her sayfa yazdirilabilir alana ORANI KORUNARAK sigdirilir,
        yatay sayfa dikey kagitta (ya da tersi) kendiliginden dondurulur. Ekrandaki son
        hal basilir (isaretlemeler dahil). Dondurur: basilan sayfa sayisi."""
        from PySide6.QtWidgets import QProgressDialog
        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.warning(self, _t("Yazdırılamadı"), _t("Yazıcı başlatılamadı."))
            return 0
        prog = None
        if len(pages) > 3:
            prog = QProgressDialog(_t("Yazdırılıyor..."), _t("İptal"), 0, len(pages), self)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(400)
        dpi = max(72, min(printer.resolution(), 300))       # 300 dpi yeter; bellek sisirmesin
        done = 0
        try:
            for i, pno in enumerate(pages):
                if prog is not None:
                    prog.setValue(i)
                    if prog.wasCanceled():
                        break
                if i and not printer.newPage():
                    break
                page = self.engine.doc[pno]
                area = painter.viewport()
                turn = (page.rect.width > page.rect.height) != (area.width() > area.height())
                mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
                if turn:
                    mat = mat.prerotate(90)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format_RGB888)
                k = min(area.width() / img.width(), area.height() / img.height())
                w_, h_ = int(img.width() * k), int(img.height() * k)
                painter.drawImage(QRect(area.x() + (area.width() - w_) // 2,
                                        area.y() + (area.height() - h_) // 2, w_, h_), img)
                done += 1
        finally:
            painter.end()
            if prog is not None:
                prog.setValue(len(pages))
        return done

    def _do_save(self, path, compress=None):
        try:
            self.engine.save(path, compress=compress)
        except Exception as e:
            QMessageBox.critical(self, _t("Kaydedilemedi"),
                                 _t("Dosya kaydedilemedi (başka bir programda açık olabilir):\n{e}", e=e))
            return False
        n = getattr(self.engine, "last_finalized", 0)
        if n:
            # bulanik alanlar kalici uygulandi: artik nesne degiller
            self.sel_markup = None
            self._populate_thumbnails()
        self._update_title()
        self.render_current_page()
        self._refresh_panel()
        self.status(_t("Kaydedildi: {path}", path=path) + (_t(
            " · {n} bulanık alan kalıcı uygulandı (alttaki içerik silindi; Ctrl+Z ile kayıt "
            "öncesine dönülebilir)", n=n) if n else ""))
        return True

    def closeEvent(self, ev):
        if self._confirm_close_all():
            self._remember_page()
            ev.accept()
        else:
            ev.ignore()

    def dragEnterEvent(self, ev):
        if any(u.toLocalFile().lower().endswith(".pdf") or image_tools.is_image(u.toLocalFile())
               for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        pdfs = [u.toLocalFile() for u in ev.mimeData().urls() if u.toLocalFile().lower().endswith(".pdf")]
        for p in pdfs:                         # her biri kendi sekmesinde
            self.open_pdf(p)
        if pdfs:
            return
        imgs = image_tools.image_paths(ev.mimeData())
        if imgs:                               # resimler birakildi: resimlerden PDF penceresi
            self.open_images_to_pdf(imgs)

    # ======================================================== resim <-> PDF
    def open_images_to_pdf(self, initial=None):
        dlg = image_tools.ImagesToPdfDialog(self, initial if isinstance(initial, list) else None, self._settings)
        dlg.exec()
        if dlg.created:
            self.open_pdf(dlg.created)

    def _export_base(self):
        return self.engine.path or getattr(self.engine, "suggested_path", None) or ""

    def export_pages_dialog(self, pno=None):
        if not self.engine.doc:
            return
        self._inline_text_done()
        cur = self.current_page if pno is None or isinstance(pno, bool) else pno
        image_tools.ExportPagesDialog(self, self.engine.doc, cur, self._export_base(), self._settings).exec()

    def extract_photos_dialog(self):
        if not self.engine.doc:
            return
        image_tools.ExtractPhotosDialog(self, self.engine.doc, self.current_page, self._export_base()).exec()

    def copy_page_image(self, pno=None):
        if not self.engine.doc:
            return
        cur = self.current_page if pno is None or isinstance(pno, bool) else pno
        QApplication.clipboard().setImage(image_tools.page_qimage(self.engine.doc, cur, 150))
        self.status(_t("{n}. sayfa panoya resim olarak kopyalandı — WhatsApp, e-posta ya da Word'e "
                       "yapıştırabilirsiniz (Ctrl+V).", n=cur + 1))

    # ======================================================== kucuk resimler
    def _thumb_pix(self, i):
        page = self.engine.doc[i]
        dpr = self.devicePixelRatioF()           # yuksek DPI ekranda net olsun
        zoom = THUMB_H * dpr / max(page.rect.height, page.rect.width * 0.75)
        pm = QPixmap.fromImage(pix_to_qimage(page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)))
        pm.setDevicePixelRatio(dpr)
        return pm

    def _populate_thumbnails(self):
        self.thumbs.set_items([self._thumb_pix(i) for i in range(self.engine.page_count())],
                              self.current_page)
        self.thumbs.ensure_visible(self.current_page)

    def _update_thumb(self, i):
        if 0 <= i < self.thumbs.count():
            self.thumbs.update_item(i, self._thumb_pix(i))

    def _on_thumb_changed(self, row):
        if row < 0 or not self.engine.doc:
            return
        if row != self.current_page:
            self.goto_page(row)

    # ======================================================== gezinme / zoom
    def goto_page(self, pno):
        if not self.engine.doc or not (0 <= pno < self.engine.page_count()):
            return
        self._inline_text_done()              # sayfada yazilan metin varsa once uygula
        self.current_page = pno
        self._remember_page()
        self._clear_selection()
        self.thumbs.set_current(pno)      # sinyal gondermez; listeyi o sayfaya kaydirir
        self.render_current_page()
        self._refresh_panel()
        self._find_page_changed()

    def change_page(self, delta):
        if self.engine.doc:
            self.goto_page(self.current_page + delta)

    def set_zoom(self, value):
        if not self.engine.doc:
            return
        self.canvas.zoom = max(MIN_ZOOM, min(value, MAX_ZOOM))
        self.render_current_page()

    def on_wheel_zoom(self, delta_y, canvas_pos):
        if not self.engine.doc:
            return
        old_zoom = self.canvas.zoom
        factor = 1.15 if delta_y > 0 else (1 / 1.15)
        new_zoom = max(MIN_ZOOM, min(old_zoom * factor, MAX_ZOOM))
        if new_zoom == old_zoom:
            return
        hbar = self.scroll.horizontalScrollBar()
        vbar = self.scroll.verticalScrollBar()
        viewport_rel_x = canvas_pos.x() - hbar.value()
        viewport_rel_y = canvas_pos.y() - vbar.value()
        pad = self.canvas.pad_top
        rel_x = canvas_pos.x() / old_zoom
        rel_y = (canvas_pos.y() - pad) / old_zoom
        self.canvas.zoom = new_zoom
        self.render_current_page()
        hbar.setValue(int(rel_x * new_zoom - viewport_rel_x))
        vbar.setValue(int(rel_y * new_zoom + pad - viewport_rel_y))

    def on_pan_start(self, global_pos):
        self._pan_start_global = global_pos
        self._pan_start_scroll = (self.scroll.horizontalScrollBar().value(),
                                  self.scroll.verticalScrollBar().value())

    def on_pan_move(self, global_pos):
        dx = global_pos.x() - self._pan_start_global.x()
        dy = global_pos.y() - self._pan_start_global.y()
        self.scroll.horizontalScrollBar().setValue(int(self._pan_start_scroll[0] - dx))
        self.scroll.verticalScrollBar().setValue(int(self._pan_start_scroll[1] - dy))

    def fit_to_width(self):
        if not self.engine.doc:
            return
        page = self.engine.doc[self.current_page]
        avail_width = self.scroll.viewport().width() - 30
        self.canvas.zoom = max(MIN_ZOOM, min(avail_width / page.rect.width, MAX_ZOOM))
        self.render_current_page()

    def fit_to_page(self):
        """Sayfanin TAMAMI gorunsun (genislik ve yukseklikten kucuk olan olcek)."""
        if not self.engine.doc:
            return
        page = self.engine.doc[self.current_page]
        vp = self.scroll.viewport()
        # Sayfa gorunen alanin TAMAMINI kullanir (ust ve altta FIT_MARGIN kadar bosluk); yuzen
        # arac seritleri sayfanin ust kenarinin ustunde durur. Eskiden sayfa iki serit
        # satirinin ALTINDAN baslatiliyordu: ustte kocaman bos bant kaliyor, sayfa kuculuyordu
        # (kullanici: "cok cirkin duruyor"). Seritlerin altinda kalan yeri gormek icin yukari
        # kaydirilabilir (tuvalin ustundeki serit payi duruyor).
        m = self.canvas.pad_bottom
        avail_w = vp.width() - 30
        avail_h = vp.height() - 2 * m
        r = page.rect
        z = min(avail_w / r.width, avail_h / r.height)
        self.canvas.zoom = max(MIN_ZOOM, min(z, MAX_ZOOM))
        self.render_current_page()
        want = max(0, self.canvas.pad_top - m)

        def settle():                          # kaydirma araligi yerlesimden sonra kesinlesir
            self.scroll.verticalScrollBar().setValue(want)
        settle()
        QTimer.singleShot(0, settle)

    def render_current_page(self):
        if not self.engine.doc:
            self.canvas.clear_page()
            return
        page = self.engine.doc[self.current_page]
        dpr = self.canvas.devicePixelRatioF()
        z = self.canvas.zoom
        # cok buyuk yakinlastirmada bellek patlamasin
        px = abs(page.rect.width * page.rect.height) * (z * dpr) ** 2
        if px > MAX_RENDER_PIXELS:
            # %800'de buyuk sayfalarda (A3 vb.) goruntu yuzlerce MB tutabilir:
            # gerekirse ekran cozunurlugunun biraz altinda cizilir (hafif yumusama,
            # ama bellek patlamaz). A4 %800'de bu sinira takilmaz.
            dpr = max(0.25, dpr * (MAX_RENDER_PIXELS / px) ** 0.5)
        doc = self.engine.doc
        hidden = []
        for x in getattr(self, "_render_hide", ()):
            try:                           # gecici "gizli" bayragi (F=2), cizimden sonra geri
                hidden.append((x, doc.xref_get_key(x, "F")))
                doc.xref_set_key(x, "F", "2")
            except Exception:
                pass
        try:
            pix = page.get_pixmap(matrix=fitz.Matrix(z * dpr, z * dpr), alpha=False)
            self._render_scale = z * dpr
        finally:
            for x, (t, v) in hidden:
                doc.xref_set_key(x, "F", v if t != "null" else "null")
        self.canvas.set_page(pix_to_qimage(pix), dpr, page.rotation_matrix, page.derotation_matrix)
        if self.editing_live():                # set_page nesnesiz arka plani sildi
            self._tx_live_cache = None
            if self.mode == "text" and self.current_span is not None:
                self._ghost_text(self.current_span)
                if self.canvas.bg is None:     # uretilemedi: opak kutuya don
                    self._tx_live = False
                    self.txt_new.setObjectName("mkInlineEdit")
                    self.txt_new.style().unpolish(self.txt_new)
                    self.txt_new.style().polish(self.txt_new)
                    self._tx_editor_color()
            # satir yuksekligi eski yakinlikta kalirsa imlec kuculup / buyuyup dikeyde kayiyordu
            self._tx_editor_color()
            self._position_text_editor()
        elif self.txt_new.isVisible():
            self._tx_editor_color()
            self._position_text_editor()
        self._show_page_number()
        self.lbl_zoom.setText(_t("%{z}", z=int(z * 100)))      # dile gore: %220 / 220%
        name = self._doc_name()
        info = _t("{name} · {n} sayfa", name=name, n=self.engine.page_count()) if name else ""
        if info and self.engine.password:
            info += " · " + _t("parola korumalı")
        self.lbl_fileinfo.setText(info)
        if self.mk_text.isVisible():           # sayfa ustundeki not yazisi kutusu zoomla birlikte
            self._mk_position_editor()
        if self.txt_new.isVisible():
            self._position_text_editor()

    def after_edit(self, all_thumbs=False):
        """Bir duzenlemeden sonra: sayfayi yeniden ciz, kucuk resmi ve
        pencere basligini guncelle."""
        # sayfa icerigi degistiyse buyutecler guncel halini gostersin
        if self.engine.doc and self.engine.sync_magnifiers(self.current_page):
            self._mk_loaded = None
        self.render_current_page()
        if all_thumbs:
            self._populate_thumbnails()
        else:
            self._update_thumb(self.current_page)
        self._update_title()
        self._refresh_panel()

    # ======================================================== modlar
    def set_mode(self, mode):
        self._inline_text_done()              # sayfada yazilan metin varsa once uygula
        if self.mode == "insert":
            self._insert_size = self.spin_size.value()
        self.mode = mode
        (self.btn_mode_markup if mode == "markup" else self.btn_mode_text).setChecked(True)
        if mode != "shape":
            self.shape_tool = "select"
        self._sync_edit_tools()
        self._clear_selection()
        if mode == "insert":
            idx = self.combo_font.findData("Arial")
            self.combo_font.setCurrentIndex(idx if idx >= 0 else 0)
            self.spin_size.setValue(self._insert_size)
            self.spin_opacity.setValue(100)
            self.chk_bold.setChecked(False)
            self.selected_color = None
            self.btn_color.set_rgb((0, 0, 0))
        self._refresh_panel()
        self.update_cursor()
        self.canvas.update()

    def _sync_edit_tools(self):
        """Duzenle'nin arac seridinde isaretli dugme = gercek durum."""
        if self.mode == "insert":
            b = self.btn_tx_new
        elif self.mode == "shape" and self.shape_tool != "select":
            b = {"line": self.btn_tool_line, "rect": self.btn_tool_rect, "ellipse": self.btn_tool_ellipse}[self.shape_tool]
        else:
            b = self.btn_tx_select
        b.setChecked(True)

    def _select_tool_active(self):
        """Duzenle'nin Sec araci mi acik? (ic durum "text" ya da "shape" + sec)"""
        return self.mode == "text" or (self.mode == "shape" and self.shape_tool == "select")

    def _enter_sub(self, mode):
        """Sec araci acikken ic durumu secime gore degistir ("text" <-> "shape"); set_mode'un
        aksine secimi temizlemez, yalnizca hangi kodun (yazi / cizim) devrede oldugunu belirler."""
        if self.mode != mode:
            self.mode = mode
            self.shape_tool = "select"
            self._sync_edit_tools()

    def set_shape_tool(self, tool):
        if tool != "select" and self.mode != "shape":      # Duzenle'de cizim aracina gecis
            self.set_mode("shape")
        self.shape_tool = tool
        self._sync_edit_tools()
        if tool != "select":
            self.sel_paths = []
            self._show_shape_style()      # secili ogenin stili degil, son kullanilan
        self.drag = None
        self._refresh_panel()
        self.update_cursor()
        self.canvas.update()

    # ---------------------------------------------- son kullanilan ayarlar
    def load_style_setting(self, key, default):
        """Kayitli stil sozlugunu oku; bozuk/eksik alanlar varsayilandan gelir."""
        try:
            data = json.loads(self._settings.value(key, "", type=str) or "{}")
        except (ValueError, TypeError):
            data = {}
        return self._merge_style(default, data)

    @classmethod
    def _merge_style(cls, default, data):
        out = {k: (dict(v) if isinstance(v, dict) else v) for k, v in default.items()}
        if not isinstance(data, dict):
            return out
        for k, v in data.items():
            if k not in default:
                continue
            dv = default[k]
            if isinstance(dv, dict):
                out[k] = cls._merge_style(dv, v)
            elif isinstance(dv, bool):
                out[k] = bool(v) if isinstance(v, bool) else dv
            elif isinstance(dv, (int, float)) and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = v
            elif isinstance(dv, list) and isinstance(v, list) and len(v) == len(dv):
                out[k] = v
            elif isinstance(dv, str) and isinstance(v, str):
                out[k] = v
            elif dv is None:
                out[k] = v
        return out

    def save_style_setting(self, key, value):
        try:
            self._settings.setValue(key, json.dumps(value))
        except (TypeError, ValueError):
            pass

    def _show_shape_style(self):
        st = self.shape_style
        self._shape_loading = True
        try:
            self.spin_width.setValue(float(st["width"]))
            self.btn_line_color.set_rgb(tuple(st["color"]))
            self.chk_dashed.setChecked(bool(st["dashed"]))
            self.cmb_dash.setCurrentIndex(max(self.cmb_dash.findData(st.get("dash") or "dash_m"), 0))
            self._shape_dash_visibility()
        finally:
            self._shape_loading = False

    def _shape_dash(self):
        """Cizgi/Kutu kesikli deseni: False (duz) ya da desen adi."""
        return self.cmb_dash.currentData() if self.chk_dashed.isChecked() else False

    def _shape_dash_visibility(self):
        """Desen listesi sadece kesikli acikken. (Henuz seride eklenmemisse dokunma:
        ebeveynsiz bir widget'i gorunur yapmak onu AYRI PENCERE olarak acar.)"""
        if self.cmb_dash.parent() is None:
            return
        self.cmb_dash.setVisible(self.chk_dashed.isChecked())
        if hasattr(self, "sh_opts_pill"):
            self._settle_bars()

    def _on_shape_style_edit(self, *_):
        if self._shape_loading:
            return
        self.shape_style = {"width": self.spin_width.value(),
                            "color": [float(c) for c in self.btn_line_color.rgb],
                            "dashed": self.chk_dashed.isChecked(),
                            "dash": self.cmb_dash.currentData()}
        self._shape_dash_visibility()
        self.save_style_setting("shape_style", self.shape_style)
        # secim varken: stil ANINDA secime uygulanir (ayri "uygula" dugmesi yok). Cizim
        # araci acikken de gecerli: yeni cizilen nesne secili kalir, stili hemen ona.
        if self.mode == "shape" and self.sel_paths:
            self._shape_style_timer.start()

    def _clear_selection(self):
        self.current_span = None
        self.hover_span = None
        self.sel_spans = []
        self.sel_images = []
        self.hover_image = None
        self.sel_paths = []
        self.hover_path = None
        self.pending_insert = None
        self.drag = None
        self._snap_pt = None
        self._nudge_token += 1
        self.sel_markup = None
        self.hover_markup = None
        self._set_render_hide(())
        self._mk_close_editor()
        if getattr(self, "txt_new", None) is not None and self.txt_new.parent() is self.canvas:
            self.txt_new.hide()

    def _set_render_hide(self, xrefs):
        """Surukleme sirasinda nesnenin kendisini sayfa goruntusunden gizle (yerine
        canli onizleme cizilir); bos demet = hepsi gorunur."""
        xrefs = tuple(xrefs)
        if xrefs == getattr(self, "_render_hide", ()):
            return
        self._render_hide = xrefs
        if self.engine.doc:
            self.render_current_page()

    def update_cursor(self, shape=None):
        if shape is None:
            if self.mode == "insert" or (self.mode == "shape" and self.shape_tool != "select") \
                    or (self.mode == "markup" and self.mk_tool != "select"):
                shape = Qt.CrossCursor
            else:
                shape = Qt.ArrowCursor
        self.canvas.setCursor(QCursor(shape))

    # ======================================================== ortak yardimcilar
    def _tol(self, px):
        return px / self.canvas.zoom

    def _moved_enough(self, pos):
        return self._press_pos is not None and (
            abs(pos.x() - self._press_pos.x()) + abs(pos.y() - self._press_pos.y())) >= DRAG_START_PX

    # ---------------- akilli kilavuzlar (hizaya oturtma) ----------------
    SNAP_PX = 6                                   # ekranda bu kadar yaklasinca oturur

    def _set_text_snap(self, on):
        self.text_snap = bool(on)
        try:
            self._settings.setValue("text_snap", self.text_snap)
        except Exception:
            pass

    def _snap_on(self, mods):
        """Dugme acik -> oturt; Alt basiliyken o an icin tersi."""
        on = getattr(self, "text_snap", True)
        return (not on) if (mods & Qt.AltModifier) else on

    def _snap_targets(self, moving=None):
        """Sayfadaki diger (donmemis) yazilarin hizalari: sol / sag / orta x ve taban cizgisi y.
        Her biri (deger, kutu) - kutu, kilavuz cizgisinin nereye kadar uzanacagi icin."""
        if self.engine.doc[self.current_page].rotation:
            return None                           # donuk sayfada eksenler karisir: oturtma yok
        skip = set()
        for ln in (getattr(moving, "lines", None) or ([moving] if moving is not None else [])):
            skip.add((round(ln.origin[0], 2), round(ln.origin[1], 2)))
        T = {"l": [], "r": [], "c": [], "b": []}
        for sp in self.engine.get_spans(self.current_page):
            if sp.rotated or (round(sp.origin[0], 2), round(sp.origin[1], 2)) in skip:
                continue
            bb = sp.bbox
            T["l"].append((bb.x0, bb))
            T["r"].append((bb.x1, bb))
            T["c"].append(((bb.x0 + bb.x1) / 2, bb))
            T["b"].append((sp.origin[1], bb))
        pr = self.engine.doc[self.current_page].rect
        T["c"].append((pr.width / 2, fitz.Rect(pr.width / 2, 0, pr.width / 2, pr.height)))   # sayfa ortasi
        return T

    @staticmethod
    def _snap_best(refs, targets, tol, other_mid):
        """refs: [(tasinan yazinin hiza degeri, tur)], targets: {tur: [(deger, kutu)]}.
        En yakin eslesmeyi bul -> (kayma, deger, kutu) | None. Esit uzakliktakilerden diger
        eksende en yakini (kilavuz cizgisi kisa olsun)."""
        best = None
        for val, kind in refs:
            for tv, bb in targets.get(kind, ()):
                dist = abs(tv - val)
                if dist > tol:
                    continue
                far = abs(other_mid(bb))
                key = (round(dist, 2), far)
                if best is None or key < best[0]:
                    best = (key, tv - val, tv, bb)
        return None if best is None else best[1:]

    def _snap_span(self, d, span, dx, dy, free=(True, True)):
        """Yaziyi (dx, dy) kadar tasirken hizaya oturt -> (dx, dy, kilavuzlar).
        kilavuz: ("v", x, y0, y1) dikey cizgi / ("h", y, x0, x1) yatay cizgi (sayfa noktasi)."""
        if span.rotated:
            return dx, dy, []
        if "snap" not in d:
            d["snap"] = self._snap_targets(span)
        T = d["snap"]
        if not T:
            return dx, dy, []
        tol = self._tol(self.SNAP_PX)
        bb = fitz.Rect(span.bbox) + (dx, dy, dx, dy)
        base = span.origin[1] + dy
        guides = []
        if free[0]:
            ymid = (bb.y0 + bb.y1) / 2
            hit = self._snap_best([(bb.x0, "l"), (bb.x1, "r"), ((bb.x0 + bb.x1) / 2, "c")], T, tol,
                                  lambda t: (t.y0 + t.y1) / 2 - ymid)
            if hit is not None:
                off, x, t = hit
                dx += off
                bb = bb + (off, 0, off, 0)
                guides.append(("v", x, min(bb.y0, t.y0), max(bb.y1, t.y1)))
        if free[1]:
            xmid = (bb.x0 + bb.x1) / 2
            hit = self._snap_best([(base, "b")], T, tol, lambda t: (t.x0 + t.x1) / 2 - xmid)
            if hit is not None:
                off, y, t = hit
                dy += off
                bb = bb + (0, off, 0, off)
                guides.append(("h", y, min(bb.x0, t.x0), max(bb.x1, t.x1)))
        return dx, dy, guides

    def _snap_point(self, x, y, mods=Qt.NoModifier):
        """Yeni metin isaretcisi: nokta yakin bir sol hizaya / taban cizgisine oturur."""
        if not self._snap_on(mods) or not self.engine.doc:
            return x, y, []
        T = self._snap_targets(None)
        if not T:
            return x, y, []
        tol = self._tol(self.SNAP_PX)
        guides = []
        hit = self._snap_best([(x, "l")], T, tol, lambda t: (t.y0 + t.y1) / 2 - y)
        if hit is not None:
            x = hit[1]
            guides.append(("v", x, min(y, hit[2].y0), max(y, hit[2].y1)))
        hit = self._snap_best([(y, "b")], T, tol, lambda t: (t.x0 + t.x1) / 2 - x)
        if hit is not None:
            y = hit[1]
            guides.append(("h", y, min(x, hit[2].x0), max(x, hit[2].x1)))
        return x, y, guides

    def _paint_guides(self, p, cv, guides):
        if not guides:
            return
        p.save()
        p.setPen(self._pen(GUIDE_COL, 1))
        for kind, v, a, b in guides:
            if kind == "v":
                p1, p2 = cv.to_px((v, a)), cv.to_px((v, b))
                p1.setY(p1.y() - 8)
                p2.setY(p2.y() + 8)
            else:
                p1, p2 = cv.to_px((a, v)), cv.to_px((b, v))
                p1.setX(p1.x() - 8)
                p2.setX(p2.x() + 8)
            p.drawLine(p1, p2)
        p.restore()

    @staticmethod
    def _axis_lock(start, p):
        """Shift: hareketi baskin yondeki eksene kilitle."""
        if abs(p.x - start.x) >= abs(p.y - start.y):
            return fitz.Point(p.x, start.y)
        return fitz.Point(start.x, p.y)

    def _display_delta(self, dx, dy):
        """Ekranda gorunen (donmus sayfa) yondeki kaymayi sayfa uzayina cevirir."""
        m = self.canvas.derot
        return fitz.Point(dx * m.a + dy * m.c, dx * m.b + dy * m.d)

    def canvas_leave(self):
        self.lbl_coords.setText("")
        if self.hover_image is not None:
            self.hover_image = None
            self.canvas.update()
        if self.hover_span is not None or self.hover_path is not None or self.hover_markup is not None:
            self.hover_span = None
            self.hover_path = None
            self.hover_markup = None
            self.canvas.update()

    # ======================================================== fare olaylari
    def canvas_press(self, pt, pos, mods):
        if not self.engine.doc:
            return
        self._text_angle_commit()     # aci surgusunun bekleyen onizlemesi varsa once uygula
        self._press_pos = pos
        self._nudge_token += 1        # yeni tiklama: sonraki ok kaydirmalari yeni geri-al adimi
        if self._select_tool_active():
            self._edit_press(pt, pos, mods)
        elif self.mode == "text":
            self._text_press(pt, mods)
        elif self.mode == "shape":
            self._shape_press(pt, pos, mods)
        elif self.mode == "markup":
            self._mk_press(pt, pos, mods)
        else:
            self._insert_press(pt, pos)
        self.canvas.update()

    def canvas_move(self, pt, pos, mods, pressed):
        if not self.engine.doc:
            return
        self.lbl_coords.setText(f"x {pt.x:.1f}  y {pt.y:.1f} pt")
        if self._select_tool_active() and not (self.drag and pressed):
            self._edit_hover(pt, pos)
        elif self.mode == "text":
            self._text_move(pt, pos, mods, pressed)
        elif self.mode == "shape":
            self._shape_move(pt, pos, mods, pressed)
        elif self.mode == "markup":
            self._mk_move(pt, pos, mods, pressed)
        else:
            self._insert_move(pt, pos, mods, pressed)

    def canvas_release(self, pt, pos, mods):
        if not self.engine.doc:
            return
        try:
            if self.mode == "text":
                self._text_release(pt, mods)
            elif self.mode == "shape":
                self._shape_release(pt, mods)
            elif self.mode == "markup":
                self._mk_release(pt, mods)
            else:
                self._insert_release()
        finally:
            self.drag = None
            self._snap_pt = None
            self._press_pos = None
            self._ghost_end()
            self._set_render_hide(())
            self.canvas.update()

    def canvas_double(self, pt):
        if self.mode == "shape" and self.shape_tool == "select":
            # bukme tutamacina cift tik = cizgiyi duzlestir
            if self._handle_at(self.canvas.to_px(pt)) == "bend":
                self.straighten_selected_line()
                return
            # Duzenle: bir cizim seciliyken YAZIYA cift tik -> o yaziyi duzenle
            span = self.engine.find_span_at(self.current_page, pt.x, pt.y)
            if span is None:
                return
            self._set_selection([span], [])
        if self.mode == "text" and self.current_span is not None:
            self._text_edit_begin(at=pt)      # yazi sayfanin ustunde duzenlenir; imlec tiklanan yerde
        elif self.mode == "markup":
            self._mk_double(pt)

    def canvas_context(self, pt, global_pos):
        if not self.engine.doc:
            return
        menu = QMenu(self)
        if self._select_tool_active() and not self.txt_new.isVisible():
            # Duzenle: tiklanan nesne neyse onun menusu (toplu secimin uyesi degilse o secilir)
            span, item, img = self._hit_object(pt)
            in_group = self._group_active() and (
                (span is not None and any(self._span_key(s) == self._span_key(span) for s in self.sel_spans))
                or (item is not None and item.index in self.sel_paths)
                or (img is not None and img.index in self.sel_images))
            if not in_group:
                if span is not None and (self.mode != "text" or self.sel_images):
                    self._set_selection([span], [])
                elif span is None and item is not None and (self.mode != "shape" or self._group_active()):
                    self._set_selection([], [item.index])
                elif img is not None:
                    self._set_selection([], [], [img.index])
        n_sel = len(self.sel_spans) + len(self.sel_paths) + len(self.sel_images)
        if self.mode == "text" and self._solo_image() is not None and self._in_selection_box(pt):
            menu.addAction(_t("Resmi kaydet..."), self.save_selected_image)
            menu.addAction(_t("Resmi değiştir..."), self.replace_selected_image)
            menu.addSeparator()
            menu.addAction(_t("Sil"), self.delete_selected)
        elif self.mode == "text" and self._group_active() and (self.sel_paths or self.sel_images) \
                and self._in_selection_box(pt):
            menu.addAction(_t("Seçili {n} öğeyi sil", n=n_sel), self.delete_selected)
            menu.addAction(_t("Seçimi kaldır"), lambda: self._set_selection([], []))
        elif self.mode == "text" and self.sel_spans and (
                (lambda s: s is not None and any(self._span_key(s) == self._span_key(x) for x in self.sel_spans))(
                    self.engine.find_span_at(self.current_page, pt.x, pt.y))):
            menu.addAction(_t("Seçili {n} yazıyı sil", n=len(self.sel_spans)), self.delete_selected)
            menu.addAction(_t("Seçimi kaldır"), lambda: self._set_text_selection([]))
        elif self.mode == "text":
            span = self.engine.find_span_at(self.current_page, pt.x, pt.y)
            if span is not None:
                self.sel_spans = []
                self._select_text_span(span)
                menu.addAction(_t("Metni düzenle"), lambda: self._text_edit_begin())
                menu.addSeparator()
                menu.addAction(_t("Kopyala\tCtrl+C"), self.copy_text)
                menu.addAction(_t("Çoğalt\tCtrl+D"), self.duplicate_text)
                menu.addSeparator()
                menu.addAction(_t("Sil"), self.delete_selected)
            elif getattr(self, "_text_clip", None) is not None or QApplication.clipboard().text().strip():
                menu.addAction(_t("Buraya yapıştır\tCtrl+V"), lambda: self.paste_text(at=pt))
        elif self.mode == "shape":
            item = self.engine.path_at(self.current_page, pt.x, pt.y, self._tol(5))
            if item is not None and item.index not in self.sel_paths:
                self.sel_paths = [item.index]
                self._on_path_selection()
            sel = self._sel_items()
            if len(sel) == 1 and sel[0].kind == "curve":
                menu.addAction(_t("Düzleştir"), self.straighten_selected_line)
            if self.sel_paths:
                menu.addAction(_t("Seçimi sil"), self.delete_selected)
                menu.addAction(_t("Seçimi kaldır"), self._deselect_paths)
            menu.addAction(_t("Sayfadaki tüm çizgileri seç"), self._select_all_paths)
        elif self.mode == "markup":
            self._mk_context(menu, pt)
        menu.addSeparator()
        menu.addMenu(self._page_menu(self.current_page))
        self.canvas.update()
        menu.exec(global_pos)

    # ---------------- metin modu ----------------
    def _text_press(self, pt, mods):
        if self.txt_new.isVisible():          # sayfada yaziliyordu: once uygula
            self._inline_text_done()
            return
        sp = self.current_span
        if sp is not None:
            q = self.canvas.to_px(self._text_rot_handle(sp))
            pos = self.canvas.to_px(pt)
            if abs(q.x() - pos.x()) <= HANDLE_PX + 4 and abs(q.y() - pos.y()) <= HANDLE_PX + 4:
                self.drag = {"kind": "textrot", "start": pt, "cur": pt, "moved": False,
                             "a0": self.engine.span_angle(sp)}
                return
        span = None
        # secili metin (ör. dev filigran) uzerindeyse onu tut; baskasina gecme
        if self.current_span is not None and self.current_span.hit(pt):
            span = self.current_span
        else:
            span = self.engine.find_span_at(self.current_page, pt.x, pt.y)
        shift = bool(mods & Qt.ShiftModifier)
        if shift and span is not None:                 # Shift + tik: secime ekle / cikar
            cur = self._selected_spans()
            k = self._span_key(span)
            if any(self._span_key(s) == k for s in cur):
                cur = [s for s in cur if self._span_key(s) != k]
            else:
                cur.append(span)
            self._set_text_selection(cur)
            return
        if self.sel_spans and not shift:               # toplu secim: uyesinden / icinden tut -> hepsi tasinir
            member = span is not None and any(self._span_key(s) == self._span_key(span) for s in self.sel_spans)
            bb, pad = self._group_bbox(), self._tol(4)
            inside = span is None and bb is not None and (bb.x0 - pad) <= pt.x <= (bb.x1 + pad) \
                and (bb.y0 - pad) <= pt.y <= (bb.y1 + pad)
            if member or inside:
                self.drag = {"kind": "tgroup", "start": pt, "cur": pt, "moved": False}
                return
        if span is None:                               # bos alan: surukleyince alan secimi
            if not shift and (self.current_span is not None or self.sel_spans):
                self._set_text_selection([])
            self.drag = {"kind": "tband", "start": pt, "cur": pt, "moved": False, "add": shift}
            return
        self.sel_spans = []
        if span is not self.current_span:
            self._select_text_span(span)
        self.drag = {"kind": "text", "start": pt, "cur": pt, "moved": False}

    # ---------------- Duzenle: Sec araci (yazi + sekil + resim tek secim) ----------------
    def _rot_handle_hit(self, pos):
        sp = self.current_span
        if self.mode != "text" or sp is None:
            return False
        q = self.canvas.to_px(self._text_rot_handle(sp))
        return abs(q.x() - pos.x()) <= HANDLE_PX + 4 and abs(q.y() - pos.y()) <= HANDLE_PX + 4

    def _hit_object(self, pt):
        """Noktadaki nesne -> (yazi | None, cizim | None, resim | None); en fazla biri dolu.
        Oncelik: yazi > cizim > resim (kutunun icindeki yaziya tiklayinca yazi, resmin
        ustundeki cizgiye tiklayinca cizgi secilir); secili yazinin ustundeyse o tutulur."""
        cs = self.current_span
        span = cs if (cs is not None and cs.hit(pt)) else self.engine.find_span_at(self.current_page, pt.x, pt.y)
        item = None if span is not None else self.engine.path_at(self.current_page, pt.x, pt.y, self._tol(5))
        img = None if (span is not None or item is not None) else self.engine.image_at(self.current_page, pt.x, pt.y)
        return span, item, img

    def _group_active(self):
        """Toplu secim durumu: 2+ yazi, yazi + cizim, ya da icinde resim olan her secim."""
        return bool(self.sel_spans or self.sel_images)

    def _in_selection_box(self, pt):
        """Nokta, coklu secimin sinir kutusunun icinde mi (aradaki bosluktan tutup tasimak icin)?"""
        bb = self._group_bbox() if self._group_active() else (self._sel_bbox() if self.sel_paths else None)
        if bb is None:
            return False
        pad = self._tol(4)
        return (bb.x0 - pad) <= pt.x <= (bb.x1 + pad) and (bb.y0 - pad) <= pt.y <= (bb.y1 + pad)

    # -- tek basina secili resim: kose tutamaclariyla boyutlandirilir
    def _solo_image(self):
        if len(self.sel_images) == 1 and not self.sel_spans and not self.sel_paths:
            items = self.engine.images_by_index(self.current_page, self.sel_images)
            return items[0] if items else None
        return None

    def _image_handles(self):
        it = self._solo_image()
        if it is None:
            return []
        r = it.bbox
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        return [("l", fitz.Point(r.x0, cy)), ("r", fitz.Point(r.x1, cy)),
                ("t", fitz.Point(cx, r.y0)), ("b", fitz.Point(cx, r.y1)),
                ("tl", fitz.Point(r.x0, r.y0)), ("tr", fitz.Point(r.x1, r.y0)),
                ("br", fitz.Point(r.x1, r.y1)), ("bl", fitz.Point(r.x0, r.y1))]

    def _image_handle_at(self, pos):
        for name, p in reversed(self._image_handles()):
            q = self.canvas.to_px(p)
            if abs(q.x() - pos.x()) <= HANDLE_PX + 3 and abs(q.y() - pos.y()) <= HANDLE_PX + 3:
                return name
        return None

    def _edit_press(self, pt, pos, mods):
        if self.txt_new.isVisible():          # sayfada yaziliyordu: once uygula
            self._inline_text_done()
            return
        shift = bool(mods & Qt.ShiftModifier)
        # 1) tutamaclar: yazinin dondurme tutamaci / cizimin ya da resmin boyut tutamaclari
        if self._rot_handle_hit(self.canvas.to_px(pt)):
            self._text_press(pt, mods)
            return
        if self.mode == "shape" and self._handle_at(pos):
            self._shape_press(pt, pos, mods)
            return
        h = self._image_handle_at(pos)
        if h:
            self._enter_sub("text")
            self.drag = {"kind": "ihandle", "handle": h, "start": pt, "cur": pt, "moved": False,
                         "bbox": fitz.Rect(self._solo_image().bbox)}
            return
        span, item, img = self._hit_object(pt)
        # 2) Shift + tik: secime ekle / cikar (yazi, cizim, resim)
        if shift and (span is not None or item is not None or img is not None):
            spans, paths, images = self._selected_spans(), list(self.sel_paths), list(self.sel_images)
            if span is not None:
                k = self._span_key(span)
                if any(self._span_key(s) == k for s in spans):
                    spans = [s for s in spans if self._span_key(s) != k]
                else:
                    spans.append(span)
            elif item is not None:
                paths.remove(item.index) if item.index in paths else paths.append(item.index)
            else:
                images.remove(img.index) if img.index in images else images.append(img.index)
            self._set_selection(spans, paths, images)
            return
        # 3) toplu secim: uyesinden ya da aradaki bosluktan tut -> hepsi tasinir
        if self._group_active() and not shift:
            member = (span is not None and any(self._span_key(s) == self._span_key(span) for s in self.sel_spans)) \
                or (item is not None and item.index in self.sel_paths) \
                or (img is not None and img.index in self.sel_images)
            if member or (span is None and item is None and img is None and self._in_selection_box(pt)):
                self._enter_sub("text")
                self.drag = {"kind": "tgroup", "start": pt, "cur": pt, "moved": False}
                return
        # 4) tek nesne: turune gore eski yazi / cizim mantigi devralir
        if span is not None:
            if self.sel_paths or self.sel_spans or self.sel_images:
                self.sel_paths, self.sel_spans, self.sel_images = [], [], []
            self._enter_sub("text")
            self._text_press(pt, mods)
            return
        if item is not None:
            self.current_span, self.sel_spans, self.sel_images = None, [], []
            self._enter_sub("shape")
            self._shape_press(pt, pos, mods)
            return
        if img is not None:                   # resim: secilir, surukleyince tasinir
            self._set_selection([], [], [img.index])
            self.drag = {"kind": "tgroup", "start": pt, "cur": pt, "moved": False}
            return
        # 5) bos alan: yalniz cizimlerden olusan secimin icindeyse onu tasi; degilse alan secimi
        if self.mode == "shape" and self.sel_paths and not shift and self._in_selection_box(pt):
            self._shape_press(pt, pos, mods)
            return
        if not shift and (self.current_span is not None or self.sel_spans or self.sel_paths or self.sel_images):
            self._set_selection([], [])
        self._enter_sub("text")
        self.drag = {"kind": "tband", "start": pt, "cur": pt, "moved": False, "add": shift}

    def _edit_hover(self, pt, pos):
        """Sec araci, fare basili degil: altindaki yazi / cizim / resim vurgulanir, imlec degisir."""
        if self._rot_handle_hit(pos):
            self.update_cursor(self._mk_handle_cursor("rot"))
            return
        if self.mode == "shape":
            h = self._handle_at(pos)
            if h:
                self.update_cursor(HANDLE_CURSORS[h])
                return
        h = self._image_handle_at(pos)
        if h:
            self.update_cursor(HANDLE_CURSORS[h])
            return
        span, item, img = self._hit_object(pt)
        hi = item.index if item is not None else None
        ii = img.index if img is not None else None
        if span is not self.hover_span or hi != self.hover_path or ii != self.hover_image:
            self.hover_span, self.hover_path, self.hover_image = span, hi, ii
            self.canvas.update()
        if span is not None or item is not None or img is not None or self._in_selection_box(pt):
            self.update_cursor(Qt.SizeAllCursor)
        else:
            self.update_cursor(None)

    def _set_selection(self, spans, paths, images=()):
        """Secimi ayarla ve ic durumu ona gore sec:
          yalniz cizim(ler)                 -> "shape" (boyut tutamaclari, cizgi ayarlari)
          tek yazi                          -> "text"  (yazi ayarlari, dondurme, cift tikla duzenleme)
          2+ yazi / yazi + cizim / resim(ler) -> toplu secim (birlikte tasinir / silinir;
                                                tek basina bir resim ayrica boyutlandirilir)"""
        uniq, seen = [], set()
        for s in self.engine.unique_spans(list(spans)):    # (her satir en cok bir kez)
            k = self._span_key(s)
            if k not in seen:
                seen.add(k)
                uniq.append(s)
        n_paths = len(self.engine.get_paths(self.current_page)) if paths else 0
        paths = sorted({i for i in paths if 0 <= i < n_paths})
        n_img = len(self.engine.get_images(self.current_page)) if images else 0
        images = sorted({i for i in images if 0 <= i < n_img})
        self.pending_insert = None
        if images or len(uniq) >= 2 or (uniq and paths):
            self._enter_sub("text")
            self.current_span = None
            self.sel_spans, self.sel_paths, self.sel_images = uniq, paths, images
            self._refresh_panel()
            n = len(uniq) + len(paths) + len(images)
            if n == 1:
                self.status(_t("Resim seçili — sürükleyerek taşıyın, köşelerinden boyutlandırın, Delete ile silin."))
            else:
                self.status(_t("{n} öğe seçili — sürükleyerek birlikte taşıyın, Delete ile silin.", n=n))
        elif not uniq:
            self.sel_spans, self.sel_images, self.current_span = [], [], None
            self._enter_sub("shape" if paths else "text")
            self.sel_paths = paths
            if paths:
                self._on_path_selection()
            else:
                self._refresh_panel()
        else:
            self.sel_spans, self.sel_paths, self.sel_images = [], [], []
            self._enter_sub("text")
            self._select_text_span(uniq[0])
        self.canvas.update()

    def select_all(self):
        """Sayfadaki tum yazilar, sekiller ve resimler (Ctrl+A). Sayfayi kaplayan zemin haric."""
        pr = self.engine.doc[self.current_page].rect
        everything = fitz.Rect(-1e5, -1e5, pr.width + 1e5, pr.height + 1e5)
        spans = self.engine.spans_in_rect(self.current_page, everything)
        paths = [it.index for it in self.engine.get_paths(self.current_page)
                 if abs(it.bbox.width * it.bbox.height) < 0.8 * abs(pr.width * pr.height)]
        images = [it.index for it in self.engine.images_in_rect(self.current_page, everything)]
        self._set_selection(spans, paths, images)

    # ---------------- toplu secim (yazilar, cizimler, resimler birlikte) ----------------
    @staticmethod
    def _span_key(sp):
        return (sp.page_num, round(sp.origin[0], 2), round(sp.origin[1], 2))

    def _selected_spans(self):
        """Secili yazilar: toplu secim varsa o, yoksa tek secili yazi."""
        return list(self.sel_spans) or ([self.current_span] if self.current_span is not None else [])

    def _set_text_selection(self, spans):
        """Secimi ayarla: 0 yazi = secim yok, 1 = normal tek secim (ayarlar, tutamaclar),
        2+ = toplu secim (birlikte tasinir / silinir; tek yaziya ozel ayarlar gizlenir)."""
        self._set_selection(spans, [])

    def _sel_image_items(self):
        return self.engine.images_by_index(self.current_page, self.sel_images)

    def _group_bbox(self):
        """Toplu secimin (yazilar + cizimler + resimler) sinir kutusu, sayfa koordinati."""
        box = None
        for s in self.sel_spans:
            q = s.quad()
            r = fitz.Rect(min(p.x for p in q), min(p.y for p in q), max(p.x for p in q), max(p.y for p in q))
            box = r if box is None else box | r
        for it in self._sel_image_items():
            box = fitz.Rect(it.bbox) if box is None else box | it.bbox
        if self.sel_paths:
            pb = self._sel_bbox()
            if pb is not None:
                box = fitz.Rect(pb) if box is None else box | pb
        return box

    def _ghost_group(self):
        """Toplu secim suruklenirken: hepsi yerinden kalkar, kendileri fareyle gider."""
        spans = list(self.sel_spans)
        items = self._sel_items() if self.sel_paths else []
        images = [it.index for it in self._sel_image_items()]
        lines = [ln for sp in spans for ln in (getattr(sp, "lines", None) or [sp])]
        if not lines and not items and not images:
            return

        def remove(doc, page):
            if items:
                pdf_paths.delete_items(doc, page, items)
            if images:
                pdf_images.delete(doc, page, images)
            if lines:
                return pdf_content.remove_texts_at(doc, page, [ln.origin for ln in lines])
        rect = None
        for sp in spans:
            r = self.canvas.poly_px(sp.quad()).boundingRect()
            rect = r if rect is None else rect.united(r)
        for it in self._sel_image_items():
            r = self.canvas.poly_px(it.quad).boundingRect()
            rect = r if rect is None else rect.united(r)
        if items:
            r = self.canvas.rect_px(self._sel_bbox())
            rect = r if rect is None else rect.united(r)
        # (yalniz yazi: kendi cizimleriyle ayrilir; cizim / resim de varsa fark yontemi)
        self._ghost_diff(rect.adjusted(-8, -8, 8, 8), remove, isolate=not items and not images)

    def _group_move(self, dx, dy, group=None):
        """Toplu secimi kaydir: TEK geri-al adimi. Secim, tasinmis haliyle korunur."""
        spans, paths, images = list(self.sel_spans), list(self.sel_paths), list(self.sel_images)
        moved = []
        with self.engine.undo_batch(group):
            if paths:                                  # once cizimler (sira numaralari tazeyken)
                self.engine.move_paths(self.current_page, paths, dx, dy)
            if images:
                self.engine.move_images(self.current_page, images, dx, dy)
            moved = self.engine.move_spans(spans, dx, dy)      # tek geciste (yazi basina degil)
        self.after_edit()
        self.sel_spans = [self._find_span_near(n) or n for n in moved]
        self._refresh_panel()
        self.canvas.update()

    def _group_delete(self):
        spans, paths, images = list(self.sel_spans), list(self.sel_paths), list(self.sel_images)
        with self.engine.undo_batch():
            if paths:
                self.engine.delete_paths(self.current_page, paths)
            if images:
                self.engine.delete_images(self.current_page, images)
            self.engine.delete_spans(spans)
        self.sel_spans, self.sel_paths, self.sel_images = [], [], []
        self.after_edit()
        n = len(spans) + len(paths) + len(images)
        self.status(_t("Resim silindi.") if (n == 1 and images) else _t("{n} öğe silindi.", n=n))

    # ---------------- resim: kaydet / degistir ----------------
    def save_selected_image(self):
        it = self._solo_image()
        got = self.engine.image_file(self.current_page, it.index) if it is not None else None
        if not got:
            return
        data, ext = got
        base = os.path.splitext(self._export_base() or "resim")[0]
        path, _ = QFileDialog.getSaveFileName(self, _t("Resmi kaydet"), f"{base}_resim.{ext}",
                                              _t("Resim dosyası (*.{ext})", ext=ext))
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(data)
        except OSError as e:
            QMessageBox.critical(self, _t("Kaydedilemedi"), str(e))
            return
        self.status(_t("Kaydedildi: {path}", path=path))

    def replace_selected_image(self):
        it = self._solo_image()
        if it is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, _t("Yeni resmi seçin"), "", image_tools.image_filter())
        if not path:
            return
        try:
            self.engine.replace_image(self.current_page, it.index, path)
        except Exception as e:
            QMessageBox.critical(self, _t("Açılamadı"), str(e))
            return
        self._set_selection([], [])
        self.after_edit()
        self.status(_t("Resim değiştirildi."))

    def select_all_text(self):
        """Sayfadaki tum yazilari sec (Ctrl+A, Metin)."""
        pr = self.engine.doc[self.current_page].rect
        self._set_text_selection(self.engine.spans_in_rect(
            self.current_page, fitz.Rect(-1e5, -1e5, pr.width + 1e5, pr.height + 1e5)))

    def _text_move(self, pt, pos, mods, pressed):
        d = self.drag
        if d and pressed:
            if not d["moved"] and not self._moved_enough(pos):
                return
            if d["kind"] == "tband":                        # alan cizerek secme
                d["moved"] = True
                d["cur"] = pt
                self.canvas.update()
                return
            if d["kind"] == "ihandle":                      # resim boyutlandiriliyor
                if not d["moved"]:
                    self._ghost_group()                     # resim yerinden kalkar, yeni hali cizilir
                d["moved"] = True
                d["cur"] = pt
                # resimde oran VARSAYILAN olarak korunur (Shift: serbest); Alt: merkezden
                d["nb"] = self._handle_bbox(d["handle"], d["bbox"], pt,
                                            keep=not (mods & Qt.ShiftModifier), center=bool(mods & Qt.AltModifier))
                self.canvas.update()
                return
            if d["kind"] == "tgroup":                       # toplu secim tasiniyor
                if not d["moved"]:
                    self._ghost_group()
                d["moved"] = True
                d["cur"] = self._axis_lock(d["start"], pt) if mods & Qt.ShiftModifier else pt
                self.canvas.update()
                return
            if not d["moved"] and d["kind"] in ("text", "textrot") and self.current_span is not None:
                self._ghost_text(self.current_span)        # yazi yerinden kalkar, kendisi gider
            d["moved"] = True
            if d["kind"] == "textrot":
                d["cur"] = pt
                d["keep"] = bool(mods & Qt.ShiftModifier)
            else:
                shift = bool(mods & Qt.ShiftModifier)
                cur = self._axis_lock(d["start"], pt) if shift else pt
                d["guides"] = []
                if self._snap_on(mods) and self.current_span is not None:
                    dx, dy = cur.x - d["start"].x, cur.y - d["start"].y
                    # Shift ile eksene kilitliyken sadece hareket eden eksende oturt
                    free = (not shift or abs(dx) > 0, not shift or abs(dy) > 0)
                    dx, dy, d["guides"] = self._snap_span(d, self.current_span, dx, dy, free)
                    cur = fitz.Point(d["start"].x + dx, d["start"].y + dy)
                d["cur"] = cur
            self.canvas.update()
            return
        if self.current_span is not None:
            q = self.canvas.to_px(self._text_rot_handle(self.current_span))
            if abs(q.x() - pos.x()) <= HANDLE_PX + 4 and abs(q.y() - pos.y()) <= HANDLE_PX + 4:
                self.update_cursor(self._mk_handle_cursor("rot"))
                return
        span = self.engine.find_span_at(self.current_page, pt.x, pt.y)
        if self.current_span is not None and self.current_span.hit(pt):
            span = self.current_span
        if span is None and self.sel_spans:              # toplu secimin icindeki bosluk da tutar
            bb, pad = self._group_bbox(), self._tol(4)
            inside = bb is not None and (bb.x0 - pad) <= pt.x <= (bb.x1 + pad) \
                and (bb.y0 - pad) <= pt.y <= (bb.y1 + pad)
            if self.hover_span is not None:
                self.hover_span = None
                self.canvas.update()
            self.update_cursor(Qt.SizeAllCursor if inside else None)
            return
        if span is not self.hover_span:
            self.hover_span = span
            self.update_cursor(Qt.SizeAllCursor if span is not None else None)
            self.canvas.update()

    def _text_release(self, pt, mods):
        d = self.drag
        if not d or not d["moved"]:
            return
        if d["kind"] == "tband":
            # AutoCAD'deki gibi: soldan saga cizilen alan yalnizca TAMAMI icinde kalanlari,
            # sagdan sola cizilen alan DEGDIGI her yaziyi secer
            rect = fitz.Rect(d["start"], d["cur"])
            inside = d["cur"].x >= d["start"].x
            found = self.engine.spans_in_rect(self.current_page, rect, inside=inside)
            pr = self.engine.doc[self.current_page].rect
            paths = [it.index for it in self.engine.paths_in_rect(self.current_page, rect, touch=not inside)
                     if abs(it.bbox.width * it.bbox.height) < 0.8 * abs(pr.width * pr.height)]
            images = [it.index for it in self.engine.images_in_rect(self.current_page, rect, touch=not inside)]
            if d.get("add"):
                found = self._selected_spans() + found
                paths = list(self.sel_paths) + paths
                images = list(self.sel_images) + images
            self._set_selection(found, paths, images)
            return
        if d["kind"] == "ihandle":
            it, nb = self._solo_image(), d.get("nb")
            if it is not None and nb is not None and (abs(nb.width - d["bbox"].width) > 0.05
                                                      or abs(nb.height - d["bbox"].height) > 0.05):
                self.engine.scale_image(self.current_page, it.index, d["bbox"], nb)
                self.after_edit()
                self.status(_t("Resim boyutlandırıldı."))
            return
        if d["kind"] == "tgroup":
            dx, dy = d["cur"].x - d["start"].x, d["cur"].y - d["start"].y
            if abs(dx) > 0.05 or abs(dy) > 0.05:
                n = len(self.sel_spans) + len(self.sel_paths) + len(self.sel_images)
                solo = self._solo_image() is not None
                self._group_move(dx, dy)
                self.status(_t("Resim taşındı.") if solo else _t("{n} öğe taşındı.", n=n))
            return
        if self.current_span is None:
            return
        if d["kind"] == "textrot":
            target = self._text_drag_angle(d)
            self._rotate_text_by(((target - d["a0"] + 180.0) % 360.0) - 180.0)
            return
        dx, dy = d["cur"].x - d["start"].x, d["cur"].y - d["start"].y
        if abs(dx) < 0.05 and abs(dy) < 0.05:
            return
        new = self.engine.move_span(self.current_span, dx, dy)
        self.after_edit()
        self._select_text_span(self._find_span_near(new) or new)
        self.status(_t("Metin taşındı."))

    def _find_span_near(self, span, tol=1.5):
        """Duzenlemeden sonra ayni taban noktasindaki guncel span'i bul. Bulunamazsa
        (saga dayali / ortali yazida baslangic kayar) ayni satirda eski yerle ortusen."""
        best, bd = None, tol
        spans = self.engine.get_spans(span.page_num)
        for s in spans:
            d = abs(s.origin[0] - span.origin[0]) + abs(s.origin[1] - span.origin[1])
            if d <= bd:
                best, bd = s, d
        if best is None:
            ob = span.bbox
            cands = [s for s in spans if abs(s.origin[1] - span.origin[1]) <= 1.0
                     and s.bbox.x0 <= ob.x1 and s.bbox.x1 >= ob.x0]
            if cands:
                best = min(cands, key=lambda s: abs((s.bbox.x0 + s.bbox.x1) - (ob.x0 + ob.x1)))
        return self.engine.expand(best)          # paragrafin satiriysa paragrafin tamami

    def _select_text_span(self, span):
        QTimer.singleShot(0, self._warm_text_scan)
        self.pending_insert = None
        self.current_span = span
        self._text_loading = True           # secili metnin ayarlarini gostermek = degisiklik degil
        try:
            self.txt_selected.setText(span.text.replace("\xa0", " "))
            self.txt_new.blockSignals(True)
            self.txt_new.setPlainText(span.text.replace("\xa0", " "))
            self.txt_new.blockSignals(False)
            self.spin_size.setValue(round(span.size, 1))
            self.spin_opacity.setValue(max(1, round(span.opacity * 100)))
            if getattr(span, "line_spacing", None):          # paragraf: gercek satir araligi
                self.spin_spacing.setValue(round(span.line_spacing, 2))
            self.combo_font.setCurrentIndex(0)
            self.chk_bold.setChecked(span.is_bold)
            self.selected_color = None
            self.btn_color.set_rgb(span.color_rgb())
            a = self.engine.span_angle(span)
            self.spin_text_angle.blockSignals(True)
            self.spin_text_angle.setValue(int(round(a)))
            self.spin_text_angle.blockSignals(False)
        finally:
            self._text_loading = False
        self._text_style_timer.stop()
        self._refresh_panel()
        self.canvas.update()

    # ---------------- metin dondurme ----------------
    def _text_rot_handle(self, span):
        """Dondurme tutamaci: yazinin ust kenarinin ortasindan yukari (yaziya gore)."""
        q = span.quad()
        top = (q[0] + q[1]) * 0.5
        c = self.engine.span_center(span)
        v = top - c
        L = abs(v)
        u = fitz.Point(v.x / L, v.y / L) if L > 1e-6 else fitz.Point(0, -1)
        return top + u * self._tol(24)

    @staticmethod
    def _preview_family(pdf_font):
        """PDF font adindan (ABCDEF+TimesNewRomanPS-BoldMT, 'Arial,Bold'...) onizleme
        icin yaklasik Windows font ailesi."""
        n = (pdf_font or "").split("+")[-1].lower().replace(" ", "")
        for key, fam in (("times", "Times New Roman"), ("arial", "Arial"), ("helvetica", "Arial"),
                         ("calibri", "Calibri"), ("cambria", "Cambria"), ("courier", "Courier New"),
                         ("verdana", "Verdana"), ("tahoma", "Tahoma"), ("segoe", "Segoe UI"),
                         ("georgia", "Georgia"), ("garamond", "Garamond")):
            if key in n:
                return fam
        return "Arial"

    def _text_drag_angle(self, d):
        if "target" in d:                       # aci kutusu / surgu: hedef aci dogrudan
            return d["target"]
        c = self.engine.span_center(self.current_span)
        deg = math.degrees(math.atan2(d["cur"].y - c.y, d["cur"].x - c.x)) + 90.0
        return self._snap_angle(deg, d.get("keep"))

    def _rotate_text_by(self, delta, group=None):
        sp = self.current_span
        if sp is None or abs(delta) < 0.05:
            return
        new = self.engine.rotate_span(sp, delta, group=group)
        self.after_edit()
        self._select_text_span(self._find_span_near(new) or new)
        self.status(_t("Metin döndürüldü: {a}°", a=f"{self.engine.span_angle(self.current_span):.0f}"))

    # --- aci kutusu / surgu: tutamacla dondurmenin "sahte suruklemesi" (onizleme + tek uygulama)
    def _text_angle_live(self, v):
        sp = self.current_span
        if sp is None or self.mode != "text" or not self.engine.doc or self._text_angle_busy:
            return
        d = self.drag
        if not (d and d.get("slider")):
            if d:                               # fareyle gercek bir surukleme suruyor
                return
            a0 = self.engine.span_angle(sp)
            if int(v) == int(round(a0)):        # gosterilen aciyla ayni: degisiklik yok
                return
            d = self.drag = {"kind": "textrot", "slider": True, "moved": True, "a0": a0}
            self._ghost_text(sp)                # yazi yerinden kalkar; onizlemede kendisi doner
        d["target"] = float(v)
        self.canvas.update()
        self._text_angle_timer.start()

    def _text_angle_commit(self):
        """Onizlenen aciyi PDF'e uygula (bekleyen yoksa False)."""
        self._text_angle_timer.stop()
        if self._text_angle_busy:
            return True
        d = self.drag
        if not (d and d.get("slider")):
            return False
        # KILIT: dondurme sirasinda (after_edit -> odak degisimi) Qt editingFinished'i bir kez
        # daha yollar; ic ice ikinci cagri ESKI span ile tekrar dondurur, yaziyi eski yerinde
        # bulamayinca geometrik yedege dusup yeni yazinin ortasini silerdi.
        self._text_angle_busy = True
        try:
            if self.current_span is not None:
                self._rotate_text_by(((d["target"] - d["a0"] + 180.0) % 360.0) - 180.0,
                                     group=("txangle", self.current_page, self._nudge_token))
        finally:
            self._text_angle_busy = False
            self.drag = None
            self._ghost_end()
            self._set_render_hide(())
            self.canvas.update()
        return True

    def _text_angle_cancel(self):
        """Esc: onizlemeyi birak, kutuyu yazinin gercek acisina dondur."""
        self._text_angle_timer.stop()
        if self.current_span is not None:
            self.spin_text_angle.blockSignals(True)
            self.spin_text_angle.setValue(int(round(self.engine.span_angle(self.current_span))))
            self.spin_text_angle.blockSignals(False)

    def _text_angle_entered(self):
        """Enter / kutudan cikis: bekleyen onizleme varsa hemen uygula, yoksa yazilan aci."""
        if self._text_angle_busy:
            return
        if not self._text_angle_commit():
            # Kutu aciyi TAM SAYIYA yuvarlayip gosterir (tutamacla 38,4° -> "38°"). Kutudaki
            # sayi gosterilenle ayniysa kullanici bir sey yazmamistir: dokunma. Yoksa surgu
            # (▾) acilirken odak degisince yazi 38,4 -> 38,0'a "duzeltiliyor", PDF yeniden
            # yazilip sayfa ciziliyor (surgu gec aciliyordu) ve geri-al adimi ekleniyordu.
            sp = self.current_span
            if sp is not None and self.spin_text_angle.value() != int(round(self.engine.span_angle(sp))):
                self._rotate_text_to(self.spin_text_angle.value())

    def _rotate_text_to(self, deg, live=False):
        """live: surgu / tekerlek - ayni secimdeki ard arda donusler TEK geri-al adimi."""
        sp = self.current_span
        if sp is None:
            return
        cur = self.engine.span_angle(sp)
        delta = ((deg - cur + 180.0) % 360.0) - 180.0
        group = ("txangle", self.current_page, self._nudge_token) if live else None
        self._rotate_text_by(delta, group=group)

    # ---------------- yazi: kopyala / yapistir / cogalt ----------------
    def copy_text(self):
        sp = self.current_span
        if sp is None:
            return
        self._text_clip = (sp, sp.text.replace("\xa0", " "))
        self._paste_n = 0
        QApplication.clipboard().setText(self._text_clip[1])
        self.status(_t("Yazı kopyalandı. Yapıştırmak için Ctrl+V."))

    def duplicate_text(self):
        """Secili yazinin kopyasi, biraz sag-alta (Ctrl+D)."""
        sp = self.current_span
        if sp is None:
            return
        step = max(8.0, sp.size * 0.9)
        new = self.engine.duplicate_span(sp, step, step)
        self.after_edit()
        self._select_text_span(self._find_span_near(new) or new)
        self.status(_t("Yazı çoğaltıldı."))

    def paste_text(self, at=None):
        """Kopyalanan yaziyi ayni gorunumle yapistir (at: sayfa noktasi = yazinin basi).
        Panoda baska programdan gelen duz metin varsa yeni yazi olarak eklenir."""
        if not self.engine.doc:
            return
        clip = getattr(self, "_text_clip", None)
        text = QApplication.clipboard().text()
        if clip is not None and (not text or text == clip[1]):
            sp = clip[0]
            if at is not None:
                dx, dy = at.x - sp.origin[0], at.y - sp.origin[1]
            elif sp.page_num == self.current_page:
                self._paste_n = getattr(self, "_paste_n", 0) + 1
                step = max(8.0, sp.size * 0.9) * self._paste_n       # ust uste binmesin
                dx = dy = step
            else:
                dx = dy = 0.0                                       # baska sayfa: ayni yere
            new = self.engine.duplicate_span(sp, dx, dy, self.current_page)
        elif text.strip():
            if at is None:                      # gorunen alanin ortasi
                vp = self.scroll.viewport()
                c = self.canvas.mapFrom(vp, QPoint(vp.width() // 2, vp.height() // 2))
                at = self.canvas.to_pdf(c)
            size = self.spin_size.value() or 11
            self.engine.insert_text_new(
                self.current_page, at.x, at.y, text.replace("\r\n", "\n").rstrip("\n"),
                fontsize=size, color_rgb=self.selected_color or (0, 0, 0),
                font_hint=self.combo_font.currentData() or "Arial", bold=self.chk_bold.isChecked(),
                opacity=self.spin_opacity.value() / 100, line_spacing=self.spin_spacing.value())
            new = None
        else:
            return
        if self.mode != "text":
            self.set_mode("text")
        self.after_edit()
        if new is None:
            new = self.engine.find_span_at(self.current_page, at.x + 1, at.y - 1)
        if new is not None:
            self._select_text_span(self._find_span_near(new) or new)
        self.status(_t("Yapıştırıldı."))

    def _on_text_color(self, rgb):
        self.selected_color = rgb
        self.canvas.update()
        if self.txt_new.isVisible():           # yazarken renk secildi: kutudaki yazi da degissin
            self._tx_editor_color()

    # ---------------- yeni metin modu ----------------
    def _marker_hit(self, pos):
        if self.pending_insert is None:
            return False
        _, x, y = self.pending_insert
        m = self.canvas.to_px((x, y))
        h = self.spin_size.value() * self.canvas.zoom
        return abs(pos.x() - m.x()) <= 8 and -h - 4 <= pos.y() - m.y() <= 6

    def _insert_press(self, pt, pos):
        if self._marker_hit(pos):
            _, x, y = self.pending_insert
            self.drag = {"kind": "marker", "start": pt, "cur": pt, "moved": False, "orig": (x, y)}
            return
        if self.txt_new.isVisible() and self.txt_new.toPlainText().strip():
            self._inline_text_done()          # yazilan metni ekle; yeni metin icin tekrar tikla
            return
        # tiklanan yerde yazma kutusu acilir; yazip Esc / Ctrl+Enter / baska yere tikla
        sx, sy, _g = self._snap_point(pt.x, pt.y, QApplication.keyboardModifiers())
        self.pending_insert = (self.current_page, sx, sy)
        self._text_loading = True
        try:
            self.txt_new.clear()
        finally:
            self._text_loading = False
        self._refresh_panel()
        self._text_edit_begin(select_all=False)

    def _insert_move(self, pt, pos, mods, pressed):
        d = self.drag
        if d and pressed:
            if not d["moved"] and not self._moved_enough(pos):
                return
            d["moved"] = True
            cur = self._axis_lock(d["start"], pt) if mods & Qt.ShiftModifier else pt
            ox, oy = d["orig"]
            nx, ny, d["guides"] = self._snap_point(ox + cur.x - d["start"].x, oy + cur.y - d["start"].y, mods)
            self.pending_insert = (self.current_page, nx, ny)
            self._position_text_editor()
            self.canvas.update()
            return
        self.update_cursor(Qt.SizeAllCursor if self._marker_hit(pos) else None)

    def _insert_release(self):
        pass

    # ---------------- cizgi / kutu modu ----------------
    def _sel_items(self):
        return self.engine.paths_by_index(self.current_page, self.sel_paths)

    def _sel_bbox(self):
        items = self._sel_items()
        if not items:
            return None
        # DIKKAT: fitz'in 'r |= bbox' birlesimi yuksekligi/genisligi sifir olan
        # (yatay/dikey cizgi) kutulari "bos" sayip yok sayar; elle birlestir.
        return fitz.Rect(min(it.bbox.x0 for it in items), min(it.bbox.y0 for it in items),
                         max(it.bbox.x1 for it in items), max(it.bbox.y1 for it in items))

    def _handles(self):
        items = self._sel_items()
        if not items or self.shape_tool != "select":
            return []
        if len(items) == 1 and items[0].kind in ("line", "curve"):
            a, b = items[0].line_points()
            m = items[0].bend_point() or (a + b) * 0.5
            # uc tutamaclari sonda: ust uste binerse (cok kisa cizgi) uc oncelikli
            return [("bend", m), ("p1", a), ("p2", b)]
        r = self._sel_bbox()
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        wide, tall = r.width > 0.5, r.height > 0.5
        hs = []
        if wide and tall:
            hs += [("tl", fitz.Point(r.x0, r.y0)), ("tr", fitz.Point(r.x1, r.y0)),
                   ("br", fitz.Point(r.x1, r.y1)), ("bl", fitz.Point(r.x0, r.y1))]
        if wide:
            hs += [("l", fitz.Point(r.x0, cy)), ("r", fitz.Point(r.x1, cy))]
        if tall:
            hs += [("t", fitz.Point(cx, r.y0)), ("b", fitz.Point(cx, r.y1))]
        return hs

    def _handle_at(self, pos):
        for name, p in reversed(self._handles()):
            q = self.canvas.to_px(p)
            if abs(q.x() - pos.x()) <= HANDLE_PX + 3 and abs(q.y() - pos.y()) <= HANDLE_PX + 3:
                return name
        return None

    @staticmethod
    def _handle_bbox(name, old, p, keep=False, center=False):
        """Tutamac surukleyince olusan yeni sinir kutusu. center (Alt): merkez sabit,
        sekil iki yana esit buyur/kuculur (karsi kenar degil)."""
        nb = MainWindow._handle_bbox_edge(name, old, p, keep)
        if not center:
            return nb
        x0, y0, x1, y1 = nb.x0, nb.y0, nb.x1, nb.y1
        # oynayan kenarin tersini karsi tarafa yansit
        if name in ("tl", "bl", "l"):
            x1 = old.x1 + (old.x0 - x0)
        elif name in ("tr", "br", "r"):
            x0 = old.x0 - (x1 - old.x1)
        if name in ("tl", "tr", "t"):
            y1 = old.y1 + (old.y0 - y0)
        elif name in ("bl", "br", "b"):
            y0 = old.y0 - (y1 - old.y1)
        # kenar tutamaciyla oran korunurken diger eksen zaten merkezden
        if name in ("l", "r") and not keep:
            y0, y1 = old.y0, old.y1
        if name in ("t", "b") and not keep:
            x0, x1 = old.x0, old.x1
        if x1 - x0 < 1:
            cx = (old.x0 + old.x1) / 2
            x0, x1 = cx - 0.5, cx + 0.5
        if y1 - y0 < 1:
            cy = (old.y0 + old.y1) / 2
            y0, y1 = cy - 0.5, cy + 0.5
        return fitz.Rect(x0, y0, x1, y1)

    @staticmethod
    def _drag_box(d):
        """Surukleyerek cizilen kutu/daire: Alt basiliysa baslangic noktasi MERKEZ."""
        a, b = d["start"], d["cur"]
        if d.get("center"):
            a = fitz.Point(2 * a.x - b.x, 2 * a.y - b.y)
        return fitz.Rect(a, b).normalize()

    @staticmethod
    def _handle_bbox_edge(name, old, p, keep=False):
        """Tutamac surukleyince olusan yeni sinir kutusu (ters donmesin diye
        karsi kenara en fazla 1 pt yaklasir).
        keep (Shift): en-boy orani korunur (daire daire, kare kare kalir)."""
        x0, y0, x1, y1 = old.x0, old.y0, old.x1, old.y1
        if name in ("tl", "bl", "l"):
            x0 = min(p.x, x1 - 1)
        if name in ("tr", "br", "r"):
            x1 = max(p.x, x0 + 1)
        if name in ("tl", "tr", "t"):
            y0 = min(p.y, y1 - 1)
        if name in ("bl", "br", "b"):
            y1 = max(p.y, y0 + 1)
        if not keep or old.width < 1e-6 or old.height < 1e-6:
            return fitz.Rect(x0, y0, x1, y1)
        ar = old.width / old.height
        if name in ("tl", "tr", "bl", "br"):
            # karsi kose sabit; baskin yondeki buyume esas alinir
            s = max((x1 - x0) / old.width, (y1 - y0) / old.height)
            w, h = old.width * s, old.height * s
            if name in ("tl", "bl"):
                x0 = old.x1 - w
            else:
                x1 = old.x0 + w
            if name in ("tl", "tr"):
                y0 = old.y1 - h
            else:
                y1 = old.y0 + h
        elif name in ("l", "r"):
            # kenar tutamaci: diger eksen merkezden buyur/kuculur
            h, cy = (x1 - x0) / ar, (old.y0 + old.y1) / 2
            y0, y1 = cy - h / 2, cy + h / 2
        else:
            w, cx = (y1 - y0) * ar, (old.x0 + old.x1) / 2
            x0, x1 = cx - w / 2, cx + w / 2
        return fitz.Rect(x0, y0, x1, y1)

    @staticmethod
    def _scale_matrix(o, n):
        sx = n.width / o.width if o.width > 1e-6 else 1.0
        sy = n.height / o.height if o.height > 1e-6 else 1.0
        return (fitz.Matrix(1, 0, 0, 1, -o.x0, -o.y0) * fitz.Matrix(sx, 0, 0, sy, 0, 0)
                * fitz.Matrix(1, 0, 0, 1, n.x0, n.y0))

    def _snap(self, pt, exclude=(), along=True):
        """Yakindaki cizgi uclarina/koselerine (yoksa cizgi uzerine) yapistir.
        Tablo cizerken yeni cizgilerin mevcut izgaraya tam oturmasini saglar."""
        tol = self._tol(SNAP_PX)
        best, bd = None, tol
        items = [it for it in self.engine.get_paths(self.current_page) if it.index not in exclude]
        for it in items:
            for poly, closed in it.polys:
                cands = poly if (closed or it.kind == "rect") else [poly[0], poly[-1]]
                for c in cands:
                    d = abs(c - pt)
                    if d < bd:
                        best, bd = fitz.Point(c), d
        if best is None and along:
            for it in items:
                if it.kind not in ("line", "rect"):
                    continue
                for poly, _ in it.polys:
                    for i in range(len(poly) - 1):
                        q = _proj(pt, poly[i], poly[i + 1])
                        d = abs(q - pt)
                        if d < bd:
                            best, bd = q, d
        self._snap_pt = best
        return best if best is not None else pt

    def _line_end(self, fixed, pt, mods, exclude=(), keep=None):
        """Cizgi ucunun yeni konumu (cizerken ve uc tutamaciyla duzenlerken ayni):
        serbest aci; neredeyse yatay/dikeyse (3 derece) otomatik duzeltilir.
        Shift: 45 derecenin katlarina kilitlenir (0/45/90/135...).
        Alt: duzenlerken (keep = ucun eski yeri) ACI SABIT, sadece uzunluk degisir;
        cizerken tamamen serbest (otomatik duzeltme yok)."""
        if mods & Qt.AltModifier and keep is not None:
            self._snap_pt = None
            return curve_math.keep_angle(fixed, keep, pt)
        p = self._snap(pt, exclude)
        if mods & Qt.ShiftModifier:
            step = math.pi / 4
            ang = round(math.atan2(pt.y - fixed.y, pt.x - fixed.x) / step) * step
        elif mods & Qt.AltModifier:
            return p
        else:
            raw = math.atan2(p.y - fixed.y, p.x - fixed.x)
            near = round(raw / (math.pi / 2)) * (math.pi / 2)
            if abs(raw - near) >= math.radians(3):
                return p
            ang = near
        # yapisilan noktanin bu dogrultu uzerindeki izdusumu
        ux, uy = math.cos(ang), math.sin(ang)
        t = (p.x - fixed.x) * ux + (p.y - fixed.y) * uy
        q = fitz.Point(fixed.x + t * ux, fixed.y + t * uy)
        # yatay/dikeyde kayan nokta hatasi birakma
        if abs(uy) < 1e-9:
            q.y = fixed.y
        elif abs(ux) < 1e-9:
            q.x = fixed.x
        return q

    @staticmethod
    def _handle_line_ends(d):
        """Uc tutamaci surukelenirken cizginin (bas, son) noktalari."""
        if d["handle"] == "p1":
            return d["cur"], d["fixed"]
        if d["handle"] == "p2":
            return d["fixed"], d["cur"]
        return d["a0"], d["b0"]

    def _bend_target(self, a, b, pt, mods):
        """Bukme tutamacinin yeni yeri: Shift = simetrik yay; duz cizgiye cok
        yakinsa None (cizgi duz kalir -> duz cizgi mantigi korunur)."""
        m = curve_math.symmetric(a, b, pt) if mods & Qt.ShiftModifier else fitz.Point(pt)
        return None if curve_math.is_straight(a, m, b, self._tol(BEND_SNAP_PX)) else m

    def straighten_selected_line(self):
        items = self._sel_items()
        if len(items) != 1 or items[0].kind != "curve":
            return
        a, b = items[0].line_points()
        self.engine.set_line_points(self.current_page, items[0].index, a, b, None)
        self.after_edit()
        self._on_path_selection()
        self.status(_t("Çizgi düzleştirildi."))

    def _shape_press(self, pt, pos, mods):
        if self.shape_tool in ("line", "rect", "ellipse"):
            p = self._snap(pt)
            self.drag = {"kind": "draw", "start": p, "cur": p, "moved": False}
            return
        h = self._handle_at(pos)
        if h:
            items = self._sel_items()
            d = {"kind": "handle", "handle": h, "start": pt, "cur": pt, "moved": False,
                 "bbox": self._sel_bbox()}
            if h in ("p1", "p2", "bend"):
                a, b = items[0].line_points()
                d["fixed"] = b if h == "p1" else a
                d["index"] = items[0].index
                d["a0"], d["b0"] = a, b
                d["bend0"] = items[0].bend_point()
                d["bend"] = d["bend0"]
            self.drag = d
            return
        item = self.engine.path_at(self.current_page, pt.x, pt.y, self._tol(5))
        if item is not None:
            if mods & Qt.ShiftModifier:
                if item.index in self.sel_paths:
                    self.sel_paths.remove(item.index)
                else:
                    self.sel_paths.append(item.index)
                self._on_path_selection()
                return
            if item.index not in self.sel_paths:
                self.sel_paths = [item.index]
                self._on_path_selection()
            self.drag = {"kind": "move", "start": pt, "cur": pt, "moved": False}
            return
        # secimin sinir kutusu icinden tutulursa (izgara arasi bosluk) tum secimi tasi
        bb = self._sel_bbox()
        if bb is not None and not (mods & Qt.ShiftModifier):
            pad = self._tol(4)
            if (bb.x0 - pad) <= pt.x <= (bb.x1 + pad) and (bb.y0 - pad) <= pt.y <= (bb.y1 + pad):
                self.drag = {"kind": "move", "start": pt, "cur": pt, "moved": False}
                return
        if not (mods & Qt.ShiftModifier) and self.sel_paths:
            self.sel_paths = []
            self._on_path_selection()
        self.drag = {"kind": "band", "start": pt, "cur": pt, "moved": False,
                     "add": bool(mods & Qt.ShiftModifier)}

    def _shape_move(self, pt, pos, mods, pressed):
        d = self.drag
        if d and pressed:
            if not d["moved"] and not self._moved_enough(pos):
                return
            if not d["moved"] and d["kind"] in ("move", "handle"):
                self._ghost_paths()     # cizim yerinden kalkar: tasirken kendisi, tutamacta yeni hali
            d["moved"] = True
            k = d["kind"]
            if k == "move":
                d["cur"] = self._axis_lock(d["start"], pt) if mods & Qt.ShiftModifier else pt
            elif k == "handle":
                if d["handle"] in ("p1", "p2"):
                    d["cur"] = self._line_end(d["fixed"], pt, mods, exclude=(d["index"],),
                                              keep=d["a0"] if d["handle"] == "p1" else d["b0"])
                    a, b = self._handle_line_ends(d)
                    d["bend"] = curve_math.carry(d["a0"], d["b0"], d["bend0"], a, b)
                elif d["handle"] == "bend":
                    d["cur"] = pt
                    d["bend"] = self._bend_target(d["a0"], d["b0"], pt, mods)
                else:
                    d["cur"] = pt
                    d["keep"] = bool(mods & Qt.ShiftModifier)
                    d["center"] = bool(mods & Qt.AltModifier)    # Alt: merkezden
            elif k == "draw":
                d["center"] = bool(mods & Qt.AltModifier)        # Alt: tiklanan nokta merkez
                if self.shape_tool == "line":
                    d["cur"] = self._line_end(d["start"], pt, mods)
                elif mods & Qt.ShiftModifier:                    # kare / tam daire
                    self._snap_pt = None
                    d["cur"] = self._square(d["start"], pt)
                elif self.shape_tool == "ellipse" or d["center"]:
                    self._snap_pt = None
                    d["cur"] = pt
                else:
                    d["cur"] = self._snap(pt, along=False)
            else:
                d["cur"] = pt
            self.canvas.update()
            return
        # --- hover ---
        if self.shape_tool != "select":
            self.update_cursor()
            return
        h = self._handle_at(pos)
        if h:
            self.update_cursor(HANDLE_CURSORS[h])
            return
        item = self.engine.path_at(self.current_page, pt.x, pt.y, self._tol(5))
        hi = item.index if item is not None else None
        if hi != self.hover_path:
            self.hover_path = hi
            self.canvas.update()
        if item is not None:
            self.update_cursor(Qt.SizeAllCursor if hi in self.sel_paths else Qt.PointingHandCursor)
        else:
            bb = self._sel_bbox()
            inside = bb is not None and bb.x0 - self._tol(4) <= pt.x <= bb.x1 + self._tol(4) \
                and bb.y0 - self._tol(4) <= pt.y <= bb.y1 + self._tol(4)
            self.update_cursor(Qt.SizeAllCursor if inside else None)

    def _shape_release(self, pt, mods):
        d = self.drag
        if not d:
            return
        k = d["kind"]
        pno = self.current_page
        if k == "band":
            if d["moved"]:
                found = [it.index for it in self.engine.paths_in_rect(pno, fitz.Rect(d["start"], d["cur"]))]
                if d["add"]:
                    self.sel_paths = sorted(set(self.sel_paths) | set(found))
                else:
                    self.sel_paths = found
                self._on_path_selection()
                self.status(_t("{n} çizim seçildi.", n=len(found)))
            return
        if not d["moved"]:
            return
        if k == "move":
            dx, dy = d["cur"].x - d["start"].x, d["cur"].y - d["start"].y
            if abs(dx) > 0.01 or abs(dy) > 0.01:
                self.engine.move_paths(pno, self.sel_paths, dx, dy)
                self.after_edit()
                self._on_path_selection()
                self.status(_t("Taşındı."))
        elif k == "handle":
            msg = _t("Boyutlandırıldı.")
            if d["handle"] in ("p1", "p2"):
                a, b = self._handle_line_ends(d)
                self.engine.set_line_points(pno, d["index"], a, b, d.get("bend"))
            elif d["handle"] == "bend":
                self.engine.set_line_points(pno, d["index"], d["a0"], d["b0"], d.get("bend"))
                msg = _t("Çizgi büküldü. (Düzleştirmek: ortadaki tutamaca çift tık)") if d.get("bend") \
                    else _t("Çizgi düzleştirildi.")
            else:
                nb = self._handle_bbox(d["handle"], d["bbox"], d["cur"], d.get("keep"), d.get("center"))
                self.engine.scale_paths(pno, self.sel_paths, d["bbox"], nb)
            self.after_edit()
            self._on_path_selection()
            self.status(msg)
        elif k == "draw":
            a, b = d["start"], d["cur"]
            if abs(b - a) < 1:
                return
            w, col, dash = self.spin_width.value(), self.btn_line_color.rgb, self._shape_dash()
            if self.shape_tool == "line":
                idx = self.engine.add_line(pno, a, b, w, col, dash)
            elif self.shape_tool == "ellipse":
                idx = self.engine.add_ellipse(pno, self._drag_box(d), w, col, None, dash)
            else:
                idx = self.engine.add_rect(pno, self._drag_box(d), w, col, None, dash)
            self.after_edit()
            self.sel_paths = [idx]
            self._on_path_selection()          # koordinat kutulari yeni cizimi gostersin
            self.status(_t("Çizildi. (Seç aracına geçmek için Esc)"))

    def _on_path_selection(self):
        """Secim degisti: paneldeki koordinat ve stil alanlarini doldur."""
        items = self._sel_items()
        self.sel_paths = [it.index for it in items]
        if items:
            n = len(items)
            kinds = {"line": _t("çizgi"), "curve": _t("bükülmüş çizgi"), "rect": _t("dikdörtgen"), "shape": _t("şekil")}
            if n == 1:
                self.lbl_sel_info.setText(_t("1 {what} seçili", what=kinds[items[0].kind]))
            else:
                self.lbl_sel_info.setText(_t("{n} öğe seçili", n=n))
            if n == 1 and items[0].kind in ("line", "curve"):
                a, b = items[0].line_points()
                labels, vals = ("X1", "Y1", "X2", "Y2"), (a.x, a.y, b.x, b.y)
            else:
                r = self._sel_bbox()
                labels, vals = (_t("Sol"), _t("Üst"), _t("Sağ"), "Alt"), (r.x0, r.y0, r.x1, r.y1)
            for lab, sp, t, v in zip(self.coord_labels, self.coord_spins, labels, vals):
                lab.setText(t)
                sp.setValue(v)
            st = self.engine.path_style(self.current_page, items[0].index)
            self._shape_loading = True    # secili ogeyi gostermek "son kullanilan"i degistirmez
            try:
                if st.get("width"):
                    self.spin_width.setValue(st["width"])
                col = st.get("color") or st.get("fill")
                if col:
                    self.btn_line_color.set_rgb(col)
                self.chk_dashed.setChecked(bool(st.get("dashed")))
                if st.get("dash"):
                    self.cmb_dash.setCurrentIndex(max(self.cmb_dash.findData(st["dash"]), 0))
                self._shape_dash_visibility()
            finally:
                self._shape_loading = False
        self._refresh_panel()
        self.canvas.update()

    def _deselect_paths(self):
        self.sel_paths = []
        self._on_path_selection()

    def _select_all_paths(self):
        self.sel_paths = [it.index for it in self.engine.get_paths(self.current_page)
                          if abs(it.bbox.width * it.bbox.height)
                          < 0.8 * abs(self.engine.doc[self.current_page].rect.width
                                      * self.engine.doc[self.current_page].rect.height)]
        self._on_path_selection()
        self.status(_t("{n} çizim seçildi.", n=len(self.sel_paths)))

    def apply_coords(self):
        items = self._sel_items()
        if not items:
            return
        v = [sp.value() for sp in self.coord_spins]
        pno = self.current_page
        if len(items) == 1 and items[0].kind in ("line", "curve"):
            a0, b0 = items[0].line_points()
            a1, b1 = fitz.Point(v[0], v[1]), fitz.Point(v[2], v[3])
            bend = curve_math.carry(a0, b0, items[0].bend_point(), a1, b1)   # egri bicimi korunur
            self.engine.set_line_points(pno, items[0].index, a1, b1, bend)
        else:
            old = self._sel_bbox()
            new = fitz.Rect(v[0], v[1], v[2], v[3])
            if old.width > 0.5 and new.width < 1 or old.height > 0.5 and new.height < 1:
                QMessageBox.warning(self, _t("Uyarı"), _t("Kutu çok küçük ya da ters olamaz (Sağ > Sol, Alt > Üst)."))
                return
            if old.width <= 0.5:
                new.x1 = new.x0 + old.width
            if old.height <= 0.5:
                new.y1 = new.y0 + old.height
            self.engine.scale_paths(pno, self.sel_paths, old, new)
        self.after_edit()
        self._on_path_selection()
        self.status(_t("Konum güncellendi."))

    def apply_path_style(self):
        if not self.sel_paths:
            return
        notes = self.engine.restyle_paths(self.current_page, self.sel_paths,
                                          width=self.spin_width.value(),
                                          color=self.btn_line_color.rgb,
                                          dashed=self._shape_dash())
        self.after_edit()
        self._on_path_selection()
        self.status(_t("Stil uygulandı") + (" (" + "; ".join(notes) + ")." if notes else "."))

    # ======================================================== ust katman cizimi
    # ------------------------------------------- surukleme: nesnenin kendisi gider
    def _ghost_diff(self, rect_px, remove, bg_only=False, isolate=False):
        """Sayfanin icindeki nesne (metin, cizim): kopyada nesnesi cikarilmis sayfa bir
        kez cizilir; arka plan o olur, nesnenin pikselleri (fark) fareyle gider.
        Basarisizsa hicbir sey degismez (eski cerceve onizlemesi kalir).
        isolate (yazi): nesne farktan degil KENDI cizimiyle alinir - baska bir yazinin
        ustundeyken de harfleri eksiksiz gider (fark, ayni renkteki pikselleri kaybeder)."""
        cv = self.canvas
        if not cv.has_page() or not getattr(self, "_render_scale", None):
            return
        d = cv.dpr
        page_img = cv._pix.toImage()
        r = QRect(int(rect_px.x() * d), int((rect_px.y() - cv.pad_top) * d),
                  int(rect_px.width() * d) + 2, int(rect_px.height() * d) + 2).intersected(page_img.rect())
        if r.isEmpty():
            return
        res = drag_ghost.render_without(self.engine.doc, self.current_page, self._render_scale, remove, r,
                                        isolate=isolate)
        if res is None:
            return
        part, r, obj = res
        if obj is not None and drag_ghost.composes(page_img.copy(r), part, obj):
            self._ghost_painter = None
            self._ghost_set(QPixmap.fromImage(obj), part, r, page_img=page_img)
            return
        if bg_only:                            # nesne baska yolla cizilir (_ghost_painter)
            self._ghost_set(None, part, r, page_img=page_img)
            return
        pm = drag_ghost.diff_ghost(page_img.copy(r), part)
        if pm is not None:
            self._ghost_painter = None
            self._ghost_set(pm, part, r, page_img=page_img)

    def _ghost_set(self, pm, part, r, clip=None, page_img=None):
        """Arka plan = sayfa, nesnenin bolgesi (r, goruntu pikseli) nesnesiz (part);
        pm = nesnenin kendi goruntusu, fareyle kayar."""
        cv = self.canvas
        d = cv.dpr
        if page_img is None:
            page_img = cv._pix.toImage()
        qp = QPainter(page_img)
        qp.drawImage(r.topLeft(), part)
        qp.end()
        bg = QPixmap.fromImage(page_img)
        bg.setDevicePixelRatio(d)
        if pm is not None:
            pm.setDevicePixelRatio(d)
        cv.bg = bg
        cv.ghost = (pm, cv.to_pdf(QPointF(r.x() / d, r.y() / d + cv.pad_top)), clip)

    def _ghost_text(self, span):
        lines = getattr(span, "lines", None) or [span]          # paragraf: tum satirlari

        def remove(doc, page):
            return pdf_content.remove_texts_at(doc, page, [ln.origin for ln in lines])
        rect = self.canvas.poly_px(span.quad()).boundingRect().adjusted(-4, -4, 4, 4)
        blend = self.engine._blend_of(self.engine.doc[self.current_page], span)
        if any(ln.opacity < 0.98 for ln in lines) or (blend and blend != "Normal"):
            # yari saydam / karisimli yazi (filigran): pikselleri alttaki yazi ve resimle
            # karisik -> sayfadan kopyalanirsa onlarin parcalari da tasinir. Yazinin
            # kendisi cizilir (fontu, boyutu, rengi, opakligi, acisi, karisimi).
            # (Yazi tek basina ayrilabilir ve saglamasi tutarsa o kullanilir; bu yedek.)
            self._ghost_painter = lambda p, cv, dd: self._paint_text_ghost(p, cv, lines, dd, blend)
            self._ghost_diff(rect, remove, bg_only=True, isolate=True)
        else:
            self._ghost_diff(rect, remove, isolate=True)

    def _paint_text_ghost(self, p, cv, lines, dd, blend):
        disp = math.degrees(math.atan2(cv.disp.b, cv.disp.a))
        for ln in lines:
            p.save()
            p.translate(cv.to_px(fitz.Point(ln.origin) + dd))
            p.rotate(self.engine.span_angle(ln) + disp)
            f = QFont(self._preview_family(ln.font))
            f.setPixelSize(max(1, round(ln.size * cv.zoom)))
            f.setBold(ln.is_bold)
            p.setFont(f)
            col = QColor.fromRgbF(*ln.color_rgb())
            col.setAlphaF(max(0.05, min(1.0, ln.opacity)))
            if blend == "Multiply":
                p.setCompositionMode(QPainter.CompositionMode_Multiply)
            p.setPen(col)
            p.drawText(QPointF(0, 0), ln.text.replace("\xa0", " "))
            p.restore()

    def _ghost_paths(self):
        items, bb = self._sel_items(), self._sel_bbox()
        if not items or bb is None:
            return
        styles = {it.index: self.engine.path_style(self.current_page, it.index) for it in items}
        if self.drag is not None:
            self.drag["styles"] = styles           # tutamacla duzenlerken gercek gorunumle cizmek icin
        pad = 8 + max(st.get("width") or 1 for st in styles.values()) * self.canvas.zoom

        def remove(doc, page):
            pdf_paths.delete_items(doc, page, items)
        self._ghost_diff(self.canvas.rect_px(bb).adjusted(-pad, -pad, pad, pad), remove)

    def _warm_text_scan(self):
        """Yazi secilince bosta: sayfa akisinin taramasi onbellege alinir; boylece
        surukleme hemen baslar ve birakinca yapilan asil tasima da hizli olur."""
        if self.engine.doc and self.mode == "text" and not self.drag:
            pdf_content.warm_scan(self.engine.doc, self.current_page)

    def _ghost_end(self):
        # Canli duzenleme surerken nesnesiz arka plan KALMALI (orijinal yazi sayfadan kalkmis
        # gorunur). Cift tikla duzenlemeye girilince ardindan gelen fare "birakildi" olayi
        # (canvas_release) burayi cagirip arka plani siliyordu: yazi silinince arkada
        # orijinali gorunuyordu. Duzenleme bitince (_tx_live False) normal calisir.
        if self.editing_live():
            return
        cv = self.canvas
        if cv.bg is not None or cv.ghost is not None:
            cv.bg = cv.ghost = None
            cv.update()

    def _ghost_delta(self):
        d = self.drag
        if not d or not d.get("moved"):
            return None
        if d["kind"] in ("text", "move", "mkmove", "tgroup"):
            return d["cur"] - d["start"]
        return None

    def _paint_ghost(self, p, cv):
        if cv.ghost is None:
            return
        dd = self._ghost_delta()
        if dd is None:
            return
        pm, anchor, clip = cv.ghost
        if pm is None:                  # nesnenin kendisi cizilir (filigran gibi yari saydam yazi)
            painter = getattr(self, "_ghost_painter", None)
            if painter is not None:
                painter(p, cv, dd)
            return
        p.save()
        if clip is not None:            # sadece bu cokgen kayar (not kutusu; ok sabit hedefe ayrica cizilir)
            path = QPainterPath()
            path.addPolygon(cv.poly_px([q + dd for q in clip]))
            p.setClipPath(path)
        # tam ekran pikseline oturt: kesirli konumda Qt goruntuyu yeniden ornekler ->
        # saydam zeminli yazi goruntusu yumusar, siyah yazi koyu gri gorunur
        pt, k = cv.to_px(anchor + dd), cv.dpr
        p.drawPixmap(QPointF(round(pt.x() * k) / k, round(pt.y() * k) / k), pm)
        p.restore()

    def paint_overlay(self, p, cv):
        self._paint_find(p, cv)
        self._paint_ghost(p, cv)
        if self.editing_live():
            self._paint_tx_live(p, cv)
        if self.mode == "text":
            self._paint_text_overlay(p, cv)
            # Duzenle: fare bir cizimin ustundeyse o da vurgulanir (tiklaninca secilecek)
            if self.hover_path is not None and self.hover_path not in self.sel_paths and not self.drag:
                p.setPen(self._pen(ACCENT, 4, alpha=90))
                p.setBrush(Qt.NoBrush)
                self._paint_polys(p, cv, self.engine.paths_by_index(self.current_page, [self.hover_path]))
            self._paint_image_hover(p, cv)
        elif self.mode == "shape":
            self._paint_shape_overlay(p, cv)
            self._paint_image_hover(p, cv)
            hs = self.hover_span
            if hs is not None and not self.drag and self.shape_tool == "select":
                p.setPen(self._pen(ACCENT, 1, Qt.DashLine, 170))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(cv.poly_px(hs.quad()))
        elif self.mode == "markup":
            self._paint_markup_overlay(p, cv)
        else:
            self._paint_insert_overlay(p, cv)

    def _paint_image_hover(self, p, cv):
        """Duzenle: fare bir resmin ustundeyse kesikli cerceve (tiklaninca secilecek)."""
        hi = self.hover_image
        if hi is None or hi in self.sel_images or self.drag or not self._select_tool_active():
            return
        for it in self.engine.images_by_index(self.current_page, [hi]):
            p.setPen(self._pen(ACCENT, 1, Qt.DashLine, 170))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(cv.poly_px(it.quad))

    def _pen(self, color, width=1.5, style=Qt.SolidLine, alpha=255):
        c = QColor(color)
        c.setAlpha(alpha)
        pen = QPen(c)
        pen.setWidthF(width)
        pen.setStyle(style)
        pen.setCosmetic(True)
        return pen

    def _paint_text_overlay(self, p, cv):
        hs = self.hover_span
        if hs is not None and hs is not self.current_span and not self.drag:
            p.setPen(self._pen(ACCENT, 1, Qt.DashLine, 170))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(cv.poly_px(hs.quad()))
        d = self.drag
        if d and d["kind"] == "tband" and d["moved"]:      # alan cizerek secme
            # duz cerceve: "tamami icinde" (soldan saga); kesikli: "degen" (sagdan sola)
            p.setPen(self._pen(ACCENT, 1, Qt.SolidLine if d["cur"].x >= d["start"].x else Qt.DashLine))
            c = QColor(ACCENT)
            c.setAlpha(30)
            p.setBrush(QBrush(c))
            p.drawRect(cv.rect_px(fitz.Rect(d["start"], d["cur"])))
        if self._group_active():                           # toplu secim: her nesnenin cercevesi + dis kutu
            off = QPointF(0, 0)
            if d and d.get("moved") and d["kind"] == "tgroup":
                off = cv.to_px(d["cur"]) - cv.to_px(d["start"])
                dd = d["cur"] - d["start"]
                self.lbl_coords.setText(f"\u0394x {dd.x:+.1f}  \u0394y {dd.y:+.1f} pt")
            p.setBrush(Qt.NoBrush)
            p.setPen(self._pen(TEXT_SEL, 1.5))
            outer = None
            for s in self.sel_spans:
                poly = cv.poly_px(s.quad()).translated(off)
                p.drawPolygon(poly)
                r = poly.boundingRect()
                outer = r if outer is None else outer.united(r)
            solo = self._solo_image()
            resizing = bool(d and d.get("moved") and d["kind"] == "ihandle" and d.get("nb") is not None)
            for it in self._sel_image_items():             # resimler
                if resizing:                               # yeni boyutuyla (sayfadaki goruntusu gerilerek)
                    old_r, new_r = cv.rect_px(d["bbox"]), cv.rect_px(d["nb"])
                    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
                    gh = cv.ghost
                    if gh is not None and gh[0] is not None:
                        # resmin KENDI pikselleri (altindaki yazi / cizgi olmadan), yeni kutuya gerilir
                        p.save()
                        p.translate(new_r.topLeft())
                        p.scale(new_r.width() / max(old_r.width(), 1e-6), new_r.height() / max(old_r.height(), 1e-6))
                        p.translate(-old_r.topLeft())
                        p.drawPixmap(cv.to_px(gh[1]), gh[0])
                        p.restore()
                    else:
                        p.drawPixmap(new_r.toRect(), cv.crop(old_r))
                    p.setPen(self._pen(TEXT_SEL, 1.5))
                    p.drawRect(new_r)
                    r = new_r
                    self.lbl_coords.setText(f"{d['nb'].width:.1f} \u00d7 {d['nb'].height:.1f} pt")
                else:
                    poly = cv.poly_px(it.quad).translated(off)
                    p.setPen(self._pen(TEXT_SEL, 1.5))
                    p.drawPolygon(poly)
                    r = poly.boundingRect()
                outer = r if outer is None else outer.united(r)
            if solo is not None and not (d and d.get("moved")):    # tek resim: boyut tutamaclari
                p.setPen(self._pen(TEXT_SEL, 1.5))
                for _name, hp in self._image_handles():
                    self._paint_handle(p, cv.to_px(hp), False, HANDLE_PX)
                return
            if resizing:
                return
            if self.sel_paths:                             # karisik secim: cizimler de vurgulu
                items = self._sel_items()
                dragging = d and d.get("moved") and d["kind"] == "tgroup"
                m = fitz.Matrix(1, 0, 0, 1, d["cur"].x - d["start"].x, d["cur"].y - d["start"].y) if dragging else None
                if not (dragging and cv.ghost is not None):   # (tasirken cizimin kendisi gidiyor)
                    p.setPen(self._pen(TEXT_SEL, 2, alpha=200))
                    self._paint_polys(p, cv, items, m)
                pb = self._sel_bbox()
                if pb is not None:
                    r = cv.rect_px(pb).translated(off)
                    outer = r if outer is None else outer.united(r)
            if outer is not None:
                p.setPen(self._pen(ACCENT, 1, Qt.DashLine, 200))
                p.drawRect(outer.adjusted(-4, -4, 4, 4))
            return
        sp = self.current_span
        if sp is None:
            return
        if self.txt_new.isVisible():           # yazarken: sadece kutu (cerceve / tutamac kutudan tasmasin)
            return
        poly = cv.poly_px(sp.quad())
        d = self.drag
        if d and d["moved"] and d["kind"] == "textrot":
            # canli: YAZININ KENDISI (font/boyut/renk) yeni aciyla cizilir. Eskiden
            # sayfa goruntusunden kesit alinip dondurluyordu; egik yazinin kutusu buyuk
            # oldugu icin komsu yazilar/tablo cizgileri de birlikte donuyordu.
            target = self._text_drag_angle(d)
            delta = ((target - d["a0"] + 180.0) % 360.0) - 180.0
            c = self.engine.span_center(sp)
            a = math.radians(delta)
            ox, oy = sp.origin[0] - c.x, sp.origin[1] - c.y
            o = fitz.Point(c.x + ox * math.cos(a) - oy * math.sin(a), c.y + ox * math.sin(a) + oy * math.cos(a))
            p.save()
            p.translate(cv.to_px(o))
            p.rotate(target + math.degrees(math.atan2(cv.disp.b, cv.disp.a)))
            f = QFont(self._preview_family(sp.font))
            f.setPixelSize(max(1, round(sp.size * cv.zoom)))
            f.setBold(sp.is_bold)
            p.setFont(f)
            col = QColor.fromRgbF(*sp.color_rgb())
            col.setAlphaF(max(0.35, sp.opacity))
            p.setPen(col)
            p.drawText(QPointF(0, 0), sp.text.replace("\xa0", " "))
            # yazinin (donmemis) kutusu, yeni aciyla
            fm = p.fontMetrics()
            p.setPen(self._pen(TEXT_SEL, 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(0, -fm.ascent(), fm.horizontalAdvance(sp.text.replace("\xa0", " ")),
                              fm.ascent() + fm.descent()))
            p.restore()
            p.setPen(self._pen(TEXT_SEL, 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(poly)
            self.lbl_coords.setText(_t("açı {a}°  (Shift: 15° adım)", a=f"{target:.0f}"))
            return
        if d and d["moved"]:
            off = cv.to_px(d["cur"]) - cv.to_px(d["start"])
            if d["kind"] == "text":
                self._paint_guides(p, cv, d.get("guides"))
            if cv.ghost is not None:              # yazinin kendisi kayiyor; secim cercevesi onunla
                p.setPen(self._pen(TEXT_SEL, 2))
                p.setBrush(Qt.NoBrush)
                p.drawPolygon(poly.translated(off))
                dd = d["cur"] - d["start"]
                self.lbl_coords.setText(f"\u0394x {dd.x:+.1f}  \u0394y {dd.y:+.1f} pt")
                return
            src = poly.boundingRect()
            if not sp.rotated:
                p.setOpacity(0.8)
                p.drawPixmap(src.topLeft() + off, cv.crop(src))
                p.setOpacity(1.0)
            p.setPen(self._pen(TEXT_SEL, 1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawPolygon(poly)
            p.setPen(self._pen(TEXT_SEL, 2))
            p.drawPolygon(poly.translated(off))
            dd = d["cur"] - d["start"]
            self.lbl_coords.setText(f"Δx {dd.x:+.1f}  Δy {dd.y:+.1f} pt")
            return
        p.setPen(self._pen(TEXT_SEL, 2))
        p.setBrush(Qt.NoBrush)
        p.drawPolygon(poly)
        # dondurme tutamaci + sap
        q = sp.quad()
        top = cv.to_px((q[0] + q[1]) * 0.5)
        hp = cv.to_px(self._text_rot_handle(sp))
        p.setPen(self._pen(TEXT_SEL, 1))
        p.drawLine(top, hp)
        p.setPen(self._pen(TEXT_SEL, 1.2))
        p.setBrush(QBrush(TEXT_SEL))
        p.drawEllipse(hp, HANDLE_PX + 0.5, HANDLE_PX + 0.5)

    @staticmethod
    def _paint_handle(p, q, round_, size, filled=False):
        """Tutamac: kare (uc/kose) ya da yuvarlak (bukme). Bukulmus cizginin
        bukme tutamaci dolu: cizginin egri oldugu bir bakista anlasilsin."""
        if round_:
            p.setBrush(QBrush(QColor(ACCENT) if filled else QColor(255, 255, 255)))
            p.drawEllipse(q, size + 0.5, size + 0.5)
        else:
            p.setBrush(QBrush(QColor(255, 255, 255)))
            p.drawRect(QRectF(q.x() - size, q.y() - size, 2 * size, 2 * size))

    def _paint_polys(self, p, cv, items, matrix=None):
        for it in items:
            for poly, closed in it.polys:
                p.drawPolyline(cv.poly_px(poly, matrix))

    def _paint_styled(self, p, cv, items, matrix=None, line=None):
        """Cizimleri gercek gorunumleriyle (kontur rengi/kalinligi, kesikli, dolgu) ciz:
        tutamacla duzenlerken orijinal sayfadan kalkmisken yeni hali."""
        styles = (self.drag or {}).get("styles") or {}
        for it in items:
            st = styles.get(it.index) or {}
            stroke, fill = st.get("color"), st.get("fill")
            if stroke is not None and it.stroked:
                w = st.get("width") or 1.0
                pen = QPen(QColor.fromRgbF(*stroke))
                pen.setWidthF(max(0.5, w * cv.zoom))
                pen.setCapStyle(Qt.FlatCap)
                pen.setJoinStyle(Qt.MiterJoin)
                if st.get("dashed"):
                    ww = max(w, 0.1)
                    pen.setDashPattern([max(0.05, v / ww)
                                        for v in curve_math.dash_array(st.get("dash") or "dash_m", ww)])
                p.setPen(pen)
            else:
                p.setPen(Qt.NoPen)
            if line is not None:
                p.setBrush(Qt.NoBrush)
                p.drawPolyline(cv.poly_px(line))
                continue
            p.setBrush(QBrush(QColor.fromRgbF(*fill)) if fill is not None else Qt.NoBrush)
            for poly, closed in it.polys:
                qp = cv.poly_px(poly, matrix)
                if closed or fill is not None:
                    p.drawPolygon(qp)
                else:
                    p.drawPolyline(qp)

    def _paint_shape_overlay(self, p, cv):
        items = self._sel_items()
        d = self.drag
        # fareyle ustune gelinen
        if self.hover_path is not None and self.hover_path not in self.sel_paths and not (d and d["moved"]):
            p.setPen(self._pen(ACCENT, 4, alpha=90))
            self._paint_polys(p, cv, self.engine.paths_by_index(self.current_page, [self.hover_path]))
        ghosting = cv.ghost is not None and d and d["moved"] and d["kind"] in ("move", "handle")
        # secili olanlar (tasirken cizimin kendisi kayiyor: vurgu yok)
        if items and not ghosting:
            p.setPen(self._pen(ACCENT, 2.5, alpha=110))
            self._paint_polys(p, cv, items)
        preview = None
        if d and d["moved"]:
            if d["kind"] == "move":
                dd = d["cur"] - d["start"]
                preview = fitz.Matrix(1, 0, 0, 1, dd.x, dd.y)
                self.lbl_coords.setText(f"Δx {dd.x:+.1f}  Δy {dd.y:+.1f} pt")
            elif d["kind"] == "handle" and d["handle"] not in ("p1", "p2", "bend"):
                nb = self._handle_bbox(d["handle"], d["bbox"], d["cur"], d.get("keep"), d.get("center"))
                preview =self._scale_matrix(d["bbox"], nb)
                self.lbl_coords.setText(f"{nb.width:.1f} × {nb.height:.1f} pt")
            elif d["kind"] == "handle":
                a, b = self._handle_line_ends(d)
                pts = curve_math.bent_points(a, d.get("bend"), b)
                if ghosting:                       # cizginin kendisi (renk, kalinlik, kesikli)
                    self._paint_styled(p, cv, items[:1], line=pts)
                else:
                    p.setPen(self._pen(ACCENT, 2))
                    p.setBrush(Qt.NoBrush)
                    p.drawPolyline(cv.poly_px(pts))
                if d["handle"] == "bend":
                    if d.get("bend") is not None:
                        # ortadan sapma: egrinin ne kadar buküldüğü
                        off = curve_math.point_seg_dist(d["bend"], a, b)
                        self.lbl_coords.setText(_t("bükme {v} pt (Shift: simetrik)", v=f"{off:.1f}"))
                    else:
                        self.lbl_coords.setText(_t("düz çizgi"))
                else:
                    self.lbl_coords.setText(_t("uzunluk {L} pt · açı {a}° (Alt: açı sabit)",
                                               L=f"{abs(b - a):.1f}", a=f"{curve_math.angle_deg(a, b):.1f}"))
        if preview is not None and not ghosting:
            p.setPen(self._pen(ACCENT, 2))
            self._paint_polys(p, cv, items, preview)
        elif preview is not None and d["kind"] == "handle":
            self._paint_styled(p, cv, items, preview)    # boyutlanan cizimin kendisi
        # secim kutusu + tutamaclar
        if items and not (d and d["moved"] and d["kind"] in ("move", "handle")):
            bb = self._sel_bbox()
            if not (len(items) == 1 and items[0].kind in ("line", "curve")):
                p.setPen(self._pen(ACCENT, 1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRect(cv.rect_px(bb).adjusted(-3, -3, 3, 3))
            p.setPen(self._pen(ACCENT, 1.2))
            for name, hp in self._handles():
                q = cv.to_px(hp)
                self._paint_handle(p, q, name == "bend", HANDLE_PX,
                                   filled=name == "bend" and items[0].kind == "curve")
        # kutu ile secim
        if d and d["kind"] == "band" and d["moved"]:
            p.setPen(self._pen(ACCENT, 1, Qt.DashLine))
            c = QColor(ACCENT)
            c.setAlpha(30)
            p.setBrush(QBrush(c))
            p.drawRect(cv.rect_px(fitz.Rect(d["start"], d["cur"])))
        # cizim onizlemesi
        if d and d["kind"] == "draw" and d["moved"]:
            col = QColor.fromRgbF(*self.btn_line_color.rgb)
            pen = QPen(col)
            pen.setWidthF(max(1.0, self.spin_width.value() * cv.zoom))
            if self.chk_dashed.isChecked():
                wd = max(self.spin_width.value(), 0.1)
                pen.setDashPattern([max(0.3, v / wd) for v in curve_math.dash_array(self._shape_dash(), wd)])
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            if self.shape_tool == "line":
                p.drawLine(cv.to_px(d["start"]), cv.to_px(d["cur"]))
                self.lbl_coords.setText(_t("uzunluk {L} pt · açı {a}°", L=f"{abs(d['cur'] - d['start']):.1f}",
                                           a=f"{curve_math.angle_deg(d['start'], d['cur']):.1f}"))
            else:
                r = self._drag_box(d)
                (p.drawEllipse if self.shape_tool == "ellipse" else p.drawRect)(cv.rect_px(r))
                if d.get("center"):               # merkez isareti
                    q = cv.to_px(d["start"])
                    p.drawLine(QPointF(q.x() - 4, q.y()), QPointF(q.x() + 4, q.y()))
                    p.drawLine(QPointF(q.x(), q.y() - 4), QPointF(q.x(), q.y() + 4))
                self.lbl_coords.setText(f"{r.width:.1f} × {r.height:.1f} pt"
                                        + ("  (merkezden)" if d.get("center") else ""))
        # yapisma gostergesi
        if self._snap_pt is not None and d and d["moved"]:
            q = cv.to_px(self._snap_pt)
            p.setPen(self._pen(QColor(230, 120, 0), 1.5))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(q, 5, 5)

    def _paint_insert_overlay(self, p, cv):
        if self.pending_insert is None:
            return
        if self.drag and self.drag.get("kind") == "marker":
            self._paint_guides(p, cv, self.drag.get("guides"))
        _, x, y = self.pending_insert
        size = self.spin_size.value()
        q = cv.to_px((x, y))
        p.save()
        p.translate(q)
        p.rotate(self.engine.doc[self.current_page].rotation)
        # isaretci (taban cizgisi + imlec)
        h = size * cv.zoom
        p.setPen(self._pen(INSERT_COL, 2))
        p.drawLine(QPointF(0, 2), QPointF(0, -h))
        p.drawLine(QPointF(-4, 2), QPointF(4, 2))
        # onizleme
        text = self.txt_new.toPlainText()
        if text.strip() and not self.txt_new.isVisible():   # yazarken kutunun kendisi gorunur
            fam = self.combo_font.currentText() if self.combo_font.currentData() else "Arial"
            f = QFont(fam)
            f.setPixelSize(max(1, round(size * cv.zoom)))
            f.setBold(self.chk_bold.isChecked())
            p.setFont(f)
            col = QColor.fromRgbF(*(self.selected_color or (0, 0, 0)))
            p.setOpacity(self.spin_opacity.value() / 100)
            p.setPen(col)
            lh = size * self.spin_spacing.value() * cv.zoom
            fm = p.fontMetrics()
            for k, line in enumerate(text.split("\n")):
                lw = fm.horizontalAdvance(line)
                off = {"center": -lw / 2, "right": -lw}.get(self.text_align, 0)
                p.drawText(QPointF(off, k * lh), line)
        p.restore()

    # ======================================================== klavye
    def canvas_key(self, ev):
        if not self.engine.doc:
            return False
        key, mods = ev.key(), ev.modifiers()
        steps = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if key == Qt.Key_Escape:
            if self.drag:
                if self.drag.get("slider"):
                    self._text_angle_cancel()
                self.drag = None
                self._ghost_end()
                self._set_render_hide(())
            elif self.mode == "shape" and self.shape_tool != "select":
                self.set_shape_tool("select")
                return True
            elif self.mode == "insert" and self.pending_insert is None:
                self.set_mode("text")          # Yeni metin araci bosken Esc: Sec aracina don
                return True
            elif self.mode == "markup" and self.sel_markup is not None:
                self._mk_select(None)          # once secimi birak, arac acik kalsin
                return True
            elif self.mode == "markup" and self.mk_tool != "select":
                self.set_markup_tool("select")
                return True
            elif (self.find_active() and self.current_span is None and not self.sel_spans
                  and not self.sel_paths and not self.sel_images):
                self.find_close()              # birakilacak secim yok: arama cubugunu kapat
                return True
            else:
                self._clear_selection()
                self._refresh_panel()
            self.canvas.update()
            return True
        if key in (Qt.Key_Delete, Qt.Key_Backspace):
            self.delete_selected()
            return True
        if self.mode == "markup" and self._mk_key(ev):     # tek tus arac kisayollari vb.
            return True
        if key == Qt.Key_A and mods & Qt.ControlModifier and self.mode in ("text", "shape"):
            self.set_shape_tool("select")
            self.select_all()                  # Duzenle: yazilar + sekiller
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2) and self.mode == "text" and self.current_span:
            self._text_edit_begin()
            return True
        plain = not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
        if self.mode in ("text", "insert") and mods & Qt.ControlModifier and not mods & Qt.AltModifier:
            if key == Qt.Key_C and self.current_span is not None:
                self.copy_text()
                return True
            if key == Qt.Key_D and self.current_span is not None:
                self.duplicate_text()
                return True
            if key == Qt.Key_V:
                self.paste_text()
                return True
        if self.mode in ("text", "insert", "shape") and plain \
                and key in (Qt.Key_V, Qt.Key_T, Qt.Key_L, Qt.Key_K, Qt.Key_D):
            # Duzenle'nin arac kisayollari: V sec, T yeni metin, L cizgi, K kutu, D daire
            if key == Qt.Key_V:
                if self.mode == "shape":
                    self.set_shape_tool("select")
                else:
                    self.set_mode("text")
            elif key == Qt.Key_T:
                self.set_mode("insert")
            else:
                self.set_shape_tool({Qt.Key_L: "line", Qt.Key_K: "rect", Qt.Key_D: "ellipse"}[key])
            return True
        if key in steps:
            step = self._nudge_step() * (5 if mods & Qt.ShiftModifier else 1)
            dx, dy = steps[key]
            v = self._display_delta(dx * step, dy * step)
            self.on_arrow_move(v.x, v.y)
            if self.current_span is not None or self.sel_spans or self.sel_paths or self.sel_images \
                    or self.pending_insert is not None or self.sel_markup is not None:
                self.status(_t("Kaydırma adımı: {s} pt (yakınlaştırma %{z})", s=f"{step:.3g}", z=int(self.canvas.zoom * 100)))
            return True
        return False

    def _nudge_step(self):
        """Ok tusu adimi (pt): ekranda ~1 piksel. %100 ve altinda 1 pt; yakinlastirdikca
        incelir (%400: 0.25 pt, %800: 0.125 pt) - hassas hizalama icin."""
        return min(1.0, 1.0 / self.canvas.zoom)

    def on_arrow_move(self, dx, dy):
        # art arda ok basislari tek geri-al adimi olsun (bkz. PDFEditor._push_undo)
        group = ("nudge", self.mode, self.current_page, self._nudge_token)
        if self.mode == "insert" and self.pending_insert is not None:
            pno, x, y = self.pending_insert
            self.pending_insert = (pno, x + dx, y + dy)
            self.canvas.update()
        elif self.mode == "text" and self._group_active():
            self._group_move(dx, dy, group=group)
        elif self.mode == "text" and self.current_span is not None:
            new = self.engine.move_span(self.current_span, dx, dy, group=group)
            self.after_edit()
            self._select_text_span(self._find_span_near(new) or new)
        elif self.mode == "shape" and self.sel_paths:
            self.engine.move_paths(self.current_page, self.sel_paths, dx, dy, group=group)
            self.after_edit()
            self._on_path_selection()
        elif self.mode == "markup" and self.sel_markup is not None:
            self._mk_nudge(dx, dy, group)

    # ======================================================== metin eylemleri
    def apply_change(self):
        if not self.engine.doc:
            return
        font_choice = self.combo_font.currentData()
        opacity = self.spin_opacity.value() / 100
        spacing = self._tx_spacing()

        if self.mode == "insert":
            if self.pending_insert is None:
                return
            new_text = self.txt_new.toPlainText()
            if not new_text.strip():
                QMessageBox.warning(self, _t("Uyarı"), _t("Eklenecek metni yazın."))
                return
            page_num, x, y = self.pending_insert
            exact = self.engine.insert_text_new(
                page_num, x, y, new_text,
                fontsize=self.spin_size.value(),
                color_rgb=self.selected_color or (0, 0, 0),
                font_hint=font_choice or "Arial",
                bold=self.chk_bold.isChecked(),
                opacity=opacity, line_spacing=spacing, align=self.text_align)
            self.pending_insert = None
            self.txt_new.hide()
            self.txt_new.clear()
            self.after_edit()
            self.status(_t("Metin eklendi."))
            if not exact:
                QMessageBox.information(self, _t("Bilgi"),
                                        _t("Seçilen font Windows'ta bulunamadı, en yakın font kullanıldı."))
            return

        if self.current_span is None:
            QMessageBox.warning(self, _t("Uyarı"), _t("Önce sayfada bir metne tıklayın."))
            return
        span = self.current_span
        new_text = self.txt_new.toPlainText()
        exact = self.engine.apply_edit(
            span, new_text,
            new_size=self.spin_size.value(),
            color_rgb=self.selected_color,
            force_bold=self.chk_bold.isChecked(),
            autofit=self.chk_autofit.isChecked(),
            font_override=font_choice,
            opacity=opacity, line_spacing=spacing, align=self.text_align)
        self.current_span = None
        self.after_edit()
        again = self._find_span_near(span) if new_text.strip() else None
        if again is not None:
            self._select_text_span(again)
        self.status(_t("Değişiklik uygulandı."))
        if not exact:
            QMessageBox.information(self, _t("Bilgi"),
                                    _t("Bu font Windows'ta tam bulunamadı, en yakın font kullanıldı."))

    def delete_selected(self):
        if not self.engine.doc:
            return
        if self.mode == "markup":
            self._mk_delete()
            return
        if self.mode == "shape":
            if not self.sel_paths:
                self.status(_t("Önce silmek istediğiniz çizgiyi seçin."))
                return
            n = len(self.sel_paths)
            self.engine.delete_paths(self.current_page, self.sel_paths)
            self.sel_paths = []
            self.after_edit()
            self.status(_t("{n} çizim silindi.", n=n))
            return
        if self.pending_insert is not None:
            self.pending_insert = None
            self.txt_new.hide()
            self.txt_new.clear()
            self._refresh_panel()
            self.canvas.update()
            return
        if self._group_active():               # toplu secim (yazi / cizim / resim)
            self._group_delete()
            return
        if self.current_span is None:
            return
        self.engine.apply_edit(self.current_span, "")
        self.current_span = None
        self.after_edit()
        self.status(_t("Metin silindi."))

    def undo_change(self):
        self._text_angle_commit()     # bekleyen aci onizlemesi
        if self.engine.doc and self.engine.undo():
            self._after_history(_t("Geri alındı."))
        else:
            self.status(_t("Geri alınacak değişiklik yok."))

    def redo_change(self):
        self._text_angle_commit()     # bekleyen aci onizlemesi
        if self.engine.doc and self.engine.redo():
            self._after_history(_t("Yinelendi."))
        else:
            self.status(_t("Yinelenecek değişiklik yok."))

    def _after_history(self, msg):
        keep_paths = list(self.sel_paths) if self.mode == "shape" else []
        keep_mk = self.sel_markup if self.mode == "markup" else None
        self._clear_selection()
        if self.current_page >= self.engine.page_count():
            self.current_page = self.engine.page_count() - 1
        self.after_edit(all_thumbs=True)
        if keep_paths:
            n = len(self.engine.get_paths(self.current_page))
            self.sel_paths = [i for i in keep_paths if i < n]
            self._on_path_selection()
        if keep_mk is not None and self.engine.markup(self.current_page, keep_mk) is not None:
            self._mk_loaded = None          # geri alinan ayarlari panele yeniden yukle
            self._mk_select(keep_mk)
        self.status(msg)

    # ======================================================== sayfa islemleri
    def _page_menu(self, pno):
        m = QMenu(_t("Sayfa {n}", n=pno + 1), self)
        m.addAction(ic("fa5s.undo"), _t("Sola döndür"), lambda: self._page_op("rotate", pno, -90))
        m.addAction(ic("fa5s.redo"), _t("Sağa döndür"), lambda: self._page_op("rotate", pno, 90))
        m.addSeparator()
        m.addAction(ic("fa5s.file"), _t("Önüne boş sayfa ekle"), lambda: self._page_op("blank", pno))
        m.addAction(ic("fa5s.file"), _t("Arkasına boş sayfa ekle"), lambda: self._page_op("blank", pno + 1))
        m.addAction(ic("fa5s.file-import"), _t("Arkasına başka PDF'ten sayfa ekle..."),
                    lambda: self._page_op("import", pno + 1))
        m.addAction(ic("fa5s.file-image"), _t("Arkasına resim ekle..."), lambda: self._page_op("image", pno + 1))
        m.addAction(ic("fa5s.copy"), _t("Çoğalt"), lambda: self._page_op("dup", pno))
        m.addSeparator()
        m.addAction(ic("fa5s.image"), _t("Resim olarak kaydet..."), lambda: self.export_pages_dialog(pno))
        m.addAction(ic("fa5s.clipboard"), _t("Panoya resim olarak kopyala"), lambda: self.copy_page_image(pno))
        m.addSeparator()
        up = m.addAction(ic("fa5s.arrow-up"), _t("Yukarı taşı"), lambda: self.move_page_to(pno, pno - 1))
        down = m.addAction(ic("fa5s.arrow-down"), _t("Aşağı taşı"), lambda: self.move_page_to(pno, pno + 1))
        up.setEnabled(pno > 0)
        down.setEnabled(pno < self.engine.page_count() - 1)
        m.addSeparator()
        dl = m.addAction(ic("fa5s.trash", "#dc2626"), _t("Sayfayı sil"), lambda: self._page_op("delete", pno))
        dl.setEnabled(self.engine.page_count() > 1)
        return m

    def _thumb_action(self, key, pno):
        """Kucuk resmin uzerine gelince cikan dugmeler."""
        if not self.engine.doc:
            return
        if key == "add":
            self._page_op("blank", pno + 1)
        elif key in ("rotl", "rotr"):
            self._page_op("rotate", pno, -90 if key == "rotl" else 90)
        elif key == "del":
            if self.engine.page_count() <= 1:
                self.status(_t("Tek sayfalık belgenin sayfası silinemez."))
                return
            self._page_op("delete", pno)

    def _thumb_context(self, index, global_pos):
        if not self.engine.doc:
            return
        pno = index if index >= 0 else self.current_page
        self._page_menu(pno).exec(global_pos)

    def _page_op(self, op, pno, arg=None):
        e = self.engine
        target = self.current_page
        if op == "rotate":
            e.rotate_page(pno, arg)
            msg = _t("Sayfa döndürüldü.")
        elif op == "blank":
            e.insert_blank_page(pno)
            target = pno
            msg = _t("Boş sayfa eklendi.")
        elif op == "import":
            path, _ = QFileDialog.getOpenFileName(self, _t("Eklenecek PDF"), os.path.dirname(self._last_open_path()),
                                                  _t("PDF Dosyaları (*.pdf)"))
            if not path:
                return
            try:
                n = e.insert_pdf_pages(path, pno)
            except Exception as ex:
                QMessageBox.critical(self, _t("Hata"), f"PDF eklenemedi:\n{ex}")
                return
            target = pno
            msg = _t("{n} sayfa eklendi.", n=n)
        elif op == "image":
            paths, _ = QFileDialog.getOpenFileNames(self, _t("Eklenecek resimler"),
                                                    os.path.dirname(self._last_open_path()),
                                                    image_tools.image_filter())
            if not paths:
                return
            ref = e.doc[min(max(pno - 1, 0), e.page_count() - 1)]       # komsu sayfanin boyutu
            r = ref.rect * ref.derotation_matrix
            src, skipped = image_tools.images_to_pdf(paths, (abs(r.width), abs(r.height)))
            if not len(src):
                QMessageBox.critical(self, _t("Hata"), _t("Resim eklenemedi:\n{e}",
                                                          e="\n".join(f"{a} ({b})" for a, b in skipped)))
                return
            n = e.insert_doc_pages(src, pno)
            target = pno
            msg = _t("{n} resim sayfa olarak eklendi.", n=n)
            if skipped:
                msg += " " + _t("Eklenemeyen: {names}", names=", ".join(a for a, _ in skipped))
        elif op == "dup":
            e.duplicate_page(pno)
            target = pno + 1
            msg = _t("Sayfa çoğaltıldı.")
        elif op == "delete":
            r = QMessageBox.question(self, _t("Sayfayı sil"), _t("{n}. sayfa silinsin mi? (Geri alınabilir)", n=pno + 1))
            if r != QMessageBox.Yes:
                return
            e.delete_page(pno)
            target = min(pno, e.page_count() - 1)
            msg = _t("Sayfa silindi.")
        else:
            return
        self.current_page = target
        self._clear_selection()
        self.after_edit(all_thumbs=True)
        if op == "rotate":
            self.fit_to_width()
        self.status(msg)

    def move_page_to(self, src, dst, view_done=False):
        """Sayfayi tasir. view_done: sol liste kullanicinin surukleyip birakmasiyla
        zaten yeniden siralandi (landing animasyonu bozulmasin diye liste bastan
        kurulmaz). Menuden tasimada liste kartlari kayarak yer degistirir."""
        if not self.engine.doc or not (0 <= dst < self.engine.page_count()) or src == dst:
            return
        self.engine.move_page(src, dst)
        if not view_done:
            self.thumbs.move(src, dst)
        self.current_page = dst
        self._clear_selection()
        self.thumbs.set_current(dst)
        self.render_current_page()
        self._update_title()
        self._refresh_panel()
        self.status(_t("Sayfa {a} → {b}. sıraya taşındı.", a=src + 1, b=dst + 1))

    # ======================================================== diger pencereler
    def _current_file_for_tools(self):
        """Acik belge diskteki haliyle aynıysa (kaydedilmemis degisiklik yoksa)
        Birlestir/Ayir pencereleri onunla hazir acilir."""
        e = self.engine
        if e.doc is not None and e.path and not e.dirty and os.path.isfile(e.path):
            return e.path
        return None

    def open_merge_dialog(self):
        MergeDialog(self, self._current_file_for_tools()).exec()

    def open_split_dialog(self):
        f = self._current_file_for_tools()
        SplitDialog(self, f if f and self.engine.page_count() > 1 else None).exec()

    def _need_doc(self):
        if not self.engine.doc:
            QMessageBox.information(self, _t("Bilgi"), _t("Önce bir PDF açın."))
            return False
        return True

    def open_watermark_dialog(self):
        if self._need_doc() and WatermarkDialog(self, self.engine, self.current_page).exec():
            self._clear_selection()
            self.after_edit(all_thumbs=True)
            self.status(_t("Filigran eklendi (Ctrl+Z ile geri alınabilir)."))

    def open_form_dialog(self):
        if not self._need_doc():
            return
        if not self.engine.get_form_fields():
            QMessageBox.information(
                self, _t("Form alanı yok"),
                _t("Bu PDF'te doldurulabilir (etkileşimli) form alanı yok.\n\n"
                "Düz bir forma yazı yazmak için \"Yeni metin\" aracıyla ilgili boşluğa "
                "tıklayıp yazabilirsiniz."))
            return
        if FormDialog(self, self.engine).exec():
            self.after_edit(all_thumbs=True)
            self.status(_t("Form alanları güncellendi."))

    def open_ocr_dialog(self):
        if not self._need_doc():
            return
        ensure_tesseract_env()
        if not self.engine.ocr_available():
            box = QMessageBox(self)
            box.setWindowTitle(_t("Tesseract gerekli"))
            box.setTextFormat(Qt.RichText)
            box.setTextInteractionFlags(Qt.TextBrowserInteraction)
            box.setText(TESSERACT_HELP)
            box.exec()
            return
        dlg = OcrDialog(self, self.engine, self.current_page)
        if dlg.exec():
            self._clear_selection()
            self.after_edit(all_thumbs=True)
            self.status(_t("OCR tamamlandı: {n} kelime tanındı.", n=dlg.result_words))


def _is_packaged():
    """Store (MSIX) paketinden mi calisiyoruz? Paketsiz surecte Windows
    APPMODEL_ERROR_NO_PACKAGE (15700) dondurur."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        n = ctypes.c_uint32(0)
        return ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(n), None) != 15700
    except Exception:
        return False


class _DarkTitleBars(QObject):
    """Windows'un pencere basligini koyu ciz (ana pencere + tum iletisim kutulari).

    Arayuz koyu, ama yerel baslik cubugu varsayilan olarak BEYAZ: ust serit "sonradan
    eklenmis" gibi duruyordu. DWM'ye koyu mod denir (Windows 10 1809+); Windows 11'de
    ayrica baslik rengi ust seridin rengine esitlenir -> tek parca gorunur. Pencere
    davranislari (yaslama, boyutlandirma) yerel kalir."""
    CAPTION = "#26282c"                       # DARK["surface"] = ust seridin rengi

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Show and obj.isWidgetType() and obj.isWindow()                 and not obj.property("_rvDarkTitle"):
            flags = obj.windowFlags()
            if not (flags & Qt.Popup == Qt.Popup or flags & Qt.ToolTip == Qt.ToolTip):
                obj.setProperty("_rvDarkTitle", True)
                self.apply(obj)
        return False

    @classmethod
    def apply(cls, w):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            dwm = ctypes.windll.dwmapi
            hwnd = ctypes.c_void_p(int(w.winId()))
            on = ctypes.c_int(1)
            # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE (Win10 20H1+), 19 = ayni sey, eski yapilar
            if dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4) != 0:
                dwm.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(on), 4)
            c = QColor(cls.CAPTION)
            ref = ctypes.c_int(c.red() | (c.green() << 8) | (c.blue() << 16))   # COLORREF 0x00BBGGRR
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ref), 4)   # DWMWA_CAPTION_COLOR (Win11)
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(ref), 4)   # DWMWA_BORDER_COLOR  (Win11)
        except Exception:
            pass


SINGLE_NAME = "RevoraPDF-tek-pencere"


def _single_name():
    """Kullaniciya ozel kanal adi (ayni bilgisayarda baska oturumla karismasin)."""
    import getpass
    try:
        user = "".join(ch for ch in getpass.getuser() if ch.isalnum())
    except Exception:
        user = ""
    # (REVORA_CHANNEL: testler kullanicinin acik Revora'sina dosya yollamasin diye ayri kanal)
    return f"{SINGLE_NAME}-{user}{os.environ.get('REVORA_CHANNEL', '')}"


def _hand_over(paths):
    """Revora zaten aciksa dosyalari ona yolla (yeni sekmede acar, one gelir) -> True.
    Acik degilse ya da 1,5 sn icinde yanit vermezse False: bu surec normal acilir."""
    from PySide6.QtNetwork import QLocalSocket
    sock = QLocalSocket()
    sock.connectToServer(_single_name())
    if not sock.waitForConnected(300):
        return False
    if sys.platform == "win32":
        try:                                   # calisan pencere one gelebilsin (Windows izni)
            import ctypes
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
    sock.write(json.dumps(paths).encode("utf-8") + b"\n")
    sock.flush()
    ok = sock.waitForReadyRead(1500) and bytes(sock.readAll()).startswith(b"ok")
    sock.disconnectFromServer()
    return ok


def _listen(app, win):
    """Sonradan calistirilan Revora'lardan gelen dosyalari bu pencerede ac."""
    from PySide6.QtNetwork import QLocalServer
    srv = QLocalServer(app)
    srv.setSocketOptions(QLocalServer.UserAccessOption)
    if not srv.listen(_single_name()):
        QLocalServer.removeServer(_single_name())      # onceki surecten kalmis ad
        if not srv.listen(_single_name()):
            return

    def on_connect():
        sock = srv.nextPendingConnection()
        if sock is None:
            return

        def on_data():
            if not sock.canReadLine():
                return
            try:
                paths = json.loads(bytes(sock.readLine()).decode("utf-8"))
            except Exception:
                paths = []
            sock.write(b"ok\n")
            sock.flush()
            sock.disconnectFromServer()
            QTimer.singleShot(0, lambda: win.open_from_other_instance(paths if isinstance(paths, list) else []))
        sock.readyRead.connect(on_data)
        sock.disconnected.connect(sock.deleteLater)
        on_data()
    srv.newConnection.connect(on_connect)
    app._single_server = srv


def main():
    # Kaynaktan (python main.py) calisirken Windows gorev cubugu uygulamayi
    # python.exe sayip Python ikonunu gosterir; kendi kimligimizi verince
    # Revora ikonu gorunur. Pencere olusturulmadan once yapilmali.
    # Store (MSIX) paketinde YAPILMAZ: kimligi paket verir; elle verilen kimlik
    # gorev cubuguna sabitlemeyi / ikon gruplamasini bozar.
    if sys.platform == "win32" and not _is_packaged():
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Revora.PDFDuzenleyici")
        except Exception:
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app._dark_titles = _DarkTitleBars(app)      # (referans tutulur)
    app.installEventFilter(app._dark_titles)
    logo = resource_path("assets", "revora.png")
    if os.path.exists(logo):
        app.setWindowIcon(QIcon(logo))   # pencere, gorev cubugu ve tum dialoglar
    app.setStyle("Fusion")
    # acilir listeler kayarak acilma animasyonu olmadan, aninda acilsin (genis listede
    # animasyon "goz kirpma" gibi gorunuyordu)
    app.setEffectEnabled(Qt.UI_AnimateCombo, False)
    app.setFont(QFont("Segoe UI", 10))
    # Qt'nin kendi metinleri (Evet/Hayir/Iptal, renk secici...) secili dilde
    from PySide6.QtCore import QTranslator, QLibraryInfo
    qt_tr = QTranslator(app)
    if qt_tr.load(f"qtbase_{i18n.qt_code()}", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(qt_tr)
    # Tek pencere: Revora zaten aciksa dosya orada yeni sekme olur, bu surec kapanir.
    # (--new ya da REVORA_MULTI=1: ayri pencere; dil degisince yeniden baslatma boyle acilir.)
    files = [os.path.abspath(a) for a in sys.argv[1:] if not a.startswith("--") and os.path.isfile(a)]
    single = "--new" not in sys.argv and os.environ.get("REVORA_MULTI") != "1"
    if single:
        try:
            if _hand_over(files):
                return
        except Exception:
            pass
    ensure_tesseract_env()
    win = MainWindow()  # tema, MainWindow.__init__ icinde uygulanir
    try:
        _listen(app, win)
    except Exception:
        pass
    win.show()
    win.raise_()
    win.activateWindow()
    active = None
    for a in sys.argv[1:]:                     # her dosya kendi sekmesinde
        if a.startswith("--tab="):
            active = a[6:]
        elif os.path.isfile(a):
            win.open_pdf(a)
    if active is not None and active.isdigit() and int(active) < len(win.tabs):
        win.switch_tab(int(active))            # (dil degisince yeniden baslatma: ayni sekme)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
