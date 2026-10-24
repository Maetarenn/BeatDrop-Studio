@echo off
chcp 65001 > nul
title BeatDrop Studio — Kurulum

echo.
echo   ██████╗ ███████╗ █████╗ ████████╗
echo   ██╔══██╗██╔════╝██╔══██╗╚══██╔══╝
echo   ██████╔╝█████╗  ███████║   ██║
echo   ██╔══██╗██╔══╝  ██╔══██║   ██║
echo   ██████╔╝███████╗██║  ██║   ██║
echo   ╚═════╝ ╚══════╝╚═╝  ╚═╝   ╚═╝
echo.
echo   ██████╗ ██████╗  ██████╗ ██████╗
echo   ██╔══██╗██╔══██╗██╔═══██╗██╔══██╗
echo   ██║  ██║██████╔╝██║   ██║██████╔╝
echo   ██║  ██║██╔══██╗██║   ██║██╔═══╝
echo   ██████╔╝██║  ██║╚██████╔╝██║
echo   ╚═════╝ ╚═╝  ╚═╝ ╚═════╝ ╚═╝
echo.
echo   BeatDrop Studio v1.0
echo   AI-Powered Sound Design ^& Pacing
echo   ─────────────────────────────────────
echo.

:: Python var mi kontrol et
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo  [HATA] Python bulunamadi!
    echo.
    echo  Python 3.9+ kurmaniz gerekiyor:
    echo  https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PY_VER=%%v
echo  Python %PY_VER% bulundu.
echo.

:: Sihirbazi baslat
echo  Kurulum sihirbazi aciliyor...
python "%~dp0installer\setup_wizard.py"

if %errorlevel% neq 0 (
    echo.
    echo  [HATA] Sihirbaz baslatılamadı.
    echo  Manuel kurulum icin README.md dosyasini inceleyin.
    pause
)
