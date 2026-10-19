"""Tab 1: YouTube Matcher UI and event handlers."""
import csv
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from src.gui.theme_and_ime import format_cover_art, format_duration, open_in_explorer
from src.matcher.scorer import MatcherEngine, MatchResult, MatchStatus
from src.youtube.extractor import YouTubeExtractor, YouTubeTrackInfo


class YouTubeTabMixin:
    """Mixin implementing Tab 1: YouTube single/playlist/chapter matcher."""

    tab_matcher: ttk.Frame
    card_bg: str
    yt_url_var: tk.StringVar
    yt_url_entry: tk.Entry
    btn_check: tk.Button
    match_status_bar: ttk.Frame
    match_progress: ttk.Progressbar
    match_status_lbl: ttk.Label
    results_container: ttk.Frame
    single_card: ttk.Frame
    badge_lbl: tk.Label
    yt_meta_lbl: ttk.Label
    score_detail_lbl: ttk.Label
    reason_lbl: ttk.Label
    local_info_frame: tk.LabelFrame
    loc_title_lbl: ttk.Label
    loc_artist_lbl: ttk.Label
    loc_album_lbl: ttk.Label
    loc_spec_lbl: ttk.Label
    loc_cover_lbl: ttk.Label
    loc_path_lbl: ttk.Label
    single_actions_frame: ttk.Frame
    current_matched_path: Optional[str]
    btn_open_folder: tk.Button
    btn_copy_path: tk.Button
    multi_frame: ttk.Frame
    playlist_summary_lbl: ttk.Label
    playlist_filter_var: tk.StringVar
    pl_tree: ttk.Treeview
    cached_playlist_results: List[Dict[str, Any]]
    engine: MatcherEngine
    extractor: YouTubeExtractor

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

        self.current_matched_path = None
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

        self.cached_playlist_results = []

    def _paste_clipboard_to_url(self) -> None:
        try:
            val = self.clipboard_get().strip()  # type: ignore[attr-defined]
            if val:
                self.yt_url_var.set(val)
        except Exception:
            pass

    def _copy_matched_path(self) -> None:
        if self.current_matched_path:
            self.clipboard_clear()  # type: ignore[attr-defined]
            self.clipboard_append(self.current_matched_path)  # type: ignore[attr-defined]
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
            self.after(0, self._on_youtube_extracted, result)  # type: ignore[attr-defined]
        except Exception as e:
            self.after(0, self._on_youtube_error, str(e))  # type: ignore[attr-defined]

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
            self.clipboard_clear()  # type: ignore[attr-defined]
            self.clipboard_append(path)  # type: ignore[attr-defined]
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
        self.clipboard_clear()  # type: ignore[attr-defined]
        self.clipboard_append(text_to_copy)  # type: ignore[attr-defined]
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
