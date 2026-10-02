"""
markup_ui.py
------------
"Isaretle" modunun arayuzu. MainWindow'a karisim (mixin) olarak eklenir:
ok, daire/elips, kutu ve not kutusu cizilir; secilir, tasinir, boyutlandirilir,
stili degistirilir. Nesneler pdf_markup ile saklandigi icin dosya kaydedilip
yeniden acilinca da duzenlenebilir.

Kisayollar: Shift ile ciz -> ok 45 derece adimlarla, daire tam daire, kutu kare.
Sec aracinda: surukle = tasi, tutamaclar = boyutlandir / ok uclari / not okunun
hedefi, Delete = sil, oklar = ince kaydirma, cift tik (not) = metni duzenle.
"""
import json
import math

# import sirasi kurali: PySide6, fitz'ten once
from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QGridLayout,
                               QDoubleSpinBox, QSpinBox, QCheckBox, QComboBox, QTextEdit,
                               QButtonGroup, QMessageBox, QSlider, QLineEdit, QLabel, QApplication)
from PySide6.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QPainterPath, QFont, QFontMetrics, QIcon
from PySide6.QtCore import Qt, QTimer, QPointF, QRectF, QEvent, QObject, QSize
import fitz

import pdf_markup
import pdf_blur
import curve_math
import markup_bar
import drag_ghost
from font_resolver import FONT_DISPLAY_NAMES
from i18n import _t

BLUE = [0.145, 0.388, 0.922]
HANDLE = 4.5  # tutamac yari-genisligi (ekran px)
BEND_SNAP = 5  # bukme tutamaci duz cizgiye bu kadar (ekran px) yaklasinca ok duzlesir
BOX_CURSORS = {"tl": Qt.SizeFDiagCursor, "br": Qt.SizeFDiagCursor,
               "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor,
               "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
               "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor}

DEFAULT_STYLE = {
    "arrow": {"color": BLUE, "width": 2.0, "opacity": 1.0, "dashed": False, "dash": "dash_m",
              "head": "end", "head_scale": 1.0},
    "ellipse": {"color": BLUE, "width": 2.0, "opacity": 1.0, "dashed": False, "dash": "dash_m",
                "fill_on": False, "fill_color": [1.0, 0.9, 0.2]},
    "rect": {"color": BLUE, "width": 1.5, "opacity": 1.0, "dashed": False, "dash": "dash_m",
             "fill_on": False, "fill_color": [1.0, 0.9, 0.2]},
    "note": {"color": BLUE, "width": 1.2, "opacity": 1.0, "border_on": False,
             "fill_on": False, "fill_color": [1.0, 1.0, 1.0], "text_color": [0.1, 0.1, 0.1],
             "size": 11.0, "font": "Arial", "bold": False, "italic": False,
             "shadow": False, "outline": False, "outline_color": [0, 0, 0], "head_scale": 1.0},
    "magnifier": {"color": BLUE, "width": 1.5, "opacity": 1.0, "dashed": False, "dash": "dash_m",
                  "mode": "detail", "zoom": 2.0, "label_on": True, "caption_on": True,
                  "show_scale": True, "label_font": "Arial", "label_size": 10.0,
                  "label_bold": True, "label_color": BLUE},
    "blur": {"bmode": "blur", "level": 5},
    # Cizgi araci = ucsuz ok; son kullanilan ayarlari oktan AYRI tutulur
    "line": {"color": BLUE, "width": 2.0, "opacity": 1.0, "dashed": False, "dash": "dash_m", "head": "none",
             "head_scale": 1.0},
    "ink": {"color": BLUE, "width": 2.0, "opacity": 1.0},                       # kalem
    "highlight": {"color": [1.0, 0.85, 0.0], "width": 12.0, "opacity": 0.5,     # fosforlu kalem + metin vurgusu
                  "hlstyle": "highlight"},
    "sign": {"color": [0.05, 0.1, 0.4], "width": 1.6, "opacity": 1.0},          # imza
    "number": {"color": [0.86, 0.15, 0.15], "text_color": [1.0, 1.0, 1.0], "nsize": 20.0, "opacity": 1.0},
    "image": {"opacity": 1.0},
}
FREEHAND = ("pen", "highlight", "eraser")      # basinca her zaman cizer (nesne secmez)
# ust cubuktaki araclar (None = ayirici) ve tek tus kisayollari
TOOLS = (("select", "mdi6.cursor-default-outline", _t("Seç / taşı")), (None, None, None),
         ("arrow", "mdi6.arrow-top-right", _t("Ok")), ("line", "mdi6.minus", _t("Çizgi")),
         ("rect", "mdi6.rectangle-outline", _t("Kutu")), ("ellipse", "mdi6.circle-outline", _t("Daire")),
         ("note", "mdi6.message-text-outline", _t("Not")), (None, None, None),
         ("pen", "mdi6.pencil-outline", _t("Kalem")),
         ("highlight", "mdi6.marker", _t("Fosforlu kalem — yazının üstünden geçince kelimelere oturur")),
         ("number", "mdi6.numeric-1-circle-outline", _t("Numara (her tıklamada sıradaki)")),
         ("eraser", "mdi6.eraser", _t("Silgi — üstünden geçtiğin işaretlemeleri siler")), (None, None, None),
         ("magnifier", "mdi6.magnify-plus-outline", _t("Büyüteç")),
         ("blur", "mdi6.blur", _t("Bulanıklaştır")))
TOOL_KEYS = {"select": "V", "arrow": "O", "line": "L", "rect": "K", "ellipse": "D", "note": "N",
             "pen": "P", "highlight": "H", "number": "1", "eraser": "E", "magnifier": "M", "blur": "B"}
KEY_TOOLS = {Qt.Key_V: "select", Qt.Key_O: "arrow", Qt.Key_L: "line", Qt.Key_K: "rect",
             Qt.Key_D: "ellipse", Qt.Key_N: "note", Qt.Key_M: "magnifier", Qt.Key_B: "blur",
             Qt.Key_P: "pen", Qt.Key_H: "highlight", Qt.Key_1: "number", Qt.Key_E: "eraser"}
MAG_MODES = ((_t("Detay görünümü"), "detail"), (_t("Yerinde büyüteç"), "lens"))
NOTE_PRESETS = {
    _t("Sade"): {"fill_on": False, "border_on": False, "text_color": [0.1, 0.1, 0.1],
             "shadow": False, "outline": False},
    _t("Etiket (koyu zemin)"): {"fill_on": True, "fill_color": [0.12, 0.12, 0.14],
                            "text_color": [1, 1, 1], "border_on": False, "shadow": False,
                            "outline": False},
    _t("Konturlu yazı"): {"fill_on": False, "border_on": False, "text_color": [1, 1, 1],
                      "outline": True, "outline_color": [0, 0, 0], "shadow": False, "bold": True},
    _t("Sarı not"): {"fill_on": True, "fill_color": [1.0, 0.95, 0.6], "text_color": [0.1, 0.1, 0.1],
                 "border_on": False, "shadow": False, "outline": False},
    _t("Çerçeve"): {"fill_on": True, "fill_color": [1, 1, 1], "text_color": [0.8, 0.05, 0.05],
                "border_on": True, "color": [0.85, 0.1, 0.1], "shadow": False, "outline": False},
}
# kendi sablonlarima kaydedilen not ayarlari (tam gorunum; yazi ve konum haric)
NOTE_STYLE_KEYS = ("color", "width", "opacity", "head_scale", "fill_on", "fill_color", "border_on",
                   "text_color", "size", "font", "bold", "italic", "shadow", "outline", "outline_color")
HEAD_SCALES = ((_t("Küçük"), 0.7), (_t("Orta"), 1.0), (_t("Büyük"), 1.5))
TOOL_KIND = {"arrow": "arrow", "line": "arrow", "ellipse": "ellipse", "rect": "rect", "note": "note",
             "magnifier": "magnifier", "blur": "blur", "pen": "ink", "highlight": "ink", "number": "number"}
# Ayarlar > Klavye kisayollari'nda gosterilen Isaretle kisayollari
SHORTCUTS = (
    (_t("Araçlar"), None),
    ("V  O  L  K  D  N", _t("Seç · Ok · Çizgi · Kutu · Daire · Not")),
    ("P  H  1  E", _t("Kalem · Fosforlu kalem · Numara · Silgi")),
    ("M  B", _t("Büyüteç · Bulanıklaştır")),
    ("S  /  G", _t("İmza ekle · Görüntü ekle")),
    (_t("Fosforlu kalem"), _t("Yazının üstünden başla: kelimelere oturur · boşta: serbest")),
    (_t("Çizim"), None),
    ("Shift", _t("Ok/çizgi/kalem 45° adım · kare / tam daire · oranı koru")),
    (_t("Shift (görüntü, imza)"), _t("Oranı bozarak boyutlandır")),
    ("Alt", _t("Kutu / daire / bulanık: merkezden çiz ve ölçekle")),
    (_t("Alt (ok/çizgi ucu)"), _t("Açı sabit, sadece uzunluk")),
    (_t("Ctrl + sürükle"), _t("Nesnenin üstünden de yeni çizim başlat")),
    (_t("Orta tutamaç"), _t("Çizgiyi / oku bük · çift tık: düzleştir")),
    (_t("Düzenleme"), None),
    ("Delete", _t("Sil")),
    ("Ctrl + D", _t("Çoğalt")),
    (_t("Oklar (+Shift)"), _t("İnce kaydırma (5 kat)")),
    (_t("F2 / çift tık"), _t("Not yazısını düzenle · Esc: bitir")),
    ("Esc", _t("Seçimi bırak · ikinci kez: Seç aracı")),
    (_t("Sağ tık"), _t("Çoğalt, öne getir / arkaya gönder, düzleştir")),
)
MAG_TEXT_KEYS = ("label_on", "caption_on", "show_scale", "label_font", "label_size",
                 "label_bold", "label_color")


def style_key(kind, P):
    """Nesnenin 'son kullanilan ayar' anahtari (kalem / fosforlu / imza ayri hatirlanir)."""
    if kind == "arrow" and P.get("head") == "none":
        return "line"
    if kind == "ink":
        return "highlight" if P.get("hl") else ("sign" if P.get("sig") else "ink")
    if kind == "texthl":
        return "highlight"
    return kind


def params_from(kind, st, geom):
    """Stil + geometri -> pdf_markup ayarlari. Donme acisi geometridir (stil degil):
    son kullanilan ayar olarak hatirlanmaz, nesneyle birlikte tasinir."""
    P = _params_from(kind, st, geom)
    if kind in ("arrow", "rect", "ellipse", "magnifier"):
        P["dash"] = st.get("dash") or "dash_m"
    if kind in pdf_markup.ROTATABLE:
        P["angle"] = float(geom.get("angle") or 0.0)
    return P


def _params_from(kind, st, geom):
    if kind == "ink":
        return {"strokes": geom["strokes"], "color": st["color"], "width": st["width"],
                "opacity": st["opacity"], "hl": bool(geom.get("hl")), "sig": bool(geom.get("sig"))}
    if kind == "texthl":
        return {"rects": geom["rects"], "color": st["color"], "opacity": st["opacity"],
                "style": st.get("hlstyle", "highlight")}
    if kind == "number":
        return {"pos": geom["pos"], "n": int(geom["n"]), "size": st.get("nsize", 20.0),
                "color": st["color"], "text_color": st.get("text_color", [1, 1, 1]),
                "opacity": st["opacity"]}
    if kind == "image":
        return {"rect": geom["rect"], "opacity": st.get("opacity", 1.0)}   # aci: params_from
    if kind == "blur":
        return {"rect": geom["rect"], "mode": st.get("bmode", "blur"), "level": st.get("level", 5)}
    if kind == "magnifier":
        P = {"mode": st.get("mode", "detail"), "src": geom["src"], "r": geom["r"],
             "dst": geom.get("dst") or geom["src"], "zoom": st.get("zoom", 2.0),
             "label": geom.get("label", ""), "caption": geom.get("caption", ""),
             "color": st["color"], "width": st["width"],
             "opacity": st["opacity"], "dashed": st["dashed"]}
        for k in MAG_TEXT_KEYS:
            P[k] = st.get(k, DEFAULT_STYLE["magnifier"][k])
        return P
    if kind == "arrow":
        return {"p1": geom["p1"], "p2": geom["p2"], "bend": geom.get("bend"),
                "color": st["color"], "width": st["width"],
                "head": st["head"], "head_scale": st.get("head_scale", 1.0),
                "dashed": st["dashed"], "opacity": st["opacity"]}
    if kind in ("ellipse", "rect"):
        return {"rect": geom["rect"], "color": st["color"], "width": st["width"],
                "fill": st["fill_color"] if st["fill_on"] else None, "dashed": st["dashed"],
                "opacity": st["opacity"]}
    return {"pos": geom["pos"], "text": geom.get("text", ""), "target": geom.get("target"),
            "bend": geom.get("bend") if geom.get("target") else None,
            "size": st["size"], "text_color": st["text_color"],
            "font": st.get("font", "Arial"), "bold": st.get("bold", False),
            "italic": st.get("italic", False), "shadow": st.get("shadow", False),
            "outline": st.get("outline", False), "outline_color": st.get("outline_color", [0, 0, 0]),
            "fill": st["fill_color"] if st["fill_on"] else None,
            "border": st["color"] if st["border_on"] else None, "border_width": st["width"],
            "arrow_color": st["color"], "arrow_width": max(1.0, st["width"] * 1.4),
            "head_scale": st.get("head_scale", 1.0), "opacity": st["opacity"]}


def style_from(kind, P):
    if kind in ("ink", "texthl", "number", "image"):
        base = dict(DEFAULT_STYLE[style_key(kind, P)])
        base["opacity"] = P.get("opacity", 1.0)
        if kind != "image":
            base["color"] = P["color"]
        if kind == "ink":
            base["width"] = P.get("width", base["width"])
        elif kind == "texthl":
            base["hlstyle"] = P.get("style", "highlight")
        elif kind == "number":
            base.update(text_color=P.get("text_color", [1, 1, 1]), nsize=P.get("size", 20.0))
        return base
    base = dict(DEFAULT_STYLE[kind])
    if "dash" in base:
        base["dash"] = P.get("dash") or "dash_m"
    if kind == "blur":
        base.update(bmode=P.get("mode", "blur"), level=P.get("level", 5))
        return base
    if kind == "magnifier":
        base.update(color=P["color"], width=P["width"], opacity=P.get("opacity", 1.0),
                    dashed=bool(P.get("dashed")), mode=P.get("mode", "detail"),
                    zoom=P.get("zoom", 2.0))
        for k in MAG_TEXT_KEYS:
            if k in P:
                base[k] = P[k]
        base["label_on"] = pdf_markup._label_on(P)
        if "label_color" not in P:
            base["label_color"] = P["color"]
        return base
    if kind == "arrow":
        base.update(color=P["color"], width=P["width"], head=P.get("head", "end"),
                    head_scale=P.get("head_scale", 1.0), dashed=bool(P.get("dashed")),
                    opacity=P.get("opacity", 1.0))
    elif kind in ("ellipse", "rect"):
        base.update(color=P["color"], width=P["width"], dashed=bool(P.get("dashed")),
                    opacity=P.get("opacity", 1.0), fill_on=P.get("fill") is not None)
        if P.get("fill") is not None:
            base["fill_color"] = P["fill"]
    else:
        base.update(color=P.get("border") or P.get("arrow_color") or base["color"],
                    border_on=P.get("border") is not None, width=P.get("border_width", 1.2),
                    fill_on=P.get("fill") is not None, text_color=P["text_color"],
                    size=P["size"], opacity=P.get("opacity", 1.0),
                    font=P.get("font", "Arial"), bold=bool(P.get("bold")),
                    italic=bool(P.get("italic")), shadow=bool(P.get("shadow")),
                    outline=bool(P.get("outline")),
                    outline_color=P.get("outline_color", [0, 0, 0]),
                    head_scale=P.get("head_scale", 1.0))
        if P.get("fill") is not None:
            base["fill_color"] = P["fill"]
    return base


def geom_from(kind, P):
    if kind == "ink":
        return {"strokes": P["strokes"], "hl": P.get("hl"), "sig": P.get("sig")}
    if kind == "texthl":
        return {"rects": P["rects"]}
    if kind == "number":
        return {"pos": P["pos"], "n": P.get("n", 1)}
    if kind == "image":
        return {"rect": P["rect"], "angle": P.get("angle", 0.0)}
    if kind == "magnifier":
        return {"src": P["src"], "r": P["r"], "dst": P.get("dst"), "label": P.get("label", ""),
                "caption": P.get("caption", "")}
    if kind == "arrow":
        return {"p1": P["p1"], "p2": P["p2"], "bend": P.get("bend")}
    if kind in ("ellipse", "rect", "blur"):
        return {"rect": P["rect"], "angle": P.get("angle", 0.0)}
    return {"pos": P["pos"], "text": P.get("text", ""), "target": P.get("target"),
            "bend": P.get("bend"), "angle": P.get("angle", 0.0)}


class _EditorKeys(QObject):
    """Sayfa ustundeki yazi kutusu (not / metin / yeni metin): Esc / Ctrl+Enter = bitir."""

    def __init__(self, owner, done=None):
        super().__init__(owner)
        self.owner = owner
        self.done = done

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.KeyPress and (
                ev.key() == Qt.Key_Escape or
                (ev.key() in (Qt.Key_Return, Qt.Key_Enter) and ev.modifiers() & Qt.ControlModifier)):
            (self.done or self.owner._mk_close_editor)()
            return True
        return False


class MarkupMixin:
    # ============================================================ panel
    def _build_markup_bar(self):
        """ShareX tarzi ust cubuk: ustte arac ikonlari, altta secili araca/nesneye
        gore degisen ayarlar. Tuvalin ustunde ortalanir; sag panel bu modda gizlenir."""
        self.mk_tool = "select"
        self.sel_markup = None
        self.hover_markup = None
        # son kullanilan ayarlar (tur basina) - kapatip acinca da hatirlanir
        self.mk_style = self.load_style_setting("markup_style", DEFAULT_STYLE)
        self._mk_loading = False
        self._mk_loaded = None
        self._mk_text_timer = QTimer(self)
        self._mk_text_timer.setSingleShot(True)
        self._mk_text_timer.setInterval(350)
        self._mk_text_timer.timeout.connect(self._mk_apply_text)
        self._blur_cache = None
        self._mag_cache = None
        self._mk_bar_buttons = []          # tema degisince ikonlari yeniden renklenecekler

        def tb(name, tip, checkable=True, text=None):
            b = markup_bar.tool_button(name, tip, checkable, text, self.dark)
            self._mk_bar_buttons.append(b)
            return b

        def spin(widget, w, tip):
            widget.setFixedWidth(w)
            widget.setToolTip(tip)
            return widget

        host = QWidget()
        host.setObjectName("mkBarHost")
        hv = QVBoxLayout(host)
        hv.setContentsMargins(8, 8, 8, 6)
        hv.setSpacing(6)

        # ---------------- 1. satir: araclar ----------------
        row1, l1 = markup_bar.pill()
        self.w_mk_tools = row1
        g = QButtonGroup(self)
        g.setExclusive(True)
        self.mk_tool_btns = {}
        for tool, icon_name, name in TOOLS:
            if tool is None:
                l1.addWidget(markup_bar.vsep())
                continue
            key = TOOL_KEYS.get(tool, "")
            b = tb(icon_name, f"{name}  ({key})" if key else name)
            g.addButton(b)
            b.clicked.connect(lambda _=False, t=tool: self.set_markup_tool(t))
            l1.addWidget(b)
            self.mk_tool_btns[tool] = b
        self.mk_tool_btns["select"].setChecked(True)
        l1.addWidget(markup_bar.vsep())
        # imza / goruntu: arac degil, tiklayinca hemen ekleyen dugmeler
        self.btn_mk_sign = tb("mdi6.signature-freehand", _t("İmza ekle  (S)"), checkable=False)
        self.btn_mk_sign.clicked.connect(self._mk_sign_menu)
        self.btn_mk_image = tb("mdi6.image-plus-outline", _t("Görüntü ekle — logo, kaşe, fotoğraf  (G)"),
                               checkable=False)
        self.btn_mk_image.clicked.connect(self._mk_add_image)
        l1.addWidget(self.btn_mk_sign)
        l1.addWidget(self.btn_mk_image)
        l1.addWidget(markup_bar.vsep())
        self.btn_mk_flatten = tb("mdi6.stamper", _t("Tüm işaretlemeleri sayfaya işle (kalıcı yap)"),
                                 checkable=False)
        self.btn_mk_flatten.clicked.connect(self.flatten_markups_dialog)
        l1.addWidget(self.btn_mk_flatten)

        # ---------------- 2. satir: ayarlar ----------------
        row2, l2 = markup_bar.pill()
        self.w_mk_options = row2
        # (gizlenince yer KORUNMAZ: satirda baska modlarin seritleri de var ve ortalanmali.
        #  Sayfanin zıplamamasini sabit satir yuksekligi saglar.)

        # ortak gorunum: renk, kalinlik, opaklik, kesikli, ok ucu, dolgu
        self.mk_box, lb = markup_bar.group()
        self.mk_color = markup_bar.SwatchButton(BLUE, _t("Renk"))
        self.mk_width = spin(QDoubleSpinBox(), 78, _t("Kalınlık (pt)"))
        self.mk_width.setRange(0.25, 20)
        self.mk_width.setSingleStep(0.25)
        self.mk_width.setDecimals(2)
        self.mk_width.setSuffix(" pt")
        self.mk_opacity = spin(QSpinBox(), 70, _t("Opaklık"))
        self.mk_opacity.setRange(5, 100)
        self.mk_opacity.setSuffix(" %")
        self.mk_dashed = tb("mdi6.format-line-style", _t("Kesikli çizgi"))
        self.mk_dash = markup_bar.dash_combo(self.dark)
        self.mk_head = spin(QComboBox(), 92, _t("Ok ucu"))
        for label, key in ((_t("→ Sonda"), "end"), (_t("← Başta"), "start"), (_t("↔ İki uç"), "both"), (_t("— Yok"), "none")):
            self.mk_head.addItem(label, key)
        self.mk_hsize = spin(QComboBox(), 82, _t("Ok ucu boyutu"))
        for label, v in HEAD_SCALES:
            self.mk_hsize.addItem(label, v)
        self.mk_fill_on = tb("mdi6.format-color-fill", _t("Dolgu / arka plan"))
        self.mk_fill = markup_bar.SwatchButton([1.0, 0.9, 0.2], _t("Dolgu rengi"))
        self.mk_border_on = tb("mdi6.checkbox-blank-outline", _t("Kenarlık"))
        self.mk_hlstyle = spin(QComboBox(), 118, _t("Yazı vurgusunun türü (yazının üstünden geçince)"))
        for key, label in pdf_markup.HL_STYLES:
            self.mk_hlstyle.addItem(label, key)
        self.mk_note_sep = markup_bar.vsep(breakable=False)       # notta: ok | kutu
        for w in (self.mk_color, self.mk_width, self.mk_opacity, self.mk_dashed, self.mk_dash, self.mk_head,
                  self.mk_hsize, self.mk_note_sep, self.mk_border_on, self.mk_fill_on, self.mk_fill,
                  self.mk_hlstyle):
            lb.addWidget(w)
        self._mk_box_lay = lb
        l2.addWidget(self.mk_box)

        # numara rozeti
        self.mk_num_box, lnum = markup_bar.group()
        lnum.addWidget(markup_bar.vsep(True))
        self.mk_num = spin(QSpinBox(), 70, _t("Numara (seçili rozetin)"))
        self.mk_num.setRange(0, 999)
        self.mk_nsize = spin(QDoubleSpinBox(), 76, _t("Rozet boyutu (pt)"))
        self.mk_nsize.setRange(8, 96)
        self.mk_nsize.setDecimals(0)
        self.mk_nsize.setSuffix(" pt")
        self.mk_num_text = markup_bar.SwatchButton([1, 1, 1], _t("Rakam rengi"), glyph="1")
        for w in (self.mk_num, self.mk_nsize, self.mk_num_text):
            lnum.addWidget(w)
        l2.addWidget(self.mk_num_box)

        # silgi: ucun boyutu (ekran px: yakinlastirmadan bagimsiz ayni buyuklukte gorunur)
        self.mk_erase_box, lerase = markup_bar.group()
        self.mk_erase = spin(QSpinBox(), 80, _t("Silgi boyutu"))
        self.mk_erase.setRange(3, 40)
        self.mk_erase.setSuffix(" px")
        try:
            v = int(self._settings.value("eraser_px", self.ERASER_PX))
        except (TypeError, ValueError):
            v = self.ERASER_PX
        self._eraser_px = min(40, max(3, v))
        self.mk_erase.setValue(self._eraser_px)
        self.mk_erase.valueChanged.connect(self._mk_set_eraser)
        lerase.addWidget(self.mk_erase)
        l2.addWidget(self.mk_erase_box)

        # not: [ok + kutu] || [yazi | yazi efekti] || [opaklik, hazir] || [aci] || [duzenle, sil]
        self.mk_note_box, ln = markup_bar.group()
        ln.addWidget(markup_bar.vsep(True))
        self.mk_text_color = markup_bar.SwatchButton([0.1, 0.1, 0.1], _t("Yazı rengi"), glyph="A")
        self.mk_font = spin(QComboBox(), 128, _t("Yazı tipi"))
        for display, key in FONT_DISPLAY_NAMES:
            self.mk_font.addItem(display, key)
        self.mk_size = spin(QDoubleSpinBox(), 64, _t("Yazı boyutu"))
        self.mk_size.setRange(5, 96)
        self.mk_size.setSingleStep(1)
        self.mk_size.setDecimals(0)
        self.mk_bold = tb("mdi6.format-bold", _t("Kalın"))
        self.mk_italic = tb("mdi6.format-italic", _t("İtalik"))
        self.mk_shadow = tb("mdi6.box-shadow", _t("Gölge"))
        self.mk_outline = tb("mdi6.format-text-variant-outline",
                             _t("Kontur: harflerin etrafına dış çizgi (renkli zeminde bile okunur)"))
        self.mk_outline_color = markup_bar.SwatchButton([0, 0, 0], _t("Kontur rengi"))
        self.mk_preset = spin(QComboBox(), 96, _t("Hazır görünümler"))
        self.mk_preset.view().setMinimumWidth(250)     # uzun sablon adlari / komutlar sigsin
        self.mk_preset.setMaxVisibleItems(60)          # kaydirmadan hepsi (en alttaki "sil" gizlenmesin)
        self._mk_fill_presets()
        self.btn_mk_edit_text = tb("mdi6.text-box-edit-outline", _t("Yazıyı düzenle (çift tık / F2)"),
                                   checkable=False)
        self.btn_mk_edit_text.clicked.connect(self._mk_edit_text)
        for w in (self.mk_font, self.mk_size, self.mk_bold, self.mk_italic, self.mk_text_color,
                  markup_bar.vsep(), self.mk_shadow, self.mk_outline, self.mk_outline_color):
            ln.addWidget(w)
        l2.addWidget(self.mk_note_box)
        # genel: opaklik (notta tum notu etkiler; ortak kutudan buraya tasinir) + hazir gorunum
        self.mk_note_gen, self._mk_note_gen_lay = markup_bar.group()
        self._mk_note_gen_lay.addWidget(markup_bar.vsep(True))
        self._mk_note_gen_lay.addWidget(self.mk_preset)
        l2.addWidget(self.mk_note_gen)

        # buyutec
        self.mk_mag_box, lm = markup_bar.group()
        lm.addWidget(markup_bar.vsep(True))
        self.mk_mag_mode = spin(QComboBox(), 150, _t("Büyüteç türü"))
        for label, key in MAG_MODES:
            self.mk_mag_mode.addItem(label, key)
        self.mk_zoom = spin(QDoubleSpinBox(), 76, _t("Büyütme oranı"))
        self.mk_zoom.setRange(1.25, 12)
        self.mk_zoom.setSingleStep(0.25)
        self.mk_zoom.setDecimals(2)
        self.mk_zoom.setSuffix(" ×")
        self.btn_mk_mag_text = tb("mdi6.format-text", _t("Etiket ve alt yazı ayarları"), checkable=False,
                                  text=_t("Yazı"))
        for w in (self.mk_mag_mode, self.mk_zoom, self.btn_mk_mag_text):
            lm.addWidget(w)
        l2.addWidget(self.mk_mag_box)
        # buyutec yazi ayarlari: acilir kutu
        self.mk_mag_pop = markup_bar.Popover(self)
        pg = QGridLayout(self.mk_mag_pop)
        pg.setContentsMargins(10, 10, 10, 10)
        pg.setHorizontalSpacing(8)
        pg.setVerticalSpacing(6)
        self.mk_label_on = QCheckBox(_t("Etiket harfi"))
        self.mk_label_on.setToolTip(_t("Kaynak dairenin yanına harf (A, B, C…)"))
        self.mk_label = QLineEdit()
        self.mk_label.setMaxLength(6)
        self.mk_label.setPlaceholderText("A")
        self.mk_label.setFixedWidth(70)
        self.mk_caption_on = QCheckBox(_t("Alt yazı"))
        self.mk_show_scale = QCheckBox(_t("Ölçek (2:1)"))
        self.mk_show_scale.setToolTip(_t("Alt yazının sonuna büyütme oranını ekler; oran değişince güncellenir"))
        self.mk_caption = QLineEdit()
        self.mk_caption.setPlaceholderText(_t("Boş: otomatik \"DETAY A\""))
        self.mk_caption.setMinimumWidth(220)
        self.mk_lfont = QComboBox()
        for display, key in FONT_DISPLAY_NAMES:
            self.mk_lfont.addItem(display, key)
        self.mk_lsize = QDoubleSpinBox()
        self.mk_lsize.setRange(5, 72)
        self.mk_lsize.setDecimals(0)
        self.mk_lsize.setSuffix(" pt")
        self.mk_lbold = QCheckBox(_t("Kalın"))
        self.mk_lcolor = markup_bar.SwatchButton(BLUE, _t("Yazı rengi"), glyph="A")
        pg.addWidget(self.mk_label_on, 0, 0)
        pg.addWidget(self.mk_label, 0, 1)
        pg.addWidget(self.mk_caption_on, 1, 0)
        pg.addWidget(self.mk_show_scale, 1, 1)
        pg.addWidget(self.mk_caption, 2, 0, 1, 2)
        pg.addWidget(self.mk_lfont, 3, 0)
        pg.addWidget(self.mk_lsize, 3, 1)
        pg.addWidget(self.mk_lbold, 4, 0)
        pg.addWidget(self.mk_lcolor, 4, 1)
        self.btn_mk_mag_text.clicked.connect(lambda: self.mk_mag_pop.show_under(self.btn_mk_mag_text))

        # bulaniklastir
        self.mk_blur_box, lz = markup_bar.group()
        self.blur_mode = spin(QComboBox(), 104, _t("Yöntem"))
        for key, label in pdf_blur.MODES:
            self.blur_mode.addItem(label, key)
        self.blur_level = QSlider(Qt.Horizontal)
        self.blur_level.setRange(*pdf_blur.LEVELS)
        self.blur_level.setPageStep(1)
        self.blur_level.setFixedWidth(110)
        self.blur_level.setToolTip(_t("Güç"))
        self.lbl_blur_level = markup_bar.small_label("5")
        self.lbl_blur_level.setStyleSheet("padding: 0 2px;")
        self.lbl_blur_level.setFixedWidth(24)
        self.lbl_blur_level.setAlignment(Qt.AlignCenter)
        self.lbl_blur_level.setToolTip(_t("Güç"))
        self.btn_blur_apply = tb("mdi6.stamper", _t("Şimdi kalıcı uygula: alttaki içerik silinir "
                                 "(kaydedince zaten otomatik uygulanır; Ctrl+Z ile geri alınabilir)"),
                                 checkable=False)
        self.btn_blur_apply.clicked.connect(self._blur_apply_selected)
        for w in (self.blur_mode, self.blur_level, self.lbl_blur_level, self.btn_blur_apply):
            lz.addWidget(w)
        l2.addWidget(self.mk_blur_box)

        # dondurme: aci kutusu (kutu, daire, bulanik, not). Oklar yok: ▾ surgu ve tutamac yeterli.
        self.mk_rot_box, lr = markup_bar.group()
        self.mk_rot_sep = markup_bar.vsep(True, breakable=False)
        lr.addWidget(self.mk_rot_sep)
        self.mk_angle = spin(QSpinBox(), 74, _t("Döndürme açısı (saat yönünde) · tutamaç: üstteki "
                                            "yuvarlak nokta, Shift: 15° adım"))
        self.mk_angle.setRange(-180, 180)
        self.mk_angle.setWrapping(True)
        self.mk_angle.setSuffix("°")
        lr.addWidget(self.mk_angle)
        l2.addWidget(self.mk_rot_box)
        self.mk_angle.valueChanged.connect(self._mk_set_angle)

        # sil
        self.mk_del_sep = markup_bar.vsep(True, breakable=False)
        l2.addWidget(self.mk_del_sep)
        l2.addWidget(self.btn_mk_edit_text)
        self.btn_mk_delete = tb("mdi6.delete-outline", _t("Sil (Delete)"), checkable=False)
        self.btn_mk_delete.setObjectName("mkToolDanger")
        self.btn_mk_delete.clicked.connect(self.delete_selected)
        l2.addWidget(self.btn_mk_delete)

        # iki satir: tum modlar ayni satirlari kullanir (Metin/Cizgi/Yeni metin seritleri
        # main.py'de eklenir). Satir yukseklikleri sabitlenir -> mod degisince sayfa kaymaz.
        self._bar_rows, self._bar_row_widgets = [], []
        for row in (row1, row2):
            rc = QWidget()
            rc.setMinimumWidth(1)              # genis serit pencereyi genisletmesin (tasarsa kirpilir)
            h = QHBoxLayout(rc)
            h.setContentsMargins(0, 0, 0, 0)
            h.addStretch()
            h.addWidget(row)
            h.addStretch()
            hv.addWidget(rc)
            self._bar_rows.append(h)
            self._bar_row_widgets.append(rc)
        host.setMinimumWidth(1)

        # not yazisi: sayfanin ustunde yazilir (tuvalin cocugu; kaydirinca birlikte kayar)
        self.mk_text = QTextEdit(self.canvas)
        self.mk_text.setObjectName("mkInlineText")
        self.mk_text.setAcceptRichText(False)
        self.mk_text.setPlaceholderText(_t("Not yazısı…"))
        self.mk_text.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mk_text.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mk_text.hide()
        self._mk_editor_keys = _EditorKeys(self)
        self.mk_text.installEventFilter(self._mk_editor_keys)

        for w in (self.mk_width, self.mk_opacity, self.mk_size, self.mk_zoom, self.mk_lsize,
                  self.blur_level, self.mk_nsize):
            w.valueChanged.connect(self._mk_on_style)
        self.mk_num.valueChanged.connect(self._mk_set_number)
        for w in (self.mk_dashed, self.mk_border_on, self.mk_fill_on, self.mk_bold, self.mk_italic,
                  self.mk_shadow, self.mk_outline, self.mk_label_on, self.mk_caption_on,
                  self.mk_show_scale, self.mk_lbold):
            w.toggled.connect(self._mk_on_style)
        for w in (self.mk_head, self.mk_hsize, self.mk_font, self.mk_mag_mode, self.mk_lfont,
                  self.blur_mode, self.mk_dash):
            w.currentIndexChanged.connect(self._mk_on_style)
        self.mk_hlstyle.currentIndexChanged.connect(self._mk_hlstyle_changed)
        for b in (self.mk_color, self.mk_fill, self.mk_text_color, self.mk_outline_color, self.mk_lcolor,
                  self.mk_num_text):
            b.changed.connect(self._mk_on_style)
        self.mk_preset.activated.connect(self._mk_preset_chosen)
        self.mk_dashed.toggled.connect(lambda _=False: (self._mk_dash_visibility(), self._settle_bars()))
        self.mk_text.textChanged.connect(self._mk_on_text)
        self.mk_label.editingFinished.connect(self._mk_apply_label)
        self.mk_caption.editingFinished.connect(self._mk_apply_label)
        # ust serit sayi kutulari: oklar yerine ▾ surgu (deger yazilabilir, tekerlek calisir)
        for sp_, lo, hi, sc, wd in ((self.mk_width, 0.25, 20, 4, 90), (self.mk_opacity, 5, 100, 1, 80),
                                    (self.mk_size, 5, 96, 1, 76), (self.mk_zoom, 1.25, 12, 4, 88),
                                    (self.mk_angle, -180, 180, 1, 82), (self.mk_nsize, 8, 96, 1, 84),
                                    (self.mk_erase, 3, 40, 1, 80)):
            sp_.setFixedWidth(wd)
            self._slider(sp_, lo, hi, sc)
        self.mk_bar_host = host
        host.hide()
        return host

    def _mk_recolor_icons(self):
        markup_bar.recolor_dash_combo(self.mk_dash, self.dark)
        if getattr(self, "cmb_dash", None) is not None:
            markup_bar.recolor_dash_combo(self.cmb_dash, self.dark)
        for b in self._mk_bar_buttons:
            ic_ = markup_bar.icon(b._icon_name, self.dark, getattr(b, "_on_white", True))
            if not ic_.isNull():
                b.setIcon(ic_)

    def _slider(self, spin, lo, hi, scale=1.0):
        """Ust serit sayi kutusuna ▾ surgu ekle (tema rengi de takip edilir)."""
        self._mk_bar_buttons.append(markup_bar.attach_slider(spin, lo, hi, scale, self.dark))

    def _mk_color_buttons(self):
        return (self.mk_color, self.mk_fill, self.mk_text_color, self.mk_outline_color, self.mk_lcolor,
                self.mk_num_text)

    def _mk_hide_panel(self):
        self.w_mk_tools.hide()
        self.w_mk_options.hide()
        self._mk_close_editor()

    def _mk_sel(self):
        if self.sel_markup is None or not self.engine.doc:
            return None
        return self.engine.markup(self.current_page, self.sel_markup)

    def _mk_panel_kind(self):
        m = self._mk_sel()
        if m is not None:
            return m["kind"]
        return TOOL_KIND.get(self.mk_tool)

    def _mk_style_key(self):
        """Son kullanilan ayarlarin anahtari: ucsuz ok = 'line', kalem / fosforlu / imza ayri."""
        m = self._mk_sel()
        if m is not None:
            return style_key(m["kind"], m["p"])
        if self.mk_tool in ("line", "highlight"):
            return self.mk_tool
        if self.mk_tool == "pen":
            return "ink"
        return TOOL_KIND.get(self.mk_tool)

    def _markup_refresh_panel(self):
        self.w_mk_options.unwrap()             # gorunurlukler degismeden once tek satira
        self.mk_bar_host.show()
        self.w_mk_tools.show()
        m = self._mk_sel()
        kind = self._mk_panel_kind()
        # ayar satiri: Sec araci + secim yokken gosterecek bir sey yok (yeri korunur)
        erasing = self.mk_tool == "eraser" and m is None
        self.w_mk_options.setVisible(kind is not None or erasing)
        self.mk_erase_box.setVisible(erasing)
        self.mk_box.setVisible(kind is not None and kind != "blur")
        self.mk_note_box.setVisible(kind == "note")
        self.mk_note_gen.setVisible(kind == "note")
        self.mk_num_box.setVisible(kind == "number")     # (asagidaki erken donusten once: silgi vb.)
        self.mk_mag_box.setVisible(kind == "magnifier")
        self.mk_blur_box.setVisible(kind == "blur")
        self.btn_blur_apply.setVisible(m is not None and kind == "blur")
        rot_ok = m is not None and kind in pdf_markup.ROTATABLE
        self.mk_rot_box.setVisible(rot_ok)
        if rot_ok:                             # tutamacla dondurulunce de kutu guncel kalsin
            a = pdf_markup.angle_of(m["p"])
            self.mk_angle.blockSignals(True)
            self.mk_angle.setValue(int(round(a - 360 if a > 180 else a)))
            self.mk_angle.blockSignals(False)
        self.btn_mk_delete.setVisible(m is not None)
        self.btn_mk_edit_text.setVisible(m is not None and kind == "note")
        self.mk_del_sep.setVisible(m is not None and kind is not None and kind != "note")
        self.mk_rot_sep.setVisible(kind != "note")   # notta: hazir, aci, duzenle, sil bir arada
        self._mk_place_opacity(kind == "note")
        if kind == "blur":
            self.blur_level.setEnabled(self.blur_mode.currentData() != "solid")
            self.lbl_blur_level.setText(str(self.blur_level.value()))
        if kind is None or kind == "blur":
            self._mk_load_if_needed(kind, m)
            return
        is_note, is_arrow, is_mag = kind == "note", kind == "arrow", kind == "magnifier"
        is_tx, is_num, is_img = kind == "texthl", kind == "number", kind == "image"
        simple = kind in ("ink", "texthl", "number", "image")
        hl = self._mk_style_key() == "highlight"
        self.mk_color.setVisible(not is_img)
        self.mk_width.setVisible(not (is_tx or is_num or is_img))
        self.mk_width.setToolTip(_t("Kalem kalınlığı (pt)") if hl else _t("Kalınlık (pt)"))
        self.mk_hlstyle.setVisible(hl and not (m is not None and kind == "ink"))
        self.mk_num.setEnabled(m is not None)
        self.mk_color.setToolTip(_t("Kenarlık / ok rengi") if is_note else (_t("Rozet rengi") if is_num else _t("Renk")))
        self.mk_head.setVisible(is_arrow)
        self.mk_hsize.setVisible(is_arrow or is_note)
        self.mk_dashed.setVisible(not is_note and not simple)
        self.mk_dashed.setToolTip(_t("Kaynak daire kesikli") if is_mag else _t("Kesikli çizgi"))
        self.mk_border_on.setVisible(is_note)
        self.mk_fill_on.setVisible(not is_arrow and not is_mag and not simple)
        self.mk_fill.setVisible(not is_arrow and not is_mag and not simple)
        self.mk_fill_on.setToolTip(_t("Arka plan") if is_note else _t("Dolgu"))
        self.mk_note_sep.setVisible(is_note)
        self._mk_load_if_needed(kind, m)
        if is_mag:
            self._mag_enable_fields(m)
        else:
            self.mk_dashed.setEnabled(True)
        self._mk_dash_visibility()

    def _mk_place_opacity(self, note):
        """Notta opaklik tum notu (ok, kutu, yazi) etkiler: 'genel' grubuna gecer;
        diger nesnelerde renk/kalinligin yaninda durur."""
        target, index = (self._mk_note_gen_lay, 1) if note else (self._mk_box_lay, 2)
        if target.indexOf(self.mk_opacity) >= 0:
            return
        other = self._mk_box_lay if note else self._mk_note_gen_lay
        other.removeWidget(self.mk_opacity)
        target.insertWidget(index, self.mk_opacity)
        self.mk_opacity.show()

    def _mk_dash_visibility(self):
        self.mk_dash.setVisible(self.mk_dashed.isVisible() and self.mk_dashed.isChecked()
                                and self.mk_dashed.isEnabled())

    def _mk_load_if_needed(self, kind, m):
        # kontrolleri yalnizca secim/arac DEGISINCE doldur (yazarken imlec kacmasin)
        if kind is None:
            return
        skey = self._mk_style_key()
        token = ("m", m["id"]) if m else ("t", skey)
        if token != self._mk_loaded:
            self._mk_loaded = token
            if m:
                self._mk_load(kind, style_from(kind, m["p"]), m["p"].get("text"), m["p"])
            else:
                self._mk_load(kind, self.mk_style[skey], None, {})

    def _mag_enable_fields(self, m):
        detail = self.mk_mag_mode.currentData() == "detail"
        self.mk_dashed.setEnabled(detail)
        self.mk_label_on.setEnabled(detail)
        self.mk_label.setEnabled(detail and self.mk_label_on.isChecked() and m is not None)
        self.mk_caption.setEnabled(self.mk_caption_on.isChecked() and m is not None)
        self.mk_caption.setPlaceholderText(_t('Boş: otomatik "DETAY A"') if detail else _t("Yazı (isteğe bağlı)"))

    def _mk_load(self, kind, st, text=None, P=None):
        self._mk_loading = True
        try:
            self.mk_mag_mode.setCurrentIndex(max(self.mk_mag_mode.findData(st.get("mode", "detail")), 0))
            self.mk_zoom.setValue(float(st.get("zoom", 2.0)))
            self.mk_label_on.setChecked(bool(st.get("label_on", True)))
            self.mk_caption_on.setChecked(bool(st.get("caption_on", True)))
            self.mk_show_scale.setChecked(bool(st.get("show_scale", True)))
            self.mk_lfont.setCurrentIndex(max(self.mk_lfont.findData(st.get("label_font", "Arial")), 0))
            self.mk_lsize.setValue(float(st.get("label_size", 10.0)))
            self.mk_lbold.setChecked(bool(st.get("label_bold", True)))
            self.mk_lcolor.set_rgb(st.get("label_color") or BLUE)
            if P is not None:
                self.mk_label.setText(P.get("label", "") if kind == "magnifier" else "")
                self.mk_caption.setText(P.get("caption", "") if kind == "magnifier" else "")
            self.blur_mode.setCurrentIndex(max(self.blur_mode.findData(st.get("bmode", "blur")), 0))
            self.blur_level.setValue(int(st.get("level", 5)))
            self.lbl_blur_level.setText(str(self.blur_level.value()))
            self.mk_color.set_rgb(st.get("color", BLUE))
            self.mk_width.setValue(st.get("width", 1.5))
            self.mk_opacity.setValue(round(st.get("opacity", 1.0) * 100))
            self.mk_dashed.setChecked(bool(st.get("dashed")))
            self.mk_dash.setCurrentIndex(max(self.mk_dash.findData(st.get("dash") or "dash_m"), 0))
            self.mk_head.setCurrentIndex(max(self.mk_head.findData(st.get("head", "end")), 0))
            hs = st.get("head_scale", 1.0)
            self.mk_hsize.setCurrentIndex(min(range(len(HEAD_SCALES)),
                                              key=lambda i: abs(HEAD_SCALES[i][1] - hs)))
            self.mk_fill_on.setChecked(bool(st.get("fill_on")))
            self.mk_fill.set_rgb(st.get("fill_color", [1, 0.9, 0.2]))
            self.mk_border_on.setChecked(bool(st.get("border_on", False)))
            self.mk_text_color.set_rgb(st.get("text_color", [0.1, 0.1, 0.1]))
            self.mk_size.setValue(st.get("size", 11.0))
            self.mk_font.setCurrentIndex(max(self.mk_font.findData(st.get("font", "Arial")), 0))
            self.mk_bold.setChecked(bool(st.get("bold")))
            self.mk_italic.setChecked(bool(st.get("italic")))
            self.mk_shadow.setChecked(bool(st.get("shadow")))
            self.mk_outline.setChecked(bool(st.get("outline")))
            self.mk_outline_color.set_rgb(st.get("outline_color", [0, 0, 0]))
            self.mk_hlstyle.setCurrentIndex(max(self.mk_hlstyle.findData(st.get("hlstyle", "highlight")), 0))
            self.mk_nsize.setValue(float(st.get("nsize", 20.0)))
            self.mk_num_text.set_rgb(st.get("text_color", [1, 1, 1]) if kind == "number"
                                     else DEFAULT_STYLE["number"]["text_color"])
            if kind == "number":
                self.mk_num.setValue(int((P or {}).get("n", 0) or 0))
            if text is not None and self.mk_text.toPlainText() != text:
                self.mk_text.setPlainText(text)
        finally:
            self._mk_loading = False
        if kind == "note":                     # secilen notun ayarlari bir sablonla ayniysa adi
            self._mk_sync_preset(self._mk_match_preset())

    def _mk_read(self):
        return {"color": list(self.mk_color.rgb), "width": self.mk_width.value(),
                "opacity": self.mk_opacity.value() / 100, "dashed": self.mk_dashed.isChecked(),
                "dash": self.mk_dash.currentData(),
                "head": self.mk_head.currentData(), "head_scale": self.mk_hsize.currentData(),
                "fill_on": self.mk_fill_on.isChecked(), "fill_color": list(self.mk_fill.rgb),
                "border_on": self.mk_border_on.isChecked(),
                "text_color": list(self.mk_text_color.rgb), "size": self.mk_size.value(),
                "font": self.mk_font.currentData(), "bold": self.mk_bold.isChecked(),
                "italic": self.mk_italic.isChecked(), "shadow": self.mk_shadow.isChecked(),
                "outline": self.mk_outline.isChecked(),
                "outline_color": list(self.mk_outline_color.rgb),
                "mode": self.mk_mag_mode.currentData(), "zoom": self.mk_zoom.value(),
                "label_on": self.mk_label_on.isChecked(), "caption_on": self.mk_caption_on.isChecked(),
                "show_scale": self.mk_show_scale.isChecked(), "label_font": self.mk_lfont.currentData(),
                "label_size": self.mk_lsize.value(), "label_bold": self.mk_lbold.isChecked(),
                "label_color": list(self.mk_lcolor.rgb),
                "bmode": self.blur_mode.currentData(), "level": self.blur_level.value(),
                "hlstyle": self.mk_hlstyle.currentData(), "nsize": self.mk_nsize.value(),
                **({"text_color": list(self.mk_num_text.rgb)} if self._mk_panel_kind() == "number" else {})}

    def _mk_on_style(self, *_):
        if self._mk_loading:
            return
        kind = self._mk_panel_kind()
        if kind is None:
            return
        st = self._mk_read()
        self.mk_style[self._mk_style_key()] = st
        self.save_style_setting("markup_style", self.mk_style)
        if kind == "note":                     # sablon uygulandiktan sonra HERHANGI bir degisiklik: "Hazir…"
            self._mk_sync_preset(getattr(self, "_mk_applying_preset", None))
        if kind == "blur":
            self.blur_level.setEnabled(st["bmode"] != "solid")
            self.lbl_blur_level.setText(str(st["level"]))
            self.canvas.update()
        m = self._mk_sel()
        if m is not None:
            geom = geom_from(kind, m["p"])
            if kind == "magnifier":
                geom = self._mag_geom_for(m["p"], st, geom)
            P = params_from(kind, st, geom)
            self.engine.update_markup(self.current_page, m["id"], P, group=("mkstyle", m["id"]))
            self._mk_changed()
        if kind == "magnifier":
            self._refresh_panel()             # tur/etiket degisince alanlarin etkinligi

    # ---------------------------------------------- buyutec yardimcilari
    def _page_box(self):
        """Sayfanin donmemis koordinatlardaki kutusu (isaretlemeler bu uzayda)."""
        page = self.engine.doc[self.current_page]
        return (page.rect * page.derotation_matrix).normalize()

    def _mag_next_label(self):
        used = {m["p"].get("label") for m in self.engine.get_markups(self.current_page)
                if m["kind"] == "magnifier"}
        for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            if c not in used:
                return c
        return "A"

    def _mag_place(self, S, rs, R):
        """Detay dairesi icin kaynagin yakininda sayfaya sigan bir yer."""
        pr = self._page_box()
        dist = rs + R + 28
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1), (0.7071, 0.7071), (-0.7071, 0.7071),
                (0.7071, -0.7071), (-0.7071, -0.7071))
        for dx, dy in dirs:
            D = fitz.Point(S.x + dx * dist, S.y + dy * dist)
            if pr.contains(fitz.Rect(D.x - R - 4, D.y - R - 4, D.x + R + 4, D.y + R + 20)):
                return D
        return fitz.Point(min(max(S.x + dist, pr.x0 + R), pr.x1 - R),
                          min(max(S.y, pr.y0 + R), pr.y1 - R))

    def _mag_geom_for(self, P, st, geom):
        """Stil degisince geometriyi uyarla: tur degisimi (detay <-> yerinde) ve etiket."""
        geom = dict(geom)
        old, new = P.get("mode", "detail"), st.get("mode", "detail")
        S = fitz.Point(P["src"])
        if old != new:
            if new == "lens":                 # kaynak dairenin biraz buyugu kadar mercek
                geom["r"] = max(float(P["r"]) * 1.5, 15.0)
            else:
                rs = max(float(P["r"]) / 1.5, 8.0)
                geom["r"] = rs
                D = self._mag_place(S, rs, rs * st.get("zoom", 2.0))
                geom["dst"] = [D.x, D.y]
        if new == "detail" and not geom.get("label"):
            geom["label"] = self._mag_next_label()
        return geom

    HL_YELLOW = [1.0, 0.85, 0.0]
    LINE_RED = [0.86, 0.15, 0.15]

    def _mk_hlstyle_changed(self, *_):
        """Vurgu <-> alti/ustu cizili: varsayilan sari cizgide neredeyse gorunmez;
        renk hala varsayilansa uygun olana gec (kullanici rengini sectiyse dokunma)."""
        if not self._mk_loading:
            line = self.mk_hlstyle.currentData() in ("underline", "strike")
            col = [round(c, 2) for c in self.mk_color.rgb]
            self._mk_loading = True
            try:
                if line and col == [round(c, 2) for c in self.HL_YELLOW]:
                    self.mk_color.set_rgb(self.LINE_RED)
                    self.mk_opacity.setValue(100)
                elif not line and col == [round(c, 2) for c in self.LINE_RED]:
                    self.mk_color.set_rgb(self.HL_YELLOW)
                    self.mk_opacity.setValue(50)
            finally:
                self._mk_loading = False
        self._mk_on_style()

    def _mk_set_number(self, n):
        m = self._mk_sel()
        if self._mk_loading or m is None or m["kind"] != "number" or int(m["p"].get("n", 0)) == n:
            return
        P = dict(m["p"])
        P["n"] = int(n)
        self.engine.update_markup(self.current_page, m["id"], P, group=("mknum", m["id"]))
        self._mk_changed()

    def _mk_apply_label(self):
        """Etiket harfi / alt yazi kutusu duzenlendi."""
        m = self._mk_sel()
        if m is None or m["kind"] != "magnifier":
            return
        label = self.mk_label.text().strip() or m["p"].get("label", "")
        caption = self.mk_caption.text().strip()
        if label == m["p"].get("label", "") and caption == (m["p"].get("caption") or ""):
            return
        P = dict(m["p"])
        P["label"], P["caption"] = label, caption
        self.engine.update_markup(self.current_page, m["id"], P)
        self._mk_changed()

    def _blur_apply_selected(self):
        m = self._mk_sel()
        if m is None or m["kind"] != "blur":
            return
        self.engine.finalize_blurs(self.current_page, m["id"])
        self.sel_markup = None
        self.after_edit()
        self.status(_t("Bulanık alan sayfaya işlendi; alttaki içerik silindi. (Geri almak: Ctrl+Z)"))

    def _mk_on_text(self):
        if not self._mk_loading and self._mk_sel() is not None:
            self._mk_text_timer.start()        # her tusta degil, yazmaya ara verince uygula
            if self.mk_text.isVisible():
                self._mk_position_editor()     # yazdikca kutu buyusun

    def _mk_apply_text(self):
        m = self._mk_sel()
        if m is None or m["kind"] != "note":
            return
        P = dict(m["p"])
        P["text"] = self.mk_text.toPlainText()
        if P["text"] == m["p"].get("text"):
            return
        self.engine.update_markup(self.current_page, m["id"], P, group=("mktext", m["id"]))
        self._mk_changed()

    # ---------------------------------------------- hazir / kendi sablonlarim (not)
    def _mk_user_presets(self):
        """Kullanicinin kaydettigi not sablonlari {ad: ayarlar} (kapatip acinca da kalir)."""
        try:
            data = json.loads(self._settings.value("note_presets", "{}", type=str) or "{}")
            return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _mk_save_user_presets(self, data):
        try:
            self._settings.setValue("note_presets", json.dumps(data, ensure_ascii=False))
        except Exception:
            pass

    def _mk_fill_presets(self, keep=None):
        """Liste: Hazir… | yerlesik sablonlar | kendi sablonlarim | kaydet / sil komutlari.
        Oge verisi: 'b:ad' yerlesik, 'u:ad' kendi, '@save' / '@delete' komut."""
        cb = self.mk_preset
        cb.blockSignals(True)
        cb.clear()
        cb.addItem(_t("Hazır…"), None)
        for name in NOTE_PRESETS:
            cb.addItem(name, "b:" + name)
        user = self._mk_user_presets()
        if user:
            cb.insertSeparator(cb.count())
            for name in user:
                cb.addItem("★ " + name, "u:" + name)
        cb.insertSeparator(cb.count())
        cb.addItem(_t("Bu görünümü şablon olarak kaydet…"), "@save")
        if user:
            cb.addItem(_t("Kendi şablonunu sil…"), "@delete")
        cb.setCurrentIndex(max(cb.findData(keep), 0) if keep else 0)
        cb.blockSignals(False)

    def _mk_preset_chosen(self, index):
        key = self.mk_preset.itemData(index)
        if key == "@save":
            self._mk_save_preset()
        elif key == "@delete":
            self._mk_delete_preset()
        elif key:
            self._mk_preset(key)               # kutuda adi kalir
        else:
            self._mk_sync_preset(None)

    def _mk_sync_preset(self, key):
        """Hazir gorunum kutusu: sablon adi ya da (degistirildiyse / yoksa) 'Hazir…'."""
        idx = max(self.mk_preset.findData(key), 0) if key else 0
        if self.mk_preset.currentIndex() != idx:
            self.mk_preset.blockSignals(True)
            self.mk_preset.setCurrentIndex(idx)
            self.mk_preset.blockSignals(False)

    def _mk_preset_values(self, key):
        if not key:
            return None
        if key.startswith("b:"):
            return NOTE_PRESETS.get(key[2:])
        if key.startswith("u:"):
            return self._mk_user_presets().get(key[2:])
        return None

    def _mk_match_preset(self):
        """Not secilince: ayarlari bir sablonla ayni mi (once kendi sablonlarim: onlar tam
        gorunumu tanimlar; sonra yerlesikler: onlar sadece birkac ayari)."""
        st = self._mk_read()

        def same(a, b):
            if isinstance(b, (list, tuple)):
                return (isinstance(a, (list, tuple)) and len(a) == len(b)
                        and all(abs(float(x) - float(y)) < 0.01 for x, y in zip(a, b)))
            if isinstance(b, float) or isinstance(a, float):
                try:
                    return abs(float(a) - float(b)) < 0.01
                except (TypeError, ValueError):
                    return False
            return a == b
        keys = ["u:" + n for n in self._mk_user_presets()] + ["b:" + n for n in NOTE_PRESETS]
        for key in keys:
            preset = self._mk_preset_values(key) or {}
            if preset and all(same(st.get(k), v) for k, v in preset.items()):
                return key
        return None

    def _mk_preset(self, key):
        values = self._mk_preset_values(key)
        if not values:
            self._mk_sync_preset(None)
            return
        st = self._mk_read()
        st.update(values)
        self._mk_load("note", st)
        self._mk_applying_preset = key
        try:
            self._mk_on_style()
        finally:
            self._mk_applying_preset = None
        self._mk_sync_preset(key)

    def _mk_save_preset(self):
        """Notun su anki gorunumunu (renk, kalinlik, kutu, yazi, efektler) adla kaydet."""
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, _t("Şablon olarak kaydet"),
                                        _t("Şablonun adı:"), text=_t("Şablonum"))
        name = (name or "").strip()
        if not ok or not name:
            self._mk_sync_preset(self._mk_match_preset())
            return
        data = self._mk_user_presets()
        if name in data and QMessageBox.question(
                self, _t("Şablon olarak kaydet"),
                _t("\"{name}\" adında bir şablon zaten var. Üzerine yazılsın mı?", name=name)) != QMessageBox.Yes:
            self._mk_sync_preset(self._mk_match_preset())
            return
        st = self._mk_read()
        data[name] = {k: st[k] for k in NOTE_STYLE_KEYS if k in st}
        self._mk_save_user_presets(data)
        self._mk_fill_presets(keep="u:" + name)
        self.status(_t("\"{name}\" şablonu kaydedildi — not menüsündeki listeden her zaman seçebilirsiniz.",
                       name=name))

    def _mk_delete_preset(self):
        from PySide6.QtWidgets import QInputDialog
        data = self._mk_user_presets()
        names = list(data)
        if not names:
            self._mk_sync_preset(None)
            return
        name, ok = QInputDialog.getItem(self, _t("Kendi şablonunu sil"), _t("Silinecek şablon:"),
                                        names, 0, False)
        if ok and name in data and QMessageBox.question(
                self, _t("Kendi şablonunu sil"), _t("\"{name}\" şablonu silinsin mi?", name=name)) == QMessageBox.Yes:
            data.pop(name)
            self._mk_save_user_presets(data)
            self.status(_t("\"{name}\" şablonu silindi.", name=name))
        self._mk_fill_presets()
        self._mk_sync_preset(self._mk_match_preset())

    def _mk_changed(self):
        """Isaretleme degisti: sayfayi ve kucuk resmi yenile (paneli bastan kurmadan)."""
        self.render_current_page()
        self._update_thumb(self.current_page)
        self._update_title()
        self.canvas.update()

    def set_markup_tool(self, tool):
        """Arac degisir; secim birakilir. Arac, bir sonraki secime kadar ACIK kalir:
        var olan nesneye basinca o nesne secilir/tasinir, bosta surukleyince cizilir."""
        self._mk_close_editor()
        self.mk_tool = tool
        self.mk_tool_btns[tool].setChecked(True)
        self.sel_markup = None
        self.drag = None
        self._refresh_panel()
        self.update_cursor()
        self.canvas.update()

    def _mk_select(self, mid):
        if mid != self.sel_markup:
            self._mk_close_editor()
        self.sel_markup = mid
        self._refresh_panel()
        self.canvas.update()

    def _mk_after_create(self, mid, msg):
        """Yeni nesne: hemen secili (tutamaclari gorunur), arac acik kalir."""
        self.sel_markup = mid
        self._mk_loaded = None
        self.after_edit()
        self.status(msg)

    # ---------------------------------------------- not yazisi (sayfanin ustunde)
    def _mk_edit_text(self, select_all=False):
        m = self._mk_sel()
        if m is None or m["kind"] != "note":
            return
        self._mk_loading = True
        try:
            self.mk_text.setPlainText(m["p"].get("text", ""))
        finally:
            self._mk_loading = False
        self._mk_position_editor()
        self.mk_text.show()
        self.mk_text.raise_()
        self.mk_text.setFocus()
        if select_all:
            self.mk_text.selectAll()
        else:
            c = self.mk_text.textCursor()
            c.movePosition(c.MoveOperation.End)
            self.mk_text.setTextCursor(c)

    def _mk_position_editor(self):
        m = self._mk_sel()
        if m is None or m["kind"] != "note":
            self.mk_text.hide()
            return
        P = m["p"]
        box = pdf_markup.note_geometry(P)[0]
        r = self.canvas.rect_px(box)
        f = QFont(P.get("font") or "Arial")
        f.setPixelSize(max(11, min(48, round(P["size"] * self.canvas.zoom))))
        f.setBold(bool(P.get("bold")))
        f.setItalic(bool(P.get("italic")))
        self.mk_text.setFont(f)
        fm = QFontMetrics(f)
        lines = (self.mk_text.toPlainText() or " ").split("\n")
        w = max(r.width() + 16, max(fm.horizontalAdvance(l) for l in lines) + 34, 170)
        h = fm.lineSpacing() * max(1, len(lines)) + 18
        self.mk_text.setGeometry(int(r.x()) - 6, int(r.y()) - 6, int(w), int(h))

    def _mk_close_editor(self):
        ed = getattr(self, "mk_text", None)
        if ed is None or not ed.isVisible():
            return
        if self._mk_text_timer.isActive():
            self._mk_text_timer.stop()
            self._mk_apply_text()
        ed.hide()
        self.canvas.setFocus()

    # ---------------------------------------------- klavye
    def _mk_key(self, ev):
        """Isaretle modunun tuslari. Islendi ise True."""
        key, mods = ev.key(), ev.modifiers()
        plain = not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))
        if plain and key == Qt.Key_S:
            self._mk_sign_menu()
            return True
        if plain and key == Qt.Key_G:
            self._mk_add_image()
            return True
        if plain and key in KEY_TOOLS:
            self.set_markup_tool(KEY_TOOLS[key])
            return True
        m = self._mk_sel()
        if m is not None and m["kind"] == "note" and key in (Qt.Key_F2, Qt.Key_Return, Qt.Key_Enter):
            self._mk_edit_text()
            return True
        if m is not None and key == Qt.Key_D and mods & Qt.ControlModifier:
            self._mk_duplicate()
            return True
        return False

    # ---------------------------------------------- cogalt / sira
    def _mk_duplicate(self):
        m = self._mk_sel()
        if m is None or m["kind"] == "texthl":
            return
        off = self._tol(14)
        img = self.engine.markup_image(self.current_page, m["id"]) if m["kind"] == "image" else None
        P = pdf_markup.moved(m, off, off, keep_target=False)
        if m["kind"] == "number":
            P["n"] = self.engine.next_number(self.current_page)
        mid = self.engine.add_markup(self.current_page, m["kind"], P, img=img)
        self._mk_after_create(mid, _t("Çoğaltıldı. (Ctrl+D)"))

    def _mk_to_front(self):
        m = self._mk_sel()
        if m is not None:
            self.engine.update_markup(self.current_page, m["id"], m["p"])
            self.after_edit()
            self.status(_t("Öne getirildi."))

    def _mk_to_back(self):
        m = self._mk_sel()
        if m is not None and self.engine.markup_to_back(self.current_page, m["id"]):
            self.after_edit()
            self.status(_t("Arkaya gönderildi."))

    # ============================================================ geometri yardimcilari
    @staticmethod
    def _rect_handles(r):
        cx, cy = (r.x0 + r.x1) / 2, (r.y0 + r.y1) / 2
        return [("tl", fitz.Point(r.x0, r.y0)), ("tr", fitz.Point(r.x1, r.y0)),
                ("br", fitz.Point(r.x1, r.y1)), ("bl", fitz.Point(r.x0, r.y1)),
                ("l", fitz.Point(r.x0, cy)), ("r", fitz.Point(r.x1, cy)),
                ("t", fitz.Point(cx, r.y0)), ("b", fitz.Point(cx, r.y1))]

    def _mk_handles(self):
        m = self._mk_sel()
        if m is None:
            return []
        P, k = m["p"], m["kind"]
        if k == "magnifier":
            S, rs, D, R = pdf_markup.mag_geometry(P)
            if P.get("mode") == "lens":
                return [("mr", fitz.Point(S.x + R, S.y))]
            return [("sr", fitz.Point(S.x + rs, S.y)), ("dr", fitz.Point(D.x + R, D.y))]
        if k == "arrow":
            a, b = fitz.Point(P["p1"]), fitz.Point(P["p2"])
            m = fitz.Point(P["bend"]) if P.get("bend") else (a + b) * 0.5
            return [("bend", m), ("p1", a), ("p2", b)]
        if k == "ink":
            r = pdf_markup.bbox(m)
            hs = self._rect_handles(r)
            if r.height < 0.5:                 # duz yatay cizgi: sadece yan tutamaclar
                hs = [h for h in hs if h[0] in ("l", "r")]
            elif r.width < 0.5:
                hs = [h for h in hs if h[0] in ("t", "b")]
            return hs
        if k == "number":
            c = fitz.Point(P["pos"])
            return [("nr", fitz.Point(c.x + P.get("size", 20) / 2, c.y))]
        if k == "texthl":
            return []
        if k == "note":
            hs = [("rot", self._mk_rot_handle_pt(m))]
            ld = pdf_markup.note_leader(P)
            if ld is None:
                return hs + ([("target", fitz.Point(P["target"]))] if P.get("target") else [])
            s, t, bend = ld
            return hs + [("bend", bend if bend is not None else (s + t) * 0.5), ("target", t)]
        r, c = pdf_markup.frame(k, P)
        a = pdf_markup.angle_of(P)
        return [("rot", self._mk_rot_handle_pt(m))] + \
            [(n, pdf_markup.rot_pt(q, c, a)) for n, q in self._rect_handles(r)]

    def _mk_handle_cursor(self, h):
        if h in ("p1", "p2", "target"):
            return Qt.CrossCursor
        if h == "bend":
            return Qt.PointingHandCursor
        if h in ("mr", "sr", "dr", "nr"):
            return Qt.SizeHorCursor
        if h == "rot":
            if getattr(self, "_rot_cursor", None) is None:
                pm = markup_bar.icon("mdi6.rotate-right", False, on_white=False).pixmap(22, 22)
                from PySide6.QtGui import QCursor
                self._rot_cursor = QCursor(pm) if not pm.isNull() else QCursor(Qt.PointingHandCursor)
            return self._rot_cursor
        m = self._mk_sel()
        a = pdf_markup.angle_of(m["p"]) if m is not None else 0.0
        if not a:
            return BOX_CURSORS[h]
        # donmus kutuda tutamacin gercek yonune gore ok imleci
        base = {"r": 0, "br": 45, "b": 90, "bl": 135, "l": 180, "tl": 225, "t": 270, "tr": 315}[h]
        d = (base + a) % 180
        return [Qt.SizeHorCursor, Qt.SizeFDiagCursor, Qt.SizeVerCursor, Qt.SizeBDiagCursor][
            int(((d + 22.5) % 180) // 45)]

    def _mk_set_angle(self, deg, group=True):
        m = self._mk_sel()
        if m is None or m["kind"] not in pdf_markup.ROTATABLE:
            return
        deg = ((float(deg) + 180.0) % 360.0) - 180.0
        if abs(deg - (((pdf_markup.angle_of(m["p"]) + 180.0) % 360.0) - 180.0)) < 1e-6:
            return
        P = dict(m["p"])
        P["angle"] = 0.0 if abs(deg) < 1e-6 else deg
        self.engine.update_markup(self.current_page, m["id"], P,
                                  group=("mkangle", m["id"]) if group else None)
        self._mk_changed()
        self._refresh_panel()

    def _mk_rotate_by(self, delta):
        m = self._mk_sel()
        if m is not None:
            self._mk_set_angle(pdf_markup.angle_of(m["p"]) + delta, group=False)

    def _mk_rot_handle_pt(self, m):
        """Dondurme tutamaci: nesnenin (donmus) ust kenarinin ortasinin biraz disinda."""
        r, c = pdf_markup.frame(m["kind"], m["p"])
        top = fitz.Point(c.x, r.y0 - self._tol(24))
        return pdf_markup.rot_pt(top, c, pdf_markup.angle_of(m["p"]))

    @staticmethod
    def _snap_angle(deg, fine):
        """Aci yakalama: Shift = 15 derece adim; yoksa 0/90/180/270'e 3 derece kala oturur."""
        if fine:
            deg = round(deg / 15.0) * 15.0
        else:
            near = round(deg / 90.0) * 90.0
            if abs(deg - near) <= 3.0:
                deg = near
        deg = ((deg + 180.0) % 360.0) - 180.0
        return 0.0 if abs(deg) < 1e-6 else deg

    def _mk_handle_at(self, pos):
        for name, p in reversed(self._mk_handles()):     # uc tutamaclari oncelikli
            q = self.canvas.to_px(p)
            if abs(q.x() - pos.x()) <= HANDLE + 3 and abs(q.y() - pos.y()) <= HANDLE + 3:
                return name
        return None

    @staticmethod
    def _snap45(a, b):
        """a'dan b'ye giden dogruyu 45 derecenin katlarina kilitle."""
        dx, dy = b.x - a.x, b.y - a.y
        L = math.hypot(dx, dy)
        ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
        return fitz.Point(a.x + L * math.cos(ang), a.y + L * math.sin(ang))

    @staticmethod
    def _square(a, b):
        s = max(abs(b.x - a.x), abs(b.y - a.y))
        return fitz.Point(a.x + math.copysign(s, b.x - a.x or 1), a.y + math.copysign(s, b.y - a.y or 1))

    def _mk_drag_params(self, m, d):
        """Surukleme sirasindaki (henuz uygulanmamis) ayarlar."""
        P = m["p"]
        cur = d["cur"]
        dx, dy = cur.x - d["start"].x, cur.y - d["start"].y
        if d["kind"] == "mkmove":
            part = d.get("part", "all")
            if m["kind"] == "magnifier" and part in ("src", "dst"):
                P2 = dict(P)            # sadece bir daire: kaynak ya da buyuk daire
                q = P[part] if P.get(part) else P["src"]
                P2[part] = [q[0] + dx, q[1] + dy]
                return P2
            return pdf_markup.moved(m, dx, dy, keep_target=not d.get("whole"))
        P2 = dict(P)
        h = d["handle"]
        if h in ("mr", "sr", "dr"):
            S, rs, D, R = pdf_markup.mag_geometry(P)
            if h == "dr":               # buyuk daire kenari = buyutme orani
                z = abs(cur - D) / max(rs, 0.5)
                z = round(z * 2) / 2 if d.get("keep") else round(z * 20) / 20
                P2["zoom"] = min(12.0, max(1.25, z))
            else:
                P2["r"] = max(3.0, abs(cur - S))
            return P2
        if h == "nr":                   # numara rozeti: kenar = yaricap
            P2["size"] = max(8.0, min(96.0, 2 * abs(cur - fitz.Point(P["pos"]))))
            return P2
        if m["kind"] == "ink" and h in BOX_CURSORS:
            old = pdf_markup.bbox(m)
            nb = self._handle_bbox(h, old, cur, d.get("keep"), d.get("center"))
            P2["strokes"] = pdf_markup.scale_strokes(P, old, nb)
            return P2
        if h == "bend":                 # cizgiyi buk (duz cizgiye yaklasinca duzlesir)
            a, b = self._mk_line_ends(m)
            mpt = curve_math.symmetric(a, b, cur) if d.get("keep") else cur
            P2["bend"] = None if curve_math.is_straight(a, mpt, b, self._tol(BEND_SNAP)) \
                else [mpt.x, mpt.y]
        elif h in ("p1", "p2"):
            P2[h] = [cur.x, cur.y]
            if P.get("bend"):           # egrinin bicimi uclarla birlikte doner/olceklenir
                mb = curve_math.carry(P["p1"], P["p2"], P["bend"], P2["p1"], P2["p2"])
                P2["bend"] = [mb.x, mb.y]
        elif h == "target":
            P2["target"] = [cur.x, cur.y]
            old = pdf_markup.note_leader(P) if P.get("bend") else None
            if old is not None:         # not cizgisi bukuluyse bicimi hedefle birlikte esnesin
                new = pdf_markup.note_leader(P2)
                if new is not None:
                    mb = curve_math.carry(old[0], old[1], old[2], new[0], new[1])
                    P2["bend"] = [mb.x, mb.y]
        elif h == "rot":                # merkez etrafinda dondur
            c = pdf_markup.frame(m["kind"], P)[1]
            deg = math.degrees(math.atan2(cur.y - c.y, cur.x - c.x)) + 90.0
            P2["angle"] = self._snap_angle(deg, d.get("keep"))
        elif pdf_markup.angle_of(P):   # donmus kutuda boyutlandirma: kendi cercevesinde
            r, c = pdf_markup.frame(m["kind"], P)
            a = pdf_markup.angle_of(P)
            nb = self._handle_bbox(h, r, pdf_markup.rot_pt(cur, c, -a), d.get("keep"), d.get("center"))
            nc = pdf_markup.rot_pt(fitz.Point((nb.x0 + nb.x1) / 2, (nb.y0 + nb.y1) / 2), c, a)
            hw, hh = nb.width / 2, nb.height / 2
            P2["rect"] = [nc.x - hw, nc.y - hh, nc.x + hw, nc.y + hh]
        else:
            nb = self._handle_bbox(h, fitz.Rect(P["rect"]).normalize(), cur, d.get("keep"), d.get("center"))
            P2["rect"] = [nb.x0, nb.y0, nb.x1, nb.y1]
        return P2

    @staticmethod
    def _mk_line_ends(m):
        """Bukulebilir cizginin iki ucu: ok -> (p1, p2); not -> (kutu kenari, hedef)."""
        P = m["p"]
        if m["kind"] == "note":
            ld = pdf_markup.note_leader(P)
            return (ld[0], ld[1]) if ld is not None else (fitz.Point(P["pos"]), fitz.Point(P["pos"]))
        return fitz.Point(P["p1"]), fitz.Point(P["p2"])

    # ============================================================ fare
    def _mk_grab_at(self, pt):
        """Imlecin altindaki (tutulabilir) nesne. Cizim araci aciktayken dolgusuz
        kutu/dairenin ICI bos sayilir (ic kismina yeni cizim baslatilabilsin),
        sadece cizgisinden tutulur."""
        drawing = self.mk_tool != "select"
        tol = self._tol(4 if drawing else 6)
        for m in reversed(self.engine.get_markups(self.current_page)):
            if not pdf_markup.hit(m, pt, tol):
                continue
            if drawing and m["kind"] in ("rect", "ellipse") and not m["p"].get("fill") \
                    and not pdf_markup.near_outline(m, pt, tol + m["p"].get("width", 1) / 2):
                continue
            return m["id"]
        return None

    def _in_note_box(self, m, pt):
        """Nokta notun kutusunun (donukse donuk) icinde mi (kutu mu, ok mu tutuldu)."""
        r0, c = pdf_markup.frame("note", m["p"])
        a = pdf_markup.angle_of(m["p"])
        q = pdf_markup.rot_pt(pt, c, -a) if a else pt
        t = self._tol(3)
        return (r0 + (-t, -t, t, t)).contains(q)

    def _mk_press(self, pt, pos, mods):
        self._mk_close_editor()
        # Ctrl + cizim araci: altinda nesne/tutamac olsa da HER ZAMAN yeni ciz
        force_draw = self.mk_tool != "select" and bool(mods & Qt.ControlModifier)
        if self.mk_tool in FREEHAND:           # kalem / fosforlu / silgi: her zaman ciz
            force_draw = True
        # 1) secili nesnenin tutamaclari (her aracta)
        h = None if force_draw else self._mk_handle_at(pos)
        if h:
            self.drag = {"kind": "mkhandle", "handle": h, "start": pt, "cur": pt, "moved": False}
            return
        # 2) var olan nesne: sec + tasi (arac degismez)
        mid = None if force_draw else self._mk_grab_at(pt)
        if mid is not None:
            if mid != self.sel_markup:
                self._mk_loaded = None
                self._mk_select(mid)
            self.drag = {"kind": "mkmove", "start": pt, "cur": pt, "moved": False}
            m = self._mk_sel()
            if m is not None and m["kind"] == "magnifier":
                self.drag["part"] = pdf_markup.mag_part(m, pt, self._tol(3))
            elif m is not None and m["kind"] == "note" and not self._in_note_box(m, pt):
                self.drag["whole"] = True      # oktan tutuldu: ok ucu dahil hepsi kayar
            return
        # 3) bos yer: secimi birak; arac aciksa surukleyince yeni nesne
        had_sel = self.sel_markup is not None
        if had_sel:
            self._mk_select(None)
        if self.mk_tool == "select":
            return
        kind = {"note": "mknote", "magnifier": "mkmag", "pen": "mkpen", "highlight": "mkhl",
                "eraser": "mkerase", "number": "mknum"}.get(self.mk_tool, "mkdraw")
        self.drag = {"kind": kind, "start": pt, "cur": pt, "moved": False, "had_sel": had_sel,
                     "pts": [pt]}
        if kind == "mkhl":                     # yazinin ustunden basladiysa kelimelere otur
            words = self.engine.get_words(self.current_page)
            wi = pdf_markup.word_at(words, pt, self._tol(2))
            if wi is not None:
                self.drag["text"] = wi
                self.drag["rects"] = pdf_markup.text_rects(words, wi, wi)
        elif kind == "mkerase":
            self.drag["hits"] = set()
            self._mk_erase_at(self.drag, pt, pt)

    def _mk_move(self, pt, pos, mods, pressed):
        d = self.drag
        if d and pressed:
            if not d["moved"] and not self._moved_enough(pos):
                return
            if not d["moved"] and d["kind"] in ("mkmove", "mkhandle"):
                m = self._mk_sel()
                if m is not None and m["kind"] in ("magnifier", "blur", "image"):
                    # nesnenin kendisi sayfadan kalkar, yerine canli onizleme cizilir
                    self._set_render_hide(m["xrefs"])
                elif m is not None and m["kind"] != "texthl":
                    # nesne sayfadan kalkar: tasirken kendi goruntusu fareyle gider, tutamacla
                    # duzenlerken gercek renk/kalinlik/kesikli cizgisiyle yeni hali cizilir
                    self._mk_ghost(m)
                    if self.canvas.ghost is None and d.get("handle") == "rot":
                        self._set_render_hide(m["xrefs"])
            d["moved"] = True
            shift = bool(mods & Qt.ShiftModifier)
            cur = pt
            if d["kind"] == "mkdraw" and shift:
                cur = self._snap45(d["start"], pt) if self.mk_tool in ("arrow", "line") \
                    else self._square(d["start"], pt)
            elif d["kind"] == "mkhandle" and shift and d["handle"] in ("p1", "p2"):
                m = self._mk_sel()
                other = fitz.Point(m["p"]["p2" if d["handle"] == "p1" else "p1"])
                cur = self._snap45(other, pt)
            elif d["kind"] == "mkhandle" and mods & Qt.AltModifier and d["handle"] in ("p1", "p2", "target"):
                # Alt: aci sabit, sadece uzunluk degisir
                m = self._mk_sel()
                if d["handle"] == "target":
                    ld = pdf_markup.note_leader(m["p"])
                    fixed, end = (ld[0], ld[1]) if ld is not None else (None, None)
                else:
                    fixed = fitz.Point(m["p"]["p2" if d["handle"] == "p1" else "p1"])
                    end = fitz.Point(m["p"][d["handle"]])
                if fixed is not None:
                    cur = curve_math.keep_angle(fixed, end, pt)
            elif d["kind"] == "mkmove" and shift:
                cur = self._axis_lock(d["start"], pt)
            if d["kind"] in ("mkpen", "mkhl", "mkerase"):
                self._mk_free_move(d, pt, shift)
                self.canvas.update()
                return
            if d["kind"] == "mkhandle":
                d["keep"] = shift          # kutu/daire: Shift en-boy oranini korur
                m = self._mk_sel()
                if m is not None and d["handle"] != "rot" and                         (m["kind"] == "image" or (m["kind"] == "ink" and m["p"].get("sig"))):
                    d["keep"] = not shift  # goruntu / imza BOYUTU: oran korunur, Shift serbest
                    # (dondurme tutamacinda Shift her nesnede ayni: 15 derece adim)
            if d["kind"] in ("mkhandle", "mkdraw"):
                d["center"] = bool(mods & Qt.AltModifier)   # Alt: merkezden cizer/olcekler
            d["cur"] = cur
            self.canvas.update()
            return
        # --- fareyle gezinme: tutamac / nesne / bos (her aracta ayni) ---
        if self.mk_tool in FREEHAND:
            self.hover_markup = None
            self.update_cursor(self._eraser_cursor() if self.mk_tool == "eraser" else None)
            return
        h = self._mk_handle_at(pos)
        if h:
            self.update_cursor(self._mk_handle_cursor(h))
            return
        mid = self._mk_grab_at(pt)
        if mid != self.hover_markup:
            self.hover_markup = mid
            self.canvas.update()
        self.update_cursor(Qt.SizeAllCursor if mid is not None else None)

    def _mk_release(self, pt, mods):
        d = self.drag
        if not d:
            return
        pno = self.current_page
        if d["kind"] in ("mkpen", "mkhl"):
            self._mk_free_create(d)
            return
        if d["kind"] == "mkerase":
            ids = list(d.get("hits") or ())
            self._render_hide = ()             # after_edit zaten yeniden cizecek
            if ids:
                n = self.engine.delete_markups(pno, ids)
                self.sel_markup = None
                self.hover_markup = None
                self.after_edit()
                self.status(_t("{n} işaretleme silindi. (Ctrl+Z ile geri alınır)", n=n))
            return
        if d["kind"] == "mknum":               # her tiklama sıradaki numara (secim olsa da)
            at = d["cur"]
            n = self.engine.next_number(pno)
            mid = self.engine.add_markup(pno, "number", params_from(
                "number", self.mk_style["number"], {"pos": [at.x, at.y], "n": n}))
            self._mk_after_create(mid, _t("{n} numarası eklendi — sıradaki {m}. Numarayı değiştirmek "
                                          "için üst çubuktaki kutuyu kullanın.", n=n, m=n + 1))
            return
        if d["kind"] == "mkmag":
            if d["moved"] or not d.get("had_sel"):      # secim birakmak icin tiklandiysa olusturma
                self._mag_create(d)
            return
        if d["kind"] == "mkdraw":
            a, b = d["start"], d["cur"]
            if not d["moved"] or abs(b - a) < 2:
                return
            tool = self.mk_tool
            kind = TOOL_KIND[tool]
            geom = {"p1": [a.x, a.y], "p2": [b.x, b.y]} if kind == "arrow" else \
                {"rect": list(self._drag_box(d))}
            if kind == "blur":
                r = fitz.Rect(geom["rect"]) & self._page_box()
                if r.is_empty or r.width < 2 or r.height < 2:
                    return
                geom["rect"] = [r.x0, r.y0, r.x1, r.y1]
            st = self.mk_style["line" if tool == "line" else kind]
            P = params_from(kind, st, geom)
            if tool == "line":
                P["head"] = "none"
            mid = self.engine.add_markup(pno, kind, P)
            self._mk_after_create(mid, _t("Bulanık alan eklendi — alttaki içerik dosyayı kaydedince kalıcı "
                                       "silinir.") if kind == "blur" else
                                  _t("Çizildi — sürükleyerek taşıyın, tutamaçlarla düzenleyin."))
            return
        if d["kind"] == "mknote":
            moved = d["moved"] and abs(d["cur"] - d["start"]) > self._tol(12)
            if not moved and d.get("had_sel"):
                return                                 # tiklama sadece secimi birakti
            target = d["start"] if moved else None
            pos = d["cur"] if target is not None else d["start"]
            st = self.mk_style["note"]
            geom = {"pos": [pos.x, pos.y - st["size"]], "text": _t("Not"),
                    "target": [target.x, target.y] if target is not None else None}
            mid = self.engine.add_markup(pno, "note", params_from("note", st, geom))
            self._mk_after_create(mid, _t("Not eklendi — yazıyı hemen yazabilirsiniz (Esc: bitir)."))
            self._mk_edit_text(select_all=True)
            return
        m = self._mk_sel()
        if m is None or not d["moved"]:
            return
        P2 = self._mk_drag_params(m, d)
        if P2 == m["p"]:                     # degisiklik yok (ör. metne bagli vurgu)
            return
        if m["kind"] == "blur":
            r = fitz.Rect(P2["rect"]) & self._page_box()
            if r.is_empty or r.width < 2 or r.height < 2:
                return
            P2["rect"] = [r.x0, r.y0, r.x1, r.y1]
        self._render_hide = ()               # after_edit zaten yeniden cizecek
        self.engine.update_markup(pno, m["id"], P2)
        if m["kind"] == "magnifier":
            self._mk_loaded = None          # buyutme orani paneldeki kutuya yansisin
        self.after_edit()
        self.status(_t("Taşındı.") if d["kind"] == "mkmove" else _t("Güncellendi."))

    # ---------------------------------------------- kalem / fosforlu kalem / silgi
    def _mk_free_move(self, d, pt, shift):
        if d["kind"] == "mkerase":
            self._mk_erase_at(d, d["pts"][-1], pt)
            d["pts"].append(pt)
            d["cur"] = pt
            return
        if d["kind"] == "mkhl" and d.get("text") is not None:
            words = self.engine.get_words(self.current_page)
            j = pdf_markup.nearest_word(words, pt)
            if j is not None:
                d["rects"] = pdf_markup.text_rects(words, d["text"], j)
            d["cur"] = pt
            return
        if shift:                              # Shift: duz cizgi (45 derece adim)
            d["pts"] = [d["pts"][0], self._snap45(d["pts"][0], pt)]
            d["straight"] = True
        else:
            if d.get("straight"):
                d["pts"] = [d["pts"][0]]
                d["straight"] = False
            if abs(pt - d["pts"][-1]) >= self._tol(0.8):
                d["pts"].append(pt)
        d["cur"] = pt

    ERASER_PX = 8          # silgi ucunun yaricapi (ekran px)

    def _mk_erase_at(self, d, a, b):
        """a-b arasindan gecen silgi ucunun dokundugu isaretlemeler: dokunulan nesne
        hemen sayfadan kaybolur (gercek silme birakinca, tek geri-al adimi)."""
        r = self._tol(self._eraser_px)
        L = abs(b - a)
        steps = max(1, int(L / max(r * 0.5, 0.01)))
        ms = self.engine.get_markups(self.current_page)
        new = False
        for k in range(steps + 1):
            q = a + (b - a) * (k / steps)
            for m in ms:
                if m["id"] not in d["hits"] and pdf_markup.hit(m, q, r):
                    d["hits"].add(m["id"])
                    new = True
        if new:
            self._set_render_hide([x for m in ms if m["id"] in d["hits"] for x in m["xrefs"]])

    def _mk_set_eraser(self, v):
        self._eraser_px = int(v)
        try:
            self._settings.setValue("eraser_px", self._eraser_px)
        except Exception:
            pass
        self._erase_cur = None
        if self.mode == "markup" and self.mk_tool == "eraser":
            self.update_cursor(self._eraser_cursor())

    def _eraser_cursor(self):
        if getattr(self, "_erase_cur", None) is None:
            from PySide6.QtGui import QPixmap, QPainter, QCursor
            n = self._eraser_px * 2 + 4
            pm = QPixmap(n, n)
            pm.fill(Qt.transparent)
            qp = QPainter(pm)
            qp.setRenderHint(QPainter.Antialiasing)
            qp.setPen(QPen(QColor(255, 255, 255, 230), 3))
            qp.drawEllipse(QRectF(2, 2, n - 4, n - 4))
            qp.setPen(QPen(QColor(60, 60, 60, 230), 1.2))
            qp.setBrush(QColor(255, 255, 255, 60))
            qp.drawEllipse(QRectF(2, 2, n - 4, n - 4))
            qp.end()
            self._erase_cur = QCursor(pm, n // 2, n // 2)
        return self._erase_cur

    def _mk_free_create(self, d):
        pno = self.current_page
        if d["kind"] == "mkhl" and d.get("text") is not None:
            rects = d.get("rects") or []
            if not rects:
                return
            mid = self.engine.add_markup(pno, "texthl", params_from(
                "texthl", self.mk_style["highlight"], {"rects": rects}))
            self.after_edit()
            self.status(_t("Yazı vurgulandı — Adobe/Edge'de de vurgu olarak görünür. "
                        "Türünü (vurgu / altı çizili / üstü çizili) üst çubuktan seçin."))
            return
        hl = d["kind"] == "mkhl"
        pts = d["pts"]
        if not d["moved"] or len(pts) < 2:
            if hl:
                return                         # bosa fosforlu tiklama: bir sey yapma
            pts = [pts[0]]                     # kalemle tiklama: nokta
        elif not d.get("straight"):
            pts = pdf_markup.simplify_stroke(pdf_markup.smooth_points(pts, self._tol(8)), self._tol(0.35))
        st = self.mk_style["highlight" if hl else "ink"]
        P = params_from("ink", st, {"strokes": [[[q.x, q.y] for q in pts]], "hl": hl})
        self.engine.add_markup(pno, "ink", P)
        self.after_edit()                      # secilmez: kalem akisi kesilmesin

    # ---------------------------------------------- imza / goruntu
    def _view_center(self):
        """Ekranda gorunen alanin ortasi (sayfa uzayinda, sayfanin icinde)."""
        vp = self.scroll.viewport()
        c = self.canvas.mapFrom(vp, vp.rect().center())
        pt = self.canvas.to_pdf(QPointF(c))
        box = self._page_box()
        return fitz.Point(min(max(pt.x, box.x0 + 20), box.x1 - 20), min(max(pt.y, box.y0 + 20), box.y1 - 20))

    def _mk_sign_menu(self):
        if not self.engine.doc:
            return
        import signature
        sigs = signature.load(self._settings)
        if not sigs:
            self._mk_new_signature()
            return
        pop = markup_bar.Popover(self)
        v = QVBoxLayout(pop)
        v.setContentsMargins(10, 10, 10, 10)
        v.setSpacing(6)
        v.addWidget(markup_bar.small_label(_t("İmzalarım — koymak için tıklayın")))
        from PySide6.QtWidgets import QPushButton, QToolButton
        for i, sg in enumerate(sigs):
            row = QHBoxLayout()
            b = QPushButton()
            b.setIcon(QIcon(signature.preview(sg, 220, 70)))
            b.setIconSize(QSize(220, 70))
            b.setFixedSize(236, 80)
            # imza kagit uzerindeki gibi gorunsun: kutunun ici her temada beyaz
            acc = QApplication.palette().highlight().color().name()
            b.setStyleSheet("QPushButton { background: #ffffff; border: 1px solid #d5d9e0; border-radius: 8px; }"
                            f"QPushButton:hover {{ border: 1px solid {acc}; }}"
                            "QPushButton:pressed { background: #f2f4f8; }")
            b.setToolTip(_t("Bu imzayı sayfaya koy"))
            b.clicked.connect(lambda _=False, sg=sg: (pop.close(), self._mk_place_signature(sg)))
            x = QToolButton()
            x.setIcon(markup_bar.icon("mdi6.close", self.dark, on_white=False))
            x.setToolTip(_t("Bu imzayı listeden sil"))
            x.setAutoRaise(True)
            x.clicked.connect(lambda _=False, i=i: (pop.close(), self._mk_delete_signature(i)))
            row.addWidget(b)
            row.addWidget(x)
            v.addLayout(row)
        new = QPushButton(_t("  Yeni imza oluştur…"))
        new.setIcon(markup_bar.icon("mdi6.plus", self.dark, on_white=False))
        new.clicked.connect(lambda: (pop.close(), self._mk_new_signature()))
        v.addWidget(new)
        pop.show_under(self.btn_mk_sign)

    def _mk_new_signature(self):
        import signature
        dlg = signature.SignatureDialog(self)
        if not dlg.exec() or dlg.result_sig is None:
            return
        sigs = signature.load(self._settings)
        signature.store(self._settings, [dlg.result_sig] + sigs)
        self._mk_place_signature(dlg.result_sig)

    def _mk_delete_signature(self, i):
        import signature
        sigs = signature.load(self._settings)
        if 0 <= i < len(sigs):
            del sigs[i]
            signature.store(self._settings, sigs)
            self.status(_t("İmza listeden silindi (sayfadakilere dokunulmadı)."))

    def _mk_place_signature(self, sg):
        import signature, base64
        c = self._view_center()
        w = min(150.0, self._page_box().width * 0.35)
        pno = self.current_page
        if sg["type"] == "image":
            h = w * float(sg.get("aspect", 0.35))
            P = {"rect": [c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2], "opacity": 1.0}
            mid = self.engine.add_markup(pno, "image", P, img=base64.b64decode(sg["png"]))
        else:
            P = params_from("ink", self.mk_style["sign"],
                            {"strokes": signature.placed_strokes(sg, c.x, c.y, w), "sig": True})
            mid = self.engine.add_markup(pno, "ink", P)
        if self.mk_tool in FREEHAND:
            self.set_markup_tool("select")
        self._mk_after_create(mid, _t("İmza eklendi — sürükleyerek yerine koyun, köşeden boyutlandırın."))

    def _mk_add_image(self):
        if not self.engine.doc:
            return
        from PySide6.QtWidgets import QFileDialog
        from PySide6.QtGui import QImage
        from PySide6.QtCore import QBuffer, QIODevice
        path, _ = QFileDialog.getOpenFileName(self, _t("Görüntü ekle"), "",
                                              _t("Görüntüler (*.png *.jpg *.jpeg *.bmp *.gif *.webp *.tif *.tiff)"))
        if not path:
            return
        img = QImage(path)
        if img.isNull():
            QMessageBox.warning(self, _t("Açılamadı"), _t("Bu görüntü dosyası açılamadı."))
            return
        if path.lower().endswith((".jpg", ".jpeg")):
            with open(path, "rb") as f:        # JPEG'i yeniden sıkıştırma: kalite kaybı olmasın
                data = f.read()
        else:
            buf = QBuffer()
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")               # saydamlik korunur
            data = bytes(buf.data())
        dpi = img.dotsPerMeterX() * 0.0254 or 96.0
        w, h = img.width() * 72.0 / dpi, img.height() * 72.0 / dpi
        box = self._page_box()
        s = min(1.0, box.width * 0.6 / max(w, 1), box.height * 0.6 / max(h, 1))
        w, h = w * s, h * s
        c = self._view_center()
        P = params_from("image", self.mk_style["image"],
                        {"rect": [c.x - w / 2, c.y - h / 2, c.x + w / 2, c.y + h / 2]})
        mid = self.engine.add_markup(self.current_page, "image", P, img=data)
        if self.mk_tool in FREEHAND:
            self.set_markup_tool("select")
        self._mk_after_create(mid, _t("Görüntü eklendi — sürükleyerek taşıyın, köşeden boyutlandırın "
                                   "(oran korunur; Shift: serbest)."))

    # ---------------------------------------------- buyutec olusturma
    def _mag_new_params(self, d):
        st = self.mk_style["magnifier"]
        S = d["start"]
        lens = st.get("mode") == "lens"
        r = abs(d["cur"] - S) if d["moved"] else 0.0
        if r < 3:
            r = 40.0 if lens else 20.0             # sadece tiklandiysa varsayilan boy
        geom = {"src": [S.x, S.y], "r": r, "dst": None, "caption": "",
                "label": self._mag_next_label() if not lens else ""}
        if not lens:
            D = self._mag_place(S, r, r * st.get("zoom", 2.0))
            geom["dst"] = [D.x, D.y]
        return params_from("magnifier", st, geom)

    def _mag_create(self, d):
        mid = self.engine.add_markup(self.current_page, "magnifier", self._mag_new_params(d))
        self._mk_after_create(mid, _t("Büyüteç eklendi — daireleri sürükleyerek taşıyın, kenardaki "
                                   "tutamaçla boyutlandırın (büyük dairenin tutamacı büyütme oranı)."))

    # ---------------------------------------------- canli onizlemeler
    def _preview_scale(self, cv, area_pt2, budget):
        """Onizleme cozunurlugu: ekran kadar, ama cok buyuk alanlarda sinirli (akici kalsin)."""
        scale = cv.zoom * getattr(cv, "dpr", 1.0)
        if area_pt2 * scale * scale > budget:
            scale = (budget / max(area_pt2, 1.0)) ** 0.5
        return scale

    def _blur_preview(self, cv, r, mode, level, fast=False):
        """Bulanik alanin canli onizlemesi (PDF'e konacak goruntuyle ayni islem).
        fast: surukleme sirasinda dusuk cozunurluk (her fare hareketinde yeniden islenir)."""
        if mode == "solid":
            return None
        scale = self._preview_scale(cv, r.width * r.height, 300_000 if fast else 4_000_000)
        key = (self.current_page, tuple(round(v, 1) for v in r), round(scale, 3), mode, level,
               self.engine.version)
        if self._blur_cache is not None and self._blur_cache[0] == key:
            return self._blur_cache[1]
        page = self.engine.doc[self.current_page]
        pad = pdf_blur.pad_pt(mode, level)
        # ekranda gorundugu yonde (donmus sayfada da) render et
        src = pdf_blur.render(page, (r * page.rotation_matrix).normalize(), scale, pad)
        img = pdf_blur.process(src, mode, level, scale, round(pad * scale) if pad else 0)
        self._blur_cache = (key, img)
        return img

    def _mag_source_image(self, cv, S, rs, z):
        """Buyutecin kaynak alaninin (sayfa icerigi) goruntusu, ekranda buyutulmus
        haliyle ayni cozunurlukte. Kaynak ayni kaldikca onbellekten gelir."""
        scale = self._preview_scale(cv, (2 * rs * z) ** 2, 2_500_000) * z
        key = (self.current_page, round(S.x, 1), round(S.y, 1), round(rs, 1), round(scale, 3),
               self.engine.version)
        if self._mag_cache is not None and self._mag_cache[0] == key:
            return self._mag_cache[1]
        page = self.engine.doc[self.current_page]
        clip = (fitz.Rect(S.x - rs, S.y - rs, S.x + rs, S.y + rs) * page.rotation_matrix).normalize()
        img = pdf_blur.render(page, clip, scale)
        self._mag_cache = (key, img)
        return img

    def _paint_blur_select(self, p, cv, r, mode, level, angle=0.0):
        """Alan secilirken/tasinirken: alttaki yazilar OKUNAKLI kalir (nereyi
        kapattigin gorulsun), hafif koyu ort + ortada etiket. Birakinca bulaniklasir."""
        if angle:
            p.save()
            rp = self._mk_frame_px(p, cv, "blur", {"rect": list(r), "angle": angle})
            self._paint_blur_select_px(p, rp, mode, level)
            p.restore()
            return
        self._paint_blur_select_px(p, cv.rect_px(r), mode, level)

    def _paint_blur_select_px(self, p, rp, mode, level):
        p.fillRect(rp, QColor(40, 40, 40, 150))          # koyu ort; alttaki yazi yine okunur
        p.setPen(QPen(QColor(255, 255, 255, 170), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rp)
        name = {"blur": _t("Bulanıklaştır"), "pixel": _t("Pikselleştir"), "solid": _t("Siyah kutu")}.get(mode, _t("Bulanıklaştır"))
        text = name + (f" [{level}]" if mode != "solid" else "")
        f = QFont(self.font())
        f.setBold(True)
        f.setPixelSize(15)
        p.setFont(f)
        if p.fontMetrics().horizontalAdvance(text) > rp.width() - 6:   # dar alan: sadece guc
            text = f"[{level}]" if mode != "solid" else ""
        p.setPen(QColor(255, 255, 255))
        p.drawText(rp, Qt.AlignCenter, text)

    def _paint_blur_preview(self, p, cv, r, mode, level, fast=False):
        rp = cv.rect_px(r)
        img = self._blur_preview(cv, r, mode, level, fast)
        if img is None:
            p.fillRect(rp, QColor(0, 0, 0))
        else:
            p.drawImage(rp, img)
        p.setPen(self._pen(QColor(37, 99, 235), 1.2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(rp)

    def _paint_mag_preview(self, p, cv, P):
        """Buyutecin canli onizlemesi: daire icinde buyutulmus icerik + cizgiler."""
        S, rs, D, R = pdf_markup.mag_geometry(P)
        img = self._mag_source_image(cv, S, rs, R / rs)
        c = cv.to_px(D)
        rp = R * cv.zoom
        disc = QRectF(c.x() - rp, c.y() - rp, 2 * rp, 2 * rp)
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 50))
        p.drawEllipse(disc.translated(2, 2))
        p.setBrush(QColor(255, 255, 255))
        p.drawEllipse(disc)
        path = QPainterPath()
        path.addEllipse(disc)
        p.setClipPath(path)
        p.drawImage(disc, img)
        p.restore()
        col = QColor.fromRgbF(*P["color"])
        pen = QPen(col)
        pen.setWidthF(max(1.0, P["width"] * cv.zoom))
        self._mk_outline(p, cv, "magnifier", P, pen, dashed_src=bool(P.get("dashed")))
        # yazilar (yaklasik; gercek cizim birakinca)
        labels = pdf_markup.mag_labels(P)
        if labels:
            f = QFont(P.get("label_font") or "Arial")
            f.setBold(bool(P.get("label_bold", True)))
            p.setPen(QColor.fromRgbF(*(P.get("label_color") or P["color"])))
            for text, o, size in labels:
                f.setPixelSize(max(1, round(size * cv.zoom)))
                p.setFont(f)
                p.drawText(cv.to_px(o), text)

    def _paint_image_preview(self, p, cv, mid, P):
        """Goruntu tasinirken / boyutlanirken / donerken resmin kendisi (canli)."""
        cache = self.__dict__.setdefault("_img_prev_cache", {})
        if mid not in cache:
            from PySide6.QtGui import QImage
            data = self.engine.markup_image(self.current_page, mid)
            cache[mid] = QImage.fromData(data) if data else None
        img = cache[mid]
        if img is None or img.isNull():
            return
        p.save()
        p.setOpacity(P.get("opacity", 1.0))
        rp = self._mk_frame_px(p, cv, "image", P)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(rp, img)
        p.restore()

    def _mk_straighten(self):
        m = self._mk_sel()
        if m is None or m["kind"] not in ("arrow", "note") or not m["p"].get("bend"):
            return
        P = dict(m["p"])
        P["bend"] = None
        self.engine.update_markup(self.current_page, m["id"], P)
        self.after_edit()
        self.status(_t("Çizgi düzleştirildi."))

    def _mk_double(self, pt):
        m = self._mk_sel()
        if m is not None and m["kind"] in ("arrow", "note") \
                and self._mk_handle_at(self.canvas.to_px(pt)) == "bend":
            self._mk_straighten()             # bukme tutamacina cift tik = duzlestir
            return
        if m is None:
            mid = self._mk_grab_at(pt)
            if mid is not None:
                self._mk_select(mid)
                m = self._mk_sel()
        if m is not None and m["kind"] == "note":
            self._mk_edit_text()

    def _mk_context(self, menu, pt):
        mid = self._mk_grab_at(pt) or self.engine.markup_at(self.current_page, pt.x, pt.y, self._tol(6))
        if mid is not None:
            self._mk_select(mid)
            m = self._mk_sel()
            ic_ = lambda n: markup_bar.icon(n, self.dark, on_white=False)
            if m["kind"] == "note":
                menu.addAction(ic_("mdi6.text-box-edit-outline"), _t("Yazıyı düzenle\tF2"), self._mk_edit_text)
            if m["kind"] in ("arrow", "note") and m["p"].get("bend"):
                menu.addAction(ic_("mdi6.vector-line"), _t("Düzleştir"), self._mk_straighten)
            menu.addAction(ic_("mdi6.content-copy"), _t("Çoğalt\tCtrl+D"), self._mk_duplicate)
            menu.addAction(ic_("mdi6.arrange-bring-to-front"), _t("Öne getir"), self._mk_to_front)
            menu.addAction(ic_("mdi6.arrange-send-to-back"), _t("Arkaya gönder"), self._mk_to_back)
            menu.addSeparator()
            menu.addAction(ic_("mdi6.delete-outline"), _t("Sil\tDelete"), self.delete_selected)
            menu.addSeparator()
        menu.addAction(_t("Tüm işaretlemeleri sayfaya işle..."), self.flatten_markups_dialog)

    def _mk_nudge(self, dx, dy, group):
        m = self._mk_sel()
        if m is None:
            return
        self.engine.update_markup(self.current_page, m["id"], pdf_markup.moved(m, dx, dy), group=group)
        self._mk_changed()

    def _mk_delete(self):
        m = self._mk_sel()
        if m is None:
            self.status(_t("Önce silmek istediğiniz işaretlemeyi seçin."))
            return
        self.engine.delete_markup(self.current_page, m["id"])
        self.sel_markup = None
        self.after_edit()
        self.status(_t("İşaretleme silindi."))

    def flatten_markups_dialog(self):
        if not self.engine.doc:
            return
        n = sum(len(self.engine.get_markups(i)) for i in range(self.engine.page_count()))
        if n == 0:
            QMessageBox.information(self, _t("İşaretleme yok"), _t("Belgede Revora ile eklenmiş işaretleme yok."))
            return
        r = QMessageBox.question(
            self, _t("Sayfaya işle"),
            _t("{n} işaretleme sayfaların kalıcı parçası olacak: artık nesne olarak taşınamaz/"
               "düzenlenemez, karşı taraf da silemez. (Ctrl+Z ile geri alınabilir.)\n\nDevam edilsin mi?", n=n))
        if r != QMessageBox.Yes:
            return
        self.engine.flatten_markups()
        self.sel_markup = None
        self.after_edit(all_thumbs=True)
        self.status(_t("İşaretlemeler sayfaya işlendi."))

    # ============================================================ cizim
    @staticmethod
    def _disp_angle(cv):
        m = cv.disp
        return math.degrees(math.atan2(m.b, m.a))

    def _mk_frame_px(self, p, cv, kind, P, pad=0.0):
        """Painter'i nesnenin merkezine tasiyip dondurur; donmemis cercevenin (merkeze
        gore) px dikdortgenini dondurur. Cagiran p.save()/p.restore() yapmali."""
        r, c = pdf_markup.frame(kind, P)
        z = cv.zoom
        q = cv.to_px(c)
        p.translate(q)
        p.rotate(pdf_markup.angle_of(P) + self._disp_angle(cv))
        return QRectF((r.x0 - c.x) * z - pad, (r.y0 - c.y) * z - pad, r.width * z + 2 * pad,
                      r.height * z + 2 * pad)

    def _mk_outline(self, p, cv, kind, P, pen, dashed_src=False):
        """Bir isaretlemenin ana hatlari (secim / tasima onizlemesi icin)."""
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if kind in ("rect", "blur", "ellipse", "note", "image") and pdf_markup.angle_of(P):
            p.save()
            rp = self._mk_frame_px(p, cv, kind, P)
            (p.drawEllipse if kind == "ellipse" else p.drawRect)(rp)
            p.restore()
            if kind == "note":
                ld = pdf_markup.note_leader(P)
                if ld is not None:
                    p.drawPolyline(cv.poly_px(curve_math.bent_points(*pdf_markup.ld_order(ld))))
            return
        if kind == "magnifier":
            S, rs, D, R = pdf_markup.mag_geometry(P)
            circles = [(D, R, False)] if P.get("mode") == "lens" else [(S, rs, dashed_src), (D, R, False)]
            for c, rad, dash in circles:
                if dash:
                    dp = QPen(pen)
                    dp.setStyle(Qt.DashLine)
                    p.setPen(dp)
                p.drawEllipse(cv.rect_px(fitz.Rect(c.x - rad, c.y - rad, c.x + rad, c.y + rad)))
                p.setPen(pen)
            con = pdf_markup.mag_connector(P)
            if con is not None:
                p.drawLine(cv.to_px(con[0]), cv.to_px(con[1]))
        elif kind in ("rect", "blur"):
            p.drawRect(cv.rect_px(P["rect"]))
        elif kind == "arrow":
            p.drawPolyline(cv.poly_px(pdf_markup.arrow_points(P)))
        elif kind == "ellipse":
            p.drawEllipse(cv.rect_px(P["rect"]))
        elif kind == "rect":
            p.drawRect(cv.rect_px(P["rect"]))
        elif kind == "ink":
            for st in pdf_markup.ink_points(P):
                if len(st) == 1:
                    q = cv.to_px(st[0])
                    p.drawEllipse(q, 2, 2)
                else:
                    p.drawPolyline(cv.poly_px(st))
        elif kind == "texthl":
            for r in P.get("rects") or []:
                p.drawRect(cv.rect_px(r))
        elif kind == "number":
            c, rad = fitz.Point(P["pos"]), P.get("size", 20) / 2
            p.drawEllipse(cv.rect_px(fitz.Rect(c.x - rad, c.y - rad, c.x + rad, c.y + rad)))
        elif kind == "image":
            p.drawRect(cv.rect_px(P["rect"]))
        else:
            box = pdf_markup.note_geometry(P)[0]
            p.drawRect(cv.rect_px(box))
            ld = pdf_markup.note_leader(P)
            if ld is not None:
                p.drawPolyline(cv.poly_px(curve_math.bent_points(*pdf_markup.ld_order(ld))))

    def _mk_ghost(self, m):
        """Tasima basinda: isaretleme sayfadan gizlenir, kendi goruntusu (saydam zeminli)
        fareyle kayar. Hedefli notta sadece kutu kayar; ok her karede yeniden cizilir."""
        doc = self.engine.doc
        page = doc[self.current_page]
        scale = getattr(self, "_render_scale", None)
        g = drag_ghost.annot_ghost(page, m["xrefs"], scale) if scale else None
        if g is None:
            return                             # olmadi: eski cerceve onizlemesi
        pm, r = g
        part = drag_ghost.render_hidden(doc, page, m["xrefs"], scale, r)   # sadece o bolge
        if part is None:
            return
        clip = None
        whole = bool((self.drag or {}).get("whole"))
        if m["kind"] == "note" and not whole and pdf_markup.note_leader(m["p"]) is not None:
            # sadece kutunun kendisi (donukse donuk cokgen); pay yalnizca kenar cizgisi
            # kadar, yoksa okun kutuya yakin ucundan bir parca da kutuyla kayar
            P = m["p"]
            pad = (P.get("border_width", 1.0) / 2 if P.get("border") else 0) + 0.3
            r0, c = pdf_markup.frame("note", P)
            a = pdf_markup.angle_of(P)
            r0 = r0 + (-pad, -pad, pad, pad)
            clip = [pdf_markup.rot_pt(q, c, a) if a else q for q in (r0.tl, r0.tr, r0.br, r0.bl)]
        self._ghost_set(pm, part, r, clip)

    def _mk_live_pen(self, cv, rgb, width, op, dash=None, round_=False):
        col = QColor.fromRgbF(*rgb)
        col.setAlphaF(max(0.0, min(1.0, op)))
        pen = QPen(col)
        pen.setWidthF(max(0.5, width * cv.zoom))
        pen.setCapStyle(Qt.RoundCap if round_ else Qt.FlatCap)
        pen.setJoinStyle(Qt.RoundJoin if round_ else Qt.MiterJoin)
        if dash:
            ww = max(width, 0.1)
            pen.setDashPattern([max(0.05, v / ww) for v in curve_math.dash_array(dash, ww)])
        return pen

    def _mk_ghost_xf(self, p, cv, pivot, angle=0.0, scale=1.0):
        """Nesnenin kendi goruntusunu (cv.ghost) pivot etrafinda dondurerek/olcekleyerek ciz;
        kirpma cokgeni (not kutusu) de onunla doner."""
        pm, anchor, clip = cv.ghost
        q = cv.to_px(pivot)
        p.save()
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.translate(q)
        p.rotate(angle)
        p.scale(scale, scale)
        p.translate(-q)
        if clip is not None:
            path = QPainterPath()
            path.addPolygon(cv.poly_px(clip))
            p.setClipPath(path)
        p.drawPixmap(cv.to_px(anchor), pm)
        p.restore()

    def _mk_paint_live(self, p, cv, m, P):
        """Tutamacla duzenlerken nesnenin KENDISI: gercek renk, kalinlik, kesikli cizgi,
        dolgu ve opaklikla yeni hali (orijinali sayfadan kalkmistir: cv.bg).
        Bu turu cizemiyorsa False (eski cerceve onizlemesi)."""
        k = m["kind"]
        op = P.get("opacity", 1.0)
        if k in ("rect", "ellipse"):
            p.save()
            p.setPen(self._mk_live_pen(cv, P["color"], P["width"], op, pdf_markup._dash(P)))
            if P.get("fill"):
                fc = QColor.fromRgbF(*P["fill"])
                fc.setAlphaF(op)
                p.setBrush(QBrush(fc))
            else:
                p.setBrush(Qt.NoBrush)
            rp = self._mk_frame_px(p, cv, k, P)
            (p.drawEllipse if k == "ellipse" else p.drawRect)(rp)
            p.restore()
            return True
        if k == "arrow":
            w, head = P["width"], P.get("head", "end")
            if P.get("bend"):
                (a, c1, c2, e), tris = pdf_markup.curve_arrow(P["p1"], P["p2"], P["bend"], w, head, P)
                path = QPainterPath(cv.to_px(a))
                path.cubicTo(cv.to_px(c1), cv.to_px(c2), cv.to_px(e))
            else:
                (a, e), tris = pdf_markup.arrow_parts(P["p1"], P["p2"], w, head, P)
                path = QPainterPath(cv.to_px(a))
                path.lineTo(cv.to_px(e))
            p.setPen(self._mk_live_pen(cv, P["color"], w, op, pdf_markup._dash(P)))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            col = QColor.fromRgbF(*P["color"])
            col.setAlphaF(op)
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(col))
            for tri in tris:
                p.drawPolygon(QPolygonF([cv.to_px(q) for q in tri]))
            return True
        if k == "ink":
            w = P.get("width", 2.0)
            pen = self._mk_live_pen(cv, P["color"], w, op, round_=True)
            p.save()
            if P.get("hl"):                    # fosforlu: carpma karisimi (alttaki yazi siyah kalir)
                p.setCompositionMode(QPainter.CompositionMode_Multiply)
            for st in pdf_markup.ink_points(P):
                if len(st) == 1 or all(abs(q - st[0]) < 0.05 for q in st):
                    p.setPen(Qt.NoPen)
                    p.setBrush(pen.color())
                    rad = max(w / 2, 0.3) * cv.zoom
                    p.drawEllipse(cv.to_px(st[0]), rad, rad)
                    continue
                path = QPainterPath(cv.to_px(st[0]))
                for a, c1, c2, b in pdf_markup.smooth_segments(st):
                    path.cubicTo(cv.to_px(c1), cv.to_px(c2), cv.to_px(b))
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                p.drawPath(path)
            p.restore()
            return True
        if k == "note":                        # kutu: kendi goruntusu (donerken doner) + ok canli
            r0, c = pdf_markup.frame("note", m["p"])
            self._mk_ghost_xf(p, cv, c, angle=pdf_markup.angle_of(P) - pdf_markup.angle_of(m["p"]))
            self._mk_paint_leader(p, cv, P)
            return True
        if k == "number":                      # rozet boyutu: kendi goruntusu olceklenir
            s0 = max(m["p"].get("size", 18), 1e-6)
            self._mk_ghost_xf(p, cv, fitz.Point(P["pos"]), scale=P.get("size", 18) / s0)
            return True
        return False

    def _mk_paint_leader(self, p, cv, P):
        """Notun oku - gercek cizimle ayni renk, kalinlik ve egri (tasima onizlemesi)."""
        ld = pdf_markup.note_leader(P)
        if ld is None:
            return
        s, t, bend = ld
        col = QColor.fromRgbF(*(P.get("arrow_color") or P.get("border") or P["text_color"]))
        col.setAlphaF(P.get("opacity", 1.0))
        w = P.get("arrow_width", 1.5)
        if bend is None:
            self._mk_draw_arrow(p, cv, s, t, col, w, "end", P)
            return
        (a, c1, c2, e), tris = pdf_markup.curve_arrow(s, t, bend, w, "end", P)
        path = QPainterPath(cv.to_px(a))
        path.cubicTo(cv.to_px(c1), cv.to_px(c2), cv.to_px(e))
        pen = QPen(col)
        pen.setWidthF(max(1.0, w * cv.zoom))
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(col))
        for tri in tris:
            p.drawPolygon(QPolygonF([cv.to_px(q) for q in tri]))

    def _mk_draw_arrow(self, p, cv, a, b, color, width, heads, P):
        """Ok onizlemesi - gercek cizimle AYNI geometri (pdf_markup.arrow_parts)."""
        (s, e), tris = pdf_markup.arrow_parts(a, b, width, heads, P)
        pen = QPen(color)
        pen.setWidthF(max(1.0, width * cv.zoom))
        p.setPen(pen)
        p.drawLine(cv.to_px(s), cv.to_px(e))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(color))
        for tri in tris:
            p.drawPolygon(QPolygonF([cv.to_px(q) for q in tri]))

    def _paint_free_overlay(self, p, cv):
        """Kalem / fosforlu kalem / silgi: cizilirken canli onizleme."""
        d = self.drag
        if self.mk_tool == "eraser":
            return                             # silinen nesne zaten sayfadan kayboluyor
        if not d or d["kind"] not in ("mkpen", "mkhl"):
            return
        hl = d["kind"] == "mkhl"
        st = self.mk_style["highlight" if hl else "ink"]
        col = QColor.fromRgbF(*st["color"])
        if hl and d.get("text") is not None:
            col.setAlphaF(0.45)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            for r in d.get("rects") or []:
                p.drawRect(cv.rect_px(r))
            return
        col.setAlphaF(st.get("opacity", 1.0) * (0.8 if hl else 1.0))
        pen = QPen(col)
        pen.setWidthF(max(1.0, st["width"] * cv.zoom))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        pts = d["pts"]
        if len(pts) == 1:
            p.drawPoint(cv.to_px(pts[0]))
        else:
            # PDF'e yazilacak egrinin aynisi (yumusatilmis) -> birakinca cizgi zıplamaz
            if not d.get("straight"):
                pts = pdf_markup.smooth_points(pts, self._tol(8))
            path = QPainterPath(cv.to_px(pts[0]))
            for a_, c1, c2, b_ in pdf_markup.smooth_segments(pts):
                path.cubicTo(cv.to_px(c1), cv.to_px(c2), cv.to_px(b_))
            p.drawPath(path)

    def _paint_markup_overlay(self, p, cv):
        acc = QColor(37, 99, 235)
        d = self.drag
        pno = self.current_page
        if self.mk_tool in FREEHAND:
            self._paint_free_overlay(p, cv)
            if self.mk_tool == "eraser":
                return
        if self.hover_markup is not None and self.hover_markup != self.sel_markup and not d:
            m = self.engine.markup(pno, self.hover_markup)
            if m:
                p.setPen(self._pen(acc, 1, Qt.DashLine, 150))
                p.setBrush(Qt.NoBrush)
                p.drawRect(cv.rect_px(pdf_markup.bbox(m)).adjusted(-4, -4, 4, 4))
        m = self._mk_sel()
        if m is not None:
            if d and d["moved"] and d["kind"] in ("mkmove", "mkhandle"):
                P2 = self._mk_drag_params(m, d)
                if m["kind"] == "magnifier":
                    self._paint_mag_preview(p, cv, P2)          # canli: daire icinde icerik
                elif m["kind"] == "blur":
                    self._paint_blur_select(p, cv, fitz.Rect(P2["rect"]).normalize(),
                                            P2.get("mode", "blur"), P2.get("level", 5),
                                            pdf_markup.angle_of(P2))
                elif m["kind"] == "image":
                    self._paint_image_preview(p, cv, m["id"], P2)   # canli: resmin kendisi
                    self._mk_outline(p, cv, "image", P2, self._pen(acc, 1, Qt.DashLine))
                elif cv.ghost is not None and d["kind"] == "mkmove":
                    if m["kind"] == "note" and not d.get("whole"):   # kutu kayar, ok hedefe esner
                        self._mk_paint_leader(p, cv, P2)
                elif cv.ghost is not None and d["kind"] == "mkhandle" and self._mk_paint_live(p, cv, m, P2):
                    pass
                else:
                    self._mk_outline(p, cv, m["kind"], P2, self._pen(acc, 2))
                dd = d["cur"] - d["start"]
                if m["kind"] == "magnifier" and d["kind"] == "mkhandle":
                    self.lbl_coords.setText(_t("büyütme {z} · yarıçap {r} pt",
                                               z=pdf_markup.zoom_text(P2.get('zoom', 2.0)), r=f"{P2['r']:.1f}"))
                elif d["kind"] == "mkhandle" and d["handle"] == "rot":
                    self.lbl_coords.setText(_t("açı {a}°  (Shift: 15° adım)", a=f"{P2.get('angle', 0):.0f}"))
                elif m["kind"] == "blur":
                    r = fitz.Rect(P2["rect"]).normalize()
                    self.lbl_coords.setText(f"{r.width:.1f} × {r.height:.1f} pt")
                elif d["kind"] == "mkhandle" and d["handle"] in ("p1", "p2", "target"):
                    a, b = self._mk_line_ends({"kind": m["kind"], "p": P2})
                    self.lbl_coords.setText(_t("uzunluk {L} pt · açı {a}° (Alt: açı sabit)",
                                               L=f"{abs(b - a):.1f}", a=f"{curve_math.angle_deg(a, b):.1f}"))
                else:
                    self.lbl_coords.setText(f"Δx {dd.x:+.1f}  Δy {dd.y:+.1f} pt")
            else:
                if m["kind"] == "magnifier":
                    self._mk_outline(p, cv, "magnifier", m["p"], self._pen(acc, 1, Qt.DashLine))
                elif m["kind"] in pdf_markup.ROTATABLE:
                    # kendi (donmus) cercevesi + dondurme tutamacina giden sap
                    p.save()
                    p.setPen(self._pen(acc, 1, Qt.DashLine))
                    p.setBrush(Qt.NoBrush)
                    rp = self._mk_frame_px(p, cv, m["kind"], m["p"], pad=3)
                    p.drawRect(rp)
                    p.setPen(self._pen(acc, 1))
                    p.drawLine(QPointF(0, rp.top()), QPointF(0, rp.top() - 24 + 3 + HANDLE))
                    p.restore()
                elif m["kind"] != "arrow":
                    p.setPen(self._pen(acc, 1, Qt.DashLine))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(cv.rect_px(pdf_markup.bbox(m)).adjusted(-4, -4, 4, 4))
                else:
                    self._mk_outline(p, cv, "arrow", m["p"], self._pen(acc, 1, Qt.DashLine))
                p.setPen(self._pen(acc, 1.2))
                for name, hp in self._mk_handles():
                    self._paint_handle(p, cv.to_px(hp), name in ("bend", "rot"), HANDLE,
                                       filled=(name == "bend" and bool(m["p"].get("bend"))) or name == "rot")
        # yeni buyutec onizlemesi (canli icerikle)
        if d and d["kind"] == "mkmag" and d["moved"]:
            P = self._mag_new_params(d)
            self._paint_mag_preview(p, cv, P)
            self.lbl_coords.setText(_t("yarıçap {r} pt · büyütme {z}", r=f"{P['r']:.1f}", z=pdf_markup.zoom_text(P['zoom'])))
        # yeni bulanik alan onizlemesi (canli)
        if d and d["moved"] and d["kind"] == "mkdraw" and self.mk_tool == "blur":
            r = self._drag_box(d)
            st = self.mk_style["blur"]
            if r.width >= 1 and r.height >= 1:
                self._paint_blur_select(p, cv, r, st.get("bmode", "blur"), st.get("level", 5))
            self.lbl_coords.setText(f"{r.width:.1f} × {r.height:.1f} pt")
            return
        # yeni cizim onizlemesi (secili stil ile)
        if d and d["moved"] and d["kind"] in ("mkdraw", "mknote"):
            kind = self.mk_tool
            st = self.mk_style[kind]
            col = QColor.fromRgbF(*st["color"])
            col.setAlphaF(max(0.2, st.get("opacity", 1.0)))
            a, b = d["start"], d["cur"]
            if kind in ("arrow", "line"):
                P = params_from("arrow", st, {"p1": [a.x, a.y], "p2": [b.x, b.y]})
                self._mk_draw_arrow(p, cv, a, b, col, st["width"],
                                    "none" if kind == "line" else st["head"], P)
                self.lbl_coords.setText(_t("uzunluk {L} pt · açı {a}°", L=f"{abs(b - a):.1f}",
                                           a=f"{curve_math.angle_deg(a, b):.1f}"))
            elif kind in ("ellipse", "rect"):
                pen = QPen(col)
                pen.setWidthF(max(1.0, st["width"] * cv.zoom))
                if st.get("dashed"):
                    pen.setDashPattern([max(0.3, v / max(st["width"], 0.1))
                                        for v in curve_math.dash_array(st.get("dash") or True, st["width"])])
                r = self._drag_box(d)
                p.setPen(pen)
                if st.get("fill_on"):
                    fc = QColor.fromRgbF(*st["fill_color"])
                    fc.setAlphaF(st.get("opacity", 1.0) * 0.6)
                    p.setBrush(QBrush(fc))
                else:
                    p.setBrush(Qt.NoBrush)
                (p.drawEllipse if kind == "ellipse" else p.drawRect)(cv.rect_px(r))
                self.lbl_coords.setText(f"{r.width:.1f} × {r.height:.1f} pt")
            else:
                geom = {"pos": [b.x, b.y - st["size"]], "text": _t("Not"), "target": [a.x, a.y]}
                P = params_from("note", st, geom)
                pen = QPen(col, 1, Qt.DashLine)
                pen.setCosmetic(True)
                p.setPen(pen)
                p.setBrush(Qt.NoBrush)
                box = pdf_markup.note_geometry(P)[0]
                p.drawRect(cv.rect_px(box))
                s = pdf_markup.edge_point(box, P["target"])
                if s is not None:
                    self._mk_draw_arrow(p, cv, s, a, col, P["arrow_width"], "end", P)
