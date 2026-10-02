"""
make_screenshots.py
-------------------
Microsoft Store ekran goruntuleri: ornek bir fatura PDF'i uretir, Revora'yi acip
ozellikleri gosteren 4 goruntu alir (1920x1080), Ingilizce ve Turkce arayuzle.

    python store/make_screenshots.py          -> store/screenshots/en, store/screenshots/tr

Kullanicinin kayitli ayarlari (QSettings) calismadan once yedeklenir, sonra geri yuklenir.
"""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "store", "screenshots")
WORK = os.path.join(ROOT, "build", "screens")
W, H = 1920, 1080
FONTS = r"C:\Windows\Fonts"

TEXT = {
    "en": dict(
        company="Bluefield Design Studio", addr1="18 Harbour Street, Bristol BS1 4RN",
        addr2="hello@bluefield.example  ·  +44 117 000 0000", title="INVOICE",
        no="Invoice no.", no_v="2026-0142", date="Date", date_v="3 October 2026",
        due="Due date", due_v="2 November 2026", bill="Bill to",
        cust="Harbor & Pine Café", cust2="7 Market Lane, Bath BA1 1AA",
        cols=("Description", "Qty", "Unit price", "Amount"),
        rows=(("Logo design", "1", "450.00", "450.00"),
              ("Brand guidelines (24 pages)", "1", "380.00", "380.00"),
              ("Menu layout, print-ready", "2", "120.00", "240.00"),
              ("Social media templates", "6", "25.00", "150.00")),
        sub="Subtotal", sub_v="1,220.00", vat="VAT 20%", vat_v="244.00",
        tot="Total (EUR)", tot_v="1,464.00",
        pay="Payment by bank transfer", iban="IBAN  GB00 BLUE 0000 0000 1426 00",
        notes=("Thank you for your business. Please include the invoice number",
               "with your payment. Files are delivered within 3 working days."),
        sign="Authorised signature",
        p2="Terms and conditions", p3="Project timeline",
        note="Pay before 2 Nov", edited="Brand guidelines (32 pages)", mag="Detail", mag_cap="Totals",
    ),
    "tr": dict(
        company="Mavi Vadi Tasarım Stüdyosu", addr1="Liman Caddesi No: 18, Kadıköy / İstanbul",
        addr2="merhaba@mavivadi.example  ·  +90 216 000 00 00", title="FATURA",
        no="Fatura no", no_v="2026-0142", date="Tarih", date_v="3 Ekim 2026",
        due="Son ödeme", due_v="2 Kasım 2026", bill="Sayın",
        cust="Liman & Çam Kafe", cust2="Çarşı Sokak No: 7, Moda / İstanbul",
        cols=("Açıklama", "Adet", "Birim fiyat", "Tutar"),
        rows=(("Logo tasarımı", "1", "4.500,00", "4.500,00"),
              ("Kurumsal kimlik kılavuzu (24 sayfa)", "1", "3.800,00", "3.800,00"),
              ("Menü tasarımı, baskıya hazır", "2", "1.200,00", "2.400,00"),
              ("Sosyal medya şablonları", "6", "250,00", "1.500,00")),
        sub="Ara toplam", sub_v="12.200,00", vat="KDV %20", vat_v="2.440,00",
        tot="Genel toplam (TL)", tot_v="14.640,00",
        pay="Ödeme: banka havalesi", iban="IBAN  TR00 0000 0000 0000 0000 1426 00",
        notes=("Bizi tercih ettiğiniz için teşekkür ederiz. Ödemede fatura numarasını",
               "belirtiniz. Dosyalar 3 iş günü içinde teslim edilir."),
        sign="Yetkili imza",
        p2="Hizmet koşulları", p3="Proje takvimi",
        note="2 Kasım'a kadar öde", edited="Kurumsal kimlik kılavuzu (32 sayfa)", mag="Detay", mag_cap="Toplam",
    ),
}

LOREM = {
    "en": ("1. Scope. The studio delivers the items listed on the invoice in the agreed formats.",
           "2. Revisions. Two rounds of revisions are included for each item.",
           "3. Ownership. Rights to the final artwork pass to the client after full payment.",
           "4. Payment. Invoices are payable within 30 days by bank transfer.",
           "5. Delivery. Files are delivered as PDF, PNG and editable source files."),
    "tr": ("1. Kapsam. Stüdyo, faturadaki işleri kararlaştırılan biçimlerde teslim eder.",
           "2. Düzeltmeler. Her iş için iki tur düzeltme fiyata dahildir.",
           "3. Haklar. Son tasarımların hakları, ödeme tamamlanınca müşteriye geçer.",
           "4. Ödeme. Faturalar 30 gün içinde banka havalesiyle ödenir.",
           "5. Teslim. Dosyalar PDF, PNG ve düzenlenebilir kaynak dosya olarak verilir."),
}


# ------------------------------------------------------------------ ornek PDF
def make_pdf(lang, path):
    import fitz
    T = TEXT[lang]
    doc = fitz.open()
    reg, bold = os.path.join(FONTS, "arial.ttf"), os.path.join(FONTS, "arialbd.ttf")
    navy, grey, ink = (0.09, 0.11, 0.16), (0.42, 0.45, 0.5), (0.12, 0.12, 0.14)
    red = (0.9, 0.16, 0.18)

    def txt(page, x, y, s, size=10, b=False, color=ink, right=False):
        font = fitz.Font(fontfile=bold if b else reg)
        if right:
            x -= font.text_length(s, fontsize=size)
        page.insert_text((x, y), s, fontsize=size, fontname="Arial-Bold" if b else "Arial",
                         fontfile=bold if b else reg, color=color)

    # --- sayfa 1: fatura
    p = doc.new_page(width=595, height=842)
    p.draw_rect(fitz.Rect(0, 0, 595, 8), color=None, fill=red)
    txt(p, 50, 70, T["company"], 18, True, navy)
    txt(p, 50, 88, T["addr1"], 9, color=grey)
    txt(p, 50, 101, T["addr2"], 9, color=grey)
    txt(p, 545, 72, T["title"], 26, True, red, right=True)
    y = 140
    for k, v in ((T["no"], T["no_v"]), (T["date"], T["date_v"]), (T["due"], T["due_v"])):
        txt(p, 385, y, k, 9, color=grey)
        txt(p, 545, y, v, 10, True, right=True)
        y += 16
    txt(p, 50, 140, T["bill"], 9, color=grey)
    txt(p, 50, 156, T["cust"], 12, True)
    txt(p, 50, 171, T["cust2"], 10)
    # tablo: gercek cizgiler (Cizgi/Kutu modunda nesne olarak secilir)
    x0, x1 = 50, 545
    cx = (50, 300, 355, 450, 545)
    top, rh = 215, 26
    p.draw_rect(fitz.Rect(x0, top, x1, top + rh), color=None, fill=(0.93, 0.94, 0.96))
    for i, c in enumerate(T["cols"]):
        if i == 0:
            txt(p, cx[0] + 8, top + 17, c, 9.5, True, navy)
        else:
            txt(p, cx[i + 1] - 8, top + 17, c, 9.5, True, navy, right=True)
    for r, row in enumerate(T["rows"]):
        yy = top + rh * (r + 1) + 17
        txt(p, cx[0] + 8, yy, row[0], 10)
        for i in (1, 2, 3):
            txt(p, cx[i + 1] - 8, yy, row[i], 10, right=True)
    bottom = top + rh * (len(T["rows"]) + 1)
    for k in range(len(T["rows"]) + 2):
        p.draw_line((x0, top + rh * k), (x1, top + rh * k), color=(0.6, 0.63, 0.68), width=0.8)
    for c in cx:
        p.draw_line((c, top), (c, bottom), color=(0.6, 0.63, 0.68), width=0.8)
    y = bottom + 24
    for k, v, b in ((T["sub"], T["sub_v"], False), (T["vat"], T["vat_v"], False)):
        txt(p, 450 - 8, y, k, 10, b, grey, right=True)
        txt(p, 545 - 8, y, v, 10, b, right=True)
        y += 18
    p.draw_line((355, y - 8), (545, y - 8), color=navy, width=1.2)
    txt(p, 450 - 8, y + 8, T["tot"], 11, True, navy, right=True)
    txt(p, 545 - 8, y + 8, T["tot_v"], 13, True, navy, right=True)
    # 125% yakinlikta ekranda ~685 pt'ye kadar gorunur: hepsi onun ustunde
    y = 532
    txt(p, 50, y, T["pay"], 10, True)
    txt(p, 50, y + 16, T["iban"], 10)
    y = 586
    for line in T["notes"]:
        txt(p, 50, y, line, 9.5, color=grey)
        y += 14
    p.draw_line((360, 650), (545, 650), color=grey, width=0.6)
    txt(p, 360, 664, T["sign"], 9, color=grey)

    # --- sayfa 2: kosullar
    p = doc.new_page(width=595, height=842)
    p.draw_rect(fitz.Rect(0, 0, 595, 8), color=None, fill=red)
    txt(p, 50, 80, T["p2"], 18, True, navy)
    y = 120
    for line in LOREM[lang]:
        txt(p, 50, y, line, 10)
        y += 26
    # --- sayfa 3: takvim
    p = doc.new_page(width=595, height=842)
    p.draw_rect(fitz.Rect(0, 0, 595, 8), color=None, fill=red)
    txt(p, 50, 80, T["p3"], 18, True, navy)
    for i, (w, col) in enumerate(((180, navy), (260, red), (140, (0.98, 0.53, 0.45)), (220, navy))):
        p.draw_rect(fitz.Rect(50 + i * 60, 130 + i * 50, 50 + i * 60 + w, 158 + i * 50),
                    color=None, fill=col)
    doc.save(path, garbage=3, deflate=True)


# ------------------------------------------------------------------ cekim
def shoot(lang):
    os.environ["REVORA_LANG"] = "en-US" if lang == "en" else "tr-TR"
    sys.path.insert(0, ROOT)
    os.chdir(ROOT)
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings, QPointF
    import fitz
    import main
    import markup_ui as mu

    settings = QSettings("PdfEdit", "PdfEdit")
    backup = {k: settings.value(k) for k in settings.allKeys()}
    app = QApplication.instance() or QApplication(sys.argv)
    from PySide6.QtGui import QFont
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    out = os.path.join(OUT, lang)
    os.makedirs(out, exist_ok=True)
    os.makedirs(WORK, exist_ok=True)
    pdf = os.path.join(WORK, f"sample_{lang}.pdf")
    make_pdf(lang, pdf)
    T = TEXT[lang]

    try:
        w = main.MainWindow()
        w.resize(W, H)
        w.show()
        w.open_pdf(pdf)
        app.processEvents()
        w.set_zoom(1.25)
        app.processEvents()

        def snap(name):
            for _ in range(5):
                app.processEvents()
            w.grab().save(os.path.join(out, name))
            print("  ", lang, name)

        def span_with(s):
            spans = w.engine.get_spans(0)
            for sp in spans:
                if sp.text.replace("\xa0", " ").strip() == s:
                    return sp
            for sp in spans:
                if s in sp.text.replace("\xa0", " "):
                    return sp
            raise SystemExit(f"yazi bulunamadi: {s}")

        def rect_of(s):
            hits = w.engine.doc[0].search_for(s)
            if not hits:
                raise SystemExit(f"yazi bulunamadi: {s}")
            return hits[0]

        # 1) yazi duzenleme: tablodaki bir satir sayfanin ustunde duzenleniyor
        w.set_mode("text")
        row = T["rows"][1][0]
        sp = span_with(row)
        w._select_text_span(sp)
        w._text_edit_begin(select_all=False)
        w.txt_new.setPlainText(T["edited"])
        cur = w.txt_new.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        w.txt_new.setTextCursor(cur)
        snap("01_edit_text.png")
        w.txt_new.setPlainText(row)          # belgeyi degistirmeden kapat
        w._inline_text_done()

        # 2) isaretleme: vurgu, numaralar, oklu not, imza, bulaniklastirma
        eng = w.engine
        st = mu.DEFAULT_STYLE

        def add(kind, style, geom):
            return eng.add_markup(0, kind, mu.params_from(kind, dict(style), geom))

        dr = rect_of(T["due_v"])
        add("texthl", st["highlight"], {"rects": [[dr.x0 - 1, dr.y0, dr.x1 + 1, dr.y1]]})
        for i, row_y in enumerate((241, 267, 293)):
            add("number", st["number"], {"pos": [36, row_y + 13], "n": i + 1})
        note_style = dict(st["note"], **mu.NOTE_PRESETS[list(mu.NOTE_PRESETS)[3]])  # sari not
        note_style.update(size=12.0, bold=True, color=[0.9, 0.16, 0.18])
        # not tarihin altinda (adres ile tablo arasindaki bosluk), ok yukari tarihe
        nid = add("note", note_style, {"pos": [255, 188], "text": T["note"],
                                        "target": [dr.x0 - 1, dr.y1]})
        ir = rect_of(T["iban"].split("  ")[1])
        add("blur", st["blur"], {"rect": [ir.x0 - 3, ir.y0 - 3, ir.x1 + 4, ir.y1 + 3]})
        import math
        strokes = [[[372 + t * 1.5, 636 - 10 * math.sin(t / 7.0) * math.exp(-t / 90)]
                    for t in range(0, 110, 3)],
                   [[400 + t * 1.2, 643 - 6 * math.cos(t / 5.0)] for t in range(0, 60, 3)]]
        add("ink", st["sign"], {"strokes": strokes, "sig": True})
        w.set_mode("markup")
        w.after_edit()
        w._mk_select(nid)
        snap("02_markup.png")

        # 3) tablo cizgileri: izgaranin tamami secili
        w.set_mode("shape")
        tb = fitz.Rect(45, 210, 550, 350)
        w.sel_paths = [it.index for it in eng.get_paths(0)
                       if tb.contains(fitz.Rect(it.bbox).normalize()) or
                       (tb.x0 <= it.bbox.x0 and it.bbox.x1 <= tb.x1 and tb.y0 <= it.bbox.y0 and it.bbox.y1 <= tb.y1)]
        w._on_path_selection()
        snap("03_tables.png")

        # 4) buyutec / detay gorunumu
        w.set_mode("markup")
        trc = rect_of(T["tot_v"])
        c = [(trc.x0 + trc.x1) / 2, (trc.y0 + trc.y1) / 2]
        mag = dict(st["magnifier"], zoom=2.0)
        mid = add("magnifier", mag, {"src": c, "r": 34, "dst": [190, 418], "label": "A",
                                     "caption": T["mag_cap"]})
        w.after_edit()
        w._mk_select(mid)
        snap("04_magnifier.png")
        w.engine.dirty = False
        w.close()
    finally:
        settings.clear()
        for k, v in backup.items():
            settings.setValue(k, v)
        settings.sync()


if __name__ == "__main__":
    if len(sys.argv) > 1:
        shoot(sys.argv[1])
    else:
        for lang in ("en", "tr"):
            subprocess.run([sys.executable, os.path.abspath(__file__), lang], check=True)
