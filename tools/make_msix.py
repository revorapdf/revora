"""
make_msix.py
------------
Microsoft Store paketi (MSIX) uretir: dist\\Revora (PyInstaller ciktisi) + Store logolari +
AppxManifest.xml -> installer\\RevoraPDF_<surum>_x64.msix

Kullanim:  build_store.bat  (once PyInstaller'i calistirir, sonra bunu)
Dogrudan:  python tools/make_msix.py [--register]
  --register : paketi bu bilgisayara GELISTIRICI olarak kaydeder (Gelistirici Modu acik
               olmali) -> Baslat menusunden paketli hali denenebilir.
               Kaldirmak: Get-AppxPackage RevoraPDF.RevoraPDF | Remove-AppxPackage

Store paketi imzalamaz; Store yuklendikten sonra kendi sertifikasiyla imzalar.
Kimlik bilgileri Partner Center > Revora PDF > Product identity sayfasindan (DEGISTIRME).
"""
import argparse
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- Partner Center > Product identity -------------------------------------------
IDENTITY_NAME = "RevoraPDF.RevoraPDF"
PUBLISHER = "CN=5804DF6C-1E62-43CA-9FD0-3969E4CAD191"
PUBLISHER_DISPLAY = "Revora PDF"
DISPLAY_NAME = "Revora PDF"          # Store'da ayrilan ad ile AYNI olmali
# ----------------------------------------------------------------------------------
DESCRIPTION = "Edit the existing text of PDFs with the original fonts."
DIST = os.path.join(ROOT, "dist", "Revora")
STAGE = os.path.join(ROOT, "build", "msix")
OUT_DIR = os.path.join(ROOT, "installer")
LOGO = os.path.join(ROOT, "assets", "revora.png")

SCALES = (100, 125, 150, 200, 400)
TARGET_SIZES = (16, 20, 24, 30, 32, 36, 40, 44, 48, 60, 64, 72, 80, 96, 256)


def sdk_tool(name):
    base = r"C:\Program Files (x86)\Windows Kits\10\bin"
    found = []
    if os.path.isdir(base):
        for v in os.listdir(base):
            p = os.path.join(base, v, "x64", name)
            if v.startswith("10.") and os.path.isfile(p):
                found.append((tuple(int(x) for x in v.split(".")), p))
    if not found:
        raise SystemExit(f"{name} bulunamadi: Windows SDK kurulu olmali "
                         "(https://developer.microsoft.com/windows/downloads/windows-sdk/).")
    return max(found)[1]


def version():
    with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
        v = f.read().strip()
    parts = (v.split(".") + ["0", "0", "0"])[:3]
    return ".".join(parts) + ".0"          # Store: 4 parca, sonuncu 0 olmali


def make_assets(assets):
    """Store/Baslat/gorev cubugu logolari. Logo zaten kendi koyu karesi olan bir
    uygulama ikonu: kucuk boyutlarda tam dolu, 150'lik karoda ortada %66."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    src = QImage(LOGO)
    if src.isNull():
        raise SystemExit(f"logo okunamadi: {LOGO}")

    def save(name, w, h, fill=1.0):
        img = QImage(w, h, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        side = max(1, round(min(w, h) * fill))
        logo = src.scaled(side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        p = QPainter(img)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage((w - logo.width()) // 2, (h - logo.height()) // 2, logo)
        p.end()
        img.save(os.path.join(assets, name), "PNG")

    for s in SCALES:
        k = s / 100
        save(f"Square44x44Logo.scale-{s}.png", round(44 * k), round(44 * k))
        save(f"Square150x150Logo.scale-{s}.png", round(150 * k), round(150 * k), 0.66)
        save(f"StoreLogo.scale-{s}.png", round(50 * k), round(50 * k))
    for t in TARGET_SIZES:
        save(f"Square44x44Logo.targetsize-{t}.png", t, t)
        save(f"Square44x44Logo.targetsize-{t}_altform-unplated.png", t, t)
        save(f"Square44x44Logo.targetsize-{t}_altform-lightunplated.png", t, t)


MANIFEST = """<?xml version="1.0" encoding="utf-8"?>
<Package
  xmlns="http://schemas.microsoft.com/appx/manifest/foundation/windows10"
  xmlns:uap="http://schemas.microsoft.com/appx/manifest/uap/windows10"
  xmlns:uap3="http://schemas.microsoft.com/appx/manifest/uap/windows10/3"
  xmlns:rescap="http://schemas.microsoft.com/appx/manifest/foundation/windows10/restrictedcapabilities"
  IgnorableNamespaces="uap uap3 rescap">

  <Identity Name="{name}" Publisher="{publisher}" Version="{version}" ProcessorArchitecture="x64" />

  <Properties>
    <DisplayName>{display}</DisplayName>
    <PublisherDisplayName>{pubdisplay}</PublisherDisplayName>
    <Logo>Assets\\StoreLogo.png</Logo>
  </Properties>

  <Dependencies>
    <TargetDeviceFamily Name="Windows.Desktop" MinVersion="10.0.17763.0" MaxVersionTested="10.0.26100.0" />
  </Dependencies>

  <Resources>
    <Resource Language="en-us" />
    <Resource Language="tr-tr" />
  </Resources>

  <Applications>
    <Application Id="RevoraPDF" Executable="Revora.exe" EntryPoint="Windows.FullTrustApplication">
      <uap:VisualElements DisplayName="{display}" Description="{description}"
        BackgroundColor="transparent"
        Square150x150Logo="Assets\\Square150x150Logo.png"
        Square44x44Logo="Assets\\Square44x44Logo.png" />
      <Extensions>
        <uap3:Extension Category="windows.fileTypeAssociation">
          <uap3:FileTypeAssociation Name="pdf" Parameters="&quot;%1&quot;">
            <uap:DisplayName>PDF</uap:DisplayName>
            <uap:SupportedFileTypes>
              <uap:FileType>.pdf</uap:FileType>
            </uap:SupportedFileTypes>
          </uap3:FileTypeAssociation>
        </uap3:Extension>
      </Extensions>
    </Application>
  </Applications>

  <Capabilities>
    <rescap:Capability Name="runFullTrust" />
  </Capabilities>
</Package>
"""


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout, r.stderr)
        raise SystemExit(f"HATA: {os.path.basename(cmd[0])} basarisiz (kod {r.returncode})")
    return r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(os.path.join(DIST, "Revora.exe")):
        raise SystemExit("dist\\Revora\\Revora.exe yok: once build_store.bat (PyInstaller) calismali.")
    ver = version()

    print("Paket klasoru hazirlaniyor...")
    if os.path.isdir(STAGE):
        shutil.rmtree(STAGE)
    shutil.copytree(DIST, STAGE)
    shutil.copyfile(os.path.join(ROOT, "LICENSE"), os.path.join(STAGE, "LICENSE.txt"))
    assets = os.path.join(STAGE, "Assets")
    os.makedirs(assets)
    make_assets(assets)
    manifest = os.path.join(STAGE, "AppxManifest.xml")
    with open(manifest, "w", encoding="utf-8") as f:
        f.write(MANIFEST.format(name=IDENTITY_NAME, publisher=PUBLISHER, version=ver,
                                display=DISPLAY_NAME, pubdisplay=PUBLISHER_DISPLAY,
                                description=DESCRIPTION))

    print("Kaynak dizini (resources.pri) olusturuluyor...")
    makepri = sdk_tool("makepri.exe")
    cfg = os.path.join(ROOT, "build", "priconfig.xml")
    run([makepri, "createconfig", "/cf", cfg, "/dq", "en-US", "/o"])
    run([makepri, "new", "/pr", STAGE, "/cf", cfg, "/mn", manifest,
         "/of", os.path.join(STAGE, "resources.pri"), "/o"])

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"RevoraPDF_{ver}_x64.msix")
    print("MSIX paketleniyor...")
    run([sdk_tool("makeappx.exe"), "pack", "/d", STAGE, "/p", out, "/o"])
    print(f"Hazir: {out}  ({os.path.getsize(out) / 1e6:.1f} MB, surum {ver})")

    if a.register:
        print("Bu bilgisayara gelistirici olarak kaydediliyor...")
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        f"Add-AppxPackage -Register '{manifest}' -ForceApplicationShutdown"], check=True)
        print("Kaydedildi: Baslat menusunde 'Revora PDF'.")


if __name__ == "__main__":
    main()
