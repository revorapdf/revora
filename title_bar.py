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
from PySide6.QtWidgets import QWidget, QHBoxLayout, QAbstractButton, QToolTip, QDialog, QDialogButtonBox
from PySide6.QtGui import QPainter, QColor, QPen, QPixmap, QFont, QPainterPath
from PySide6.QtCore import Qt, Signal, QRect, QRectF, QPoint, QPointF, QSize, QEvent, QObject, QTimer
import win_frame
from i18n import _t

BAR_H = 40          # serit yuksekligi
TAB_H = 32          # sekme yuksekligi (alta yasli; ustte pencereyi boyutlandirma payi kalir)
HOME_W = 46         # logo (baslangic) dugmesinin kapladigi genislik
PLUS_W = 38         # "+" dugmesinin kapladigi genislik
TAB_MAX = 226
TAB_LEAD = -1       # ilk sekme sol menunun kenar cizgisine YAPISIK baslar (sol kenari o cizginin devami)
CORNER_R = 9        # ilk sekme secili degilken arac cubugunun sol ust kosesindeki kavis (CornerPiece)
TAB_MIN = 44
DRAG_MIN = 90       # sekmeler ne kadar cogalirsa cogalsin surukleme icin kalan bos alan
BTN_W = 46          # pencere dugmesi genisligi (Windows olcusu)

_DEFAULT = {"bg": "#1b1b1b", "surface": "#2c2c2c", "border": "#323232", "text": "#ededed",
            "text2": "#b4b4b4", "muted": "#7a7a7a", "tool_hover": "#303030", "tool_press": "#363636",
            "side": "#212121", "bar": "#262626"}
BACK_W = 96         # acilis ekraninda "Geri" dugmesinin genisligi


class LogoCache:
    """Logonun EKRANA GIDECEK hali: kaynak (256 x 256), cizilecegi fiziksel boyuta (mantiksal boyut
    x ekran olcegi) bir kez SmoothTransformation ile kucultulur ve saklanir.
    Kaynagi dogrudan 19 x 19'a cizdirmek (drawPixmap, 13 kat kucultme) kenarlari basamakli
    yapiyordu: boyayici o oranda yalniz komsu pikselleri karistirir, aradaki 12 pikseli atlar.
    pixmap(olcek): olcek degismedikce AYNI nesneyi verir (her cizimde yeniden olcekleme yok);
    pencere baska olcekli ekrana gecince yenisi hazirlanir."""

    def __init__(self, source, size):
        self.source, self.size = source, size
        self._dpr, self._pm = None, None

    def pixmap(self, dpr):
        if self._pm is None or self._dpr != dpr:
            px = max(1, int(round(self.size * dpr)))
            im = self.source.toImage().scaled(px, px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            pm = QPixmap.fromImage(im)
            pm.setDevicePixelRatio(dpr)
            self._dpr, self._pm = dpr, pm
        return self._pm

    def draw(self, p, x, y, dpr):
        """Logoyu (x, y) noktasina ciz. Hazir pixmap ekran pikseliyle BIRE BIR konur (yeniden
        olceklenmez, ekran pikseline oturur): %125 / %150 gibi kesirli olceklerde ikinci bir
        yumusatma bulaniklik yapardi. Boyut tam ekran pikseline yuvarlandigi icin mantiksal olcu
        o olceklerde 19 yerine 19,2 / 18,7 olur (gozle ayirt edilmez)."""
        pm = self.pixmap(dpr)
        smooth = p.testRenderHint(QPainter.SmoothPixmapTransform)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        p.drawPixmap(QPointF(x, y), pm)
        p.setRenderHint(QPainter.SmoothPixmapTransform, smooth)


class TabStrip(QWidget):
    currentChanged = Signal(int)            # kullanici secti: sekme sirasi, -1 = baslangic
    closeRequested = Signal(int)
    moved = Signal(int, int)                # (eski_sira, yeni_sira): surukleyerek siralandi
    newRequested = Signal()                 # "+"
    contextRequested = Signal(int, QPoint)  # sag tik: (sekme, ekran konumu)
    backRequested = Signal()                # acilis ekranindaki "Geri": acik belgeye don
    cornerChanged = Signal(bool)            # arac cubugunun sol ust kosesi kavisli mi (bkz. CornerPiece)
    hoverChanged = Signal()                 # fare baska bir sekmenin / dugmenin ustune gecti

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
        self._logo_cache = LogoCache(self._logo, 19)
        self.home_w = HOME_W                # logo (baslangic) dugmesinin genisligi; genisse yaninda marka adi
        self.logo_external = False          # True: logoyu LogoPiece cizer (serit yalniz tiklamayi alir)
        self.logo_x = 20                    # o durumda logonun sol kenari (tiklama alani icin)
        self.logo_w = 19                    # ... ve genisligi (yaninda marka adi varsa o dahil)
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
            self._relayout()
            if self.parentWidget() is not None:
                self.parentWidget().update()        # (serit zemini acilis ekraninda farkli)

    def home_mode(self):
        """ACILIS EKRANI: sekmeler ve "+" gorunmez (acilis ayri bir ekran; kullanici: "ust
        sekmeleri niye goruyorum"). Acik belge varsa solda "Geri" dugmesi."""
        return self.current == -1

    def count(self):
        return len(self.tabs)

    def set_colors(self, colors):
        self.colors = {**_DEFAULT, **colors}
        self.update()

    def set_home_width(self, w):
        """Marka alani (logo + ad): sol menuyle ayni genislikte tutulur, sekmeler onun saginda baslar."""
        if w != self.home_w:
            self.home_w = int(w)
            self._relayout()

    def set_available(self, width):
        if width != self._avail:
            self._avail = width
            self._relayout()

    # ---------------------------------------------------------------- yerlesim
    def tab_w(self):
        n = len(self.tabs)
        if not n:
            return 0
        return int(max(TAB_MIN, min(TAB_MAX, (self._avail - self.home_w - PLUS_W) / n)))

    def _relayout(self):
        if self.home_mode():
            self.setFixedWidth(BACK_W + 16 if self.tabs else 1)
        else:
            self.setFixedWidth(self.home_w + TAB_LEAD + len(self.tabs) * self.tab_w() + PLUS_W)
        self.update()

    def home_rect(self):
        if self.home_mode():                 # "Geri" dugmesi
            return QRect(8, (BAR_H - 30) // 2 + 1, BACK_W, 30)
        if self.logo_external:               # logo ayri parca (LogoPiece): tiklama alani onun cevresi
            return QRect(max(0, self.logo_x - 7), 8, self.logo_w + 14, BAR_H - 8)
        return QRect(max(2, min(11, (self.home_w - 36) // 2)), (BAR_H - 30) // 2 + 1, 36, 30)

    def tab_rect(self, i):
        return QRect(self.home_w + TAB_LEAD + i * self.tab_w(), BAR_H - TAB_H, self.tab_w(), TAB_H)

    def close_rect(self, i):
        r = self.tab_rect(i)
        return QRect(r.right() - 33, r.center().y() - 9, 18, 18)

    def plus_rect(self):
        return QRect(self.home_w + TAB_LEAD + len(self.tabs) * self.tab_w() + 9, (BAR_H - 26) // 2 + 3, 26, 26)

    def _has_close(self, i):
        """Dar sekmede carpiya yer yok: yalnizca secili sekmede gosterilir."""
        return self.tab_w() >= 76 or i == self.current

    def hit(self, pos):
        if self.home_mode():
            return ("home",) if self.tabs and self.home_rect().contains(pos) else None
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
                if self.home_mode():
                    self.backRequested.emit()
                else:
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
            self.hoverChanged.emit()
            if self.logo_external:           # (logonun cevresinde kutu yok: tiklanabildigini imlec soyler)
                if h == ("home",) and not self.home_mode():
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.unsetCursor()

    def _drag_to(self, x):
        d, tw, n = self._drag, self.tab_w(), len(self.tabs)
        x0 = self.home_w + TAB_LEAD
        d["x"] = max(x0, min(x - d["grab"], x0 + (n - 1) * tw))
        j = max(0, min(n - 1, int((d["x"] - x0 + tw / 2) // tw)))
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
            self.hoverChanged.emit()

    def event(self, e):
        if e.type() == QEvent.ToolTip:
            h = self.hit(e.pos())
            tip = ""
            if h == ("home",):
                tip = _t("Açık belgeye dön") if self.home_mode() else _t("Başlangıç")
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
    def _tab_path(r, flare=True, first=False, closed=True):
        """Sekme bicimi: hafif TRAPEZ (kenarlar capraz iner), ust koseler yuvarlak; flare: alt
        koseler disa dogru kavisle arac cubuguna akar (secili sekme). Her kose iki dogrunun
        kesisiminden yuvarlatilir -> egri kiriksiz. first: EN BASTAKI sekmenin sol kenari DUZ
        (sol menunun kenar cizgisinin devami), yalniz ust kosesi yuvarlak. closed=False: kontur
        cizgisi icin acik yol (alt kenar yok)."""
        d, rad = 6.0, 10.0
        L, Rt, top, b = float(r.left()), float(r.right()), float(r.top()), float(r.bottom())
        n = (d * d + (b - top) ** 2) ** 0.5
        ux, uy = d / n, (top - b) / n                  # egik kenar boyunca birim vektor (yukari)
        p = QPainterPath()
        if first:
            p.moveTo(L, b)
            p.lineTo(L, top + rad)
            p.quadTo(L, top, L + rad, top)
        else:
            if flare:
                p.moveTo(L - rad, b)
                p.quadTo(L, b, L + ux * rad, b + uy * rad)
            else:
                p.moveTo(L, b)
            p.lineTo(L + d - ux * rad, top - uy * rad)
            p.quadTo(L + d, top, L + d + rad, top)
        p.lineTo(Rt - d - rad, top)
        p.quadTo(Rt - d, top, Rt - d + ux * rad, top - uy * rad)
        if flare:
            p.lineTo(Rt - ux * rad, b + uy * rad)
            p.quadTo(Rt, b, Rt + rad, b)
        else:
            p.lineTo(Rt, b)
        if closed:
            p.closeSubpath()
        return p

    def paintEvent(self, e):
        c = self.colors
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        hover = self._hover or ()
        H = float(self.height())
        # ilk sekme secili (ve suruklenmiyor): sol kenari sol menunun cizgisine yapisik, kose kavisi yok
        flush = self.current == 0 and not (self._drag and self._drag["i"] == 0)
        corner = not self.home_mode() and not flush
        if corner != getattr(self, "_corner_on", None):
            self._corner_on = corner
            QTimer.singleShot(0, lambda on=corner: self.cornerChanged.emit(on))

        # --- logo: baslangic ekrani
        hr = QRectF(self.home_rect())
        if self.home_mode():                 # acilis ekrani: yalniz "Geri" (acik belge varsa)
            if self.tabs:
                if hover == ("home",):
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(c["tool_hover"]))
                    p.drawRoundedRect(hr, 8, 8)
                col = QColor(c["text"] if hover == ("home",) else c["text2"])
                p.setPen(QPen(col, 1.5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                m = QPointF(hr.left() + 17, hr.center().y())
                p.drawLine(QPointF(m.x() + 3, m.y() - 5), QPointF(m.x() - 2, m.y()))
                p.drawLine(QPointF(m.x() - 2, m.y()), QPointF(m.x() + 3, m.y() + 5))
                bf = QFont(self.font())
                bf.setPointSizeF(9.5)
                p.setFont(bf)
                p.setPen(col)
                p.drawText(QRectF(hr.left() + 30, hr.top(), hr.width() - 34, hr.height()),
                           Qt.AlignVCenter | Qt.AlignLeft, _t("Geri"))
            p.end()
            return
        wide = self.home_w >= 48             # (dar menude de kenar cizgisi yukari devam eder)
        if hover == ("home",) and not self.logo_external:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["tool_hover"]))
            p.drawRoundedRect(hr, 8, 8)
        if not self._logo.isNull() and not self.logo_external:
            s = self._logo_cache.size
            self._logo_cache.draw(p, hr.center().x() - s / 2, hr.center().y() - s / 2, self.devicePixelRatioF())
        # KONTUR: sol menunun kenar cizgisi tepeye CIKMAZ; seridin altindan saga gider, secili
        # sekmenin cevresinden dolanir (ilk sekme seciliyse dogrudan onun duz sol kenarina baglanir)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawLine(QPointF(self.home_w - 0.5 if flush else self.home_w + CORNER_R - 1, H - 0.5),
                   QPointF(self.width(), H - 0.5))

        # --- sekmeler (suruklenen en ustte)
        f = QFont(self.font())
        f.setPointSizeF(9.0)
        p.setFont(f)
        # sira: once secili olmayanlar (uzerine gelinenin dolgusu secili sekmenin kavisini ortmesin),
        # sonra secili sekme, en ustte suruklenen
        drag_i = self._drag["i"] if self._drag else -1
        order = [i for i in range(len(self.tabs)) if i != drag_i and i != self.current]
        if 0 <= self.current < len(self.tabs) and self.current != drag_i:
            order.append(self.current)
        if self._drag:
            order.append(drag_i)
        tw = self.tab_w()
        for i in order:
            title, _tip, dirty = self.tabs[i]
            r = QRectF(self.tab_rect(i))
            if self._drag and self._drag["i"] == i:
                r.moveLeft(self._drag["x"])
            sel = i == self.current
            hov = len(hover) == 2 and hover[1] == i
            if sel:
                first = i == 0 and flush
                # (yarim piksele oturtulur: 1 px kontur keskin; alt kenar seridin alt cizgisinde)
                s = QRectF(r.left() + (0.5 if first else 1.5), r.top() + 0.5,
                           r.width() - (2.0 if first else 3.0), H - 1.0 - r.top())
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["bar"]))
                p.drawPath(self._tab_path(s, first=first))
                x0 = s.left() + 0.5 if first else s.left() - 10.0       # sekmenin altinda cizgi yok
                p.fillRect(QRectF(x0, H - 1.0, s.right() + 10.0 - x0, 1.0), QColor(c["bar"]))
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(c["border"]), 1))
                p.drawPath(self._tab_path(s, first=first, closed=False))
            elif hov:
                # uzerine gelinen sekme: secili sekmeyle AYNI boy, alt cizgiye kadar dolu (altta bos
                # serit kalmaz); en bastaki sekmenin sol kenari burada da duz
                first = i == 0 and not (self._drag and self._drag["i"] == 0)
                s = QRectF(r.left() + (0.5 if first else 1.5), r.top() + 0.5,
                           r.width() - (2.0 if first else 3.0), H - 1.5 - r.top())
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(c["tool_hover"]))
                p.drawPath(self._tab_path(s, flare=False, first=first))
            elif i + 1 != self.current and i + 1 < len(self.tabs) and not (len(hover) == 2 and hover[1] == i + 1):
                p.setPen(QPen(QColor(c["border"]), 1))          # komsu sekmeler arasi ince ayirac
                p.drawLine(QPointF(r.right(), r.top() + 9), QPointF(r.right(), r.bottom() - 8))
            show_x = self._has_close(i) and (sel or hov)
            show_dot = dirty and not (show_x and hover == ("close", i))
            pad_r = 30 if (show_x or dirty) and tw >= 60 else 10
            p.setPen(QColor(c["text"] if sel else c["muted"]))
            tr = r.adjusted(20, 0, -pad_r - 6, 0)
            if tr.width() > 14:
                p.drawText(tr, Qt.AlignVCenter | Qt.AlignLeft,
                           p.fontMetrics().elidedText(title, Qt.ElideRight, int(tr.width())))
            cr = QRectF(r.right() - 33, r.center().y() - 9, 18, 18)
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
        # acilis ekraninda serit o ekranin PARCASI (ayni zemin; pencere dugmeleri ona ait gorunur)
        p.fillRect(self.rect(), QColor(self.colors["bg" if self.strip.home_mode() else "side"]))
        if not self.strip.home_mode():       # kontur sekmelerin saginda da seridin altindan devam eder
            p.setPen(QPen(QColor(self.colors["border"]), 1))
            y = self.height() - 0.5
            p.drawLine(QPointF(self.strip.geometry().right(), y), QPointF(self.width(), y))
        p.end()


class LogoPiece(QWidget):
    """Sol ustteki logo. Ustteki boslugu soldaki bosluguna ESIT olsun diye baslik seridinin (40 px)
    ortasinda degil, daha asagida durur ve seridin altina biraz tasar; o yuzden seridin icinde
    cizilmez, ustte duran ayri bir parcadir. Fareyi engellemez (tiklama alttaki seride gecer).
    Yeri: place(sol, ust) = gorselin DOLU kisminin (murekkebinin) sol ve ust kenari."""
    S = 19

    def __init__(self, parent, strip):
        super().__init__(parent)
        self._pm = strip._logo
        self._cache = LogoCache(self._pm, self.S)      # (ekran olcegine gore hazir, yumusak kucultulmus)
        self._strip = strip                  # (renkler: yazi rengi temadan)
        self._name = ""                      # logonun yanindaki marka adi (dar menude bos)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(self.S + 3, self.S + 3)
        self._fx = self._fy = 0.0
        # gorselin kenarinda saydam pay olabilir: dolu kismin basladigi yer (S x S olceginde)
        self._ink = (0, 0)
        if not self._pm.isNull():
            im = self._pm.toImage().scaled(self.S, self.S, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
            xs = [x for x in range(im.width()) if any(im.pixelColor(x, y).alpha() > 110 for y in range(im.height()))]
            ys = [y for y in range(im.height()) if any(im.pixelColor(x, y).alpha() > 110 for x in range(im.width()))]
            if xs and ys:
                self._ink = (xs[0], ys[0])
        self.hide()

    def _font(self):
        f = QFont(self.font())
        f.setPointSizeF(11.5)
        f.setWeight(QFont.DemiBold)
        return f

    def set_name(self, text):
        """Logonun yanina marka adi (genis menude "Revora"; dar menude bos = yalniz logo)."""
        if text != self._name:
            self._name = text
            from PySide6.QtGui import QFontMetrics
            extra = (10 + QFontMetrics(self._font()).horizontalAdvance(text) + 4) if text else 0
            self.setFixedSize(self.S + 3 + extra, self.S + 3)
            self.update()

    def place(self, left, top):
        x, y = left - self._ink[0], top - self._ink[1]
        self.move(int(x), int(y))
        self._fx, self._fy = x - int(x), y - int(y)
        self.update()

    def paintEvent(self, e):
        if self._pm.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._cache.draw(p, self._fx, self._fy, self.devicePixelRatioF())
        if self._name:
            p.setFont(self._font())
            p.setPen(QColor(self._strip.colors.get("text", "#ededed")))
            p.drawText(QRectF(self._fx + self.S + 10, self._fy - 1, self.width(), self.S + 1),
                       Qt.AlignVCenter | Qt.AlignLeft, self._name)
        p.end()


class CornerPiece(QWidget):
    """Arac cubugunun SOL UST kosesindeki kavis. Ilk sekme secili degilken kontur, sol menunun
    kenar cizgisinden yukari cikip burada saga doner (seridin altindan sekmelere dogru). Kavis
    baslik seridinin son satiri ile sol menunun son sutununa tasar; o yuzden ayri, ustte duran
    kucuk bir parca (fareyi engellemez). Yeri: arac cubugunun sol ust kosesinin 1 px sol ustu."""
    SIZE = CORNER_R + 1

    def __init__(self, parent, bar):
        super().__init__(parent)
        self._bar = bar                      # TitleBar: renkleri ondan okur
        bar.strip.hoverChanged.connect(self.update)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.hide()

    def paintEvent(self, e):
        c = self._bar.colors
        r, n = float(CORNER_R), float(self.SIZE)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(c["side"]))
        path = QPainterPath(QPointF(0.5, n))
        path.lineTo(0.5, r + 0.5)
        path.quadTo(0.5, 0.5, r + 0.5, 0.5)
        path.lineTo(n, 0.5)
        fill = QPainterPath(path)
        fill.lineTo(n, n)
        fill.closeSubpath()
        # ilk sekmenin uzerine gelindiginde dolgusu kavisin DISINDAKI koseyi de doldurur (yoksa
        # sekmenin sol altinda, yuvarlak kosenin ustunde koyu bir bosluk kaliyordu)
        strip = self._bar.strip
        h = strip._hover
        if h is not None and h[0] in ("tab", "close") and h[1] == 0 and not strip._drag:
            wedge = QPainterPath()
            wedge.addRect(QRectF(0.5, 0.0, n - 0.5, n))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["tool_hover"]))
            p.drawPath(wedge.subtracted(fill))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(c["bar"]))
        p.drawPath(fill)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.drawPath(path)
        p.end()


# =====================================================================================
# Iletisim kutulari (Ayarlar, soru kutulari, Birlestir ...): ayni duz baslik
# =====================================================================================
def run_modal(win, *args):
    """Kipli pencereyi ya da sag tik menusunu calistirir (exec) ve kapaninca BELLEKTEN
    KALDIRIR. Duz "pencere.exec" yazma: ana pencerenin cocugu olarak kurulan pencere kapaninca
    yok olmaz, gorunmeden yasar; gorunum degisince Qt onu da yeniden bicimlendirir. (Ayarlar her
    acilista 466 parcalik yeni bir kopya birakiyordu: bes ac-kapattan sonra gorunum degistirmek
    0,2 sn yerine 1,5 sn suruyordu.)
    Silme ertelenir (deleteLater): cagiran, exec dondukten sonra pencerenin secimlerini okuyabilir;
    nesne ancak o islem bitip ana dongüye donulunce yok olur. Surekli yasayan menulerde KULLANMA."""
    try:
        return win.exec(*args)
    finally:
        win.deleteLater()


class _ActionButtons(QDialogButtonBox):
    def __init__(self, primary, cancel):
        super().__init__()
        self._primary = primary
        self.addButton(primary, QDialogButtonBox.AcceptRole)
        self.addButton(cancel, QDialogButtonBox.RejectRole)

    def showEvent(self, ev):
        super().showEvent(ev)
        # Qt, pencerede baska bir dugme varsayilani once kaptiysa islem dugmesine vermez
        # (PDF bol, Imza): Enter her pencerede ISLEM dugmesidir.
        self._primary.setDefault(True)


def action_buttons(primary, cancel):
    """Pencerenin altindaki "islem + Vazgec" cifti, PLATFORMUN sirasiyla: Windows'ta islem solda,
    Vazgec sagda; macOS'ta tersi. Sira elle verilmez -> butun pencereler ve soru kutulari ayni
    sirayi izler (elle dizilen pencerelerde islem sagda, digerlerinde soldaydi). Dugmeleri
    cagiran kurar (yazi, ikon, baglanti); islem dugmesi Enter'in varsayilani olur."""
    return _ActionButtons(primary, cancel)


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
        p.fillRect(self.rect(), QColor(c["side"]))
        f = QFont(self.font())
        f.setPointSizeF(10.0)
        f.setWeight(QFont.DemiBold)
        p.setFont(f)
        p.setPen(QColor(c["text"]))
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
                    if parts[0] is not None:
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
            # Ilerleme penceresi (QProgressDialog) parcalarini KENDI yerlestirir, ic bosluklari
            # dikkate almaz: baslik seridi yazisinin ustune biniyordu (yazi yarim gorunuyordu).
            # Gecici bir kutu oldugu icin baslik seridi konmaz, yalniz ince cerceve.
            from PySide6.QtWidgets import QProgressDialog
            bare = isinstance(dlg, QProgressDialog)
            title = None if bare else DialogTitle(dlg, self.colors)
            border = _DialogBorder(dlg, self.colors)
            dlg._rv_chrome = (title, border)
            if not bare:
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
        try:                                   # ana dugme acik dolgulu (QSS: QPushButton#primary)
            from PySide6.QtWidgets import QDialogButtonBox
            for bb in QWidget.findChildren(dlg, QDialogButtonBox):
                for b in bb.buttons():
                    if bb.buttonRole(b) in (QDialogButtonBox.AcceptRole, QDialogButtonBox.YesRole,
                                            QDialogButtonBox.ApplyRole) and not b.objectName():
                        b.setObjectName("primary")
                        b.style().unpolish(b)
                        b.style().polish(b)
        except Exception:
            pass
        try:
            self._modernize(dlg)
        except Exception:
            pass

    def _modernize(self, dlg):
        """Soru / bilgi kutularinda Windows'un eski ikonlari yok (uyari ve hata: duz cizgi ikon);
        ana dugmeyle ayni satirdaki dugmeler AYNI genislikte (biri uzun biri kisa durmasin)."""
        from PySide6.QtWidgets import QMessageBox, QPushButton, QBoxLayout
        if isinstance(dlg, QMessageBox):
            kind = QMessageBox.icon(dlg)
            if kind in (QMessageBox.Question, QMessageBox.Information):
                QMessageBox.setIcon(dlg, QMessageBox.NoIcon)
            elif kind in (QMessageBox.Warning, QMessageBox.Critical):
                try:
                    import qtawesome as qta
                    col = self.colors.get("danger", "#f07171") if kind == QMessageBox.Critical else "#e0b25a"
                    QMessageBox.setIconPixmap(dlg, qta.icon("ph.warning-circle", color=col).pixmap(QSize(30, 30)))
                except Exception:
                    pass
            # (ikon degisince Qt yerlesimi YENIDEN kurar: bosluklar ondan sonra verilir)
            lay = QWidget.layout(dlg)                  # ferah ic bosluk (yazi kenara yapisik durmasin)
            if lay is not None:
                lay.setContentsMargins(18, 10, 18, 16)
                if hasattr(lay, "setVerticalSpacing"):
                    lay.setVerticalSpacing(12)
                    lay.setHorizontalSpacing(0 if QMessageBox.iconPixmap(dlg).isNull() else 12)

        def row_of(layout, target):
            if layout is None:
                return None
            for i in range(layout.count()):
                it = layout.itemAt(i)
                if it.widget() is target:
                    return layout
                if it.layout() is not None:
                    r = row_of(it.layout(), target)
                    if r is not None:
                        return r
            return None

        for b in QWidget.findChildren(dlg, QPushButton):
            if b.objectName() != "primary" or b.parentWidget() is None:
                continue
            row = row_of(QWidget.layout(b.parentWidget()), b)
            if not isinstance(row, QBoxLayout) or row.direction() in (QBoxLayout.TopToBottom, QBoxLayout.BottomToTop):
                continue
            peers = [row.itemAt(i).widget() for i in range(row.count())]
            peers = [x for x in peers if isinstance(x, QPushButton) and x.text().strip() and not x.isCheckable()
                     and x.objectName() in ("", "primary", "danger")]
            if peers:                          # (tek dugme de cok dar kalmasin)
                w = max([96] + [x.sizeHint().width() for x in peers])
                for x in peers:
                    x.setMinimumWidth(w)

    def _attach(self, dlg):
        title = dlg._rv_chrome[0]
        ref = dlg

        def caption(pos, t=title):
            return t is not None and t.is_caption(t.mapFrom(t.parentWidget(), pos))

        def resizable(d=ref):
            return (QWidget.minimumWidth(d) < QWidget.maximumWidth(d)
                    or QWidget.minimumHeight(d) < QWidget.maximumHeight(d))
        if QWidget.testAttribute(dlg, Qt.WA_WState_Created):
            win_frame.attach_dialog(dlg, caption, resizable)

    @staticmethod
    def _place(dlg):
        title, border = dlg._rv_chrome
        w, h = QWidget.width(dlg), QWidget.height(dlg)
        if title is not None:
            title.setGeometry(1, 1, max(0, w - 2), DLG_H)
            title.raise_()
        border.setGeometry(0, 0, w, h)
        border.raise_()
