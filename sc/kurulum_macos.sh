#!/bin/bash
# BeatDrop Studio — macOS Kurulum Başlatıcı

echo ""
echo "  BeatDrop Studio v1.0"
echo "  ─────────────────────────────────"
echo ""

# Python kontrolü
if ! command -v python3 &> /dev/null; then
    echo "  [HATA] Python 3 bulunamadı!"
    echo "  Homebrew ile kurun: brew install python3"
    exit 1
fi

PY_VER=$(python3 --version 2>&1)
echo "  $PY_VER bulundu."
echo ""
echo "  Kurulum sihirbazı açılıyor..."

# Sihirbazı başlat
python3 "$(dirname "$0")/installer/setup_wizard.py"
