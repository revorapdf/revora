"""
xlsx_writer.py
--------------
Bagimliliksiz, kucuk bir Excel (.xlsx) yazici: yalnizca zipfile + elle yazilan XML.
(openpyxl / xlsxwriter pakete ~4 MB ekler; ihtiyacimiz olan tablo dokmek.)

Desteklenen: birden cok sayfa (sekme), yazi ve sayi hucreleri, kalin, kenarlik, satir
kaydirma (cok satirli hucre), birlesik hucreler, sutun genislikleri, satir yukseklikleri,
yazi bicimi (italik, boyut, renk, yazi tipi), yatay / dikey hizalama,
RESIMLER (PNG / JPEG; hucreye demirli, hucrelerin ustunde durur).

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
        self.images = []           # (satir, sutun, png baytlari, genislik pt, yukseklik pt)

    def set(self, r, c, value, bold=False, border=True, title=False, italic=False, size=None, color=None,
            font=None, align=None, valign=None):
        """border: kenarlikli tablo hucresi (yazi kaydirilir, uste yaslanir; sayi saga yaslanir).
        border=False: duz yazi (kaydirmasiz, saga tasar). title: kalin 12 punto baslik satiri.
        align: left / center / right, valign: top / center / bottom (verilmezse yukaridaki varsayilan)."""
        num = isinstance(value, (int, float)) and not isinstance(value, bool)
        st = self.styles
        if title:
            style = st.xf(st.font(True, False, 12.0), False, None, None, False)
        elif not border:
            style = st.xf(st.font(bold, italic, size, color, font), False, align, valign, False)
        else:
            style = st.xf(st.font(bold, italic, size, color, font), True, align or ("right" if num else None),
                          valign or "top", not num)
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

    def height(self, r, points):
        """Satir yuksekligi. Excel, BIRLESIK hucredeki cok satirli yaziya gore satiri kendisi
        buyutmez (yazi tek satir yuksekliginde kirpik gorunur): yukseklik elle verilir."""
        self.heights[r] = max(6.0, min(float(points), 409.0))

    def image(self, r, c, png, width_pt, height_pt):
        """Resmi (PNG ya da JPEG baytlari) (r, c) hucresinin sol-ust kosesine demirle; boyutu
        punto olarak verilir."""
        if png and width_pt > 0 and height_pt > 0:
            self.images.append((r, c, bytes(png), float(width_pt), float(height_pt)))

    def drawing_xml(self, rids):
        """Bu sayfanin cizim parcasi (resimler). rids: her resim icin iliski kimligi."""
        out = [HEAD, f'<xdr:wsDr xmlns:xdr="{NS_XDR}" xmlns:a="{NS_A}" xmlns:r="{NS_R}">']
        for i, ((r, c, _png, w, h), rid) in enumerate(zip(self.images, rids)):
            cx, cy = int(w * EMU_PER_PT), int(h * EMU_PER_PT)
            out.append(
                '<xdr:oneCellAnchor>'
                f'<xdr:from><xdr:col>{c}</xdr:col><xdr:colOff>0</xdr:colOff>'
                f'<xdr:row>{r}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
                f'<xdr:ext cx="{cx}" cy="{cy}"/>'
                '<xdr:pic>'
                f'<xdr:nvPicPr><xdr:cNvPr id="{i + 2}" name="Resim {i + 1}"/>'
                '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr></xdr:nvPicPr>'
                f'<xdr:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
                f'<xdr:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
                '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>'
                '</xdr:pic><xdr:clientData/></xdr:oneCellAnchor>')
        out.append("</xdr:wsDr>")
        return "".join(out)

    def xml(self):
        out = [HEAD, f'<worksheet xmlns="{NS}" xmlns:r="{NS_R}">' if self.images else f'<worksheet xmlns="{NS}">']
        if self.widths:
            out.append("<cols>")
            for c in sorted(self.widths):
                out.append(f'<col min="{c + 1}" max="{c + 1}" width="{self.widths[c]:.2f}" customWidth="1"/>')
            out.append("</cols>")
        out.append("<sheetData>")
        rows = {}
        for (r, c), v in self.cells.items():
            rows.setdefault(r, {})[c] = v
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
        if self.images:                              # (sema sirasi: mergeCells'ten SONRA)
            out.append('<drawing r:id="rId1"/>')
        out.append("</worksheet>")
        return "".join(out)


class Styles:
    """Bicim tablosu (styles.xml). Istenen her yazi tipi / kenarlik / hizalama bilesimi BIR kez
    tanimlanir; hucreler onu sira numarasiyla gosterir."""

    def __init__(self):
        self.fonts, self.xfs = {}, {}              # anahtar -> sira (sozluk ekleme sirasini korur)
        self.font()                                # 0: varsayilan yazi tipi (sutun genisligi birimi de bu)
        self.xf(0, False, None, None, False)       # 0: duz hucre

    def font(self, bold=False, italic=False, size=None, color=None, name=None):
        """color: 0xRRGGBB (siyah / None = otomatik). name: yazi tipi ailesi (None = varsayilan)."""
        key = (bool(bold), bool(italic), round(float(size or DEFAULT_SIZE) * 2) / 2, int(color) if color else None,
               name or None)
        return self.fonts.setdefault(key, len(self.fonts))

    def xf(self, font, border, align, valign, wrap):
        key = (font, bool(border), align or None, valign or None, bool(wrap))
        return self.xfs.setdefault(key, len(self.xfs))

    def xml(self):
        out = [HEAD, f'<styleSheet xmlns="{NS}">', f'<fonts count="{len(self.fonts)}">']
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
        for font, border, align, valign, wrap in self.xfs:
            attrs = f'numFmtId="0" fontId="{font}" fillId="0" borderId="{1 if border else 0}" xfId="0"'
            if font:
                attrs += ' applyFont="1"'
            if border:
                attrs += ' applyBorder="1"'
            if align or valign or wrap:
                al = ("<alignment" + (f' horizontal="{align}"' if align else "")
                      + (f' vertical="{valign}"' if valign else "") + (' wrapText="1"' if wrap else "") + "/>")
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
        wb = [HEAD, f'<workbook xmlns="{NS}" xmlns:r="{NS_R}"><sheets>']
        wrels = [HEAD, f'<Relationships xmlns="{NS_PKG}">']
        for i, sh in enumerate(self.sheets):
            wb.append(f'<sheet name="{escape(sh.name, {chr(34): "&quot;"})}" sheetId="{i + 1}" r:id="rId{i + 1}"/>')
            wrels.append(f'<Relationship Id="rId{i + 1}" Type="{NS_R}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>')
        wb.append("</sheets></workbook>")
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
