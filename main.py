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
    QComboBox, QMenu, QListWidget, QListWidgetItem, QAbstractItemView
)
from PySide6.QtGui import (QImage, QPixmap, QPainter, QPen, QColor, QCursor, QIcon,
                           QFont, QPalette, QPolygonF, QBrush, QKeySequence, QShortcut,
                           QPainterPath)
from PySide6.QtCore import Qt, QRect, QRectF, QPointF, QPoint, QSize, QSettings, QTimer, QObject, QEvent

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
from pdf_engine import PDFEditor
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
import pdf_content
import pdf_paths

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


def ic(name, color="#4b5058"):
    """Font Awesome ikonu dondurur; qtawesome yoksa bos QIcon."""
    if HAS_QTA:
        try:
            return qta.icon(name, color=color)
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
QLabel#pageLabel { color: %(text2)s; padding: 0 4px; }

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
QToolButton#mkToolDanger:hover { background: %(danger_bg)s; }
QToolButton#mkSwatch { background: transparent; border: none; border-radius: 7px; padding: 2px; }
QToolButton#mkSwatch:hover { background: %(tool_hover)s; }
QFrame#mkSep { background: %(border)s; margin: 0 4px; }
QFrame#mkSepStrong { background: %(muted)s; border-radius: 1px; }
QLabel#mkLabel { color: %(muted)s; padding: 0 6px; }
QFrame#mkPopover { background: %(surface)s; border: 1px solid %(border_input)s; border-radius: 10px; }
QFrame#mkPill QComboBox, QFrame#mkPill QDoubleSpinBox, QFrame#mkPill QSpinBox { padding: 3px 6px; }
QTextEdit#mkInlineText { background: rgba(255, 255, 255, 245); color: #111111;
    border: 2px solid %(accent)s; border-radius: 4px; padding: 2px; }

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: %(scroll)s; border-radius: 5px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: %(scroll_hover)s; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: %(scroll)s; border-radius: 5px; min-width: 30px; }
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
        self.setFixedSize(QSize(round(qimg.width() / dpr), round(qimg.height() / dpr) + self.pad_top))
        self.update()

    def set_pad_top(self, px):
        px = int(px)
        if px != self.pad_top:
            self.pad_top = px
            if self._pix is not None:
                sz = self._pix.deviceIndependentSize()
                self.setFixedSize(QSize(round(sz.width()), round(sz.height()) + px))
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
        bg = self.bg if self.bg is not None and getattr(self.win, "drag", None) else self._pix
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


def paint_thumb(p, r, pix, info):
    """Sol listede bir sayfa (ReorderView karti): kucuk resim + sayfa numarasi.
    Numara, surukleme sirasinda sayfanin birakilinca alacagi yeni sirayi gosterir."""
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


class MainWindow(QMainWindow, MarkupMixin):
    def __init__(self):
        super().__init__()
        self.resize(1280, 840)
        self.setAcceptDrops(True)

        self.engine = PDFEditor()
        self.current_page = 0
        self.mode = "text"            # "text" | "shape" | "insert"
        self.shape_tool = "select"    # "select" | "line" | "rect"
        self.current_span = None
        self.hover_span = None
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

    # ======================================================== UI kurulumu
    def _sep(self):
        w = QWidget()
        w.setFixedWidth(1)
        w.setFixedHeight(26)
        w.setStyleSheet("background:#8b909640;")
        return w

    def _tool_btn(self, fa, fallback, tip, checkable=False, text=None):
        b = QPushButton()
        b.setObjectName("toolbtn")
        b.setCheckable(checkable)
        b.setToolTip(tip)
        b.setCursor(QCursor(Qt.PointingHandCursor))
        icon = ic(fa, "#3d424a")
        if not icon.isNull():
            b.setIcon(icon)
            b.setIconSize(QSize(16, 16))
            if text:
                b.setText("  " + text)
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
            b.setIconSize(QSize(15, 15))
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
        root.addWidget(self._build_topbar())

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        # --- sol: sayfa kucuk resimleri ---
        # iOS tarzi siralama: tutulan sayfa kalkar, birakilacak yerde bosluk acilir.
        # Odak almaz (focusable=False): ok tuslari tuvalde metni tasimaya devam etsin.
        self.thumbs = ReorderView(THUMB_H + 26, paint_thumb, spacing=4, margin=6, focusable=False)
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
        pane = QWidget()
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
        bar = self._build_markup_bar()
        bar.setParent(center)
        self._bar_placer = _Resized(self._place_bar_overlay)
        center.installEventFilter(self._bar_placer)
        self.scroll.viewport().installEventFilter(self._bar_placer)
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

    def _build_topbar(self):
        bar = QWidget()
        bar.setObjectName("topbar")
        h = QHBoxLayout(bar)
        h.setContentsMargins(10, 8, 10, 8)
        h.setSpacing(4)

        # Dosya
        self.btn_open = self._tool_btn("fa5s.folder-open", _t("Aç"), _t("PDF aç (Ctrl+O)"), text=_t("Aç"))
        self.btn_save = self._tool_btn("fa5s.save", _t("Kaydet"), _t("Kaydet (Ctrl+S)"), text=_t("Kaydet"))
        self.btn_open.clicked.connect(self.open_pdf)
        self.btn_save.clicked.connect(self.save_pdf)
        save_menu = QMenu(self)
        save_menu.addAction(_t("Kaydet\tCtrl+S"), self.save_pdf)
        save_menu.addAction(_t("Farklı kaydet...\tCtrl+Shift+S"), self.save_pdf_as)
        self.btn_save_more = self._tool_btn("fa5s.caret-down", "▾", _t("Kaydetme seçenekleri"))
        self.btn_save_more.setMenu(save_menu)
        h.addWidget(self.btn_open)
        h.addWidget(self.btn_save)
        h.addWidget(self.btn_save_more)
        self.btn_undo = self._tool_btn("fa5s.undo", "↶", _t("Geri al (Ctrl+Z)"))
        self.btn_redo = self._tool_btn("fa5s.redo", "↷", _t("Yinele (Ctrl+Y)"))
        self.btn_undo.clicked.connect(self.undo_change)
        self.btn_redo.clicked.connect(self.redo_change)
        h.addWidget(self.btn_undo)
        h.addWidget(self.btn_redo)
        h.addWidget(self._sep())

        # Gezinme + zoom
        self.btn_prev = self._tool_btn("fa5s.chevron-left", "◀", _t("Önceki sayfa (PgUp)"))
        self.lbl_page = QLabel("—")
        self.lbl_page.setObjectName("pageLabel")
        self.btn_next = self._tool_btn("fa5s.chevron-right", "▶", _t("Sonraki sayfa (PgDn)"))
        self.btn_prev.clicked.connect(lambda: self.change_page(-1))
        self.btn_next.clicked.connect(lambda: self.change_page(1))
        h.addWidget(self.btn_prev)
        h.addWidget(self.lbl_page)
        h.addWidget(self.btn_next)

        self.btn_zoom_out = self._tool_btn("fa5s.search-minus", "−", _t("Uzaklaştır (Ctrl+tekerlek)"))
        self.lbl_zoom = QLabel("")
        self.lbl_zoom.setObjectName("pageLabel")
        self.btn_zoom_in = self._tool_btn("fa5s.search-plus", "+", _t("Yakınlaştır (Ctrl+tekerlek)"))
        self.btn_fit = self._tool_btn("fa5s.expand", _t("Sığdır"), _t("Sayfa genişliğine sığdır"))
        self.btn_zoom_out.clicked.connect(lambda: self.set_zoom(self.canvas.zoom / 1.2))
        self.btn_zoom_in.clicked.connect(lambda: self.set_zoom(self.canvas.zoom * 1.2))
        self.btn_fit.clicked.connect(self.fit_to_width)
        h.addWidget(self.btn_zoom_out)
        h.addWidget(self.lbl_zoom)
        h.addWidget(self.btn_zoom_in)
        h.addWidget(self.btn_fit)
        h.addWidget(self._sep())

        # Araclar (segment)
        self.btn_mode_text = self._make_seg("segL", "fa5s.i-cursor", _t("Metin"),
                                            _t("Var olan metni düzenle, sürükleyerek taşı, sil"))
        self.btn_mode_shape = self._make_seg("segM", "fa5s.vector-square", _t("Çizgi / Kutu"),
                                             _t("Çizgi ve çerçeveleri seç, taşı, boyutlandır, çiz"))
        self.btn_mode_insert = self._make_seg("segM", "fa5s.plus", _t("Yeni metin"),
                                              _t("Boş alana yeni metin ekle"))
        self.btn_mode_markup = self._make_seg("segR", "fa5s.highlighter", _t("İşaretle"),
                                              _t("Ok, daire, kutu ve not kutusu ekle (sonradan da "
                                              "düzenlenebilir)"))
        self.btn_mode_text.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        for b in (self.btn_mode_text, self.btn_mode_shape, self.btn_mode_insert, self.btn_mode_markup):
            grp.addButton(b)
        self.btn_mode_text.clicked.connect(lambda: self.set_mode("text"))
        self.btn_mode_shape.clicked.connect(lambda: self.set_mode("shape"))
        self.btn_mode_insert.clicked.connect(lambda: self.set_mode("insert"))
        self.btn_mode_markup.clicked.connect(lambda: self.set_mode("markup"))
        seg = QHBoxLayout()
        seg.setSpacing(0)
        seg.addWidget(self.btn_mode_text)
        seg.addWidget(self.btn_mode_shape)
        seg.addWidget(self.btn_mode_insert)
        seg.addWidget(self.btn_mode_markup)
        seg_w = QWidget()
        seg_w.setLayout(seg)
        h.addWidget(seg_w)

        h.addStretch()

        # Sayfa menusu (gecerli sayfa icin)
        self.btn_page = self._tool_btn("fa5s.file-alt", _t("Sayfa"), _t("Sayfa işlemleri"), text=_t("Sayfa"))
        self.btn_page.clicked.connect(
            lambda: self._page_menu(self.current_page).exec(
                self.btn_page.mapToGlobal(self.btn_page.rect().bottomLeft())))
        h.addWidget(self.btn_page)

        # PDF islemleri menusu
        self.btn_more = self._tool_btn("fa5s.ellipsis-v", _t("PDF İşlemleri"), _t("Birleştir, ayır, filigran, form, OCR"),
                                       text=_t("PDF İşlemleri"))
        menu = QMenu(self)
        menu.addAction(ic("fa5s.object-group"), _t("PDF Birleştir"), self.open_merge_dialog)
        menu.addAction(ic("fa5s.cut"), _t("PDF Ayır"), self.open_split_dialog)
        menu.addSeparator()
        # resim <-> PDF
        menu.addAction(ic("fa5s.file-image"), _t("Resimlerden PDF oluştur..."), self.open_images_to_pdf)
        self._doc_actions = [
            menu.addAction(ic("fa5s.image"), _t("Sayfayı resim olarak kaydet..."), self.export_pages_dialog),
            menu.addAction(ic("fa5s.images"), _t("Fotoğrafları çıkar (kalite kaybı olmadan)..."),
                           self.extract_photos_dialog),
            menu.addAction(ic("fa5s.clipboard"), _t("Sayfayı panoya resim olarak kopyala"), self.copy_page_image),
        ]
        menu.aboutToShow.connect(
            lambda: [a.setEnabled(self.engine.doc is not None) for a in self._doc_actions])
        menu.addSeparator()
        menu.addAction(ic("fa5s.stamp"), _t("Filigran ekle..."), self.open_watermark_dialog)
        menu.addAction(ic("fa5s.edit"), _t("Form doldur..."), self.open_form_dialog)
        menu.addAction(ic("fa5s.eye"), _t("OCR — taranmış sayfayı metne çevir..."), self.open_ocr_dialog)
        menu.addSeparator()
        menu.addAction(ic("fa5s.stamp"), _t("İşaretlemeleri sayfaya işle..."), self.flatten_markups_dialog)
        self.btn_more.setMenu(menu)
        h.addWidget(self.btn_more)

        # ayarlar (tema, kisayollar, hakkinda)
        self.btn_settings = self._tool_btn("fa5s.cog", _t("Ayarlar"), _t("Ayarlar (Ctrl+,)"))
        self.btn_settings.clicked.connect(self.open_settings)
        h.addWidget(self.btn_settings)
        return bar

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
        self.spin_text_angle.editingFinished.connect(
            lambda: self._rotate_text_to(self.spin_text_angle.value()))
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
        self.sh_tools_pill, l1 = markup_bar.pill()
        for b in (self.btn_tool_select, self.btn_tool_line, self.btn_tool_rect, self.btn_tool_ellipse):
            l1.addWidget(b)
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

        # ---- Metin / Yeni metin: yazi ayarlari
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
        self.btn_tx_edit.clicked.connect(self._text_edit_begin)
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
        self.txt_new.setObjectName("mkInlineText")
        self.txt_new.setMinimumHeight(0)
        self.txt_new.setMaximumHeight(16777215)
        self.txt_new.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_new.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.txt_new.setPlaceholderText(_t("Yazın…"))
        self.txt_new.hide()
        self._tx_editor_keys = _EditorKeys(self, self._inline_text_done)
        self.txt_new.installEventFilter(self._tx_editor_keys)
        self._apply_editor_align()
        self.txt_new.textChanged.connect(self._position_text_editor)

        self.cmb_dash.setVisible(self.chk_dashed.isChecked())     # desen listesi: sadece kesikliyken
        for w in (self.sh_tools_pill, self.sh_opts_pill, self.tx_opts_pill):
            w.hide()
        # satir yukseklikleri sabit: hangi mod/serit gorunurse gorunsun sayfa kaymaz
        pills = [(self.w_mk_tools, self.sh_tools_pill), (self.w_mk_options, self.sh_opts_pill,
                                                        self.tx_opts_pill)]
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
        if self.mode == "insert":
            self._position_text_editor()
            self.canvas.update()
        elif self.mode == "text" and self.current_span is not None and not self.txt_new.isVisible():
            self._text_style_timer.start()

    def _apply_text_style(self):
        if self.mode == "text" and self.current_span is not None and not self.txt_new.isVisible():
            self.apply_change()

    def _apply_shape_style_now(self):
        if self.mode == "shape" and self.sel_paths:
            self.apply_path_style()

    # ---------------- sayfa ustunde metin yazma ----------------
    def _text_edit_begin(self, select_all=True):
        """Secili metni (Metin modu) ya da yeni metni (Yeni metin modu) sayfanin
        ustunde duzenle."""
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
        self._position_text_editor()
        self.txt_new.raise_()
        self.txt_new.setFocus()
        if select_all:
            self.txt_new.selectAll()
        self.canvas.update()

    def _position_text_editor(self):
        if not self.txt_new.isVisible():
            return
        cv = self.canvas
        if self.mode == "text" and self.current_span is not None:
            sp = self.current_span
            q = sp.quad()
            r = cv.rect_px(fitz.Rect(min(p.x for p in q), min(p.y for p in q),
                                     max(p.x for p in q), max(p.y for p in q)))
            size = self.spin_size.value() or sp.size
            fam = self.combo_font.currentText() if self.combo_font.currentData() else self._preview_family(sp.font)
        elif self.mode == "insert" and self.pending_insert is not None:
            _, x, y = self.pending_insert
            size = self.spin_size.value()
            a = cv.to_px((x, y - size))
            r = QRectF(a.x(), a.y(), 0, size * cv.zoom)
            fam = self.combo_font.currentText() if self.combo_font.currentData() else "Arial"
        else:
            return
        f = QFont(fam)
        f.setPixelSize(max(11, min(60, round(size * cv.zoom))))
        f.setBold(self.chk_bold.isChecked())
        self.txt_new.setFont(f)
        fm = self.txt_new.fontMetrics()
        lines = (self.txt_new.toPlainText() or " ").split("\n")
        w = max(r.width() + 18, max(fm.horizontalAdvance(l) for l in lines) + 36, 180)
        h = fm.lineSpacing() * max(1, len(lines)) + 18
        # hizalamaya gore kutunun yeri: sola = basi, ortali = ortasi, saga = sonu sabit
        if self.text_align == "center":
            x = r.center().x() - w / 2
        elif self.text_align == "right":
            x = r.right() - w + 6
        else:
            x = r.x() - 6
        self.txt_new.setGeometry(int(x), int(r.y()) - 6, int(w), int(h))

    def _inline_text_done(self):
        """Yazma kutusu kapaniyor (Esc / Ctrl+Enter / baska yere tiklama): uygula."""
        if not self.txt_new.isVisible():
            return
        self.txt_new.hide()
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
        if not self._confirm_discard():
            return
        from PySide6.QtCore import QProcess
        path = self.engine.path if self.engine.doc is not None else None
        if self.engine.doc is not None:
            self.engine.dirty = False             # soruldu; kapanirken tekrar sorulmasin
        if getattr(sys, "frozen", False):
            prog, args = sys.executable, []
        else:
            prog, args = sys.executable, [os.path.abspath(__file__)]   # nasil baslatildiysa
        if path and os.path.isfile(path):
            args.append(path)
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
        has = self.engine.doc is not None
        self.btn_undo.setEnabled(has and bool(self.engine.undo_stack))
        self.btn_redo.setEnabled(has and bool(self.engine.redo_stack))
        for b in (self.btn_pg_dup, self.btn_pg_blank, self.btn_pg_import,
                  self.btn_save, self.btn_save_more, self.btn_page, self.btn_prev, self.btn_next,
                  self.btn_zoom_in, self.btn_zoom_out, self.btn_fit):
            b.setEnabled(has)

    def _refresh_panel(self):
        """Ust seritler: hangi mod aciksa onun araclari (1. satir) ve ayarlari (2. satir).
        Sag panel yok; bilgi yazisi yok. Satir yukseklikleri sabit (sayfa kaymaz)."""
        self._refresh_bars()
        self._settle_bars()

    def _settle_bars(self):
        """Seritlerde parca gizlenip gosterilince boyut + ortalama HEMEN yeniden hesaplansin
        (yoksa daralan serit bir sonraki olaya kadar eski yerinde, ortadan kaymis kaliyor)."""
        for p in (self.w_mk_tools, self.w_mk_options, self.sh_tools_pill, self.sh_opts_pill,
                  self.tx_opts_pill):
            if p.isVisibleTo(self.mk_bar_host):
                p.layout().activate()
        # bos satir gizlenir: tek seritli modlarda (Metin, Yeni metin) serit en uste cikar
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
        for w in (self.sh_tools_pill, self.sh_opts_pill, self.tx_opts_pill):
            w.hide()
        self.mk_bar_host.setVisible(has_doc)
        if not has_doc:
            return
        if self.mode == "markup":
            self._markup_refresh_panel()
            return
        if self.mode == "shape":
            self.sh_tools_pill.show()
            sel = bool(self.sel_paths)
            # Sec araci + secim yok: gosterecek ayar yok (bosa tiklayinca / silince kalkar)
            self.sh_opts_pill.setVisible(sel or self.shape_tool != "select")
            if not sel and self.shape_tool != "select":
                self._show_shape_style()      # cizim araci: son kullanilan (secilenin degil)
            self.sh_del_sep.setVisible(sel)
            self.btn_sh_delete.setVisible(sel)
            return
        if self.mode == "insert":
            self.tx_opts_pill.show()
            self.chk_autofit.hide()
            self.tx_rot_box.hide()
            self.tx_edit_box.hide()
            return
        # metin modu: bir metin secilince ayarlari cikar
        has = self.current_span is not None
        self.tx_opts_pill.setVisible(has)
        self.chk_autofit.show()
        self.tx_rot_box.show()
        self.tx_edit_box.show()

    # ======================================================== dosya
    def _confirm_discard(self):
        """Kaydedilmemis degisiklik varsa sor. Devam edilebilirse True."""
        if self.engine.doc is None or not self.engine.dirty:
            return True
        r = self._ask_unsaved()
        if r == "save":
            return self.save_pdf()
        return r == "discard"

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
        if not self._confirm_discard():
            return
        if not path:
            path, _ = QFileDialog.getOpenFileName(
                self, _t("PDF Aç"), self._last_open_path(),
                _t("PDF ve resimler (*.pdf {p})", p=image_tools.IMAGE_PATTERN) + ";;"
                + _t("PDF Dosyaları (*.pdf)") + ";;" + image_tools.image_filter())
        if not path:
            return
        try:
            if image_tools.is_image(path):      # resim: tek sayfalik PDF'e cevrilip acilir
                doc, skipped = image_tools.images_to_pdf([path], "image")
                if not len(doc):
                    raise ValueError(skipped[0][1] if skipped else path)
                self.engine.open_doc(doc, os.path.splitext(path)[0] + ".pdf")
            else:
                self.engine.open(path)
        except Exception as e:
            QMessageBox.critical(self, _t("Açılamadı"),
                                 _t("Bu PDF açılamadı (bozuk ya da desteklenmeyen dosya):\n{e}", e=e))
            return
        if self.engine.doc.needs_pass:
            QMessageBox.warning(self, _t("Şifreli PDF"),
                                _t("Bu PDF parola korumalı. Lütfen önce parolayı kaldırıp tekrar açın."))
            self.engine.doc = None
            self.canvas.clear_page()
            self._update_title()
            self._refresh_panel()
            return
        self.current_page = 0
        last = self._last_page_of(path)        # bu dosyada en son bakilan sayfa (liste dolarken
        self._remember_open(path)              # 1. sayfaya donulup ezilmeden once okunur)
        self._clear_selection()
        self._populate_thumbnails()
        self.fit_to_width()
        if 0 < last < self.engine.page_count():
            self.goto_page(last)
        self._refresh_panel()
        self._update_title()
        self.status(_t("Açıldı: {name}", name=os.path.basename(path)))

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
            return True
        return False

    def _do_save(self, path):
        try:
            self.engine.save(path)
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
        if self._confirm_discard():
            ev.accept()
        else:
            ev.ignore()

    def dragEnterEvent(self, ev):
        if any(u.toLocalFile().lower().endswith(".pdf") or image_tools.is_image(u.toLocalFile())
               for u in ev.mimeData().urls()):
            ev.acceptProposedAction()

    def dropEvent(self, ev):
        for u in ev.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(".pdf"):
                self.open_pdf(p)
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
        self.lbl_page.setText(f"{self.current_page + 1} / {self.engine.page_count()}")
        self.lbl_zoom.setText(_t("%{z}", z=int(z * 100)))      # dile gore: %220 / 220%
        name = self._doc_name()
        self.lbl_fileinfo.setText(_t("{name} · {n} sayfa", name=name, n=self.engine.page_count()) if name else "")
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
        {"text": self.btn_mode_text, "shape": self.btn_mode_shape,
         "insert": self.btn_mode_insert, "markup": self.btn_mode_markup}[mode].setChecked(True)
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

    def set_shape_tool(self, tool):
        self.shape_tool = tool
        {"select": self.btn_tool_select, "line": self.btn_tool_line,
         "rect": self.btn_tool_rect, "ellipse": self.btn_tool_ellipse}[tool].setChecked(True)
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
        if self.hover_span is not None or self.hover_path is not None or self.hover_markup is not None:
            self.hover_span = None
            self.hover_path = None
            self.hover_markup = None
            self.canvas.update()

    # ======================================================== fare olaylari
    def canvas_press(self, pt, pos, mods):
        if not self.engine.doc:
            return
        self._press_pos = pos
        self._nudge_token += 1        # yeni tiklama: sonraki ok kaydirmalari yeni geri-al adimi
        if self.mode == "text":
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
        if self.mode == "text":
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
        if self.mode == "text" and self.current_span is not None:
            self._text_edit_begin()           # yazi sayfanin ustunde duzenlenir
        elif self.mode == "markup":
            self._mk_double(pt)

    def canvas_context(self, pt, global_pos):
        if not self.engine.doc:
            return
        menu = QMenu(self)
        if self.mode == "text":
            span = self.engine.find_span_at(self.current_page, pt.x, pt.y)
            if span is not None:
                self._select_text_span(span)
                menu.addAction(_t("Metni düzenle"), lambda: (self.txt_new.setFocus(), self.txt_new.selectAll()))
                menu.addAction(_t("Metni kopyala"),
                               lambda: QApplication.clipboard().setText(span.text.replace("\xa0", " ")))
                menu.addSeparator()
                menu.addAction(_t("Sil"), self.delete_selected)
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
        if span is None:
            if self.current_span is not None:
                self.current_span = None
                self._refresh_panel()
            return
        if span is not self.current_span:
            self._select_text_span(span)
        self.drag = {"kind": "text", "start": pt, "cur": pt, "moved": False}

    def _text_move(self, pt, pos, mods, pressed):
        d = self.drag
        if d and pressed:
            if not d["moved"] and not self._moved_enough(pos):
                return
            if not d["moved"] and d["kind"] in ("text", "textrot") and self.current_span is not None:
                self._ghost_text(self.current_span)        # yazi yerinden kalkar, kendisi gider
            d["moved"] = True
            if d["kind"] == "textrot":
                d["cur"] = pt
                d["keep"] = bool(mods & Qt.ShiftModifier)
            else:
                d["cur"] = self._axis_lock(d["start"], pt) if mods & Qt.ShiftModifier else pt
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
        if span is not self.hover_span:
            self.hover_span = span
            self.update_cursor(Qt.SizeAllCursor if span is not None else None)
            self.canvas.update()

    def _text_release(self, pt, mods):
        d = self.drag
        if not d or not d["moved"] or self.current_span is None:
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

    def _rotate_text_to(self, deg):
        sp = self.current_span
        if sp is None:
            return
        cur = self.engine.span_angle(sp)
        delta = ((deg - cur + 180.0) % 360.0) - 180.0
        self._rotate_text_by(delta)

    def _on_text_color(self, rgb):
        self.selected_color = rgb
        self.canvas.update()

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
        self.pending_insert = (self.current_page, pt.x, pt.y)
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
            self.pending_insert = (self.current_page, ox + cur.x - d["start"].x, oy + cur.y - d["start"].y)
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
    def _ghost_diff(self, rect_px, remove, bg_only=False):
        """Sayfanin icindeki nesne (metin, cizim): kopyada nesnesi cikarilmis sayfa bir
        kez cizilir; arka plan o olur, nesnenin pikselleri (fark) fareyle gider.
        Basarisizsa hicbir sey degismez (eski cerceve onizlemesi kalir)."""
        cv = self.canvas
        if not cv.has_page() or not getattr(self, "_render_scale", None):
            return
        d = cv.dpr
        page_img = cv._pix.toImage()
        r = QRect(int(rect_px.x() * d), int((rect_px.y() - cv.pad_top) * d),
                  int(rect_px.width() * d) + 2, int(rect_px.height() * d) + 2).intersected(page_img.rect())
        if r.isEmpty():
            return
        res = drag_ghost.render_without(self.engine.doc, self.current_page, self._render_scale, remove, r)
        if res is None:
            return
        part, r = res
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
            self._ghost_painter = lambda p, cv, dd: self._paint_text_ghost(p, cv, lines, dd, blend)
            self._ghost_diff(rect, remove, bg_only=True)
        else:
            self._ghost_diff(rect, remove)

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
        cv = self.canvas
        if cv.bg is not None or cv.ghost is not None:
            cv.bg = cv.ghost = None
            cv.update()

    def _ghost_delta(self):
        d = self.drag
        if not d or not d.get("moved"):
            return None
        if d["kind"] in ("text", "move", "mkmove"):
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
        p.drawPixmap(cv.to_px(anchor + dd), pm)
        p.restore()

    def paint_overlay(self, p, cv):
        self._paint_ghost(p, cv)
        if self.mode == "text":
            self._paint_text_overlay(p, cv)
        elif self.mode == "shape":
            self._paint_shape_overlay(p, cv)
        elif self.mode == "markup":
            self._paint_markup_overlay(p, cv)
        else:
            self._paint_insert_overlay(p, cv)

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
        sp = self.current_span
        if sp is None:
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
                self.drag = None
                self._ghost_end()
                self._set_render_hide(())
            elif self.mode == "shape" and self.shape_tool != "select":
                self.set_shape_tool("select")
                return True
            elif self.mode == "markup" and self.sel_markup is not None:
                self._mk_select(None)          # once secimi birak, arac acik kalsin
                return True
            elif self.mode == "markup" and self.mk_tool != "select":
                self.set_markup_tool("select")
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
        if key == Qt.Key_A and mods & Qt.ControlModifier and self.mode == "shape":
            self.set_shape_tool("select")
            self._select_all_paths()
            return True
        if key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2) and self.mode == "text" and self.current_span:
            self._text_edit_begin()
            return True
        plain = not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
        if self.mode == "shape" and plain and key in (Qt.Key_V, Qt.Key_L, Qt.Key_K, Qt.Key_D):
            self.set_shape_tool({Qt.Key_V: "select", Qt.Key_L: "line", Qt.Key_K: "rect",
                                 Qt.Key_D: "ellipse"}[key])
            return True
        if key in steps:
            step = self._nudge_step() * (5 if mods & Qt.ShiftModifier else 1)
            dx, dy = steps[key]
            v = self._display_delta(dx * step, dy * step)
            self.on_arrow_move(v.x, v.y)
            if self.current_span is not None or self.sel_paths or self.pending_insert is not None \
                    or self.sel_markup is not None:
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
        spacing = self.spin_spacing.value()

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
        if self.current_span is None:
            return
        self.engine.apply_edit(self.current_span, "")
        self.current_span = None
        self.after_edit()
        self.status(_t("Metin silindi."))

    def undo_change(self):
        if self.engine.doc and self.engine.undo():
            self._after_history(_t("Geri alındı."))
        else:
            self.status(_t("Geri alınacak değişiklik yok."))

    def redo_change(self):
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
    ensure_tesseract_env()
    win = MainWindow()  # tema, MainWindow.__init__ icinde uygulanir
    win.show()
    win.raise_()
    win.activateWindow()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        win.open_pdf(sys.argv[1])
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
