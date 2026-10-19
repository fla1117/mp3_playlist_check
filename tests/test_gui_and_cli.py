"""Tests for config absolute paths, CLI spaced path handling, repository alias deletion, and GUI initialization."""
from pathlib import Path
from typer.testing import CliRunner

from src.cli import app
from src.config import DEFAULT_DATA_DIR, DEFAULT_DB_PATH, PROJECT_ROOT, SETTINGS_PATH
from src.db.repository import Repository
from src.gui import MusicCheckerGUI
from tests.test_scanner_and_db import create_dummy_mp3

runner = CliRunner()


def test_config_absolute_paths():
    """Verify that configuration paths are always absolute and anchored to project root."""
    assert PROJECT_ROOT.is_absolute()
    assert DEFAULT_DATA_DIR.is_absolute()
    assert DEFAULT_DB_PATH.is_absolute()
    assert SETTINGS_PATH.is_absolute()

    assert DEFAULT_DB_PATH == PROJECT_ROOT / "data" / "music_library.db"
    assert SETTINGS_PATH == PROJECT_ROOT / "data" / "settings.json"


def test_repository_delete_alias(tmp_path):
    """Verify Repository.delete_alias removes alias from DB and updates in-memory cache."""
    db_file = tmp_path / "alias_test.db"
    repo = Repository(db_file)

    # 1. Add alias
    repo.add_alias("뉴진스", "nwjns")
    assert repo.resolve_canonical_artist("nwjns") == "뉴진스"

    # 2. Delete alias
    deleted = repo.delete_alias("nwjns")
    assert deleted is True
    assert repo.resolve_canonical_artist("nwjns") == "nwjns"  # Returns raw since deleted

    # 3. Delete non-existent alias
    deleted_false = repo.delete_alias("nonexistent")
    assert deleted_false is False


def test_cli_scan_spaced_path_arguments(tmp_path):
    """Verify CLI scan correctly joins multiple arguments when unquoted path with spaces is passed."""
    # Create folder with spaces: e.g. "My Music Library 2026"
    spaced_dir = tmp_path / "My Music Library 2026"
    spaced_dir.mkdir(parents=True)

    song = spaced_dir / "test_song.mp3"
    create_dummy_mp3(song, title="Spaced Title", artist="Spaced Artist")

    db_file = tmp_path / "spaced_test.db"

    # Simulate passing unquoted spaced path as separate arguments:
    # "scan", "C:\...\My", "Music", "Library", "2026", "--db", db_file
    parent_prefix = str(tmp_path)
    # The tokens to pass
    tokens = [parent_prefix + "\\My", "Music", "Library", "2026"]

    args = ["scan"] + tokens + ["--db", str(db_file)]
    res = runner.invoke(app, args)

    assert res.exit_code == 0
    assert "발견된 총 파일 수" in res.output

    repo = Repository(db_file)
    tracks = repo.get_all_active_tracks()
    assert len(tracks) == 1
    assert tracks[0]["title"] == "Spaced Title"


def test_gui_headless_initialization(tmp_path):
    """Verify MusicCheckerGUI initializes all tabs and styles without errors."""
    import src.gui as gui_module

    # Confirm play_audio_file was removed per anti-slop / PRD conformance
    assert not hasattr(gui_module, "play_audio_file")

    db_file = tmp_path / "gui_init.db"
    gui_app = MusicCheckerGUI(db_path=db_file)

    # Verify window title
    assert "mp3_playlist_check" in gui_app.title()

    # Verify 4 tabs exist
    assert gui_app.notebook.index("end") == 4

    # Verify instances
    assert gui_app.repo is not None
    assert gui_app.engine is not None
    assert gui_app.extractor is not None

    # Verify pl_tree is placed inside pl_table_frame container (not directly in multi_frame)
    assert gui_app.pl_tree.master != gui_app.multi_frame
    assert gui_app.pl_tree.master.master == gui_app.multi_frame

    # Verify all 5 text entry widgets are native tk.Entry (not ttk.Entry) for Korean IME stability
    import tkinter as tk
    from tkinter import ttk

    assert isinstance(gui_app.yt_url_entry, tk.Entry) and not isinstance(gui_app.yt_url_entry, ttk.Entry)
    assert isinstance(gui_app.scan_dir_entry, tk.Entry) and not isinstance(gui_app.scan_dir_entry, ttk.Entry)
    assert isinstance(gui_app.lib_search_entry, tk.Entry) and not isinstance(gui_app.lib_search_entry, ttk.Entry)
    assert isinstance(gui_app.canon_entry, tk.Entry) and not isinstance(gui_app.canon_entry, ttk.Entry)
    assert isinstance(gui_app.alias_entry, tk.Entry) and not isinstance(gui_app.alias_entry, ttk.Entry)

    # Verify debounce and Korean space-insensitive search ("좋은날" matches "좋은 날")
    gui_app.all_library_tracks = [
        {
            "id": 1,
            "artist": "아이유",
            "title": "좋은 날",
            "album": "Real",
            "duration_sec": 233.0,
            "bitrate_kbps": 320,
            "file_ext": "mp3",
            "file_path": "C:/music/iu_good_day.mp3",
            "file_name": "좋은 날.mp3",
            "has_cover_art": 1,
        },
        {
            "id": 2,
            "artist": "NewJeans",
            "title": "Ditto",
            "album": "OMG",
            "duration_sec": 185.0,
            "bitrate_kbps": 320,
            "file_ext": "flac",
            "file_path": "C:/music/ditto.flac",
            "file_name": "Ditto.flac",
            "has_cover_art": 1,
        },
    ]

    # Test debounce trigger
    gui_app._on_search_key_release()
    assert gui_app._search_after_id is not None
    gui_app.after_cancel(gui_app._search_after_id)
    gui_app._search_after_id = None

    # Test space-insensitive search: "좋은날" matches "좋은 날"
    gui_app.lib_search_entry.delete(0, tk.END)
    gui_app.lib_search_entry.insert(0, "좋은날")
    gui_app._filter_library_table()

    children = gui_app.lib_tree.get_children()
    assert len(children) == 1
    vals = gui_app.lib_tree.item(children[0], "values")
    assert vals[3] == "좋은 날"

    # Test partial Korean match: "아이" matches "아이유"
    gui_app.lib_search_entry.delete(0, tk.END)
    gui_app.lib_search_entry.insert(0, "아이")
    gui_app._filter_library_table()

    children = gui_app.lib_tree.get_children()
    assert len(children) == 1
    vals = gui_app.lib_tree.item(children[0], "values")
    assert vals[2] == "아이유"

    # Test search clear
    gui_app._clear_search()
    assert gui_app.lib_search_var.get() == ""
    assert len(gui_app.lib_tree.get_children()) == 2

    # Verify get_entry_text_with_ime
    gui_app.lib_search_entry.delete(0, tk.END)
    gui_app.lib_search_entry.insert(0, "한글테스트")
    assert gui_module.get_entry_text_with_ime(gui_app.lib_search_entry) == "한글테스트"
    gui_app.lib_search_entry.delete(0, tk.END)

    # Verify _on_scan_finished triggers sync on library table and audit stats
    from unittest.mock import MagicMock
    from src.scanner.file_walker import ScanSummary

    gui_app._refresh_audit_stats = MagicMock()
    gui_app._load_audit_category = MagicMock()
    gui_app._reload_library_table = MagicMock()

    dummy_summary = ScanSummary(total_files=10, added=5, updated=2, skipped=3)
    gui_app._on_scan_finished(dummy_summary)

    gui_app._reload_library_table.assert_called_once()
    gui_app._refresh_audit_stats.assert_called_once()
    gui_app._load_audit_category.assert_called_once()

    gui_app.destroy()


def test_run_gui_bat_crlf_and_ascii():
    """Verify run_gui.bat is 100% pure ASCII and uses Windows CRLF line endings."""
    bat_file = PROJECT_ROOT / "run_gui.bat"
    assert bat_file.exists()

    raw_bytes = bat_file.read_bytes()
    assert len(raw_bytes) > 0

    # 1. Pure ASCII validation (< 128)
    assert all(b < 128 for b in raw_bytes), "run_gui.bat contains non-ASCII characters"

    # 2. CRLF line endings validation
    assert b"\r\n" in raw_bytes, "run_gui.bat must use CRLF (\\r\\n) line endings"
    crlf_count = raw_bytes.count(b"\r\n")
    lf_count = raw_bytes.count(b"\n")
    assert crlf_count == lf_count, "run_gui.bat contains standalone LF line endings without CR"
