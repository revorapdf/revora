@echo off
REM Microsoft Store paketi (MSIX) uretir: installer\RevoraPDF_<surum>_x64.msix
REM Partner Center'a bu dosya yuklenir. Surum VERSION dosyasindan okunur.
REM Gereken: Windows SDK (makeappx, makepri). Inno Setup GEREKMEZ.
call "%~dp0build_exe.bat" store
