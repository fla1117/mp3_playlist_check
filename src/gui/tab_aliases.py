"""Tab 4: Artist Aliases Management UI and event handlers."""
import tkinter as tk
from tkinter import messagebox, ttk

from src.db.repository import Repository


class AliasesTabMixin:
    """Mixin implementing Tab 4: Artist alias dictionary management."""

    tab_alias: ttk.Frame
    card_bg: str
    canon_alias_var: tk.StringVar
    canon_entry: tk.Entry
    new_alias_var: tk.StringVar
    alias_entry: tk.Entry
    alias_tree: ttk.Treeview
    repo: Repository

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
