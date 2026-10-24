"""
=============================================================================
ai_pipeline.py
BeatDrop Studio — Gerçek AI Olay Algılama Motoru
=============================================================================
Üç katmanlı AI pipeline:

  Katman 1 — Whisper (OpenAI)
    Ses dosyasından konuşmayı metne çevirir, her kelimenin zaman damgasını
    çıkarır. Vurgulu/önemli kelimeleri (büyük harf, ünlem, noktalama)
    otomatik olarak tespit eder → POP / DING efekti planlar.

  Katman 2 — YAMNet / PANNs (TensorFlow / PyTorch)
    Google'ın AudioSet üzerinde eğitilmiş ses olay sınıflandırıcısı.
    Kahkaha, alkış, patlama, müzik, ağlama, bağırma gibi 521 sınıfı tanır.
    Her olaya özel SFX ve zoom kararı verir.

  Katman 3 — Wav2Vec 2.0 (Duygu Analizi)
    HuggingFace'den ses tabanlı duygu tanıma modeli.
    Konuşmacının heyecanlı / sakin / öfkeli / üzgün olduğu anları tespit
    eder, yüksek arousal dönemlerine dinamik zoom ekler.

Tüm katmanların sonuçları birleştirilir, çakışmalar öncelik kuralıyla
çözülür ve tek bir AnalysisResult nesnesi döndürülür.

Gereksinimler:
  pip install openai-whisper tensorflow tensorflow-hub
              transformers torch torchaudio
=============================================================================
"""

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

from models import (
    AudioEvent,
    EventType,
    SFXType,
    ZoomKeyframe,
    AnalysisResult,
)
from audio_analyzer import AudioAnalyzer, seconds_to_timecode

logger = logging.getLogger(__name__)


# ===========================================================================
# Öncelik Tablosu: Aynı zaman dilimine birden fazla AI karar verirse
# ===========================================================================

import random

# SFX önceliği (yüksek → düşük): patlama/impact > whoosh/geçiş > komik > notif > none
SFX_PRIORITY = {
    SFXType.BOOM:          5,
    SFXType.IMPACT:        5,
    SFXType.PUNCH:         5,
    SFXType.SUB_BASS:      4,
    SFXType.VINE_BOOM:     4,
    SFXType.WHOOSH:        3,
    SFXType.SWIPE:         3,
    SFXType.SWOOSH:        3,
    SFXType.WHOOSH_DOWN:   3,
    SFXType.BRUH:          2,
    SFXType.CARTOON_BOING: 2,
    SFXType.RIZZ:          2,
    SFXType.POP:           2,
    SFXType.DING:          1,
    SFXType.CHIME:         1,
    SFXType.SPARKLE:       1,
    SFXType.NONE:          0,
}

# YAMNet sınıf → SFX / Event tipi eşlemesi (Havuz bazlı dinamik ve zengin)
def get_yamnet_sfx(class_name: str) -> tuple[SFXType, EventType]:
    """AudioSet sınıfına göre dinamik, zengin ve çeşitli SFX atar."""
    c = class_name.lower()
    
    # Gülme / Komik anlar
    if any(k in c for k in ("laughter", "chuckle", "giggle", "snicker", "cackle")):
        funny_choice = random.choice([
            SFXType.VINE_BOOM,
            SFXType.BRUH,
            SFXType.CARTOON_BOING,
            SFXType.RIZZ,
            SFXType.POP,
        ])
        return (funny_choice, EventType.PEAK)

    # Patlama / Güçlü vuruşlar
    if any(k in c for k in ("explosion", "gunshot", "thunder", "boom", "blast", "artillery")):
        impact_choice = random.choice([SFXType.BOOM, SFXType.IMPACT, SFXType.SUB_BASS])
        return (impact_choice, EventType.SCENE_TRANSITION)

    # Darbe / Yumruk / Vuruş
    if any(k in c for k in ("punch", "slap", "hit", "knock", "tap", "slam", "drum")):
        hit_choice = random.choice([SFXType.PUNCH, SFXType.IMPACT, SFXType.SUB_BASS])
        return (hit_choice, EventType.PEAK)

    # Rüzgar / Hızlı geçiş
    if any(k in c for k in ("wind", "whoosh", "swoosh", "whip", "air")):
        whoosh_choice = random.choice([SFXType.WHOOSH, SFXType.SWIPE, SFXType.SWOOSH, SFXType.WHOOSH_DOWN])
        return (whoosh_choice, EventType.SCENE_TRANSITION)

    # Alkış / Tezahürat / Kalabalık coşkusu
    if any(k in c for k in ("applause", "cheering", "clapping")):
        social_choice = random.choice([SFXType.POP, SFXType.SPARKLE, SFXType.DING])
        return (social_choice, EventType.PEAK)

    # Bağırma / Çığlık
    if any(k in c for k in ("shout", "screaming", "yell")):
        shout_choice = random.choice([SFXType.VINE_BOOM, SFXType.BRUH, SFXType.BOOM])
        return (shout_choice, EventType.PEAK)

    # Zil / Bildirim / Küçük başarı
    if any(k in c for k in ("bell", "ding", "chime", "tick", "ring")):
        notif_choice = random.choice([SFXType.DING, SFXType.CHIME, SFXType.SPARKLE])
        return (notif_choice, EventType.PEAK)

    # Müzik geçişi
    if "music" in c:
        return (SFXType.WHOOSH, EventType.SCENE_TRANSITION)

    if "silence" in c:
        return (SFXType.NONE, EventType.PAUSE)

    return (SFXType.POP, EventType.PEAK)

# Geriye dönük uyumluluk dict'i (fallback için)
YAMNET_CLASS_MAP = {
    "Explosion":         (SFXType.BOOM,          EventType.SCENE_TRANSITION),
    "Gunshot, gunfire":  (SFXType.IMPACT,        EventType.SCENE_TRANSITION),
    "Thunder":           (SFXType.SUB_BASS,      EventType.SCENE_TRANSITION),
    "Bass drum":         (SFXType.SUB_BASS,      EventType.PEAK),
    "Boom":              (SFXType.BOOM,          EventType.SCENE_TRANSITION),
    "Wind":              (SFXType.WHOOSH,        EventType.SCENE_TRANSITION),
    "Whoosh, swoosh":    (SFXType.SWOOSH,        EventType.SCENE_TRANSITION),
    "Swoosh":            (SFXType.SWOOSH,        EventType.SCENE_TRANSITION),
    "Laughter":          (SFXType.VINE_BOOM,     EventType.PEAK),
    "Applause":          (SFXType.POP,           EventType.PEAK),
    "Cheering":          (SFXType.SPARKLE,       EventType.PEAK),
    "Clapping":          (SFXType.POP,           EventType.PEAK),
    "Shout":             (SFXType.BRUH,          EventType.PEAK),
    "Screaming":         (SFXType.VINE_BOOM,     EventType.PEAK),
    "Bell":              (SFXType.DING,          EventType.PEAK),
    "Ding":              (SFXType.DING,          EventType.PEAK),
    "Chime":             (SFXType.CHIME,         EventType.PEAK),
    "Tick":              (SFXType.DING,          EventType.PEAK),
    "Music":             (SFXType.WHOOSH,        EventType.SCENE_TRANSITION),
    "Silence":           (SFXType.NONE,          EventType.PAUSE),
}

# Duygu → Zoom kararı
EMOTION_ZOOM_MAP = {
    "angry":    (109.0, True),   # Öfke → agresif zoom
    "fearful":  (105.0, True),   # Korku → hafif zoom
    "happy":    (107.0, True),   # Mutluluk → standart zoom
    "surprised":(108.0, True),   # Şaşkınlık → hızlı zoom
    "disgust":  (104.0, False),  # Tiksinti → zoom yok
    "sad":      (100.0, False),  # Üzüntü → zoom geri çek
    "neutral":  (100.0, False),  # Nötr → normal
}


# ===========================================================================
# Veri Sınıfları
# ===========================================================================

@dataclass
class WhisperSegment:
    """Whisper'dan gelen bir konuşma segmenti"""
    start:      float
    end:        float
    text:       str
    is_emphasis: bool = False   # Büyük harf, ünlem veya kısa/yüksek segment


@dataclass
class YAMNetEvent:
    """YAMNet'ten gelen bir ses olayı"""
    start:      float
    end:        float
    class_name: str
    confidence: float
    sfx_type:   SFXType
    event_type: EventType


@dataclass
class EmotionSegment:
    """Wav2Vec duygu analizinden gelen bir segment"""
    start:   float
    end:     float
    emotion: str
    score:   float
    arousal: float   # 0-1: düşük=sakin, yüksek=heyecanlı


# ===========================================================================
# Katman 1: Whisper Konuşma Transkripsiyonu
# ===========================================================================

class WhisperLayer:
    """
    OpenAI Whisper kullanarak ses dosyasını transkripte eder.
    Her kelimenin/segmentin zaman damgasını çıkarır.
    Vurgulu kelimeleri (büyük harf, ünlem, kısa+güçlü cümleler) tespit eder.
    """

    def __init__(self, model_size: str = "base"):
        """
        model_size: "tiny" | "base" | "small" | "medium" | "large"
        Öneri: "base" (hız/kalite dengesi), "medium" (daha doğru)
        """
        self.model_size = model_size
        self._model = None  # Lazy load — ilk kullanımda yüklenir

    def _load_model(self):
        """Whisper modelini RAM'e yükler (ilk çağrıda)."""
        if self._model is None:
            try:
                import whisper
                logger.info(f"Whisper modeli yükleniyor: {self.model_size}")
                t0 = time.time()
                self._model = whisper.load_model(self.model_size)
                logger.info(f"Whisper yüklendi ({time.time()-t0:.1f}s)")
            except ImportError:
                raise ImportError(
                    "Whisper yüklü değil: pip install openai-whisper"
                )
        return self._model

    def transcribe(self, file_path: str) -> list[WhisperSegment]:
        """
        Ses dosyasını transkripte eder ve WhisperSegment listesi döndürür.
        word_timestamps=True ile her kelimenin zaman damgası çıkarılır.

        Args:
            file_path: Ses dosyası yolu

        Returns:
            WhisperSegment listesi (zaman damgalı konuşma birimleri)
        """
        model = self._load_model()
        logger.info(f"Whisper transkripsiyonu başlıyor: {file_path}")
        t0 = time.time()

        try:
            result = model.transcribe(
                file_path,
                word_timestamps=True,   # Kelime bazında zaman damgası
                language=None,          # Otomatik dil tespiti
                verbose=False,
            )
        except Exception as e:
            logger.error(f"Whisper transkripsiyon hatası: {e}")
            raise RuntimeError(f"Whisper hatası: {e}") from e

        elapsed = time.time() - t0
        logger.info(
            f"Transkripsiyon tamamlandı ({elapsed:.1f}s): "
            f"{len(result.get('segments', []))} segment"
        )

        return self._extract_segments(result)

    def _extract_segments(self, whisper_result: dict) -> list[WhisperSegment]:
        """
        Whisper çıktısını WhisperSegment listesine dönüştürür.
        Vurgulu segmentleri işaretler.
        """
        segments = []

        for seg in whisper_result.get("segments", []):
            text  = seg.get("text", "").strip()
            start = float(seg.get("start", 0.0))
            end   = float(seg.get("end", 0.0))

            if not text:
                continue

            # Vurgu tespiti: büyük harf yoğunluğu, ünlem, kısa+güçlü segmentler
            is_emphasis = self._detect_emphasis(text, start, end)

            segments.append(WhisperSegment(
                start=start,
                end=end,
                text=text,
                is_emphasis=is_emphasis,
            ))

            # Kelime düzeyinde granüler segmentler (word_timestamps varsa)
            words = seg.get("words", [])
            for word_info in words:
                word_text  = word_info.get("word", "").strip()
                word_start = float(word_info.get("start", start))
                word_end   = float(word_info.get("end", end))
                word_prob  = float(word_info.get("probability", 0.5))

                # Yüksek olasılıklı ve vurgulu kelimeleri ekle
                if word_prob > 0.85 and self._detect_emphasis(word_text, word_start, word_end):
                    segments.append(WhisperSegment(
                        start=word_start,
                        end=word_end,
                        text=word_text,
                        is_emphasis=True,
                    ))

        # Sırala ve tekrarları temizle
        segments.sort(key=lambda s: s.start)
        return self._deduplicate(segments)

    @staticmethod
    def _detect_emphasis(text: str, start: float, end: float) -> bool:
        """
        Bir metin segmentinin vurgulu olup olmadığını belirler.
        Kurallar:
          - Büyük harf oranı > %60 (bağırma/vurgu)
          - Ünlem işareti içeriyor
          - Çok kısa ama güçlü segment (< 0.3s)
          - Soru işareti + kısa süre (dramatik soru)
        """
        if not text:
            return False

        # Büyük harf yoğunluğu
        letters = [c for c in text if c.isalpha()]
        if letters:
            upper_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if upper_ratio > 0.6:
                return True

        # Noktalama tabanlı vurgu
        if "!" in text:
            return True

        # Çok kısa segment (tek kelime, yüksek enerji varsayımı)
        duration = end - start
        if duration < 0.3 and len(text.split()) == 1:
            return True

        return False

    @staticmethod
    def _deduplicate(segments: list[WhisperSegment], min_dist: float = 0.2) -> list[WhisperSegment]:
        """Çok yakın segmentleri birleştirir."""
        if not segments:
            return segments
        result = [segments[0]]
        for seg in segments[1:]:
            if seg.start - result[-1].start >= min_dist:
                result.append(seg)
        return result

    def to_audio_events(self, segments: list[WhisperSegment]) -> list[AudioEvent]:
        """WhisperSegment listesini AudioEvent listesine dönüştürür."""
        events = []
        for seg in segments:
            if not seg.is_emphasis:
                continue  # Sadece vurgulu segmentleri ekle

            sfx = SFXType.POP if len(seg.text.split()) > 1 else SFXType.DING

            events.append(AudioEvent(
                time_seconds=round(seg.start, 3),
                timecode=seconds_to_timecode(seg.start),
                event_type=EventType.PEAK,
                sfx_type=sfx,
                rms_value=0.0,   # Whisper RMS bilmez
                confidence=0.85,
            ))

        return events


# ===========================================================================
# Katman 2: YAMNet Ses Olay Sınıflandırıcı
# ===========================================================================

class YAMNetLayer:
    """
    Google YAMNet modeli ile ses olaylarını sınıflandırır.
    521 AudioSet sınıfından video editörle ilgili olanları filtreler.
    TensorFlow Hub üzerinden çalışır.
    """

    CHUNK_DURATION = 0.96   # YAMNet'in çalıştığı pencere boyutu (saniye)
    MIN_CONFIDENCE = 0.25   # Bu değerin altındaki tahminler atılır

    def __init__(self):
        self._model = None
        self._class_names = None

    def _load_model(self):
        """YAMNet modelini TensorFlow Hub'dan yükler."""
        if self._model is None:
            try:
                import tensorflow as tf
                import tensorflow_hub as hub
                logger.info("YAMNet modeli yükleniyor (TF Hub)...")
                t0 = time.time()
                self._model = hub.load(
                    "https://tfhub.dev/google/yamnet/1"
                )
                # Sınıf isimlerini yükle
                import csv, io, urllib.request
                class_map_url = (
                    "https://raw.githubusercontent.com/tensorflow/models/"
                    "master/research/audioset/yamnet/yamnet_class_map.csv"
                )
                with urllib.request.urlopen(class_map_url) as f:
                    reader = csv.DictReader(io.StringIO(f.read().decode()))
                    self._class_names = [row["display_name"] for row in reader]

                logger.info(f"YAMNet yüklendi ({time.time()-t0:.1f}s), {len(self._class_names)} sınıf")

            except ImportError as e:
                raise ImportError(
                    f"YAMNet bağımlılıkları eksik: {e}\n"
                    "Yüklemek için: pip install tensorflow tensorflow-hub"
                )
        return self._model

    def classify(self, file_path: str) -> list[YAMNetEvent]:
        """
        Ses dosyasını 0.96s'lik pencerelere bölerek her pencerede
        ses sınıflandırması yapar.

        Returns:
            YAMNetEvent listesi (yalnızca YAMNET_CLASS_MAP'te tanımlı sınıflar)
        """
        import librosa
        import tensorflow as tf

        model = self._load_model()
        logger.info(f"YAMNet sınıflandırması başlıyor: {file_path}")
        t0 = time.time()

        # YAMNet 16kHz mono ses ister
        y, sr = librosa.load(file_path, sr=16000, mono=True)
        waveform = tf.constant(y, dtype=tf.float32)

        # Çalıştır: scores (n_frames, 521), embeddings, spectrogram
        scores, embeddings, spectrogram = model(waveform)
        scores_np = scores.numpy()  # shape: (n_frames, 521)

        logger.info(
            f"YAMNet tamamlandı ({time.time()-t0:.1f}s): "
            f"{scores_np.shape[0]} frame"
        )

        return self._extract_events(scores_np, total_duration=len(y)/16000)

    def _extract_events(
        self, scores: np.ndarray, total_duration: float
    ) -> list[YAMNetEvent]:
        """
        Her frame'deki en yüksek skorlu sınıfı değerlendirerek
        YAMNET_CLASS_MAP'teki sınıflara eşleşen olayları döndürür.
        """
        events = []
        n_frames = scores.shape[0]
        frame_dur = total_duration / n_frames if n_frames > 0 else self.CHUNK_DURATION

        for i, frame_scores in enumerate(scores):
            start = round(i * frame_dur, 3)
            end   = round(start + frame_dur, 3)

            # En yüksek 3 skoru kontrol et
            top_indices = np.argsort(frame_scores)[::-1][:3]

            for idx in top_indices:
                if self._class_names is None:
                    break
                if idx >= len(self._class_names):
                    continue

                class_name  = self._class_names[idx]
                confidence  = float(frame_scores[idx])

                if confidence < self.MIN_CONFIDENCE:
                    continue

                # YAMNET_CLASS_MAP'te tanımlı mı veya genel anahtar kelime eşleşmesi var mı?
                mapping = YAMNET_CLASS_MAP.get(class_name)
                if mapping or any(k in class_name.lower() for k in ("laugh", "giggle", "snicker", "boom", "punch", "hit", "wind", "whoosh", "applause", "bell", "ding")):
                    sfx_type, event_type = get_yamnet_sfx(class_name)

                    if sfx_type == SFXType.NONE:
                        continue

                    events.append(YAMNetEvent(
                        start=start,
                        end=end,
                        class_name=class_name,
                        confidence=confidence,
                        sfx_type=sfx_type,
                        event_type=event_type,
                    ))
                    break  # Bu frame için bir olay yeterli

        # Yakın olayları birleştir
        return self._merge_adjacent(events)

    @staticmethod
    def _merge_adjacent(
        events: list[YAMNetEvent], gap: float = 0.5
    ) -> list[YAMNetEvent]:
        """
        Aynı sınıftan ve 0.5s'den yakın olayları tek olaya birleştirir.
        """
        if not events:
            return events

        merged = [events[0]]
        for evt in events[1:]:
            prev = merged[-1]
            if (evt.class_name == prev.class_name and
                    evt.start - prev.end <= gap):
                # Birleştir: sonu uzat, güveni ortalamasını al
                merged[-1] = YAMNetEvent(
                    start=prev.start,
                    end=evt.end,
                    class_name=prev.class_name,
                    confidence=(prev.confidence + evt.confidence) / 2,
                    sfx_type=prev.sfx_type,
                    event_type=prev.event_type,
                )
            else:
                merged.append(evt)

        return merged

    def to_audio_events(self, yamnet_events: list[YAMNetEvent]) -> list[AudioEvent]:
        """YAMNetEvent listesini AudioEvent listesine dönüştürür."""
        return [
            AudioEvent(
                time_seconds=round(evt.start, 3),
                timecode=seconds_to_timecode(evt.start),
                event_type=evt.event_type,
                sfx_type=evt.sfx_type,
                rms_value=0.0,
                confidence=round(evt.confidence, 3),
            )
            for evt in yamnet_events
        ]


# ===========================================================================
# Katman 3: Wav2Vec 2.0 Duygu Analizi
# ===========================================================================

class EmotionLayer:
    """
    HuggingFace Wav2Vec 2.0 tabanlı ses duygu tanıma modeli.
    Konuşmacının duygusal durumunu zaman dilimlerine göre belirler.
    Yüksek arousal (heyecan/öfke) dönemlerine zoom efekti ekler.

    Varsayılan model: ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition
    """

    MODEL_ID   = "ehcalabres/wav2vec2-lg-xlsr-en-speech-emotion-recognition"
    CHUNK_SEC  = 3.0    # Her analiz penceresi (saniye)
    OVERLAP    = 0.5    # Pencereler arası örtüşme (saniye)
    SR         = 16000  # Model örnekleme hızı

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or self.MODEL_ID
        self._pipe    = None

    def _load_model(self):
        """Duygu modelini HuggingFace Hub'dan yükler."""
        if self._pipe is None:
            try:
                from transformers import pipeline
                import torch
                device = 0 if torch.cuda.is_available() else -1
                logger.info(f"Duygu modeli yükleniyor: {self.model_id}")
                t0 = time.time()
                self._pipe = pipeline(
                    "audio-classification",
                    model=self.model_id,
                    device=device,
                )
                logger.info(f"Duygu modeli yüklendi ({time.time()-t0:.1f}s)")
            except ImportError as e:
                raise ImportError(
                    f"Transformers/Torch eksik: {e}\n"
                    "Yüklemek için: pip install transformers torch torchaudio"
                )
        return self._pipe

    def analyze(self, file_path: str) -> list[EmotionSegment]:
        """
        Ses dosyasını CHUNK_SEC uzunluğunda pencerelere bölerek
        her pencerenin duygusunu tahmin eder.

        Returns:
            EmotionSegment listesi
        """
        import librosa

        pipe = self._load_model()
        logger.info(f"Duygu analizi başlıyor: {file_path}")
        t0 = time.time()

        # 16kHz mono yükle
        y, _ = librosa.load(file_path, sr=self.SR, mono=True)
        total_dur = len(y) / self.SR

        segments: list[EmotionSegment] = []
        step = self.CHUNK_SEC - self.OVERLAP
        current = 0.0

        while current < total_dur:
            end = min(current + self.CHUNK_SEC, total_dur)
            s_idx = int(current * self.SR)
            e_idx = int(end * self.SR)

            chunk = y[s_idx:e_idx]
            if len(chunk) < self.SR * 0.5:  # 0.5s'den kısa parçaları atla
                break

            try:
                # Pipeline ses array'i alabilir
                results = pipe(
                    {"array": chunk, "sampling_rate": self.SR},
                    top_k=3,
                )

                # En yüksek skorlu duygu
                top = results[0]
                emotion = top["label"].lower()
                score   = float(top["score"])

                # Arousal hesapla (heyecan seviyesi)
                arousal = self._compute_arousal(results)

                segments.append(EmotionSegment(
                    start=round(current, 3),
                    end=round(end, 3),
                    emotion=emotion,
                    score=score,
                    arousal=arousal,
                ))

                logger.debug(
                    f"[{current:.1f}s-{end:.1f}s] "
                    f"duygu={emotion} ({score:.0%}), arousal={arousal:.2f}"
                )

            except Exception as e:
                logger.warning(f"Duygu analizi chunk hatası [{current:.1f}s]: {e}")

            current += step

        elapsed = time.time() - t0
        logger.info(
            f"Duygu analizi tamamlandı ({elapsed:.1f}s): "
            f"{len(segments)} segment"
        )

        return segments

    @staticmethod
    def _compute_arousal(results: list[dict]) -> float:
        """
        Duygu tahmin sonuçlarından arousal (heyecan/enerji) skoru hesaplar.
        Yüksek arousal duyguları: angry, fearful, surprised, happy
        Düşük arousal duyguları: sad, neutral, calm, disgust
        """
        HIGH_AROUSAL = {"angry", "fearful", "surprised", "happy", "excited"}
        LOW_AROUSAL  = {"sad", "neutral", "calm", "disgust", "bored"}

        arousal = 0.0
        for r in results:
            label = r["label"].lower()
            score = float(r["score"])
            if label in HIGH_AROUSAL:
                arousal += score
            elif label in LOW_AROUSAL:
                arousal -= score * 0.5

        return max(0.0, min(1.0, arousal))

    def to_zoom_keyframes(
        self,
        emotion_segments: list[EmotionSegment],
        arousal_threshold: float = 0.6,
        hold_duration: float = 0.4,
    ) -> list[ZoomKeyframe]:
        """
        Yüksek arousal dönemlerini zoom keyframe'lerine dönüştürür.

        Args:
            emotion_segments:  EmotionSegment listesi
            arousal_threshold: Bu değerin üzerindeki arousal → zoom başlat
            hold_duration:     Zoom-in ne kadar süre tutulsun (saniye)

        Returns:
            ZoomKeyframe listesi
        """
        keyframes: list[ZoomKeyframe] = []

        for seg in emotion_segments:
            if seg.arousal < arousal_threshold:
                continue

            emotion_cfg = EMOTION_ZOOM_MAP.get(seg.emotion, (107.0, True))
            zoom_scale, do_zoom = emotion_cfg

            if not do_zoom:
                continue

            # Segmentin başına zoom-in
            keyframes.append(ZoomKeyframe(
                time_seconds=seg.start,
                timecode=seconds_to_timecode(seg.start),
                scale=zoom_scale,
                type="zoom_in",
            ))

            # hold_duration sonra zoom-out
            zoom_out_time = seg.start + hold_duration
            keyframes.append(ZoomKeyframe(
                time_seconds=round(zoom_out_time, 3),
                timecode=seconds_to_timecode(zoom_out_time),
                scale=100.0,
                type="zoom_out",
            ))

        return keyframes


# ===========================================================================
# Ana AI Pipeline — Üç Katmanı Birleştirir
# ===========================================================================

class AIPipeline:
    """
    Whisper + YAMNet + Wav2Vec duygu analizini birleştirerek
    tam AnalysisResult üretir.

    Katmanlar paralel veya sıralı çalışabilir.
    Aynı zaman dilimine birden fazla AI karar verirse öncelik tablosu kullanılır.
    """

    def __init__(
        self,
        use_whisper:  bool = True,
        use_yamnet:   bool = True,
        use_emotion:  bool = True,
        whisper_model: str = "base",
        yamnet_min_conf: float = 0.25,
        emotion_arousal_threshold: float = 0.6,
        also_run_dsp: bool = True,  # Eski DSP analizini de çalıştır (hibrit mod)
    ):
        self.use_whisper  = use_whisper
        self.use_yamnet   = use_yamnet
        self.use_emotion  = use_emotion
        self.also_run_dsp = also_run_dsp

        # Katman örnekleri
        self.whisper_layer = WhisperLayer(model_size=whisper_model) if use_whisper else None
        self.yamnet_layer  = YAMNetLayer()                           if use_yamnet  else None
        self.emotion_layer = EmotionLayer()                          if use_emotion else None
        self.dsp_analyzer  = AudioAnalyzer()                         if also_run_dsp else None

        self.emotion_arousal_threshold = emotion_arousal_threshold

    # -----------------------------------------------------------------------
    # Ana Analiz Fonksiyonu
    # -----------------------------------------------------------------------
    def analyze(
        self,
        file_path: str,
        timeline_offset: float = 0.0,
    ) -> AnalysisResult:
        """
        Üç AI katmanını çalıştırır, sonuçları birleştirir.

        Args:
            file_path:       Ses dosyasının tam yolu
            timeline_offset: Timeline başlangıç offseti (saniye)

        Returns:
            Birleşik AnalysisResult
        """
        logger.info("=" * 60)
        logger.info("AI Pipeline başlatıldı")
        logger.info(f"Dosya: {file_path}")
        logger.info(
            f"Aktif katmanlar: "
            f"{'Whisper ' if self.use_whisper else ''}"
            f"{'YAMNet ' if self.use_yamnet else ''}"
            f"{'Duygu ' if self.use_emotion else ''}"
            f"{'DSP ' if self.also_run_dsp else ''}"
        )

        all_events:   list[AudioEvent]   = []
        all_keyframes: list[ZoomKeyframe] = []

        # ---- Katman 1: DSP (eski yöntem, hız için her zaman çalıştır) ----
        dsp_result = None
        if self.dsp_analyzer:
            logger.info("[DSP] Başlatıldı...")
            try:
                dsp_result = self.dsp_analyzer.analyze(file_path, offset=timeline_offset)
                all_events.extend(dsp_result.events)
                all_keyframes.extend(dsp_result.zoom_keyframes)
                logger.info(
                    f"[DSP] Tamamlandı: {len(dsp_result.events)} event, "
                    f"{len(dsp_result.zoom_keyframes)} zoom KF"
                )
            except Exception as e:
                logger.warning(f"[DSP] Hata (atlandı): {e}")

        # ---- Katman 2: Whisper ----
        if self.whisper_layer:
            logger.info("[Whisper] Başlatıldı...")
            try:
                segments = self.whisper_layer.transcribe(file_path)
                w_events = self.whisper_layer.to_audio_events(segments)
                # Offset ekle
                for e in w_events:
                    e.time_seconds += timeline_offset
                    e.timecode = seconds_to_timecode(e.time_seconds)
                all_events.extend(w_events)
                logger.info(f"[Whisper] {len(w_events)} vurgulu kelime/segment bulundu")
            except Exception as e:
                logger.warning(f"[Whisper] Hata (atlandı): {e}")

        # ---- Katman 3: YAMNet ----
        if self.yamnet_layer:
            logger.info("[YAMNet] Başlatıldı...")
            try:
                yamnet_events = self.yamnet_layer.classify(file_path)
                y_events = self.yamnet_layer.to_audio_events(yamnet_events)
                for e in y_events:
                    e.time_seconds += timeline_offset
                    e.timecode = seconds_to_timecode(e.time_seconds)
                all_events.extend(y_events)
                logger.info(f"[YAMNet] {len(y_events)} ses olayı sınıflandırıldı")
            except Exception as e:
                logger.warning(f"[YAMNet] Hata (atlandı): {e}")

        # ---- Katman 4: Duygu Analizi ----
        if self.emotion_layer:
            logger.info("[Duygu] Başlatıldı...")
            try:
                emotion_segs = self.emotion_layer.analyze(file_path)
                e_keyframes  = self.emotion_layer.to_zoom_keyframes(
                    emotion_segs,
                    arousal_threshold=self.emotion_arousal_threshold,
                )
                for kf in e_keyframes:
                    kf.time_seconds += timeline_offset
                    kf.timecode = seconds_to_timecode(kf.time_seconds)
                all_keyframes.extend(e_keyframes)
                logger.info(f"[Duygu] {len(e_keyframes)} zoom keyframe üretildi")
            except Exception as e:
                logger.warning(f"[Duygu] Hata (atlandı): {e}")

        # ---- Birleştir ve Temizle ----
        merged_events    = self._merge_events(all_events)
        merged_keyframes = self._merge_keyframes(all_keyframes)

        # DSP'den metadata al (veya default değerler)
        total_duration = dsp_result.total_duration if dsp_result else 0.0
        sample_rate    = dsp_result.sample_rate    if dsp_result else 0
        rms_mean       = dsp_result.rms_mean       if dsp_result else 0.0
        rms_std        = dsp_result.rms_std        if dsp_result else 0.0

        logger.info(
            f"Pipeline tamamlandı: "
            f"{len(merged_events)} event, "
            f"{len(merged_keyframes)} zoom KF"
        )
        logger.info("=" * 60)

        return AnalysisResult(
            total_duration=total_duration,
            sample_rate=sample_rate,
            rms_mean=rms_mean,
            rms_std=rms_std,
            events=merged_events,
            zoom_keyframes=merged_keyframes,
        )

    # -----------------------------------------------------------------------
    # Birleştirme: Çakışan Event'leri Önceliğe Göre Çöz
    # -----------------------------------------------------------------------
    @staticmethod
    def _merge_events(
        events: list[AudioEvent],
        window: float = 0.15,
    ) -> list[AudioEvent]:
        """
        Aynı zaman dilimine (±window saniye) düşen event'leri
        SFX öncelik tablosuna göre birleştirir.
        """
        if not events:
            return events

        # Zaman sırasına diz
        events.sort(key=lambda e: e.time_seconds)

        merged = [events[0]]

        for evt in events[1:]:
            prev = merged[-1]

            # Çakışıyor mu?
            if abs(evt.time_seconds - prev.time_seconds) <= window:
                # Yüksek öncelikli SFX'i koru
                if SFX_PRIORITY.get(evt.sfx_type, 0) > SFX_PRIORITY.get(prev.sfx_type, 0):
                    merged[-1] = evt
                # Aynı öncelikte → güveni güncelle
                elif SFX_PRIORITY.get(evt.sfx_type, 0) == SFX_PRIORITY.get(prev.sfx_type, 0):
                    merged[-1].confidence = max(prev.confidence, evt.confidence)
            else:
                merged.append(evt)

        return merged

    @staticmethod
    def _merge_keyframes(
        keyframes: list[ZoomKeyframe],
        window: float = 0.2,
    ) -> list[ZoomKeyframe]:
        """
        Çok yakın zoom keyframe'leri birleştirir (en yüksek scale kazanır).
        """
        if not keyframes:
            return keyframes

        keyframes.sort(key=lambda kf: kf.time_seconds)
        merged = [keyframes[0]]

        for kf in keyframes[1:]:
            prev = merged[-1]
            if abs(kf.time_seconds - prev.time_seconds) <= window:
                # En agresif zoom'u koru
                if kf.scale > prev.scale:
                    merged[-1] = kf
            else:
                merged.append(kf)

        return merged
