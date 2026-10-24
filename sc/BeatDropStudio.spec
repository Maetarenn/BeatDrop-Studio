# =============================================================================
# BeatDropStudio.spec — PyInstaller Build Spec
# =============================================================================
# Kullanım:
#   pyinstaller BeatDropStudio.spec
#
# Çıktı:
#   dist/BeatDropStudio_Setup.exe  (tek dosya, taşınabilir)
#
# Bu spec dosyası:
#   - Kurulum sihirbazını (setup_wizard.py) ana giriş noktası olarak alır
#   - installer_core.py'yi dahil eder
#   - Tüm proje dosyalarını (backend/, premiere-cep/, davinci-script/, assets/)
#     exe içine gömer
#   - Windows için özel ikon ve manifest uygular
# =============================================================================

import sys
from pathlib import Path

# Proje kök dizini (bu spec dosyasının bulunduğu yer)
ROOT = Path(SPECPATH)

block_cipher = None

# ─── Dahil edilecek veri dosyaları ──────────────────────────────────────────
# Format: (kaynak_yol, exe_içindeki_hedef_klasör)
datas = [
    # Installer core modülü
    (str(ROOT / "installer" / "scripts" / "installer_core.py"),
     "installer/scripts"),

    # Python backend dosyaları
    (str(ROOT / "backend" / "main.py"),            "backend"),
    (str(ROOT / "backend" / "audio_analyzer.py"),  "backend"),
    (str(ROOT / "backend" / "ai_pipeline.py"),     "backend"),
    (str(ROOT / "backend" / "models.py"),          "backend"),
    (str(ROOT / "backend" / "sfx_mapper.py"),      "backend"),
    (str(ROOT / "backend" / "requirements.txt"),   "backend"),

    # Premiere CEP eklentisi
    (str(ROOT / "premiere-cep"), "premiere-cep"),

    # DaVinci script
    (str(ROOT / "davinci-script"), "davinci-script"),

    # Assets (SFX klasörü)
    (str(ROOT / "assets"), "assets"),

    # CustomTkinter tema dosyaları (zorunlu — yoksa hata verir)
    (r"C:\Users\hmaki\AppData\Local\Python\pythoncore-3.14-64\Lib\site-packages\customtkinter",
     "customtkinter"),
]

# ─── Gizli import'lar (PyInstaller otomatik bulamazsa) ───────────────────────
hiddenimports = [
    # Tkinter (standart)
    "tkinter",
    "tkinter.ttk",
    "tkinter.messagebox",
    "tkinter.scrolledtext",
    # CustomTkinter ve bağımlılıkları
    "customtkinter",
    "customtkinter.windows",
    "customtkinter.windows.widgets",
    "customtkinter.windows.widgets.theme",
    "darkdetect",
    # Standart kütüphane
    "threading",
    "pathlib",
    "json",
    "subprocess",
    "platform",
    "shutil",
    "winreg",
]

# ─── Analysis ────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "installer" / "setup_wizard.py")],
    pathex=[
        str(ROOT / "installer"),
        str(ROOT / "installer" / "scripts"),
    ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # AI kütüphaneleri exe'ye dahil edilmez — pip ile kurulur
        "torch", "torchaudio", "tensorflow", "transformers",
        "librosa", "numpy", "scipy", "fastapi", "uvicorn",
        # Gereksiz büyük modüller
        "matplotlib", "PIL", "cv2", "sklearn",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ─── PYZ (bytecode arşivi) ───────────────────────────────────────────────────
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ─── EXE (tek dosya) ─────────────────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="BeatDropStudio_Setup",        # Çıktı dosya adı
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,                           # UPX ile sıkıştır (daha küçük boyut)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,                      # GUI modu — siyah terminal penceresi açılmaz
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows manifest — UAC yönetici izni ister
    uac_admin=True,
    uac_uiaccess=False,
    # Windows ikon (varsa)
    icon=str(ROOT / "installer" / "assets" / "icon.ico")
    if (ROOT / "installer" / "assets" / "icon.ico").exists()
    else None,
    # Sürüm bilgisi (varsa)
    version=str(ROOT / "installer" / "assets" / "version_info.txt")
    if (ROOT / "installer" / "assets" / "version_info.txt").exists()
    else None,
)
