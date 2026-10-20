"""Unit and integration tests for v0.3.0 enhancements.

Covers:
- Tag normalizer: sanitize_filename, apply_fallback_tags_to_file, rename_file_standard
- Cover manager: extract_cover_bytes_from_file, embed_cover_art, fetch_cover_art_auto
- Repository duplicates: canonical alias clustering, featuring split clustering, sorting
- Repository deletion: delete_tracks_by_ids and FTS sync
- CSV export & UTF-8 with BOM (utf-8-sig) verification
"""
import csv
import io
import json
import os
from pathlib import Path
import stat
import struct
from unittest.mock import MagicMock, patch
import wave

import pytest
from mutagen.id3 import ID3, APIC, TIT2, TPE1
from mutagen.mp3 import MP3
from mutagen.wave import WAVE

from src.db.repository import Repository
from src.matcher.scorer import MatchStatus
from src.scanner.cover_manager import (
    embed_cover_art,
    extract_cover_bytes_from_file,
    fetch_cover_art_auto,
)
from src.scanner.file_walker import sync_single_file
from src.scanner.tag_normalizer import (
    apply_fallback_tags_to_file,
    batch_standardize_underscore_directory,
    parse_underscore_filename,
    rename_file_standard,
    sanitize_filename,
    standardize_underscore_filename,
)

# 1x1 minimal JPEG bytes
JPEG_1X1_BYTES = bytes.fromhex(
    "ffd8ffe000104a46494600010101004800480000ffdb004300080606070605080707070909080a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e2720222c231c1c2837292c30313434341f27393d38323c2e333430ffc0000b080001000101011100ffda0008010100003f00bf00ffd9"
)


def create_test_mp3(path: Path, title: str = "", artist: str = "", album: str = "", with_cover: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    path.write_bytes(frame * 10)

    audio = MP3(str(path))
    audio.add_tags()
    if artist:
        audio.tags.add(TPE1(encoding=3, text=[artist]))
    if title:
        audio.tags.add(TIT2(encoding=3, text=[title]))
    if album:
        from mutagen.id3 import TALB
        audio.tags.add(TALB(encoding=3, text=[album]))
    if with_cover:
        audio.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=JPEG_1X1_BYTES))
    audio.save()


def create_dummy_wav(path: Path, title: str = "", artist: str = "") -> None:
    """Create a minimal valid WAV file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(44100)
        wav_file.writeframes(struct.pack("<h", 0) * 44100)

    if title or artist:
        audio = WAVE(str(path))
        audio.add_tags()
        if title:
            audio.tags.add(TIT2(encoding=3, text=[title]))
        if artist:
            audio.tags.add(TPE1(encoding=3, text=[artist]))
        audio.save()


def test_sanitize_filename() -> None:
    assert sanitize_filename("A/B\\C:D*E?F\"G<H>I|J") == "A_B_C_D_E_F_G_H_I_J"
    assert sanitize_filename("  Hello... World.mp3...  ") == "Hello... World.mp3"
    assert sanitize_filename("") == "Unknown"
    assert sanitize_filename("Normal Title") == "Normal Title"


def test_tag_normalizer_apply_tags_and_rename(tmp_path: Path) -> None:
    mp3_path = tmp_path / "raw_track.mp3"
    create_test_mp3(mp3_path, title="", artist="")

    # Apply fallback tags
    ok = apply_fallback_tags_to_file(mp3_path, artist="NewJeans", title="Ditto")
    assert ok is True

    # Check tags applied
    audio = MP3(str(mp3_path))
    assert audio.tags.get("TPE1").text[0] == "NewJeans"
    assert audio.tags.get("TIT2").text[0] == "Ditto"

    # Rename file to standard format
    new_path = rename_file_standard(mp3_path, artist="NewJeans", title="Ditto")
    assert new_path is not None
    assert Path(new_path).name == "NewJeans - Ditto.mp3"
    assert Path(new_path).exists()
    assert not mp3_path.exists()

    # Test collision handling: create another file and rename to the same
    dup_mp3 = tmp_path / "another_raw.mp3"
    create_test_mp3(dup_mp3, title="", artist="")
    collided_path = rename_file_standard(dup_mp3, artist="NewJeans", title="Ditto")
    assert Path(collided_path).name == "NewJeans - Ditto (1).mp3"
    assert Path(collided_path).exists()


def test_cover_manager_embed_and_extract(tmp_path: Path) -> None:
    mp3_path = tmp_path / "song.mp3"
    create_test_mp3(mp3_path, title="Song", artist="Artist", with_cover=False)

    # Initially no cover
    res = extract_cover_bytes_from_file(mp3_path)
    assert res is None

    # Embed cover
    ok = embed_cover_art(mp3_path, JPEG_1X1_BYTES, "image/jpeg")
    assert ok is True

    # Extract back and verify
    res = extract_cover_bytes_from_file(mp3_path)
    assert res is not None
    cov_bytes, mime = res
    assert cov_bytes == JPEG_1X1_BYTES
    assert mime == "image/jpeg"

    # Test sync_single_file updates database
    db_file = tmp_path / "test.db"
    repo = Repository(db_file)
    track_id = sync_single_file(mp3_path, repo)
    assert track_id > 0
    t = repo.get_track_by_path(str(mp3_path.resolve()))
    assert t is not None
    assert t["has_cover_art"] == 1


def test_cover_manager_auto_fetch_album_sharing(tmp_path: Path) -> None:
    album_dir = tmp_path / "album_folder"
    track1_path = album_dir / "01. Song1.mp3"
    track2_path = album_dir / "02. Song2.mp3"
    create_test_mp3(track1_path, title="Song1", artist="Artist", album="Great Album", with_cover=True)
    create_test_mp3(track2_path, title="Song2", artist="Artist", album="Great Album", with_cover=False)

    track1_dict = {
        "file_path": str(track1_path.resolve()),
        "artist": "Artist",
        "title": "Song1",
        "album": "Great Album",
        "has_cover_art": 1,
    }
    track2_dict = {
        "file_path": str(track2_path.resolve()),
        "artist": "Artist",
        "title": "Song2",
        "album": "Great Album",
        "has_cover_art": 0,
    }

    # fetch_cover_art_auto for track2 should share from track1
    res = fetch_cover_art_auto(track2_dict, [track1_dict, track2_dict])
    assert res is not None
    cov_bytes, mime = res
    assert cov_bytes == JPEG_1X1_BYTES
    assert mime == "image/jpeg"


def test_cover_manager_auto_fetch_itunes_fallback(tmp_path: Path) -> None:
    track_path = tmp_path / "solo_song.mp3"
    create_test_mp3(track_path, title="Super Shy", artist="NewJeans", with_cover=False)

    track_dict = {
        "file_path": str(track_path.resolve()),
        "artist": "NewJeans",
        "title": "Super Shy",
        "album": "Get Up",
        "has_cover_art": 0,
    }

    # Mock iTunes API search and image download
    mock_api_response = json.dumps({
        "resultCount": 1,
        "results": [
            {
                "artworkUrl100": "https://example.com/cover100.jpg",
                "collectionName": "Get Up",
                "artistName": "NewJeans",
            }
        ]
    }).encode("utf-8")

    class MockHTTPResponse:
        def __init__(self, data: bytes):
            self._data = data
        def read(self) -> bytes:
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    def mock_urlopen(req, timeout=10):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        if "itunes.apple.com" in url:
            return MockHTTPResponse(mock_api_response)
        elif "example.com" in url:
            return MockHTTPResponse(JPEG_1X1_BYTES)
        raise ValueError(f"Unexpected url {url}")

    with patch("urllib.request.urlopen", side_effect=mock_urlopen):
        res = fetch_cover_art_auto(track_dict, [track_dict])
        assert res is not None
        cov_bytes, mime = res
        assert cov_bytes == JPEG_1X1_BYTES
        assert mime == "image/jpeg"


def test_cover_manager_auto_fetch_not_found_returns_none(tmp_path: Path) -> None:
    track_dict = {
        "file_path": str(tmp_path / "unknown.mp3"),
        "artist": "NonExistentArtistXYZ123",
        "title": "NonExistentSongXYZ123",
        "album": "",
        "has_cover_art": 0,
    }

    mock_empty_response = json.dumps({"resultCount": 0, "results": []}).encode("utf-8")

    class MockEmptyHTTPResponse:
        def read(self) -> bytes:
            return mock_empty_response
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    with patch("urllib.request.urlopen", return_value=MockEmptyHTTPResponse()):
        res = fetch_cover_art_auto(track_dict, [track_dict])
        assert res is None


def test_advanced_duplicate_clustering_and_canonical_aliases(tmp_path: Path) -> None:
    db_file = tmp_path / "dups_test.db"
    repo = Repository(db_file)

    # Register canonical alias: iu <-> 아이유
    repo.add_alias("아이유", "iu")

    # Insert duplicate pair 1 (Alias clustering):
    # Track 1: Artist "아이유", Title "좋은 날", 320kbps, with cover
    # Track 2: Artist "IU", Title "좋은 날", 192kbps, no cover
    repo.upsert_track({
        "file_path": "C:/music/iu_320.mp3",
        "file_name": "iu_320.mp3",
        "file_ext": "mp3",
        "file_size": 10000000,
        "mtime": 1700000000,
        "partial_hash": "hash1",
        "artist": "아이유",
        "title": "좋은 날",
        "norm_artist": "아이유",
        "norm_title": "좋은 날",
        "album": "Real",
        "duration_sec": 233.0,
        "bitrate_kbps": 320,
        "has_cover_art": 1,
    })
    repo.upsert_track({
        "file_path": "C:/music/iu_192.mp3",
        "file_name": "iu_192.mp3",
        "file_ext": "mp3",
        "file_size": 5000000,
        "mtime": 1700000000,
        "partial_hash": "hash2",
        "artist": "IU",
        "title": "좋은 날",
        "norm_artist": "iu",
        "norm_title": "좋은 날",
        "album": "Real",
        "duration_sec": 233.0,
        "bitrate_kbps": 192,
        "has_cover_art": 0,
    })

    # Insert duplicate pair 2 (Featuring split clustering):
    # Track 3: Artist "아이유", Title "잔소리 (feat. 임슬옹)"
    # Track 4: Artist "아이유 (with 임슬옹)", Title "잔소리"
    repo.upsert_track({
        "file_path": "C:/music/nagging_1.mp3",
        "file_name": "nagging_1.mp3",
        "file_ext": "mp3",
        "file_size": 8000000,
        "mtime": 1700000000,
        "partial_hash": "hash3",
        "artist": "아이유",
        "title": "잔소리 (feat. 임슬옹)",
        "norm_artist": "아이유",
        "norm_title": "잔소리 feat 임슬옹",
        "album": "",
        "duration_sec": 213.0,
        "bitrate_kbps": 320,
        "has_cover_art": 1,
    })
    repo.upsert_track({
        "file_path": "C:/music/nagging_2.mp3",
        "file_name": "nagging_2.mp3",
        "file_ext": "mp3",
        "file_size": 4000000,
        "mtime": 1700000000,
        "partial_hash": "hash4",
        "artist": "아이유 (with 임슬옹)",
        "title": "잔소리",
        "norm_artist": "아이유 with 임슬옹",
        "norm_title": "잔소리",
        "album": "",
        "duration_sec": 213.0,
        "bitrate_kbps": 192,
        "has_cover_art": 0,
    })

    # Non-duplicate track (should NOT be returned in duplicates)
    repo.upsert_track({
        "file_path": "C:/music/unique.mp3",
        "file_name": "unique.mp3",
        "file_ext": "mp3",
        "file_size": 6000000,
        "mtime": 1700000000,
        "partial_hash": "hash5",
        "artist": "태연",
        "title": "I",
        "norm_artist": "태연",
        "norm_title": "i",
        "album": "",
        "duration_sec": 200.0,
        "bitrate_kbps": 320,
        "has_cover_art": 1,
    })

    dups = repo.get_duplicates()
    assert len(dups) == 4

    # Group by dup_group_key
    groups = {}
    for d in dups:
        assert "dup_group_key" in d
        groups.setdefault(d["dup_group_key"], []).append(d)

    assert len(groups) == 2

    # Verify quality ranking in each group: index 0 must be 320k with cover
    for gkey, items in groups.items():
        assert len(items) == 2
        best, inferior = items[0], items[1]
        assert best["bitrate_kbps"] == 320
        assert best["has_cover_art"] == 1
        assert inferior["bitrate_kbps"] == 192


def test_duplicate_sorting_bitrate_priority_over_cover_art(tmp_path: Path) -> None:
    """Verify that audio bitrate and format strictly take precedence over cover art presence."""
    db_file = tmp_path / "bitrate_dups_test.db"
    repo = Repository(db_file)

    # 1. Bitrate vs Cover Art test:
    # 320k (no cover) vs 160k (has cover)
    # 320k MUST be 1st (preserved), 160k MUST be 2nd (inferior/deletion candidate)
    repo.upsert_track({
        "file_path": "C:/music/kwill_160_with_cover.mp3",
        "file_name": "kwill_160_with_cover.mp3",
        "file_ext": "mp3",
        "file_size": 4000000,
        "mtime": 1700000000,
        "partial_hash": "kwill_h1",
        "artist": "케이윌",
        "title": "Love Blossom",
        "norm_artist": "케이윌",
        "norm_title": "love blossom",
        "duration_sec": 215.0,
        "bitrate_kbps": 160,
        "has_cover_art": 1,
        "cover_width": 500,
        "cover_height": 500,
    })
    repo.upsert_track({
        "file_path": "C:/music/kwill_320_no_cover.mp3",
        "file_name": "kwill_320_no_cover.mp3",
        "file_ext": "mp3",
        "file_size": 8000000,
        "mtime": 1700000000,
        "partial_hash": "kwill_h2",
        "artist": "케이윌",
        "title": "Love Blossom",
        "norm_artist": "케이윌",
        "norm_title": "love blossom",
        "duration_sec": 215.0,
        "bitrate_kbps": 320,
        "has_cover_art": 0,
        "cover_width": 0,
        "cover_height": 0,
    })

    # 2. Cover resolution tiebreaker test:
    # Both 320k with cover, but 480x480 vs 240x240
    repo.upsert_track({
        "file_path": "C:/music/2bic_240.mp3",
        "file_name": "2bic_240.mp3",
        "file_ext": "mp3",
        "file_size": 7900000,
        "mtime": 1700000000,
        "partial_hash": "2bic_h1",
        "artist": "투빅, 다비치",
        "title": "오늘같은 밤이면",
        "norm_artist": "투빅 다비치",
        "norm_title": "오늘같은 밤이면",
        "duration_sec": 220.0,
        "bitrate_kbps": 320,
        "has_cover_art": 1,
        "cover_width": 240,
        "cover_height": 240,
    })
    repo.upsert_track({
        "file_path": "C:/music/2bic_480.mp3",
        "file_name": "2bic_480.mp3",
        "file_ext": "mp3",
        "file_size": 8100000,
        "mtime": 1700000000,
        "partial_hash": "2bic_h2",
        "artist": "투빅, 다비치",
        "title": "오늘같은 밤이면",
        "norm_artist": "투빅 다비치",
        "norm_title": "오늘같은 밤이면",
        "duration_sec": 220.0,
        "bitrate_kbps": 320,
        "has_cover_art": 1,
        "cover_width": 480,
        "cover_height": 480,
    })

    # 3. Format weight test:
    # FLAC vs MP3 320k
    repo.upsert_track({
        "file_path": "C:/music/iu_mp3.mp3",
        "file_name": "iu_mp3.mp3",
        "file_ext": "mp3",
        "file_size": 9000000,
        "mtime": 1700000000,
        "partial_hash": "iu_mp3_h",
        "artist": "아이유",
        "title": "너랑 나",
        "norm_artist": "아이유",
        "norm_title": "너랑 나",
        "duration_sec": 240.0,
        "bitrate_kbps": 320,
        "has_cover_art": 1,
    })
    repo.upsert_track({
        "file_path": "C:/music/iu_flac.flac",
        "file_name": "iu_flac.flac",
        "file_ext": "flac",
        "file_size": 25000000,
        "mtime": 1700000000,
        "partial_hash": "iu_flac_h",
        "artist": "아이유",
        "title": "너랑 나",
        "norm_artist": "아이유",
        "norm_title": "너랑 나",
        "duration_sec": 240.0,
        "bitrate_kbps": 900,
        "has_cover_art": 0,
    })

    dups = repo.get_duplicates()
    groups = {}
    for d in dups:
        groups.setdefault(d["dup_group_key"], []).append(d)

    assert len(groups) == 3

    # Check 1: 320k (no cover) beats 160k (has cover)
    kwill_group = [grp for grp in groups.values() if any("Love Blossom" in x["title"] for x in grp)][0]
    assert len(kwill_group) == 2
    best_kwill = kwill_group[0]
    inferior_kwill = kwill_group[1]
    assert best_kwill["bitrate_kbps"] == 320
    assert best_kwill["has_cover_art"] == 0
    assert inferior_kwill["bitrate_kbps"] == 160
    assert inferior_kwill["has_cover_art"] == 1

    # Check 2: 480x480 beats 240x240 when bitrates are equal
    twobic_group = [grp for grp in groups.values() if any("오늘같은 밤이면" in x["title"] for x in grp)][0]
    assert len(twobic_group) == 2
    assert twobic_group[0]["cover_width"] == 480
    assert twobic_group[1]["cover_width"] == 240

    # Check 3: FLAC beats MP3
    iu_group = [grp for grp in groups.values() if any("너랑 나" in x["title"] for x in grp)][0]
    assert len(iu_group) == 2
    assert iu_group[0]["file_ext"] == "flac"
    assert iu_group[1]["file_ext"] == "mp3"


def test_repository_delete_tracks_by_ids(tmp_path: Path) -> None:
    db_file = tmp_path / "del_test.db"
    repo = Repository(db_file)

    t1_id = repo.upsert_track({
        "file_path": "C:/music/t1.mp3",
        "file_name": "t1.mp3",
        "file_ext": "mp3",
        "file_size": 1000,
        "mtime": 1700000000,
        "partial_hash": "h1",
        "artist": "Artist",
        "title": "Song One",
        "norm_artist": "artist",
        "norm_title": "song one",
        "duration_sec": 120.0,
    })
    t2_id = repo.upsert_track({
        "file_path": "C:/music/t2.mp3",
        "file_name": "t2.mp3",
        "file_ext": "mp3",
        "file_size": 1000,
        "mtime": 1700000000,
        "partial_hash": "h2",
        "artist": "Artist",
        "title": "Song Two",
        "norm_artist": "artist",
        "norm_title": "song two",
        "duration_sec": 120.0,
    })

    assert len(repo.get_all_active_tracks()) == 2

    # Delete t1
    del_cnt = repo.delete_tracks_by_ids([t1_id])
    assert del_cnt == 1

    remaining = repo.get_all_active_tracks()
    assert len(remaining) == 1
    assert remaining[0]["id"] == t2_id


def test_csv_export_utf8_sig_compatibility() -> None:
    test_results = [
        {
            "num": 1,
            "status_str": "✅ 보유",
            "yt_title": "아이유 (IU) - 좋은 날 (Good Day)",
            "duration": "03:53",
            "local_match": "아이유 - 좋은 날",
            "score": "98%",
            "path": "F:\\음악\\아이유 - 좋은 날.mp3",
            "reason": "곡명/가수 완벽 일치",
        },
        {
            "num": 2,
            "status_str": "❌ 미보유",
            "yt_title": "NewJeans - Ditto",
            "duration": "03:05",
            "local_match": "-",
            "score": "0%",
            "path": "-",
            "reason": "검색 결과 없음",
        },
    ]

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["순번", "판별 상태", "YouTube 제목", "영상 길이", "로컬 매칭 음원", "일치율", "로컬 파일 경로", "판별 사유/비고"])
    for r in test_results:
        writer.writerow([
            r["num"],
            r["status_str"],
            r["yt_title"],
            r["duration"],
            r["local_match"],
            r["score"],
            r["path"],
            r["reason"],
        ])

    csv_text = out.getvalue()
    raw_bytes = csv_text.encode("utf-8-sig")

    # Verify UTF-8 BOM is present
    assert raw_bytes[:3] == b"\xef\xbb\xbf"

    # Verify decoding produces exact Korean text
    decoded_text = raw_bytes.decode("utf-8-sig")
    assert "아이유" in decoded_text
    assert "좋은 날" in decoded_text
    assert "NewJeans" in decoded_text


def test_readonly_file_handling(tmp_path: Path) -> None:
    """Verify that read-only files can have cover art embedded, tags updated, and be deleted."""
    mp3_path = tmp_path / "readonly_track.mp3"
    create_test_mp3(mp3_path, title="Old Title", artist="Old Artist", with_cover=False)

    # 1. Set file to read-only (Windows FILE_ATTRIBUTE_READONLY)
    os.chmod(mp3_path, stat.S_IREAD)
    st = mp3_path.stat()
    assert not (st.st_mode & stat.S_IWRITE)

    # 2. Test embed_cover_art on read-only file
    ok_cover = embed_cover_art(mp3_path, JPEG_1X1_BYTES, "image/jpeg")
    assert ok_cover is True
    cover_data = extract_cover_bytes_from_file(mp3_path)
    assert cover_data is not None
    assert cover_data[0] == JPEG_1X1_BYTES

    # 3. Set file back to read-only and test apply_fallback_tags_to_file
    os.chmod(mp3_path, stat.S_IREAD)
    assert not (mp3_path.stat().st_mode & stat.S_IWRITE)

    ok_tags = apply_fallback_tags_to_file(mp3_path, artist="New Artist", title="New Title", album="New Album")
    assert ok_tags is True
    audio = MP3(str(mp3_path))
    assert audio.tags.get("TPE1").text[0] == "New Artist"
    assert audio.tags.get("TIT2").text[0] == "New Title"

    # 4. Set file back to read-only and test rename_file_standard
    os.chmod(mp3_path, stat.S_IREAD)
    assert not (mp3_path.stat().st_mode & stat.S_IWRITE)

    renamed_p = rename_file_standard(mp3_path, "New Artist", "New Title")
    assert renamed_p.exists()
    assert renamed_p.name == "New Artist - New Title.mp3"

    # 5. Set renamed file to read-only and verify deletion logic (ensure writable before unlink)
    os.chmod(renamed_p, stat.S_IREAD)
    assert not (renamed_p.stat().st_mode & stat.S_IWRITE)

    st_del = renamed_p.stat()
    if not (st_del.st_mode & stat.S_IWRITE):
        os.chmod(renamed_p, stat.S_IWRITE | stat.S_IREAD)
    renamed_p.unlink()
    assert not renamed_p.exists()


def test_misnamed_container_tag_apply_and_missing_tags_filter(tmp_path: Path) -> None:
    """Verify tag application and missing tags filter update on misnamed audio container (.mp3 with WAV content)."""
    db_file = tmp_path / "test_misnamed.db"
    repo = Repository(db_file)

    # 1. Create a WAV file disguised with .mp3 extension and no tags (filename fallback pattern)
    misnamed_file = tmp_path / "NewJeans - Ditto.mp3"
    create_dummy_wav(misnamed_file, title="", artist="")

    # Verify initial container is WAV format (RIFF header)
    initial_bytes = misnamed_file.read_bytes()
    assert initial_bytes[:4] == b"RIFF"
    assert initial_bytes[8:12] == b"WAVE"

    # 2. Initial scan: sync_single_file records track with tag_source == 'FILENAME_FALLBACK'
    sync_single_file(misnamed_file, repo)

    missing_initial = repo.get_missing_tags()
    assert len(missing_initial) == 1
    assert missing_initial[0]["file_name"] == "NewJeans - Ditto.mp3"
    assert missing_initial[0]["tag_source"] == "FILENAME_FALLBACK"
    assert missing_initial[0]["artist"] == "NewJeans"
    assert missing_initial[0]["title"] == "Ditto"

    # 3. Apply fallback tags into the file
    ok = apply_fallback_tags_to_file(misnamed_file, artist="NewJeans", title="Ditto")
    assert ok is True

    # 4. Verify RIFF header is intact (not overwritten or corrupted by raw ID3 header)
    updated_bytes = misnamed_file.read_bytes()
    assert updated_bytes[:4] == b"RIFF"
    assert updated_bytes[8:12] == b"WAVE"

    # Verify mutagen WAVE reads the newly added tags
    wav_audio = WAVE(str(misnamed_file))
    assert wav_audio.tags is not None
    assert wav_audio.tags.get("TPE1").text[0] == "NewJeans"
    assert wav_audio.tags.get("TIT2").text[0] == "Ditto"

    # 5. Sync file again and verify tag_source == 'ID3' and excluded from get_missing_tags()
    sync_single_file(misnamed_file, repo)

    active_tracks = repo.get_all_active_tracks()
    assert len(active_tracks) == 1
    assert active_tracks[0]["tag_source"] == "ID3"

    missing_after = repo.get_missing_tags()
    assert len(missing_after) == 0


def test_underscore_filename_standardization(tmp_path: Path) -> None:
    """Verify parsing, standardizing, collision avoidance, and batch directory rename of underscore filenames."""
    # 1. Test parse_underscore_filename
    assert parse_underscore_filename("BLACKPINK_불장난.mp3") == ("BLACKPINK", "불장난")
    assert parse_underscore_filename("아이유_밤편지.flac") == ("아이유", "밤편지")
    assert parse_underscore_filename("NewJeans_Hype Boy.m4a") == ("NewJeans", "Hype Boy")
    assert parse_underscore_filename("Artist_Title") == ("Artist", "Title")
    assert parse_underscore_filename(Path("C:/music/Artist_Title.wav")) == ("Artist", "Title")

    # Invalid patterns
    assert parse_underscore_filename("BLACKPINK - 불장난.mp3") is None
    assert parse_underscore_filename("A_B_C.mp3") is None
    assert parse_underscore_filename("_Title.mp3") is None
    assert parse_underscore_filename("Artist_.mp3") is None
    assert parse_underscore_filename("Artist_Title - Live.mp3") is None
    assert parse_underscore_filename("NoUnderscore.mp3") is None
    assert parse_underscore_filename("   _   .mp3") is None

    # 2. Test standardize_underscore_filename with auto_tag
    f1 = tmp_path / "BLACKPINK_불장난.mp3"
    create_test_mp3(f1, title="", artist="")
    new_path = standardize_underscore_filename(f1, auto_tag=True)
    expected_path = tmp_path / "BLACKPINK - 불장난.mp3"
    assert new_path == expected_path
    assert expected_path.exists()
    assert not f1.exists()

    audio = MP3(str(expected_path))
    assert audio.tags.get("TPE1").text[0] == "BLACKPINK"
    assert audio.tags.get("TIT2").text[0] == "불장난"

    # 3. Test collision handling (target already exists)
    f2 = tmp_path / "BLACKPINK_불장난.mp3"
    create_test_mp3(f2, title="", artist="")
    collided_path = standardize_underscore_filename(f2, auto_tag=False)
    expected_collision = tmp_path / "BLACKPINK - 불장난 (1).mp3"
    assert collided_path == expected_collision
    assert expected_collision.exists()
    assert not f2.exists()

    # 4. Test repo.get_nonstandard_naming_tracks and batch_standardize_underscore_directory
    db_file = tmp_path / "test_naming.db"
    repo = Repository(db_file)

    music_dir = tmp_path / "music_batch"
    music_dir.mkdir(parents=True, exist_ok=True)

    file_iu = music_dir / "IU_Celebrity.mp3"
    file_taeyeon = music_dir / "Taeyeon_INVU.mp3"
    file_standard = music_dir / "Aespa - Next Level.mp3"
    file_multi = music_dir / "Invalid_Multiple_Underscores.mp3"

    create_test_mp3(file_iu)
    create_test_mp3(file_taeyeon)
    create_test_mp3(file_standard)
    create_test_mp3(file_multi)

    for f in [file_iu, file_taeyeon, file_standard, file_multi]:
        sync_single_file(f, repo)

    nonstandard = repo.get_nonstandard_naming_tracks()
    assert len(nonstandard) == 2
    matched_names = {r["file_name"] for r in nonstandard}
    assert matched_names == {"IU_Celebrity.mp3", "Taeyeon_INVU.mp3"}

    target_names = {r["target_name"] for r in nonstandard}
    assert target_names == {"IU - Celebrity.mp3", "Taeyeon - INVU.mp3"}

    # 5. Batch standardization
    res = batch_standardize_underscore_directory(music_dir, repo=repo, auto_tag=True)
    assert res["total_found"] == 2
    assert res["renamed"] == 2
    assert res["failed"] == 0
    assert len(res["errors"]) == 0

    assert (music_dir / "IU - Celebrity.mp3").exists()
    assert (music_dir / "Taeyeon - INVU.mp3").exists()
    assert not file_iu.exists()
    assert not file_taeyeon.exists()
    assert file_standard.exists()
    assert file_multi.exists()

    # Verify DB paths updated
    active_names = {t["file_name"] for t in repo.get_all_active_tracks()}
    assert "IU - Celebrity.mp3" in active_names
    assert "Taeyeon - INVU.mp3" in active_names
    assert "IU_Celebrity.mp3" not in active_names

    # Verify no nonstandard naming tracks remaining
    assert len(repo.get_nonstandard_naming_tracks()) == 0



