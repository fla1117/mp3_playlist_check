"""Tab 3: Quality Audit & Statistics UI and batch maintenance operations."""
import os
import stat
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Set

from src.config import OPERATION_LOG_PATH
from src.db.repository import Repository
from src.gui.theme_and_ime import format_cover_art, open_in_explorer
from src.scanner.cover_manager import embed_cover_art, fetch_cover_art_auto
from src.scanner.file_walker import sync_single_file
from src.scanner.tag_normalizer import (
    apply_fallback_tags_to_file,
    batch_standardize_underscore_directory,
    parse_underscore_filename,
    rename_file_standard,
    standardize_underscore_filename,
)


class AuditTabMixin:
    """Mixin implementing Tab 3: Library quality audit, duplicate cleanup, and tag/cover repair."""

    tab_audit: ttk.Frame
    card_bg: str
    stats_top_frame: ttk.Frame
    stats_summary_lbl: ttk.Label
    audit_cat_var: tk.StringVar
    audit_count_lbl: ttk.Label
    audit_tree: ttk.Treeview
    audit_actions_outer: ttk.Frame
    audit_right_frame: ttk.Frame
    common_audit_frame: ttk.Frame
    btn_delete_dups: tk.Button
    audit_dynamic_frame: ttk.Frame
    audit_frame_dups: ttk.Frame
    audit_frame_covers: ttk.Frame
    btn_auto_covers: tk.Button
    btn_local_cover: tk.Button
    audit_frame_tags: ttk.Frame
    btn_apply_tags: tk.Button
    btn_rename_files: tk.Button
    audit_frame_naming: ttk.Frame
    btn_standardize_naming: tk.Button
    _audit_row_meta: Dict[str, Dict[str, Any]]
    _audit_checked_items: Set[str]
    repo: Repository

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
            ("📝 비표준 파일명 ('_') 정리", "naming"),
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

        # 4. Naming subframe
        self.audit_frame_naming = ttk.Frame(self.audit_dynamic_frame)
        self.btn_standardize_naming = tk.Button(
            self.audit_frame_naming,
            text="✏️ 선택 파일 일괄 표준화 ('가수 - 제목')",
            bg="#dbeafe",
            fg="#1e40af",
            font=("Malgun Gothic", 9, "bold"),
            command=self._standardize_checked_naming_files,
            padx=10,
            pady=4,
            state="disabled",
        )
        self.btn_standardize_naming.pack(side="left", padx=(0, 6))

        tk.Button(
            self.audit_frame_naming,
            text="📂 외부 폴더 직접 선택하여 일괄 정리...",
            bg="#f3f4f6",
            command=self._standardize_external_folder_dialog,
            padx=10,
            pady=4,
        ).pack(side="left", padx=4)

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
        self.audit_frame_naming.pack_forget()
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

        elif cat == "naming":
            self.audit_frame_naming.pack(side="left")
            cols = ("check", "current_name", "target_name", "artist", "title", "path")
            self.audit_tree.config(columns=cols)
            self.audit_tree.heading("check", text="선택")
            self.audit_tree.heading("current_name", text="현재 파일명")
            self.audit_tree.heading("target_name", text="변경 예정 파일명")
            self.audit_tree.heading("artist", text="가수")
            self.audit_tree.heading("title", text="제목")
            self.audit_tree.heading("path", text="파일 경로")
            self.audit_tree.column("check", width=45, anchor="center")
            self.audit_tree.column("current_name", width=240)
            self.audit_tree.column("target_name", width=240)
            self.audit_tree.column("artist", width=140)
            self.audit_tree.column("title", width=180)
            self.audit_tree.column("path", width=340)

            rows = self.repo.get_nonstandard_naming_tracks()
            for r in rows:
                item_id = self.audit_tree.insert(
                    "",
                    "end",
                    values=(
                        "☐",
                        r.get("file_name") or "",
                        r.get("target_name") or "",
                        r.get("parsed_artist") or r.get("artist") or "-",
                        r.get("parsed_title") or r.get("title") or "-",
                        r.get("file_path") or "",
                    ),
                )
                self._audit_row_meta[item_id] = r
            self.audit_count_lbl.config(text=f"비표준 파일명 ('_') {len(rows):,}건")

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
        elif cat == "naming":
            self.btn_standardize_naming.config(
                text=f"✏️ 선택 파일 일괄 표준화 ({cnt}건)" if cnt > 0 else "✏️ 선택 파일 일괄 표준화 ('가수 - 제목')",
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
            self.clipboard_clear()  # type: ignore[attr-defined]
            self.clipboard_append(p)  # type: ignore[attr-defined]
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
        failed_samples: List[str] = []
        ids_to_delete: List[int] = []

        for t in target_tracks:
            fpath = t.get("file_path")
            if fpath:
                try:
                    p = Path(fpath)
                    if p.exists():
                        st = p.stat()
                        if not (st.st_mode & stat.S_IWRITE):
                            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
                        p.unlink(missing_ok=True)
                    deleted_files += 1
                    ids_to_delete.append(t["id"])
                except Exception as e:
                    failed_files += 1
                    err_msg = f"{type(e).__name__}: {e}"
                    # 1. Append to operation_errors.log
                    try:
                        OPERATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with open(OPERATION_LOG_PATH, "a", encoding="utf-8") as f:
                            f.write(f"[{now_str}] [DELETE_ERROR] {fpath} -> {err_msg}\n")
                    except Exception:
                        pass

                    # 2. Record to scan_errors in database
                    try:
                        self.repo.record_scan_error(fpath, f"[삭제 실패] {err_msg}")
                    except Exception:
                        pass

                    if len(failed_samples) < 3:
                        failed_samples.append(f"• {Path(fpath).name}: {err_msg}")
            else:
                ids_to_delete.append(t["id"])

        if ids_to_delete:
            self.repo.delete_tracks_by_ids(ids_to_delete)

        self._refresh_audit_stats()
        self._load_audit_category()
        if hasattr(self, "_reload_library_table"):
            self._reload_library_table()  # type: ignore[attr-defined]

        msg = f"{deleted_files}개의 중복 파일이 디스크 및 DB에서 정상적으로 삭제되었습니다."
        if failed_files > 0:
            msg += f"\n\n⚠️ 파일 삭제 실패: {failed_files}건"
            if failed_samples:
                msg += "\n[대표 실패 원인]\n" + "\n".join(failed_samples)
            msg += f"\n\n상세 로그는 '{OPERATION_LOG_PATH.name}' 파일 및 상단 '⚠️ 스캔 오류 파일 목록' 탭에서 확인하실 수 있습니다."
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
                try:
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
                except Exception as e:
                    fail_cnt += 1
                    try:
                        self.repo.record_scan_error(fpath, f"[커버 자동채우기 실패] {type(e).__name__}: {e}")
                    except Exception:
                        pass

            def on_done() -> None:
                self._refresh_audit_stats()
                self._load_audit_category()
                if hasattr(self, "_reload_library_table"):
                    self._reload_library_table()  # type: ignore[attr-defined]
                messagebox.showinfo(
                    "커버아트 자동 채우기 완료",
                    f"총 {len(checked_tracks)}곡 중 {success_cnt}곡에 커버아트가 성공적으로 적용되었습니다.\n"
                    f"(실패/미발견: {fail_cnt}곡)",
                )

            self.after(0, on_done)  # type: ignore[attr-defined]

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
                    try:
                        ok = embed_cover_art(fpath, img_bytes, mime)
                        if ok:
                            sync_single_file(fpath, self.repo)
                            success_cnt += 1
                        else:
                            fail_cnt += 1
                    except Exception as e:
                        fail_cnt += 1
                        try:
                            self.repo.record_scan_error(fpath, f"[커버 수동삽입 실패] {type(e).__name__}: {e}")
                        except Exception:
                            pass
                else:
                    fail_cnt += 1

            self._refresh_audit_stats()
            self._load_audit_category()
            if hasattr(self, "_reload_library_table"):
                self._reload_library_table()  # type: ignore[attr-defined]
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
            "태그 자동 저장 확인",
            f"선택한 {len(checked_tracks)}곡의 추론된 가수·제목 정보를 프로그램이 실제 음원 파일 태그(ID3/Vorbis/MP4)에 자동으로 일괄 저장할까요?",
        ):
            return

        success_cnt = 0
        fail_cnt = 0
        for t in checked_tracks:
            fpath = t.get("file_path")
            artist = t.get("artist") or ""
            title = t.get("title") or ""
            if fpath and Path(fpath).exists() and (artist or title):
                try:
                    ok = apply_fallback_tags_to_file(fpath, artist, title)
                    if ok:
                        sync_single_file(fpath, self.repo)
                        success_cnt += 1
                    else:
                        fail_cnt += 1
                except Exception as e:
                    fail_cnt += 1
                    err_msg = f"{type(e).__name__}: {e}"
                    try:
                        OPERATION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
                        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        with open(OPERATION_LOG_PATH, "a", encoding="utf-8") as f:
                            f.write(f"[{now_str}] [TAG_SAVE_ERROR] {fpath} -> {err_msg}\n")
                    except Exception:
                        pass
                    try:
                        self.repo.record_scan_error(fpath, f"[태그 저장 실패] {err_msg}")
                    except Exception:
                        pass
            else:
                fail_cnt += 1

        self._refresh_audit_stats()
        self._load_audit_category()
        if hasattr(self, "_reload_library_table"):
            self._reload_library_table()  # type: ignore[attr-defined]
        msg = f"{len(checked_tracks)}곡 중 {success_cnt}곡의 실제 파일에 메타데이터 태그가 저장되었습니다."
        if fail_cnt > 0:
            msg += f"\n(실패: {fail_cnt}곡 — 상세 원인은 ⚠️ 스캔 오류 파일 목록 탭 참조)"
        messagebox.showinfo("태그 저장 완료", msg)

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
        if hasattr(self, "_reload_library_table"):
            self._reload_library_table()  # type: ignore[attr-defined]
        messagebox.showinfo(
            "파일명 통일 완료",
            f"{len(checked_tracks)}곡 중 {renamed_cnt}개 파일명이 표준 형식으로 변경되었습니다.",
        )

    def _standardize_checked_naming_files(self) -> None:
        checked_tracks = [self._audit_row_meta[item_id] for item_id in self._audit_checked_items if item_id in self._audit_row_meta]
        if not checked_tracks:
            messagebox.showinfo("선택 필요", "표준화할 파일을 체크박스로 선택해 주세요.")
            return

        if not messagebox.askyesno(
            "파일명 표준화 확인",
            f"선택한 {len(checked_tracks)}개 파일의 이름을 '[가수] - [제목].[확장자]' 형식으로 일괄 변경하시겠습니까?",
        ):
            return

        renamed_cnt = 0
        fail_cnt = 0
        for t in checked_tracks:
            old_path = t.get("file_path")
            if not old_path or not Path(old_path).exists():
                fail_cnt += 1
                continue

            try:
                new_path = standardize_underscore_filename(old_path)
                if new_path and new_path != Path(old_path):
                    st = new_path.stat()
                    self.repo.update_track_path(
                        old_path=str(old_path),
                        new_path=str(new_path),
                        new_name=new_path.name,
                        new_ext=new_path.suffix.lstrip(".").lower(),
                        mtime=st.st_mtime,
                        file_size=st.st_size,
                    )
                    renamed_cnt += 1
                else:
                    fail_cnt += 1
            except Exception as e:
                fail_cnt += 1
                err_msg = f"{type(e).__name__}: {e}"
                try:
                    with open(OPERATION_LOG_PATH, "a", encoding="utf-8") as lf:
                        lf.write(f"[{datetime.now().isoformat()}] [RENAME_ERROR] {old_path} -> {err_msg}\n")
                except Exception:
                    pass
                try:
                    self.repo.record_scan_error(old_path, f"[파일명 표준화 실패] {err_msg}")
                except Exception:
                    pass

        self._refresh_audit_stats()
        self._load_audit_category()
        if hasattr(self, "_reload_library_table"):
            self._reload_library_table()  # type: ignore[attr-defined]

        messagebox.showinfo(
            "파일명 표준화 완료",
            f"{len(checked_tracks)}개 중 {renamed_cnt}개 파일명이 표준 형식으로 변경되었습니다.",
        )

    def _standardize_external_folder_dialog(self) -> None:
        folder = filedialog.askdirectory(title="일괄 파일명 표준화할 음악 폴더 선택")
        if not folder:
            return
        folder_path = Path(folder)
        if not folder_path.exists():
            return

        AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg", ".wma"}
        try:
            candidates = [
                f for f in folder_path.iterdir()
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS and parse_underscore_filename(f) is not None
            ]
        except Exception as e:
            messagebox.showerror("오류", f"폴더를 읽는 도중 오류가 발생했습니다: {e}")
            return

        candidate_count = len(candidates)
        if candidate_count == 0:
            messagebox.showinfo(
                "대상 없음",
                f"선택한 폴더에 '가수_제목' 형식의 음원 파일이 없습니다.\n\n폴더: {folder}",
            )
            return

        if not messagebox.askyesno(
            "폴더 일괄 변경 확인",
            f"선택한 폴더:\n{folder}\n\n폴더 내 {candidate_count}개의 '가수_제목' 형식 파일을 '[가수] - [제목]'으로 일괄 변경하시겠습니까?",
        ):
            return

        result = batch_standardize_underscore_directory(folder_path, self.repo)

        self._refresh_audit_stats()
        self._load_audit_category()
        if hasattr(self, "_reload_library_table"):
            self._reload_library_table()  # type: ignore[attr-defined]

        messagebox.showinfo(
            "파일명 표준화 완료",
            f"{result['renamed']}개 파일명 변경 완료 (오류: {result['failed']}건)",
        )
