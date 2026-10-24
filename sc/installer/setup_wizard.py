"""
=============================================================================
setup_wizard.py — BeatDrop Studio v1.0
Kurulum Sihirbazı (CustomTkinter — Modern UI)
=============================================================================
Çalıştırma: python setup_wizard.py  (Python 3.9+, customtkinter gerekli)
pip install customtkinter

Ekranlar:
  0. Karşılama (Splash)
  1. Lisans Sözleşmesi
  2. Program Tespiti
  3. Bileşen Seçimi
  4. Kurulum İlerlemesi
  5. Tamamlandı / Hata
=============================================================================
"""

import sys
import threading
import platform
from pathlib import Path
import customtkinter as ctk
from tkinter import messagebox

IS_WINDOWS = platform.system() == "Windows"

# ── PyInstaller yol çözümlemesi ───────────────────────────────────────────
def _base_path() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).parent.parent

BASE_PATH   = _base_path()
_SCRIPT_DIR = BASE_PATH / "installer" / "scripts"
if not _SCRIPT_DIR.exists():
    _SCRIPT_DIR = BASE_PATH / "scripts"
sys.path.insert(0, str(_SCRIPT_DIR))

CORE_OK   = True
_CORE_ERR = ""
try:
    from installer_core import (
        ProgramDetector, run_installation,
        load_install_state,
    )
except ImportError as _e:
    CORE_OK   = False
    _CORE_ERR = str(_e)

# ── CustomTkinter Global Tema ─────────────────────────────────────────────
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ── Renk Paleti ───────────────────────────────────────────────────────────
C = {
    "bg":       "#0a0a0f",
    "surface":  "#111118",
    "surface2": "#18181f",
    "card":     "#1e1e28",
    "border":   "#2a2a3a",
    "accent":   "#7c3aed",
    "accent2":  "#a855f7",
    "success":  "#22c55e",
    "warning":  "#f59e0b",
    "danger":   "#ef4444",
    "text":     "#f1f5f9",
    "sub":      "#94a3b8",
    "muted":    "#475569",
}

WIN_W, WIN_H = 680, 540

# ─────────────────────────────────────────────────────────────────────────
# Ana Uygulama
# ─────────────────────────────────────────────────────────────────────────
class BeatDropInstaller(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("BeatDrop Studio — Kurulum Sihirbazı")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.resizable(False, False)
        self.configure(fg_color=C["bg"])

        # ── Uygulama ikonunu ayarla (görev çubuğu + başlık barı) ─────────
        self._set_icon()

        self._center()

        # Durum
        self.detected   = {}
        self.v_premiere = ctk.BooleanVar(value=True)
        self.v_davinci  = ctk.BooleanVar(value=True)
        self.v_ai       = ctk.BooleanVar(value=False)
        self.v_license  = ctk.BooleanVar(value=False)
        self.v_progress = ctk.DoubleVar(value=0)
        self.v_prog_msg = ctk.StringVar(value="")

        # İçerik alanı
        self.content = ctk.CTkFrame(self, fg_color=C["bg"], corner_radius=0)
        self.content.pack(fill="both", expand=True)

        self._screen_welcome()

    def _set_icon(self):
        """
        Görev çubuğu + başlık barı ikonunu BeatDrop Studio logosuyla değiştirir.
        ICO dosyası bulunamazsa PIL ile anlık üretir.
        """
        # İkon yolları: önce assets, sonra MEIPASS, sonra anlık üret
        candidates = [
            BASE_PATH / "installer" / "assets" / "icon.ico",
            BASE_PATH / "assets" / "icon.ico",
            Path(__file__).parent / "assets" / "icon.ico",
        ]
        ico_path = next((p for p in candidates if p.exists()), None)

        if ico_path is None:
            # Anlık ikon üret (PIL gerekir)
            try:
                from PIL import Image, ImageDraw
                ico_path = Path(__file__).parent / "_icon_tmp.ico"
                frames = []
                for size in [16, 32, 48, 64]:
                    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
                    d = ImageDraw.Draw(img)
                    m = max(1, size // 16)
                    d.ellipse([m, m, size-m, size-m], fill=(15, 8, 35, 255))
                    cx, cy, lw = size//2, size//2, max(1, size//18)
                    gap = max(2, size // 9)
                    for x, h, col in [
                        (cx-gap*2-lw, int(size*.28), (124,58,237,200)),
                        (cx-lw,       int(size*.58), (168,85,247,255)),
                        (cx+gap,      int(size*.42), (139,92,246,220)),
                    ]:
                        d.rounded_rectangle([x,cy-h//2,x+lw*2,cy+h//2], radius=lw, fill=col)
                    frames.append(img)
                frames[0].save(str(ico_path), format="ICO",
                               sizes=[(s, s) for s in [16,32,48,64]],
                               append_images=frames[1:])
            except Exception:
                return  # PIL yoksa varsayılan ikon kalır

        try:
            self.iconbitmap(str(ico_path))
        except Exception:
            # iconbitmap bazen macOS'ta hata verir — sessizce geç
            pass

    def _center(self):
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - WIN_W) // 2
        y = (self.winfo_screenheight() - WIN_H) // 2
        self.geometry(f"+{x}+{y}")

    def _clear(self):
        for w in self.content.winfo_children():
            w.destroy()

    # ── HEADER ──────────────────────────────────────────────────────────
    def _header(self, title: str, sub: str = ""):
        hdr = ctk.CTkFrame(self.content, fg_color=C["surface"],
                           corner_radius=0, height=90)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)

        # Sol mor şerit
        ctk.CTkFrame(hdr, fg_color=C["accent"],
                     corner_radius=0, width=5).pack(side="left", fill="y")

        inner = ctk.CTkFrame(hdr, fg_color=C["surface"], corner_radius=0)
        inner.pack(side="left", padx=20, pady=14, fill="both")

        ctk.CTkLabel(inner, text=title,
                     font=ctk.CTkFont("Segoe UI", 22, "bold"),
                     text_color=C["text"]).pack(anchor="w")
        if sub:
            ctk.CTkLabel(inner, text=sub,
                         font=ctk.CTkFont("Segoe UI", 10),
                         text_color=C["accent2"]).pack(anchor="w", pady=(1, 0))

    # ── NAVBAR ──────────────────────────────────────────────────────────
    def _navbar(self, back_cmd=None, next_cmd=None,
                next_text="İleri  →", back_text="← Geri",
                next_enabled=True):
        """
        ÖNCE çağrılmalı, body'den önce pack edilmeli!
        """
        bar = ctk.CTkFrame(self.content, fg_color=C["surface"],
                           corner_radius=0, height=62)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)

        # Üst ince çizgi
        ctk.CTkFrame(bar, fg_color=C["border"],
                     corner_radius=0, height=1).pack(fill="x")

        btn_row = ctk.CTkFrame(bar, fg_color=C["surface"], corner_radius=0)
        btn_row.pack(side="right", padx=20, pady=12)

        if back_cmd:
            ctk.CTkButton(btn_row, text=back_text, command=back_cmd,
                          width=110, height=36,
                          fg_color=C["card"], hover_color=C["border"],
                          text_color=C["sub"],
                          font=ctk.CTkFont("Segoe UI", 11),
                          corner_radius=8).pack(side="left", padx=(0, 10))

        nb = ctk.CTkButton(btn_row, text=next_text, command=next_cmd,
                           width=140, height=36,
                           fg_color=C["accent"], hover_color=C["accent2"],
                           text_color=C["text"],
                           font=ctk.CTkFont("Segoe UI", 11, "bold"),
                           corner_radius=8,
                           state="normal" if next_enabled else "disabled")
        nb.pack(side="left")
        return nb

    # ── BODY ────────────────────────────────────────────────────────────
    def _body(self, padx=30, pady=20):
        f = ctk.CTkFrame(self.content, fg_color=C["bg"], corner_radius=0)
        f.pack(fill="both", expand=True, padx=padx, pady=pady)
        return f

    # ── CARD ────────────────────────────────────────────────────────────
    def _card(self, parent, **kw):
        return ctk.CTkFrame(parent, fg_color=C["card"],
                            border_color=C["border"], border_width=1,
                            corner_radius=10, **kw)

    # ════════════════════════════════════════════════════════════════════
    # EKRAN 0 — Karşılama
    # ════════════════════════════════════════════════════════════════════
    def _screen_welcome(self):
        self._clear()
        self._header("BeatDrop Studio", "v1.0  ·  AI-Powered Sound Design & Pacing")
        self._navbar(next_cmd=self._screen_license, next_text="Başla  →")
        body = self._body()

        # Logo kartı
        logo_card = self._card(body)
        logo_card.pack(pady=(4, 0))
        ctk.CTkLabel(logo_card, text="🎵",
                     font=ctk.CTkFont("Segoe UI Emoji", 38),
                     width=80, height=80).pack(padx=20, pady=14)

        ctk.CTkLabel(body, text="Hoş Geldiniz!",
                     font=ctk.CTkFont("Segoe UI", 18, "bold"),
                     text_color=C["accent2"]).pack(pady=(14, 6))

        info_card = self._card(body)
        info_card.pack(fill="x", pady=(0, 6), ipady=4)
        for line in [
            "🎬  Adobe Premiere Pro ve DaVinci Resolve desteklenir",
            "🧠  AI ses analizi — Whisper + YAMNet + Duygu motoru",
            "⚡  Backend servisi otomatik kurulur ve başlatılır",
            "🚀  Tek tıkla kurulum — 5 dakikadan az sürer",
        ]:
            ctk.CTkLabel(info_card, text=line,
                         font=ctk.CTkFont("Segoe UI", 11),
                         text_color=C["sub"],
                         anchor="w").pack(anchor="w", padx=16, pady=3)

        ver_card = self._card(body)
        ver_card.pack(fill="x", ipady=6)
        ctk.CTkLabel(ver_card,
                     text="Versiyon 1.0.0  ·  Windows & macOS  ·  © 2024 BeatDrop Studio",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=C["muted"]).pack()

    # ════════════════════════════════════════════════════════════════════
    # EKRAN 1 — Lisans
    # ════════════════════════════════════════════════════════════════════
    def _screen_license(self):
        self._clear()
        self._header("Lisans Sözleşmesi", "Devam etmek için okuyun ve onaylayın")
        self._lic_next = self._navbar(
            back_cmd=self._screen_welcome,
            next_cmd=self._screen_detect,
            next_enabled=False)

        body = self._body(pady=14)

        # Checkbox ÖNCE (side=bottom)
        chk_frame = ctk.CTkFrame(body, fg_color=C["bg"], corner_radius=0)
        chk_frame.pack(side="bottom", fill="x", pady=(8, 0))
        ctk.CTkCheckBox(chk_frame,
                        text="  Lisans sözleşmesini okudum ve kabul ediyorum",
                        variable=self.v_license,
                        command=self._license_toggle,
                        font=ctk.CTkFont("Segoe UI", 11),
                        text_color=C["text"],
                        fg_color=C["accent"],
                        hover_color=C["accent2"],
                        border_color=C["border"],
                        checkmark_color=C["text"],
                        corner_radius=5).pack(anchor="w", padx=4)

        # Metin kutusu
        txt_card = self._card(body)
        txt_card.pack(fill="both", expand=True)
        txt_card.grid_rowconfigure(0, weight=1)
        txt_card.grid_columnconfigure(0, weight=1)

        txt = ctk.CTkTextbox(txt_card,
                             font=ctk.CTkFont("Segoe UI", 10),
                             text_color=C["sub"],
                             fg_color=C["surface"],
                             scrollbar_button_color=C["accent"],
                             corner_radius=8,
                             wrap="word")
        txt.pack(fill="both", expand=True, padx=2, pady=2)

        eula = """SON KULLANICI LİSANS SÖZLEŞMESİ (EULA)
BeatDrop Studio v1.0
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Bu yazılımı satın alarak aşağıdaki koşulları kabul etmiş sayılırsınız.

1. LİSANS HAKKI
Bu yazılım, tek bir kullanıcıya özel olarak kişisel lisanslanmıştır.
Yazılımı üçüncü şahıslara devredemez veya alt lisans veremezsiniz.

2. KULLANIM KAPSAMI
Yazılımı ticari projelerinizde serbestçe kullanabilirsiniz.
Oluşturulan içerikler üzerinde tam ticari hak size aittir.

3. KISITLAMALAR
• Kaynak kodunu kopyalayamaz veya dağıtamazsınız.
• Tersine mühendislik (reverse engineering) yasaktır.
• Birden fazla aktif kurulum için ek lisans satın alınmalıdır.

4. SORUMLULUK REDDİ
Yazılım "OLDUĞU GİBİ" sunulmaktadır. Geliştirici, yazılımın kesintisiz
veya hatasız çalışacağını garanti etmez. Yazılımın kullanımından
doğabilecek doğrudan veya dolaylı zararlardan sorumlu tutulamaz.

5. DESTEK
Lisans sahipleri satın alma tarihinden itibaren 12 ay ücretsiz
teknik destek alır.
E-posta: destek@beatdropstudio.com

6. GEÇERLİ HUKUK
Bu sözleşme Türkiye Cumhuriyeti kanunlarına tabidir. Anlaşmazlıklarda
Türkiye mahkemeleri yetkilidir.
"""
        txt.insert("1.0", eula)
        txt.configure(state="disabled")

    def _license_toggle(self):
        state = "normal" if self.v_license.get() else "disabled"
        self._lic_next.configure(state=state)

    # ════════════════════════════════════════════════════════════════════
    # EKRAN 2 — Program Tespiti
    # ════════════════════════════════════════════════════════════════════
    def _screen_detect(self):
        self._clear()
        self._header("Program Tespiti", "Bilgisayarınız taranıyor...")
        self._det_next = self._navbar(
            back_cmd=self._screen_license,
            next_cmd=self._screen_options,
            next_enabled=False)

        body = self._body()

        ctk.CTkLabel(body,
                     text="⏳  Video düzenleme yazılımları aranıyor...",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["accent2"]).pack(pady=(0, 14))

        # Premiere kart
        pp_card = self._card(body)
        pp_card.pack(fill="x", pady=5)
        pp_row = ctk.CTkFrame(pp_card, fg_color=C["card"], corner_radius=0)
        pp_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(pp_row,
                     text="🎬  Adobe Premiere Pro",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["text"]).pack(side="left")
        self._pp_badge = ctk.CTkLabel(pp_row, text="Taranıyor...",
                                      font=ctk.CTkFont("Segoe UI", 10),
                                      text_color=C["warning"])
        self._pp_badge.pack(side="right")
        self._pp_sub = ctk.CTkLabel(pp_card, text="",
                                    font=ctk.CTkFont("Segoe UI", 9),
                                    text_color=C["muted"])
        self._pp_sub.pack(anchor="w", padx=16, pady=(0, 10))

        # DaVinci kart
        dv_card = self._card(body)
        dv_card.pack(fill="x", pady=5)
        dv_row = ctk.CTkFrame(dv_card, fg_color=C["card"], corner_radius=0)
        dv_row.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(dv_row,
                     text="🎞️  DaVinci Resolve",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["text"]).pack(side="left")
        self._dv_badge = ctk.CTkLabel(dv_row, text="Taranıyor...",
                                      font=ctk.CTkFont("Segoe UI", 10),
                                      text_color=C["warning"])
        self._dv_badge.pack(side="right")
        self._dv_sub = ctk.CTkLabel(dv_card, text="",
                                    font=ctk.CTkFont("Segoe UI", 9),
                                    text_color=C["muted"])
        self._dv_sub.pack(anchor="w", padx=16, pady=(0, 10))

        # Tarama animasyonu (dönen yükleme çubuğu)
        self._scan_bar = ctk.CTkProgressBar(body,
                                            mode="indeterminate",
                                            progress_color=C["accent"],
                                            fg_color=C["card"],
                                            height=6,
                                            corner_radius=3)
        self._scan_bar.pack(fill="x", pady=(16, 0))
        self._scan_bar.start()

        threading.Thread(target=self._run_detect, daemon=True).start()

    def _run_detect(self):
        if not CORE_OK:
            self.after(0, lambda: messagebox.showerror(
                "Hata", f"Installer core yüklenemedi:\n{_CORE_ERR}"))
            return
        self.detected = ProgramDetector().detect_all()
        self.after(0, self._update_detect)

    def _update_detect(self):
        self._scan_bar.stop()
        self._scan_bar.pack_forget()

        pp = self.detected.get("premiere", {})
        dv = self.detected.get("davinci",  {})

        if pp.get("found"):
            self._pp_badge.configure(
                text=f"✓  BULUNDU  (v{pp.get('version','?')})",
                text_color=C["success"])
            self._pp_sub.configure(text=f"CEP Klasörü: {pp.get('cep_path','')}")
        else:
            self._pp_badge.configure(text="✗  BULUNAMADI", text_color=C["muted"])
            self._pp_sub.configure(text="Premiere Pro kurulmamış veya tespit edilemedi")

        if dv.get("found"):
            self._dv_badge.configure(
                text=f"✓  BULUNDU  (v{dv.get('version','?')})",
                text_color=C["success"])
            self._dv_sub.configure(text=f"Script Klasörü: {dv.get('script_path','')}")
        else:
            self._dv_badge.configure(text="✗  BULUNAMADI", text_color=C["muted"])
            self._dv_sub.configure(text="DaVinci Resolve kurulmamış veya tespit edilemedi")

        self._det_next.configure(state="normal")

        if not pp.get("found") and not dv.get("found"):
            messagebox.showwarning(
                "Program Bulunamadı",
                "Desteklenen bir video düzenleme yazılımı tespit edilemedi.\n"
                "Yine de devam edebilirsiniz.")

    # ════════════════════════════════════════════════════════════════════
    # EKRAN 3 — Bileşen Seçimi
    # ════════════════════════════════════════════════════════════════════
    def _screen_options(self):
        self._clear()
        self._header("Kurulum Seçenekleri", "Hangi bileşenler kurulsun?")
        self._navbar(back_cmd=self._screen_detect,
                     next_cmd=self._screen_install,
                     next_text="Kur  ✓")
        body = self._body()

        pp = self.detected.get("premiere", {})
        dv = self.detected.get("davinci",  {})

        def comp_card(icon, title, desc, var, found=True):
            c = self._card(body)
            c.pack(fill="x", pady=5)
            row = ctk.CTkFrame(c, fg_color=C["card"], corner_radius=0)
            row.pack(fill="x", padx=16, pady=(10, 4))

            ctk.CTkCheckBox(row, text="",
                            variable=var,
                            fg_color=C["accent"],
                            hover_color=C["accent2"],
                            border_color=C["border"],
                            checkmark_color=C["text"],
                            corner_radius=5,
                            state="normal" if found else "disabled",
                            width=24).pack(side="left", padx=(0, 10))

            info = ctk.CTkFrame(row, fg_color=C["card"], corner_radius=0)
            info.pack(side="left", fill="x", expand=True)
            ctk.CTkLabel(info,
                         text=f"{icon}  {title}",
                         font=ctk.CTkFont("Segoe UI", 12, "bold"),
                         text_color=C["text"] if found else C["muted"],
                         anchor="w").pack(anchor="w")
            ctk.CTkLabel(info, text=desc,
                         font=ctk.CTkFont("Segoe UI", 9),
                         text_color=C["sub"] if found else C["muted"],
                         anchor="w").pack(anchor="w")

            badge_color = C["success"] if found else C["muted"]
            badge_text  = "Tespit Edildi ✓" if found else "Bulunamadı"
            ctk.CTkLabel(row, text=badge_text,
                         font=ctk.CTkFont("Segoe UI", 9, "bold"),
                         text_color=badge_color).pack(side="right")

            ctk.CTkFrame(c, fg_color=C["border"],
                         height=1, corner_radius=0).pack(fill="x", padx=16)
            ctk.CTkLabel(c, text=f"  Kurulum yolu tespit edildi" if found else "  Manuel kurulum gerekebilir",
                         font=ctk.CTkFont("Segoe UI", 9),
                         text_color=C["muted"]).pack(anchor="w", padx=16, pady=(4, 10))

        pp_found = pp.get("found", False)
        dv_found = dv.get("found", False)
        if not pp_found: self.v_premiere.set(False)
        if not dv_found: self.v_davinci.set(False)

        comp_card("🎬", "Adobe Premiere Pro Paneli",
                  "CEP Extension + ExtendScript köprüsü",
                  self.v_premiere, found=pp_found)

        comp_card("🎞️", "DaVinci Resolve Script",
                  "Python köprüsü + Timeline entegrasyonu",
                  self.v_davinci, found=dv_found)

        # Zorunlu çekirdek
        core_c = self._card(body)
        core_c.pack(fill="x", pady=5)
        core_row = ctk.CTkFrame(core_c, fg_color=C["card"], corner_radius=0)
        core_row.pack(fill="x", padx=16, pady=10)
        ctk.CTkLabel(core_row,
                     text="✅  Çekirdek Motor  (Zorunlu — kaldırılamaz)",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["success"]).pack(side="left")
        ctk.CTkLabel(core_c,
                     text="  FastAPI backend  ·  LibROSA ses analizi  ·  SFX eşleştirici",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=C["muted"]).pack(anchor="w", padx=16, pady=(0, 10))

        # AI paketi
        ai_c = self._card(body)
        ai_c.pack(fill="x", pady=5)
        ai_row = ctk.CTkFrame(ai_c, fg_color=C["card"], corner_radius=0)
        ai_row.pack(fill="x", padx=16, pady=(10, 4))
        ctk.CTkCheckBox(ai_row, text="",
                        variable=self.v_ai,
                        fg_color=C["accent"],
                        hover_color=C["accent2"],
                        border_color=C["border"],
                        checkmark_color=C["text"],
                        corner_radius=5,
                        width=24).pack(side="left", padx=(0, 10))
        ai_info = ctk.CTkFrame(ai_row, fg_color=C["card"], corner_radius=0)
        ai_info.pack(side="left")
        ctk.CTkLabel(ai_info,
                     text="🧠  AI Paketi  (Opsiyonel)",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"),
                     text_color=C["accent2"]).pack(anchor="w")
        ctk.CTkLabel(ai_info,
                     text="Whisper + YAMNet + Duygu Analizi",
                     font=ctk.CTkFont("Segoe UI", 9),
                     text_color=C["sub"]).pack(anchor="w")
        ctk.CTkLabel(ai_row,
                     text="~6 GB  ·  ~15 dk",
                     font=ctk.CTkFont("Segoe UI", 9, "bold"),
                     text_color=C["warning"]).pack(side="right")

    # ════════════════════════════════════════════════════════════════════
    # EKRAN 4 — Kurulum
    # ════════════════════════════════════════════════════════════════════
    def _screen_install(self):
        self._clear()
        self._header("Kuruluyor...", "Lütfen bekleyin — pencereyi kapatmayın")
        # Alt bar (buton yok)
        ctk.CTkFrame(self.content, fg_color=C["surface"],
                     corner_radius=0, height=8).pack(side="bottom", fill="x")
        body = self._body(pady=20)

        # Progress bar
        self._pbar = ctk.CTkProgressBar(body,
                                        variable=self.v_progress,
                                        progress_color=C["accent"],
                                        fg_color=C["card"],
                                        height=16,
                                        corner_radius=8)
        self._pbar.pack(fill="x", pady=(0, 8))
        self._pbar.set(0)

        ctk.CTkLabel(body, textvariable=self.v_prog_msg,
                     font=ctk.CTkFont("Segoe UI", 10),
                     text_color=C["accent2"]).pack()

        # Log dosyası — AppData'ya yazılır, kurulum bitince Notepad açar
        import os, datetime
        log_dir = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "BeatDrop Studio")
        os.makedirs(log_dir, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self._log_file_path = os.path.join(log_dir, f"install_{ts}.log")
        with open(self._log_file_path, "w", encoding="utf-8") as f:
            f.write(f"BeatDrop Studio - Kurulum Logu\n")
            f.write(f"Tarih: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")

        threading.Thread(target=self._run_install, daemon=True).start()

    def _log_line(self, msg: str):
        """Log satırını diske yazar (Notepad için)."""
        try:
            with open(self._log_file_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        except Exception:
            pass  # log yazma hatası kurulumu engellemesin

    def _progress_cb(self, pct: int, msg: str):
        self.after(0, lambda: self.v_progress.set(pct / 100))
        self.after(0, lambda: self.v_prog_msg.set(msg))
        self._log_line(f"[{pct:3d}%] {msg}")

    def _run_install(self):
        if not CORE_OK:
            self._log_line(f"[HATA] Core yuklenemedui: {_CORE_ERR}")
            self.after(0, lambda: self._screen_done(False, [f"Core yuklenemedi: {_CORE_ERR}"], []))
            return
        result = run_installation(
            install_premiere  = self.v_premiere.get(),
            install_davinci   = self.v_davinci.get(),
            install_ai        = self.v_ai.get(),
            detected_programs = self.detected,
            cb                = self._progress_cb,
        )
        # Hata ve uyarıları log dosyasına yaz
        self._log_line("\n" + "=" * 60)
        if result.get("errors"):
            self._log_line("[HATALAR]")
            for e in result["errors"]:
                self._log_line(f"  - {e}")
        if result.get("warnings"):
            self._log_line("[UYARILAR]")
            for w in result["warnings"]:
                self._log_line(f"  - {w}")
        status = "BASARILI" if result["success"] else "HATAYLA TAMAMLANDI"
        self._log_line(f"\nSonuc: {status}")
        self._log_line(f"Log dosyasi: {self._log_file_path}\n")

        self.after(0, lambda: self._screen_done(
            result["success"],
            result.get("errors", []),
            result.get("warnings", []),
        ))

    # ════════════════════════════════════════════════════════════════════
    # EKRAN 5 — Tamamlandı
    # ════════════════════════════════════════════════════════════════════
    def _screen_done(self, success: bool, errors: list, warnings: list):
        self._clear()
        if success:
            self._header("Kurulum Tamamlandi!", "BeatDrop Studio kullanima hazir")
        else:
            self._header("Kurulum Hatasi", "Bazi bilesenlerde sorun olustu — loga bakin")

        # Hata varsa Notepad'i OTOMATIK ac
        if not success and hasattr(self, "_log_file_path"):
            self.after(800, self._open_log)

        # Alt buton bari
        bar = ctk.CTkFrame(self.content, fg_color=C["surface"],
                           corner_radius=0, height=62)
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        ctk.CTkFrame(bar, fg_color=C["border"],
                     corner_radius=0, height=1).pack(fill="x")
        btn_row = ctk.CTkFrame(bar, fg_color=C["surface"], corner_radius=0)
        btn_row.pack(side="right", padx=20, pady=12)

        ctk.CTkButton(btn_row, text="Kapat", command=self.destroy,
                      width=100, height=36,
                      fg_color=C["card"], hover_color=C["border"],
                      text_color=C["sub"],
                      font=ctk.CTkFont("Segoe UI", 11),
                      corner_radius=8).pack(side="left", padx=(0, 8))

        # Her durumda "Log Dosyasini Ac" butonu
        if hasattr(self, "_log_file_path"):
            ctk.CTkButton(btn_row, text="  Log Dosyasini Ac",
                          command=self._open_log,
                          width=160, height=36,
                          fg_color=C["card"], hover_color=C["surface2"],
                          text_color=C["sub"],
                          font=ctk.CTkFont("Segoe UI", 11),
                          corner_radius=8).pack(side="left", padx=(0, 8))

        if success:
            ctk.CTkButton(btn_row, text="Backend'i Baslat",
                          command=self._start_backend,
                          width=170, height=36,
                          fg_color="#15803d", hover_color=C["success"],
                          text_color=C["text"],
                          font=ctk.CTkFont("Segoe UI", 11, "bold"),
                          corner_radius=8).pack(side="left")

        body = self._body(pady=16)

        # Sonuç ikonu
        icon_color = C["success"] if success else C["danger"]
        icon_text  = "✅" if success else "❌"
        result_msg = "Kurulum başarıyla tamamlandı!" if success else "Kurulum hatalarla tamamlandı"

        result_card = self._card(body)
        result_card.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(result_card,
                     text=f"{icon_text}  {result_msg}",
                     font=ctk.CTkFont("Segoe UI", 14, "bold"),
                     text_color=icon_color).pack(pady=14)

        if success:
            steps_card = self._card(body)
            steps_card.pack(fill="x", pady=4)
            for step in [
                "1.  Premiere: Window → Extensions → BeatDrop Studio",
                "2.  DaVinci: Workspace → Scripts → BeatDropStudio",
                "3.  Backend sunucu otomatik başlayacak",
                "4.  assets/sfx/ klasörüne SFX WAV dosyalarınızı ekleyin",
            ]:
                ctk.CTkLabel(steps_card, text=f"  {step}",
                             font=ctk.CTkFont("Segoe UI", 10),
                             text_color=C["sub"],
                             anchor="w").pack(anchor="w", padx=16, pady=3)
            ctk.CTkLabel(steps_card, text="").pack(pady=2)  # boşluk

        for err in errors:
            ec = self._card(body)
            ec.pack(fill="x", pady=2)
            ctk.CTkLabel(ec, text=f"  ✗  {err}",
                         font=ctk.CTkFont("Segoe UI", 10),
                         text_color=C["danger"],
                         anchor="w").pack(anchor="w", padx=16, pady=8)

        for wrn in warnings:
            wc = self._card(body)
            wc.pack(fill="x", pady=2)
            ctk.CTkLabel(wc, text=f"  ⚠  {wrn}",
                         font=ctk.CTkFont("Segoe UI", 10),
                         text_color=C["warning"],
                         anchor="w").pack(anchor="w", padx=16, pady=8)

    def _start_backend(self):
        import subprocess, os
        # AppData'daki venv'i kullan (kurulum burada yapıldı)
        appdata = os.getenv("APPDATA", os.path.expanduser("~"))
        venv_dir = Path(appdata) / "BeatDrop Studio" / "venv"
        py = (venv_dir / "Scripts" / "python.exe") if IS_WINDOWS \
             else (venv_dir / "bin" / "python")
        backend = BASE_PATH / "backend"
        try:
            flags = subprocess.CREATE_NEW_CONSOLE if IS_WINDOWS else 0
            subprocess.Popen(
                [str(py), "-m", "uvicorn", "main:app",
                 "--host", "127.0.0.1", "--port", "8765"],
                cwd=str(backend), creationflags=flags)
            messagebox.showinfo(
                "Baslatildi",
                "Backend sunucu baslatildi!\n"
                "Swagger UI: http://127.0.0.1:8765/docs")
        except Exception as e:
            messagebox.showerror("Hata", f"Sunucu baslatılamadi:\n{e}")

    def _open_log(self):
        """Log dosyasini Notepad ile acar."""
        try:
            if not hasattr(self, "_log_file_path"):
                return
            import subprocess, os
            if IS_WINDOWS:
                subprocess.Popen(["notepad.exe", self._log_file_path])
            else:
                subprocess.Popen(["open", "-t", self._log_file_path])
        except Exception:
            pass


# ── Giriş Noktası ─────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = BeatDropInstaller()
    app.mainloop()
