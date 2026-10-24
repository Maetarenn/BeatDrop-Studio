"""
=============================================================================
models.py
BeatDrop Studio — Pydantic Veri Modelleri
=============================================================================
Tüm API istekleri ve yanıtları için tip güvenli Pydantic şemaları.
=============================================================================
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ===========================================================================
# Enum Tanımları
# ===========================================================================

class SFXType(str, Enum):
    """Uygulanabilecek ses efekti tipleri"""
    # Geçiş efektleri
    WHOOSH        = 'whoosh'
    WHOOSH_DOWN   = 'whoosh_down'
    SWIPE         = 'swipe'
    SWOOSH        = 'swoosh'
    # Vurgu/Impact
    SUB_BASS      = 'sub_bass'
    IMPACT        = 'impact'
    PUNCH         = 'punch'
    BOOM          = 'boom'
    # Komik
    POP           = 'pop'
    CARTOON_BOING = 'cartoon_boing'
    VINE_BOOM     = 'vine_boom'
    BRUH          = 'bruh'
    RIZZ          = 'rizz'
    # Notifikasyon
    DING          = 'ding'
    CHIME         = 'chime'
    SPARKLE       = 'sparkle'
    NONE          = 'none'


class EventType(str, Enum):
    """Tespit edilen ses olayının tipi"""
    PEAK             = "peak"             # Ani ses yükselmesi / vurgu
    SCENE_TRANSITION = "scene_transition" # Sahne geçişi (sessizlik sonrası güçlü giriş)
    PAUSE            = "pause"            # Sessizlik / duraklama başlangıcı


# ===========================================================================
# İstek (Request) Şemaları
# ===========================================================================

class AnalyzeRequest(BaseModel):
    """
    /analyze endpoint'ine gönderilen istek gövdesi.
    Dosya yolu yerine upload kullanıldığında bu model opsiyoneldir.
    """
    file_path: str = Field(
        ...,
        description="Sunucu tarafından erişilebilir ses dosyasının tam yolu",
        example="/home/user/project/audio/voiceover.wav",
    )
    timeline_offset: float = Field(
        default=0.0,
        ge=0.0,
        description="Klibin timeline'daki başlangıç zamanı (saniye). "
                    "Premiere/DaVinci offset değeri için kullanılır.",
    )
    silence_db_threshold: float = Field(
        default=-40.0,
        le=0.0,
        description="Bu dB değerinin altındaki bölgeler sessizlik sayılır.",
    )
    peak_min_distance: float = Field(
        default=0.5,
        gt=0.0,
        description="İki vurgu noktası arasındaki minimum süre (saniye).",
    )
    zoom_in_scale: float = Field(
        default=107.0,
        ge=100.0,
        le=120.0,
        description="Punch-in zoom yüzdesi (örn. 107 → %107 scale).",
    )


# ===========================================================================
# Yanıt (Response) Şemaları
# ===========================================================================

class AudioEvent(BaseModel):
    """Tek bir ses olayını temsil eder."""
    time_seconds: float = Field(..., description="Olayın zamanı (saniye, float)")
    timecode:     str   = Field(..., description="SMPTE zaman kodu (HH:MM:SS:FF)")
    event_type:   EventType
    sfx_type:     SFXType
    rms_value:    float = Field(..., description="O andaki RMS enerji değeri")
    confidence:   float = Field(
        ..., ge=0.0, le=1.0,
        description="Tespit güven skoru (0-1 arası, 1 en yüksek güven)"
    )


class ZoomKeyframe(BaseModel):
    """Tek bir dinamik zoom keyframe'ini temsil eder."""
    time_seconds: float = Field(..., description="Keyframe zamanı (saniye)")
    timecode:     str   = Field(..., description="SMPTE zaman kodu")
    scale:        float = Field(..., description="Scale değeri (100=normal, 107=punch-in)")
    type:         str   = Field(..., description="'zoom_in' veya 'zoom_out'")


class AnalysisResult(BaseModel):
    """
    Ses analizinin tam çıktısı.
    Bu JSON doğrudan Premiere Pro ExtendScript ve DaVinci Python script'i tarafından tüketilir.
    """
    total_duration:  float            = Field(..., description="Ses dosyasının toplam süresi (saniye)")
    sample_rate:     int              = Field(..., description="Örnekleme hızı (Hz)")
    rms_mean:        float            = Field(..., description="Ortalama RMS enerji değeri")
    rms_std:         float            = Field(..., description="RMS standart sapması")
    events:          list[AudioEvent] = Field(default_factory=list, description="Tüm ses olayları listesi")
    zoom_keyframes:  list[ZoomKeyframe] = Field(default_factory=list, description="Dinamik zoom keyframe'leri")


class HealthResponse(BaseModel):
    """Sunucu sağlık kontrolü yanıtı"""
    status:  str = "ok"
    version: str = "1.0.0"
    message: str = "BeatDrop Studio Engine çalışıyor"


class ErrorResponse(BaseModel):
    """Hata yanıtı şablonu"""
    error:   str
    detail:  Optional[str] = None
    code:    int
