"""
=============================================================================
main.py
BeatDrop Studio — FastAPI Ana Sunucu
=============================================================================
Yerel arka plan sunucusu. Hem Adobe Premiere Pro CEP paneli hem de
DaVinci Resolve Python script'i bu sunucuya HTTP/WebSocket üzerinden bağlanır.

Endpoints:
  GET  /health              → Sunucu sağlık kontrolü
  GET  /sfx/validate        → SFX dosyalarının varlık kontrolü
  POST /analyze             → Ses dosyası analizi (DSP, hızlı mod)
  POST /analyze/ai          → Tam AI pipeline (Whisper + YAMNet + Duygu)
  POST /analyze/upload      → Ses dosyası analizi (dosya yükleyerek)
  WS   /ws/analyze          → WebSocket üzerinden gerçek zamanlı analiz

Çalıştırma:
  uvicorn main:app --host 127.0.0.1 --port 8765 --reload
=============================================================================
"""

import os
import shutil
import logging
import tempfile
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import (
    FastAPI,
    HTTPException,
    UploadFile,
    File,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from models import (
    AnalyzeRequest,
    AnalysisResult,
    HealthResponse,
    ErrorResponse,
)
from audio_analyzer import AudioAnalyzer
from sfx_mapper import validate_sfx_files, get_sfx_path

# ---------------------------------------------------------------------------
# Logging Yapılandırması
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Geçici Dosya Klasörü (upload'lar için)
# ---------------------------------------------------------------------------
UPLOAD_DIR = Path(tempfile.gettempdir()) / "smart_ssd_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Desteklenen Ses Formatları
# ---------------------------------------------------------------------------
ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".aac", ".m4a"}


# ===========================================================================
# Lifespan: Başlangıç / Bitiş Olayları
# ===========================================================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Uygulama başlarken ve kapanırken çalışan kod bloğu."""
    # ---- Başlangıç ----
    logger.info("=" * 60)
    logger.info("BeatDrop Studio Engine başlatılıyor...")
    logger.info(f"Upload klasörü: {UPLOAD_DIR}")

    # SFX dosyalarını doğrula
    sfx_status = validate_sfx_files()
    missing = [k for k, v in sfx_status.items() if not v]
    if missing:
        logger.warning(
            f"Eksik SFX dosyaları tespit edildi: {missing}. "
            "assets/sfx/ klasörüne WAV dosyalarınızı ekleyin."
        )
    else:
        logger.info("Tüm SFX dosyaları mevcut ✓")

    logger.info("Sunucu hazır → http://127.0.0.1:8765")
    logger.info("=" * 60)

    yield  # Uygulama burada çalışır

    # ---- Kapanış ----
    logger.info("Sunucu kapatılıyor, geçici dosyalar temizleniyor...")
    shutil.rmtree(UPLOAD_DIR, ignore_errors=True)
    logger.info("Sunucu kapatıldı.")


# ===========================================================================
# FastAPI Uygulaması
# ===========================================================================
app = FastAPI(
    title="BeatDrop Studio Engine",
    description=(
        "Adobe Premiere Pro ve DaVinci Resolve için yerel AI ses analizi sunucusu. "
        "Ses dosyalarını analiz ederek vurgu noktalarını, SFX önerilerini ve "
        "dinamik zoom keyframe'lerini hesaplar."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS: CEP Panel (Premiere) ve DaVinci script'inin erişimine izin ver
# ---------------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # Geliştirme için; üretimde kısıtlayın
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Analyzer Singleton (uygulama boyunca tek örnek)
# ---------------------------------------------------------------------------
analyzer = AudioAnalyzer()


# ===========================================================================
# Yardımcı Fonksiyonlar
# ===========================================================================

def enrich_with_sfx_paths(result: AnalysisResult) -> dict:
    """
    AnalysisResult'ı dict'e çevirip her event'e SFX dosya yolunu ekler.
    Premiere Pro ve DaVinci script'leri bu bilgiyi kullanarak
    doğru ses dosyasını koyacak yeri bilir.
    """
    data = result.model_dump()

    for event in data["events"]:
        sfx_enum_value = event["sfx_type"]
        event["sfx_file_path"] = get_sfx_path(sfx_enum_value)

    return data


def validate_audio_extension(filename: str) -> None:
    """Dosya uzantısını doğrular, geçersizse HTTPException fırlatır."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Desteklenmeyen dosya formatı: '{ext}'. "
                f"Kabul edilenler: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}"
            ),
        )


# ===========================================================================
# Endpoint: Sağlık Kontrolü
# ===========================================================================
@app.get(
    "/health",
    response_model=HealthResponse,
    summary="Sunucu sağlık kontrolü",
    tags=["System"],
)
async def health_check():
    """Sunucunun çalışıp çalışmadığını kontrol eder."""
    return HealthResponse()


# ===========================================================================
# Endpoint: SFX Doğrulama
# ===========================================================================
@app.get(
    "/sfx/validate",
    summary="SFX dosyalarının varlık kontrolü",
    tags=["System"],
)
async def sfx_validate():
    """
    assets/sfx/ klasöründeki ses efekti dosyalarının
    mevcut olup olmadığını listeler.
    """
    status_map = validate_sfx_files()
    all_present = all(status_map.values())
    return {
        "all_present": all_present,
        "files": status_map,
        "sfx_directory": str(Path(__file__).parent.parent / "assets" / "sfx"),
    }


@app.post(
    "/sfx/download",
    summary="Eksik SFX dosyalarını otomatik indir",
    tags=["SFX"],
)
async def download_sfx_endpoint():
    """
    Eksik SFX dosyalarını freesound / remote kaynaklardan indirir.
    """
    from sfx_mapper import download_missing_sfx
    results = await download_missing_sfx()
    downloaded = sum(1 for v in results.values() if v == "downloaded")
    existed = sum(1 for v in results.values() if v == "exists")
    errors = sum(1 for v in results.values() if v not in ("downloaded", "exists"))
    return {
        "status": "ok",
        "downloaded_count": downloaded,
        "already_existed_count": existed,
        "error_count": errors,
        "results": results,
    }


# ===========================================================================
# Endpoint: Dosya Yolu ile Analiz
# ===========================================================================
@app.post(
    "/analyze",
    response_model=None,  # Zenginleştirilmiş dict döndürüyoruz
    summary="Ses dosyasını analiz et (sunucu yolu ile)",
    tags=["Analysis"],
)
async def analyze_by_path(request: AnalyzeRequest):
    """
    Sunucunun erişebildiği bir yoldaki ses dosyasını analiz eder.

    Kullanım senaryosu:
    - Premiere Pro veya DaVinci, aktif proje ses dosyasının tam yolunu gönderir.
    - Sunucu analizi yapar ve timeline'a uygulanacak JSON'u döndürür.
    """
    try:
        # Dosya varlığını kontrol et
        if not os.path.isfile(request.file_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Ses dosyası bulunamadı: {request.file_path}",
            )

        validate_audio_extension(request.file_path)

        # Analiz yap
        logger.info(f"Analiz başlıyor: {request.file_path}")
        result = analyzer.analyze(
            file_path=request.file_path,
            offset=request.timeline_offset,
        )

        # SFX yollarını ekle ve döndür
        enriched = enrich_with_sfx_paths(result)
        logger.info(
            f"Analiz tamamlandı: {len(result.events)} event, "
            f"{len(result.zoom_keyframes)} zoom keyframe"
        )
        return JSONResponse(content=enriched)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Analiz hatası: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Analiz sırasında beklenmeyen hata: {str(exc)}",
        )


# ===========================================================================
# Endpoint: Dosya Yükleyerek Analiz
# ===========================================================================
@app.post(
    "/analyze/upload",
    summary="Ses dosyasını yükleyerek analiz et",
    tags=["Analysis"],
)
async def analyze_upload(
    file: UploadFile = File(..., description="Analiz edilecek ses dosyası"),
    timeline_offset: float = 0.0,
    silence_db_threshold: float = -40.0,
    peak_min_distance: float = 0.5,
    zoom_in_scale: float = 107.0,
):
    """
    Kullanıcının yüklediği ses dosyasını analiz eder.
    Dosya geçici klasöre kaydedilir, analiz edilir, ardından silinir.

    Kullanım senaryosu:
    - CEP Panel'den "Ses Dosyası Seç" butonu ile doğrudan yükleme yapılır.
    """
    try:
        validate_audio_extension(file.filename or "unknown.tmp")

        # Geçici dosyaya kaydet
        suffix = Path(file.filename or "audio.wav").suffix
        tmp_path = UPLOAD_DIR / f"upload_{id(file)}{suffix}"

        try:
            with open(tmp_path, "wb") as f:
                content = await file.read()
                f.write(content)
            logger.info(f"Upload kaydedildi: {tmp_path} ({len(content)} byte)")

            # Analiz yap
            result = analyzer.analyze(
                file_path=str(tmp_path),
                offset=timeline_offset,
            )

            enriched = enrich_with_sfx_paths(result)
            return JSONResponse(content=enriched)

        finally:
            # Geçici dosyayı her durumda sil
            if tmp_path.exists():
                tmp_path.unlink()
                logger.debug(f"Geçici dosya silindi: {tmp_path}")

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"Upload analiz hatası: {exc}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Upload analizi sırasında hata: {str(exc)}",
        )


# ===========================================================================
# WebSocket: Gerçek Zamanlı Analiz
# ===========================================================================
@app.websocket("/ws/analyze")
async def websocket_analyze(websocket: WebSocket):
    """
    WebSocket endpoint'i — Adobe Premiere Pro CEP paneli bu kanalı kullanarak
    gerçek zamanlı durum güncellemeleri alabilir.

    Protokol:
      Client → Server: JSON { "file_path": "...", "timeline_offset": 0.0, ... }
      Server → Client: JSON { "status": "analyzing" | "complete" | "error", ... }
    """
    await websocket.accept()
    logger.info("WebSocket bağlantısı kuruldu")

    try:
        while True:
            # İstemciden mesaj bekle
            raw = await websocket.receive_json()
            logger.info(f"WS isteği alındı: {raw}")

            # İstek doğrulama
            file_path = raw.get("file_path")
            if not file_path:
                await websocket.send_json({
                    "status": "error",
                    "message": "'file_path' alanı zorunludur",
                })
                continue

            if not os.path.isfile(file_path):
                await websocket.send_json({
                    "status": "error",
                    "message": f"Dosya bulunamadı: {file_path}",
                })
                continue

            # Analiz başladığını bildir
            await websocket.send_json({
                "status": "analyzing",
                "message": "Ses analizi başlıyor...",
                "file": file_path,
            })

            try:
                result = analyzer.analyze(
                    file_path=file_path,
                    offset=raw.get("timeline_offset", 0.0),
                )
                enriched = enrich_with_sfx_paths(result)

                await websocket.send_json({
                    "status": "complete",
                    "message": "Analiz tamamlandı",
                    "data": enriched,
                })
                logger.info("WS analiz tamamlandı, sonuç gönderildi")

            except Exception as exc:
                logger.exception(f"WS analiz hatası: {exc}")
                await websocket.send_json({
                    "status": "error",
                    "message": f"Analiz hatası: {str(exc)}",
                })

    except WebSocketDisconnect:
        logger.info("WebSocket bağlantısı kesildi")
    except Exception as exc:
        logger.error(f"WebSocket beklenmeyen hata: {exc}")
        try:
            await websocket.send_json({
                "status": "error",
                "message": f"Sunucu hatası: {str(exc)}",
            })
        except Exception:
            pass


# ===========================================================================
# Global Hata Yakalayıcı
# ===========================================================================
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Yakalanmamış hata: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="InternalServerError",
            detail=str(exc),
            code=500,
        ).model_dump(),
    )


# ===========================================================================
# Endpoint: Tam AI Pipeline ile Analiz
# ===========================================================================

from pydantic import BaseModel as _BaseModel

class AIAnalyzeRequest(_BaseModel):
    """POST /analyze/ai isteği"""
    file_path:                  str
    timeline_offset:            float = 0.0
    use_whisper:                bool  = True
    use_yamnet:                 bool  = True
    use_emotion:                bool  = True
    also_run_dsp:               bool  = True
    whisper_model:              str   = "base"
    emotion_arousal_threshold:  float = 0.6
    zoom_in_scale:              float = 107.0


@app.post(
    "/analyze/ai",
    summary="Tam AI Pipeline ile Analiz (Whisper + YAMNet + Duygu)",
    tags=["Analysis"],
)
async def analyze_with_ai(request: AIAnalyzeRequest):
    """
    Gerçek AI katmanlarını çalıştırarak ses dosyasını analiz eder:

    - **Whisper**: Konuşmayı metne çevirir, vurgulu kelimeleri tespit eder
    - **YAMNet**: Kahkaha, alkış, patlama, rüzgar gibi ses olaylarını sınıflandırır
    - **Wav2Vec**: Konuşmacının duygu durumunu (heyecanlı/sakin/öfkeli) analiz eder
    - **DSP**: Eski istatistiksel analizi de hibrit olarak çalıştırır

    ⚠️ Bu endpoint ilk çağrıda AI modellerini indireceğinden yavaş olabilir.
    Sonraki çağrılarda modeller bellekte olduğu için çok daha hızlı çalışır.

    Gereksinimler:
      `pip install openai-whisper tensorflow tensorflow-hub transformers torch torchaudio`
    """
    try:
        if not os.path.isfile(request.file_path):
            raise HTTPException(
                status_code=404,
                detail=f"Ses dosyası bulunamadı: {request.file_path}",
            )

        validate_audio_extension(request.file_path)

        # AI Pipeline'ı lazy import et (bağımlılıklar opsiyonel)
        try:
            from ai_pipeline import AIPipeline
        except ImportError as ie:
            raise HTTPException(
                status_code=501,
                detail=(
                    f"AI Pipeline bağımlılıkları eksik: {ie}\n"
                    "Yüklemek için: pip install openai-whisper tensorflow "
                    "tensorflow-hub transformers torch torchaudio"
                ),
            )

        logger.info(f"AI Pipeline başlatılıyor: {request.file_path}")

        pipeline = AIPipeline(
            use_whisper  = request.use_whisper,
            use_yamnet   = request.use_yamnet,
            use_emotion  = request.use_emotion,
            also_run_dsp = request.also_run_dsp,
            whisper_model= request.whisper_model,
            emotion_arousal_threshold=request.emotion_arousal_threshold,
        )

        result = pipeline.analyze(
            file_path=request.file_path,
            timeline_offset=request.timeline_offset,
        )

        enriched = enrich_with_sfx_paths(result)

        logger.info(
            f"AI analiz tamamlandı: {len(result.events)} event, "
            f"{len(result.zoom_keyframes)} zoom KF"
        )
        return JSONResponse(content=enriched)

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception(f"AI analiz hatası: {exc}")
        raise HTTPException(
            status_code=500,
            detail=f"AI analizi sırasında hata: {str(exc)}",
        )


# ===========================================================================
# Doğrudan çalıştırma (python main.py)
# ===========================================================================
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8765,
        reload=True,
        log_level="info",
    )
