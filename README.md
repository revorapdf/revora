# Revora — PDF Düzenleyici

PDF içindeki yazıları, orijinal font/boyut/kalınlık/opaklığı koruyarak (Windows'ta
zaten kurulu olan gerçek font dosyalarını kullanarak) düzenlemenizi; çizgi ve
tabloları fareyle yönetmenizi; sayfa, filigran ve form işlemlerini yapmanızı sağlar.

## Çalıştırma

`run.bat`'e çift tıklayın (ya da komut satırında `python main.py`). Bir PDF'i
`run.bat`'in ya da açık pencerenin üzerine sürükleyip bırakarak da açabilirsiniz.

İlk kurulumda bir kez: `pip install -r requirements.txt`

Üstteki üç mod: **Metin** · **Çizgi / Kutu** · **Yeni metin**.

## 1) Metin düzenleme (Metin modu)

- Bir yazıya **tıklayın** → kırmızı çerçeveyle seçilir, sağ panele gelir.
- **Tutup sürükleyin** → yazı taşınır. Sürüklerken **Shift** basılıysa yalnızca
  yatay ya da dikey gider. İnce ayar için **ok tuşları** (1 pt, Shift ile 5 pt).
- Yeni yazıyı sağdaki kutuya yazıp **Değişikliği uygula** (ya da **Ctrl+Enter**).
  Kutuda **Enter** yeni satır açar — **çok satırlı** metin artık doğru yazılır;
  satırlar arası mesafe "Satır aralığı" ile ayarlanır.
- **Opaklık**: yarı saydam yazılar (ör. filigranlar) düzenlenirken orijinal
  saydamlığı korunur; isterseniz değiştirebilirsiniz.
- **Delete** → seçili yazıyı siler (alttaki/üstteki yazılara dokunmaz).
- **Çift tık** → yazıyı doğrudan düzenlemeye başlar. Sağ tık → menü.

Dev, eğik filigranlar artık yalnızca kendi harflerinin üzerine tıklayınca
seçilir; altındaki tablo yazılarına tıklamak onları seçer.

## 2) Çizgi / Kutu modu (tablolar, çerçeveler)

Çizgiler tek tek, gerçek nesneler olarak düzenlenir — beyaz kutu boyanmaz,
renk/kalınlık/kesiklilik korunur.

**Seç aracı:**
- Bir çizgiye **tıklayın** → seçilir (fareyle üzerine gelince vurgulanır).
- **Shift+tık** → seçime ekle/çıkar.
- Boş bir yerden **sürükleyerek kutu çizin** → kutunun tamamen içinde kalan tüm
  çizgiler seçilir (bir tablonun tüm ızgarası gibi). **Ctrl+A**: sayfadaki hepsi.
- Seçimi **sürükleyerek taşıyın** (ızgara çizgilerinin arasındaki boşluktan da
  tutabilirsiniz). Shift: yalnızca yatay/dikey.
- **Tutamaçlar** (küçük kareler) ile boyutlandırın. Tek bir çizgide iki ucu
  ayrı ayrı sürüklenir; yatay/dikey çizgi yatay/dikey kalır (Alt: serbest).
- Sağ panelden koordinatları elle girebilir, **kalınlık / renk / kesikli**
  stilini değiştirebilirsiniz. **Delete** siler.

**Çizgi / Dikdörtgen araçları:** sürükleyerek yeni çizgi ya da dikdörtgen
çizin. Uçlar yakındaki çizgi köşelerine ve çizgilerin üzerine **yapışır**
(turuncu halka), neredeyse yatay/dikey çizgiler otomatik düzeltilir.
**Esc** ile Seç aracına dönülür.

## 3) Boş alana yeni metin (Yeni metin modu)

Sayfada bir yere tıklayın → yeşil işaretçi çıkar. Yazdıkça **önizleme sayfada
görünür**. İşaretçiyi fareyle sürükleyerek ya da ok tuşlarıyla konumlayın,
yazı tipi/boyut/renk/opaklık seçin, **Ctrl+Enter** ile ekleyin.

## 4) İşaretle modu (ok, kalem, vurgu, numara, imza...)

Üstteki çubuktan bir araç seçin; alt satırda o aracın (ya da seçili nesnenin)
ayarları çıkar. Eklenen her şey ayrı bir nesnedir: kaydedip açtıktan sonra da
seçilip taşınabilir, boyutlandırılabilir, silinebilir. Son kullanılan ayarlar
hatırlanır.

- **Ok, Çizgi, Kutu, Daire, Not** — sürükleyerek çizin; tutamaçlarla düzenleyin.
- **Kalem (P)** — serbest çizim; titreme yumuşatılır. Shift: düz çizgi.
- **Fosforlu kalem (H)** — yazının üstünden başlarsanız kelimelere oturur ve
  gerçek bir PDF vurgusu olur (Adobe/Edge'de de vurgu olarak görünür). Türü
  çubuktan seçilir: **Vurgu / Altı çizili / Üstü çizili**. Tek tık: tek kelime.
  Boş yerde serbest fosforlu çizer (alttaki yazı soluklaşmaz).
- **Numara (1)** — her tıklamada sıradaki numaralı rozet (1, 2, 3...).
  Seçili rozetin numarası, boyutu ve renkleri çubuktan değişir.
- **Silgi (E)** — üstünden geçtiğiniz işaretlemeler kırmızıyla gösterilir,
  bırakınca silinir (tek Ctrl+Z ile geri gelir).
- **Büyüteç (M), Bulanıklaştır (B)** — detay görünümü ve güvenli karartma.
- **İmza (S)** — imzanızı bir kez fareyle atın (ya da kâğıttaki imzanın
  fotoğrafını yükleyin, beyaz arka planı kaldırılır); kaydedilir. Sonra listeden
  tek tıkla sayfaya koyarsınız.
- **Görüntü ekle (G)** — logo, kaşe, fotoğraf. Köşeden boyutlandırınca oran
  korunur (Shift: serbest).

## 5) Sayfa işlemleri

Soldaki küçük resimlerde fareyle bir sayfanın **üstüne gelin**: altında
**+** (arkasına boş sayfa), **sola / sağa döndür** ve **sil** düğmeleri çıkar.
Listenin üstünde **çoğalt**, **boş sayfa ekle** ve **başka PDF'ten sayfa ekle**
düğmeleri var. Tüm işlemler için **sağ tık** ya da üstteki **Sayfa** menüsü.
Küçük resimleri **sürükleyerek** sayfa sırasını değiştirebilirsiniz.

## 6) PDF İşlemleri menüsü

- **PDF Birleştir / PDF Ayır** — ayrı pencerelerde (önceki gibi).
- **Filigran ekle** — metin, yazı tipi, boyut, açı, renk, opaklık; tüm
  sayfalara, bu sayfaya ya da bir aralığa (ör. `1-3, 5`).
- **Form doldur** — PDF'te doldurulabilir form alanları varsa hepsi bir
  listede açılır (metin, onay kutusu, açılır liste).
- **OCR** — taranmış (resim) sayfalardaki yazıyı tanır ve görünmez bir metin
  katmanı ekler: sayfa aynı görünür ama metin seçilebilir/aranabilir olur.
  Bunun için ücretsiz **Tesseract** programının kurulu olması gerekir
  (program ilk kullanımda nasıl kurulacağını gösterir).

## 7) Kaydetme ve geri alma

- **Ctrl+S** kaydet (ilk seferde orijinalin üzerine yazmak için onay ister),
  **Ctrl+Shift+S** farklı kaydet.
- **Ctrl+Z** geri al, **Ctrl+Y** yinele (son 30 adım).
- Kaydedilmemiş değişiklik varken pencere başlığında **•** görünür; kapatırken
  ya da başka dosya açarken sorulur.

## 8) Yakınlaştırma / gezinme

- **Ctrl + fare tekerleği**: imlecin olduğu noktaya yakınlaştır.
- **Ctrl + sürükle** ya da **orta tuşla sürükle**: sayfayı kaydır.
- **PgUp / PgDn**: önceki/sonraki sayfa. **Ctrl+0**: genişliğe sığdır.

## 9) Ayarlar

Sağ üstteki **dişli** (ya da **Ctrl+,**): **dil** (Türkçe / English; değişiklik
program yeniden başlatılınca geçerli olur, "Şimdi yeniden başlat" düğmesi var),
tüm **klavye kısayolları**, **Hakkında** ve **Destek ol**. Program hep koyu
temayla açılır (açık tema 1.2.0'dan sonra kaldırıldı).

## 10) Dağıtım: kurulum dosyası

`build_exe.bat`'e çift tıklayın (2-3 dakika). Sonuç:
**`installer\Revora_Kurulum.exe`** — başkasına sadece bu tek dosyayı verin.

Çift tıklayınca Türkçe kurulum sihirbazı açılır ve önce kurulum kipi sorulur:
**"Yalnızca geçerli kullanıcı için"** (yönetici şifresi istemez) ya da **"Tüm
kullanıcılar için"** (Program Files'a kurar, yönetici izni ister). Başlat menüsüne eklenir, isteğe bağlı olarak
masaüstü kısayolu ve PDF'lere sağ tıklayınca "Revora ile aç" seçeneği eklenir.
Kaldırmak için: **Ayarlar > Uygulamalar > Revora > Kaldır**.

Kurulum dosyası için bu bilgisayarda ücretsiz **Inno Setup** kurulu olmalı
(yoksa betik sadece `dist\Revora` klasörünü üretir). Revora'yı kuracak
kişinin hiçbir şey kurmasına gerek yok.

**Yeni sürüm çıkarırken** `Revora.iss` içindeki `AppVersion` satırını artırın
(ör. `1.1.0`) ve `build_exe.bat`'i çalıştırın. Yeni kurulum eskisinin
üzerine güncellenir; ayarlar korunur.

**Logoyu değiştirmek için** `assets\revora.png` dosyasını yenisiyle
değiştirip (kare, şeffaf arka planlı PNG, en az 512×512) yeniden paketleyin;
Windows ikonu otomatik üretilir. Windows eski ikonu önbellekte tutabilir;
exe'nin adını değiştirmek ya da başka klasöre kopyalamak genelde çözer.

## Font eşleşmesi hakkında

Program, PDF'teki yazı tipini (ör. "Tahoma", "Arial") Windows'un font
klasöründen (`C:\Windows\Fonts`) bulup kullanır; böylece tüm Türkçe
karakterler doğru çıkar. PDF çok nadir bir font kullanıyorsa en yakın font
kullanılır ve bir uyarı gösterilir.

Taranmış (resim) belgelerde gerçek metin nesnesi olmadığından yazılar
düzenlenemez; OCR ile yalnızca aranabilir/seçilebilir hale getirilebilir.

## Lisans

Revora özgür ve açık kaynak bir yazılımdır: **GNU Affero Genel Kamu Lisansı
sürüm 3 (AGPL-3.0)** ile dağıtılır, tam metin `LICENSE` dosyasındadır.
Kaynak kodu: https://github.com/revorapdf/revora · Web: https://revorapdf.com ·
İletişim: revorapdf@gmail.com
