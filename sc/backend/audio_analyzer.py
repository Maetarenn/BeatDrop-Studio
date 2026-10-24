"""
=============================================================================
audio_analyzer.py
BeatDrop Studio — Ses Analiz Motoru
=============================================================================
Bu modül ses dosyalarını analiz ederek:
  - Ses piklerini (peak) ve vurgulu anları tespit eder
  - Sessizlik bölgelerini (duraksamaları) bulur
  - Her olaya uygun SFX tipini belirler
  - Dinamik zoom için zaman kodlarını hesaplar

Kullanılan kütüphaneler: librosa, numpy, scipy
=============================================================================
"""

import random
import numpy as np
import librosa
import logging
from typing import Optional
from models import (
    AudioEvent,
    EventType,
    ZoomKeyframe,
    AnalysisResult,
    SFXType,
)

# ---------------------------------------------------------------------------
# Logger kurulumu
# ---------------------------------------------------------------------------
logger = logging.getLogger(__name__)


# ===========================================================================
# Yardımcı Fonksiyonlar
# ===========================================================================

def samples_to_timecode(sample_index: int, sample_rate: int) -> str:
    """
    Örnek (sample) indeksini HH:MM:SS:FF formatındaki SMPTE zaman koduna dönüştürür.
    Varsayılan kare hızı: 30 fps
    """
    fps = 30
    total_seconds = sample_index / sample_rate
    hours = int(total_seconds // 3600)
    minutes = int((total_seconds % 3600) // 60)
    seconds = int(total_seconds % 60)
    frames = int((total_seconds % 1) * fps)
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frames:02}"


def seconds_to_timecode(seconds_float: float) -> str:
    """
    Float saniye değerini SMPTE HH:MM:SS:FF formatına çevirir.
    """
    fps = 30
    h = int(seconds_float // 3600)
    m = int((seconds_float % 3600) // 60)
    s = int(seconds_float % 60)
    f = int((seconds_float % 1) * fps)
    return f"{h:02}:{m:02}:{s:02}:{f:02}"


def assign_sfx_type(
    rms_value: float,
    rms_mean: float,
    rms_std: float,
    is_silence: bool,
    event_type: str = "",
) -> SFXType:
    """
    Tespit edilen olayın RMS değerine, sessizlik durumuna ve event tipine göre
    hangi ses efektinin uygulanacağını belirler.

    Kurallar:
      - 'laughter' veya 'funny' event'lerde: komik havuzundan random
      - Sessizlik sonu / scene transition → geçiş havuzundan random
      - Çok yüksek enerji (normalised >0.75) → impact havuzundan random
      - Orta enerji → geçiş havuzundan random
      - Düşük enerji → notifikasyon havuzundan random
    """
    # Havuzlar
    funny_pool      = [SFXType.VINE_BOOM, SFXType.BRUH, SFXType.CARTOON_BOING, SFXType.RIZZ, SFXType.POP]
    impact_pool     = [SFXType.BOOM, SFXType.IMPACT, SFXType.PUNCH, SFXType.SUB_BASS]
    transition_pool = [SFXType.WHOOSH, SFXType.SWIPE, SFXType.SWOOSH, SFXType.WHOOSH_DOWN]
    notify_pool     = [SFXType.DING, SFXType.CHIME, SFXType.SPARKLE]

    # Komik / eğlenceli event
    event_lower = (event_type or "").lower()
    if any(kw in event_lower for kw in ("laughter", "funny", "laugh", "comedy", "joke")):
        return random.choice(funny_pool)

    # Sessizlik sonrası sahne geçişi
    if is_silence:
        return random.choice(transition_pool)

    # Enerji bazlı sınıflandırma
    # Normalised energy: (rms - mean) / (std + eps) → 0.75 threshold for high energy
    eps = 1e-8
    normalised = (rms_value - rms_mean) / (rms_std + eps)

    if normalised >= 0.75:
        return random.choice(impact_pool)
    elif normalised >= 0.0:
        return random.choice(transition_pool)
    else:
        return random.choice(notify_pool)


# ===========================================================================
# Ana Analiz Sınıfı
# ===========================================================================

class AudioAnalyzer:
    """
    Ses dosyasını yükleyip çok katmanlı analiz yapan ana sınıf.

    Parametreler:
      hop_length      : Pencereler arası adım büyüklüğü (örnek sayısı)
      frame_length    : FFT pencere boyutu
      silence_db      : Bu dB'nin altındaki bölgeler sessizlik sayılır
      min_silence_dur : Geçerli bir duraklama için minimum süre (saniye)
      peak_distance   : İki pik arasındaki minimum mesafe (saniye)
    """

    def __init__(
        self,
        hop_length: int = 512,
        frame_length: int = 2048,
        silence_db: float = -40.0,
        min_silence_dur: float = 0.3,
        peak_distance: float = 0.5,
    ):
        self.hop_length = hop_length
        self.frame_length = frame_length
        self.silence_db = silence_db
        self.min_silence_dur = min_silence_dur
        self.peak_distance = peak_distance

    # -----------------------------------------------------------------------
    # Dosya Yükleme
    # -----------------------------------------------------------------------
    def load_audio(self, file_path: str) -> tuple[np.ndarray, int]:
        """
        Ses dosyasını mono olarak yükler.
        Desteklenen formatlar: WAV, MP3, FLAC, OGG
        """
        try:
            y, sr = librosa.load(file_path, mono=True, sr=None)
            logger.info(f"Ses yüklendi: {file_path} | SR={sr} | Süre={len(y)/sr:.2f}s")
            return y, sr
        except Exception as e:
            logger.error(f"Ses dosyası yüklenemedi: {e}")
            raise RuntimeError(f"Ses yükleme hatası: {e}") from e

    # -----------------------------------------------------------------------
    # RMS Enerji Analizi
    # -----------------------------------------------------------------------
    def compute_rms(self, y: np.ndarray) -> np.ndarray:
        """
        Frame bazında RMS (Root Mean Square) enerji değerlerini hesaplar.
        Bu değer, her zaman dilimindeki ses yoğunluğunu temsil eder.
        """
        rms = librosa.feature.rms(
            y=y,
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )[0]  # shape: (n_frames,)
        logger.debug(f"RMS hesaplandı: {len(rms)} frame")
        return rms

    # -----------------------------------------------------------------------
    # Onset (Ani Başlangıç) Tespiti
    # -----------------------------------------------------------------------
    def detect_onsets(self, y: np.ndarray, sr: int) -> np.ndarray:
        """
        librosa.onset.onset_detect kullanarak seste ani enerji
        yükselişlerini (transient/vurgu başlangıçları) tespit eder.
        Döndürülen değer: saniye cinsinden onset zamanları dizisi.
        """
        onset_frames = librosa.onset.onset_detect(
            y=y,
            sr=sr,
            hop_length=self.hop_length,
            backtrack=True,        # Gerçek başlangıca geri sar
            normalize=True,
        )
        onset_times = librosa.frames_to_time(
            onset_frames, sr=sr, hop_length=self.hop_length
        )
        # Çok yakın onset'leri filtrele (min mesafe: peak_distance saniye)
        filtered = self._filter_min_distance(onset_times, self.peak_distance)
        logger.info(f"Onset tespiti: {len(filtered)} adet vurgu noktası bulundu")
        return filtered

    # -----------------------------------------------------------------------
    # Sessizlik Tespiti
    # -----------------------------------------------------------------------
    def detect_silences(
        self, y: np.ndarray, sr: int
    ) -> list[dict]:
        """
        Belirtilen dB eşiğinin altındaki sessizlik bölgelerini döndürür.
        Her bölge: {"start": float, "end": float} (saniye cinsinden)
        """
        # dB cinsinden enerji matrisi
        intervals = librosa.effects.split(
            y,
            top_db=abs(self.silence_db),
            frame_length=self.frame_length,
            hop_length=self.hop_length,
        )
        # split() ses olan bölgeleri döndürür; aralarındaki boşluklar sessizliktir
        silences = []
        total_samples = len(y)

        # İlk ses öncesi sessizlik
        if len(intervals) > 0 and intervals[0][0] > 0:
            dur = intervals[0][0] / sr
            if dur >= self.min_silence_dur:
                silences.append({"start": 0.0, "end": intervals[0][0] / sr})

        # Ses blokları arasındaki sessizlikler
        for i in range(len(intervals) - 1):
            gap_start = intervals[i][1] / sr
            gap_end = intervals[i + 1][0] / sr
            if (gap_end - gap_start) >= self.min_silence_dur:
                silences.append({"start": gap_start, "end": gap_end})

        # Son ses sonrası sessizlik
        if len(intervals) > 0 and intervals[-1][1] < total_samples:
            gap_start = intervals[-1][1] / sr
            gap_end = total_samples / sr
            if (gap_end - gap_start) >= self.min_silence_dur:
                silences.append({"start": gap_start, "end": gap_end})

        logger.info(f"Sessizlik tespiti: {len(silences)} duraklama bulundu")
        return silences

    # -----------------------------------------------------------------------
    # Zoom Keyframe Hesaplama
    # -----------------------------------------------------------------------
    def compute_zoom_keyframes(
        self,
        onset_times: np.ndarray,
        rms: np.ndarray,
        sr: int,
        rms_mean: float,
        rms_std: float,
        zoom_in_scale: float = 107.0,   # %107 punch-in
        zoom_out_scale: float = 100.0,  # %100 normal
        hold_duration: float = 0.4,     # Zoom-in ne kadar süre tutulacak (saniye)
    ) -> list[ZoomKeyframe]:
        """
        Her vurgulu onset için punch-in / punch-out keyframe çifti üretir.

        Kurallar:
          - RMS değeri (mean + 0.8*std) üzerindeyse zoom uygula
          - Zoom-in keyframe → onset zamanı
          - Zoom-out keyframe → onset + hold_duration
        """
        keyframes: list[ZoomKeyframe] = []

        for onset_sec in onset_times:
            # O anın frame indeksini bul
            frame_idx = int(
                librosa.time_to_frames(onset_sec, sr=sr, hop_length=self.hop_length)
            )
            frame_idx = min(frame_idx, len(rms) - 1)
            local_rms = float(rms[frame_idx])

            # Zoom eşiği: ortalamanın üstündeki güçlü vurgular
            if local_rms >= (rms_mean + 0.8 * rms_std):
                # Punch-IN
                keyframes.append(
                    ZoomKeyframe(
                        time_seconds=round(onset_sec, 3),
                        timecode=seconds_to_timecode(onset_sec),
                        scale=zoom_in_scale,
                        type="zoom_in",
                    )
                )
                # Punch-OUT
                zoom_out_time = onset_sec + hold_duration
                keyframes.append(
                    ZoomKeyframe(
                        time_seconds=round(zoom_out_time, 3),
                        timecode=seconds_to_timecode(zoom_out_time),
                        scale=zoom_out_scale,
                        type="zoom_out",
                    )
                )

        logger.info(f"Zoom keyframe: {len(keyframes)} adet üretildi")
        return keyframes

    # -----------------------------------------------------------------------
    # Tüm Analizi Birleştir
    # -----------------------------------------------------------------------
    def analyze(self, file_path: str, offset: float = 0.0) -> AnalysisResult:
        """
        Ses dosyasını uçtan uca analiz eder ve AnalysisResult döndürür.

        Parametreler:
          file_path : Analiz edilecek ses dosyasının tam yolu
          offset    : Timeline üzerindeki başlangıç süresi (saniye).
                      Premiere/DaVinci'de klibin timeline offset'i varsa buraya girin.
        """
        # 1. Ses yükle
        y, sr = self.load_audio(file_path)
        total_duration = float(len(y) / sr)

        # 2. RMS hesapla
        rms = self.compute_rms(y)
        rms_mean = float(np.mean(rms))
        rms_std = float(np.std(rms))

        # 3. Onset tespiti
        onset_times = self.detect_onsets(y, sr)

        # 4. Sessizlik tespiti
        silences = self.detect_silences(y, sr)
        silence_ends = {round(s["end"], 2) for s in silences}  # Hızlı arama için set

        # 5. Olayları oluştur
        events: list[AudioEvent] = []

        for onset_sec in onset_times:
            frame_idx = int(
                librosa.time_to_frames(onset_sec, sr=sr, hop_length=self.hop_length)
            )
            frame_idx = min(frame_idx, len(rms) - 1)
            local_rms = float(rms[frame_idx])

            # Sessizlik bitmek üzere mi? (silence_end'e 0.15s yakınsa)
            is_after_silence = any(
                abs(onset_sec - se) <= 0.15 for se in silence_ends
            )

            sfx = assign_sfx_type(local_rms, rms_mean, rms_std, is_after_silence)

            # Timeline offset'i ekle
            timeline_sec = round(onset_sec + offset, 3)

            events.append(
                AudioEvent(
                    time_seconds=timeline_sec,
                    timecode=seconds_to_timecode(timeline_sec),
                    event_type=EventType.PEAK if not is_after_silence else EventType.SCENE_TRANSITION,
                    sfx_type=sfx,
                    rms_value=round(local_rms, 6),
                    confidence=round(
                        min((local_rms - rms_mean) / (rms_std + 1e-8), 1.0), 3
                    ),
                )
            )

        # 6. Sessizlik olaylarını ekle (sessizliğin başlangıcı → PAUSE eventi)
        for sil in silences:
            timeline_sec = round(sil["start"] + offset, 3)
            events.append(
                AudioEvent(
                    time_seconds=timeline_sec,
                    timecode=seconds_to_timecode(timeline_sec),
                    event_type=EventType.PAUSE,
                    sfx_type=SFXType.NONE,
                    rms_value=0.0,
                    confidence=1.0,
                )
            )

        # Zamana göre sırala
        events.sort(key=lambda e: e.time_seconds)

        # 7. Zoom keyframe'leri hesapla
        zoom_keyframes = self.compute_zoom_keyframes(
            onset_times, rms, sr, rms_mean, rms_std
        )
        # Offset ekle
        for kf in zoom_keyframes:
            kf.time_seconds = round(kf.time_seconds + offset, 3)
            kf.timecode = seconds_to_timecode(kf.time_seconds)

        logger.info(
            f"Analiz tamamlandı: {len(events)} event, {len(zoom_keyframes)} zoom keyframe"
        )

        return AnalysisResult(
            total_duration=round(total_duration, 3),
            sample_rate=sr,
            rms_mean=round(rms_mean, 6),
            rms_std=round(rms_std, 6),
            events=events,
            zoom_keyframes=zoom_keyframes,
        )

    # -----------------------------------------------------------------------
    # Yardımcı: Minimum Mesafe Filtresi
    # -----------------------------------------------------------------------
    @staticmethod
    def _filter_min_distance(times: np.ndarray, min_dist: float) -> np.ndarray:
        """
        Birbirinden çok yakın zaman noktalarını filtreler.
        Her iki komşu nokta arasında en az `min_dist` saniye olmasını sağlar.
        """
        if len(times) == 0:
            return times
        filtered = [times[0]]
        for t in times[1:]:
            if t - filtered[-1] >= min_dist:
                filtered.append(t)
        return np.array(filtered)
