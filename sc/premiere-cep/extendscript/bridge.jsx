/**
 * =============================================================================
 * bridge.jsx — BeatDrop Studio
 * Adobe Premiere Pro ExtendScript Köprüsü
 * =============================================================================
 *
 * Bu dosya Adobe Premiere Pro'nun ExtendScript motorunda çalışır.
 * CEP panel (index.html içindeki JavaScript) csInterface.evalScript()
 * ile bu fonksiyonları çağırır.
 *
 * Sorumluluklar:
 *  1. Aktif timeline'dan ses klibi yolunu okur
 *  2. Python backend'den gelen analiz JSON'unu alır
 *  3. Ses efektlerini belirtilen zaman kodlarına ekler (A2 kanalına)
 *  4. Video kliplerinin Scale (Ölçek) değerini zoom keyframe'lerine göre ayarlar
 *
 * Notlar:
 *  - ExtendScript, ES3 uyumludur; modern JS sözdizimi (arrow fn, const vb.) kullanılamaz.
 *  - app.project.activeSequence üzerinden timeline manipülasyonu yapılır.
 *  - Ses efekti dosyaları lokal 'assets/sfx/' klasöründe olmalıdır.
 * =============================================================================
 */

// ============================================================================
// Sabitler
// ============================================================================

/** Python backend'in dinlediği URL */
var BACKEND_URL = "http://127.0.0.1:8765";

/** SFX efektlerinin yerleştirileceği ses kanalı indeksi (0-tabanlı, A2 = indeks 1) */
var SFX_AUDIO_TRACK_INDEX = 1;

/** Video zoom efektlerinin uygulanacağı video kanalı indeksi (V1 = indeks 0) */
var VIDEO_TRACK_INDEX = 0;

/** Opus ses efekti klasörünün tam yolu (kendi kurulumunuza göre düzenleyin) */
var SFX_FOLDER_PATH = "/Applications/BeatDropStudio/assets/sfx/";
// Windows için örnek: "C:\\BeatDropStudio\\assets\\sfx\\";


// ============================================================================
// 1. Aktif Klibin Ses Dosyası Yolunu Al
// ============================================================================

/**
 * Aktif sequence'taki ilk video klibine bağlı ses dosyasının tam yolunu döndürür.
 * CEP panel bu fonksiyonu çağırarak backend'e gönderecek dosya yolunu alır.
 *
 * @returns {string} Ses dosyasının tam yolu veya "ERROR:..." formatında hata
 */
function getActiveClipAudioPath() {
    try {
        var seq = app.project.activeSequence;
        if (!seq) {
            return "ERROR: Aktif sequence bulunamadı. Lütfen bir sequence açın.";
        }

        var videoTracks = seq.videoTracks;
        if (!videoTracks || videoTracks.numTracks === 0) {
            return "ERROR: Sequence'ta video kanalı bulunamadı.";
        }

        // V1 kanalındaki ilk klibi al
        var v1Track = videoTracks[VIDEO_TRACK_INDEX];
        var clips   = v1Track.clips;

        if (!clips || clips.numItems === 0) {
            return "ERROR: V1 kanalında klip bulunamadı.";
        }

        var firstClip   = clips[0];
        var projectItem = firstClip.projectItem;

        if (!projectItem) {
            return "ERROR: Klip proje öğesine bağlanamadı.";
        }

        // Medya dosyasının tam yolunu al
        var mediaPath = projectItem.getMediaPath();

        if (!mediaPath) {
            return "ERROR: Medya dosyası yolu alınamadı.";
        }

        return mediaPath;

    } catch (e) {
        return "ERROR: " + e.message;
    }
}


// ============================================================================
// 2. Analiz Sonucunu Timeline'a Uygula (Ana Fonksiyon)
// ============================================================================

/**
 * Python backend'den gelen analiz JSON'unu timeline'a uygular.
 * CEP panel'den JSON string olarak çağrılır.
 *
 * İşlemler:
 *  a) Her AudioEvent için → uygun SFX dosyasını A2 kanalına ekler
 *  b) Her ZoomKeyframe için → V1 kanalındaki klibin Scale değerini günceller
 *
 * @param {string} analysisJsonStr - Python backend'den gelen JSON string
 * @returns {string} Başarı mesajı veya "ERROR:..." formatında hata açıklaması
 */
function applyAnalysisToTimeline(analysisJsonStr) {
    try {
        // JSON string'i nesneye çevir
        var data = JSON.parse(analysisJsonStr);

        var seq = app.project.activeSequence;
        if (!seq) {
            return "ERROR: Aktif sequence bulunamadı.";
        }

        var appliedSFX  = 0;
        var appliedZoom = 0;
        var errors      = [];

        // ----------------------------------------------------------------
        // A. SFX Efektlerini Yerleştir
        // ----------------------------------------------------------------
        if (data.events && data.events.length > 0) {
            var sfxResult = _applySFXEvents(seq, data.events, errors);
            appliedSFX = sfxResult;
        }

        // ----------------------------------------------------------------
        // B. Zoom Keyframe'lerini Uygula
        // ----------------------------------------------------------------
        if (data.zoom_keyframes && data.zoom_keyframes.length > 0) {
            var zoomResult = _applyZoomKeyframes(seq, data.zoom_keyframes, errors);
            appliedZoom = zoomResult;
        }

        // Sonuç mesajı oluştur
        var msg = appliedSFX + " SFX eklendi, " + appliedZoom + " zoom keyframe uygulandı.";
        if (errors.length > 0) {
            msg += " [" + errors.length + " uyarı: " + errors.slice(0, 3).join("; ") + "]";
        }

        return msg;

    } catch (e) {
        return "ERROR: applyAnalysisToTimeline - " + e.message;
    }
}


// ============================================================================
// Dahili: SFX Olaylarını A2 Kanalına Yerleştir
// ============================================================================

/**
 * Verilen event listesindeki her SFX'i A2 ses kanalına ekler.
 * SFX dosyaları SFX_FOLDER_PATH klasöründen import edilir.
 *
 * @param {Sequence}  seq    - Aktif Premiere sequence nesnesi
 * @param {Array}     events - AudioEvent listesi
 * @param {Array}     errors - Hata mesajlarının biriktirildiği dizi (referans)
 * @returns {number} Başarıyla eklenen SFX sayısı
 */
function _applySFXEvents(seq, events, errors) {
    var count      = 0;
    var audioTrack = null;

    // A2 ses kanalına eriş (veya oluştur)
    try {
        var audioTracks = seq.audioTracks;

        if (audioTracks.numTracks <= SFX_AUDIO_TRACK_INDEX) {
            // Yeterli ses kanalı yoksa yeni ekle
            seq.audioTracks.addTrack();
        }

        audioTrack = audioTracks[SFX_AUDIO_TRACK_INDEX];
    } catch (e) {
        errors.push("Ses kanalı alınamadı: " + e.message);
        return 0;
    }

    // Her event için işlem yap
    for (var i = 0; i < events.length; i++) {
        var evt = events[i];

        // PAUSE olayları ve sfx_type="none" olanlar için SFX ekleme
        if (evt.event_type === "pause" || evt.sfx_type === "none") {
            continue;
        }

        // SFX dosyasının yolunu belirle
        var sfxFileName = _getSFXFileName(evt.sfx_type);
        if (!sfxFileName) {
            continue;
        }

        var sfxFilePath = SFX_FOLDER_PATH + sfxFileName;

        try {
            // Dosyayı projeye import et (zaten varsa Premiere atlar)
            var importResult = app.project.importFiles(
                [sfxFilePath],
                true,   // suppress UI
                app.project.rootItem,
                false   // import as numbered stills
            );

            // Import edilen öğeyi bul
            var sfxItem = _findProjectItem(app.project.rootItem, sfxFileName);

            if (!sfxItem) {
                errors.push(sfxFileName + " import edilemedi.");
                continue;
            }

            // Zaman kodunu tick'e çevir (Premiere iç birimi)
            var startTimeTicks = _secondsToTicks(evt.time_seconds);

            // Ses klibini timeline'a ekle
            audioTrack.insertClip(sfxItem, startTimeTicks);
            count++;

        } catch (e) {
            errors.push(
                "SFX eklenemedi [" + evt.timecode + "]: " + e.message
            );
        }
    }

    return count;
}


// ============================================================================
// Dahili: Zoom Keyframe'lerini V1 Klibine Uygula
// ============================================================================

/**
 * ZoomKeyframe listesindeki Scale değerlerini V1 kanalındaki
 * ilgili klibin Motion > Scale parametresine keyframe olarak ekler.
 *
 * @param {Sequence} seq            - Aktif Premiere sequence nesnesi
 * @param {Array}    zoomKeyframes  - ZoomKeyframe listesi
 * @param {Array}    errors         - Hata mesajları listesi
 * @returns {number} Uygulanan keyframe sayısı
 */
function _applyZoomKeyframes(seq, zoomKeyframes, errors) {
    var count      = 0;
    var videoTrack = null;

    try {
        videoTrack = seq.videoTracks[VIDEO_TRACK_INDEX];
    } catch (e) {
        errors.push("Video kanalı alınamadı: " + e.message);
        return 0;
    }

    if (!videoTrack || videoTrack.clips.numItems === 0) {
        errors.push("V1 kanalında klip bulunamadı.");
        return 0;
    }

    // Her keyframe için uygun klibi bul ve Scale ayarla
    for (var i = 0; i < zoomKeyframes.length; i++) {
        var kf = zoomKeyframes[i];

        try {
            // Zaman koduna göre hangi klipte olduğumuzu bul
            var clip = _findClipAtTime(videoTrack, kf.time_seconds);

            if (!clip) {
                errors.push("Klip bulunamadı: " + kf.timecode);
                continue;
            }

            // Motion > Scale parametresine eriş
            var motionEffect = _getMotionEffect(clip);
            if (!motionEffect) {
                errors.push("Motion efekti bulunamadı: " + kf.timecode);
                continue;
            }

            var scaleParam = motionEffect.parameters.getParamForName("scale");
            if (!scaleParam) {
                errors.push("Scale parametresi bulunamadı: " + kf.timecode);
                continue;
            }

            // Keyframe'i ekle
            var timeTicks = _secondsToTicks(kf.time_seconds);

            // Önce keyframe modunu etkinleştir
            scaleParam.setInterpolationType(kfInterp.kfInterpMode_Linear);

            // Keyframe değeri ekle
            scaleParam.addKey(timeTicks);
            scaleParam.setValueAtKey(timeTicks, kf.scale, false);

            count++;

        } catch (e) {
            errors.push(
                "Zoom keyframe hatası [" + kf.timecode + "]: " + e.message
            );
        }
    }

    return count;
}


// ============================================================================
// Yardımcı Fonksiyonlar
// ============================================================================

/**
 * SFX tipine göre dosya adını döndürür.
 * @param {string} sfxType - "whoosh" | "sub_bass" | "pop" | "ding"
 * @returns {string} Dosya adı veya ""
 */
function _getSFXFileName(sfxType) {
    var map = {
        "whoosh":   "whoosh.wav",
        "sub_bass": "sub_bass.wav",
        "pop":      "pop.wav",
        "ding":     "ding.wav"
    };
    return map[sfxType] || "";
}


/**
 * Proje ağacında belirtilen ada sahip öğeyi recursive olarak arar.
 * @param {ProjectItem} rootItem - Başlangıç klasörü
 * @param {string}      name     - Aranacak dosya adı
 * @returns {ProjectItem|null}
 */
function _findProjectItem(rootItem, name) {
    if (!rootItem || !rootItem.children) return null;

    for (var i = 0; i < rootItem.children.numItems; i++) {
        var child = rootItem.children[i];
        if (child.name === name) {
            return child;
        }
        // Alt klasörleri recursive ara
        if (child.type === ProjectItemType.BIN) {
            var found = _findProjectItem(child, name);
            if (found) return found;
        }
    }
    return null;
}


/**
 * Belirtilen saniye değerini Premiere'ın dahili Tick birimine çevirir.
 * Premiere Pro: 1 saniye = 254016000000 tick (QD2 time base)
 *
 * @param {number} seconds - Saniye cinsinden zaman
 * @returns {number} Tick değeri
 */
function _secondsToTicks(seconds) {
    var TICKS_PER_SECOND = 254016000000;
    return Math.round(seconds * TICKS_PER_SECOND);
}


/**
 * V1 track'inde belirtilen saniye değerinde bulunan klibi döndürür.
 * @param {Track}  track       - Video kanalı
 * @param {number} timeSec     - Aranacak zaman (saniye)
 * @returns {TrackItem|null}
 */
function _findClipAtTime(track, timeSec) {
    if (!track || !track.clips) return null;

    for (var i = 0; i < track.clips.numItems; i++) {
        var clip      = track.clips[i];
        var startSec  = clip.start.seconds;
        var endSec    = clip.end.seconds;

        if (timeSec >= startSec && timeSec <= endSec) {
            return clip;
        }
    }
    return null;
}


/**
 * Bir klip üzerindeki "Motion" (Hareket) video efektini döndürür.
 * @param {TrackItem} clip - Premiere klip nesnesi
 * @returns {VideoEffect|null}
 */
function _getMotionEffect(clip) {
    if (!clip || !clip.components) return null;

    for (var i = 0; i < clip.components.numItems; i++) {
        var component = clip.components[i];
        // Motion efektinin adı locale'e göre farklılık gösterebilir
        if (component.displayName === "Motion" ||
            component.displayName === "Hareket"  ||
            component.displayName === "Mouvement") {
            return component;
        }
    }
    return null;
}


// ============================================================================
// 3. Timeline'dan Aktif Klibin Bilgilerini Al (Debug Amaçlı)
// ============================================================================

/**
 * Aktif sequence hakkında özet bilgi döndürür.
 * CEP panel'den debug amacıyla çağrılabilir.
 *
 * @returns {string} JSON formatında sequence bilgisi
 */
function getSequenceInfo() {
    try {
        var seq = app.project.activeSequence;
        if (!seq) {
            return "ERROR: Aktif sequence yok.";
        }

        var info = {
            name:           seq.name,
            duration:       seq.end.seconds,
            frameRate:      seq.videoFrameRate,
            videoTracks:    seq.videoTracks.numTracks,
            audioTracks:    seq.audioTracks.numTracks,
            timecode:       seq.getPlayerPosition().timecode
        };

        return JSON.stringify(info);

    } catch (e) {
        return "ERROR: " + e.message;
    }
}
