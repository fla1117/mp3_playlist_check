"""Main GUI Application Window combining tab mixins and modern theme."""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Dict, Optional, Set

# Ensure project root is in sys.path
PROJECT_ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT_DIR))

from src.config import DEFAULT_DB_PATH
from src.db.repository import Repository
from src.gui.tab_aliases import AliasesTabMixin
from src.gui.tab_audit import AuditTabMixin
from src.gui.tab_library import LibraryTabMixin
from src.gui.tab_youtube import YouTubeTabMixin
from src.gui.theme_and_ime import ThemeMixin, load_settings
from src.matcher.scorer import MatcherEngine
from src.youtube.extractor import YouTubeExtractor


class MusicCheckerGUI(
    tk.Tk,
    ThemeMixin,
    YouTubeTabMixin,
    LibraryTabMixin,
    AuditTabMixin,
    AliasesTabMixin,
):
    """Main Application Window."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
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


def main() -> None:
    """GUI entrypoint."""
    app = MusicCheckerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
