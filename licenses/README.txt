Revora PDF - third-party licenses
=================================

Revora PDF itself is free software under the GNU Affero General Public License
version 3 (see the LICENSE file). Its complete source code is
available at https://github.com/revorapdf/revora

Revora PDF includes the following third-party components:

Component                         License                          File in this folder
--------------------------------  -------------------------------  ------------------------------------
PyMuPDF / MuPDF (Artifex)         GNU AGPL-3.0                     LICENSE (Revora's own license; same text)
Qt for Python (PySide6, Shiboken) GNU LGPL-3.0                     LGPL-3.0.txt (+ GPL-3.0.txt, which
  6.11.1 and the Qt 6 libraries                                     the LGPL refers to)
Python                            PSF License                      Python-PSF.txt
QtAwesome                         MIT                              QtAwesome-MIT.txt
Icon fonts bundled with QtAwesome:
  Font Awesome Free 5 and 6,      SIL Open Font License 1.1        OFL-1.1.txt
  Elusive Icons
  Material Design Icons 5 and 6,  Apache License 2.0               Apache-2.0.txt
  Remix Icon
  Phosphor                        MIT                              Phosphor-MIT.txt
  Codicons (Microsoft)            CC BY 4.0                        Codicons-CC-BY-4.0.txt

Qt for Python and the Qt libraries are used unmodified, as separate shared
libraries (the Qt and PySide6 DLLs in the program folder), as the LGPL requires.
The complete source code of Revora PDF is public as well, so the program can be
rebuilt with a modified Qt. Qt's source code is available from
https://www.qt.io and https://code.qt.io

Qt and MuPDF contain further third-party libraries under their own permissive
licenses; see https://doc.qt.io/qt-6/licenses-used-in-qt.html and
https://mupdf.com/licensing
Portions of this software are copyright (c) The FreeType Project
(https://freetype.org). All rights reserved.
