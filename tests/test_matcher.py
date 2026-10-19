"""Unit tests for MatcherEngine, scoring calculations, alias resolution, and edge cases."""
import pytest
from src.db.repository import Repository
from src.matcher.scorer import MatcherEngine, MatchStatus


@pytest.fixture
def repo(tmp_path):
    """Create an isolated test repository in temporary directory."""
    db_file = tmp_path / "test_music.db"
    return Repository(db_file)


@pytest.fixture
def engine(repo):
    """Create MatcherEngine instance."""
    return MatcherEngine(repo)


def test_exact_match(repo, engine):
    # Insert local track: IU - 좋은 날 (Good Day), 233 seconds, studio
    repo.upsert_track(
        {
            "file_path": "/music/IU/Good_Day.flac",
            "file_name": "Good_Day.flac",
            "file_ext": "flac",
            "file_size": 25000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_good_day",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "아이유",
            "album_artist": "아이유",
            "title": "좋은 날 (Good Day)",
            "album": "Real",
            "release_year": 2010,
            "track_number": 3,
            "disc_number": 1,
            "genre": "K-Pop",
            "has_cover_art": 1,
            "cover_mime": "image/jpeg",
            "cover_width": 600,
            "cover_height": 600,
            "duration_sec": 233.0,
            "bitrate_kbps": 1024,
            "sample_rate_hz": 44100,
            "norm_artist": "아이유",
            "norm_title": "좋은날goodday",
            "feat_artists": None,
            "version_tag": "studio",
        }
    )

    # YouTube: [MV] IU(아이유) _ Good Day(좋은 날), 238 seconds (5s diff)
    res = engine.match(
        raw_title="[MV] IU(아이유) _ Good Day(좋은 날)",
        uploader="1theK (원더케이)",
        duration_sec=238.0,
    )

    assert res.status == MatchStatus.EXACT_MATCH
    assert res.score >= 85.0
    assert res.version_penalty == 0.0
    assert res.duration_score == 100.0
    assert res.matched_track is not None
    assert res.matched_track["title"] == "좋은 날 (Good Day)"


def test_alias_matching(repo, engine):
    # Local track has Korean artist: 방탄소년단
    repo.upsert_track(
        {
            "file_path": "/music/BTS/Dynamite.mp3",
            "file_name": "Dynamite.mp3",
            "file_ext": "mp3",
            "file_size": 8000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_dynamite",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "방탄소년단",
            "album_artist": "방탄소년단",
            "title": "Dynamite",
            "album": "Dynamite",
            "release_year": 2020,
            "track_number": 1,
            "disc_number": 1,
            "genre": "Pop",
            "has_cover_art": 1,
            "cover_mime": "image/jpeg",
            "cover_width": 500,
            "cover_height": 500,
            "duration_sec": 199.0,
            "bitrate_kbps": 320,
            "sample_rate_hz": 44100,
            "norm_artist": "방탄소년단",
            "norm_title": "dynamite",
            "feat_artists": None,
            "version_tag": "studio",
        }
    )

    # YouTube has English alias: BTS
    res = engine.match(
        raw_title="BTS - Dynamite (Official MV)",
        uploader="HYBE LABELS",
        duration_sec=200.0,
    )

    assert res.status == MatchStatus.EXACT_MATCH
    assert res.artist_score == 100.0
    assert res.matched_track["artist"] == "방탄소년단"


def test_version_mismatch_penalty(repo, engine):
    # Local track is studio version
    repo.upsert_track(
        {
            "file_path": "/music/IU/Good_Day.mp3",
            "file_name": "Good_Day.mp3",
            "file_ext": "mp3",
            "file_size": 9000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_gd_studio",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "아이유",
            "title": "좋은 날",
            "duration_sec": 233.0,
            "norm_artist": "아이유",
            "norm_title": "좋은날",
            "version_tag": "studio",
            "has_cover_art": 0,
        }
    )

    # YouTube is Live version
    res = engine.match(
        raw_title="아이유 - 좋은 날 (Live ver.)",
        uploader="KBS Kpop",
        duration_sec=235.0,
    )

    assert res.status == MatchStatus.PARTIAL_MATCH
    assert res.version_penalty == 20.0
    assert "Live 버전" in res.reason


def test_shorts_teaser_duration_filter(repo, engine):
    # Local song is full 233 seconds
    repo.upsert_track(
        {
            "file_path": "/music/IU/Good_Day.mp3",
            "file_name": "Good_Day.mp3",
            "file_ext": "mp3",
            "file_size": 9000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_gd_full",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "아이유",
            "title": "좋은 날",
            "duration_sec": 233.0,
            "norm_artist": "아이유",
            "norm_title": "좋은날",
            "version_tag": "studio",
            "has_cover_art": 1,
        }
    )

    # YouTube video is a 30s teaser/Shorts of the song
    res = engine.match(
        raw_title="아이유 - 좋은 날 #Shorts",
        uploader="IU Official",
        duration_sec=30.0,
    )

    # Must NOT be EXACT_MATCH because delta t = 203s > 15s
    assert res.status != MatchStatus.EXACT_MATCH
    assert res.duration_score == 0.0


def test_bidirectional_title_artist(repo, engine):
    repo.upsert_track(
        {
            "file_path": "/music/NewJeans/Ditto.flac",
            "file_name": "Ditto.flac",
            "file_ext": "flac",
            "file_size": 20000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_ditto",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "뉴진스",
            "title": "Ditto",
            "duration_sec": 185.0,
            "norm_artist": "뉴진스",
            "norm_title": "ditto",
            "version_tag": "studio",
            "has_cover_art": 1,
        }
    )

    # YouTube title in 'Title - Artist' order: 'Ditto - NewJeans'
    res = engine.match(
        raw_title="Ditto - NewJeans",
        uploader="Various Artists",
        duration_sec=185.0,
    )

    assert res.status == MatchStatus.EXACT_MATCH
    assert res.matched_track["title"] == "Ditto"


def test_multiple_candidates_prioritization(repo, engine):
    # Same track in MP3 128kbps without cover, MP3 320kbps with cover, FLAC 1024kbps with cover
    repo.upsert_track(
        {
            "file_path": "/music/IU/03.mp3",
            "file_name": "03.mp3",
            "file_ext": "mp3",
            "file_size": 3000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_low_mp3",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "아이유",
            "title": "좋은 날",
            "duration_sec": 233.0,
            "bitrate_kbps": 128,
            "norm_artist": "아이유",
            "norm_title": "좋은날",
            "version_tag": "studio",
            "has_cover_art": 0,
        }
    )
    repo.upsert_track(
        {
            "file_path": "/music/IU/GoodDay_high.mp3",
            "file_name": "GoodDay_high.mp3",
            "file_ext": "mp3",
            "file_size": 9000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_high_mp3",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "아이유",
            "title": "좋은 날",
            "duration_sec": 233.0,
            "bitrate_kbps": 320,
            "norm_artist": "아이유",
            "norm_title": "좋은날",
            "version_tag": "studio",
            "has_cover_art": 1,
        }
    )
    repo.upsert_track(
        {
            "file_path": "/music/IU/GoodDay.flac",
            "file_name": "GoodDay.flac",
            "file_ext": "flac",
            "file_size": 25000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_lossless_flac",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "아이유",
            "title": "좋은 날",
            "duration_sec": 233.0,
            "bitrate_kbps": 1024,
            "norm_artist": "아이유",
            "norm_title": "좋은날",
            "version_tag": "studio",
            "has_cover_art": 1,
        }
    )

    res = engine.match(
        raw_title="아이유 - 좋은 날",
        duration_sec=233.0,
    )

    assert res.status == MatchStatus.EXACT_MATCH
    # FLAC must be selected as the top matched track
    assert res.matched_track["file_ext"] == "flac"
    assert res.matched_track["bitrate_kbps"] == 1024


def test_parenthesized_artist_alias_matching(repo, engine):
    """Test that local track with 'BTS (방탄소년단)' matches YouTube query with 'BTS' or '방탄소년단'."""
    repo.upsert_track(
        {
            "file_path": "/music/BTS/SpringDay.mp3",
            "file_name": "SpringDay.mp3",
            "file_ext": "mp3",
            "file_size": 10000000,
            "mtime": 1700000000.0,
            "partial_hash": "hash_spring_day",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": "BTS (방탄소년단)",
            "title": "봄날 (Spring Day)",
            "duration_sec": 274.0,
            "norm_artist": "bts방탄소년단",
            "norm_title": "봄날springday",
            "version_tag": "studio",
            "has_cover_art": 1,
        }
    )

    # 1. YouTube with 'BTS - Spring Day'
    res1 = engine.match(
        raw_title="BTS - Spring Day (봄날)",
        duration_sec=274.0,
    )
    assert res1.status == MatchStatus.EXACT_MATCH
    assert res1.artist_score == 100.0

    # 2. YouTube with '방탄소년단 - 봄날'
    res2 = engine.match(
        raw_title="방탄소년단 - 봄날",
        duration_sec=274.0,
    )
    assert res2.status == MatchStatus.EXACT_MATCH
    assert res2.artist_score == 100.0

