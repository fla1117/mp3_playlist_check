"""YouTube metadata extractor using yt-dlp with caching and playlist/chapter support."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

import yt_dlp

from src.config import CHAPTER_SPLIT_MIN_DURATION_SEC
if TYPE_CHECKING:
    from src.db.repository import Repository

VIDEO_ID_REGEX = re.compile(r"(?:v=|\/|youtu\.be\/|shorts\/)([0-9A-Za-z_-]{11})")
PLAYLIST_ID_REGEX = re.compile(r"[?&]list=([0-9A-Za-z_-]+)")


@dataclass
class YouTubeTrackInfo:
    """Extracted YouTube track metadata."""
    video_id: str
    raw_title: str
    uploader: str
    duration_sec: float
    yt_artist: Optional[str] = None
    yt_track: Optional[str] = None
    is_chapter: bool = False
    chapter_start: Optional[float] = None
    chapter_end: Optional[float] = None


@dataclass
class YouTubeExtractResult:
    """Result of YouTube URL extraction: single track, playlist, or chapter compilation."""
    url: str
    is_playlist: bool = False
    playlist_title: Optional[str] = None
    tracks: List[YouTubeTrackInfo] = field(default_factory=list)


def extract_video_id(url: str) -> Optional[str]:
    """Extract 11-char video ID from various YouTube URL formats."""
    match = VIDEO_ID_REGEX.search(url)
    return match.group(1) if match else None


def parse_provided_to_youtube(description: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Parse 'Provided to YouTube by ...' description from YouTube Music Topic uploads."""
    if not description or "Provided to YouTube by" not in description:
        return None, None
    lines = [line.strip() for line in description.splitlines() if line.strip()]
    for i, line in enumerate(lines):
        if line.startswith("Provided to YouTube by") and i + 1 < len(lines):
            next_line = lines[i + 1]
            # Format: Track Name · Artist Name
            if "·" in next_line:
                parts = next_line.split("·")
                if len(parts) >= 2:
                    return parts[1].strip(), parts[0].strip()
            # Or: Track Name · Artist1 · Artist2
    return None, None


class YouTubeExtractor:
    """Extractor for YouTube video, playlist, and chapter compilation metadata."""

    def __init__(self, repo: Optional[Repository] = None):
        self.repo = repo
        self.ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
        }

    def extract(self, url: str) -> YouTubeExtractResult:
        """Extract metadata from YouTube URL with cache support."""
        vid = extract_video_id(url)
        is_playlist_url = bool(PLAYLIST_ID_REGEX.search(url)) and ("list=" in url and "watch" not in url)

        # Check single video cache
        if vid and not is_playlist_url and self.repo:
            cached = self.repo.get_cached_youtube(vid)
            if cached:
                # If cached chapters exist
                chapters = cached.get("chapters")
                dur = cached.get("duration_sec", 0.0) or 0.0
                if chapters and dur >= CHAPTER_SPLIT_MIN_DURATION_SEC:
                    tracks = []
                    for ch in chapters:
                        ch_dur = max(0.0, ch.get("end_time", 0.0) - ch.get("start_time", 0.0))
                        tracks.append(
                            YouTubeTrackInfo(
                                video_id=f"{vid}_ch_{ch.get('start_time', 0):.0f}",
                                raw_title=ch.get("title", ""),
                                uploader=cached.get("uploader", ""),
                                duration_sec=ch_dur,
                                is_chapter=True,
                                chapter_start=ch.get("start_time"),
                                chapter_end=ch.get("end_time"),
                            )
                        )
                    return YouTubeExtractResult(url=url, is_playlist=False, tracks=tracks)

                return YouTubeExtractResult(
                    url=url,
                    is_playlist=False,
                    tracks=[
                        YouTubeTrackInfo(
                            video_id=vid,
                            raw_title=cached.get("raw_title", ""),
                            uploader=cached.get("uploader", ""),
                            duration_sec=dur,
                            yt_artist=cached.get("yt_artist"),
                            yt_track=cached.get("yt_track"),
                        )
                    ],
                )

        # Use yt-dlp to extract info
        with yt_dlp.YoutubeDL(self.ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        if not info:
            raise ValueError(f"Could not extract metadata from URL: {url}")

        # Check if playlist
        if "entries" in info and info.get("_type") == "playlist":
            playlist_title = info.get("title", "YouTube Playlist")
            tracks: List[YouTubeTrackInfo] = []
            for entry in info["entries"]:
                if not entry:
                    continue
                e_id = entry.get("id") or extract_video_id(entry.get("url", "")) or ""
                e_title = entry.get("title", "")
                e_uploader = entry.get("uploader") or entry.get("channel") or ""
                e_dur = float(entry.get("duration") or 0.0)
                tracks.append(
                    YouTubeTrackInfo(
                        video_id=e_id,
                        raw_title=e_title,
                        uploader=e_uploader,
                        duration_sec=e_dur,
                        yt_artist=entry.get("artist"),
                        yt_track=entry.get("track"),
                    )
                )
            return YouTubeExtractResult(
                url=url,
                is_playlist=True,
                playlist_title=playlist_title,
                tracks=tracks,
            )

        # Single video / Chapter video
        raw_title = info.get("title", "")
        uploader = info.get("uploader") or info.get("channel") or ""
        duration_sec = float(info.get("duration") or 0.0)
        yt_track = info.get("track")
        yt_artist = info.get("artist")

        if not yt_artist or not yt_track:
            desc_artist, desc_track = parse_provided_to_youtube(info.get("description"))
            if desc_artist and not yt_artist:
                yt_artist = desc_artist
            if desc_track and not yt_track:
                yt_track = desc_track

        chapters = info.get("chapters")
        video_id = info.get("id") or vid or "unknown"

        # Save to repository cache
        if self.repo and video_id != "unknown":
            self.repo.save_youtube_cache(
                {
                    "video_id": video_id,
                    "raw_title": raw_title,
                    "uploader": uploader,
                    "yt_artist": yt_artist,
                    "yt_track": yt_track,
                    "duration_sec": duration_sec,
                    "chapters": chapters,
                }
            )

        # Check if long compilation video with chapters
        if duration_sec >= CHAPTER_SPLIT_MIN_DURATION_SEC and chapters:
            tracks = []
            for ch in chapters:
                ch_dur = max(0.0, float(ch.get("end_time", 0.0) - ch.get("start_time", 0.0)))
                tracks.append(
                    YouTubeTrackInfo(
                        video_id=f"{video_id}_ch_{ch.get('start_time', 0):.0f}",
                        raw_title=ch.get("title", ""),
                        uploader=uploader,
                        duration_sec=ch_dur,
                        is_chapter=True,
                        chapter_start=ch.get("start_time"),
                        chapter_end=ch.get("end_time"),
                    )
                )
            return YouTubeExtractResult(url=url, is_playlist=False, tracks=tracks)

        return YouTubeExtractResult(
            url=url,
            is_playlist=False,
            tracks=[
                YouTubeTrackInfo(
                    video_id=video_id,
                    raw_title=raw_title,
                    uploader=uploader,
                    duration_sec=duration_sec,
                    yt_artist=yt_artist,
                    yt_track=yt_track,
                )
            ],
        )
