"""
=============================================================================
installer_core.py — BeatDrop Studio
Kurulum Motoru (Tüm platformlarda çalışır: Windows & macOS)
=============================================================================
Bu modül kurulum sihirbazı GUI'si tarafından çağrılır.
Bağımsız da çalışabilir: python installer_core.py

Yapılanlar:
  1. Python 3.9+ kontrolü
  2. Adobe Premiere Pro kurulum yolu tespiti (registry & sabit yollar)
  3. DaVinci Resolve kurulum yolu tespiti
  4. Virtual environment oluşturma
  5. Bağımlılık kurulumu (temel + opsiyonel AI)
  6. CEP eklenti dosyalarını kopyalama (Premiere)
  7. DaVinci script dosyasını kopyalama
  8. Backend otomatik başlatma servisi kurma
  9. Windows: Başlangıç kısayolu / Görev Zamanlayıcı
  10. macOS: LaunchAgent plist
=============================================================================
"""

import os
import sys
import shutil
import subprocess
import platform
import json
import time
from pathlib import Path
from typing import Optional, Callable


IS_WINDOWS = platform.system() == "Windows"
IS_MAC     = platform.system() == "Darwin"

# ─── İki farklı kök yolu ─────────────────────────────────────────────────
#
# BUNDLE_ROOT : Kaynak dosyaların okunacağı yer
#   - EXE modunda: sys._MEIPASS (PyInstaller geçici klasörü — okuma amaçlı)
#   - Script modunda: proje kökü
#
# INSTALL_ROOT: Dosyaların KALICI olarak kurulacağı yer
#   - EXE modunda: EXE'nin bulunduğu klasör (dist/ → müşteri bilgisayarında
#                  EXE'yi koyduğu yer)
#   - Script modunda: proje kökü (aynı)
#
# BUG FIX: Önceki sürüm PRODUCT_ROOT=sys._MEIPASS kullanıyordu.
# _MEIPASS geçici bir temp klasörüdür, EXE kapanınca silinir.
# Venv ve kurulum dosyaları orada oluşturulamaz.

def _resolve_bundle_root() -> Path:
    """Kaynak dosyaların okunduğu yer (bundled assets)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)          # PyInstaller temp — READONLY
    return Path(__file__).parent.parent.parent.resolve()

def _resolve_install_root() -> Path:
    """Dosyaların kalıcı olarak yazılacağı yer."""
    if getattr(sys, "frozen", False):
        # EXE'nin bulunduğu dizin — kullanıcının seçtiği yer
        return Path(sys.executable).parent
    return Path(__file__).parent.parent.parent.resolve()

BUNDLE_ROOT  = _resolve_bundle_root()   # kaynak okuma
INSTALL_ROOT = _resolve_install_root()  # kurulum hedefi
PRODUCT_ROOT = INSTALL_ROOT             # geriye dönük uyumluluk

# Kaynak dosyalar BUNDLE_ROOT'tan okunur
BACKEND_DIR = BUNDLE_ROOT / "backend"
CEP_SRC_DIR = BUNDLE_ROOT / "premiere-cep"
DV_SRC_DIR  = BUNDLE_ROOT / "davinci-script"


# ===========================================================================
# Progress Callback Tipi
# ===========================================================================
# Kurulum adımlarında GUI'ye ilerleme bildirmek için kullanılır.
# Signature: progress_cb(percent: int, message: str)
ProgressCallback = Callable[[int, str], None]


def _default_cb(pct: int, msg: str):
    print(f"[{pct:3d}%] {msg}")


# ===========================================================================
# 1. Sistem Kontrolü
# ===========================================================================

def check_python_version() -> tuple[bool, str]:
    """Python 3.9+ kurulu ve yeterli versiyon mu kontrol eder."""
    major, minor = sys.version_info[:2]
    if major < 3 or (major == 3 and minor < 9):
        return False, f"Python 3.9+ gerekli (mevcut: {major}.{minor})"
    return True, f"Python {major}.{minor} ✓"


def find_system_python() -> Optional[str]:
    """
    Sistemde kurulu Python 3.9+ bulur.
    ÖNEMLI: WindowsApps stub'ı (Microsoft Store yönlendirmesi) ATLANIR —
    bu sahte exe venv oluşturamaz.
    """
    import shutil

    def _is_valid(path: str) -> bool:
        """Gerçek Python exe mi kontrol eder (Store stub değil)."""
        if not path:
            return False
        # Windows Store stub'larını atla
        if "WindowsApps" in path:
            return False
        try:
            r = subprocess.run(
                [path, "-c", "import sys; print(sys.version_info[:2])"],
                capture_output=True, text=True, timeout=5
            )
            if r.returncode != 0:
                return False
            # "(3, 9)" gibi bir tuple bekliyoruz
            ver = eval(r.stdout.strip())
            return isinstance(ver, tuple) and ver[0] == 3 and ver[1] >= 9
        except Exception:
            return False

    # PATH'te ara
    for cmd in ["python3", "python", "py"]:
        path = shutil.which(cmd)
        if path and _is_valid(path):
            return path

    if not IS_WINDOWS:
        return None

    # Windows'ta yaygın kurulum yollarını tara
    import glob, os
    username = os.getenv("USERNAME", "*")
    patterns = [
        r"C:\Python3*\python.exe",
        r"C:\Program Files\Python3*\python.exe",
        r"C:\Program Files (x86)\Python3*\python.exe",
        rf"C:\Users\{username}\AppData\Local\Programs\Python\Python3*\python.exe",
    ]
    for pattern in patterns:
        for found in sorted(glob.glob(pattern), reverse=True):  # yeniden eskiye
            if _is_valid(found):
                return found

    return None


def install_python_windows(cb: "ProgressCallback" = None) -> bool:
    """
    Windows'ta Python 3.12'yi otomatik kurar.
    Önce winget, sonra direkt indirme dener.
    Yönetici yetkisi gerektirir.
    """
    if cb:
        cb(3, "Python bulunamadı — otomatik kuruluyor...")

    # Yöntem 1: winget (Windows 11 / güncel Win10)
    import shutil
    if shutil.which("winget"):
        try:
            if cb: cb(5, "winget ile Python 3.12 kuruluyor...")
            result = subprocess.run(
                ["winget", "install", "--id", "Python.Python.3.12",
                 "--silent", "--accept-source-agreements",
                 "--accept-package-agreements"],
                capture_output=True, timeout=300
            )
            if result.returncode == 0:
                if cb: cb(15, "Python 3.12 kuruldu (winget) ✓")
                return True
        except Exception as e:
            if cb: cb(5, f"winget başarısız: {e} — web'den indiriliyor...")

    # Yöntem 2: Direkt web'den indir
    import urllib.request
    import tempfile
    PY_URL = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-amd64.exe"
    tmp = Path(tempfile.gettempdir()) / "python_installer.exe"

    try:
        if cb: cb(6, "Python 3.12 indiriliyor (~25 MB)...")

        def _progress(block, block_size, total):
            if total > 0 and cb:
                pct = min(int(block * block_size / total * 8) + 6, 13)
                cb(pct, f"İndiriliyor... {int(block * block_size / 1024 / 1024)} MB")

        urllib.request.urlretrieve(PY_URL, tmp, _progress)

        if cb: cb(13, "Python kuruluyor (sessiz mod)...")
        result = subprocess.run(
            [str(tmp), "/quiet", "InstallAllUsers=0",
             "PrependPath=1", "Include_pip=1"],
            capture_output=True, timeout=300
        )
        tmp.unlink(missing_ok=True)

        if result.returncode == 0:
            if cb: cb(15, "Python 3.12 kuruldu ✓")
            return True
        else:
            if cb: cb(3, f"Python kurulum hatası: {result.stderr.decode()[:100]}")
            return False

    except Exception as e:
        if cb: cb(3, f"Python indirme hatası: {e}")
        tmp.unlink(missing_ok=True)
        return False



# ===========================================================================
# 2. Program Tespiti
# ===========================================================================

class ProgramDetector:
    """
    Bilgisayarda kurulu video düzenleme yazılımlarını tespit eder.
    Windows Registry ve sabit yollar üzerinden arama yapar.
    """

    def detect_all(self) -> dict:
        """
        Tespit edilen tüm programları döndürür.
        {
            "premiere": {"found": bool, "version": str, "cep_path": str},
            "davinci":  {"found": bool, "version": str, "script_path": str},
        }
        """
        return {
            "premiere": self._detect_premiere(),
            "davinci":  self._detect_davinci(),
        }

    # -----------------------------------------------------------------------
    def _detect_premiere(self) -> dict:
        """Adobe Premiere Pro'yu tespit eder."""
        result = {"found": False, "version": "?", "cep_path": ""}

        if IS_WINDOWS:
            cep_path = Path(os.environ.get("APPDATA", "")) / \
                       "Adobe" / "CEP" / "extensions"
            result["cep_path"] = str(cep_path)

            # Registry'den versiyon bul
            version = self._win_registry_premiere_version()
            if version:
                result["found"]   = True
                result["version"] = version
                return result

            # Registry bulamazsa sabit yolları tara
            for year in range(2024, 2019, -1):
                paths = [
                    Path(f"C:/Program Files/Adobe/Adobe Premiere Pro {year}"),
                    Path(f"C:/Program Files/Adobe/Adobe Premiere Pro CC {year}"),
                ]
                for p in paths:
                    if p.exists():
                        result["found"]   = True
                        result["version"] = str(year)
                        return result

        elif IS_MAC:
            cep_path = Path.home() / "Library" / "Application Support" / \
                       "Adobe" / "CEP" / "extensions"
            result["cep_path"] = str(cep_path)

            for year in range(2024, 2019, -1):
                paths = [
                    Path(f"/Applications/Adobe Premiere Pro {year}/"
                         f"Adobe Premiere Pro {year}.app"),
                    Path(f"/Applications/Adobe Premiere Pro/Adobe Premiere Pro.app"),
                ]
                for p in paths:
                    if p.exists():
                        result["found"]   = True
                        result["version"] = str(year)
                        return result

        return result

    def _win_registry_premiere_version(self) -> Optional[str]:
        """Windows Registry'den Premiere Pro versiyonunu okur."""
        if not IS_WINDOWS:
            return None
        try:
            import winreg
            base = r"SOFTWARE\Adobe\Premiere Pro"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
                version, _ = winreg.QueryValueEx(key, "CurrentVersion")
                return str(version)
        except Exception:
            return None

    # -----------------------------------------------------------------------
    def _detect_davinci(self) -> dict:
        """DaVinci Resolve'u tespit eder."""
        result = {"found": False, "version": "?", "script_path": ""}

        if IS_WINDOWS:
            # DaVinci Resolve UI menüsü "Workspace -> Scripts" altını Fusion/Scripts klasörlerinden okur!
            # Hem Utility (menünün hemen altında görünür) hem Edit klasörüne kuruyoruz.
            script_path = (
                Path(os.environ.get("PROGRAMDATA", "")) /
                "Blackmagic Design" / "DaVinci Resolve" /
                "Fusion" / "Scripts" / "Utility"
            )
            result["script_path"] = str(script_path)

            # Tespit yolları
            detect_paths = [
                Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"),
                Path(r"C:\Program Files\Blackmagic Design\DaVinci Resolve Studio\Resolve.exe"),
            ]
            for p in detect_paths:
                if p.exists():
                    result["found"]   = True
                    result["version"] = self._get_davinci_version_win(p)
                    return result

            # Registry
            version = self._win_registry_davinci_version()
            if version:
                result["found"]   = True
                result["version"] = version

        elif IS_MAC:
            script_path = (
                Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve") /
                "Developer" / "Scripting" / "Scripts" / "Edit"
            )
            result["script_path"] = str(script_path)

            detect_paths = [
                Path("/Applications/DaVinci Resolve/DaVinci Resolve.app"),
                Path("/Applications/DaVinci Resolve Studio/DaVinci Resolve.app"),
            ]
            for p in detect_paths:
                if p.exists():
                    result["found"]   = True
                    result["version"] = "detected"
                    return result

        return result

    def _win_registry_davinci_version(self) -> Optional[str]:
        if not IS_WINDOWS:
            return None
        try:
            import winreg
            base = r"SOFTWARE\Blackmagic Design\DaVinci Resolve"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as key:
                version, _ = winreg.QueryValueEx(key, "Version")
                return str(version)
        except Exception:
            return None

    @staticmethod
    def _get_davinci_version_win(exe_path: Path) -> str:
        try:
            import winreg
            key_path = r"SOFTWARE\Blackmagic Design\DaVinci Resolve"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as k:
                v, _ = winreg.QueryValueEx(k, "Version")
                return str(v)
        except Exception:
            return "detected"


# ===========================================================================
# 3. Sanal Ortam & Bağımlılık Kurulumu
# ===========================================================================

class DependencyInstaller:
    """
    Python bağımlılıklarını sanal ortama yükler.
    Önce uv paket yöneticisini dener (pip'ten 10-100x hızlı),
    bulamazsa otomatik kurar, o da olmazsa pip'e düşer.
    """

    def __init__(self, venv_dir: Path, python_exe: str = None):
        self.venv_dir    = venv_dir
        self.base_python = python_exe or sys.executable
        self._uv_exe: Optional[str] = None  # uv bulununca dolar

        if IS_WINDOWS:
            self.python = venv_dir / "Scripts" / "python.exe"
            self.pip    = venv_dir / "Scripts" / "pip.exe"
        else:
            self.python = venv_dir / "bin" / "python"
            self.pip    = venv_dir / "bin" / "pip"

    # ── uv desteği ────────────────────────────────────────────────────
    def _find_or_install_uv(self, cb) -> Optional[str]:
        """
        uv paket yöneticisini bulur veya kurar.
        uv: Rust tabanlı ultra-hızlı pip alternatifi (pip'ten 10-100x hızlı).
        Başarılıysa uv exe yolunu, başarısızsa None döndürür.
        """
        import shutil

        # 1. PATH'te var mı?
        found = shutil.which("uv")
        if found:
            cb(21, f"uv bulundu: {found} ✓")
            return found

        # 2. Venv içinde var mı? (önceki kurulumdan kalmış olabilir)
        uv_venv = (self.venv_dir / "Scripts" / "uv.exe") if IS_WINDOWS \
                  else (self.venv_dir / "bin" / "uv")
        if uv_venv.exists():
            return str(uv_venv)

        # 3. pip ile kur (uv çok küçük ~5 MB, hızlı iner)
        cb(21, "uv kuruluyor (hızlı pip alternatifi)...")
        try:
            result = subprocess.run(
                [self.base_python, "-m", "pip", "install", "uv",
                 "--quiet", "--prefer-binary"],
                capture_output=True, timeout=60
            )
            if result.returncode == 0:
                # pip ile kuruldu — PATH'te veya user bin'de olabilir
                found = shutil.which("uv") or str(uv_venv)
                if Path(found).exists():
                    cb(22, "uv kuruldu ✓")
                    return found
        except Exception:
            pass

        cb(22, "uv kurulamadı — pip kullanılacak (biraz daha yavaş)")
        return None

    def create_venv(self, cb: ProgressCallback = _default_cb) -> bool:
        """
        Sanal Python ortamı oluşturur.
        uv varsa uv venv (çok hızlı), yoksa python -m venv.
        """
        cb(20, f"Python sanal ortami olusturuluyor: {self.venv_dir}")

        # uv bul veya kur
        self._uv_exe = self._find_or_install_uv(cb)

        # Zaten varsa yeniden oluşturma
        if self.python.exists():
            cb(30, "Mevcut sanal ortam kullanılıyor ✓")
            return True

        # Klasörü oluştur
        self.venv_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            if self._uv_exe:
                # uv venv — hızlı, NOT: --seed eski uv flag'i, kullanma
                result = subprocess.run(
                    [self._uv_exe, "venv", str(self.venv_dir),
                     "--python", self.base_python],
                    capture_output=True, timeout=60
                )
                if result.returncode != 0:
                    err = (result.stderr or b"").decode(errors="replace")
                    cb(22, f"uv venv hatası: {err[:100]} — python -m venv deneniyor...")
                    # uv başarısız → pip'e düş
                    subprocess.run(
                        [self.base_python, "-m", "venv", str(self.venv_dir)],
                        check=True, capture_output=True, timeout=120
                    )
            else:
                subprocess.run(
                    [self.base_python, "-m", "venv", str(self.venv_dir)],
                    check=True, capture_output=True, timeout=120
                )

            if self.python.exists():
                cb(30, "Sanal ortam hazır ✓")
                return True
            else:
                cb(0, f"Sanal ortam oluşturuldu ama python bulunamadı: {self.python}")
                return False

        except subprocess.CalledProcessError as e:
            err = (e.stderr or b"").decode(errors="replace")
            cb(0, f"Sanal ortam hatası: {err[:300]}")
            return False
        except Exception as e:
            cb(0, f"Sanal ortam beklenmeyen hata: {e}")
            return False


    def _pip_run(self, packages: list, cb, start_pct: int, end_pct: int,
                 label: str, timeout: int = 600) -> bool:
        """
        Paket kurulumunu canlı output ile çalıştırır.
        uv varsa → uv pip install (10-100x hızlı)
        yoksa    → pip install --prefer-binary (yedek)
        """
        if self._uv_exe:
            # uv pip install — paralel indirme, önbellek, çok hızlı
            cmd = [
                self._uv_exe, "pip", "install",
                "--python", str(self.python),
                "--no-progress",
            ] + packages
        else:
            # Yedek: pip --prefer-binary
            cmd = [
                str(self.pip), "install",
                "--prefer-binary",
                "--no-compile",
                "--quiet",
                "--progress-bar", "off",
            ] + packages

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            total = max(len(packages), 1)
            done  = 0
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                # uv: "Installed X packages" / pip: "Successfully installed"
                if any(k in line for k in (
                    "Installed", "Successfully installed", "already satisfied",
                    "Resolved", "Downloaded", "Built"
                )):
                    done = min(done + 1, total)
                pct = start_pct + int((done / total) * (end_pct - start_pct))
                cb(min(pct, end_pct - 1), f"{label}: {line[:75]}")

            proc.wait(timeout=timeout)
            if proc.returncode != 0:
                cb(start_pct, f"{label} hatası (kod {proc.returncode})")
                return False
            cb(end_pct, f"{label} tamamlandı ✓")
            return True

        except subprocess.TimeoutExpired:
            proc.kill()
            cb(start_pct, f"{label} zaman aşımı — internet bağlantısını kontrol edin")
            return False
        except Exception as e:
            cb(start_pct, f"{label} hatası: {e}")
            return False

    def install_core(self, cb: ProgressCallback = _default_cb) -> bool:
        """
        Temel backend bağımlılıklarını yükler.
        uv ile tüm paketler paralel indirilir — çok hızlı.
        """
        # pip/uv güncelle
        cb(32, "Paket yöneticisi hazırlanıyor...")
        if self._uv_exe:
            cb(33, "uv hazır — hızlı kurulum modu aktif ⚡")
        else:
            subprocess.run(
                [str(self.pip), "install", "--upgrade", "pip", "--quiet"],
                capture_output=True, timeout=60
            )
            cb(33, "pip güncellendi ✓")

        # uv varsa HEPSİNİ TEK SEFERDE kur (paralel indirme = çok hızlı)
        all_packages = [
            "fastapi==0.111.0",
            "uvicorn[standard]==0.30.1",
            "python-multipart==0.0.9",
            "websockets==12.0",
            "pydantic==2.7.1",
            "requests==2.32.3",
            "soundfile==0.12.1",
            "numpy==1.26.4",
            "scipy==1.13.1",
            "librosa==0.10.2.post1",
        ]

        if self._uv_exe:
            # uv: tümünü paralel kur (~30-90 sn)
            if not self._pip_run(all_packages, cb, 34, 82,
                                 "⚡ Hızlı kurulum (uv)", timeout=300):
                return False
        else:
            # pip yedek: grup grup kur
            g1 = all_packages[:7]
            g2 = ["numpy==1.26.4", "scipy==1.13.1"]
            g3 = ["librosa==0.10.2.post1"]
            if not self._pip_run(g1, cb, 34, 50, "Temel paketler", timeout=180):
                return False
            if not self._pip_run(g2, cb, 50, 65, "Bilimsel kütüphaneler", timeout=180):
                return False
            if not self._pip_run(g3, cb, 65, 80, "Ses analiz motoru", timeout=300):
                return False

        cb(82, "Tüm temel kütüphaneler kuruldu ✓")
        return True

    def install_ai(self, cb: ProgressCallback = _default_cb) -> bool:
        """Opsiyonel AI kütüphanelerini yükler."""
        cb(83, "AI modülleri yükleniyor — 10-20 dk sürebilir (büyük indirme)...")

        ok1 = self._pip_run(["openai-whisper==20231117"],
                            cb, 83, 87, "Whisper", timeout=300)
        ok2 = self._pip_run(
            ["tensorflow==2.16.1", "tensorflow-hub==0.16.1", "transformers==4.41.2"],
            cb, 87, 93, "TensorFlow/Transformers", timeout=900)
        ok3 = self._pip_run(["torch==2.3.0", "torchaudio==2.3.0"],
                            cb, 93, 98, "PyTorch", timeout=1200)

        if ok1 and ok2 and ok3:
            cb(98, "AI modülleri kuruldu ✓")
            return True
        cb(98, "AI modüllerinin bir kısmı kurulamadı — temel özellikler çalışır")
        return False



# ===========================================================================
# 4. Dosya Kopyalama
# ===========================================================================

class FileDeployer:
    """Eklenti dosyalarını hedef konumlara kopyalar."""

    def deploy_premiere(self, cep_extensions_dir: str, cb: ProgressCallback = _default_cb) -> bool:
        """Premiere Pro CEP eklentisini kopyalar."""
        target = Path(cep_extensions_dir) / "BeatDropStudio"
        cb(82, f"Premiere Pro paneli kopyalanıyor → {target}")
        try:
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(CEP_SRC_DIR, target)
            # Registry'de debug modunu etkinleştir (geliştirici CEP panelleri için)
            if IS_WINDOWS:
                self._enable_cep_debug_win()
            cb(88, "Premiere Pro paneli kuruldu ✓")
            return True
        except Exception as e:
            cb(0, f"Premiere kurulum hatası: {e}")
            return False

    def deploy_davinci(self, script_dir: str, cb: ProgressCallback = _default_cb) -> bool:
        """DaVinci Resolve script'ini kopyalar (hem ortak hem kullanıcı klasörlerine)."""
        src_file = DV_SRC_DIR / "davinci_bridge.py"
        cb(90, f"DaVinci script kopyalanıyor...")

        target_dirs = [Path(script_dir)]
        if IS_WINDOWS:
            prog_data = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData"))
            app_data = Path(os.environ.get("APPDATA", ""))
            target_dirs.extend([
                prog_data / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts" / "Utility",
                prog_data / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts" / "Edit",
                app_data / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Utility",
                app_data / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts" / "Edit",
            ])
        elif IS_MAC:
            target_dirs.append(
                Path.home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts" / "Utility"
            )

        src_py = DV_SRC_DIR / "davinci_bridge.py"
        src_lua = DV_SRC_DIR / "BeatDropStudio.lua"

        success = False
        for t_dir in set(target_dirs):
            try:
                t_dir.mkdir(parents=True, exist_ok=True)
                if src_py.exists():
                    shutil.copy2(src_py, t_dir / "BeatDropStudio.py")
                if src_lua.exists():
                    shutil.copy2(src_lua, t_dir / "BeatDropStudio.lua")
                success = True
            except Exception:
                pass

        if success:
            cb(92, "DaVinci Resolve script kuruldu ✓")
            return True
        else:
            cb(0, "DaVinci Resolve script kopyalanamadı")
            return False

    @staticmethod
    def _enable_cep_debug_win():
        """Windows'ta CEP eklentilerinin çalışması için debug modunu açar."""
        try:
            import winreg
            # CSXS sürümlerini dene (9, 10, 11, 12)
            for ver in ["9", "10", "11", "12"]:
                key_path = rf"SOFTWARE\Adobe\CSXS.{ver}"
                try:
                    with winreg.OpenKey(
                        winreg.HKEY_CURRENT_USER, key_path,
                        0, winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY
                    ) as key:
                        winreg.SetValueEx(key, "PlayerDebugMode", 0, winreg.REG_SZ, "1")
                except Exception:
                    pass
        except ImportError:
            pass  # winreg sadece Windows'ta var


# ===========================================================================
# 5. Backend Otomatik Başlatma
# ===========================================================================

class AutoStartManager:
    """Backend sunucusunu sistem başlangıcında otomatik başlatır."""

    def __init__(self, venv_dir: Path):
        self.venv_dir = venv_dir
        if IS_WINDOWS:
            self.python_exe = venv_dir / "Scripts" / "python.exe"
        else:
            self.python_exe = venv_dir / "bin" / "python"
        self.backend_script = BACKEND_DIR / "main.py"

    def setup_windows(self, cb: ProgressCallback = _default_cb) -> bool:
        """Windows Görev Zamanlayıcı görevi oluşturur."""
        cb(94, "Otomatik başlatma ayarlanıyor (Windows Task Scheduler)...")
        try:
            # Başlangıç bat dosyası oluştur
            bat_path = PRODUCT_ROOT / "installer" / "_start_backend.bat"
            bat_content = (
                f'@echo off\n'
                f'cd /d "{BACKEND_DIR}"\n'
                f'"{self.python_exe}" -m uvicorn main:app '
                f'--host 127.0.0.1 --port 8765 --log-level warning\n'
            )
            bat_path.write_text(bat_content, encoding="utf-8")

            # Görev Zamanlayıcı XML'i oluştur
            xml_path = PRODUCT_ROOT / "installer" / "_task.xml"
            xml_content = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Smart Sound Design Backend Server</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger><Enabled>true</Enabled></LogonTrigger>
  </Triggers>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>"{bat_path}"</Command>
      <WorkingDirectory>{BACKEND_DIR}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""
            xml_path.write_text(xml_content, encoding="utf-16")

            subprocess.run(
                ["schtasks", "/Create", "/TN", "BeatDropStudio_Backend",
                 "/XML", str(xml_path), "/F"],
                capture_output=True, timeout=30
            )
            cb(97, "Otomatik başlatma ayarlandı ✓")
            return True
        except Exception as e:
            cb(95, f"Otomatik başlatma uyarısı: {e}")
            return False

    def setup_macos(self, cb: ProgressCallback = _default_cb) -> bool:
        """macOS LaunchAgent oluşturur."""
        cb(94, "Otomatik başlatma ayarlanıyor (macOS LaunchAgent)...")
        try:
            plist_dir  = Path.home() / "Library" / "LaunchAgents"
            plist_dir.mkdir(parents=True, exist_ok=True)
            plist_path = plist_dir / "com.BeatDropStudio.backend.plist"

            plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>         <string>com.BeatDropStudio.backend</string>
    <key>ProgramArguments</key>
    <array>
        <string>{self.python_exe}</string>
        <string>-m</string><string>uvicorn</string>
        <string>main:app</string>
        <string>--host</string><string>127.0.0.1</string>
        <string>--port</string><string>8765</string>
    </array>
    <key>WorkingDirectory</key><string>{BACKEND_DIR}</string>
    <key>RunAtLoad</key>     <true/>
    <key>KeepAlive</key>     <true/>
    <key>StandardErrorPath</key>
    <string>{PRODUCT_ROOT}/backend.log</string>
</dict>
</plist>"""
            plist_path.write_text(plist)
            subprocess.run(["launchctl", "load", str(plist_path)],
                           capture_output=True, timeout=15)
            cb(97, "LaunchAgent yüklendi ✓")
            return True
        except Exception as e:
            cb(95, f"LaunchAgent uyarısı: {e}")
            return False


# ===========================================================================
# 6. Kurulum Durumu Kaydetme / Okuma
# ===========================================================================

def save_install_state(state: dict):
    """Kurulum durumunu JSON dosyasına kaydeder."""
    state_file = PRODUCT_ROOT / "installer" / "install_state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_install_state() -> Optional[dict]:
    """Daha önce kaydedilmiş kurulum durumunu okur."""
    state_file = PRODUCT_ROOT / "installer" / "install_state.json"
    if state_file.exists():
        try:
            with open(state_file, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None


# ===========================================================================
# 7. Tam Kurulum Akışı (GUI'den çağrılır)
# ===========================================================================

def run_installation(
    install_premiere: bool = True,
    install_davinci:  bool = True,
    install_ai:       bool = False,
    detected_programs: dict = None,
    cb: ProgressCallback = _default_cb,
) -> dict:
    """
    Tam kurulum akışını yürütür.

    Args:
        install_premiere:  Premiere Pro eklentisi kurulsun mu
        install_davinci:   DaVinci Resolve script'i kurulsun mu
        install_ai:        AI bağımlılıkları yüklensin mi (büyük indirme)
        detected_programs: detect_all() sonucu
        cb:                Progres callback fonksiyonu

    Returns:
        {"success": bool, "errors": [str], "warnings": [str]}
    """
    errors   = []
    warnings = []
    state    = {"installed_at": time.strftime("%Y-%m-%d %H:%M:%S")}

    # ── ADIM 1: Python kontrolü — yoksa otomatik kur ────────────────────
    cb(1, "Python kontrol ediliyor...")
    system_python = find_system_python()

    if system_python:
        cb(2, f"Python bulundu: {system_python} ✓")
    else:
        # Python yok — kurulmaya çalış
        cb(2, "Python bulunamadı — otomatik kuruluyor...")
        if IS_WINDOWS:
            py_ok = install_python_windows(cb)
        else:
            py_ok = False  # macOS'ta homebrew veya pyenv önerilir
            warnings.append(
                "Python kurulu değil. Lütfen python.org adresinden Python 3.12'yi kurun."
            )

        if not py_ok:
            return {
                "success": False,
                "errors": [
                    "Python kurulamadı. Lütfen https://python.org/downloads adresinden "
                    "Python 3.12'yi manuel olarak kurun ve kurulumu yeniden başlatın."
                ],
                "warnings": warnings,
            }

        # Tekrar ara — kurulum PATH'e ekledi mi?
        import importlib
        system_python = find_system_python()
        if not system_python:
            # PATH henüz güncellenmedi — bilinen konuma bak
            fallback = Path(
                r"C:\Users") / __import__("os").getenv("USERNAME", "") / \
                "AppData/Local/Programs/Python/Python312/python.exe"
            if fallback.exists():
                system_python = str(fallback)
            else:
                warnings.append(
                    "Python kuruldu ancak PATH'e eklenemedi. "
                    "Bilgisayarı yeniden başlatmanız gerekebilir."
                )
                system_python = sys.executable  # son çare: EXE'nin Python'u

    state["python_path"] = str(system_python)

    # ── ADIM 2: Sanal ortam — AppData'ya kur (kalici yer) ──────────────
    import os
    appdata = os.getenv("APPDATA") or os.path.expanduser("~")
    venv_dir  = Path(appdata) / "BeatDrop Studio" / "venv"
    cb(18, f"Kurulum hedefi: {venv_dir.parent}")

    dep       = DependencyInstaller(venv_dir, python_exe=system_python)
    autostart = AutoStartManager(venv_dir)
    deployer  = FileDeployer()

    if not dep.create_venv(cb):
        return {"success": False,
                "errors": [f"Sanal ortam olusturulamadi ({venv_dir})"],
                "warnings": warnings}

    # ---- Temel bagimlilıklar ----
    if not dep.install_core(cb):
        return {"success": False,
                "errors": ["Temel kutuphaneler kurulamadi — internet baglantinizi kontrol edin"],
                "warnings": warnings}

    # ---- AI bağımlılıklar (opsiyonel) ----
    if install_ai:
        if not dep.install_ai(cb):
            warnings.append("AI modülleri kurulamadı — temel özellikler çalışmaya devam eder")

    # ---- Premiere Pro ----
    if install_premiere and detected_programs:
        pm_info = detected_programs.get("premiere", {})
        if pm_info.get("found") and pm_info.get("cep_path"):
            if not deployer.deploy_premiere(pm_info["cep_path"], cb):
                errors.append("Premiere Pro paneli kopyalanamadı")
            else:
                state["premiere_installed"] = True
                state["premiere_cep_path"]  = pm_info["cep_path"]
        else:
            warnings.append("Premiere Pro tespit edilemedi, atlandı")

    # ---- DaVinci Resolve ----
    if install_davinci and detected_programs:
        dv_info = detected_programs.get("davinci", {})
        if dv_info.get("found") and dv_info.get("script_path"):
            if not deployer.deploy_davinci(dv_info["script_path"], cb):
                errors.append("DaVinci Resolve script kopyalanamadı")
            else:
                state["davinci_installed"] = True
                state["davinci_script_path"] = dv_info["script_path"]
        else:
            warnings.append("DaVinci Resolve tespit edilemedi, atlandı")

    # ---- SFX Ses Efektleri Kurulumu ----
    cb(94, "SFX ses efektleri hazırlanıyor (16 efekt)...")
    try:
        import urllib.request
        sfx_dir = INSTALL_ROOT / "assets" / "sfx"
        sfx_dir.mkdir(parents=True, exist_ok=True)
        sfx_urls = {
            "whoosh.wav":        "https://freesound.org/data/previews/519/519180_5123851-lq.mp3",
            "whoosh_down.wav":   "https://freesound.org/data/previews/264/264828_4486188-lq.mp3",
            "swipe.wav":         "https://freesound.org/data/previews/320/320655_5260872-lq.mp3",
            "swoosh.wav":        "https://freesound.org/data/previews/609/609561_12517458-lq.mp3",
            "sub_bass.wav":      "https://freesound.org/data/previews/396/396765_7073468-lq.mp3",
            "impact.wav":        "https://freesound.org/data/previews/523/523654_10462585-lq.mp3",
            "punch.wav":         "https://freesound.org/data/previews/640/640947_10859175-lq.mp3",
            "boom.wav":          "https://freesound.org/data/previews/333/333785_3263906-lq.mp3",
            "pop.wav":           "https://freesound.org/data/previews/523/523651_10462585-lq.mp3",
            "cartoon_boing.wav": "https://freesound.org/data/previews/341/341695_5260872-lq.mp3",
            "vine_boom.wav":     "https://freesound.org/data/previews/521/521975_2398403-lq.mp3",
            "bruh.wav":          "https://freesound.org/data/previews/494/494279_6142149-lq.mp3",
            "rizz.wav":          "https://freesound.org/data/previews/352/352647_3263906-lq.mp3",
            "ding.wav":          "https://freesound.org/data/previews/397/397354_7073468-lq.mp3",
            "chime.wav":         "https://freesound.org/data/previews/411/411749_5121236-lq.mp3",
            "sparkle.wav":       "https://freesound.org/data/previews/478/478687_847821-lq.mp3",
        }
        sfx_downloaded = 0
        for fname, url in sfx_urls.items():
            fpath = sfx_dir / fname
            if not fpath.exists():
                try:
                    urllib.request.urlretrieve(url, str(fpath))
                    sfx_downloaded += 1
                except Exception:
                    pass
        cb(96, f"SFX ses efektleri hazırlandı ({sfx_downloaded} yeni) ✓")
    except Exception as e:
        warnings.append(f"SFX efektleri indirilemedi: {e}")
        cb(96, "SFX klasörü hazır (efektler daha sonra indirilebilir)")

    # ---- Otomatik başlatma ----
    cb(97, "Sunucu otomatik başlatma ayarlanıyor...")
    if IS_WINDOWS:
        autostart.setup_windows(cb)
    elif IS_MAC:
        autostart.setup_macos(cb)

    cb(99, "Kurulum tamamlanıyor...")
    save_install_state(state)
    cb(100, "✓ Kurulum başarıyla tamamlandı!")

    return {"success": len(errors) == 0, "errors": errors, "warnings": warnings}
