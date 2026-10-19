"""Integration tests for Scanner, Database Repository, Incremental Sync, and CLI."""
import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from mutagen.id3 import ID3, APIC, TIT2, TPE1
from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from typer.testing import CliRunner

from src.cli import app
from src.db.repository import Repository
from src.matcher.scorer import MatchStatus
from src.scanner.file_walker import scan_directory
from src.youtube.extractor import YouTubeExtractResult, YouTubeTrackInfo

runner = CliRunner()

# 1x1 minimal JPEG bytes
JPEG_1X1_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010101004800480000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333430ffc0000b080001000101011100ffda0008010100003f00bf00ffd9"
)


def create_dummy_mp3(path: Path, title: str = "", artist: str = "", with_cover: bool = False, mojibake: bool = False):
    """Create a minimal valid MP3 file with MPEG-1 frames and optional ID3 tags."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * 10)

    audio = MP3(str(path))
    audio.add_tags()

    if mojibake and artist:
        # Save CP949 string as Latin-1 encoding=0
        raw_cp949_latin1 = artist.encode("cp949").decode("latin-1")
        audio.tags.add(TPE1(encoding=0, text=[raw_cp949_latin1]))
    elif artist:
        audio.tags.add(TPE1(encoding=3, text=[artist]))

    if title:
        audio.tags.add(TIT2(encoding=3, text=[title]))

    if with_cover:
        audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=JPEG_1X1_BYTES))

    audio.save()


def create_dummy_wav(path: Path, title: str = "", artist: str = ""):
    """Create a minimal valid WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44100)
        wav_file.writeframes(struct.pack("<h", 0) * 44100)

    audio = WAVE(str(path))
    audio.add_tags()
    if title:
        audio.tags.add(TIT2(encoding=3, text=[title]))
    if artist:
        audio.tags.add(TPE1(encoding=3, text=[artist]))
    audio.save()


@pytest.fixture
def test_env(tmp_path):
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    db_file = tmp_path / "test.db"
    repo = Repository(db_file)
    return music_dir, db_file, repo


def test_incremental_scan_and_sync(test_env):
    music_dir, db_file, repo = test_env

    # 1. Add two songs
    song1 = music_dir / "IU_GoodDay.mp3"
    create_dummy_mp3(song1, title="좋은 날", artist="아이유", with_cover=True)

    song2 = music_dir / "BTS_Dynamite.wav"
    create_dummy_wav(song2, title="Dynamite", artist="방탄소년단")

    # Initial scan
    s1 = scan_directory(music_dir, repo)
    assert s1.total_files == 2
    assert s1.added == 2
    assert s1.skipped == 0
    assert s1.moved == 0
    assert s1.missing == 0
    assert s1.errors == 0

    # 2. Rescan without changes -> should skip all
    s2 = scan_directory(music_dir, repo)
    assert s2.total_files == 2
    assert s2.added == 0
    assert s2.skipped == 2

    # 3. Move song2 to a subfolder
    sub_dir = music_dir / "Pop"
    sub_dir.mkdir()
    song2_moved = sub_dir / "BTS_Dynamite_Renamed.wav"
    song2.rename(song2_moved)

    s3 = scan_directory(music_dir, repo)
    assert s3.moved == 1
    assert s3.skipped == 1  # song1 skipped
    assert s3.added == 0

    # Check DB updated path
    t2 = repo.get_track_by_path(str(song2_moved.resolve()))
    assert t2 is not None
    assert t2["is_missing"] == 0

    # 4. Delete song1
    song1.unlink()
    s4 = scan_directory(music_dir, repo)
    assert s4.total_files == 1
    assert s4.missing == 1  # song1 marked missing

    t1 = repo.get_track_by_path(str(song1.resolve()))
    assert t1 is not None
    assert t1["is_missing"] == 1


def test_mojibake_recovery_in_scan(test_env):
    music_dir, _, repo = test_env
    song = music_dir / "mojibake.mp3"
    create_dummy_mp3(song, title="좋은 날", artist="아이유", mojibake=True)

    scan_directory(music_dir, repo)
    t = repo.get_track_by_path(str(song.resolve()))
    assert t is not None
    assert t["artist"] == "아이유"
    assert t["norm_artist"] == "아이유"


def test_fallback_tag_source(test_env):
    music_dir, _, repo = test_env
    # File without tags, named with 'Artist - Title' pattern
    song = music_dir / "01. NewJeans - Hype Boy.mp3"
    # Create empty tags
    create_dummy_mp3(song, title="", artist="")

    scan_directory(music_dir, repo)
    t = repo.get_track_by_path(str(song.resolve()))
    assert t is not None
    assert t["artist"] == "NewJeans"
    assert t["title"] == "Hype Boy"
    assert t["tag_source"] == "FILENAME_FALLBACK"


def test_cover_art_detection(test_env):
    music_dir, _, repo = test_env

    # Embedded cover
    song1 = music_dir / "embedded.mp3"
    create_dummy_mp3(song1, title="Song1", artist="Artist1", with_cover=True)

    # External cover in folder
    album_dir = music_dir / "AlbumFolder"
    album_dir.mkdir()
    song2 = album_dir / "external.mp3"
    create_dummy_mp3(song2, title="Song2", artist="Artist2", with_cover=False)
    cover_img = album_dir / "cover.jpg"
    cover_img.write_bytes(JPEG_1X1_BYTES)

    # No cover
    song3 = music_dir / "nocover.mp3"
    create_dummy_mp3(song3, title="Song3", artist="Artist3", with_cover=False)

    scan_directory(music_dir, repo)

    t1 = repo.get_track_by_path(str(song1.resolve()))
    assert t1["has_cover_art"] == 1
    assert t1["cover_width"] == 1
    assert t1["cover_height"] == 1

    t2 = repo.get_track_by_path(str(song2.resolve()))
    assert t2["has_cover_art"] == 2

    t3 = repo.get_track_by_path(str(song3.resolve()))
    assert t3["has_cover_art"] == 0


def test_corrupt_file_handling(test_env):
    music_dir, _, repo = test_env
    corrupt_file = music_dir / "corrupted.mp3"
    corrupt_file.write_bytes(b"INVALID_HEADER_GARBAGE_BYTES_1234567890")

    summary = scan_directory(music_dir, repo)
    assert summary.errors == 1
    errs = repo.get_scan_errors()
    assert len(errs) == 1
    assert "corrupted.mp3" in errs[0]["file_path"]


def test_quality_audit_reports(test_env):
    music_dir, _, repo = test_env
    # 1. No cover
    s1 = music_dir / "nocover.mp3"
    create_dummy_mp3(s1, title="No Cover Song", artist="Artist A", with_cover=False)

    # 2. Missing tag
    s2 = music_dir / "02. Artist B - Fallback Song.mp3"
    create_dummy_mp3(s2, title="", artist="", with_cover=True)

    # 3. Duplicate
    s3 = music_dir / "dup1.mp3"
    create_dummy_mp3(s3, title="Same Song", artist="Same Artist", with_cover=True)
    s4 = music_dir / "dup2.wav"
    create_dummy_wav(s4, title="Same Song", artist="Same Artist")

    scan_directory(music_dir, repo)

    # Missing covers
    missing_covers = repo.get_missing_covers()
    assert any(t["title"] == "No Cover Song" for t in missing_covers)

    # Missing tags
    missing_tags = repo.get_missing_tags()
    assert any(t["tag_source"] == "FILENAME_FALLBACK" for t in missing_tags)

    # Duplicates
    dups = repo.get_duplicates()
    assert len(dups) >= 2
    assert all(t["norm_title"] == "samesong" for t in dups)


def test_cli_commands(test_env):
    music_dir, db_file, _ = test_env
    song = music_dir / "IU_GoodDay.mp3"
    create_dummy_mp3(song, title="좋은 날", artist="아이유", with_cover=True)

    # 1. scan command
    res_scan = runner.invoke(app, ["scan", str(music_dir), "--db", str(db_file)])
    assert res_scan.exit_code == 0
    assert "발견된 총 파일 수" in res_scan.output

    # 2. stats commands
    res_stats = runner.invoke(app, ["stats", "--db", str(db_file)])
    assert res_stats.exit_code == 0
    assert "종합 통계" in res_stats.output

    res_stats_covers = runner.invoke(app, ["stats", "--missing-covers", "--db", str(db_file)])
    assert res_stats_covers.exit_code == 0

    res_stats_tags = runner.invoke(app, ["stats", "--missing-tags", "--db", str(db_file)])
    assert res_stats_tags.exit_code == 0

    res_stats_dups = runner.invoke(app, ["stats", "--duplicates", "--db", str(db_file)])
    assert res_stats_dups.exit_code == 0

    # 3. alias commands
    res_alias_list = runner.invoke(app, ["alias", "list", "--db", str(db_file)])
    assert res_alias_list.exit_code == 0
    assert "아이유" in res_alias_list.output

    res_alias_add = runner.invoke(app, ["alias", "add", "아이유", "이지금", "--db", str(db_file)])
    assert res_alias_add.exit_code == 0
    assert "별칭 등록 완료" in res_alias_add.output

    # 4. check command with mocked YouTube extractor
    mock_extract_res = YouTubeExtractResult(
        url="https://www.youtube.com/watch?v=mocked12345",
        is_playlist=False,
        tracks=[
            YouTubeTrackInfo(
                video_id="mocked12345",
                raw_title="[MV] IU(아이유) - 좋은 날",
                uploader="1theK",
                duration_sec=0.26,  # matches dummy mp3 duration
            )
        ],
    )

    with patch("src.cli.YouTubeExtractor.extract", return_value=mock_extract_res):
        res_check = runner.invoke(app, ["check", "https://www.youtube.com/watch?v=mocked12345", "--db", str(db_file)])
        assert res_check.exit_code == 0
        assert "판별 결과: 보유 중" in res_check.output or "EXACT_MATCH" in res_check.output


def test_mark_missing_tracks_prefix_boundary(tmp_path):
    """Verify that scanning /music/Pop does NOT mark tracks in sibling /music/PopRock as missing."""
    base_dir = tmp_path / "music"
    pop_dir = base_dir / "Pop"
    pop_rock_dir = base_dir / "PopRock"
    pop_dir.mkdir(parents=True)
    pop_rock_dir.mkdir(parents=True)

    db_file = tmp_path / "prefix_test.db"
    repo = Repository(db_file)

    song_pop = pop_dir / "pop_song.mp3"
    create_dummy_mp3(song_pop, title="Pop Song", artist="Singer A")

    song_poprock = pop_rock_dir / "rock_song.mp3"
    create_dummy_mp3(song_poprock, title="Rock Song", artist="Singer B")

    # 1. First scan PopRock
    scan_directory(pop_rock_dir, repo)
    t_rock = repo.get_track_by_path(str(song_poprock.resolve()))
    assert t_rock is not None
    assert t_rock["is_missing"] == 0

    # 2. Now scan Pop
    scan_directory(pop_dir, repo)
    t_pop = repo.get_track_by_path(str(song_pop.resolve()))
    assert t_pop is not None
    assert t_pop["is_missing"] == 0

    # Crucial check: song_poprock in PopRock must NOT be marked missing when Pop is scanned
    t_rock_recheck = repo.get_track_by_path(str(song_poprock.resolve()))
    assert t_rock_recheck["is_missing"] == 0, "PopRock song was falsely marked missing when Pop was scanned!"

