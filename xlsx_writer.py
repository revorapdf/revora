"""
xlsx_writer.py
--------------
Bagimliliksiz, kucuk bir Excel (.xlsx) yazici: yalnizca zipfile + elle yazilan XML.
(openpyxl / xlsxwriter pakete ~4 MB ekler; ihtiyacimiz olan tablo dokmek.)

Desteklenen: birden cok sayfa (sekme), yazi ve sayi hucreleri, kalin, kenarlik, satir
kaydirma (cok satirli hucre), birlesik hucreler, sutun genislikleri, satir yukseklikleri,
yazi bicimi (italik, boyut, renk, yazi tipi), yatay / dikey hizalama, dondurulmus yazi (dikey
baslik), hucreye sigdirma, sayi bicimi, PUNTO olculu sutun genisligi (width_pt), baski ayarlari
(kagit, yon, kenar bosluklari, yazdirma alani), RESIMLER (PNG / JPEG; hucreye demirli).

Kullanim:
    wb = Workbook()
    sh = wb.sheet("Tablo 1")
    sh.set(0, 0, "Baslik", bold=True)            # (satir, sutun) 0'dan baslar
    sh.set(1, 0, 12.5)                           # sayi
    sh.set(2, 0, "Ortali", size=14, color=0xC00000, align="center", valign="center")
    sh.merge(0, 0, 0, 2)                         # satir0, sutun0, satir1, sutun1 (dahil)
    sh.width(0, 18)                              # sutun genisligi (karakter)
    wb.save("cikti.xlsx")

Yapi, Excel'in kabul ettigi en kucuk gecerli pakettir (ECMA-376): [Content_Types].xml,
_rels/.rels, xl/workbook.xml, xl/_rels/workbook.xml.rels, xl/styles.xml, xl/worksheets/sheetN.xml.
Yazilar "inlineStr" olarak hucrenin icinde tutulur (sharedStrings tablosu gerekmez).
"""
import hashlib
import re
import zipfile
from xml.sax.saxutils import escape

NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_XDR = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_PER_PT = 12700
HEAD = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

DEFAULT_FONT, DEFAULT_SIZE = "Calibri", 10.0
SERIF_FONTS = ("Times New Roman", "Cambria", "Georgia", "Garamond", "Palatino Linotype", "Book Antiqua")

_BAD_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_BAD_NAME = re.compile(r"[\[\]\*\?/\\:]")


def col_name(c):
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    s = ""
    c += 1
    while c:
        c, r = divmod(c - 1, 26)
        s = chr(65 + r) + s
    return s


def ref(r, c):
    return f"{col_name(c)}{r + 1}"


def _text(v):
    return escape(_BAD_XML.sub("", str(v)))


def col_points(chars):
    """Sutun genisligi (karakter) -> yaklasik punto. Excel: piksel = karakter x en genis rakam
    (Calibri 10'da 6 px) + 5 px ic bosluk; 96 dpi'de 1 px = 0,75 punto."""
    return (float(chars) * 6.0 + 5.0) * 0.75


# SUTUN GENISLIGI BIRIMI (gercek Excel 2016 ile olculdu, 2026-10-13): dosyadaki "width" degeri W,
#   piksel = kes((256 * W + 18) / 256 * 7)        (7 = Excel'in "en genis rakam" olcusu, 96 dpi)
# olarak yorumlanir; 1 piksel = 0,75 punto. Yani genislik ancak 0,75 puntoluk adimlarla verilebilir.
# (col_points yukarida eski, yaklasik hesaptir; yalniz eski kipin resim kaydirmasi kullanir.)
PX_PT = 0.75
_MDW = 7.0
# BASKI OLCEGI (gercek Excel 2016, uc ayri yazici surucusuyle olculdu, 2026-10-13): Excel sayfayi
# %100 olcekle bile ekrandaki olculeriyle BASMAZ. Sutunlar 0,96 katina daralir (1 piksel = 0,72
# punto), satirlar 1,0245 katina uzar. Yazi boyutu ve "tek uctan bagli" resimler ise gercek
# olcusuyle basilir. PDF duzeni kipi sutun / satir olculerini bu yuzden BASKIYA gore verir.
PRINT_X = 0.96
PRINT_Y = 1.0245


def width_for_px(px):
    """Excel'de tam `px` piksel genislik veren "width" degeri."""
    return (max(1, int(px)) + 0.5) / _MDW - 18.0 / 256.0


PAPERS = (("A4", 9, 595.28, 841.89), ("A3", 8, 841.89, 1190.55), ("A5", 11, 419.53, 595.28),
          ("Letter", 1, 612.0, 792.0), ("Legal", 5, 612.0, 1008.0), ("Tabloid", 3, 792.0, 1224.0),
          ("B5", 13, 515.91, 728.5), ("B4", 12, 728.5, 1031.81), ("Executive", 7, 522.0, 756.0))


def paper_for(width_pt, height_pt):
    """Sayfa boyutuna uyan kagit -> (ad, Excel kagit no, yatay mi, tam mi). Tam uyan yoksa sayfayi
    ICINE ALAN en kucuk kagit (o da yoksa A3) doner ve tam = False olur."""
    landscape = width_pt > height_pt + 0.5
    a, b = sorted((width_pt, height_pt))
    for name, code, pw, ph in PAPERS:
        if abs(pw - a) <= 3.0 and abs(ph - b) <= 3.0:
            return name, code, landscape, True
    holds = [pp for pp in PAPERS if pp[2] >= a - 1 and pp[3] >= b - 1]
    name, code, pw, ph = min(holds, key=lambda pp: pp[2] * pp[3]) if holds else PAPERS[1]
    return name, code, landscape, False


_BUILTIN_FMT = {"0": 1, "0.00": 2, "#,##0": 3, "#,##0.00": 4}


def _image_ext(data):
    """Resim baytlarinin turu: 'jpeg' ya da 'png'."""
    return "jpeg" if data[:2] == b"\xff\xd8" else "png"


class Sheet:
    def __init__(self, name, styles=None):
        self.name = name
        self.styles = styles or Styles()
        self.cells = {}            # (satir, sutun) -> (deger, bicim)
        self.merges = []           # (r0, c0, r1, c1)
        self.widths = {}           # sutun -> genislik (karakter)
        self.heights = {}          # satir -> yukseklik (punto)
        self.images = []           # (satir, sutun, resim baytlari, genislik pt, yukseklik pt, dx pt, dy pt, bitis)
        self.grid = True           # ekranda kilavuz cizgileri (PDF duzeni kipinde kapali)
        self.exact = False         # sutun genislikleri piksel olcusunde verildi (4 haneyle yazilir)
        self.all_rows = False      # yuksekligi verilen BOS satirlar da yazilsin (PDF duzeni: her satirin olcusu belli)
        self.page = None           # baski ayarlari: {paper, landscape, left, right, top, bottom, area, fit}
        #                            fit: True = tek sayfaya sigdir; "width" = butun sutunlar bir sayfa
        #                            genisligine sigar, boyu gerektigi kadar sayfaya akar

    def set(self, r, c, value, bold=False, border=True, title=False, italic=False, size=None, color=None,
            font=None, align=None, valign=None, wrap=None, rotation=None, shrink=False, numfmt=None):
        """border: kenarlikli tablo hucresi (yazi kaydirilir, uste yaslanir; sayi saga yaslanir).
        border=False: duz yazi (kaydirmasiz, saga tasar). title: kalin 12 punto baslik satiri.
        align: left / center / right, valign: top / center / bottom (verilmezse yukaridaki varsayilan).
        wrap: kaydirma (None = yukaridaki varsayilan). rotation: yazinin acisi (90 = asagidan yukari,
        -90 = yukaridan asagi). shrink: sigmayan yaziyi kuculterek sigdir. numfmt: sayi bicimi ("0.00")."""
        num = isinstance(value, (int, float)) and not isinstance(value, bool)
        st = self.styles
        if title:
            style = st.xf(st.font(True, False, 12.0), False, None, None, False)
        elif not border:
            style = st.xf(st.font(bold, italic, size, color, font), False, align, valign, bool(wrap),
                          rotation, shrink, numfmt)
        else:
            style = st.xf(st.font(bold, italic, size, color, font), True, align or ("right" if num else None),
                          valign or "top", (not num) if wrap is None else bool(wrap), rotation, shrink, numfmt)
        self.cells[(r, c)] = (value, style)

    def merge(self, r0, c0, r1, c1, bold=False):
        """Hucreleri birlestir. Kenarlik butun aralikta gorunsun diye bos hucreler de yazilir."""
        if (r0, c0) == (r1, c1):
            return
        self.merges.append((r0, c0, r1, c1))
        base = self.cells.get((r0, c0), ("", self.styles.xf(0, True, None, "top", True)))[1]
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                self.cells.setdefault((r, c), ("", base))

    def width(self, c, chars):
        self.widths[c] = max(2.0, min(float(chars), 120.0))

    def width_px(self, c, px):
        """Sutun genisligi PIKSEL olarak (1 piksel = 0,75 punto): PDF duzeni kipinde olculer PDF'teki
        puntolardan gelir; karakter sayisiyla tahmin edilmez."""
        self.widths[c] = width_for_px(px)
        self.exact = True

    def height(self, r, points):
        """Satir yuksekligi. Excel, BIRLESIK hucredeki cok satirli yaziya gore satiri kendisi
        buyutmez (yazi tek satir yuksekliginde kirpik gorunur): yukseklik elle verilir."""
        self.heights[r] = max(6.0, min(float(points), 409.0))

    def height_exact(self, r, points):
        """Satir yuksekligi, alt sinir olmadan (PDF duzeni: 6 puntodan kisa aralik satirlari da var)."""
        self.heights[r] = max(0.75, min(float(points), 409.0))

    def image(self, r, c, png, width_pt, height_pt, dx_pt=0.0, dy_pt=0.0, end=None):
        """Resmi (PNG ya da JPEG baytlari) (r, c) hucresine demirle; boyutu punto olarak verilir.
        dx_pt / dy_pt: hucrenin sol-ust kosesinden kaydirma.
        end = (satir, sutun, dx, dy): resmin SAG-ALT kosesi de hucreye baglanir; resim hucrelerle
        birlikte olceklenir (baskida hucreler ekrandaki olcusunde cikmaz; resim yerinde kalir)."""
        if png and width_pt > 0 and height_pt > 0:
            self.images.append((r, c, bytes(png), float(width_pt), float(height_pt),
                                max(0.0, float(dx_pt)), max(0.0, float(dy_pt)), end))

    def drawing_xml(self, rids):
        """Bu sayfanin cizim parcasi (resimler). rids: her resim icin iliski kimligi."""
        out = [HEAD, f'<xdr:wsDr xmlns:xdr="{NS_XDR}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">']
        for i, ((r, c, _png, w, h, dx, dy, end), rid) in enumerate(zip(self.images, rids)):
            cx, cy = int(w * EMU_PER_PT), int(h * EMU_PER_PT)
            start = (f'<xdr:from><xdr:col>{c}</xdr:col><xdr:colOff>{int(dx * EMU_PER_PT)}</xdr:colOff>'
                     f'<xdr:row>{r}</xdr:row><xdr:rowOff>{int(dy * EMU_PER_PT)}</xdr:rowOff></xdr:from>')
            if end:
                r1, c1, dx1, dy1 = end
                tag = "twoCellAnchor"
                head = (f'<xdr:twoCellAnchor editAs="twoCell">{start}'
                        f'<xdr:to><xdr:col>{c1}</xdr:col><xdr:colOff>{int(max(0.0, dx1) * EMU_PER_PT)}</xdr:colOff>'
                        f'<xdr:row>{r1}</xdr:row><xdr:rowOff>{int(max(0.0, dy1) * EMU_PER_PT)}</xdr:rowOff></xdr:to>')
            else:
                tag = "oneCellAnchor"
                head = f'<xdr:oneCellAnchor>{start}<xdr:ext cx="{cx}" cy="{cy}"/>'
            out.append(
                head +
                '<xdr:pic>'
                f'<xdr:nvPicPr><xdr:cNvPr id="{i + 2}" name="Resim {i + 1}"/>'
                '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
                f'<xdr:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>'
                f'</xdr:pic><xdr:clientData/></xdr:{tag}>')
        out.append("</xdr:wsDr>")
        return "".join(out)

    def xml(self):
        out = [HEAD, f'<worksheet xmlns="{NS}" xmlns:r="{NS_R}">' if self.images else f'<worksheet xmlns="{NS}">']
        if self.page and self.page.get("fit"):       # (tek sayfaya sigdirma: sheetPr ILK oge olmali)
            out.append('<sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>')
        if not self.grid:                            # (sema sirasi: cols'tan ONCE)
            out.append('<sheetViews><sheetView showGridLines="0" workbookViewId="0"/></sheetViews>')
        if self.widths:
            out.append("<cols>")
            for c in sorted(self.widths):
                w = f"{self.widths[c]:.4f}" if self.exact else f"{self.widths[c]:.2f}"
                out.append(f'<col min="{c + 1}" max="{c + 1}" width="{w}" customWidth="1"/>')
            out.append("</cols>")
        out.append("<sheetData>")
        rows = {}
        for (r, c), v in self.cells.items():
            rows.setdefault(r, {})[c] = v
        if self.all_rows:                            # (yoksa Excel bos satira varsayilan yuksekligi verir)
            for r in self.heights:
                rows.setdefault(r, {})
        for r in sorted(rows):
            ht = self.heights.get(r)
            out.append(f'<row r="{r + 1}" ht="{ht:.2f}" customHeight="1">' if ht else f'<row r="{r + 1}">')
            for c in sorted(rows[r]):
                value, style = rows[r][c]
                a = f'r="{ref(r, c)}" s="{style}"'
                if value is None or value == "":
                    out.append(f"<c {a}/>")
                elif isinstance(value, (int, float)) and not isinstance(value, bool):
                    out.append(f"<c {a}><v>{repr(float(value)) if isinstance(value, float) else value}</v></c>")
                else:
                    out.append(f'<c {a} t="inlineStr"><is><t xml:space="preserve">{_text(value)}</t></is></c>')
            out.append("</row>")
        out.append("</sheetData>")
        if self.merges:
            out.append(f'<mergeCells count="{len(self.merges)}">')
            for r0, c0, r1, c1 in self.merges:
                out.append(f'<mergeCell ref="{ref(r0, c0)}:{ref(r1, c1)}"/>')
            out.append("</mergeCells>")
        if self.page:                                # (sema sirasi: mergeCells'ten sonra, drawing'den once)
            pg = self.page
            out.append('<pageMargins left="%.4f" right="%.4f" top="%.4f" bottom="%.4f" header="0" footer="0"/>' % tuple(
                max(0.0, pg[k]) / 72.0 for k in ("left", "right", "top", "bottom")))
            fit = (' fitToWidth="1" fitToHeight="0"' if pg.get("fit") == "width" else
                   ' fitToWidth="1" fitToHeight="1"' if pg.get("fit") else ' scale="100"')
            out.append(f'<pageSetup paperSize="{pg["paper"]}" orientation="{"landscape" if pg["landscape"] else "portrait"}"'
                       f'{fit}/>')
        if self.images:                              # (sema sirasi: mergeCells'ten SONRA)
            out.append('<drawing r:id="rId1"/>')
        out.append("</worksheet>")
        return "".join(out)


class Styles:
    """Bicim tablosu (styles.xml). Istenen her yazi tipi / kenarlik / hizalama bilesimi BIR kez
    tanimlanir; hucreler onu sira numarasiyla gosterir."""

    def __init__(self):
        self.fonts, self.xfs = {}, {}              # anahtar -> sira (sozluk ekleme sirasini korur)
        self.numfmts = {}                          # ozel sayi bicimi -> numFmtId (164'ten baslar)
        self.font()                                # 0: varsayilan yazi tipi (sutun genisligi birimi de bu)
        self.xf(0, False, None, None, False)       # 0: duz hucre

    def font(self, bold=False, italic=False, size=None, color=None, name=None):
        """color: 0xRRGGBB (siyah / None = otomatik). name: yazi tipi ailesi (None = varsayilan)."""
        key = (bool(bold), bool(italic), round(float(size or DEFAULT_SIZE) * 2) / 2, int(color) if color else None,
               name or None)
        return self.fonts.setdefault(key, len(self.fonts))

    def xf(self, font, border, align, valign, wrap, rotation=None, shrink=False, numfmt=None):
        fmt = 0
        if numfmt:
            fmt = _BUILTIN_FMT.get(numfmt) or self.numfmts.setdefault(numfmt, 164 + len(self.numfmts))
        key = (font, bool(border), align or None, valign or None, bool(wrap), int(rotation) if rotation else None,
               bool(shrink), fmt)
        return self.xfs.setdefault(key, len(self.xfs))

    def xml(self):
        out = [HEAD, f'<styleSheet xmlns="{NS}">']
        if self.numfmts:                           # (sema sirasi: fonts'tan ONCE)
            out.append(f'<numFmts count="{len(self.numfmts)}">' + "".join(
                f'<numFmt numFmtId="{i}" formatCode="{escape(code, {chr(34): "&quot;"})}"/>'
                for code, i in self.numfmts.items()) + "</numFmts>")
        out.append(f'<fonts count="{len(self.fonts)}">')
        for bold, italic, size, color, name in self.fonts:
            out.append("<font>" + ("<b/>" if bold else "") + ("<i/>" if italic else "") + f'<sz val="{size:g}"/>'
                       + (f'<color rgb="FF{color:06X}"/>' if color else "")
                       + f'<name val="{escape(name or DEFAULT_FONT, {chr(34): "&quot;"})}"/>'
                       + f'<family val="{1 if name in SERIF_FONTS else 2}"/></font>')
        out.append('</fonts>'
                   '<fills count="2"><fill><patternFill patternType="none"/></fill>'
                   '<fill><patternFill patternType="gray125"/></fill></fills>'
                   '<borders count="2">'
                   '<border><left/><right/><top/><bottom/><diagonal/></border>'
                   '<border><left style="thin"><color auto="1"/></left><right style="thin"><color auto="1"/></right>'
                   '<top style="thin"><color auto="1"/></top><bottom style="thin"><color auto="1"/></bottom>'
                   '<diagonal/></border></borders>'
                   '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
                   f'<cellXfs count="{len(self.xfs)}">')
        for font, border, align, valign, wrap, rotation, shrink, fmt in self.xfs:
            attrs = f'numFmtId="{fmt}" fontId="{font}" fillId="0" borderId="{1 if border else 0}" xfId="0"'
            if fmt:
                attrs += ' applyNumberFormat="1"'
            if font:
                attrs += ' applyFont="1"'
            if border:
                attrs += ' applyBorder="1"'
            if align or valign or wrap or rotation or shrink:
                # textRotation: 1..90 saat yonunun tersi, 91..180 saat yonu (90 + derece)
                rot = (rotation if rotation > 0 else 90 - rotation) if rotation else 0
                al = ("<alignment" + (f' horizontal="{align}"' if align else "")
                      + (f' vertical="{valign}"' if valign else "") + (f' textRotation="{rot}"' if rot else "")
                      + (' wrapText="1"' if wrap else "") + (' shrinkToFit="1"' if shrink and not wrap else "") + "/>")
                out.append(f'<xf {attrs} applyAlignment="1">{al}</xf>')
            else:
                out.append(f"<xf {attrs}/>")
        out.append('</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
                   '</styleSheet>')
        return "".join(out)


class Workbook:
    def __init__(self):
        self.sheets = []
        self.styles = Styles()

    def sheet(self, name):
        """Yeni sayfa (sekme). Ad Excel kurallarina uydurulur: 31 karakter, []*?/\\: yok, tekrarsiz."""
        base = _BAD_NAME.sub(" ", _BAD_XML.sub("", str(name))).strip().strip("'")[:31] or "Sayfa"
        used = {s.name.lower() for s in self.sheets}
        cand, k = base, 2
        while cand.lower() in used:
            suffix = f" ({k})"
            cand = base[:31 - len(suffix)] + suffix
            k += 1
        sh = Sheet(cand, self.styles)
        self.sheets.append(sh)
        return sh

    def save(self, path):
        if not self.sheets:
            self.sheet("Sayfa1")
        n = len(self.sheets)
        types = [HEAD, '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
                 '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
                 '<Default Extension="xml" ContentType="application/xml"/>',
                 '<Override PartName="/xl/workbook.xml" ContentType='
                 '"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
                 '<Override PartName="/xl/styles.xml" ContentType='
                 '"application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
        for i in range(n):
            types.append(f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType='
                         '"application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
        media, order = {}, []                       # ayni resim bir kez saklanir
        for sh in self.sheets:
            for im in sh.images:
                key = hashlib.md5(im[2]).hexdigest()
                if key not in media:
                    media[key] = (f"image{len(media) + 1}.{_image_ext(im[2])}", im[2])
                    order.append(key)
        drawn = [i for i, sh in enumerate(self.sheets) if sh.images]
        for ext in sorted({name.rsplit(".", 1)[1] for name, _data in media.values()}):
            types.insert(3, f'<Default Extension="{ext}" ContentType="image/{ext}"/>')
        for k, _i in enumerate(drawn):
            types.append(f'<Override PartName="/xl/drawings/drawing{k + 1}.xml" ContentType='
                         '"application/vnd.openxmlformats-officedocument.drawing+xml"/>')
        types.append("</Types>")
        rels = (HEAD + f'<Relationships xmlns="{NS_PKG}"><Relationship Id="rId1" Type='
                f'"{NS_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        wb = [HEAD, f'<workbook xmlns="{NS}" xmlns:r="{NS_R}">']
        if any(not sh.grid for sh in self.sheets):  # (sheetView'un gosterdigi pencere tanimi)
            wb.append("<bookViews><workbookView/></bookViews>")
        wb.append("<sheets>")
        wrels = [HEAD, f'<Relationships xmlns="{NS_PKG}">']
        for i, sh in enumerate(self.sheets):
            wb.append(f'<sheet name="{escape(sh.name, {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>')
            wrels.append(f'<Relationship Id="rId{i + 1}" Type="{NS_R}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>')
        wb.append("</sheets>")
        areas = [(i, sh) for i, sh in enumerate(self.sheets) if sh.page and sh.page.get("area")]
        if areas:                                   # yazdirma alani (sema sirasi: sheets'ten SONRA)
            wb.append("<definedNames>")
            for i, sh in areas:
                r0, c0, r1, c1 = sh.page["area"]
                quoted = "'" + sh.name.replace("'", "''") + "'"
                wb.append(f'<definedName name="_xlnm.Print_Area" localSheetId="{i}">' + escape(
                    f"{quoted}!${col_name(c0)}${r0 + 1}:${col_name(c1)}${r1 + 1}") + "</definedName>")
            wb.append("</definedNames>")
        wb.append("</workbook>")
        wrels.append(f'<Relationship Id="rId{n + 1}" Type="{NS_R}/styles" Target="styles.xml"/></Relationships>')
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("[Content_Types].xml", "".join(types))
            z.writestr("_rels/.rels", rels)
            z.writestr("xl/workbook.xml", "".join(wb))
            z.writestr("xl/_rels/workbook.xml.rels", "".join(wrels))
            z.writestr("xl/styles.xml", self.styles.xml())
            for i, sh in enumerate(self.sheets):
                z.writestr(f"xl/worksheets/sheet{i + 1}.xml", sh.xml())
            for key in order:
                z.writestr("xl/media/" + media[key][0], media[key][1])
            for k, i in enumerate(drawn):
                sh = self.sheets[i]
                z.writestr(f"xl/worksheets/_rels/sheet{i + 1}.xml.rels",
                           HEAD + f'<Relationships xmlns="{NS_PKG}"><Relationship Id="rId1" Type="{NS_R}/drawing" '
                           f'Target="../drawings/drawing{k + 1}.xml"/></Relationships>')
                rids, rels, seen = [], [HEAD, f'<Relationships xmlns="{NS_PKG}">'], {}
                for im in sh.images:
                    key = hashlib.md5(im[2]).hexdigest()
                    if key not in seen:
                        seen[key] = f"rId{len(seen) + 1}"
                        rels.append(f'<Relationship Id="{seen[key]}" Type="{NS_R}/image" '
                                    f'Target="../media/{media[key][0]}"/>')
                    rids.append(seen[key])
                rels.append("</Relationships>")
                z.writestr(f"xl/drawings/drawing{k + 1}.xml", sh.drawing_xml(rids))
                z.writestr(f"xl/drawings/_rels/drawing{k + 1}.xml.rels", "".join(rels))
