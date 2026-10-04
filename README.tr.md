<p align="center">
  <img src="assets/revora.png" width="128" alt="Revora PDF logosu">
</p>

<h1 align="center">Revora PDF</h1>

<p align="center">
  PDF'teki <b>mevcut</b> yazıyı orijinal yazı tipiyle düzenleyen Windows uygulaması.<br>
  Çevrimdışı, gizli, açık kaynak.
</p>

<p align="center">
  <a href="https://revorapdf.com/tr/">revorapdf.com</a> ·
  <a href="README.md">English</a> ·
  <a href="LICENSE">AGPL-3.0</a>
</p>

---

Çoğu ücretsiz PDF aracı yazıyı "düzenlerken" üstüne beyaz bir kutu koyup yenisini yazar.
Revora yazının kendisini değiştirir: PDF'in kullandığı yazı tipini Windows'ta kurulu
yazı tipleri arasında bulur ve aynı yazı tipi, boyut, kalınlık, renk ve saydamlıkla yazar.

Yazı düzenleme, tablo çizgilerini nesne olarak taşıma, kaydettikten sonra da düzenlenebilen
işaretleme (ok, not, vurgu, numara, büyüteç, imza), alttaki yazıyı gerçekten silen
bulanıklaştırma, sayfa işlemleri, birleştirme/ayırma, filigran, form doldurma, OCR ve
resim ↔ PDF. Ayrıntılar: [revorapdf.com/tr](https://revorapdf.com/tr/)

## Revora PDF'i edinin

Revora PDF **[Microsoft Store](https://apps.microsoft.com/detail/9nvq2dcd165x?hl=tr-TR&gl=TR)**'da: Microsoft tarafından imzalı, tek tıkla kurulur,
kendiliğinden güncellenir, 7 gün ücretsiz denenebilir. Satın almak geliştirmeyi destekler.

## Kaynak kodu

Bu depo, lisansın gerektirdiği üzere Microsoft Store'da satılan sürümün kaynak kodunun
tamamını içerir. Uygulama Python 3.11+ / PySide6 / PyMuPDF ile yazılmıştır (bağımlılıklar
`requirements.txt`'te); Store paketi `build_store.bat` ile üretilir. Burada hazır derlenmiş
dosya sunulmaz ve derleme desteği verilmez.

## Lisans

Revora PDF özgür yazılımdır; [GNU Affero Genel Kamu Lisansı sürüm 3](LICENSE) ile
lisanslanmıştır ve hiçbir garanti olmadan "olduğu gibi" sunulur.

[PyMuPDF / MuPDF](https://github.com/pymupdf/PyMuPDF) (AGPL-3.0),
[Qt for Python / PySide6](https://www.qt.io/qt-for-python) (LGPL-3.0) ve
[QtAwesome](https://github.com/spyder-ide/qtawesome) (MIT) üzerine kuruludur.

## İletişim

[revorapdf.com](https://revorapdf.com/tr/) · revorapdf@gmail.com
