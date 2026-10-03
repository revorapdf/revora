<p align="center">
  <img src="assets/revora.png" width="128" alt="Revora PDF logo">
</p>

<h1 align="center">Revora PDF</h1>

<p align="center">
  A Windows PDF editor that edits the <b>existing</b> text of a PDF with its original fonts.<br>
  Offline, private, open source.
</p>

<p align="center">
  <a href="https://revorapdf.com">revorapdf.com</a> ·
  <a href="README.tr.md">Türkçe</a> ·
  <a href="LICENSE">AGPL-3.0</a>
</p>

---

Most free PDF tools "edit" text by covering it with a white box and typing on top.
Revora changes the text itself: it finds the font the PDF uses among the fonts installed
in Windows and rewrites the text with the same font, size, weight, color and opacity.

## Features

**Text**
- Click any text to edit it, drag to move it, rotate it, change its opacity
- Multi-line text with line spacing; add new text anywhere on the page
- Deleting a piece of text leaves the text above and below it untouched

**Lines and tables**
- Select table lines as real objects: move, resize, bend, recolor, make dashed
- Box-select a whole table grid and move it at once; new lines snap to corners

**Markup** (stays editable after saving, also shows correctly in other PDF readers)
- Arrows, boxes, circles, notes with shadows/outlines, numbered badges
- Pen and highlighter (the highlighter snaps to words and creates real PDF highlights)
- Magnifier / detail view, eraser, your own note templates
- Signatures: draw once or load a photo of your paper signature (background removed)
- Images, logos and stamps with rotation
- Blur that **really removes** the text underneath (redaction), not just covers it

**Pages and documents**
- Reorder pages by dragging thumbnails, rotate, delete, duplicate, insert blank pages
- Insert pages from another PDF, merge and split PDFs
- Watermarks, form filling, OCR for scanned pages (requires the free Tesseract)
- Images → PDF (keeps JPEG quality, fixes phone photo orientation)
- PDF pages → PNG/JPG (up to 600 dpi), extract embedded photos at full resolution

**General**
- Works fully offline: no account, no cloud, your files never leave your computer
- English and Turkish interface, dark theme
- Undo/redo, zoom up to 800%, remembers the last page of each file

## Get Revora PDF

Revora PDF is available on the **Microsoft Store**: signed by Microsoft, installs in one
click, updates automatically, 7-day free trial. Buying it supports the development.

## Source code

This repository contains the complete source code of the version sold on the Microsoft
Store, as required by the license. It is a Python 3.11+ / PySide6 / PyMuPDF application
(dependencies in `requirements.txt`); the Store package is produced by `build_store.bat`.
No prebuilt binaries are provided here and no build support is offered.

## License

Revora PDF is free software, licensed under the
[GNU Affero General Public License v3.0](LICENSE).
It is provided "as is", without any warranty.

It is built on [PyMuPDF / MuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0),
[Qt for Python / PySide6](https://www.qt.io/qt-for-python) (LGPL-3.0) and
[QtAwesome](https://github.com/spyder-ide/qtawesome) (MIT).

## Contact

[revorapdf.com](https://revorapdf.com) · revorapdf@gmail.com
