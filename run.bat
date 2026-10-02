@echo off
REM Gelistirirken TEST icin: cift tikla, uygulama acilir. (Paketleme YOK.)
REM Bir PDF'i bu dosyanin ustune surukleyip birakirsan dogrudan onu acar.
cd /d "%~dp0"
REM "py" baslaticisi her bilgisayarda yok; yoksa "python" kullan
set PY=py
where py >nul 2>nul || set PY=python
%PY% main.py %*
if errorlevel 1 (
  echo.
  echo Uygulama beklenmedik sekilde kapandi. Hata mesaji icin:
  %PY% -u main.py %* > "%~dp0run_log.txt" 2>&1
  echo Ayrinti run_log.txt dosyasina yazildi.
  pause
)
