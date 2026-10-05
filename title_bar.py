"""
title_bar.py
------------
Birlesik baslik cubugu: Windows'un baslik seridi yerine uygulamanin kendi seridi.

  [logo = baslangic] [sekme] [sekme] ... [+]      <surukleme alani>      [-] [kare] [x]

- TabStrip: belge sekmeleri (kendi cizimi: duz, tek ton; secili sekme alttaki arac
  seridiyle ayni renkte -> ona "bagli" gorunur). Surukleyerek siralanir, orta tusla /
  carpiyla kapanir, kaydedilmemis belgede carpinin yerinde nokta durur.
- WinButton: kucult / buyut-geri al / kapat (Windows 10-11 olculerinde, kendi cizimi).
- TitleBar: ikisini tasir; bos kalan yer pencereyi surukleme alanidir (win_frame.py
  oraya "baslik" der: surukleme, cift tikla buyutme, kenara yaslama Windows'tan gelir).

Renkler main.py'deki tema sozlugunden (DARK / LIGHT) alinir: set_colors().
"""
# import sirasi kurali: PySide6, fitz'ten once (bu modul fitz kullanmiyor)
from PySide6.QtWidgets import QWidget, QHBoxLayout, QAbstractButton, QToolTip, QDialog
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QFont, QPainterPath
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPoint, QPointF, QSize, QEvent, QObject
import win_frame
from i18n import _t

BAR_H = 40          # serit yuksekligi
TAB_H = 32          # sekme yuksekligi (alta yasli; ustte pencereyi boyutlandirma payi kalir)
HOME_W = 46         # logo (baslangic) dugmesinin kapladigi genislik
PLUS_W = 38         # "+" dugmesinin kapladigi genislik
TAB_MAX = 210
TAB_MIN = 44
DRAG_MIN = 90       # sekmeler ne kadar cogalirsa cogalsin surukleme icin kalan bos alan
BTN_W = 46          # pencere dugmesi genisligi (Windows olcusu)

_DEFAULT = {"bg": "#17181b", "surface": "#26282c", "border": "#33363c", "text": "#e6e8eb",
            "text2": "#c4c8d0", "muted": "#9aa0a6", "tool_hover": "#2f3238", "tool_press": "#33373d"}


class TabStrip(QWidget):
    currentChanged = Signal(int)            # kullanici secti: sekme sirasi, -1 = baslangic
    closeRequested = Signal(int)
    moved = Signal(int, int)                # (eski_sira, yeni_sira): surukleyerek siralandi
    newRequested = Signal()                 # "+"
    contextRequested = Signal(int, QPoint)  # sag tik: (sekme, ekran konumu)

    def __init__(self, logo_path, parent=None):
        super().__init__(parent)
        self.tabs = []                      # [baslik, ipucu, degisti_mi]
        self.current = -1
        self.colors = dict(_DEFAULT)
        self._avail = 600                   # sekmelere ayrilabilecek en buyuk genislik
        self._hover = None                  # ("home",) | ("plus",) | ("tab", i) | ("close", i)
        self._press = None                  # (sekme, basilan x)
        self._drag = None                   # {"i": sekme, "grab": sekme icinde tutulan x, "x": sol kenar}
        self._logo = QPixmap(logo_path)
        self.setMouseTracking(True)
        self.setFixedHeight(BAR_H)
        self._relayout()

    # ---------------------------------------------------------------- icerik
    def add_tab(self, title, tip="", dirty=False):
        self.tabs.append([title, tip, dirty])
        self._relayout()
        return len(self.tabs) - 1

    def remove_tab(self, i):
        if 0 <= i < len(self.tabs):
            del self.tabs[i]
            self._drag = self._press = None
            if self.current >= len(self.tabs):
                self.current = len(self.tabs) - 1
            self._relayout()

    def set_tab(self, i, title, tip="", dirty=False):
        if 0 <= i < len(self.tabs) and self.tabs[i] != [title, tip, dirty]:
            self.tabs[i] = [title, tip, dirty]
            self.update()

    def set_current(self, i):
        if i != self.current:
            self.current = i
            self.update()

    def count(self):
        return len(self.tabs)

    def set_colors(self, colors):
        self.colors = {**_DEFAULT, **colors}
        self.update()

    def set_available(self, width):
        if width != self._avail:
            self._avail = width
            self._relayout()

    # ---------------------------------------------------------------- yerlesim
    def tab_w(self):
        n = len(self.tabs)
        if not n:
            return 0
        return int(max(TAB_MIN, min(TAB_MAX, (self._avail - HOME_W - PLUS_W) / n)))

    def _relayout(self):
        self.setFixedWidth(HOME_W + len(self.tabs) * self.tab_w() + PLUS_W)
        self.update()

    def home_rect(self):
        return QRect(6, (BAR_H - 30) // 2 + 2, 34, 30)

    def tab_rect(self, i):
        return QRect(HOME_W + i * self.tab_w(), BAR_H - TAB_H, self.tab_w(), TAB_H)

    def close_rect(self, i):
        r = self.tab_rect(i)
        return QRect(r.right() - 25, r.center().y() - 9, 18, 18)

    def plus_rect(self):
        return QRect(HOME_W + len(self.tabs) * self.tab_w() + 5, (BAR_H - 26) // 2 + 3, 26, 26)

    def _has_close(self, i):
        """Dar sekmede carpiya yer yok: yalnizca secili sekmede gosterilir."""
        return self.tab_w() >= 76 or i == self.current

    def hit(self, pos):
        if self.home_rect().adjusted(-4, -4, 4, 6).contains(pos):
            return ("home",)
        if self.plus_rect().adjusted(-3, -3, 3, 3).contains(pos):
            return ("plus",)
        for i in range(len(self.tabs)):
            if self.tab_rect(i).contains(pos):
                if self._has_close(i) and self.close_rect(i).adjusted(-2, -2, 2, 2).contains(pos):
                    return ("close", i)
                return ("tab", i)
        return None

    # ---------------------------------------------------------------- fare
    def mousePressEvent(self, e):
        h = self.hit(e.position().toPoint())
        if h is None:
            return
        if e.button() == Qt.LeftButton:
            if h[0] == "home":
                self.currentChanged.emit(-1)
            elif h[0] == "plus":
                self.newRequested.emit()
            elif h[0] == "close":
                self._press = ("close", h[1])
            else:
                i = h[1]
                self._press = (i, e.position().x())
                if i != self.current:
                    self.currentChanged.emit(i)
        elif e.button() == Qt.MiddleButton and h[0] in ("tab", "close"):
            self._press = ("mid", h[1])

    def mouseMoveEvent(self, e):
        pos = e.position().toPoint()
        if self._press and isinstance(self._press[0], int) and (e.buttons() & Qt.LeftButton):
            i, x0 = self._press
            if self._drag is None and abs(e.position().x() - x0) > 8 and len(self.tabs) > 1:
                self._drag = {"i": i, "grab": x0 - self.tab_rect(i).x(), "x": self.tab_rect(i).x()}
            if self._drag is not None:
                self._drag_to(e.position().x())
                return
        h = self.hit(pos)
        if h != self._hover:
            self._hover = h
            self.update()

    def _drag_to(self, x):
        d, tw, n = self._drag, self.tab_w(), len(self.tabs)
        d["x"] = max(HOME_W, min(x - d["grab"], HOME_W + (n - 1) * tw))
        j = max(0, min(n - 1, int((d["x"] - HOME_W + tw / 2) // tw)))
        if j != d["i"]:
            i = d["i"]
            self.tabs.insert(j, self.tabs.pop(i))
            d["i"] = j
            if self.current == i:
                self.current = j
            elif min(i, j) <= self.current <= max(i, j):
                self.current += 1 if j < i else -1
            self.moved.emit(i, j)
        self.update()

    def mouseReleaseEvent(self, e):
        press, self._press = self._press, None
        if self._drag is not None:
            self._drag = None
            self.update()
            return
        h = self.hit(e.position().toPoint())
        if not press or h is None:
            return
        if press[0] == "close" and e.button() == Qt.LeftButton and h == ("close", press[1]):
            self.closeRequested.emit(press[1])
        elif press[0] == "mid" and e.button() == Qt.MiddleButton and h[0] in ("tab", "close") and h[1] == press[1]:
            self.closeRequested.emit(press[1])

    def contextMenuEvent(self, e):
        h = self.hit(e.pos())
        if h is not None and h[0] in ("tab", "close"):
            self.contextRequested.emit(h[1], e.globalPos())

    def leaveEvent(self, e):
        if self._hover is not None:
            self._hover = None
            self.update()

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            h = self.hit(e.pos())
            tip = ""
            if h == ("home",):
                tip = _t("Başlangıç")
            elif h == ("plus",):
                tip = _t("PDF aç (Ctrl+O)")
            elif h is not None and h[0] == "close":
                tip = _t("Sekmeyi kapat (Ctrl+W)")
            elif h is not None:
                tip = self.tabs[h[1]][1] or self.tabs[h[1]][0]
            if tip:
                QToolTip.showText(e.globalPos(), tip, self)
            else:
                QToolTip.hideText()
            return True
        return super().event(e)

    # ---------------------------------------------------------------- cizim
    @staticmethod
    def _tab_path(r):
        """Ust koseleri yuvarlak sekme bicimi."""
        rad = 8.0
        x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
        p = QPainterPath(QPointF(x0, y1))
        p.lineTo(x0, y0 + rad)
        p.quadTo(x0, y0, x0 + rad, y0)
        p.lineTo(x1 - rad, y0)
        p.quadTo(x1, y0, x1, y0 + rad)
        p.lineTo(x1, y1)
        p.closeSubpath()
        return p

    def paintEvent(self, e):
        c = self.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        hover = self._hover or ()

        # --- logo: baslangic ekrani
        hr = QRectF(self.home_rect())
        if self.current == -1 or hover == ("home",):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["surface"] if self.current == -1 else c["tool_hover"]))
            p.drawRoundedRect(hr, 8, 8)
        if not self._logo.isNull():
            s = 20
            p.drawPixmap(QRectF(hr.center().x() - s / 2, hr.center().y() - s / 2, s, s),
                         self._logo, QRectF(self._logo.rect()))

        # --- sekmeler (suruklenen en ustte)
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        p.setFont(f)
        order = [i for i in range(len(self.tabs)) if not (self._drag and self._drag["i"] == i)]
        if self._drag:
            order.append(self._drag["i"])
        tw = self.tab_w()
        for i in order:
            title, _tip, dirty = self.tabs[i]
            r = QRectF(self.tab_rect(i))
            if self._drag and self._drag["i"] == i:
                r.moveLeft(self._drag["x"])
            sel = i == self.current
            hov = len(hover) == 2 and hover[1] == i
            if sel or hov:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["surface"] if sel else c["tool_hover"]))
                p.drawPath(self._tab_path(r.adjusted(1, 0, -1, 1) if sel else r.adjusted(1, 3, -1, -3)))
            elif i + 1 != self.current and i + 1 < len(self.tabs) and not (len(hover) == 2 and hover[1] == i + 1):
                p.setPen(QPen(QColor(c["border"]), 1))          # komsu sekmeler arasi ince ayirac
                p.drawLine(QPointF(r.right(), r.top() + 9), QPointF(r.right(), r.bottom() - 8))
            show_x = self._has_close(i) and (sel or hov)
            show_dot = dirty and not (show_x and hover == ("close", i))
            pad_r = 30 if (show_x or dirty) and tw >= 60 else 10
            p.setPen(QColor(c["text"] if sel else c["muted"]))
            tr = r.adjusted(12, 0, -pad_r, 0)
            if tr.width() > 14:
                p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft,
                           p.fontMetrics().elidedText(title, Qt.ElideRight, int(tr.width())))
            cr = QRectF(r.right() - 25, r.center().y() - 9, 18, 18)
            if show_dot and (tw >= 60 or sel):
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["text2"] if sel else c["muted"]))
                p.drawEllipse(cr.center(), 3.2, 3.2)
            elif show_x:
                if hover == ("close", i):
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(c["tool_press"] if sel else c["border"]))
                    p.drawRoundedRect(cr, 5, 5)
                p.setPen(QPen(QColor(c["text"] if hover == ("close", i) else c["muted"]), 1.3, Qt.SolidLine,
                              Qt.RoundCap))
                m = cr.center()
                p.drawLine(QPointF(m.x() - 3.6, m.y() - 3.6), QPointF(m.x() + 3.6, m.y() + 3.6))
                p.drawLine(QPointF(m.x() + 3.6, m.y() - 3.6), QPointF(m.x() - 3.6, m.y() + 3.6))

        # --- "+"
        pr = QRectF(self.plus_rect())
        if hover == ("plus",):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["tool_hover"]))
            p.drawRoundedRect(pr, 7, 7)
        p.setPen(QPen(QColor(c["text2"] if hover == ("plus",) else c["muted"]), 1.4, Qt.SolidLine, Qt.RoundCap))
        m = pr.center()
        p.drawLine(QPointF(m.x() - 5, m.y()), QPointF(m.x() + 5, m.y()))
        p.drawLine(QPointF(m.x(), m.y() - 5), QPointF(m.x(), m.y() + 5))
        p.end()


class WinButton(QAbstractButton):
    """Pencere dugmesi: kind = "min" | "max" | "close" (max: buyukken "geri al" simgesi)."""

    def __init__(self, kind, tip, parent=None, size=None):
        super().__init__(parent)
        self.kind = kind
        self.maximized = False
        self.colors = dict(_DEFAULT)
        self.setToolTip(tip)
        self.setFixedSize(*(size or (BTN_W, BAR_H)))
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)

    def paintEvent(self, e):
        c = self.colors
        p = QPainter(self)
        hov, down = self.underMouse(), self.isDown()
        fg = QColor(c["text2"])
        if hov or down:
            if self.kind == "close":
                p.fillRect(self.rect(), QColor("#b3261e" if down else "#e81123"))
                fg = QColor("#ffffff")
            else:
                p.fillRect(self.rect(), QColor(c["tool_press"] if down else c["tool_hover"]))
        m = QPointF(self.width() / 2, self.height() / 2)
        pen = QPen(fg, 1.0)
        p.setPen(pen)
        s = 5                                              # simgenin yari boyu (10 px, Windows'taki gibi)
        if self.kind == "min":
            p.drawLine(QPointF(m.x() - s, m.y() + 0.5), QPointF(m.x() + s, m.y() + 0.5))
        elif self.kind == "max" and not self.maximized:
            p.drawRect(QRectF(m.x() - s + 0.5, m.y() - s + 0.5, 2 * s - 1, 2 * s - 1))
        elif self.kind == "max":                           # geri al: ust uste iki kare
            p.drawRect(QRectF(m.x() - s + 0.5, m.y() - s + 2.5, 2 * s - 3, 2 * s - 3))
            p.drawLine(QPointF(m.x() - s + 2.5, m.y() - s + 2.5), QPointF(m.x() - s + 2.5, m.y() - s + 0.5))
            p.drawLine(QPointF(m.x() - s + 2.5, m.y() - s + 0.5), QPointF(m.x() + s - 0.5, m.y() - s + 0.5))
            p.drawLine(QPointF(m.x() + s - 0.5, m.y() - s + 0.5), QPointF(m.x() + s - 0.5, m.y() + s - 2.5))
            p.drawLine(QPointF(m.x() + s - 0.5, m.y() + s - 2.5), QPointF(m.x() + s - 2.5, m.y() + s - 2.5))
        else:
            p.setRenderHint(QPainter.Antialiasing, True)
            pen.setWidthF(1.1)
            p.setPen(pen)
            p.drawLine(QPointF(m.x() - s, m.y() - s), QPointF(m.x() + s, m.y() + s))
            p.drawLine(QPointF(m.x() + s, m.y() - s), QPointF(m.x() - s, m.y() + s))
        p.end()


class TitleBar(QWidget):
    def __init__(self, logo_path, window, own_buttons=True):
        super().__init__(window)
        self._window = window
        self.colors = dict(_DEFAULT)
        self.setFixedHeight(BAR_H)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.strip = TabStrip(logo_path, self)
        lay.addWidget(self.strip)
        lay.addStretch(1)
        self.buttons = []
        if own_buttons:
            self.btn_min = WinButton("min", _t("Simge durumuna küçült"), self)
            self.btn_max = WinButton("max", _t("Ekranı kapla"), self)
            self.btn_close = WinButton("close", _t("Kapat"), self)
            self.btn_min.clicked.connect(window.showMinimized)
            self.btn_max.clicked.connect(self.toggle_max)
            self.btn_close.clicked.connect(window.close)
            self.buttons = [self.btn_min, self.btn_max, self.btn_close]
            for b in self.buttons:
                lay.addWidget(b)

    def toggle_max(self):
        w = self._window
        if hasattr(w, "toggle_maximized"):     # cercevesiz pencerede Windows'un kendi komutu
            w.toggle_maximized()
        else:
            w.showNormal() if w.isMaximized() else w.showMaximized()

    def set_maximized(self, on):
        if self.buttons:
            self.btn_max.maximized = bool(on)
            self.btn_max.setToolTip(_t("Önceki boyut") if on else _t("Ekranı kapla"))
            self.btn_max.update()

    def set_colors(self, colors):
        self.colors = {**_DEFAULT, **colors}
        self.strip.set_colors(colors)
        for b in self.buttons:
            b.colors = self.colors
            b.update()
        self.update()

    def is_caption(self, pos):
        """pos (bu seridin koordinati) bos surukleme alaninda mi? Sekmeler ve dugmeler degil."""
        if not self.rect().contains(pos):
            return False
        if self.strip.geometry().contains(pos):
            return False
        return not any(b.geometry().contains(pos) for b in self.buttons)

    def resizeEvent(self, e):
        self.strip.set_available(self.width() - len(self.buttons) * BTN_W - DRAG_MIN)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self.colors["bg"]))
        p.end()


# =====================================================================================
# Iletisim kutulari (Ayarlar, soru kutulari, Birlestir ...): ayni duz baslik
# =====================================================================================
DLG_H = 36          # kutu basliginin yuksekligi


class DialogTitle(QWidget):
    """Kutunun ustundeki serit: baslik yazisi + kapat. Bos yeri kutuyu surukler."""

    def __init__(self, dlg, colors):
        super().__init__(dlg)
        self.colors = colors
        self._dlg = dlg
        self.btn_close = WinButton("close", _t("Kapat"), self, size=(42, DLG_H))
        self.btn_close.colors = colors
        self.btn_close.clicked.connect(lambda: QWidget.close(dlg))

    def is_caption(self, pos):
        return self.rect().contains(pos) and not self.btn_close.geometry().contains(pos)

    def resizeEvent(self, e):
        self.btn_close.move(self.width() - self.btn_close.width(), 0)

    def paintEvent(self, e):
        c = self.colors
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(c["bg"]))
        f = QFont(self.font())
        f.setPointSizeF(9.5)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(c["text2"]))
        r = self.rect().adjusted(16, 0, -self.btn_close.width() - 8, 0)
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft,
                   p.fontMetrics().elidedText(QWidget.windowTitle(self._dlg), Qt.ElideRight, r.width()))
        p.end()


class _DialogBorder(QWidget):
    """Kutunun cevresinde 1 piksel cizgi (fareyi engellemez)."""

    def __init__(self, dlg, colors):
        super().__init__(dlg)
        self.colors = colors
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QColor(self.colors["border_input"]))
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        p.end()


class DialogChrome(QObject):
    """Uygulama olay suzgeci: gosterilmek uzere olan her QDialog'u cercevesiz yapar ve ustune
    kendi basligimizi koyar. Kutularin kodu degismez (hazir QMessageBox, renk secici dahil).

    DIKKAT: kutunun islevleri QWidget.xxx(dlg) diye cagrilir, dlg.xxx() diye DEGIL. Bazi
    kutularda ayni adda alan var (Filigran: self.size = sayi kutusu, self.font = liste);
    dlg.size() o alani cagirmaya calisip hata veriyor, kutu basliksiz kaliyordu.

    Windows'un KENDI pencereleri (dosya sec / kaydet, yazdir) Qt'de gorunmeyen bir QDialog ile
    temsil edilir (WA_DontShowOnScreen): onlara dokunulmaz, sistemin penceresi olarak kalir."""
    _instance = None

    @classmethod
    def ensure(cls, app, colors):
        if not win_frame.ACTIVE:
            return None
        if cls._instance is None:
            win_frame.install(app)
            cls._instance = cls(app)
            app.installEventFilter(cls._instance)
        cls._instance.colors.clear()
        cls._instance.colors.update({**_DEFAULT, "border_input": "#3c3f46", **colors})
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.colors = {}                     # tek sozluk: tum kutular ayni nesneyi okur

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t == QEvent.Polish:
            if (isinstance(obj, QDialog) and QWidget.isWindow(obj) and not QWidget.property(obj, "_rvChrome")
                    and not QWidget.testAttribute(obj, Qt.WA_DontShowOnScreen)):
                self._apply(obj)
        elif t in (QEvent.Resize, QEvent.WindowTitleChange, QEvent.WinIdChange, QEvent.Show):
            parts = getattr(obj, "_rv_chrome", None) if obj.isWidgetType() else None
            if parts is not None:
                if t == QEvent.WinIdChange:
                    self._attach(obj)
                elif t == QEvent.WindowTitleChange:
                    parts[0].update()
                else:
                    self._place(obj)
        return False

    def _apply(self, dlg):
        W = QWidget
        W.setProperty(dlg, "_rvChrome", True)
        try:
            resized = W.testAttribute(dlg, Qt.WA_Resized)
            size = W.size(dlg)
            W.setWindowFlag(dlg, Qt.FramelessWindowHint, True)
            title = DialogTitle(dlg, self.colors)
            border = _DialogBorder(dlg, self.colors)
            dlg._rv_chrome = (title, border)
            m = W.contentsMargins(dlg)
            W.setContentsMargins(dlg, m.left() + 1, m.top() + DLG_H + 1, m.right() + 1, m.bottom() + 1)
            # baslik artik kutunun ICINDE: elle verilmis boyutlar baslik kadar buyur
            if W.minimumHeight(dlg) > 0:
                W.setMinimumHeight(dlg, W.minimumHeight(dlg) + DLG_H)
            if W.maximumHeight(dlg) < 16777215:
                W.setMaximumHeight(dlg, W.maximumHeight(dlg) + DLG_H)
            if resized and size.height() > 0:
                W.resize(dlg, size.width(), size.height() + DLG_H)
            self._attach(dlg)
            self._place(dlg)
        except Exception:
            pass

    def _attach(self, dlg):
        title = dlg._rv_chrome[0]
        ref = dlg

        def caption(pos, t=title):
            return t.is_caption(t.mapFrom(t.parentWidget(), pos))

        def resizable(d=ref):
            return (QWidget.minimumWidth(d) < QWidget.maximumWidth(d)
                    or QWidget.minimumHeight(d) < QWidget.maximumHeight(d))
        if QWidget.testAttribute(dlg, Qt.WA_WState_Created):
            win_frame.attach_dialog(dlg, caption, resizable)

    @staticmethod
    def _place(dlg):
        title, border = dlg._rv_chrome
        w, h = QWidget.width(dlg), QWidget.height(dlg)
        title.setGeometry(1, 1, max(0, w - 2), DLG_H)
        border.setGeometry(0, 0, w, h)
        title.raise_()
        border.raise_()
