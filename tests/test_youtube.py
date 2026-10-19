"""Unit tests for YouTube extractor, URL parsing, description parsing, chapters, and caching."""
from unittest.mock import MagicMock, patch

import pytest

from src.db.repository import Repository
from src.youtube.extractor import (
    YouTubeExtractor,
    extract_video_id,
    parse_provided_to_youtube,
)


def test_extract_video_id():
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://music.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ&list=PL12345") == "dQw4w9WgXcQ"


def test_parse_provided_to_youtube():
    desc = """
    Provided to YouTube by Kakao Entertainment
    Good Day (좋은 날) · IU
    Real
    ℗ 2010 Fave Entertainment
    """
    artist, track = parse_provided_to_youtube(desc)
    assert artist == "IU"
    assert "좋은 날" in track or "Good Day" in track

    no_desc = "Just some description without credit"
    assert parse_provided_to_youtube(no_desc) == (None, None)


def test_youtube_extractor_single_and_cache(tmp_path):
    repo = Repository(tmp_path / "yt_test.db")
    extractor = YouTubeExtractor(repo)

    mock_info = {
        "id": "abc12345678",
        "title": "IU - Good Day",
        "uploader": "1theK",
        "duration": 238,
        "track": "Good Day",
        "artist": "IU",
        "chapters": None,
    }

    with patch("src.youtube.extractor.yt_dlp.YoutubeDL") as MockYDL:
        mock_instance = MockYDL.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = mock_info

        # 1st call: uses yt-dlp
        res1 = extractor.extract("https://www.youtube.com/watch?v=abc12345678")
        assert len(res1.tracks) == 1
        assert res1.tracks[0].video_id == "abc12345678"
        assert res1.tracks[0].yt_track == "Good Day"
        assert res1.tracks[0].yt_artist == "IU"
        assert mock_instance.extract_info.call_count == 1

        # 2nd call: retrieved from youtube_cache, yt-dlp NOT called
        res2 = extractor.extract("https://www.youtube.com/watch?v=abc12345678")
        assert len(res2.tracks) == 1
        assert res2.tracks[0].video_id == "abc12345678"
        assert res2.tracks[0].yt_track == "Good Day"
        assert mock_instance.extract_info.call_count == 1  # Still 1 because cached!


def test_youtube_chapters_split(tmp_path):
    repo = Repository(tmp_path / "yt_test2.db")
    extractor = YouTubeExtractor(repo)

    mock_compilation = {
        "id": "compilation1",
        "title": "IU Best Songs Playlist",
        "uploader": "Music Channel",
        "duration": 1800,  # 30 minutes (>600s)
        "chapters": [
            {"title": "Good Day", "start_time": 0.0, "end_time": 233.0},
            {"title": "You & I", "start_time": 233.0, "end_time": 473.0},
            {"title": "Palette", "start_time": 473.0, "end_time": 700.0},
        ],
    }

    with patch("src.youtube.extractor.yt_dlp.YoutubeDL") as MockYDL:
        mock_instance = MockYDL.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = mock_compilation

        res = extractor.extract("https://www.youtube.com/watch?v=compilation1")
        assert not res.is_playlist
        assert len(res.tracks) == 3
        assert res.tracks[0].raw_title == "Good Day"
        assert res.tracks[0].is_chapter is True
        assert res.tracks[0].duration_sec == 233.0
        assert res.tracks[1].raw_title == "You & I"
        assert res.tracks[1].duration_sec == 240.0


def test_youtube_playlist(tmp_path):
    repo = Repository(tmp_path / "yt_test3.db")
    extractor = YouTubeExtractor(repo)

    mock_playlist = {
        "_type": "playlist",
        "title": "K-Pop Top Hits",
        "entries": [
            {"id": "vid00000001", "title": "Track 1", "uploader": "Artist 1", "duration": 200},
            {"id": "vid00000002", "title": "Track 2", "uploader": "Artist 2", "duration": 210},
        ],
    }

    with patch("src.youtube.extractor.yt_dlp.YoutubeDL") as MockYDL:
        mock_instance = MockYDL.return_value.__enter__.return_value
        mock_instance.extract_info.return_value = mock_playlist

        res = extractor.extract("https://www.youtube.com/playlist?list=PLtestplaylist")
        assert res.is_playlist is True
        assert res.playlist_title == "K-Pop Top Hits"
        assert len(res.tracks) == 2
        assert res.tracks[0].video_id == "vid00000001"
        assert res.tracks[1].video_id == "vid00000002"
