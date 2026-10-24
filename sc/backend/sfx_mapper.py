"""
sfx_mapper.py
BeatDrop Studio - SFX Dosya Yoneticisi
"""
import os
import logging
from pathlib import Path
from typing import Optional
from models import SFXType

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).parent.parent
_SFX_DIR = _BASE_DIR / "assets" / "sfx"

_SFX_FILE_MAP: dict = {
    SFXType.WHOOSH:        "whoosh.wav",
    SFXType.WHOOSH_DOWN:   "whoosh_down.wav",
    SFXType.SWIPE:         "swipe.wav",
    SFXType.SWOOSH:        "swoosh.wav",
    SFXType.SUB_BASS:      "sub_bass.wav",
    SFXType.IMPACT:        "impact.wav",
    SFXType.PUNCH:         "punch.wav",
    SFXType.BOOM:          "boom.wav",
    SFXType.POP:           "pop.wav",
    SFXType.CARTOON_BOING: "cartoon_boing.wav",
    SFXType.VINE_BOOM:     "vine_boom.wav",
    SFXType.BRUH:          "bruh.wav",
    SFXType.RIZZ:          "rizz.wav",
    SFXType.DING:          "ding.wav",
    SFXType.CHIME:         "chime.wav",
    SFXType.SPARKLE:       "sparkle.wav",
    SFXType.NONE:          "",
}

# Freesound.org preview URL'leri (ucretsiz, kucuk boyut ~30-100KB)
_SFX_DOWNLOAD_URLS: dict = {
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


class SFXMapper:
    def __init__(self, sfx_dir: Optional[Path] = None):
        self.sfx_dir = sfx_dir or _SFX_DIR

    def get_path(self, sfx_type: SFXType) -> str:
        if sfx_type == SFXType.NONE:
            return ""
        file_name = _SFX_FILE_MAP.get(sfx_type, "")
        if not file_name:
            return ""
        full_path = self.sfx_dir / file_name
        if not full_path.exists():
            logger.warning(f"SFX bulunamadi: {full_path}")
            return ""
        return str(full_path.resolve())

    def validate_all(self) -> dict:
        result = {}
        for sfx_type, file_name in _SFX_FILE_MAP.items():
            if sfx_type == SFXType.NONE:
                continue
            path = self.sfx_dir / file_name
            result[sfx_type.value] = path.exists()
        return result

    def get_missing(self) -> list:
        return [k for k, v in self.validate_all().items() if not v]


_sfx_mapper = SFXMapper()


def get_sfx_path(sfx_type: SFXType) -> str:
    return _sfx_mapper.get_path(sfx_type)


def validate_sfx_files() -> dict:
    return _sfx_mapper.validate_all()


def get_sfx_download_urls() -> dict:
    return _SFX_DOWNLOAD_URLS


def synthesize_sfx(filename: str, output_path: Path):
    """
    Eğer uzaktan indirme başarısız olursa veya çevrimdışıysak,
    NumPy ve SciPy kullanarak yüksek kaliteli minimalist ses efekti üretir.
    """
    import numpy as np
    import scipy.io.wavfile as wavfile

    sr = 44100
    t = np.linspace(0, 1.0, sr, endpoint=False)
    data = np.zeros_like(t)

    fname = filename.lower()
    if "whoosh" in fname or "swipe" in fname or "swoosh" in fname:
        # Bant geçiren gürültü + genlik zarfı
        noise = np.random.uniform(-1, 1, sr)
        envelope = np.exp(-((t - 0.4) ** 2) / 0.04)
        data = noise * envelope * 0.7
    elif "sub_bass" in fname or "boom" in fname:
        # Düşük frekans sinüs dalgası (60Hz -> 30Hz düşen)
        freq = np.linspace(65, 30, sr)
        envelope = np.exp(-t * 4.0)
        data = np.sin(2 * np.pi * freq * t) * envelope * 0.9
    elif "impact" in fname or "punch" in fname:
        # Sert vuruş: Hızlı transiyent + bas sönümü
        transient = np.random.uniform(-1, 1, sr) * np.exp(-t * 25.0)
        body = np.sin(2 * np.pi * 90 * t) * np.exp(-t * 8.0)
        data = (transient * 0.6 + body * 0.8)
    elif "pop" in fname:
        # Kısa minik balon patlaması (1200Hz -> 200Hz)
        t_pop = np.linspace(0, 0.12, int(sr * 0.12), endpoint=False)
        f_pop = np.linspace(1200, 200, len(t_pop))
        d_pop = np.sin(2 * np.pi * f_pop * t_pop) * np.exp(-t_pop * 35.0)
        data = np.pad(d_pop, (0, sr - len(d_pop)))
    elif "cartoon_boing" in fname or "rizz" in fname:
        # Eğlenceli FM modülasyonlu yaylanma (Boing!)
        carrier = 350 + 150 * np.sin(2 * np.pi * 15 * t)
        envelope = np.exp(-t * 3.0)
        data = np.sin(2 * np.pi * carrier * t) * envelope * 0.8
    elif "vine_boom" in fname or "bruh" in fname:
        # Derin distorsiyonlu bas patlaması
        f_boom = np.linspace(80, 25, sr)
        env = np.exp(-t * 3.5)
        raw = np.sin(2 * np.pi * f_boom * t) * 2.0
        data = np.tanh(raw) * env * 0.95  # Soft saturation
    elif "ding" in fname or "chime" in fname or "sparkle" in fname:
        # Kristal netliğinde zil (1200Hz + 2400Hz harmonikler)
        env = np.exp(-t * 3.0)
        data = (0.7 * np.sin(2 * np.pi * 1200 * t) + 0.3 * np.sin(2 * np.pi * 2400 * t)) * env
    else:
        # Varsayılan temiz sinüs vurgusu
        data = np.sin(2 * np.pi * 440 * t) * np.exp(-t * 5.0)

    # Normalize ve 16-bit PCM WAV yaz
    data = np.clip(data, -0.98, 0.98)
    pcm = (data * 32767).astype(np.int16)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(output_path), sr, pcm)


async def download_missing_sfx(cb=None) -> dict:
    """
    Eksik SFX dosyalarını uzaktan indirir.
    Eğer URL erişilemezse otomatik olarak DSP ile profesyonel WAV üretir!
    Böylece tüm 16 efekt her koşulda hazır olur.
    """
    try:
        import httpx
    except ImportError:
        httpx = None

    urls = get_sfx_download_urls()
    results = {}
    _SFX_DIR.mkdir(parents=True, exist_ok=True)

    for filename, url in urls.items():
        path = _SFX_DIR / filename
        if path.exists():
            results[filename] = 'exists'
            continue

        downloaded = False
        try:
            if httpx:
                async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
                    r = await client.get(url, headers={"User-Agent": "BeatDropStudio/1.0"})
                    if r.status_code == 200:
                        path.write_bytes(r.content)
                        results[filename] = 'downloaded'
                        downloaded = True
        except Exception:
            pass

        # Eğer indirme başarısız olduysa veya 404 aldıysa -> DSP Sentezle!
        if not downloaded:
            try:
                synthesize_sfx(filename, path)
                results[filename] = 'synthesized_ok'
            except Exception as se:
                results[filename] = f'error: {str(se)[:50]}'

        if cb:
            cb(filename, results[filename])

    return results
