; Revora kurulum dosyasi (Inno Setup betigi)
; build_exe.bat paketlemeden sonra bunu ISCC ile derler:
;   dist\Revora\  ->  installer\Revora_Kurulum.exe
;
; YENI SURUM: sadece VERSION dosyasini degistir (program "Hakkinda" da oradan okur).
; AppId ASLA degismemeli; ayni AppId sayesinde yeni kurulum eskisinin uzerine guncellenir.
; Bu dosya BOM'lu UTF-8 olmali (yoksa sihirbazdaki Turkce karakterler bozulur).

#define AppName "Revora"
#define VerFile FileOpen(AddBackslash(SourcePath) + "VERSION")
#define AppVersion Trim(FileRead(VerFile))
#expr FileClose(VerFile)
#define AppExe "Revora.exe"

[Setup]
AppId={{1E997DF1-B60B-45E0-B838-4C6DFAC51FD4}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=Revora PDF
AppPublisherURL=https://revorapdf.com
AppSupportURL=https://revorapdf.com
AppCopyright=© 2026 Revora PDF — GNU AGPL-3.0
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} PDF Editor Setup
; Kurulumun basinda secim sorulur:
;  "Sadece benim icin"  -> yonetici istemez, %LOCALAPPDATA%\Programs\Revora (varsayilan)
;  "Tum kullanicilar"   -> yonetici izni ister, C:\Program Files\Revora
; {autopf}, {autoprograms}, {autodesktop} ve HKA secilen moda gore kendiliginden degisir.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=Revora_Kurulum
SetupIconFile=assets\revora.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
WizardStyle=modern
; sag ustteki kucuk gorsel: Revora logosu (ekran olcegine gore uygun boyut secilir)
WizardSmallImageFile=assets\installer\wizard_small_55.bmp,assets\installer\wizard_small_69.bmp,assets\installer\wizard_small_83.bmp,assets\installer\wizard_small_110.bmp,assets\installer\wizard_small_138.bmp
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; guncellerken acik Revora'yi kapatmayi teklif et
CloseApplications=yes
; kurulumun basinda dil sorulur (guncellemede onceki secim hatirlanir)
ShowLanguageDialog=yes

[Languages]
; InfoBeforeFile: kurulumdan once bilgi sayfasi (Revora'nin AGPL-3.0 lisansi, kaynak kodu
; adresi, kullanilan acik kaynak bilesenler). "Kabul ediyorum" (LicenseFile) sayfasi YOK:
; AGPL kullanmak icin kabul istemez; tam metin {app}\LICENSE.txt olarak kurulur.
Name: "turkish"; MessagesFile: "compiler:Languages\Turkish.isl"; InfoBeforeFile: "assets\installer\bilgi_tr.txt"
Name: "english"; MessagesFile: "compiler:Default.isl"; InfoBeforeFile: "assets\installer\bilgi_en.txt"

[CustomMessages]
turkish.PdfMenu=PDF dosyalarına sağ tıklayınca "Revora ile aç" seçeneği ekle (varsayılan PDF programınız değişmez)
english.PdfMenu=Add "Open with Revora" to the right-click menu of PDF files (your default PDF program does not change)
turkish.OtherOptions=Ek seçenekler:
english.OtherOptions=Other options:
turkish.OpenWith=Revora ile aç
english.OpenWith=Open with Revora

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "pdfmenu"; Description: "{cm:PdfMenu}"; GroupDescription: "{cm:OtherOptions}"; Flags: unchecked

[InstallDelete]
; guncellemede onceki surumun kutuphaneleri karismasin
Type: filesandordirs; Name: "{app}\_internal"

[Files]
Source: "dist\Revora\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Registry]
; "Revora ile ac" sag tik menusu (kaldirinca silinir). HKA: "sadece benim icin"
; kurulumda bu kullanici (HKCU), "tum kullanicilar"da herkes (HKLM).
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\Revora"; ValueType: string; ValueName: ""; ValueData: "{cm:OpenWith}"; Flags: uninsdeletekey; Tasks: pdfmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\Revora"; ValueType: string; ValueName: "Icon"; ValueData: """{app}\{#AppExe}"",0"; Tasks: pdfmenu
Root: HKA; Subkey: "Software\Classes\SystemFileAssociations\.pdf\shell\Revora\command"; ValueType: string; ValueName: ""; ValueData: """{app}\{#AppExe}"" ""%1"""; Tasks: pdfmenu
; Program dili = kurulumda secilen dil (program QSettings("PdfEdit","PdfEdit") okur).
; createvalueifdoesntexist: kullanici programin icinden dil sectiyse guncelleme onu ezmez.
Root: HKCU; Subkey: "Software\PdfEdit\PdfEdit"; ValueType: string; ValueName: "language"; ValueData: "tr-TR"; Languages: turkish; Flags: createvalueifdoesntexist
Root: HKCU; Subkey: "Software\PdfEdit\PdfEdit"; ValueType: string; ValueName: "language"; ValueData: "en-US"; Languages: english; Flags: createvalueifdoesntexist

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
