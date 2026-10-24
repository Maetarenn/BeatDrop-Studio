@echo off
chcp 65001 > nul
title BeatDrop Studio — EXE Build

echo.
echo  ╔══════════════════════════════════════╗
echo  ║   BeatDrop Studio — EXE Derleyici   ║
echo  ║   PyInstaller ile tek .exe paket     ║
echo  ╚══════════════════════════════════════╝
echo.

:: Python kontrolü
python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadı!
    pause & exit /b 1
)

:: PyInstaller kontrolü
python -m PyInstaller --version > nul 2>&1
if %errorlevel% neq 0 (
    echo PyInstaller kuruluyor...
    python -m pip install pyinstaller
)

:: Önceki build klasörlerini temizle
echo [1/4] Önceki build temizleniyor...
if exist "build"        rmdir /s /q "build"
if exist "dist"         rmdir /s /q "dist"

:: Boş assets/sfx klasörü oluştur (exe içine gömülür)
echo [2/4] Klasör yapısı hazırlanıyor...
if not exist "assets\sfx" mkdir "assets\sfx"

:: README oluştur (SFX klasörü için)
echo Bu klasore asagidaki WAV dosyalarini ekleyin: > "assets\sfx\BURAYA_EKLE.txt"
echo   whoosh.wav   - Sahne gecisi efekti >> "assets\sfx\BURAYA_EKLE.txt"
echo   sub_bass.wav - Guclu vurgu efekti  >> "assets\sfx\BURAYA_EKLE.txt"
echo   pop.wav      - Kelime vurgu efekti >> "assets\sfx\BURAYA_EKLE.txt"
echo   ding.wav     - Hafif bildirim      >> "assets\sfx\BURAYA_EKLE.txt"

:: EXE'yi derle
echo [3/4] EXE derleniyor... (1-3 dakika surebilir)
echo.
python -m PyInstaller BeatDropStudio.spec --clean --noconfirm

if %errorlevel% neq 0 (
    echo.
    echo [HATA] Derleme basarisiz!
    echo Build loglarini inceleyin.
    pause
    exit /b 1
)

:: Sonucu kontrol et
if not exist "dist\BeatDropStudio_Setup.exe" (
    echo [HATA] EXE olusturulamadi!
    pause & exit /b 1
)

:: Boyutu göster
echo.
echo [4/4] Tamamlandi!
echo.
for %%F in ("dist\BeatDropStudio_Setup.exe") do (
    set /a SIZE_MB=%%~zF / 1048576
    echo  Dosya : dist\BeatDropStudio_Setup.exe
    echo  Boyut : !SIZE_MB! MB
)
echo.
echo  Kullanicilara dagitmak icin:
echo  dist\BeatDropStudio_Setup.exe dosyasini gonderin.
echo.

:: dist klasörünü aç
explorer "dist"
pause
