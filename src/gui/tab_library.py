"""Tab 2: Local Scanner and Library Search UI and event handlers."""
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional

from src.db.repository import Repository
from src.gui.theme_and_ime import (
    format_cover_art,
    format_duration,
    get_entry_text_with_ime,
    open_in_explorer,
    save_settings,
)
from src.matcher.normalizer import normalize_text
from src.scanner.file_walker import ScanSummary, scan_directory


class LibraryTabMixin:
    """Mixin implementing Tab 2: Local library scanning, incremental sync, and live search."""

    tab_scanner: ttk.Frame
    card_bg: str
    settings: Dict[str, Any]
    scan_dir_var: tk.StringVar
    scan_dir_entry: tk.Entry
    btn_run_scan: tk.Button
    scan_status_frame: ttk.Frame
    scan_progress_bar: ttk.Progressbar
    scan_status_lbl: ttk.Label
    scan_summary_banner: tk.Label
    lib_search_var: tk.StringVar
    lib_search_entry: tk.Entry
    lib_count_lbl: ttk.Label
    lib_tree: ttk.Treeview
    all_library_tracks: List[Dict[str, Any]]
    _search_after_id: Optional[str]
    repo: Repository

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

        self.all_library_tracks = []
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
            def _prog(fname: str, cur: int, total: int) -> None:
                pct = (cur / total * 100) if total else 0
                self.after(0, self._update_scan_progress, fname, cur, total, pct)  # type: ignore[attr-defined]

            summary = scan_directory(dir_path, self.repo, progress_callback=_prog)
            self.after(0, self._on_scan_finished, summary)  # type: ignore[attr-defined]
        except Exception as e:
            self.after(0, self._on_scan_error, str(e))  # type: ignore[attr-defined]

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
        if hasattr(self, "_refresh_audit_stats"):
            self._refresh_audit_stats()  # type: ignore[attr-defined]
        if hasattr(self, "_load_audit_category"):
            self._load_audit_category()  # type: ignore[attr-defined]

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
                self.after_cancel(self._search_after_id)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._search_after_id = self.after(150, self._filter_library_table)  # type: ignore[attr-defined]

    def _clear_search(self) -> None:
        if self._search_after_id:
            try:
                self.after_cancel(self._search_after_id)  # type: ignore[attr-defined]
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
                self.after_cancel(self._search_after_id)  # type: ignore[attr-defined]
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
            self.clipboard_clear()  # type: ignore[attr-defined]
            self.clipboard_append(p)  # type: ignore[attr-defined]
            messagebox.showinfo("복사 완료", "파일 경로가 클립보드에 복사되었습니다.")
        else:
            messagebox.showinfo("선택 필요", "라이브러리에서 곡을 선택해 주세요.")
