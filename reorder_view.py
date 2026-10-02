"""
reorder_view.py
---------------
iOS tarzi, surukleyerek siralanan dikey liste.

Tutulan kart KALKAR (hafif buyur, golge dusurur) ve eski yeri kapanir;
surukledikce diger kartlar kayarak birakilacak yerde BOSLUK acar; kartlarin
uzerindeki sira numaralari canli guncellenir; birakinca kart bosluga suzulerek
oturur. Liste kenarina gelince kendiliginden kayar, Esc ile vazgecilir.

Qt'nin hazir surukle-birakini (InternalMove) KULLANMAZ: o, tutulan satiri
yerinde birakip sadece bir cizgi gosteriyordu. Burada her kartin konumu
kendimiz tarafindan canlandirilir. Kartlarin nasil cizilecegi disaridan
paint_item(painter, rect, item, info) fonksiyonuyla verilir; boylece hem PDF
Birlestir listesi hem ana penceredeki sayfa kucuk resimleri ayni bileseni kullanir.
"""
from PySide6.QtWidgets import QWidget, QScrollArea, QToolTip, QApplication
from PySide6.QtGui import QPainter, QColor, QCursor, QPalette
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF, QPoint, Signal


class ReorderView(QWidget):
    moved = Signal(int, int)              # (eski_sira, yeni_sira) - kullanici surukleyip birakti
    currentChanged = Signal(int)          # kullanici bir karti secti
    activated = Signal(int)               # cift tik
    contextRequested = Signal(int, QPoint)  # sag tik: (sira ya da -1, ekran konumu)
    deleteRequested = Signal()
    filesDropped = Signal(list)           # Gezgin'den PDF birakildi (accept_files=True ise)
    actionTriggered = Signal(str, int)    # uzerine gelince cikan dugme: (anahtar, sira)

    DRAG_PX = 6       # bu kadar oynamadan surukleme baslamaz
    EDGE_PX = 40      # gorunur alanin kenarina bu kadar yaklasinca otomatik kaydir
    EASE = 0.3        # her karede hedefe kalan yolun ne kadari gidilir (yumusak kayma)

    def __init__(self, row_h, paint_item, spacing=8, margin=8, accept_files=False, focusable=True):
        super().__init__()
        self.row_h, self.spacing, self.margin = row_h, spacing, margin
        self.paint_item = paint_item
        self.items = []
        self._y = []          # her kartin o anki (canlandirilan) ust kenari
        self.current = -1
        self.hover = -1
        self._press = None    # (sira, basma_konumu, tutma_payi)
        self._drag = None     # {"src", "y", "gap", "grab"}
        self._timer = QTimer(self)
        self._timer.setInterval(16)   # ~60 kare/sn
        self._timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover)
        self.setFocusPolicy(Qt.StrongFocus if focusable else Qt.NoFocus)
        self.setAcceptDrops(accept_files)
        self.file_exts = (".pdf",)     # birakilabilecek dosya turleri
        # uzerine gelince kartin altinda cikan yuvarlak dugmeler:
        # [(anahtar, ikon_adi, ipucu, tehlikeli_mi)], ikon_fn(ad, renk) -> QIcon
        self.hover_actions = []
        self.icon_fn = None
        self.action_y = None      # dugme seridinin kart icindeki dikey merkezi (None: alt kenar)
        self._act_hover = None    # uzerindeki dugme anahtari
        self._icon_cache = {}

    def set_actions(self, actions, icon_fn, center_y=None):
        self.hover_actions, self.icon_fn, self.action_y = list(actions), icon_fn, center_y
        self._icon_cache = {}
        self.update()

    ACT = 26      # dugme capi
    ACT_GAP = 3

    def _action_rects(self, i):
        """Uzerine gelinen kartin dugmeleri: [(anahtar, QRectF), ...]"""
        if not self.hover_actions or not (0 <= i < len(self.items)):
            return []
        r = self.item_rect(i)
        n = len(self.hover_actions)
        w = n * self.ACT + (n - 1) * self.ACT_GAP
        cy = r.y() + (self.action_y if self.action_y is not None else r.height() - self.ACT / 2 - 2)
        x = r.center().x() - w / 2
        return [(a[0], QRectF(x + k * (self.ACT + self.ACT_GAP), cy - self.ACT / 2, self.ACT, self.ACT))
                for k, a in enumerate(self.hover_actions)]

    def _action_at(self, pos):
        if self._drag or self.hover < 0:
            return None
        p = QPointF(pos)
        for key, rr in self._action_rects(self.hover):
            if rr.adjusted(-1, -1, 1, 1).contains(p):
                return key
        return None

    # ------------------------------------------------------------ geometri
    @property
    def pitch(self):
        return self.row_h + self.spacing

    def slot_y(self, j):
        return self.margin + j * self.pitch

    def _relayout(self):
        n = len(self.items)
        self.setMinimumHeight(int(2 * self.margin + max(0, n * self.pitch - self.spacing)))

    def _targets(self):
        """(hedef_y listesi, her kartin gorsel sirasi). Surukleme varken tutulan
        kart listeden cikmis sayilir ve 'gap' sirasinda bosluk acilir."""
        n = len(self.items)
        d = self._drag
        if d is None:
            return [self.slot_y(i) for i in range(n)], list(range(n))
        t, slots, k = [0.0] * n, [0] * n, 0
        for i in range(n):
            if i == d["src"]:
                continue
            j = k if k < d["gap"] else k + 1
            t[i], slots[i] = self.slot_y(j), j
            k += 1
        t[d["src"]], slots[d["src"]] = d["y"], d["gap"]
        return t, slots

    def item_rect(self, i):
        return QRectF(self.margin, self._y[i], self.width() - 2 * self.margin, self.row_h)

    def index_at(self, pos):
        p = QPointF(pos)
        for i in range(len(self.items)):
            if self._drag and i == self._drag["src"]:
                continue
            if self.item_rect(i).contains(p):
                return i
        return -1

    # ------------------------------------------------------------ disaridan kullanim
    def count(self):
        return len(self.items)

    def item(self, i):
        return self.items[i]

    def set_items(self, items, current=-1):
        self._drag = self._press = None
        self.items = list(items)
        self._y = [self.slot_y(i) for i in range(len(self.items))]
        self.current = current if 0 <= current < len(self.items) else -1
        self._relayout()
        self.update()

    def add_item(self, item, select=True):
        self.items.append(item)
        self._y.append(self.slot_y(len(self.items) - 1))
        self._relayout()
        if select:
            self.set_current(len(self.items) - 1, emit=True)
        self.update()

    def remove(self, i):
        if not (0 <= i < len(self.items)):
            return
        self.items.pop(i)
        self._y.pop(i)
        if self.current > i:
            self.current -= 1
        self.current = min(self.current, len(self.items) - 1)   # silinen sondaysa bir oncekine
        self._relayout()
        self._kick()
        self.currentChanged.emit(self.current)

    def move(self, src, dst):
        """Programla tasima (yukari/asagi butonlari): kart yeni yerine kayarak gider."""
        n = len(self.items)
        if src == dst or not (0 <= src < n and 0 <= dst < n):
            return
        self.items.insert(dst, self.items.pop(src))
        self._y.insert(dst, self._y.pop(src))
        c = self.current
        if c == src:
            self.current = dst
        elif src < c <= dst:
            self.current = c - 1
        elif dst <= c < src:
            self.current = c + 1
        self._kick()

    def update_item(self, i, item):
        if 0 <= i < len(self.items):
            self.items[i] = item
            self.update()

    def set_current(self, i, emit=False):
        if i != self.current:
            self.current = i
            self.update()
            if emit:
                self.currentChanged.emit(i)
        self.ensure_visible(i)

    def ensure_visible(self, i):
        sa = self._scroll_area()
        if sa is not None and 0 <= i < len(self.items):
            sa.ensureVisible(int(self.width() / 2), int(self.slot_y(i) + self.row_h / 2),
                             0, int(self.row_h / 2 + self.margin))

    def _scroll_area(self):
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        return w

    # ------------------------------------------------------------ canlandirma
    def _kick(self):
        if not self._timer.isActive():
            self._timer.start()
        self.update()

    def _tick(self):
        if self._drag:
            self._autoscroll()
        t, _ = self._targets()
        moving = False
        for i in range(len(self._y)):
            if self._drag and i == self._drag["src"]:
                self._y[i] = t[i]          # tutulan kart imleci dogrudan izler
                continue
            dy = t[i] - self._y[i]
            if abs(dy) < 0.5:
                self._y[i] = t[i]
            else:
                self._y[i] += dy * self.EASE
                moving = True
        self.update()
        if not moving and not self._drag:
            self._timer.stop()

    def _autoscroll(self):
        sa = self._scroll_area()
        if sa is None:
            return
        vp = sa.viewport()
        p = vp.mapFromGlobal(QCursor.pos())
        step = 0
        if p.y() < self.EDGE_PX:
            step = -min(18, max(2, (self.EDGE_PX - p.y()) // 2))
        elif p.y() > vp.height() - self.EDGE_PX:
            step = min(18, max(2, (p.y() - (vp.height() - self.EDGE_PX)) // 2))
        if step:
            bar = sa.verticalScrollBar()
            old = bar.value()
            bar.setValue(old + step)
            if bar.value() != old:
                self._update_drag(QPointF(self.mapFromGlobal(QCursor.pos())))

    # ------------------------------------------------------------ fare / klavye
    def _update_drag(self, pos):
        d = self._drag
        n = len(self.items)
        y = pos.y() - d["grab"]
        # ilk/son yuvanin otesine tasmasin (tasarsa gorunur alanin disinda kesilir)
        y = max(self.slot_y(0) - 2, min(y, self.slot_y(n - 1) + 2))
        d["y"] = y
        g = int((y + self.row_h / 2 - self.margin + self.spacing / 2) // self.pitch)
        d["gap"] = max(0, min(n - 1, g))
        self._kick()

    def mousePressEvent(self, e):
        i = self.index_at(e.position())
        if e.button() == Qt.RightButton:
            if i >= 0:
                self.set_current(i, emit=True)
            self.contextRequested.emit(i, e.globalPosition().toPoint())
            return
        if e.button() != Qt.LeftButton:
            return
        key = self._action_at(e.position())
        if key is not None:
            self._press = None
            self.actionTriggered.emit(key, self.hover)
            return
        if i >= 0:
            self.set_current(i, emit=True)
            self._press = (i, e.position(), e.position().y() - self._y[i])
        else:
            self._press = None

    def mouseMoveEvent(self, e):
        if self._drag:
            self._update_drag(e.position())
            return
        if self._press and e.buttons() & Qt.LeftButton and len(self.items) > 1:
            i, p0, grab = self._press
            if (e.position() - p0).manhattanLength() >= self.DRAG_PX:
                self._drag = {"src": i, "y": self._y[i], "gap": i, "grab": grab}
                self.setCursor(Qt.ClosedHandCursor)
                self.grabKeyboard()        # odak almayan listede de Esc calissin
                self._update_drag(e.position())
            return
        h = self.index_at(e.position())
        if h != self.hover:
            self.hover = h
            self.update()
        key = self._action_at(e.position())
        if key != self._act_hover:
            self._act_hover = key
            self.update()
            tip = next((a[2] for a in self.hover_actions if a[0] == key), "")
            if tip:
                QToolTip.showText(e.globalPosition().toPoint(), tip, self)
            else:
                QToolTip.hideText()
        if key is not None:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.OpenHandCursor if h >= 0 and len(self.items) > 1 else Qt.ArrowCursor)

    def mouseReleaseEvent(self, e):
        self._press = None
        if self._drag:
            self._end_drag(commit=True)

    def _end_drag(self, commit):
        d, self._drag = self._drag, None
        self.releaseKeyboard()
        self.unsetCursor()
        src, gap = d["src"], d["gap"]
        self._y[src] = d["y"]            # birakildigi yerden yuvasina suzulsun
        if commit and gap != src:
            self.items.insert(gap, self.items.pop(src))
            self._y.insert(gap, self._y.pop(src))
            self.current = gap
            self._kick()
            self.moved.emit(src, gap)
        else:
            self._kick()                 # vazgecildi: eski yerine geri kayar

    def keyPressEvent(self, e):
        k = e.key()
        if self._drag:
            if k == Qt.Key_Escape:
                self._end_drag(commit=False)
            return
        if k in (Qt.Key_Delete, Qt.Key_Backspace):
            self.deleteRequested.emit()
        elif k == Qt.Key_Up and self.current > 0:
            self.set_current(self.current - 1, emit=True)
        elif k == Qt.Key_Down and self.current < len(self.items) - 1:
            self.set_current(self.current + 1, emit=True)
        else:
            super().keyPressEvent(e)

    def mouseDoubleClickEvent(self, e):
        i = self.index_at(e.position())
        if i >= 0:
            self.activated.emit(i)

    def leaveEvent(self, e):
        if self.hover != -1 and not self._drag:
            self.hover = -1
            self._act_hover = None
            self.update()

    # ------------------------------------------------------------ Gezgin'den birakma
    def _pdfs(self, mime):
        return [u.toLocalFile() for u in mime.urls() if u.toLocalFile().lower().endswith(self.file_exts)]

    def dragEnterEvent(self, e):
        if self._pdfs(e.mimeData()):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._pdfs(e.mimeData()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        paths = self._pdfs(e.mimeData())
        if paths:
            self.filesDropped.emit(paths)
            e.acceptProposedAction()

    # ------------------------------------------------------------ cizim
    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        _, slots = self._targets()
        d = self._drag
        for i, it in enumerate(self.items):
            if d and i == d["src"]:
                continue
            self.paint_item(p, self.item_rect(i), it,
                            {"number": slots[i] + 1, "selected": i == self.current and not d,
                             "hover": i == self.hover and not d, "lifted": False,
                             "actions": bool(self.hover_actions) and i == self.hover and not d})
        if d:                             # tutulan kart en ustte: buyumus + golgeli
            r = self.item_rect(d["src"])
            p.save()
            c = r.center()
            p.translate(c)
            p.scale(1.025, 1.025)
            p.translate(-c)
            p.setPen(Qt.NoPen)
            for spread, alpha in ((12, 16), (7, 26), (3, 38)):
                p.setBrush(QColor(0, 0, 0, alpha))
                p.drawRoundedRect(r.adjusted(-spread / 2, spread / 3 + 3, spread / 2, spread / 2 + 5),
                                  12, 12)
            self.paint_item(p, r, self.items[d["src"]],
                            {"number": d["gap"] + 1, "selected": True, "hover": False, "lifted": True})
            p.restore()
        elif self.hover >= 0 and self.hover_actions:
            self._paint_actions(p)
        p.end()

    def _icon_pix(self, name, color, size):
        key = (name, color.name(), size)
        if key not in self._icon_cache:
            ic = self.icon_fn(name, color.name()) if self.icon_fn else None
            self._icon_cache[key] = ic.pixmap(size, size) if ic is not None and not ic.isNull() else None
        return self._icon_cache[key]

    def _paint_actions(self, p):
        pal = QApplication.palette()
        base = pal.color(QPalette.Base)
        border = pal.color(QPalette.Mid)
        normal = pal.color(QPalette.Text)
        danger = QColor(220, 38, 38)
        acc = pal.color(QPalette.Highlight)
        for (key, rr), a in zip(self._action_rects(self.hover), self.hover_actions):
            hot = key == self._act_hover
            col = danger if a[3] else normal
            p.setPen(border if not hot else (danger if a[3] else acc))
            fill = QColor(base)
            if hot:
                fill = QColor(danger if a[3] else acc)
                fill.setAlpha(40)
                fill = QColor.fromRgbF(*(base.getRgbF()[i] * (1 - 0.16) + fill.getRgbF()[i] * 0.16
                                         for i in range(3)))
            p.setBrush(fill)
            p.drawEllipse(rr)
            pm = self._icon_pix(a[1], col, 13)
            if pm is not None:
                p.drawPixmap(QRectF(rr.center().x() - 6.5, rr.center().y() - 6.5, 13, 13), pm,
                             QRectF(pm.rect()))
