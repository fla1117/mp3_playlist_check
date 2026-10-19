"""Native Windows Desktop GUI for mp3_playlist_check using tkinter/ttk."""
import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path

# Ensure project root is in sys.path for direct invocation from any directory
PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_DIR))

import csv
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Set, Tuple

from src.config import DEFAULT_DB_PATH, SETTINGS_PATH
from src.db.repository import Repository
from src.matcher.normalizer import normalize_text
from src.matcher.scorer import MatcherEngine, MatchResult, MatchStatus
from src.scanner.cover_manager import embed_cover_art, fetch_cover_art_auto
from src.scanner.file_walker import ScanSummary, scan_directory, sync_single_file
from src.scanner.tag_normalizer import apply_fallback_tags_to_file, rename_file_standard
from src.youtube.extractor import YouTubeExtractor, YouTubeTrackInfo


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


class MusicCheckerGUI(tk.Tk):
    """Main Application Window."""

    def __init__(self, db_path: Optional[Path | str] = None):
        super().__init__()
        self.title("로컬 음원 기반 YouTube 보유 곡 판별기 (mp3_playlist_check)")
        self.geometry("1120x760")
        self.minsize(920, 620)

        self._search_after_id: Optional[str] = None
        self._audit_row_meta: Dict[str, Dict[str, Any]] = {}
        self._audit_checked_items: Set[str] = set()
        self.repo = Repository(db_path or DEFAULT_DB_PATH)
        self.engine = MatcherEngine(self.repo)
        self.extractor = YouTubeExtractor(self.repo)
        self.settings = load_settings()

        self._init_styles()
        self._build_ui()

    def _init_styles(self) -> None:
        """Configure modern clean ttk styling."""
        self.style = ttk.Style(self)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Color palette
        self.bg_color = "#f4f5f8"
        self.card_bg = "#ffffff"
        self.primary_color = "#3b82f6"
        self.primary_active = "#2563eb"
        self.text_color = "#1f2937"
        self.dim_text = "#6b7280"

        self.configure(bg=self.bg_color)

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

    def _build_ui(self) -> None:
        """Build tabbed interface."""
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # Tab 1: YouTube Matcher
        self.tab_matcher = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_matcher, text=" 🔍 YouTube 보유 여부 판별 ")
        self._build_matcher_tab()

        # Tab 2: Local Scanner & Library Search
        self.tab_scanner = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_scanner, text=" 📁 음원 폴더 스캔 & 라이브러리 ")
        self._build_scanner_tab()

        # Tab 3: Quality Audit & Stats (FR-10)
        self.tab_audit = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_audit, text=" 📊 라이브러리 품질 감사 & 통계 ")
        self._build_audit_tab()

        # Tab 4: Artist Aliases Management
        self.tab_alias = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_alias, text=" 👥 한/영 아티스트 별칭 사전 ")
        self._build_alias_tab()

    # --------------------------------------------------------------------------
    # TAB 1: YouTube Matcher
    # --------------------------------------------------------------------------
    def _build_matcher_tab(self) -> None:
        # Top URL Input Bar
        top_frame = ttk.Frame(self.tab_matcher, style="Card.TFrame", padding=12)
        top_frame.pack(fill="x", padx=8, pady=(8, 4))

        lbl = ttk.Label(top_frame, text="YouTube URL:", font=("Malgun Gothic", 10, "bold"), background=self.card_bg)
        lbl.pack(side="left", padx=(0, 8))

        self.yt_url_var = tk.StringVar()
        self.yt_url_entry = tk.Entry(
            top_frame,
            textvariable=self.yt_url_var,
            font=("Malgun Gothic", 10),
            relief="solid",
            bd=1,
            bg="white",
            fg="#111827",
            insertbackground="#111827",
        )
        self.yt_url_entry.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=3)
        self.yt_url_entry.bind("<Return>", lambda e: self._start_check_youtube())

        btn_paste = tk.Button(
            top_frame,
            text="📋 붙여넣기",
            bg="#e5e7eb",
            relief="flat",
            command=self._paste_clipboard_to_url,
            padx=8,
            pady=4,
        )
        btn_paste.pack(side="left", padx=(0, 6))

        self.btn_check = tk.Button(
            top_frame,
            text="🔍 보유 여부 판별",
            bg="#2563eb",
            fg="white",
            activebackground="#1d4ed8",
            activeforeground="white",
            font=("Malgun Gothic", 9, "bold"),
            relief="flat",
            command=self._start_check_youtube,
            padx=12,
            pady=4,
            cursor="hand2",
        )
        self.btn_check.pack(side="left")

        # Progress / Status Banner
        self.match_status_bar = ttk.Frame(self.tab_matcher, padding=[8, 2])
        self.match_status_bar.pack(fill="x", padx=8)

        self.match_progress = ttk.Progressbar(self.match_status_bar, mode="indeterminate", length=200)
        self.match_status_lbl = ttk.Label(self.match_status_bar, text="URL을 입력하고 판별 버튼을 누르세요.")
        self.match_status_lbl.pack(side="left")

        # Main Results Container (Switchable between Single Video & Playlist Table)
        self.results_container = ttk.Frame(self.tab_matcher)
        self.results_container.pack(fill="both", expand=True, padx=8, pady=4)

        # Single Video Result Card
        self.single_card = ttk.Frame(self.results_container, style="Card.TFrame", padding=16)
        self.single_card.pack(fill="both", expand=True)

        self.badge_lbl = tk.Label(
            self.single_card,
            text="대기 중",
            font=("Malgun Gothic", 14, "bold"),
            bg="#9ca3af",
            fg="white",
            padx=14,
            pady=6,
        )
        self.badge_lbl.pack(anchor="w", pady=(0, 10))

        self.yt_meta_lbl = ttk.Label(self.single_card, text="", style="Header.TLabel")
        self.yt_meta_lbl.pack(anchor="w", pady=(0, 4))

        self.score_detail_lbl = ttk.Label(self.single_card, text="", style="Dim.TLabel")
        self.score_detail_lbl.pack(anchor="w", pady=(0, 8))

        self.reason_lbl = ttk.Label(self.single_card, text="", font=("Malgun Gothic", 9, "italic"), foreground="#b45309", background=self.card_bg)
        self.reason_lbl.pack(anchor="w", pady=(0, 12))

        # Local Track Details Frame
        self.local_info_frame = tk.LabelFrame(
            self.single_card,
            text=" 매칭된 로컬 음원 정보 ",
            bg=self.card_bg,
            fg="#1e40af",
            font=("Malgun Gothic", 10, "bold"),
            padx=12,
            pady=8,
        )
        self.local_info_frame.pack(fill="x", expand=False, pady=(0, 12))

        self.loc_title_lbl = ttk.Label(self.local_info_frame, text="• 곡명: -", background=self.card_bg)
        self.loc_title_lbl.pack(anchor="w", pady=2)
        self.loc_artist_lbl = ttk.Label(self.local_info_frame, text="• 아티스트: -", background=self.card_bg)
        self.loc_artist_lbl.pack(anchor="w", pady=2)
        self.loc_album_lbl = ttk.Label(self.local_info_frame, text="• 앨범: -", background=self.card_bg)
        self.loc_album_lbl.pack(anchor="w", pady=2)
        self.loc_spec_lbl = ttk.Label(self.local_info_frame, text="• 음원 스펙: -", background=self.card_bg)
        self.loc_spec_lbl.pack(anchor="w", pady=2)
        self.loc_cover_lbl = ttk.Label(self.local_info_frame, text="• 썸네일: -", background=self.card_bg)
        self.loc_cover_lbl.pack(anchor="w", pady=2)
        self.loc_path_lbl = ttk.Label(self.local_info_frame, text="• 파일 경로: -", font=("Malgun Gothic", 8), foreground="#4b5563", background=self.card_bg)
        self.loc_path_lbl.pack(anchor="w", pady=2)

        # Action Buttons
        self.single_actions_frame = ttk.Frame(self.single_card, style="Card.TFrame")
        self.single_actions_frame.pack(anchor="w", pady=6)

        self.current_matched_path: Optional[str] = None
        self.btn_open_folder = tk.Button(
            self.single_actions_frame,
            text="📂 탐색기에서 위치 열기",
            bg="#f3f4f6",
            command=lambda: open_in_explorer(self.current_matched_path),
            padx=10,
            pady=4,
        )
        self.btn_open_folder.pack(side="left", padx=(0, 8))

        self.btn_copy_path = tk.Button(
            self.single_actions_frame,
            text="📋 파일 경로 복사",
            bg="#f3f4f6",
            command=self._copy_matched_path,
            padx=10,
            pady=4,
        )
        self.btn_copy_path.pack(side="left")

        # Multi-Track / Playlist Results Area (Hidden by default, shown when multi-track)
        self.multi_frame = ttk.Frame(self.results_container)

        self.playlist_summary_lbl = ttk.Label(self.multi_frame, text="", font=("Malgun Gothic", 10, "bold"))
        self.playlist_summary_lbl.pack(anchor="w", pady=(0, 6))

        # Filter bar for playlist
        multi_filter_bar = ttk.Frame(self.multi_frame)
        multi_filter_bar.pack(fill="x", pady=(0, 6))

        ttk.Label(multi_filter_bar, text="결과 필터: ").pack(side="left")
        self.playlist_filter_var = tk.StringVar(value="전체")
        for val in ["전체", "보유만", "유사만", "미보유만"]:
            rb = ttk.Radiobutton(
                multi_filter_bar,
                text=val,
                value=val,
                variable=self.playlist_filter_var,
                command=self._apply_playlist_filter,
            )
            rb.pack(side="left", padx=4)

        # Treeview container frame for playlist table
        pl_table_frame = ttk.Frame(self.multi_frame)
        pl_table_frame.pack(side="top", fill="both", expand=True)

        # Treeview for playlist
        cols = ("num", "status", "yt_title", "duration", "local_match", "score", "path", "reason")
        self.pl_tree = ttk.Treeview(pl_table_frame, columns=cols, show="headings", selectmode="browse")
        self.pl_tree.heading("num", text="#")
        self.pl_tree.heading("status", text="판별 상태")
        self.pl_tree.heading("yt_title", text="YouTube 제목")
        self.pl_tree.heading("duration", text="영상 길이")
        self.pl_tree.heading("local_match", text="로컬 매칭 음원")
        self.pl_tree.heading("score", text="일치율")
        self.pl_tree.heading("path", text="로컬 파일 경로")
        self.pl_tree.heading("reason", text="판별 사유/비고")

        self.pl_tree.column("num", width=35, anchor="center")
        self.pl_tree.column("status", width=85, anchor="center")
        self.pl_tree.column("yt_title", width=240)
        self.pl_tree.column("duration", width=70, anchor="center")
        self.pl_tree.column("local_match", width=200)
        self.pl_tree.column("score", width=60, anchor="e")
        self.pl_tree.column("path", width=250)
        self.pl_tree.column("reason", width=180)

        pl_scrollbar_y = ttk.Scrollbar(pl_table_frame, orient="vertical", command=self.pl_tree.yview)
        self.pl_tree.configure(yscrollcommand=pl_scrollbar_y.set)
        self.pl_tree.pack(side="left", fill="both", expand=True)
        pl_scrollbar_y.pack(side="right", fill="y")

        self.pl_tree.bind("<Double-1>", self._on_playlist_tree_double_click)

        # Multi-Track Action Bar
        multi_actions = ttk.Frame(self.multi_frame, padding=6)
        multi_actions.pack(side="bottom", fill="x", pady=4)
        tk.Button(
            multi_actions,
            text="📂 선택 곡 탐색기 열기",
            bg="#f3f4f6",
            command=self._open_selected_playlist_file,
            padx=10,
            pady=4,
        ).pack(side="left", padx=3)
        tk.Button(
            multi_actions,
            text="📋 선택 곡 경로 복사",
            bg="#f3f4f6",
            command=self._copy_selected_playlist_path,
            padx=10,
            pady=4,
        ).pack(side="left", padx=3)
        tk.Button(
            multi_actions,
            text="📋 미보유 곡 목록 복사",
            bg="#fef3c7",
            fg="#92400e",
            command=self._copy_missing_playlist_tracks,
            padx=10,
            pady=4,
        ).pack(side="left", padx=3)
        tk.Button(
            multi_actions,
            text="📥 결과 CSV 저장...",
            bg="#f3f4f6",
            command=self._export_playlist_results_csv,
            padx=10,
            pady=4,
        ).pack(side="left", padx=3)

        self.cached_playlist_results: List[Dict[str, Any]] = []

    def _paste_clipboard_to_url(self) -> None:
        try:
            val = self.clipboard_get().strip()
            if val:
                self.yt_url_var.set(val)
        except Exception:
            pass

    def _copy_matched_path(self) -> None:
        if self.current_matched_path:
            self.clipboard_clear()
            self.clipboard_append(self.current_matched_path)
            messagebox.showinfo("복사 완료", "파일 경로가 클립보드에 복사되었습니다.")

    def _start_check_youtube(self) -> None:
        url = self.yt_url_var.get().strip()
        if not url:
            messagebox.showwarning("입력 필요", "YouTube URL을 입력해 주세요.")
            return

        self.btn_check.config(state="disabled")
        self.match_progress.pack(side="right", padx=10)
        self.match_progress.start(10)
        self.match_status_lbl.config(text=f"YouTube 메타데이터 수집 중... ({url[:45]}...)")

        threading.Thread(target=self._worker_check_youtube, args=(url,), daemon=True).start()

    def _worker_check_youtube(self, url: str) -> None:
        try:
            result = self.extractor.extract(url)
            self.after(0, self._on_youtube_extracted, result)
        except Exception as e:
            self.after(0, self._on_youtube_error, str(e))

    def _on_youtube_error(self, err_msg: str) -> None:
        self.match_progress.stop()
        self.match_progress.pack_forget()
        self.btn_check.config(state="normal")
        self.match_status_lbl.config(text="오류 발생")
        messagebox.showerror("YouTube 조회 실패", f"YouTube 메타데이터를 수집하지 못했습니다:\n{err_msg}")

    def _on_youtube_extracted(self, result: Any) -> None:
        self.match_progress.stop()
        self.match_progress.pack_forget()
        self.btn_check.config(state="normal")

        if not result.tracks:
            self.match_status_lbl.config(text="트랙을 찾을 수 없습니다.")
            return

        # Single video mode
        if len(result.tracks) == 1 and not result.is_playlist and not result.tracks[0].is_chapter:
            self.multi_frame.pack_forget()
            self.single_card.pack(fill="both", expand=True)

            track_info = result.tracks[0]
            m = self.engine.match(
                raw_title=track_info.raw_title,
                uploader=track_info.uploader,
                yt_artist=track_info.yt_artist,
                yt_track=track_info.yt_track,
                duration_sec=track_info.duration_sec,
            )
            self._render_single_match(track_info, m)
            self.match_status_lbl.config(text=f"판별 완료: {m.status.value} (일치율 {m.score:.0f}%)")

        # Playlist / Chapter Compilation Mode
        else:
            self.single_card.pack_forget()
            self.multi_frame.pack(fill="both", expand=True)
            self._render_multi_match(result)
            self.match_status_lbl.config(text=f"총 {len(result.tracks)}곡 분석 완료")

    def _render_single_match(self, yt_info: YouTubeTrackInfo, m: MatchResult) -> None:
        dur_str = format_duration(yt_info.duration_sec)
        self.yt_meta_lbl.config(text=f"영상: {yt_info.raw_title}  |  채널: {yt_info.uploader}  |  길이: {dur_str}")

        detail_text = (
            f"종합 점수: {m.score:.1f}%   (곡명: {m.title_score:.1f}% | 아티스트: {m.artist_score:.1f}% | "
            f"재생시간: {m.duration_score:.1f}% | 버전페널티: -{m.version_penalty:.1f}점)"
        )
        self.score_detail_lbl.config(text=detail_text)
        self.reason_lbl.config(text=f"사유: {m.reason}" if m.reason else "")

        if m.status == MatchStatus.EXACT_MATCH:
            self.badge_lbl.config(text=f"✅ 보유 중 (EXACT_MATCH | {m.score:.0f}%)", bg="#16a34a", fg="white")
        elif m.status == MatchStatus.PARTIAL_MATCH:
            self.badge_lbl.config(text=f"⚠️ 유사/버전 상이 (PARTIAL_MATCH | {m.score:.0f}%)", bg="#d97706", fg="white")
        else:
            self.badge_lbl.config(text=f"❌ 미보유 (NOT_FOUND | {m.score:.0f}%)", bg="#dc2626", fg="white")

        mt = m.matched_track
        if mt:
            self.current_matched_path = mt.get("file_path")
            self.loc_title_lbl.config(text=f"• 곡명: {mt.get('title') or '-'}")
            self.loc_artist_lbl.config(text=f"• 아티스트: {mt.get('artist') or '-'}")
            self.loc_album_lbl.config(
                text=f"• 앨범: {mt.get('album') or '알 수 없음'} ({mt.get('release_year') or '연도미상'}) - Track #{mt.get('track_number') or '01'}"
            )
            loc_dur = mt.get("duration_sec", 0.0)
            diff_sec = int(round(abs(yt_info.duration_sec - loc_dur)))
            spec_str = (
                f"{mt.get('file_ext', '').upper()} | {mt.get('bitrate_kbps', 0)} kbps | "
                f"{format_duration(loc_dur)} (영상과 {diff_sec}초 차이)"
            )
            self.loc_spec_lbl.config(text=f"• 음원 스펙: {spec_str}")
            self.loc_cover_lbl.config(text=f"• 썸네일(커버아트): {format_cover_art(mt)}")
            self.loc_path_lbl.config(text=f"• 파일 경로: {self.current_matched_path}")
            self.btn_open_folder.config(state="normal")
            self.btn_copy_path.config(state="normal")
        else:
            self.current_matched_path = None
            self.loc_title_lbl.config(text="• 곡명: -")
            self.loc_artist_lbl.config(text="• 아티스트: -")
            self.loc_album_lbl.config(text="• 앨범: -")
            self.loc_spec_lbl.config(text="• 음원 스펙: -")
            self.loc_cover_lbl.config(text="• 썸네일: -")
            self.loc_path_lbl.config(text="• 파일 경로: 로컬 라이브러리에 일치하는 파일이 없습니다.")
            self.btn_open_folder.config(state="disabled")
            self.btn_copy_path.config(state="disabled")

    def _render_multi_match(self, result: Any) -> None:
        self.cached_playlist_results = []
        exact_cnt = 0
        partial_cnt = 0
        not_found_cnt = 0

        for i, t in enumerate(result.tracks, 1):
            m = self.engine.match(
                raw_title=t.raw_title,
                uploader=t.uploader,
                yt_artist=t.yt_artist,
                yt_track=t.yt_track,
                duration_sec=t.duration_sec,
            )
            if m.status == MatchStatus.EXACT_MATCH:
                exact_cnt += 1
                status_str = "✅ 보유"
                loc_name = f"{m.matched_track.get('artist')} - {m.matched_track.get('title')}"
                loc_path = m.matched_track.get("file_path", "")
            elif m.status == MatchStatus.PARTIAL_MATCH:
                partial_cnt += 1
                status_str = "⚠️ 유사"
                loc_name = f"{m.matched_track.get('artist')} - {m.matched_track.get('title')}"
                loc_path = m.matched_track.get("file_path", "")
            else:
                not_found_cnt += 1
                status_str = "❌ 미보유"
                loc_name = "-"
                loc_path = "-"

            self.cached_playlist_results.append(
                {
                    "num": i,
                    "status_code": m.status,
                    "status_str": status_str,
                    "yt_title": t.raw_title,
                    "duration": format_duration(t.duration_sec),
                    "local_match": loc_name,
                    "score": f"{m.score:.0f}%",
                    "path": loc_path,
                    "reason": m.reason or "",
                }
            )

        total_cnt = len(result.tracks)
        pct = (exact_cnt / total_cnt * 100) if total_cnt else 0
        self.playlist_summary_lbl.config(
            text=f"📋 {result.playlist_title or '모음집 영상'} 결과: 총 {total_cnt}곡  |  "
            f"✅ 보유 {exact_cnt}곡 ({pct:.1f}%)  |  ⚠️ 유사 {partial_cnt}곡  |  ❌ 미보유 {not_found_cnt}곡"
        )
        self._apply_playlist_filter()

    def _apply_playlist_filter(self) -> None:
        for item in self.pl_tree.get_children():
            self.pl_tree.delete(item)

        flt = self.playlist_filter_var.get()
        for r in self.cached_playlist_results:
            if flt == "보유만" and r["status_code"] != MatchStatus.EXACT_MATCH:
                continue
            if flt == "유사만" and r["status_code"] != MatchStatus.PARTIAL_MATCH:
                continue
            if flt == "미보유만" and r["status_code"] != MatchStatus.NOT_FOUND:
                continue

            self.pl_tree.insert(
                "",
                "end",
                values=(
                    r["num"],
                    r["status_str"],
                    r["yt_title"],
                    r["duration"],
                    r["local_match"],
                    r["score"],
                    r["path"],
                    r["reason"],
                ),
            )

    def _get_selected_playlist_path(self) -> Optional[str]:
        sel = self.pl_tree.selection()
        if not sel:
            return None
        vals = self.pl_tree.item(sel[0], "values")
        if vals and len(vals) >= 7 and vals[6] != "-":
            return vals[6]
        return None

    def _on_playlist_tree_double_click(self, event: Any) -> None:
        path = self._get_selected_playlist_path()
        if path:
            open_in_explorer(path)

    def _open_selected_playlist_file(self) -> None:
        path = self._get_selected_playlist_path()
        if path:
            open_in_explorer(path)
        else:
            messagebox.showinfo("선택 필요", "로컬 매칭된 곡을 테이블에서 선택해 주세요.")

    def _copy_selected_playlist_path(self) -> None:
        path = self._get_selected_playlist_path()
        if path:
            self.clipboard_clear()
            self.clipboard_append(path)
            messagebox.showinfo("복사 완료", "파일 경로가 클립보드에 복사되었습니다.")
        else:
            messagebox.showinfo("선택 필요", "로컬 매칭된 곡을 테이블에서 선택해 주세요.")

    def _copy_missing_playlist_tracks(self) -> None:
        if not self.cached_playlist_results:
            messagebox.showinfo("안내", "복사할 판별 결과가 없습니다.")
            return

        missing_tracks = [
            r for r in self.cached_playlist_results
            if r["status_code"] == MatchStatus.NOT_FOUND
        ]
        if not missing_tracks:
            messagebox.showinfo("알림", "미보유 곡이 없습니다! 모든 곡을 보유 중입니다.")
            return

        lines = [f"[미보유 곡 목록 - 총 {len(missing_tracks)}곡]"]
        for r in missing_tracks:
            lines.append(f"{r['num']}. {r['yt_title']} ({r['duration']})")

        text_to_copy = "\n".join(lines)
        self.clipboard_clear()
        self.clipboard_append(text_to_copy)
        messagebox.showinfo("복사 완료", f"미보유 곡 {len(missing_tracks)}개의 목록이 클립보드에 복사되었습니다.")

    def _export_playlist_results_csv(self) -> None:
        if not self.cached_playlist_results:
            messagebox.showinfo("안내", "내보낼 판별 결과가 없습니다.")
            return

        fpath = filedialog.asksaveasfilename(
            title="판별 결과 CSV 저장",
            defaultextension=".csv",
            filetypes=[("CSV 파일 (Excel 호환)", "*.csv"), ("텍스트 파일", "*.txt")],
            initialfile="youtube_match_results.csv",
        )
        if not fpath:
            return

        try:
            with open(fpath, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["순번", "판별 상태", "YouTube 제목", "영상 길이", "로컬 매칭 음원", "일치율", "로컬 파일 경로", "판별 사유/비고"])
                for r in self.cached_playlist_results:
                    writer.writerow([
                        r.get("num", ""),
                        r.get("status_str", ""),
                        r.get("yt_title", ""),
                        r.get("duration", ""),
                        r.get("local_match", ""),
                        r.get("score", ""),
                        r.get("path", ""),
                        r.get("reason", ""),
                    ])
            messagebox.showinfo("저장 완료", f"결과가 성공적으로 저장되었습니다:\n{fpath}")
        except Exception as e:
            messagebox.showerror("저장 실패", f"CSV 파일 저장 중 오류가 발생했습니다:\n{e}")

    # --------------------------------------------------------------------------
    # TAB 2: Local Scanner & Library Search
    # --------------------------------------------------------------------------
    def _build_scanner_tab(self) -> None:
        # Top Folder Picker Bar
        top_frame = ttk.Frame(self.tab_scanner, style="Card.TFrame", padding=12)
        top_frame.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(top_frame, text="음원 폴더 경로:", font=("Malgun Gothic", 10, "bold"), background=self.card_bg).pack(
            side="left", padx=(0, 6)
        )

        self.scan_dir_var = tk.StringVar(value=self.settings.get("last_scanned_dir", ""))
        self.scan_dir_entry = tk.Entry(
            top_frame,
            textvariable=self.scan_dir_var,
            font=("Malgun Gothic", 10),
            relief="solid",
            bd=1,
            bg="white",
            fg="#111827",
            insertbackground="#111827",
        )
        self.scan_dir_entry.pack(side="left", fill="x", expand=True, padx=(0, 6), ipady=3)

        tk.Button(
            top_frame,
            text="📂 폴더 찾아보기...",
            bg="#e5e7eb",
            relief="flat",
            command=self._browse_scan_dir,
            padx=10,
            pady=4,
        ).pack(side="left", padx=(0, 8))

        self.btn_run_scan = tk.Button(
            top_frame,
            text="🚀 스캔 & 동기화 시작",
            bg="#16a34a",
            fg="white",
            activebackground="#15803d",
            activeforeground="white",
            font=("Malgun Gothic", 9, "bold"),
            relief="flat",
            command=self._start_scan_dir,
            padx=14,
            pady=4,
            cursor="hand2",
        )
        self.btn_run_scan.pack(side="left")

        # Scan Progress & Summary Banner
        self.scan_status_frame = ttk.Frame(self.tab_scanner, padding=[8, 4])
        self.scan_status_frame.pack(fill="x", padx=8)

        self.scan_progress_bar = ttk.Progressbar(self.scan_status_frame, orient="horizontal", mode="determinate")
        self.scan_progress_bar.pack(fill="x", pady=2)

        self.scan_status_lbl = ttk.Label(self.scan_status_frame, text="폴더를 선택하고 스캔 버튼을 누르세요.")
        self.scan_status_lbl.pack(anchor="w")

        self.scan_summary_banner = tk.Label(
            self.tab_scanner,
            text="",
            font=("Malgun Gothic", 9, "bold"),
            bg="#e0f2fe",
            fg="#0369a1",
            relief="flat",
            padx=8,
            pady=4,
        )

        # Library Live Search & Browser Header
        search_frame = ttk.Frame(self.tab_scanner, padding=[8, 4])
        search_frame.pack(fill="x", padx=8, pady=(4, 2))

        ttk.Label(search_frame, text="🔎 라이브러리 실시간 검색:", font=("Malgun Gothic", 10, "bold")).pack(side="left", padx=(0, 6))
        self.lib_search_var = tk.StringVar()
        self.lib_search_entry = tk.Entry(
            search_frame,
            textvariable=self.lib_search_var,
            width=32,
            font=("Malgun Gothic", 10),
            relief="solid",
            bd=1,
            bg="white",
            fg="#111827",
            insertbackground="#111827",
        )
        self.lib_search_entry.pack(side="left", padx=(0, 4), ipady=3)
        self.lib_search_entry.bind("<KeyRelease>", self._on_search_key_release)
        self.lib_search_entry.bind("<Return>", lambda e: self._filter_library_table())
        self.lib_search_entry.bind("<FocusOut>", lambda e: self._filter_library_table())

        tk.Button(
            search_frame,
            text="🔍 검색",
            bg="#f3f4f6",
            font=("Malgun Gothic", 9),
            command=self._filter_library_table,
            padx=8,
            pady=2,
        ).pack(side="left", padx=(0, 4))

        tk.Button(
            search_frame,
            text="✖ 초기화",
            bg="#f3f4f6",
            font=("Malgun Gothic", 9),
            command=self._clear_search,
            padx=8,
            pady=2,
        ).pack(side="left", padx=(0, 8))

        self.lib_count_lbl = ttk.Label(search_frame, text="총 0곡", foreground="#4b5563")
        self.lib_count_lbl.pack(side="left")

        tk.Button(search_frame, text="🔄 새로고침", bg="#f3f4f6", command=self._reload_library_table, padx=8, pady=2).pack(
            side="right"
        )

        # Library Table
        lib_table_frame = ttk.Frame(self.tab_scanner, padding=[8, 2])
        lib_table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        lib_cols = ("id", "ext", "artist", "title", "album", "duration", "bitrate", "cover", "path")
        self.lib_tree = ttk.Treeview(lib_table_frame, columns=lib_cols, show="headings", selectmode="browse")
        self.lib_tree.heading("id", text="ID")
        self.lib_tree.heading("ext", text="포맷")
        self.lib_tree.heading("artist", text="아티스트")
        self.lib_tree.heading("title", text="곡명")
        self.lib_tree.heading("album", text="앨범")
        self.lib_tree.heading("duration", text="재생시간")
        self.lib_tree.heading("bitrate", text="음질")
        self.lib_tree.heading("cover", text="커버아트")
        self.lib_tree.heading("path", text="파일 경로")

        self.lib_tree.column("id", width=40, anchor="center")
        self.lib_tree.column("ext", width=50, anchor="center")
        self.lib_tree.column("artist", width=140)
        self.lib_tree.column("title", width=220)
        self.lib_tree.column("album", width=180)
        self.lib_tree.column("duration", width=65, anchor="center")
        self.lib_tree.column("bitrate", width=70, anchor="center")
        self.lib_tree.column("cover", width=120)
        self.lib_tree.column("path", width=320)

        lib_scroll_y = ttk.Scrollbar(lib_table_frame, orient="vertical", command=self.lib_tree.yview)
        self.lib_tree.configure(yscrollcommand=lib_scroll_y.set)
        self.lib_tree.pack(side="left", fill="both", expand=True)
        lib_scroll_y.pack(side="right", fill="y")

        self.lib_tree.bind("<Double-1>", lambda e: open_in_explorer(self._get_selected_lib_path()))

        # Library Bottom Actions
        lib_actions = ttk.Frame(self.tab_scanner, padding=6)
        lib_actions.pack(fill="x", padx=8, pady=(0, 6))

        tk.Button(
            lib_actions,
            text="📂 탐색기에서 열기",
            bg="#f3f4f6",
            command=lambda: open_in_explorer(self._get_selected_lib_path()),
            padx=10,
            pady=4,
        ).pack(side="left", padx=4)

        tk.Button(
            lib_actions,
            text="📋 파일 경로 복사",
            bg="#f3f4f6",
            command=self._copy_selected_lib_path,
            padx=10,
            pady=4,
        ).pack(side="left", padx=4)

        self.all_library_tracks: List[Dict[str, Any]] = []
        self._reload_library_table()

    def _browse_scan_dir(self) -> None:
        initial = self.scan_dir_var.get() or "C:\\"
        d = filedialog.askdirectory(initialdir=initial, title="스캔할 음악 폴더 선택")
        if d:
            self.scan_dir_var.set(str(Path(d).resolve()))
            self.settings["last_scanned_dir"] = str(Path(d).resolve())
            save_settings(self.settings)

    def _start_scan_dir(self) -> None:
        dir_path = self.scan_dir_var.get().strip()
        if not dir_path or not Path(dir_path).exists():
            messagebox.showwarning("폴더 확인", f"유효한 폴더 경로를 선택해 주세요:\n{dir_path}")
            return

        self.settings["last_scanned_dir"] = dir_path
        save_settings(self.settings)

        self.btn_run_scan.config(state="disabled")
        self.scan_progress_bar["value"] = 0
        self.scan_status_lbl.config(text=f"음원 파일 탐색 및 스캔 시작: {dir_path}")
        self.scan_summary_banner.pack_forget()

        threading.Thread(target=self._worker_scan_dir, args=(dir_path,), daemon=True).start()

    def _worker_scan_dir(self, dir_path: str) -> None:
        try:
            def _prog(fname: str, cur: int, total: int):
                pct = (cur / total * 100) if total else 0
                self.after(0, self._update_scan_progress, fname, cur, total, pct)

            summary = scan_directory(dir_path, self.repo, progress_callback=_prog)
            self.after(0, self._on_scan_finished, summary)
        except Exception as e:
            self.after(0, self._on_scan_error, str(e))

    def _update_scan_progress(self, fname: str, cur: int, total: int, pct: float) -> None:
        self.scan_progress_bar["value"] = pct
        self.scan_status_lbl.config(text=f"스캔 중 ({cur}/{total} 파일) : {fname}")

    def _on_scan_finished(self, summary: ScanSummary) -> None:
        self.btn_run_scan.config(state="normal")
        self.scan_progress_bar["value"] = 100
        self.scan_status_lbl.config(text="✅ 스캔 및 동기화가 완료되었습니다.")

        banner_text = (
            f"스캔 결과: 총 {summary.total_files}개 파일 발견  |  신규 추가: {summary.added}개  |  "
            f"수정 갱신: {summary.updated}개  |  이동 감지: {summary.moved}개  |  "
            f"스킵: {summary.skipped}개  |  삭제/유실: {summary.missing}개  |  오류: {summary.errors}개"
        )
        self.scan_summary_banner.config(text=banner_text)
        self.scan_summary_banner.pack(fill="x", padx=8, pady=4)

        self._reload_library_table()
        self._refresh_audit_stats()
        self._load_audit_category()

    def _on_scan_error(self, err_msg: str) -> None:
        self.btn_run_scan.config(state="normal")
        self.scan_status_lbl.config(text="오류로 인해 스캔이 중단되었습니다.")
        messagebox.showerror("스캔 실패", f"스캔 도중 오류가 발생했습니다:\n{err_msg}")

    def _reload_library_table(self) -> None:
        try:
            self.all_library_tracks = self.repo.get_all_active_tracks()
            self._filter_library_table()
        except Exception:
            pass

    def _on_search_key_release(self, event: Any = None) -> None:
        if self._search_after_id:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
        self._search_after_id = self.after(150, self._filter_library_table)

    def _clear_search(self) -> None:
        if self._search_after_id:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
            self._search_after_id = None
        self.lib_search_var.set("")
        if hasattr(self, "lib_search_entry") and isinstance(self.lib_search_entry, tk.Entry):
            self.lib_search_entry.delete(0, tk.END)
            self.lib_search_entry.focus_set()
        self._filter_library_table()

    def _filter_library_table(self) -> None:
        if self._search_after_id:
            try:
                self.after_cancel(self._search_after_id)
            except Exception:
                pass
            self._search_after_id = None

        for item in self.lib_tree.get_children():
            self.lib_tree.delete(item)

        raw_q = ""
        if hasattr(self, "lib_search_entry") and isinstance(self.lib_search_entry, tk.Entry):
            raw_q = get_entry_text_with_ime(self.lib_search_entry).strip()
        if not raw_q and hasattr(self, "lib_search_var"):
            raw_q = self.lib_search_var.get().strip()

        q_lower = raw_q.lower()
        q_norm = normalize_text(raw_q)

        matched_count = 0
        for t in self.all_library_tracks:
            searchable = f"{t.get('artist') or ''} {t.get('title') or ''} {t.get('album') or ''} {t.get('file_name') or ''}"
            if q_lower:
                direct_match = q_lower in searchable.lower()
                norm_match = bool(q_norm and (q_norm in normalize_text(searchable)))
                if not (direct_match or norm_match):
                    continue

            matched_count += 1
            self.lib_tree.insert(
                "",
                "end",
                values=(
                    t["id"],
                    (t.get("file_ext") or "").upper(),
                    t.get("artist") or "-",
                    t.get("title") or "-",
                    t.get("album") or "-",
                    format_duration(t.get("duration_sec", 0.0)),
                    f"{t.get('bitrate_kbps') or 0}k",
                    format_cover_art(t),
                    t.get("file_path"),
                ),
            )
        self.lib_count_lbl.config(text=f"총 {matched_count:,}곡 표시 중 (전체 {len(self.all_library_tracks):,}곡)")

    def _get_selected_lib_path(self) -> Optional[str]:
        sel = self.lib_tree.selection()
        if not sel:
            return None
        vals = self.lib_tree.item(sel[0], "values")
        return vals[8] if vals and len(vals) >= 9 else None

    def _copy_selected_lib_path(self) -> None:
        p = self._get_selected_lib_path()
        if p:
            self.clipboard_clear()
            self.clipboard_append(p)
            messagebox.showinfo("복사 완료", "파일 경로가 클립보드에 복사되었습니다.")
        else:
            messagebox.showinfo("선택 필요", "라이브러리에서 곡을 선택해 주세요.")

    # --------------------------------------------------------------------------
    # TAB 3: Quality Audit & Statistics (FR-10)
    # --------------------------------------------------------------------------
    def _build_audit_tab(self) -> None:
        # Top Stats Cards Frame
        self.stats_top_frame = ttk.Frame(self.tab_audit, style="Card.TFrame", padding=12)
        self.stats_top_frame.pack(fill="x", padx=8, pady=(8, 4))

        self.stats_summary_lbl = ttk.Label(self.stats_top_frame, text="", font=("Malgun Gothic", 10, "bold"), background=self.card_bg)
        self.stats_summary_lbl.pack(side="left", padx=4)

        tk.Button(
            self.stats_top_frame,
            text="🔄 통계 새로고침",
            bg="#f3f4f6",
            command=self._refresh_audit_stats,
            padx=10,
            pady=4,
        ).pack(side="right")

        # Audit Category Toggle Bar
        cat_bar = ttk.Frame(self.tab_audit, padding=[8, 4])
        cat_bar.pack(fill="x", padx=8, pady=(4, 2))

        ttk.Label(cat_bar, text="감사 카테고리: ", font=("Malgun Gothic", 10, "bold")).pack(side="left", padx=(0, 8))
        self.audit_cat_var = tk.StringVar(value="covers")

        categories = [
            ("🖼️ 커버아트 누락 곡", "covers"),
            ("🏷️ 메타데이터 결측/추론 곡", "tags"),
            ("👯 동일 곡 중복 보유 목록", "dups"),
            ("⚠️ 스캔 오류 파일 목록", "errors"),
        ]
        for text, val in categories:
            rb = ttk.Radiobutton(cat_bar, text=text, value=val, variable=self.audit_cat_var, command=self._load_audit_category)
            rb.pack(side="left", padx=6)

        self.audit_count_lbl = ttk.Label(cat_bar, text="", foreground="#b45309", font=("Malgun Gothic", 9, "bold"))
        self.audit_count_lbl.pack(side="right")

        # Audit Table
        audit_table_frame = ttk.Frame(self.tab_audit, padding=[8, 2])
        audit_table_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self.audit_tree = ttk.Treeview(audit_table_frame, show="headings", selectmode="browse")
        self.audit_tree.pack(side="left", fill="both", expand=True)

        audit_scroll_y = ttk.Scrollbar(audit_table_frame, orient="vertical", command=self.audit_tree.yview)
        self.audit_tree.configure(yscrollcommand=audit_scroll_y.set)
        audit_scroll_y.pack(side="right", fill="y")

        # Configure treeview tags for checkboxes and duplicate zebra striping
        self.audit_tree.tag_configure("checked", background="#fee2e2")
        self.audit_tree.tag_configure("group_even", background="#ffffff")
        self.audit_tree.tag_configure("group_odd", background="#f1f5f9")

        self.audit_tree.bind("<ButtonRelease-1>", self._on_audit_tree_click)
        self.audit_tree.bind("<space>", self._on_audit_tree_space)
        self.audit_tree.bind("<Double-1>", self._on_audit_tree_double_click)

        # Audit Actions Outer Frame
        self.audit_actions_outer = ttk.Frame(self.tab_audit, padding=6)
        self.audit_actions_outer.pack(fill="x", padx=8, pady=(0, 6))

        # Right Actions Container (Common tools + Far Right Delete button)
        self.audit_right_frame = ttk.Frame(self.audit_actions_outer)
        self.audit_right_frame.pack(side="right")

        self.common_audit_frame = ttk.Frame(self.audit_right_frame)
        self.common_audit_frame.pack(side="left")

        tk.Button(
            self.common_audit_frame,
            text="☑ 전체 선택",
            bg="#f3f4f6",
            command=self._check_all_audit_items,
            padx=8,
            pady=4,
        ).pack(side="left", padx=2)

        tk.Button(
            self.common_audit_frame,
            text="☑ 선택 토글",
            bg="#f3f4f6",
            command=self._toggle_selected_audit_check,
            padx=8,
            pady=4,
        ).pack(side="left", padx=2)

        tk.Button(
            self.common_audit_frame,
            text="☐ 전체 해제",
            bg="#f3f4f6",
            command=self._uncheck_all_audit_items,
            padx=8,
            pady=4,
        ).pack(side="left", padx=2)

        tk.Button(
            self.common_audit_frame,
            text="📂 탐색기에서 열기",
            bg="#f3f4f6",
            command=self._open_selected_audit_file,
            padx=8,
            pady=4,
        ).pack(side="left", padx=2)

        tk.Button(
            self.common_audit_frame,
            text="📋 파일 경로 복사",
            bg="#f3f4f6",
            command=self._copy_selected_audit_path,
            padx=8,
            pady=4,
        ).pack(side="left", padx=2)

        # Far right delete button (shown only in dups category)
        self.btn_delete_dups = tk.Button(
            self.audit_right_frame,
            text="🗑️ 선택 파일 삭제 (0건)",
            bg="#fee2e2",
            fg="#991b1b",
            font=("Malgun Gothic", 9, "bold"),
            command=self._delete_selected_audit_files,
            padx=12,
            pady=4,
            state="disabled",
        )

        # Dynamic Action Buttons Frame (Left)
        self.audit_dynamic_frame = ttk.Frame(self.audit_actions_outer)
        self.audit_dynamic_frame.pack(side="left", fill="x", expand=True)

        # Dynamic subframes for each category
        # 1. Dups subframe
        self.audit_frame_dups = ttk.Frame(self.audit_dynamic_frame)
        tk.Button(
            self.audit_frame_dups,
            text="⚡ 저음질/하위 중복 자동 선택",
            bg="#fef3c7",
            fg="#92400e",
            font=("Malgun Gothic", 9, "bold"),
            command=self._auto_select_inferior_duplicates,
            padx=10,
            pady=4,
        ).pack(side="left", padx=(0, 6))

        # 2. Covers subframe
        self.audit_frame_covers = ttk.Frame(self.audit_dynamic_frame)
        self.btn_auto_covers = tk.Button(
            self.audit_frame_covers,
            text="🖼️ 선택 곡 커버아트 자동 채우기",
            bg="#e0e7ff",
            fg="#3730a3",
            font=("Malgun Gothic", 9, "bold"),
            command=self._auto_fill_covers_for_checked,
            padx=10,
            pady=4,
            state="disabled",
        )
        self.btn_auto_covers.pack(side="left", padx=(0, 6))

        self.btn_local_cover = tk.Button(
            self.audit_frame_covers,
            text="📁 내 PC 이미지로 커버 넣기...",
            bg="#f3f4f6",
            command=self._insert_local_image_for_checked,
            padx=10,
            pady=4,
            state="disabled",
        )
        self.btn_local_cover.pack(side="left", padx=4)

        # 3. Tags subframe
        self.audit_frame_tags = ttk.Frame(self.audit_dynamic_frame)
        self.btn_apply_tags = tk.Button(
            self.audit_frame_tags,
            text="🏷️ 추론된 가수·제목을 실제 태그에 저장",
            bg="#dcfce7",
            fg="#166534",
            font=("Malgun Gothic", 9, "bold"),
            command=self._apply_tags_to_checked_files,
            padx=10,
            pady=4,
            state="disabled",
        )
        self.btn_apply_tags.pack(side="left", padx=(0, 6))

        self.btn_rename_files = tk.Button(
            self.audit_frame_tags,
            text="✏️ 파일명을 '가수 - 제목' 형식으로 통일",
            bg="#f3f4f6",
            command=self._rename_checked_files_to_standard,
            padx=10,
            pady=4,
            state="disabled",
        )
        self.btn_rename_files.pack(side="left", padx=4)

        self._refresh_audit_stats()
        self._load_audit_category()

    def _refresh_audit_stats(self) -> None:
        try:
            st = self.repo.get_stats()
            fmt_str = ", ".join(f"{k.upper()}: {v}" for k, v in st["by_format"].items()) or "없음"
            ca = st["cover_art"]
            text = (
                f"총 활성 음원: {st['total_active']:,}곡   |   유실 음원: {st['total_missing']:,}곡   |   "
                f"커버아트 내장: {ca['embedded']:,} / 폴더: {ca['folder']:,} / [누락: {ca['none']:,}]   |   "
                f"포맷: [{fmt_str}]   |   스캔 오류: {st['total_errors']}건"
            )
            self.stats_summary_lbl.config(text=text)
        except Exception:
            pass

    def _load_audit_category(self) -> None:
        self._audit_checked_items.clear()
        self._audit_row_meta.clear()

        for item in self.audit_tree.get_children():
            self.audit_tree.delete(item)

        # Hide all dynamic frames first
        self.audit_frame_dups.pack_forget()
        self.audit_frame_covers.pack_forget()
        self.audit_frame_tags.pack_forget()
        self.btn_delete_dups.pack_forget()

        cat = self.audit_cat_var.get()
        if cat == "covers":
            self.audit_frame_covers.pack(side="left")
            cols = ("check", "id", "artist", "title", "album", "path")
            self.audit_tree.config(columns=cols)
            self.audit_tree.heading("check", text="선택")
            self.audit_tree.heading("id", text="ID")
            self.audit_tree.heading("artist", text="아티스트")
            self.audit_tree.heading("title", text="곡명")
            self.audit_tree.heading("album", text="앨범")
            self.audit_tree.heading("path", text="파일 경로")
            self.audit_tree.column("check", width=45, anchor="center")
            self.audit_tree.column("id", width=55, anchor="center")
            self.audit_tree.column("artist", width=160)
            self.audit_tree.column("title", width=220)
            self.audit_tree.column("album", width=180)
            self.audit_tree.column("path", width=380)

            rows = self.repo.get_missing_covers()
            for r in rows:
                item_id = self.audit_tree.insert(
                    "",
                    "end",
                    values=(
                        "☐",
                        r["id"],
                        r.get("artist") or "-",
                        r.get("title") or "-",
                        r.get("album") or "-",
                        r.get("file_path") or "",
                    ),
                )
                self._audit_row_meta[item_id] = r
            self.audit_count_lbl.config(text=f"커버아트 누락 {len(rows):,}건")

        elif cat == "tags":
            self.audit_frame_tags.pack(side="left")
            cols = ("check", "source", "artist", "title", "album", "path")
            self.audit_tree.config(columns=cols)
            self.audit_tree.heading("check", text="선택")
            self.audit_tree.heading("source", text="태그 출처")
            self.audit_tree.heading("artist", text="가수(추론)")
            self.audit_tree.heading("title", text="제목(추론)")
            self.audit_tree.heading("album", text="앨범")
            self.audit_tree.heading("path", text="파일 경로")
            self.audit_tree.column("check", width=45, anchor="center")
            self.audit_tree.column("source", width=110, anchor="center")
            self.audit_tree.column("artist", width=160)
            self.audit_tree.column("title", width=220)
            self.audit_tree.column("album", width=160)
            self.audit_tree.column("path", width=380)

            rows = self.repo.get_missing_tags()
            for r in rows:
                item_id = self.audit_tree.insert(
                    "",
                    "end",
                    values=(
                        "☐",
                        r.get("tag_source") or "결측",
                        r.get("artist") or "(누락)",
                        r.get("title") or "(누락)",
                        r.get("album") or "(누락)",
                        r.get("file_path") or "",
                    ),
                )
                self._audit_row_meta[item_id] = r
            self.audit_count_lbl.config(text=f"메타데이터 결측/추론 {len(rows):,}건")

        elif cat == "dups":
            self.audit_frame_dups.pack(side="left")
            self.btn_delete_dups.pack(side="left", padx=(6, 0))
            cols = ("check", "artist", "title", "ext", "bitrate", "cover", "path")
            self.audit_tree.config(columns=cols)
            self.audit_tree.heading("check", text="선택")
            self.audit_tree.heading("artist", text="아티스트")
            self.audit_tree.heading("title", text="곡명")
            self.audit_tree.heading("ext", text="포맷")
            self.audit_tree.heading("bitrate", text="비트레이트")
            self.audit_tree.heading("cover", text="커버아트")
            self.audit_tree.heading("path", text="파일 경로")
            self.audit_tree.column("check", width=45, anchor="center")
            self.audit_tree.column("artist", width=160)
            self.audit_tree.column("title", width=220)
            self.audit_tree.column("ext", width=60, anchor="center")
            self.audit_tree.column("bitrate", width=80, anchor="center")
            self.audit_tree.column("cover", width=80, anchor="center")
            self.audit_tree.column("path", width=380)

            rows = self.repo.get_duplicates()
            current_group_key = None
            group_stripe_idx = 0
            idx_in_group = 0

            for r in rows:
                gkey = r.get("dup_group_key") or f"{r.get('norm_artist')}__{r.get('norm_title')}"
                if gkey != current_group_key:
                    current_group_key = gkey
                    group_stripe_idx += 1
                    idx_in_group = 0
                else:
                    idx_in_group += 1

                stripe_tag = "group_odd" if group_stripe_idx % 2 == 1 else "group_even"
                r["_stripe_tag"] = stripe_tag
                r["_group_key"] = gkey
                r["_is_first_in_group"] = (idx_in_group == 0)

                item_id = self.audit_tree.insert(
                    "",
                    "end",
                    values=(
                        "☐",
                        r.get("artist") or "-",
                        r.get("title") or "-",
                        (r.get("file_ext") or "").upper(),
                        f"{r.get('bitrate_kbps') or 0}k",
                        format_cover_art(r),
                        r.get("file_path") or "",
                    ),
                    tags=(stripe_tag,),
                )
                self._audit_row_meta[item_id] = r

            self.audit_count_lbl.config(text=f"중복 보유 {len(rows):,}건")

        elif cat == "errors":
            cols = ("id", "time", "message", "note", "path")
            self.audit_tree.config(columns=cols)
            self.audit_tree.heading("id", text="ID")
            self.audit_tree.heading("time", text="오류 발생 시각")
            self.audit_tree.heading("message", text="오류 내용")
            self.audit_tree.heading("note", text="비고")
            self.audit_tree.heading("path", text="파일 경로")
            self.audit_tree.column("id", width=50, anchor="center")
            self.audit_tree.column("time", width=140)
            self.audit_tree.column("message", width=280)
            self.audit_tree.column("note", width=100)
            self.audit_tree.column("path", width=420)

            rows = self.repo.get_scan_errors()
            for r in rows:
                item_id = self.audit_tree.insert(
                    "",
                    "end",
                    values=(
                        r["id"],
                        r.get("created_at") or "-",
                        r.get("error_message") or "-",
                        "파싱 불가",
                        r.get("file_path") or "",
                    ),
                )
                self._audit_row_meta[item_id] = r
            self.audit_count_lbl.config(text=f"스캔 오류 누적 {len(rows):,}건")

        self._update_audit_action_buttons()

    def _toggle_audit_item_check(self, item_id: str) -> None:
        if item_id not in self._audit_row_meta:
            return
        cat = self.audit_cat_var.get()
        if cat == "errors":
            return

        meta = self._audit_row_meta[item_id]
        stripe = meta.get("_stripe_tag", "")

        vals = list(self.audit_tree.item(item_id, "values"))
        if not vals:
            return

        if item_id in self._audit_checked_items:
            self._audit_checked_items.remove(item_id)
            vals[0] = "☐"
            tags = (stripe,) if stripe else ()
            self.audit_tree.item(item_id, values=vals, tags=tags)
        else:
            self._audit_checked_items.add(item_id)
            vals[0] = "☑"
            tags = ("checked",)
            self.audit_tree.item(item_id, values=vals, tags=tags)

        self._update_audit_action_buttons()

    def _on_audit_tree_click(self, event: Any) -> None:
        region = self.audit_tree.identify_region(event.x, event.y)
        col = self.audit_tree.identify_column(event.x)
        if region == "cell" and col == "#1":
            item = self.audit_tree.identify_row(event.y)
            if item:
                self._toggle_audit_item_check(item)

    def _on_audit_tree_space(self, event: Any) -> None:
        sel = self.audit_tree.selection()
        for item in sel:
            self._toggle_audit_item_check(item)

    def _on_audit_tree_double_click(self, event: Any) -> None:
        cat = self.audit_cat_var.get()
        item = self.audit_tree.identify_row(event.y)
        if not item:
            return
        if cat == "errors":
            open_in_explorer(self._get_selected_audit_path())
        else:
            self._toggle_audit_item_check(item)

    def _update_audit_action_buttons(self) -> None:
        cat = self.audit_cat_var.get()
        cnt = len(self._audit_checked_items)
        if cat == "dups":
            self.btn_delete_dups.config(
                text=f"🗑️ 선택 파일 삭제 ({cnt}건)",
                state="normal" if cnt > 0 else "disabled",
            )
        elif cat == "covers":
            self.btn_auto_covers.config(
                text=f"🖼️ 선택 곡 커버아트 자동 채우기 ({cnt}건)" if cnt > 0 else "🖼️ 선택 곡 커버아트 자동 채우기",
                state="normal" if cnt > 0 else "disabled",
            )
            self.btn_local_cover.config(
                text=f"📁 내 PC 이미지로 커버 넣기 ({cnt}건)..." if cnt > 0 else "📁 내 PC 이미지로 커버 넣기...",
                state="normal" if cnt > 0 else "disabled",
            )
        elif cat == "tags":
            self.btn_apply_tags.config(
                text=f"🏷️ 추론된 가수·제목을 실제 태그에 저장 ({cnt}건)" if cnt > 0 else "🏷️ 추론된 가수·제목을 실제 태그에 저장",
                state="normal" if cnt > 0 else "disabled",
            )
            self.btn_rename_files.config(
                text=f"✏️ 파일명을 '가수 - 제목' 형식으로 통일 ({cnt}건)" if cnt > 0 else "✏️ 파일명을 '가수 - 제목' 형식으로 통일",
                state="normal" if cnt > 0 else "disabled",
            )

    def _get_selected_audit_path(self) -> Optional[str]:
        sel = self.audit_tree.selection()
        if not sel:
            return None
        item_id = sel[0]
        if item_id in self._audit_row_meta:
            return self._audit_row_meta[item_id].get("file_path")
        vals = self.audit_tree.item(item_id, "values")
        if vals:
            return vals[-1]
        return None

    def _open_selected_audit_file(self) -> None:
        p = self._get_selected_audit_path()
        if p:
            open_in_explorer(p)
        else:
            messagebox.showinfo("선택 필요", "테이블에서 항목을 선택해 주세요.")

    def _copy_selected_audit_path(self) -> None:
        p = self._get_selected_audit_path()
        if p:
            self.clipboard_clear()
            self.clipboard_append(p)
            messagebox.showinfo("복사 완료", "파일 경로가 클립보드에 복사되었습니다.")
        else:
            messagebox.showinfo("선택 필요", "테이블에서 항목을 선택해 주세요.")

    def _toggle_selected_audit_check(self) -> None:
        sel = self.audit_tree.selection()
        if not sel:
            messagebox.showinfo("선택 필요", "체크 상태를 토글할 행을 선택해 주세요.")
            return
        for item in sel:
            self._toggle_audit_item_check(item)

    def _check_all_audit_items(self) -> None:
        cat = self.audit_cat_var.get()
        if cat == "errors":
            return
        for item_id in list(self._audit_row_meta.keys()):
            if item_id not in self._audit_checked_items:
                self._toggle_audit_item_check(item_id)

    def _uncheck_all_audit_items(self) -> None:
        for item_id in list(self._audit_checked_items):
            self._toggle_audit_item_check(item_id)

    def _auto_select_inferior_duplicates(self) -> None:
        self._uncheck_all_audit_items()
        selected_cnt = 0
        for item_id, meta in self._audit_row_meta.items():
            if not meta.get("_is_first_in_group", False):
                if item_id not in self._audit_checked_items:
                    self._toggle_audit_item_check(item_id)
                    selected_cnt += 1
        if selected_cnt > 0:
            messagebox.showinfo("선택 완료", f"중복 그룹 내 품질이 낮거나 하위인 음원 {selected_cnt}곡이 자동 선택되었습니다.")
        else:
            messagebox.showinfo("안내", "자동 선택할 하위 중복 음원이 없습니다.")

    def _delete_selected_audit_files(self) -> None:
        if not self._audit_checked_items:
            messagebox.showinfo("선택 필요", "삭제할 중복 파일을 선택해 주세요.")
            return

        # Safety guard: Ensure at least one file is preserved per duplicate group
        group_counts: Dict[str, int] = {}
        checked_counts: Dict[str, int] = {}
        for item_id, meta in self._audit_row_meta.items():
            gkey = meta.get("_group_key", "")
            group_counts[gkey] = group_counts.get(gkey, 0) + 1
            if item_id in self._audit_checked_items:
                checked_counts[gkey] = checked_counts.get(gkey, 0) + 1

        for gkey, total_c in group_counts.items():
            c_count = checked_counts.get(gkey, 0)
            if c_count > 0 and c_count >= total_c:
                messagebox.showerror(
                    "안전 삭제 차단",
                    "중복 그룹 내 모든 파일이 선택된 곡이 포함되어 있습니다!\n"
                    "곡이 라이브러리에서 완전히 유실되는 것을 방지하기 위해, 각 중복 그룹당 최소 1개의 원본 파일은 반드시 보존되어야 합니다.\n\n"
                    "선택 항목을 다시 확인해 주시기 바랍니다.",
                )
                return

        target_tracks = [self._audit_row_meta[item_id] for item_id in self._audit_checked_items if item_id in self._audit_row_meta]
        cnt = len(target_tracks)

        if not messagebox.askyesno(
            "중복 파일 영구 삭제 확인",
            f"선택한 {cnt}개 음원 파일을 로컬 디스크에서 영구 삭제하고 라이브러리 DB에서 제거하시겠습니까?\n\n"
            "⚠️ 삭제된 파일은 휴지통을 거치지 않고 영구 삭제될 수 있으므로 주의하십시오.",
            icon="warning",
        ):
            return

        deleted_files = 0
        failed_files = 0
        ids_to_delete: List[int] = []

        for t in target_tracks:
            fpath = t.get("file_path")
            if fpath:
                try:
                    p = Path(fpath)
                    if p.exists():
                        p.unlink(missing_ok=True)
                    deleted_files += 1
                    ids_to_delete.append(t["id"])
                except Exception:
                    failed_files += 1
            else:
                ids_to_delete.append(t["id"])

        if ids_to_delete:
            self.repo.delete_tracks_by_ids(ids_to_delete)

        self._refresh_audit_stats()
        self._load_audit_category()
        self._reload_library_table()

        msg = f"{deleted_files}개의 중복 파일이 디스크 및 DB에서 정상적으로 삭제되었습니다."
        if failed_files > 0:
            msg += f"\n(파일 사용 중 등으로 삭제 실패: {failed_files}건)"
        messagebox.showinfo("삭제 완료", msg)

    def _auto_fill_covers_for_checked(self) -> None:
        checked_tracks = [self._audit_row_meta[item_id] for item_id in self._audit_checked_items if item_id in self._audit_row_meta]
        if not checked_tracks:
            messagebox.showinfo("선택 필요", "커버아트를 채울 곡을 체크박스로 선택해 주세요.")
            return

        def worker() -> None:
            all_tracks = self.repo.get_all_active_tracks()
            success_cnt = 0
            fail_cnt = 0
            for t in checked_tracks:
                fpath = t.get("file_path")
                if not fpath or not Path(fpath).exists():
                    fail_cnt += 1
                    continue
                res = fetch_cover_art_auto(t, all_tracks, repo=self.repo)
                if res:
                    cover_bytes, mime = res
                    ok = embed_cover_art(fpath, cover_bytes, mime)
                    if ok:
                        sync_single_file(fpath, self.repo)
                        success_cnt += 1
                    else:
                        fail_cnt += 1
                else:
                    fail_cnt += 1

            def on_done() -> None:
                self._refresh_audit_stats()
                self._load_audit_category()
                self._reload_library_table()
                messagebox.showinfo(
                    "커버아트 자동 채우기 완료",
                    f"총 {len(checked_tracks)}곡 중 {success_cnt}곡에 커버아트가 성공적으로 적용되었습니다.\n"
                    f"(실패/미발견: {fail_cnt}곡)",
                )

            self.after(0, on_done)

        threading.Thread(target=worker, daemon=True).start()
        messagebox.showinfo("작업 시작", f"{len(checked_tracks)}곡의 커버아트 자동 탐색 및 내장을 시작합니다.\n완료 시 알림이 표시됩니다.")

    def _insert_local_image_for_checked(self) -> None:
        checked_tracks = [self._audit_row_meta[item_id] for item_id in self._audit_checked_items if item_id in self._audit_row_meta]
        if not checked_tracks:
            messagebox.showinfo("선택 필요", "커버아트를 적용할 곡을 체크박스로 선택해 주세요.")
            return

        img_path = filedialog.askopenfilename(
            title="내 PC에서 커버아트 이미지 선택",
            filetypes=[
                ("이미지 파일", "*.jpg *.jpeg *.png *.webp"),
                ("JPEG 이미지", "*.jpg *.jpeg"),
                ("PNG 이미지", "*.png"),
                ("모든 파일", "*.*"),
            ],
        )
        if not img_path:
            return

        try:
            with open(img_path, "rb") as f:
                img_bytes = f.read()
            ext = Path(img_path).suffix.lower()
            mime = "image/png" if ext == ".png" else "image/jpeg"

            success_cnt = 0
            fail_cnt = 0
            for t in checked_tracks:
                fpath = t.get("file_path")
                if fpath and Path(fpath).exists():
                    ok = embed_cover_art(fpath, img_bytes, mime)
                    if ok:
                        sync_single_file(fpath, self.repo)
                        success_cnt += 1
                    else:
                        fail_cnt += 1
                else:
                    fail_cnt += 1

            self._refresh_audit_stats()
            self._load_audit_category()
            self._reload_library_table()
            messagebox.showinfo(
                "커버아트 적용 완료",
                f"선택한 {len(checked_tracks)}곡 중 {success_cnt}곡에 이미지가 성공적으로 내장되었습니다.",
            )
        except Exception as ex:
            messagebox.showerror("오류", f"이미지 파일을 읽거나 적용하는 중 오류가 발생했습니다:\n{ex}")

    def _apply_tags_to_checked_files(self) -> None:
        checked_tracks = [self._audit_row_meta[item_id] for item_id in self._audit_checked_items if item_id in self._audit_row_meta]
        if not checked_tracks:
            messagebox.showinfo("선택 필요", "태그를 적용할 곡을 체크박스로 선택해 주세요.")
            return

        if not messagebox.askyesno(
            "태그 적용 확인",
            f"선택한 {len(checked_tracks)}곡의 파일에 추론된 가수·곡명 메타데이터 태그(ID3/Vorbis)를 직접 기록하시겠습니까?",
        ):
            return

        success_cnt = 0
        fail_cnt = 0
        for t in checked_tracks:
            fpath = t.get("file_path")
            artist = t.get("artist") or ""
            title = t.get("title") or ""
            if fpath and Path(fpath).exists() and (artist or title):
                ok = apply_fallback_tags_to_file(fpath, artist, title)
                if ok:
                    sync_single_file(fpath, self.repo)
                    success_cnt += 1
                else:
                    fail_cnt += 1
            else:
                fail_cnt += 1

        self._refresh_audit_stats()
        self._load_audit_category()
        self._reload_library_table()
        messagebox.showinfo(
            "태그 저장 완료",
            f"{len(checked_tracks)}곡 중 {success_cnt}곡의 실제 파일에 메타데이터 태그가 저장되었습니다.",
        )

    def _rename_checked_files_to_standard(self) -> None:
        checked_tracks = [self._audit_row_meta[item_id] for item_id in self._audit_checked_items if item_id in self._audit_row_meta]
        if not checked_tracks:
            messagebox.showinfo("선택 필요", "파일명을 통일할 곡을 체크박스로 선택해 주세요.")
            return

        if not messagebox.askyesno(
            "파일명 변경 확인",
            f"선택한 {len(checked_tracks)}개 파일의 이름을 '[가수] - [제목].[확장자]' 표준 양식으로 변경하시겠습니까?",
        ):
            return

        renamed_cnt = 0
        fail_cnt = 0
        for t in checked_tracks:
            old_path = t.get("file_path")
            artist = t.get("artist") or ""
            title = t.get("title") or ""
            if old_path and Path(old_path).exists() and (artist or title):
                try:
                    new_path = rename_file_standard(old_path, artist, title)
                    if new_path and new_path != old_path:
                        p = Path(new_path)
                        stat = p.stat()
                        self.repo.update_track_path(
                            old_path=old_path,
                            new_path=str(p),
                            new_name=p.name,
                            new_ext=p.suffix.lstrip(".").lower(),
                            mtime=stat.st_mtime,
                            file_size=stat.st_size,
                        )
                        renamed_cnt += 1
                except Exception:
                    fail_cnt += 1
            else:
                fail_cnt += 1

        self._refresh_audit_stats()
        self._load_audit_category()
        self._reload_library_table()
        messagebox.showinfo(
            "파일명 통일 완료",
            f"{len(checked_tracks)}곡 중 {renamed_cnt}개 파일명이 표준 형식으로 변경되었습니다.",
        )

    # --------------------------------------------------------------------------
    # TAB 4: Artist Aliases Management
    # --------------------------------------------------------------------------
    def _build_alias_tab(self) -> None:
        # Top Add Form
        top_frame = ttk.Frame(self.tab_alias, style="Card.TFrame", padding=12)
        top_frame.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(top_frame, text="대표 아티스트 (Canonical):", background=self.card_bg).pack(side="left", padx=(0, 4))
        self.canon_alias_var = tk.StringVar()
        self.canon_entry = tk.Entry(
            top_frame,
            textvariable=self.canon_alias_var,
            width=16,
            font=("Malgun Gothic", 10),
            relief="solid",
            bd=1,
            bg="white",
            fg="#111827",
            insertbackground="#111827",
        )
        self.canon_entry.pack(side="left", padx=(0, 10), ipady=3)

        ttk.Label(top_frame, text="별칭 (Alias):", background=self.card_bg).pack(side="left", padx=(0, 4))
        self.new_alias_var = tk.StringVar()
        self.alias_entry = tk.Entry(
            top_frame,
            textvariable=self.new_alias_var,
            width=16,
            font=("Malgun Gothic", 10),
            relief="solid",
            bd=1,
            bg="white",
            fg="#111827",
            insertbackground="#111827",
        )
        self.alias_entry.pack(side="left", padx=(0, 12), ipady=3)

        tk.Button(
            top_frame,
            text="➕ 별칭 등록",
            bg="#2563eb",
            fg="white",
            relief="flat",
            command=self._add_alias_from_form,
            padx=12,
            pady=4,
            cursor="hand2",
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            top_frame,
            text="🗑️ 선택 별칭 삭제",
            bg="#fee2e2",
            fg="#991b1b",
            relief="flat",
            command=self._delete_selected_alias,
            padx=10,
            pady=4,
        ).pack(side="left")

        # Aliases Treeview
        table_frame = ttk.Frame(self.tab_alias, padding=[8, 4])
        table_frame.pack(fill="both", expand=True, padx=8, pady=4)

        cols = ("canonical", "alias")
        self.alias_tree = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.alias_tree.heading("canonical", text="대표 아티스트 (Canonical)")
        self.alias_tree.heading("alias", text="등록된 별칭 (Alias)")
        self.alias_tree.column("canonical", width=260)
        self.alias_tree.column("alias", width=260)

        alias_scroll_y = ttk.Scrollbar(table_frame, orient="vertical", command=self.alias_tree.yview)
        self.alias_tree.configure(yscrollcommand=alias_scroll_y.set)
        self.alias_tree.pack(side="left", fill="both", expand=True)
        alias_scroll_y.pack(side="right", fill="y")

        self._load_alias_tree()

    def _load_alias_tree(self) -> None:
        for item in self.alias_tree.get_children():
            self.alias_tree.delete(item)
        aliases = self.repo.get_aliases()
        for a in aliases:
            self.alias_tree.insert("", "end", values=(a["canonical_norm_artist"], a["alias_norm_artist"]))

    def _add_alias_from_form(self) -> None:
        canon = self.canon_alias_var.get().strip()
        alias = self.new_alias_var.get().strip()
        if not canon or not alias:
            messagebox.showwarning("입력 필요", "대표 아티스트와 별칭을 모두 입력해 주세요.")
            return

        self.repo.add_alias(canon, alias)
        self.canon_alias_var.set("")
        self.new_alias_var.set("")
        self._load_alias_tree()
        messagebox.showinfo("등록 완료", f"별칭이 등록되었습니다:\n'{canon}' ↔ '{alias}'")

    def _delete_selected_alias(self) -> None:
        sel = self.alias_tree.selection()
        if not sel:
            messagebox.showinfo("선택 필요", "삭제할 별칭을 목록에서 선택해 주세요.")
            return
        vals = self.alias_tree.item(sel[0], "values")
        if not vals:
            return
        canon, alias = vals[0], vals[1]
        if messagebox.askyesno("삭제 확인", f"별칭 '{alias}' (대표: {canon}) 항목을 삭제하시겠습니까?"):
            self.repo.delete_alias(alias)
            self._load_alias_tree()


def main() -> None:
    """GUI entrypoint."""
    app = MusicCheckerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
