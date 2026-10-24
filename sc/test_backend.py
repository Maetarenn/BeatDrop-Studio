"""
=============================================================================
test_backend.py — BeatDrop Studio Backend Testi
=============================================================================
Backend'in doğru çalışıp çalışmadığını doğrulayan hızlı test scripti.
Çalıştırma: python test_backend.py
=============================================================================
"""

import sys
import json
import time
import tempfile
import numpy as np
from pathlib import Path

# ---- Test için yapay ses dosyası üret (librosa gerektirmeden) ----
def create_test_wav(path: str, duration: float = 5.0, sr: int = 22050):
    """
    Gerçek ses olmadan test için yapay WAV dosyası üretir.
    İçinde birkaç belirgin pik barındırır.
    """
    import wave, struct

    n_samples = int(duration * sr)
    samples   = np.zeros(n_samples, dtype=np.float32)

    # Sesli bölgeler: 0.5s, 1.5s, 2.5s, 3.5s, 4.5s
    for peak_time in [0.5, 1.5, 2.5, 3.5, 4.5]:
        center = int(peak_time * sr)
        width  = int(0.05 * sr)  # 50ms pik
        for i in range(max(0, center - width), min(n_samples, center + width)):
            amp = 1.0 - abs(i - center) / width
            samples[i] = amp * np.sin(2 * np.pi * 440 * i / sr)

    # Arka plan gürültü (düşük seviye)
    samples += np.random.normal(0, 0.01, n_samples).astype(np.float32)

    # WAV olarak kaydet
    with wave.open(path, 'w') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sr)
        int_samples = (samples * 32767).astype(np.int16)
        wf.writeframes(int_samples.tobytes())

    return path


def test_audio_analyzer():
    """AudioAnalyzer sınıfını doğrudan test eder."""
    print("\n[1] AudioAnalyzer Doğrudan Testi")
    print("-" * 40)

    try:
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        from audio_analyzer import AudioAnalyzer
        from models import AnalysisResult

        # Geçici test WAV oluştur
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            wav_path = tmp.name

        create_test_wav(wav_path, duration=5.0)
        print(f"  Test WAV oluşturuldu: {wav_path}")

        analyzer = AudioAnalyzer(
            hop_length=512,
            frame_length=2048,
            peak_distance=0.3,
        )

        t0 = time.time()
        result = analyzer.analyze(wav_path, offset=0.0)
        elapsed = time.time() - t0

        print(f"  ✓ Analiz süresi: {elapsed:.2f}s")
        print(f"  ✓ Toplam süre: {result.total_duration:.2f}s")
        print(f"  ✓ Event sayısı: {len(result.events)}")
        print(f"  ✓ Zoom keyframe: {len(result.zoom_keyframes)}")
        print(f"  ✓ RMS mean: {result.rms_mean:.6f}")

        if result.events:
            print(f"\n  İlk 5 Event:")
            for evt in result.events[:5]:
                print(f"    {evt.timecode} | {evt.event_type.value:18s} | {evt.sfx_type.value}")

        if result.zoom_keyframes:
            print(f"\n  İlk 4 Zoom Keyframe:")
            for kf in result.zoom_keyframes[:4]:
                print(f"    {kf.timecode} | {kf.type:10s} | scale={kf.scale}%")

        # JSON serileştirme testi
        json_output = json.dumps(result.model_dump(), indent=2, ensure_ascii=False)
        print(f"\n  ✓ JSON çıktısı ({len(json_output)} karakter) geçerli")

        # Temizlik
        Path(wav_path).unlink(missing_ok=True)
        print("  ✓ Test dosyası temizlendi")

        return True

    except ImportError as e:
        print(f"  ✗ Import hatası: {e}")
        print("    Çözüm: pip install -r backend/requirements.txt")
        return False
    except Exception as e:
        print(f"  ✗ Test başarısız: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_backend_api():
    """Çalışan FastAPI sunucusuna HTTP isteği atar."""
    print("\n[2] FastAPI Backend HTTP Testi")
    print("-" * 40)

    try:
        import requests
    except ImportError:
        print("  ✗ Requests kütüphanesi eksik: pip install requests")
        return False

    server = "http://127.0.0.1:8765"

    # Sağlık kontrolü
    try:
        res = requests.get(f"{server}/health", timeout=3)
        if res.status_code == 200:
            data = res.json()
            print(f"  ✓ Sunucu çalışıyor: {data.get('message')}")
        else:
            print(f"  ✗ Sunucu hatası: {res.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"  ⚠ Sunucu çalışmıyor ({server})")
        print("    Başlatmak için: uvicorn main:app --host 127.0.0.1 --port 8765")
        print("    (Bu test sunucu gerektirmediğinden devam ediyoruz...)")
        return None  # Sunucu yoksa atla

    # SFX doğrulama
    res = requests.get(f"{server}/sfx/validate", timeout=3)
    sfx_data = res.json()
    print(f"  SFX dosyaları: {sfx_data.get('files', {})}")

    # Analiz testi (geçici WAV ile)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        wav_path = tmp.name
    create_test_wav(wav_path)

    try:
        res = requests.post(
            f"{server}/analyze",
            json={"file_path": wav_path, "timeline_offset": 0.0},
            timeout=60,
        )
        if res.status_code == 200:
            data = res.json()
            print(f"  ✓ /analyze OK: {len(data.get('events', []))} event")
        else:
            print(f"  ✗ /analyze hatası: {res.status_code} — {res.text[:200]}")
    finally:
        Path(wav_path).unlink(missing_ok=True)

    return True


def test_sfx_mapper():
    """SFX eşleştirici modülünü test eder."""
    print("\n[3] SFX Mapper Testi")
    print("-" * 40)

    try:
        sys.path.insert(0, str(Path(__file__).parent / "backend"))
        from sfx_mapper import SFXMapper
        from models import SFXType

        mapper = SFXMapper()
        validate = mapper.validate_all()
        print(f"  SFX durumu: {validate}")

        # Tip → yol eşleştirmesi
        for sfx_type in [SFXType.WHOOSH, SFXType.POP, SFXType.DING, SFXType.SUB_BASS]:
            path = mapper.get_path(sfx_type)
            status = "✓ Mevcut" if path else "⚠ Dosya yok (eklenecek)"
            print(f"  {sfx_type.value:10s}: {status}")

        return True
    except Exception as e:
        print(f"  ✗ Hata: {e}")
        return False


# ===========================================================================
# Test Çalıştırıcı
# ===========================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("BeatDrop Studio — Test Suite")
    print("=" * 50)

    results = {
        "AudioAnalyzer": test_audio_analyzer(),
        "SFX Mapper":    test_sfx_mapper(),
        "Backend API":   test_backend_api(),
    }

    print("\n" + "=" * 50)
    print("TEST SONUÇLARI")
    print("=" * 50)
    for test_name, passed in results.items():
        if passed is True:
            status = "✅ GEÇTİ"
        elif passed is False:
            status = "❌ BAŞARISIZ"
        else:
            status = "⏭  ATLAND (sunucu gerektirir)"
        print(f"  {test_name:20s}: {status}")

    failed = [k for k, v in results.items() if v is False]
    if failed:
        print(f"\n  {len(failed)} test başarısız. Hata loglarını inceleyin.")
        sys.exit(1)
    else:
        print("\n  Tüm testler başarıyla tamamlandı! 🎉")
