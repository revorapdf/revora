"""
find_bar.py
-----------
Bul / Degistir: tuvalin sag ustunde yuzen cubuk (FindBar) ve ana pencereye eklenen davranis
(FindMixin). Arama motoru: pdf_search.

Cubuk her modda acilir (Ctrl+F; degistirme satiriyla Ctrl+H). Kapsam: "Bu sayfa" ya da
"Tum sayfalar" - sayac, ileri / geri ve "Tumunu" degistir bu kapsama gore calisir.
"""
import time

from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit,
                               QToolButton, QButtonGroup, QWidget, QProgressDialog)
from PySide6.QtGui import QColor, QPainter, QPen, QCursor
from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect

from i18n import _t
import markup_bar
import pdf_search

BAR_W = 384
ROW_H = 30
SLICE_MS = 12            # arka planda sayfa taramasina her turda ayrilan sure (arayuz donmasin)
HIT_FILL = QColor("#ffe066")         # eslesmeler (carpma kipinde: yazi okunur kalir)
CUR_FILL = QColor("#ffa94d")         # siradaki eslesme
CUR_LINE = QColor("#e8590c")


class _FindEdit(QLineEdit):
    """Arama kutusu: sag ucunda sayac ("2 / 5"); Enter sonraki, Shift+Enter onceki, Esc kapat."""
    enter = Signal(bool)                 # shift basili mi
    escape = Signal()

    def __init__(self, counter=False):
        super().__init__()
        self.setFixedHeight(ROW_H)
        self.setClearButtonEnabled(False)
        self.count = None
        if counter:
            self.count = QLabel(self)
            self.count.setObjectName("findCount")
            self.count.setAttribute(Qt.WA_TransparentForMouseEvents)
            self.count.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def set_count(self, text):
        self.count.setText(text)
        w = self.count.fontMetrics().horizontalAdvance(text) + 4 if text else 0
        self.setTextMargins(0, 0, w + 4 if w else 0, 0)
        self._place()

    def _place(self):
        if self.count is not None:
            w = self.count.fontMetrics().horizontalAdvance(self.count.text()) + 4
            self.count.setGeometry(self.width() - w - 9, 0, w, self.height())

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._place()

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.enter.emit(bool(ev.modifiers() & Qt.ShiftModifier))
        elif ev.key() == Qt.Key_Escape:
            self.escape.emit()
        else:
            super().keyPressEvent(ev)


class FindBar(QFrame):
    changed = Signal()                   # aranan yazi / secenek degisti
    step = Signal(int)                   # +1 sonraki, -1 onceki
    replace_one = Signal()
    replace_all = Signal()
    closed = Signal()

    def __init__(self, parent, dark=True):
        super().__init__(parent)
        self.setObjectName("mkPill")
        self.setFixedWidth(BAR_W)
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        def icon_btn(name, tip, checkable=False):
            b = markup_bar.tool_button(name, tip, checkable, None, dark, size=ROW_H)
            b.setFocusPolicy(Qt.NoFocus)
            return b

        def text_btn(text, tip, name="findBtn", checkable=False):
            b = QToolButton()
            b.setObjectName(name)
            b.setText(text)
            b.setToolTip(tip)
            b.setCheckable(checkable)
            b.setCursor(QCursor(Qt.PointingHandCursor))
            b.setFocusPolicy(Qt.NoFocus)
            b.setFixedHeight(ROW_H if name == "findBtn" else ROW_H - 4)
            return b

        # ---- 1. satir: bul
        self.btn_more = icon_btn("mdi6.chevron-right", _t("Değiştirme satırını aç / kapat (Ctrl+H)"))
        self.ed_find = _FindEdit(counter=True)
        self.ed_find.setPlaceholderText(_t("Bul"))
        self.btn_prev = icon_btn("mdi6.chevron-up", _t("Önceki (Shift+Enter)"))
        self.btn_next = icon_btn("mdi6.chevron-down", _t("Sonraki (Enter)"))
        self.btn_close = icon_btn("mdi6.close", _t("Kapat (Esc)"))
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        for w in (self.btn_more, self.ed_find, self.btn_prev, self.btn_next, self.btn_close):
            r1.addWidget(w, 1 if w is self.ed_find else 0)
        v.addLayout(r1)

        # ---- 2. satir: degistir (istenince acilir)
        self.w_repl = QWidget()
        r2 = QHBoxLayout(self.w_repl)
        r2.setContentsMargins(ROW_H + 4, 0, 0, 0)
        r2.setSpacing(4)
        self.ed_repl = _FindEdit()
        self.ed_repl.setPlaceholderText(_t("Şununla değiştir"))
        self.btn_one = text_btn(_t("Değiştir"), _t("Sıradaki eşleşmeyi değiştir (Enter)"))
        self.btn_all = text_btn(_t("Tümünü"), "")
        r2.addWidget(self.ed_repl, 1)
        r2.addWidget(self.btn_one)
        r2.addWidget(self.btn_all)
        v.addWidget(self.w_repl)
        self.w_repl.hide()

        # ---- 3. satir: kapsam + harf ayrimi
        r3 = QHBoxLayout()
        r3.setContentsMargins(ROW_H + 4, 0, 0, 0)
        r3.setSpacing(2)
        self.btn_this = text_btn(_t("Bu sayfa"), _t("Yalnızca açık olan sayfada ara ve değiştir"), "findSeg", True)
        self.btn_doc = text_btn(_t("Tüm sayfalar"), _t("Belgenin bütün sayfalarında ara ve değiştir"), "findSeg", True)
        self.btn_doc.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.btn_this)
        grp.addButton(self.btn_doc)
        self.btn_case = text_btn("Aa", _t("Büyük / küçük harfe duyarlı"), "findSeg", True)
        r3.addWidget(self.btn_this)
        r3.addWidget(self.btn_doc)
        r3.addStretch(1)
        r3.addWidget(self.btn_case)
        v.addLayout(r3)

        self.ed_find.textChanged.connect(lambda _=None: self.changed.emit())
        self.btn_case.toggled.connect(lambda _=None: self.changed.emit())
        self.btn_doc.toggled.connect(self._scope_changed)
        self.ed_find.enter.connect(lambda shift: self.step.emit(-1 if shift else 1))
        self.ed_repl.enter.connect(lambda _shift: self.replace_one.emit())
        self.ed_find.escape.connect(self.closed.emit)
        self.ed_repl.escape.connect(self.closed.emit)
        self.btn_prev.clicked.connect(lambda: self.step.emit(-1))
        self.btn_next.clicked.connect(lambda: self.step.emit(1))
        self.btn_close.clicked.connect(self.closed.emit)
        self.btn_more.clicked.connect(lambda: self.set_replace(self.w_repl.isHidden()))
        self.btn_one.clicked.connect(self.replace_one.emit)
        self.btn_all.clicked.connect(self.replace_all.emit)
        self._dark = dark
        self._scope_changed()

    # ---- durum
    def needle(self):
        return self.ed_find.text()

    def replacement(self):
        return self.ed_repl.text()

    def case(self):
        return self.btn_case.isChecked()

    def all_pages(self):
        return self.btn_doc.isChecked()

    def replacing(self):
        return not self.w_repl.isHidden()

    def set_replace(self, on):
        self.w_repl.setVisible(on)
        self.btn_more.setIcon(markup_bar.icon("mdi6.chevron-down" if on else "mdi6.chevron-right", self._dark))
        self.btn_more._icon_name = "mdi6.chevron-down" if on else "mdi6.chevron-right"
        self.adjustSize()
        if on:
            self.ed_repl.setFocus()

    def _scope_changed(self, *_):
        self.btn_all.setToolTip(_t("Tüm sayfalardaki eşleşmelerin hepsini değiştir") if self.all_pages()
                                else _t("Bu sayfadaki eşleşmelerin hepsini değiştir"))
        self.changed.emit()

    def set_state(self, count_text, total, none=False):
        self.ed_find.set_count(count_text)
        self.ed_find.count.setProperty("none", bool(none))
        self.ed_find.count.style().unpolish(self.ed_find.count)
        self.ed_find.count.style().polish(self.ed_find.count)
        for b in (self.btn_prev, self.btn_next, self.btn_one, self.btn_all):
            b.setEnabled(total > 0)

    def focus_find(self):
        self.ed_find.setFocus()
        self.ed_find.selectAll()


class FindMixin:
    """MainWindow'a eklenir. Beklenenler: engine, canvas, scroll, thumbs, current_page, goto_page,
    after_edit, status, _finish_edits, _clear_selection, _update_thumb, _update_title, _refresh_panel."""

    def _build_find_bar(self, parent):
        self.find_bar = FindBar(parent, getattr(self, "dark", True))
        self.find_bar.hide()
        self._fx_finder = pdf_search.Finder()
        self._fx_matches = {}            # sayfa -> [Match]
        self._fx_pending = []            # henuz taranmamis sayfalar
        self._fx_cur = None              # siradaki eslesme
        self._fx_query = None            # (aranan, harf ayrimi, tum sayfalar, sayfa)
        self._fx_restart_queued = False
        self._fx_busy = False            # degistirme suruyor: araya arama / yeniden tarama girmesin
        self._fx_typing = QTimer(self)
        self._fx_typing.setSingleShot(True)
        self._fx_typing.setInterval(120)
        self._fx_typing.timeout.connect(self._find_restart)
        self._fx_worker = QTimer(self)
        self._fx_worker.setInterval(0)
        self._fx_worker.timeout.connect(self._find_work)
        b = self.find_bar
        b.changed.connect(self._fx_typing.start)
        b.step.connect(self.find_step)
        b.replace_one.connect(self.find_replace_one)
        b.replace_all.connect(self.find_replace_all)
        b.closed.connect(self.find_close)

    # ---- ac / kapat / yer
    def find_open(self, replace=False):
        if not self.engine.doc or self.scroll.isHidden():
            return
        b = self.find_bar
        if replace and not b.replacing():
            b.set_replace(True)
        b.show()
        b.adjustSize()
        self._place_find_bar()
        b.raise_()
        if replace and b.needle():
            b.ed_repl.setFocus()
            b.ed_repl.selectAll()
        else:
            b.focus_find()
        self._find_restart()

    def find_close(self):
        self.find_bar.hide()
        self._fx_worker.stop()
        self._fx_typing.stop()
        self._fx_matches, self._fx_pending, self._fx_cur, self._fx_query = {}, [], None, None
        self._find_badges_update()
        self.canvas.update()
        self.canvas.setFocus()

    def find_active(self):
        return getattr(self, "find_bar", None) is not None and not self.find_bar.isHidden()

    def _place_find_bar(self):
        """Tuval alaninin sag ustu, yuzen arac seritlerinin ALTI (yakinlastirma hapiyla ayni sag hiza)."""
        b = getattr(self, "find_bar", None)
        if b is None or b.isHidden():
            return
        if self.engine.doc is None or self.scroll.isHidden():
            self.find_close()
            return
        g = self.scroll.geometry()
        x = g.right() - b.width() - 14 - self.scroll.verticalScrollBar().sizeHint().width()
        b.move(max(g.left() + 4, x), g.top() + self.canvas.pad_top + 8)
        b.raise_()

    # ---- arama
    def _find_restart(self, after=None):
        """Aramayi bastan kur. after: (sayfa, y, x, harf sirasi) - siradaki eslesme bundan SONRAKI olsun
        (degistirmeden sonra ayni yerde kalmamak icin); verilmezse acik sayfadaki ilk eslesme."""
        self._fx_restart_queued = False
        if self._fx_busy:
            return
        self._fx_typing.stop()
        self._fx_worker.stop()
        self._fx_matches, self._fx_pending, self._fx_cur = {}, [], None
        if not self.find_active():
            return
        b = self.find_bar
        if not self.engine.doc:
            self.find_close()
            return
        self._fx_finder.attach(self.engine)
        needle = b.needle()
        cp, n = self.current_page, self.engine.page_count()
        self._fx_query = (needle, b.case(), b.all_pages(), cp)
        if needle.strip():
            self._fx_matches[cp] = self._fx_finder.search(cp, needle, b.case())
            if b.all_pages():
                self._fx_pending = list(range(cp + 1, n)) + list(range(cp))
                self._fx_worker.start()
            if after is not None:
                if self._fx_pending:
                    self._find_finish()
                self._fx_cur = self._find_first_after(after)
            elif self._fx_matches[cp]:
                self._fx_cur = self._fx_matches[cp][0]
        self._find_refresh()
        if self._fx_cur is not None:
            self._find_show(self._fx_cur)

    def _find_work(self):
        t0 = time.monotonic()
        needle, case = self._fx_query[0], self._fx_query[1]
        while self._fx_pending and (time.monotonic() - t0) * 1000 < SLICE_MS:
            p = self._fx_pending.pop(0)
            self._fx_matches[p] = self._fx_finder.search(p, needle, case)
        if not self._fx_pending:
            self._fx_worker.stop()
        self._find_refresh()

    def _find_finish(self):
        """Kalan sayfalari hemen tara (ileri / geri / tumunu degistir oncesi)."""
        if not self._fx_pending:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            needle, case = self._fx_query[0], self._fx_query[1]
            for p in self._fx_pending:
                self._fx_matches[p] = self._fx_finder.search(p, needle, case)
            self._fx_pending = []
            self._fx_worker.stop()
        finally:
            QApplication.restoreOverrideCursor()

    def _find_list(self):
        """Kapsamdaki eslesmeler, belge sirasinda."""
        if not self._fx_query:
            return []
        if not self._fx_query[2]:
            return list(self._fx_matches.get(self.current_page, ()))
        return [m for p in sorted(self._fx_matches) for m in self._fx_matches[p]]

    @staticmethod
    def _find_pos(m, shift=0):
        sp, a, _b = m.segs[0]
        return (m.page, round(sp.origin[1]), sp.origin[0], a + shift)

    def _find_first_after(self, pos):
        lst = self._find_list()
        for m in lst:
            if self._find_pos(m) >= pos:
                return m
        return lst[0] if lst else None

    def _find_refresh(self):
        b = self.find_bar
        lst = self._find_list()
        total, more = len(lst), "…" if self._fx_pending else ""
        if not b.needle().strip():
            text = ""
        elif self._fx_cur is not None and any(m is self._fx_cur for m in lst):
            text = f"{next(i for i, m in enumerate(lst) if m is self._fx_cur) + 1} / {total}{more}"
        elif total or more:
            text = f"{total}{more}"
        else:
            text = _t("Sonuç yok")
        b.set_state(text, total, none=bool(b.needle().strip()) and not total and not more)
        self._find_badges_update()
        self.canvas.update()

    def _find_badges_update(self):
        counts = {p: len(ms) for p, ms in self._fx_matches.items() if ms} if self.find_active() else {}
        if not (self._fx_query and self._fx_query[2]):
            counts = {}                               # "Bu sayfa": sol listede rozet yok
        if counts != getattr(self, "_find_badges", {}):
            self._find_badges = counts
            self.thumbs.update()

    def _find_page_changed(self):
        """goto_page sonrasi: "Bu sayfa" kapsaminda arama yeni sayfa icin yenilenir."""
        if not self.find_active() or not self._fx_query:
            return
        if not self._fx_query[2]:
            self._find_restart()
        else:
            self._find_refresh()

    # ---- gezinme
    def find_step(self, delta=1):
        if not self.find_active():
            self.find_open()
            return
        if self._fx_typing.isActive() or self._find_stale():
            self._find_restart()
        self._find_finish()
        lst = self._find_list()
        if not lst:
            return
        cur = self._fx_cur
        idx = next((i for i, m in enumerate(lst) if m is cur), None)
        if idx is None:                               # siradaki yok: acik sayfadan itibaren ilk / onceki
            here = (self.current_page, -1e9, -1e9, 0)
            if delta > 0:
                m = self._find_first_after(here)
            else:
                before = [x for x in lst if self._find_pos(x) < here]
                m = before[-1] if before else lst[-1]
        else:
            m = lst[(idx + delta) % len(lst)]
        self._fx_cur = m
        self._find_show(m)
        self._find_refresh()

    def _find_show(self, m):
        """Eslesmenin sayfasina git, gorunur alana getir (cubugun altinda kalmasin)."""
        if m.page != self.current_page:
            self.goto_page(m.page)
        r = self.canvas.rect_px(self._fx_finder.bbox(m))
        vp = self.scroll.viewport()
        c = r.center()
        self.scroll.ensureVisible(int(c.x()), int(c.y()), min(220, vp.width() // 3), min(180, vp.height() // 3))
        bar = self.find_bar
        top_left = self.canvas.mapTo(bar.parentWidget(), QPoint(int(r.left()), int(r.top())))
        hit = QRect(top_left.x(), top_left.y(), int(r.width()) + 1, int(r.height()) + 1)
        if hit.intersects(bar.geometry().adjusted(-8, 0, 8, 8)):
            sb = self.scroll.verticalScrollBar()
            sb.setValue(sb.value() - (bar.geometry().bottom() + 16 - hit.top()))
        self.canvas.update()

    def _find_stale(self):
        f = self._fx_finder
        return f.engine is not self.engine or f.version != self.engine.version

    # ---- cizim (paint_overlay'den)
    def _paint_find(self, p, cv):
        if not self.find_active() or self._fx_busy:
            return
        if self._find_stale():                        # belge degisti (duzenleme, geri al, sekme): yenile
            if not self._fx_restart_queued:
                self._fx_restart_queued = True
                QTimer.singleShot(0, self._find_restart)
            return
        ms = self._fx_matches.get(self.current_page)
        if not ms:
            return
        p.save()
        p.setPen(Qt.NoPen)
        p.setCompositionMode(QPainter.CompositionMode_Multiply)
        cur = self._fx_cur
        for m in ms:
            p.setBrush(CUR_FILL if m is cur else HIT_FILL)
            for q in self._fx_finder.quads(m):
                p.drawPolygon(cv.poly_px(q))
        p.setCompositionMode(QPainter.CompositionMode_SourceOver)
        if cur is not None and cur.page == self.current_page:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(CUR_LINE, 1.5))
            for q in self._fx_finder.quads(cur):
                p.drawPolygon(cv.poly_px(q))
        p.restore()

    def _find_badge(self, info):
        """Sol listedeki sayfa icin eslesme sayisi (paint_thumb'a)."""
        if info.get("lifted"):
            return 0
        return getattr(self, "_find_badges", {}).get(info["number"] - 1, 0)

    # ---- degistirme
    def _find_apply(self, matches, new_text):
        self._finish_edits()
        self._clear_selection()
        prog = None
        if len({m.page for m in matches}) > 10:       # cok sayfa: ilerleme goster
            prog = QProgressDialog(_t("Değiştiriliyor..."), "", 0, 100, self)
            prog.setCancelButton(None)
            prog.setWindowModality(Qt.WindowModal)
            prog.setMinimumDuration(400)

        def tick(i, n):
            if prog is not None:
                prog.setMaximum(n)
                prog.setValue(i)

        # ilerleme penceresi olaylari isletir: o sirada tuval boyanir, "belge degisti" diye arama
        # yeniden kurulmaya kalkar (yarim belge taranir, onbellek degistirmenin ortasinda atilir)
        self._fx_busy = True
        self._fx_typing.stop()
        self._fx_worker.stop()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            done, skipped, pages, inexact = pdf_search.replace(self.engine, matches, new_text, tick)
        finally:
            QApplication.restoreOverrideCursor()
            if prog is not None:
                prog.setValue(prog.maximum())
            self._fx_busy = False
        if not done:
            return done, skipped, pages, inexact
        self._fx_finder.touch(pages)
        for p in sorted(pages):
            if p != self.current_page:
                try:
                    self.engine.sync_magnifiers(p)
                except Exception:
                    pass
                self._update_thumb(p)
        if self.current_page in pages:
            self.after_edit()
        else:
            self._update_title()
            self._refresh_panel()
        return done, skipped, pages, inexact

    def find_replace_one(self):
        if not self.find_active():
            return
        if self._fx_typing.isActive() or self._find_stale():
            self._find_restart()
        m = self._fx_cur
        if m is None or not any(x is m for x in self._find_list()):
            self.find_step(1)                         # ilk basis: once eslesmeyi goster
            return
        if not m.replaceable:
            self.status(_t("Bu eşleşme birden çok yazı parçasına bölünmüş; değiştirilemedi. Elle düzenleyin."))
            self.find_step(1)
            return
        new = self.find_bar.replacement()
        after = self._find_pos(m, len(new))
        done, _skipped, _pages, inexact = self._find_apply([m], new)
        if done:
            self.status(_t("Değiştirildi.") + self._find_font_note(inexact))
        self._find_restart(after=after)

    def find_replace_all(self):
        if not self.find_active():
            return
        if self._fx_typing.isActive() or self._find_stale():
            self._find_restart()
        self._find_finish()
        lst = self._find_list()
        if not lst:
            return
        done, skipped, pages, inexact = self._find_apply(lst, self.find_bar.replacement())
        if done:
            msg = (_t("{n} yer değiştirildi ({p} sayfada). Geri almak için Ctrl+Z.", n=done, p=len(pages))
                   if len(pages) > 1 else _t("{n} yer değiştirildi. Geri almak için Ctrl+Z.", n=done))
        else:
            msg = _t("Değiştirilen yer olmadı.")
        if skipped:
            msg += " " + _t("{n} eşleşme birden çok yazı parçasına bölünmüş olduğu için atlandı.", n=skipped)
        self.status(msg + self._find_font_note(inexact))
        self._find_restart()

    @staticmethod
    def _find_font_note(inexact):
        return (" " + _t("{n} yerde yazı tipi tam bulunamadı, en yakını kullanıldı.", n=inexact)) if inexact else ""
