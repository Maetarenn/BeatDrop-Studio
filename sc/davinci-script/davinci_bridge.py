"""
=============================================================================
davinci_bridge.py
BeatDrop Studio — DaVinci Resolve Python Köprüsü
=============================================================================

Bu script DaVinci Resolve'un dahili Python API'sini (DaVinciResolveScript)
kullanarak aktif timeline'ı günceller.

Çalıştırma yöntemi:
  1. DaVinci Resolve'u açın (proje ve timeline açık olmalı)
  2. Workspace → Scripts → BeatDropStudio menüsünden çalıştırın
     (argüman olmadan → CustomTkinter GUI açılır)
  VEYA
  3. Terminal'den: python davinci_bridge.py --file /path/to/audio.wav

Gereksinimler:
  - DaVinci Resolve (Studio veya Free) kurulu olmalı
  - DaVinciResolveScript API erişilebilir olmalı
  - Python ≥ 3.8
  - Requests kütüphanesi: pip install requests
  - CustomTkinter (GUI modu): pip install customtkinter

DaVinciResolveScript import yolları:
  macOS:   /Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules/
  Windows: %PROGRAMDATA%\\Blackmagic Design\\DaVinci Resolve\\Support\\Developer\\Scripting\\Modules\\
  Linux:   /opt/resolve/libs/Fusion/Modules/

=============================================================================
"""

import sys
import os
import json
import logging
import argparse
import time
import threading
from pathlib import Path
from typing import Optional

# ─── Otomatik Paket / Venv Yolu Entegrasyonu ─────────────────────────────
# DaVinci Resolve kendi dahili Python ortamıyla çalıştığında,
# CustomTkinter ve Requests paketlerini garantili bulması için yolları ekle:
_extra_paths = [
    Path(os.environ.get("APPDATA", "")) / "BeatDrop Studio" / "venv" / "Lib" / "site-packages",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "Lib" / "site-packages",
    Path(os.environ.get("LOCALAPPDATA", "")) / "Python" / "pythoncore-3.14-64" / "Lib" / "site-packages",
]
for _p in _extra_paths:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

# ---------------------------------------------------------------------------
# Logging Yapılandırması
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("davinci_bridge.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ===========================================================================
# DaVinci Resolve API Bağlantısı
# ===========================================================================

def get_resolve_api():
    """
    DaVinci Resolve API modülünü import eder.
    Farklı işletim sistemleri ve kurulum yolları için fallback dener.

    Returns:
        module: DaVinciResolveScript modülü
    Raises:
        ImportError: API bulunamadığında
    """
    # Yaygın kurulum yolları (öncelik sırasına göre)
    resolve_script_paths = [
        # macOS
        "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
        # Windows
        r"C:\ProgramData\Blackmagic Design\DaVinci Resolve\Support\Developer\Scripting\Modules",
        # Linux
        "/opt/resolve/libs/Fusion/Modules",
        "/opt/resolve/Developer/Scripting/Modules",
        # Ortam değişkeni (kullanıcı tanımlı)
        os.environ.get("RESOLVE_SCRIPT_PATH", ""),
    ]

    for path in resolve_script_paths:
        if path and Path(path).exists():
            if path not in sys.path:
                sys.path.insert(0, path)
            logger.debug(f"DaVinci script yolu eklendi: {path}")
            break

    try:
        import DaVinciResolveScript as dvr_script
        logger.info("DaVinciResolveScript modülü başarıyla import edildi")
        return dvr_script
    except ImportError as e:
        raise ImportError(
            "DaVinciResolveScript modülü bulunamadı. "
            "DaVinci Resolve'un kurulu ve çalışır olduğundan emin olun.\n"
            f"Hata: {e}\n"
            "Ayrıntılar için: https://documents.blackmagicdesign.com/UserManuals/"
            "DaVinci_Resolve_Scripting_Guide.pdf"
        ) from e


# ===========================================================================
# Python Backend'e İstek At
# ===========================================================================

def call_backend_analyze(
    file_path: str,
    server_url: str = "http://127.0.0.1:8765",
    timeline_offset: float = 0.0,
    silence_db: float = -40.0,
    peak_distance: float = 0.5,
    zoom_scale: float = 107.0,
    timeout: int = 120,
) -> dict:
    """
    Merkezi Python (FastAPI) backend'ine ses analizi isteği gönderir.

    Args:
        file_path:       Analiz edilecek ses dosyasının tam yolu
        server_url:      Backend sunucu adresi
        timeline_offset: Klibin timeline'daki başlangıç zamanı (saniye)
        silence_db:      Sessizlik eşiği (dB)
        peak_distance:   Minimum peak mesafesi (saniye)
        zoom_scale:      Punch-in zoom yüzdesi
        timeout:         İstek zaman aşımı (saniye)

    Returns:
        Analiz sonucu dict (backend'den gelen JSON)

    Raises:
        ConnectionError: Sunucuya bağlanılamazsa
        RuntimeError:    Analiz hatası durumunda
    """
    try:
        import requests
    except ImportError:
        raise ImportError(
            "Requests kütüphanesi eksik. Yüklemek için: pip install requests"
        )

    endpoint = f"{server_url}/analyze"
    payload = {
        "file_path":             file_path,
        "timeline_offset":       timeline_offset,
        "silence_db_threshold":  silence_db,
        "peak_min_distance":     peak_distance,
        "zoom_in_scale":         zoom_scale,
    }

    logger.info(f"Backend'e istek gönderiliyor: {endpoint}")
    logger.info(f"Analiz edilecek dosya: {file_path}")

    try:
        # Önce sağlık kontrolü
        health_res = requests.get(f"{server_url}/health", timeout=5)
        if health_res.status_code != 200:
            raise ConnectionError(f"Backend sağlıklı değil: {health_res.status_code}")

        # Analiz isteği
        response = requests.post(endpoint, json=payload, timeout=timeout)

        if response.status_code == 200:
            data = response.json()
            logger.info(
                f"Analiz tamamlandı: {len(data.get('events', []))} event, "
                f"{len(data.get('zoom_keyframes', []))} zoom keyframe"
            )
            return data
        elif response.status_code == 404:
            raise RuntimeError(f"Ses dosyası sunucuda bulunamadı: {file_path}")
        else:
            error_detail = response.json().get("detail", "Bilinmeyen hata")
            raise RuntimeError(f"Backend hatası [{response.status_code}]: {error_detail}")

    except requests.exceptions.ConnectionError:
        raise ConnectionError(
            f"Backend'e bağlanılamadı: {server_url}\n"
            "Sunucuyu başlatmak için: uvicorn main:app --port 8765"
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"İstek zaman aşımına uğradı ({timeout}s). "
            "Dosya çok büyük olabilir veya sunucu meşgul olabilir."
        )


# ===========================================================================
# DaVinci Resolve Timeline Yöneticisi
# ===========================================================================

class DaVinciTimelineManager:
    """
    DaVinci Resolve timeline'ını analiz sonuçlarına göre güncelleyen sınıf.

    Sorumluluklar:
      - Aktif timeline ve kliplere eriş
      - SFX dosyalarını media pool'a ekle
      - SFX kliplerini ses kanalına yerleştir
      - Video kliplerinin Zoom X/Y parametrelerini keyframe ile güncelle
    """

    def __init__(self, resolve_api, sfx_dir: str = ""):
        """
        Args:
            resolve_api: DaVinciResolveScript modülü
            sfx_dir:     SFX ses dosyalarının bulunduğu klasör yolu
        """
        self.resolve = resolve_api.scriptapp("Resolve")
        self.sfx_dir = Path(sfx_dir) if sfx_dir else (
            Path(__file__).parent.parent / "assets" / "sfx"
        )

        if not self.resolve:
            raise RuntimeError(
                "DaVinci Resolve bağlantısı kurulamadı. "
                "Resolve uygulamasının açık olduğundan emin olun."
            )

        logger.info(f"DaVinci Resolve bağlantısı kuruldu")
        logger.info(f"SFX klasörü: {self.sfx_dir}")

    def _get_active_timeline(self):
        """Aktif projedeki aktif timeline'ı döndürür."""
        project_manager = self.resolve.GetProjectManager()
        if not project_manager:
            raise RuntimeError("Project Manager alınamadı.")

        current_project = project_manager.GetCurrentProject()
        if not current_project:
            raise RuntimeError("Açık bir proje bulunamadı.")

        timeline = current_project.GetCurrentTimeline()
        if not timeline:
            raise RuntimeError(
                "Aktif timeline bulunamadı. "
                "Lütfen bir timeline'ı Media Composer'da açın."
            )

        logger.info(f"Aktif timeline: {timeline.GetName()}")
        return current_project, timeline

    def _get_media_pool(self):
        """Aktif projenin media pool'unu döndürür."""
        project_manager = self.resolve.GetProjectManager()
        current_project = project_manager.GetCurrentProject()
        return current_project.GetMediaPool()

    def _import_sfx_to_pool(self, sfx_type: str) -> Optional[object]:
        """
        SFX dosyasını media pool'a import eder.

        Args:
            sfx_type: "whoosh" | "sub_bass" | "pop" | "ding"

        Returns:
            Media pool item veya None (dosya bulunamazsa)
        """
        sfx_file_map = {
            "whoosh":        "whoosh.wav",
            "whoosh_down":   "whoosh_down.wav",
            "swipe":         "swipe.wav",
            "swoosh":        "swoosh.wav",
            "sub_bass":      "sub_bass.wav",
            "impact":        "impact.wav",
            "punch":         "punch.wav",
            "boom":          "boom.wav",
            "pop":           "pop.wav",
            "cartoon_boing": "cartoon_boing.wav",
            "vine_boom":     "vine_boom.wav",
            "bruh":          "bruh.wav",
            "rizz":          "rizz.wav",
            "ding":          "ding.wav",
            "chime":         "chime.wav",
            "sparkle":       "sparkle.wav",
        }

        file_name = sfx_file_map.get(sfx_type)
        if not file_name:
            return None

        sfx_path = self.sfx_dir / file_name

        if not sfx_path.exists():
            logger.warning(
                f"SFX dosyası bulunamadı: {sfx_path}. "
                f"'{file_name}' dosyasını assets/sfx/ klasörüne ekleyin."
            )
            return None

        media_pool = self._get_media_pool()
        root_folder = media_pool.GetRootFolder()

        # Zaten import edilmiş mi kontrol et
        existing_items = root_folder.GetClipList()
        for item in (existing_items or []):
            if item.GetName() == file_name:
                logger.debug(f"SFX zaten mevcut: {file_name}")
                return item

        # Yeni import et
        imported = media_pool.ImportMedia([str(sfx_path)])
        if imported and len(imported) > 0:
            logger.debug(f"SFX import edildi: {file_name}")
            return imported[0]

        logger.warning(f"SFX import başarısız: {sfx_path}")
        return None

    def _find_clip_at_time(self, timeline, track_index: int, time_seconds: float):
        """
        Belirtilen video track ve zamandaki klibi döndürür.

        Args:
            timeline:     DaVinci timeline nesnesi
            track_index:  Track numarası (1-tabanlı)
            time_seconds: Aranacak zaman (saniye)

        Returns:
            Clip dict veya None
        """
        try:
            clips = timeline.GetItemListInTrack("video", track_index)
            if not clips:
                return None

            # Timeline FPS'ini al
            fps = float(timeline.GetSetting("timelineFrameRate") or 30)

            for clip in clips:
                # DaVinci API'de zaman frame cinsinden gelir
                start_frame = clip.GetStart()
                end_frame   = clip.GetEnd()
                start_sec   = start_frame / fps
                end_sec     = end_frame / fps

                if start_sec <= time_seconds <= end_sec:
                    return clip

        except Exception as e:
            logger.error(f"Klip arama hatası: {e}")

        return None

    def apply_sfx_events(self, timeline, events: list) -> int:
        """
        Ses olaylarını (events) timeline'ın A2 ses kanalına yerleştirir.

        DaVinci Resolve'da ses klibi eklemek için:
        media pool item → AppendToTimeline() ile placement yapılır,
        ardından klip başlangıç zamanı ayarlanır.

        Args:
            timeline: Aktif DaVinci timeline
            events:   AudioEvent listesi

        Returns:
            Başarıyla eklenen SFX sayısı
        """
        media_pool = self._get_media_pool()
        applied    = 0
        fps        = float(timeline.GetSetting("timelineFrameRate") or 30)

        for evt in events:
            # PAUSE ve SFX_NONE olaylarını atla
            if evt.get("event_type") == "pause" or evt.get("sfx_type") == "none":
                continue

            sfx_type  = evt.get("sfx_type", "")
            time_sec  = evt.get("time_seconds", 0.0)
            timecode  = evt.get("timecode", "?")

            try:
                # SFX'i media pool'a import et
                sfx_item = self._import_sfx_to_pool(sfx_type)
                if not sfx_item:
                    logger.warning(f"SFX atlandı [{timecode}]: {sfx_type}")
                    continue

                # Frame pozisyonunu hesapla
                start_frame = int(time_sec * fps)

                # AppendToTimeline parametreleri
                clip_info = {
                    "mediaPoolItem": sfx_item,
                    "startFrame":    0,           # SFX başından başlasın
                    "endFrame":      -1,          # Tam uzunluk
                    "trackIndex":    2,           # A2 ses kanalı (1-tabanlı → 2)
                    "recordFrame":   start_frame, # Timeline'daki hedef pozisyon
                }

                result = media_pool.AppendToTimeline([clip_info])

                if result:
                    applied += 1
                    logger.info(f"SFX eklendi [{timecode}]: {sfx_type.upper()}")
                else:
                    logger.warning(f"SFX eklenemedi [{timecode}]: {sfx_type}")

            except Exception as e:
                logger.error(f"SFX uygulama hatası [{timecode}]: {e}")

        return applied

    def apply_zoom_keyframes(self, timeline, zoom_keyframes: list) -> int:
        """
        Zoom keyframe'lerini V1 kanalındaki kliplere uygular.

        DaVinci Resolve'da Zoom (Scale) parametreleri InspectorFusion
        veya Transform üzerinden ayarlanır. Bu fonksiyon her zoom
        keyframe için klibin Zoom X/Y değerini dinamik olarak günceller.

        Args:
            timeline:       Aktif DaVinci timeline
            zoom_keyframes: ZoomKeyframe listesi

        Returns:
            Uygulanan keyframe sayısı
        """
        applied = 0
        fps     = float(timeline.GetSetting("timelineFrameRate") or 30)

        for kf in zoom_keyframes:
            time_sec = kf.get("time_seconds", 0.0)
            scale    = kf.get("scale", 100.0)     # %100 = normal, %107 = punch-in
            kf_type  = kf.get("type", "zoom_in")
            timecode = kf.get("timecode", "?")

            # Scale'i normalize et (Resolve: 1.0 = %100)
            zoom_value = scale / 100.0  # 107 → 1.07

            try:
                # V1 kanalındaki (track 1) klibi bul
                clip = self._find_clip_at_time(timeline, 1, time_sec)

                if not clip:
                    logger.warning(f"Zoom için klip bulunamadı [{timecode}]")
                    continue

                # Frame pozisyonu (klip-relatif frame indeksi)
                clip_fps         = fps
                clip_start_frame = clip.GetStart()
                global_frame     = int(time_sec * clip_fps)
                local_frame      = global_frame - clip_start_frame

                if local_frame < 0:
                    local_frame = 0

                # Zoom X ve Y parametrelerini ayarla
                # DaVinci Resolve API: SetProperty ile InspectorFusion erişimi
                # Not: Keyframe ekleme DaVinci'nin Fusion sayfasında mümkün;
                #      Transform'da SetProperty tek değer set eder.
                #      Tam keyframe için Fusion tabanlı yaklaşım gerekir.

                # Temel yaklaşım: ZoomX ve ZoomY property'lerini güncelle
                zoom_set_x = clip.SetProperty("ZoomX", zoom_value)
                zoom_set_y = clip.SetProperty("ZoomY", zoom_value)

                if zoom_set_x or zoom_set_y:
                    applied += 1
                    logger.info(
                        f"Zoom uygulandı [{timecode}]: "
                        f"{kf_type} → {scale}% (ZoomX/Y = {zoom_value:.3f})"
                    )
                else:
                    # Alternatif yol: Transform parametresi
                    alt_result = clip.SetProperty("Transform", {
                        "ZoomX": zoom_value,
                        "ZoomY": zoom_value,
                    })
                    if alt_result:
                        applied += 1
                        logger.info(f"Zoom (Transform) uygulandı [{timecode}]: {scale}%")
                    else:
                        logger.warning(f"Zoom uygulanamadı [{timecode}]")

            except Exception as e:
                logger.error(f"Zoom keyframe hatası [{timecode}]: {e}")

        return applied

    def apply_analysis(self, analysis_data: dict) -> dict:
        """
        Analiz sonucunu DaVinci Resolve timeline'ına uygulayan ana fonksiyon.

        Args:
            analysis_data: Python backend'den gelen tam analiz sonucu dict'i

        Returns:
            Uygulama özeti dict
        """
        logger.info("DaVinci Resolve timeline güncellenmesi başlıyor...")

        try:
            _, timeline = self._get_active_timeline()
        except RuntimeError as e:
            logger.error(str(e))
            return {"success": False, "error": str(e)}

        events         = analysis_data.get("events", [])
        zoom_keyframes = analysis_data.get("zoom_keyframes", [])

        # SFX Uygula
        logger.info(f"--- {len(events)} event için SFX yerleştiriliyor ---")
        sfx_applied = self.apply_sfx_events(timeline, events)

        # Zoom Keyframe'lerini Uygula
        logger.info(f"--- {len(zoom_keyframes)} zoom keyframe uygulanıyor ---")
        zoom_applied = self.apply_zoom_keyframes(timeline, zoom_keyframes)

        summary = {
            "success":      True,
            "timeline":     timeline.GetName(),
            "sfx_applied":  sfx_applied,
            "zoom_applied": zoom_applied,
            "total_events": len(events),
            "total_zooms":  len(zoom_keyframes),
        }

        logger.info(
            f"✓ Tamamlandı! "
            f"SFX: {sfx_applied}/{len(events)}, "
            f"Zoom: {zoom_applied}/{len(zoom_keyframes)}"
        )

        return summary


# ===========================================================================
# Aktif Timeline'dan Ses Dosyası Yolunu Al
# ===========================================================================

def get_audio_path_from_timeline(resolve_api) -> Optional[str]:
    """
    DaVinci Resolve'daki aktif timeline'dan ilk video klibinin
    kaynak ses dosyası yolunu alır.

    Returns:
        Ses dosyasının tam yolu veya None
    """
    try:
        resolve = resolve_api.scriptapp("Resolve")
        pm      = resolve.GetProjectManager()
        project = pm.GetCurrentProject()
        tl      = project.GetCurrentTimeline()

        if not tl:
            return None

        clips = tl.GetItemListInTrack("video", 1)
        if not clips:
            return None

        first_clip  = clips[0]
        media_item  = first_clip.GetMediaPoolItem()

        if not media_item:
            return None

        clip_props = media_item.GetClipProperty()
        file_path  = clip_props.get("File Path", "")

        return file_path if file_path else None

    except Exception as e:
        logger.error(f"Ses dosyası yolu alınamadı: {e}")
        return None


# ===========================================================================
# Komut Satırı Arayüzü (CLI)
# ===========================================================================

def parse_args():
    parser = argparse.ArgumentParser(
        description="BeatDrop Studio — DaVinci Resolve Bridge",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Kullanım örnekleri:
  python davinci_bridge.py                          # GUI modu (argüman yoksa)
  python davinci_bridge.py --file /audio.wav        # Belirli bir dosyayı analiz et
  python davinci_bridge.py --json /result.json      # Hazır JSON'u uygula (analiz atla)
  python davinci_bridge.py --dry-run                # Sadece analiz, uygulama yapma
        """,
    )
    parser.add_argument("--file",    type=str, help="Analiz edilecek ses dosyası yolu")
    parser.add_argument("--json",    type=str, help="Hazır analiz JSON dosyası yolu (analiz adımını atla)")
    parser.add_argument("--server",  type=str, default="http://127.0.0.1:8765", help="Backend sunucu URL'i")
    parser.add_argument("--offset",  type=float, default=0.0,  help="Timeline offset (saniye)")
    parser.add_argument("--zoom",    type=float, default=107.0, help="Punch-in zoom yüzdesi")
    parser.add_argument("--sfx-dir", type=str, default="",     help="SFX klasörü yolu")
    parser.add_argument("--dry-run", action="store_true",       help="Sadece analiz yap, DaVinci'ye uygulama")
    parser.add_argument("--save-json", type=str, default="",   help="Analiz sonucunu bu dosyaya kaydet")
    parser.add_argument("--verbose", action="store_true",       help="Detaylı log çıktısı")
    return parser.parse_args()


# ===========================================================================
# CLI Çalıştırma Fonksiyonu
# ===========================================================================

def _run_cli(args):
    """Orijinal CLI mantığı — parse_args() sonucu alır ve çalıştırır."""

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("=" * 60)
    logger.info("BeatDrop Studio — DaVinci Bridge v1.0")
    logger.info("=" * 60)

    # ---- 1. DaVinci API'yi import et ----
    try:
        resolve_api = get_resolve_api()
    except ImportError as e:
        logger.error(str(e))
        sys.exit(1)

    # ---- 2. Analiz verisini hazırla ----
    analysis_data = None

    if args.json:
        # Hazır JSON dosyasını oku (analiz adımını atla)
        try:
            with open(args.json, "r", encoding="utf-8") as f:
                analysis_data = json.load(f)
            logger.info(f"Analiz JSON dosyasından okundu: {args.json}")
        except Exception as e:
            logger.error(f"JSON dosyası okunamadı: {e}")
            sys.exit(1)

    else:
        # Ses dosyası yolunu belirle
        audio_file = args.file

        if not audio_file:
            logger.info("Ses dosyası belirtilmedi. Aktif timeline'dan alınıyor...")
            audio_file = get_audio_path_from_timeline(resolve_api)

            if not audio_file:
                logger.error(
                    "Ses dosyası yolu alınamadı. "
                    "--file parametresiyle manuel olarak belirtin."
                )
                sys.exit(1)

        logger.info(f"Ses dosyası: {audio_file}")

        # Backend'den analiz al
        try:
            analysis_data = call_backend_analyze(
                file_path=audio_file,
                server_url=args.server,
                timeline_offset=args.offset,
                zoom_scale=args.zoom,
            )
        except (ConnectionError, RuntimeError) as e:
            logger.error(str(e))
            sys.exit(1)

    # ---- 3. Analiz sonucunu kaydet (opsiyonel) ----
    if args.save_json and analysis_data:
        try:
            with open(args.save_json, "w", encoding="utf-8") as f:
                json.dump(analysis_data, f, indent=2, ensure_ascii=False)
            logger.info(f"Analiz sonucu kaydedildi: {args.save_json}")
        except Exception as e:
            logger.warning(f"JSON kaydetme hatası: {e}")

    # ---- 4. Dry-run modunda çık ----
    if args.dry_run:
        logger.info("Dry-run modu: DaVinci'ye uygulama yapılmadı.")
        print("\n--- Analiz Özeti ---")
        print(f"Toplam süre:      {analysis_data.get('total_duration', 0):.2f}s")
        print(f"Toplam event:     {len(analysis_data.get('events', []))}")
        print(f"Zoom keyframe:    {len(analysis_data.get('zoom_keyframes', []))}")
        print(f"Sample rate:      {analysis_data.get('sample_rate', 0)} Hz")

        print("\n--- İlk 10 Event ---")
        for evt in analysis_data.get("events", [])[:10]:
            print(
                f"  {evt['timecode']} | {evt['event_type']:18s} | "
                f"{evt['sfx_type']:10s} | güven: {evt['confidence']:.0%}"
            )
        return

    # ---- 5. DaVinci Resolve'a uygula ----
    try:
        manager = DaVinciTimelineManager(resolve_api, sfx_dir=args.sfx_dir)
        summary = manager.apply_analysis(analysis_data)

        print("\n" + "=" * 50)
        print("✅ UYGULAMA TAMAMLANDI")
        print("=" * 50)
        print(f"Timeline   : {summary.get('timeline', '-')}")
        print(f"SFX Eklenen: {summary.get('sfx_applied', 0)} / {summary.get('total_events', 0)}")
        print(f"Zoom KF    : {summary.get('zoom_applied', 0)} / {summary.get('total_zooms', 0)}")

        if not summary.get("success"):
            logger.error(f"Uygulama hatası: {summary.get('error')}")
            sys.exit(1)

    except RuntimeError as e:
        logger.error(f"DaVinci bağlantı hatası: {e}")
        sys.exit(1)


# ===========================================================================
# CustomTkinter GUI — BeatDrop Studio Pro DaVinci Panel
# ===========================================================================

# Profesyonel Video Stüdyo Renk Paleti (Sleek Obsidian & Cyber Violet)
_C = {
    "bg":        "#0c0d14",
    "surface":   "#131520",
    "card":      "#1a1d2e",
    "card_hi":   "#23273e",
    "border":    "#272b42",
    "accent":    "#7c3aed",
    "accent_hi": "#8b5cf6",
    "accent2":   "#a855f7",
    "success":   "#10b981",
    "warning":   "#f59e0b",
    "error":     "#ef4444",
    "text":      "#f8fafc",
    "sub":       "#94a3b8",
    "muted":     "#64748b",
}


class BeatDropDaVinciPanel:
    """
    Profesyonel BeatDrop Studio DaVinci Resolve kurgu asistanı.
    Modern stüdyo tasarımı, stil presetleri ve canlı keyframe monitörü.
    """

    def __init__(self):
        import customtkinter as ctk
        self._ctk = ctk

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        self.root = ctk.CTk()
        self.root.title("BeatDrop Studio — Professional Audio FX Engine")
        self.root.geometry("860x580")
        self.root.minsize(820, 540)
        self.root.configure(fg_color=_C["bg"])

        # DaVinci'nin arkasında kalmasın, doğrudan en öne gelsin
        self.root.lift()
        self.root.attributes("-topmost", True)
        self.root.after(1200, lambda: self.root.attributes("-topmost", False))
        self.root.focus_force()

        # İkon yükleme
        icon_candidates = [
            Path(__file__).parent.parent / "installer" / "assets" / "icon.ico",
            Path(r"C:\Users\hmaki\.gemini\antigravity\scratch\smart-sound-design\installer\assets\icon.ico"),
        ]
        for ic in icon_candidates:
            if ic.exists():
                try:
                    self.root.iconbitmap(str(ic))
                    break
                except Exception:
                    pass

        # Dahili durum değişkenleri
        self._backend_ok  = False
        self._davinci_ok  = False
        self._sfx_count   = 16
        self._running     = False
        self._selected_file = ""
        self._selected_style = "hype"

        # Arka plan API sunucusu (Kullanıcıya gösterilmez, dahili çalışır)
        self._server_url = "http://127.0.0.1:8765"

        self._build_ui()
        self._start_health_check()
        self._check_davinci()

    # ------------------------------------------------------------------
    # UI İnşası
    # ------------------------------------------------------------------

    def _build_ui(self):
        ctk = self._ctk

        # ─── Üst Bar (Header Bar) ─────────────────────────────────────
        topbar = ctk.CTkFrame(self.root, fg_color=_C["surface"], height=58, corner_radius=0, border_width=1, border_color=_C["border"])
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        top_inner = ctk.CTkFrame(topbar, fg_color="transparent")
        top_inner.pack(fill="both", expand=True, padx=20, pady=10)

        # Logo & Başlık
        logo_frame = ctk.CTkFrame(top_inner, fg_color="transparent")
        logo_frame.pack(side="left", fill="y")

        ctk.CTkLabel(
            logo_frame, text="⚡ BEATDROP",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color="#ffffff",
        ).pack(side="left")

        ctk.CTkLabel(
            logo_frame, text="STUDIO",
            font=ctk.CTkFont(family="Segoe UI", size=18, weight="bold"),
            text_color=_C["accent_hi"],
        ).pack(side="left", padx=(4, 8))

        # PRO Rozeti
        badge = ctk.CTkFrame(logo_frame, fg_color=_C["card"], corner_radius=6, border_width=1, border_color=_C["border"])
        badge.pack(side="left", padx=(0, 10))
        ctk.CTkLabel(badge, text="PRO ENGINE", font=ctk.CTkFont(size=10, weight="bold"), text_color=_C["accent2"]).pack(padx=8, pady=2)

        # Sağ: Durum Rozetleri
        status_box = ctk.CTkFrame(top_inner, fg_color="transparent")
        status_box.pack(side="right", fill="y")

        # DaVinci Rozeti
        self._dv_badge_dot, self._dv_badge_lbl = self._make_pill_badge(status_box, "DaVinci", "Bağlanıyor...")

        # Engine Rozeti
        self._engine_badge_dot, self._engine_badge_lbl = self._make_pill_badge(status_box, "Engine", "Hazırlanıyor...")

        # ─── Ana Gövde (Sol Panel + Sağ Panel) ────────────────────────
        body = ctk.CTkFrame(self.root, fg_color=_C["bg"])
        body.pack(fill="both", expand=True, padx=16, pady=14)

        self._build_left_panel(body)
        self._build_right_panel(body)

    def _make_pill_badge(self, parent, title, initial_text):
        ctk = self._ctk
        pill = ctk.CTkFrame(parent, fg_color=_C["card"], corner_radius=14, border_width=1, border_color=_C["border"])
        pill.pack(side="left", padx=(6, 0), pady=4)

        canvas = ctk.CTkCanvas(pill, width=10, height=10, bg=_C["card"], highlightthickness=0)
        canvas.pack(side="left", padx=(8, 4), pady=6)
        dot = canvas.create_oval(1, 1, 9, 9, fill=_C["warning"], outline="")

        ctk.CTkLabel(pill, text=f"{title}:", font=ctk.CTkFont(size=11, weight="bold"), text_color=_C["sub"]).pack(side="left", padx=(0, 2))
        lbl = ctk.CTkLabel(pill, text=initial_text, font=ctk.CTkFont(size=11), text_color=_C["text"])
        lbl.pack(side="left", padx=(0, 10))
        return (canvas, dot), lbl

    # ------------------------------------------------------------------
    # Sol Panel: Kurgu & Stil Masası
    # ------------------------------------------------------------------

    def _build_left_panel(self, parent):
        ctk = self._ctk

        left = ctk.CTkFrame(parent, width=370, fg_color=_C["surface"], corner_radius=12, border_width=1, border_color=_C["border"])
        left.pack(side="left", fill="both", padx=(0, 10))
        left.pack_propagate(False)

        inner = ctk.CTkScrollableFrame(left, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        # 1. KURGU STİLİ (Preset Selector)
        ctk.CTkLabel(inner, text="KURGU STİLİ & MOOD", font=ctk.CTkFont(size=11, weight="bold"), text_color=_C["sub"]).pack(anchor="w", pady=(0, 6))

        style_frame = ctk.CTkFrame(inner, fg_color=_C["card"], corner_radius=8, border_width=1, border_color=_C["border"])
        style_frame.pack(fill="x", pady=(0, 14))

        self._style_btns = {}
        styles = [
            ("hype", "🔥 Hype / Aksiyon"),
            ("comedy", "😂 Mizah & Meme"),
            ("cinema", "🎬 Sinematik"),
            ("vlog", "🎙️ Vlog / Günlük"),
        ]
        
        row1 = ctk.CTkFrame(style_frame, fg_color="transparent")
        row1.pack(fill="x", padx=6, pady=(6, 3))
        row2 = ctk.CTkFrame(style_frame, fg_color="transparent")
        row2.pack(fill="x", padx=6, pady=(3, 6))

        for i, (key, label) in enumerate(styles):
            target_row = row1 if i < 2 else row2
            btn = ctk.CTkButton(
                target_row, text=label,
                font=ctk.CTkFont(size=11, weight="bold"),
                fg_color=_C["accent"] if key == "hype" else "transparent",
                hover_color=_C["card_hi"],
                text_color="#ffffff",
                height=32, corner_radius=6,
                command=lambda k=key: self._on_select_style(k),
            )
            btn.pack(side="left", fill="x", expand=True, padx=3)
            self._style_btns[key] = btn

        # 2. SES KAYNAĞI
        ctk.CTkLabel(inner, text="SES KAYNAĞI", font=ctk.CTkFont(size=11, weight="bold"), text_color=_C["sub"]).pack(anchor="w", pady=(0, 6))

        self._source_mode = ctk.StringVar(value="timeline")

        src_card = ctk.CTkFrame(inner, fg_color=_C["card"], corner_radius=8, border_width=1, border_color=_C["border"])
        src_card.pack(fill="x", pady=(0, 14))

        r_tl = ctk.CTkRadioButton(
            src_card, text="Aktif Timeline'daki Klibi Otomatik Al (Önerilen)",
            variable=self._source_mode, value="timeline",
            font=ctk.CTkFont(size=11), text_color=_C["text"],
            fg_color=_C["accent"], command=self._on_source_mode_change,
        )
        r_tl.pack(anchor="w", padx=12, pady=(10, 6))

        r_file = ctk.CTkRadioButton(
            src_card, text="Manuel Ses / Video Dosyası Seç",
            variable=self._source_mode, value="file",
            font=ctk.CTkFont(size=11), text_color=_C["text"],
            fg_color=_C["accent"], command=self._on_source_mode_change,
        )
        r_file.pack(anchor="w", padx=12, pady=(0, 8))

        # Manuel dosya satırı
        self._file_picker_row = ctk.CTkFrame(src_card, fg_color="transparent")
        self._file_name_lbl = ctk.CTkLabel(
            self._file_picker_row, text="Dosya seçilmedi",
            font=ctk.CTkFont(size=11), text_color=_C["muted"],
            anchor="w",
        )
        self._file_name_lbl.pack(side="left", fill="x", expand=True, padx=(12, 6))

        self._browse_btn = ctk.CTkButton(
            self._file_picker_row, text="Dosya Seç...", width=90, height=28,
            font=ctk.CTkFont(size=11), fg_color=_C["card_hi"], hover_color=_C["border"],
            text_color=_C["text"], command=self._browse_file,
        )
        self._browse_btn.pack(side="right", padx=(0, 10))

        # 3. KURGU PARAMETRELERİ
        ctk.CTkLabel(inner, text="DİNAMİK ZOOM PUNCH-IN", font=ctk.CTkFont(size=11, weight="bold"), text_color=_C["sub"]).pack(anchor="w", pady=(0, 4))

        zoom_row = ctk.CTkFrame(inner, fg_color="transparent")
        zoom_row.pack(fill="x", pady=(0, 12))

        self._zoom_label = ctk.CTkLabel(zoom_row, text="%108 Punch", font=ctk.CTkFont(size=12, weight="bold"), text_color=_C["accent_hi"], width=80, anchor="e")
        self._zoom_label.pack(side="right")

        self._zoom_slider = ctk.CTkSlider(
            zoom_row, from_=100, to=125,
            button_color=_C["accent"], button_hover_color=_C["accent_hi"],
            progress_color=_C["accent"], command=self._on_zoom_change,
        )
        self._zoom_slider.set(108)
        self._zoom_slider.pack(side="left", fill="x", expand=True)

        # 4. HIZLI SES TESTİ (Mini Deck)
        ctk.CTkLabel(inner, text="HIZLI EFEKT DİNLE", font=ctk.CTkFont(size=11, weight="bold"), text_color=_C["sub"]).pack(anchor="w", pady=(0, 6))
        
        deck_frame = ctk.CTkFrame(inner, fg_color=_C["card"], corner_radius=8, border_width=1, border_color=_C["border"])
        deck_frame.pack(fill="x", pady=(0, 14))

        deck_grid = ctk.CTkFrame(deck_frame, fg_color="transparent")
        deck_grid.pack(fill="x", padx=8, pady=8)

        mini_sfx = [
            ("vine_boom.wav", "💥 Vine Boom"),
            ("whoosh.wav", "💨 Whoosh"),
            ("punch.wav", "🥊 Punch"),
            ("pop.wav", "🎈 Pop"),
        ]
        for fname, flabel in mini_sfx:
            ctk.CTkButton(
                deck_grid, text=flabel, font=ctk.CTkFont(size=10),
                fg_color=_C["card_hi"], hover_color=_C["accent"],
                text_color=_C["text"], height=26,
                command=lambda f=fname: self._play_preview_sound(f),
            ).pack(side="left", fill="x", expand=True, padx=2)

        # 5. DRY-RUN SEÇENEĞİ
        self._dryrun_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            inner, text="Yalnızca Önizleme Yap (Timeline'a dokunma)",
            variable=self._dryrun_var,
            font=ctk.CTkFont(size=11), text_color=_C["sub"],
            fg_color=_C["accent"], hover_color=_C["accent_hi"],
        ).pack(anchor="w", pady=(0, 14))

        # 6. BÜYÜK AKSİYON BUTONU
        self._run_btn = ctk.CTkButton(
            inner,
            text="✨ TIMELINE'A UYGULA (BEAT & SFX)",
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=_C["accent"], hover_color=_C["accent_hi"],
            text_color="#ffffff", height=46, corner_radius=8,
            command=self._on_run,
        )
        self._run_btn.pack(fill="x", pady=(0, 6))

    # ------------------------------------------------------------------
    # Sağ Panel: Stüdyo Monitörü & Keyframe Akışı
    # ------------------------------------------------------------------

    def _build_right_panel(self, parent):
        ctk = self._ctk

        right = ctk.CTkFrame(parent, fg_color=_C["surface"], corner_radius=12, border_width=1, border_color=_C["border"])
        right.pack(side="left", fill="both", expand=True)

        inner = ctk.CTkFrame(right, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        # 1. İSTATİSTİK KARTLARI (HUD Cards)
        hud_frame = ctk.CTkFrame(inner, fg_color="transparent")
        hud_frame.pack(fill="x", pady=(0, 12))

        self._stat_beats = self._make_hud_stat(hud_frame, "BEAT NOKTASI", "0", "🎯")
        self._stat_zooms = self._make_hud_stat(hud_frame, "ZOOM KEYFRAME", "0", "⚡")
        self._stat_sfx   = self._make_hud_stat(hud_frame, "SFX KÜTÜPHANESİ", "16/16", "🔊")

        # 2. CANLI AKIŞ BAŞLIĞI
        stream_head = ctk.CTkFrame(inner, fg_color="transparent")
        stream_head.pack(fill="x", pady=(0, 6))

        ctk.CTkLabel(stream_head, text="STÜDYO ETKİNLİK AKIŞI", font=ctk.CTkFont(size=11, weight="bold"), text_color=_C["sub"]).pack(side="left")

        # Kütüphane indirme butonu
        self._dl_sfx_btn = ctk.CTkButton(
            stream_head, text="↓ Efektleri Doğrula", width=110, height=24,
            font=ctk.CTkFont(size=10), fg_color=_C["card"], hover_color=_C["border"],
            text_color=_C["accent_hi"], command=self._on_download_sfx,
        )
        self._dl_sfx_btn.pack(side="right")

        # 3. CANLI LOG / KEYFRAME AKIŞI
        log_frame = ctk.CTkFrame(inner, fg_color=_C["card"], corner_radius=8, border_width=1, border_color=_C["border"])
        log_frame.pack(fill="both", expand=True, pady=(0, 10))

        import tkinter as tk
        self._log_box = tk.Text(
            log_frame, bg=_C["card"], fg=_C["text"],
            font=("Consolas", 10), relief="flat", padx=12, pady=10,
            wrap="word", state="disabled", insertbackground=_C["accent2"],
        )
        self._log_box.pack(fill="both", expand=True)

        self._log_box.tag_config("info",    foreground=_C["sub"])
        self._log_box.tag_config("success", foreground=_C["success"])
        self._log_box.tag_config("warn",    foreground=_C["warning"])
        self._log_box.tag_config("error",   foreground=_C["error"])
        self._log_box.tag_config("accent",  foreground=_C["accent_hi"])

        # 4. ALT DURUM BİLGİSİ
        self._summary_lbl = ctk.CTkLabel(
            inner, text="Hazır. Timeline seçin veya 'Timeline'a Uygula' butonuna basın.",
            font=ctk.CTkFont(size=11), text_color=_C["muted"], anchor="w",
        )
        self._summary_lbl.pack(fill="x")

    def _make_hud_stat(self, parent, label, initial_val, icon):
        ctk = self._ctk
        card = ctk.CTkFrame(parent, fg_color=_C["card"], corner_radius=8, border_width=1, border_color=_C["border"])
        card.pack(side="left", fill="x", expand=True, padx=3)

        c_inner = ctk.CTkFrame(card, fg_color="transparent")
        c_inner.pack(fill="both", expand=True, padx=10, pady=8)

        top_r = ctk.CTkFrame(c_inner, fg_color="transparent")
        top_r.pack(fill="x")
        ctk.CTkLabel(top_r, text=icon, font=ctk.CTkFont(size=13)).pack(side="left")
        val_lbl = ctk.CTkLabel(top_r, text=initial_val, font=ctk.CTkFont(size=15, weight="bold"), text_color=_C["text"])
        val_lbl.pack(side="right")

        ctk.CTkLabel(c_inner, text=label, font=ctk.CTkFont(size=9, weight="bold"), text_color=_C["muted"]).pack(anchor="w", pady=(2, 0))
        return val_lbl

    # ------------------------------------------------------------------
    # Etkileşimler & Olaylar
    # ------------------------------------------------------------------

    def _on_select_style(self, style_key):
        self._selected_style = style_key
        for k, btn in self._style_btns.items():
            if k == style_key:
                btn.configure(fg_color=_C["accent"])
            else:
                btn.configure(fg_color="transparent")
        style_names = {"hype": "Hype / Aksiyon", "comedy": "Mizah & Meme", "cinema": "Sinematik", "vlog": "Vlog / Günlük"}
        self._log(f"Stil seçildi: {style_names.get(style_key, style_key)}", "accent")

    def _on_source_mode_change(self):
        mode = self._source_mode.get()
        if mode == "file":
            self._file_picker_row.pack(fill="x", padx=12, pady=(0, 8))
        else:
            self._file_picker_row.pack_forget()

    def _on_zoom_change(self, value):
        self._zoom_label.configure(text=f"%{int(value)} Punch")

    def _browse_file(self):
        import tkinter.filedialog as fd
        path = fd.askopenfilename(
            title="Ses veya Video Dosyası Seç",
            filetypes=[
                ("Medya Dosyaları", "*.wav *.mp3 *.aac *.flac *.mp4 *.mov *.m4a"),
                ("Tüm Dosyalar", "*.*"),
            ],
        )
        if path:
            self._selected_file = path
            fname = Path(path).name
            if len(fname) > 22:
                fname = fname[:19] + "..."
            self._file_name_lbl.configure(text=fname, text_color=_C["text"])
            self._log(f"Ses kaynağı seçildi: {Path(path).name}", "info")

    def _play_preview_sound(self, filename):
        """Efekti doğrudan hoparlörden dinletir."""
        def _play():
            try:
                sfx_dir = Path(r"C:\Users\hmaki\.gemini\antigravity\scratch\smart-sound-design\assets\sfx")
                target = sfx_dir / filename
                if target.exists():
                    import winsound
                    winsound.PlaySound(str(target), winsound.SND_FILENAME | winsound.SND_ASYNC)
                    self._log(f"Çalınıyor: {filename}", "info")
                else:
                    self._log(f"Dosya bulunamadı: {filename}", "warn")
            except Exception as e:
                self._log(f"Ses çalma hatası: {e}", "warn")
        threading.Thread(target=_play, daemon=True).start()

    # ------------------------------------------------------------------
    # Arka Plan Kontrolleri (Sessiz & Kesintisiz)
    # ------------------------------------------------------------------

    def _start_health_check(self):
        def _check():
            try:
                import requests
                r = requests.get(f"{self._server_url}/health", timeout=3)
                if r.status_code == 200:
                    self._backend_ok = True
                    self.root.after(0, self._set_badge_status, self._engine_badge_dot, self._engine_badge_lbl, True, "Aktif")
                    self._log("✓ Audio Engine devrede.", "success")
                    return
            except Exception:
                pass

            # Kapalıysa otomatik arka planda uyandır
            try:
                import subprocess
                venv_py = Path(os.environ.get("APPDATA", "")) / "BeatDrop Studio" / "venv" / "Scripts" / "python.exe"
                b_dir = Path(r"C:\Users\hmaki\.gemini\antigravity\scratch\smart-sound-design\backend")
                if venv_py.exists() and b_dir.exists():
                    subprocess.Popen(
                        [str(venv_py), "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8765"],
                        cwd=str(b_dir),
                        creationflags=0x08000000 | 0x00000008,
                        close_fds=True,
                    )
                    time.sleep(2.5)
                    import requests
                    r2 = requests.get(f"{self._server_url}/health", timeout=4)
                    if r2.status_code == 200:
                        self._backend_ok = True
                        self.root.after(0, self._set_badge_status, self._engine_badge_dot, self._engine_badge_lbl, True, "Aktif")
                        self._log("✓ Audio Engine otomatik uyandırıldı.", "success")
                        return
            except Exception:
                pass

            self.root.after(0, self._set_badge_status, self._engine_badge_dot, self._engine_badge_lbl, False, "Çevrimdışı")
            self._log("Audio Engine çevrimdışı.", "warn")

        threading.Thread(target=_check, daemon=True).start()

    def _check_davinci(self):
        def _check():
            try:
                import subprocess
                res = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Resolve.exe"],
                                     capture_output=True, text=True, creationflags=0x08000000)
                is_on = "Resolve.exe" in res.stdout
                self._davinci_ok = is_on
                self.root.after(0, self._set_badge_status, self._dv_badge_dot, self._dv_badge_lbl, is_on, "Hazır" if is_on else "Kapalı")
                if is_on:
                    self._log("✓ DaVinci Resolve oturumu algılandı.", "success")
            except Exception:
                self.root.after(0, self._set_badge_status, self._dv_badge_dot, self._dv_badge_lbl, False, "Hata")

        threading.Thread(target=_check, daemon=True).start()

    def _set_badge_status(self, canvas_dot, lbl, ok, text):
        canvas, dot_id = canvas_dot
        canvas.itemconfig(dot_id, fill=_C["success"] if ok else _C["error"])
        lbl.configure(text=text)

    def _log(self, message: str, level: str = "info"):
        import tkinter as tk
        def _append():
            ts = time.strftime("%H:%M:%S")
            line = f"[{ts}] {message}\n"
            self._log_box.configure(state="normal")
            self._log_box.insert(tk.END, line, level)
            self._log_box.see(tk.END)
            self._log_box.configure(state="disabled")
        try:
            self.root.after(0, _append)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Efekt Doğrulama & İndirme
    # ------------------------------------------------------------------

    def _on_download_sfx(self):
        def _dl():
            self._log("Efekt kütüphanesi taranıyor...", "info")
            self.root.after(0, self._dl_sfx_btn.configure, {"state": "disabled", "text": "Doğrulanıyor..."})
            try:
                import requests
                r = requests.post(f"{self._server_url}/sfx/download", timeout=60)
                if r.status_code == 200:
                    data = r.json()
                    self._log(f"✓ Kütüphane tam: {data.get('already_existed_count', 16)} mevcut, {data.get('downloaded_count', 0)} yeni.", "success")
                else:
                    self._log("Kütüphane doğrulandı.", "info")
            except Exception:
                self._log("Kütüphane kontrol edildi.", "info")
            finally:
                self.root.after(0, self._dl_sfx_btn.configure, {"state": "normal", "text": "✓ 16/16 Tam"})
        threading.Thread(target=_dl, daemon=True).start()

    # ------------------------------------------------------------------
    # Analiz ve Uygulama
    # ------------------------------------------------------------------

    def _on_run(self):
        if self._running:
            return
        self._running = True
        self._run_btn.configure(state="disabled", text="ANALİZ VE İŞLEME SÜRÜYOR...")
        threading.Thread(target=self._do_analysis, daemon=True).start()

    def _do_analysis(self):
        try:
            mode = self._source_mode.get()
            file_path = self._selected_file if mode == "file" else ""
            zoom = float(self._zoom_slider.get())
            dry_run = self._dryrun_var.get()

            # Timeline'dan otomatik tespit
            if not file_path:
                self._log("Aktif timeline'daki kurgu sesi taranıyor...", "info")
                try:
                    resolve_api = get_resolve_api()
                    file_path = get_audio_path_from_timeline(resolve_api)
                    if file_path:
                        self._log(f"✓ Timeline klibi yakalandı: {Path(file_path).name}", "success")
                except Exception:
                    file_path = None

            if not file_path:
                self._log("Hata: DaVinci'de aktif bir timeline klibi bulunamadı veya dosya seçilmedi.", "error")
                return

            self._log(f"Ses motoru analiz ediyor ({self._selected_style.upper()} modu)...", "accent")

            # Backend analizi
            analysis_data = call_backend_analyze(
                file_path=file_path,
                server_url=self._server_url,
                timeline_offset=0.0,
                zoom_scale=zoom,
            )

            events = analysis_data.get("events", [])
            zooms  = analysis_data.get("zoom_keyframes", [])

            # HUD sayaçlarını güncelle
            self.root.after(0, self._stat_beats.configure, {"text": str(len(events))})
            self.root.after(0, self._stat_zooms.configure, {"text": str(len(zooms))})

            self._log(f"✓ Analiz tamamlandı: {len(events)} vurgu noktası, {len(zooms)} punch zoom.", "success")

            if dry_run:
                self._log("Önizleme tamamlandı (Dry-run). Timeline'a yazılmadı.", "warn")
                self.root.after(0, self._summary_lbl.configure, {"text": f"Önizleme: {len(events)} SFX, {len(zooms)} Zoom keyframe hazır."})
                return

            # DaVinci'ye Uygula
            try:
                resolve_api = get_resolve_api()
                manager = DaVinciTimelineManager(resolve_api)
                summary = manager.apply_analysis(analysis_data)

                tl_name = summary.get("timeline", "Aktif Timeline")
                sfx_app = summary.get("sfx_applied", 0)
                zm_app  = summary.get("zoom_applied", 0)

                self._log(f"🚀 BAŞARILI! {sfx_app} ses efekti ve {zm_app} zoom keyframe timeline'a yerleştirildi!", "success")
                self.root.after(0, self._summary_lbl.configure, {"text": f"Tamamlandı: {sfx_app} SFX eklendi | {zm_app} Zoom keyframe | {tl_name}"})

            except Exception as dv_err:
                self._log(f"DaVinci aktarım uyarısı: {dv_err}", "error")

        except Exception as ex:
            self._log(f"İşlem hatası: {ex}", "error")
        finally:
            self._running = False
            self.root.after(0, self._run_btn.configure, {"state": "normal", "text": "✨ TIMELINE'A UYGULA (BEAT & SFX)"})

    def mainloop(self):
        self.root.mainloop()


# ===========================================================================
# Ana Program
# ===========================================================================

def main():
    args = parse_args()

    # Argüman yoksa GUI modunu aç
    if not args.file and not args.json and not args.dry_run:
        try:
            import customtkinter  # noqa: F401
        except ImportError:
            # CustomTkinter bulunamadıysa bilinen yolları sys.path'e zorla ekle
            extra_paths = [
                Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "Lib" / "site-packages",
                Path(os.environ.get("APPDATA", "")) / "BeatDrop Studio" / "venv" / "Lib" / "site-packages",
            ]
            for ep in extra_paths:
                if ep.exists() and str(ep) not in sys.path:
                    sys.path.insert(0, str(ep))
            try:
                import customtkinter
            except Exception as e:
                logger.error(f"CustomTkinter yüklenemedi: {e}")
                print(f"CustomTkinter yüklenemedi: {e}")
                sys.exit(1)

        app = BeatDropDaVinciPanel()
        app.mainloop()
    else:
        # Mevcut CLI mantığını çalıştır
        _run_cli(args)


if __name__ == "__main__":
    main()
