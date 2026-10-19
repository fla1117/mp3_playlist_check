"""Theme, styles, IME composition helpers, and formatting utilities for GUI."""
import json
import os
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional

from src.config import SETTINGS_PATH

BG_COLOR = "#f4f5f8"
CARD_BG = "#ffffff"
PRIMARY_COLOR = "#3b82f6"
PRIMARY_ACTIVE = "#2563eb"
TEXT_COLOR = "#1f2937"
DIM_TEXT = "#6b7280"


def get_entry_text_with_ime(entry: tk.Entry) -> str:
    """Read entry text and append any in-flight Windows IME composition characters if uncommitted."""
    text = entry.get()
    if os.name == "nt":
        try:
            import ctypes
            hwnd = entry.winfo_id()
            if hwnd:
                imm32 = ctypes.windll.imm32
                himc = imm32.ImmGetContext(hwnd)
                if himc:
                    # 0x0008: GCS_COMPSTR (IME composition string)
                    size = imm32.ImmGetCompositionStringW(himc, 0x0008, None, 0)
                    if size > 0:
                        buf = ctypes.create_unicode_buffer(size // 2 + 1)
                        imm32.ImmGetCompositionStringW(himc, 0x0008, buf, size + 2)
                        comp_str = buf.value
                        if comp_str and not text.endswith(comp_str):
                            text += comp_str
                    imm32.ImmReleaseContext(hwnd, himc)
        except Exception:
            pass
    return text


def load_settings() -> Dict[str, Any]:
    """Load settings from settings.json."""
    default_dir = "F:\\2. 음악\\Music\\3차 편집" if Path("F:\\2. 음악\\Music\\3차 편집").exists() else ""
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if not data.get("last_scanned_dir") and default_dir:
                    data["last_scanned_dir"] = default_dir
                return data
        except Exception:
            pass
    return {"last_scanned_dir": default_dir}


def save_settings(settings: Dict[str, Any]) -> None:
    """Save settings to settings.json."""
    try:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def format_duration(seconds: float) -> str:
    """Format seconds into MM:SS."""
    sec = int(round(seconds or 0))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def format_cover_art(track: Dict[str, Any]) -> str:
    """Format cover art string."""
    has_cover = track.get("has_cover_art", 0)
    w = track.get("cover_width")
    h = track.get("cover_height")
    mime = track.get("cover_mime") or ""
    sub_fmt = mime.split("/")[-1].upper() if "/" in mime else mime.upper()
    if has_cover == 1:
        if w and h:
            return f"있음 ({w}x{h} {sub_fmt})"
        return "있음 (내장 태그)"
    elif has_cover == 2:
        return "있음 (폴더 외부 이미지)"
    return "없음"


def open_in_explorer(file_path: Optional[str]) -> None:
    """Open Windows Explorer with file selected."""
    if not file_path:
        return
    p = Path(file_path).resolve()
    if p.exists():
        subprocess.run(["explorer", f"/select,{p}"])
    else:
        messagebox.showwarning("파일 없음", f"파일을 찾을 수 없습니다:\n{p}")


class ThemeMixin:
    """Mixin for GUI styling and theme initialization."""

    bg_color: str
    card_bg: str
    primary_color: str
    primary_active: str
    text_color: str
    dim_text: str
    style: ttk.Style

    def _init_styles(self) -> None:
        """Configure modern clean ttk styling."""
        self.style = ttk.Style(self)  # type: ignore[arg-type]
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Color palette
        self.bg_color = BG_COLOR
        self.card_bg = CARD_BG
        self.primary_color = PRIMARY_COLOR
        self.primary_active = PRIMARY_ACTIVE
        self.text_color = TEXT_COLOR
        self.dim_text = DIM_TEXT

        self.configure(bg=self.bg_color)  # type: ignore[attr-defined]

        self.style.configure(".", background=self.bg_color, foreground=self.text_color, font=("Malgun Gothic", 9))
        self.style.configure("TNotebook", background=self.bg_color, tabmargins=[6, 6, 6, 0])
        self.style.configure(
            "TNotebook.Tab",
            padding=[16, 8],
            font=("Malgun Gothic", 10, "bold"),
            background="#e5e7eb",
            foreground="#374151",
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", self.card_bg)],
            foreground=[("selected", self.primary_color)],
        )

        self.style.configure("Card.TFrame", background=self.card_bg, relief="flat")
        self.style.configure("Header.TLabel", font=("Malgun Gothic", 11, "bold"), background=self.card_bg)
        self.style.configure("Dim.TLabel", foreground=self.dim_text, background=self.card_bg)

        # Treeview styling
        self.style.configure(
            "Treeview",
            background=self.card_bg,
            foreground=self.text_color,
            rowheight=26,
            fieldbackground=self.card_bg,
            font=("Malgun Gothic", 9),
        )
        self.style.configure(
            "Treeview.Heading",
            font=("Malgun Gothic", 9, "bold"),
            background="#e5e7eb",
            foreground="#111827",
            padding=[4, 4],
        )
        self.style.map("Treeview", background=[("selected", "#dbeafe")], foreground=[("selected", "#1e40af")])
