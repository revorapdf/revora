@echo off
chcp 65001 >nul
title Revora - paketleme ve kurulum dosyasi
REM Dagitim icin paketler. TEST icin kullanma; test icin run.bat yeterli.
REM Cikti 1: dist\Revora\Revora.exe        (klasor hali)
REM Cikti 2: installer\Revora_Kurulum.exe   (baskasina verilecek TEK dosya)
REM Yeni surumde VERSION dosyasindaki surumu artirin (program ve kurulum oradan okur).

cd /d "%~dp0"
set PY=py
where py >nul 2>nul || set PY=python

if not exist "main.py" (
    echo HATA: main.py bu klasorde bulunamadi.
    goto :error
)

echo Gerekli paketler kontrol ediliyor...
%PY% -m pip install -r requirements.txt
if errorlevel 1 goto :error

echo.
echo Ikon hazirlaniyor (assets\revora.png -^> assets\revora.ico)...
%PY% assets\make_icon.py
if errorlevel 1 goto :error
%PY% assets\make_wizard_images.py
if errorlevel 1 goto :error

echo.
echo Eski paketleme dosyalari temizleniyor...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "Revora.spec" del /q "Revora.spec"

echo.
echo EXE olusturuluyor (birkac dakika surebilir)...
REM --onedir     : tek dosya (onefile) gibi her acilista gecici klasore acilmaz, hizli baslar
REM --icon       : exe dosyasinin Windows'ta gorunen ikonu
REM --add-data   : pencere/gorev cubugu ikonu icin logo (main.py resource_path ile bulur)
REM                ve dil dosyalari: locales klasoru (i18n.locales_dir)
REM PySide6 icin --collect-all KULLANILMIYOR: PyInstaller'in kendi kancasi gerekenleri
REM alir; hepsini toplamak paketi yuzlerce MB buyutup acilisi yavaslatir.
%PY% -m PyInstaller --noconfirm --clean --onedir --windowed ^
    --name "Revora" ^
    --icon "assets\revora.ico" ^
    --add-data "assets\revora.png;assets" ^
    --add-data "locales;locales" ^
    --add-data "VERSION;." ^
    --collect-all pymupdf ^
    --collect-data qtawesome ^
    "main.py"
if errorlevel 1 goto :error

echo.
echo Kurulum dosyasi olusturuluyor (Inno Setup)...
set ISCC=
for %%P in ("%ProgramFiles%\Inno Setup 7\ISCC.exe" "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" "%ProgramFiles%\Inno Setup 6\ISCC.exe" "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe") do (
    if not defined ISCC if exist %%P set ISCC=%%P
)
if not defined ISCC (
    echo UYARI: Inno Setup bulunamadi; sadece dist\Revora klasoru olusturuldu.
    echo Kurulum dosyasi icin https://jrsoftware.org/isdl.php adresinden Inno Setup kurun.
    explorer "%CD%\dist\Revora"
    pause
    exit /b 0
)
if exist "installer" rmdir /s /q "installer"
%ISCC% /Q "Revora.iss"
if errorlevel 1 goto :error

echo.
echo ============================================
echo BASARILI
echo Kurulum dosyasi: %CD%\installer\Revora_Kurulum.exe
echo Baskasina sadece bu dosyayi verin; cift tiklayinca Revora kurulur.
echo ============================================
echo.
explorer "%CD%\installer"
pause
exit /b 0

:error
echo.
echo ============================================
echo HATA: EXE olusturulamadi.
echo Yukaridaki hata mesajinin ekran goruntusunu alin.
echo ============================================
echo.
pause
exit /b 1
