"""Cover art extraction, auto-fetching, and embedding utilities."""
import json
import mimetypes
import os
import stat
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, ID3NoHeaderError
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.wave import WAVE


def extract_cover_bytes_from_file(file_path: Path | str) -> Optional[Tuple[bytes, str]]:
    """Extract embedded cover art raw bytes and mime type from an audio file."""
    p = Path(file_path)
    if not p.exists():
        return None

    ext = p.suffix.lower()
    try:
        audio = mutagen.File(str(p))

        # 1. MP4 / M4A / AAC container
        if isinstance(audio, MP4):
            covrs = audio.get("covr", [])
            if covrs:
                c = covrs[0]
                mime = "image/png" if getattr(c, "imageformat", None) == MP4Cover.FORMAT_PNG else "image/jpeg"
                return bytes(c), mime

        # 2. FLAC container
        elif isinstance(audio, FLAC):
            if audio.pictures:
                pic = audio.pictures[0]
                return pic.data, pic.mime or "image/jpeg"

        # 3. WAVE container
        elif isinstance(audio, WAVE):
            if audio.tags:
                for key in audio.tags:
                    if key.startswith("APIC"):
                        apic = audio.tags[key]
                        return apic.data, apic.mime or "image/jpeg"

        # 4. MP3 container
        elif isinstance(audio, MP3) or (audio is None and ext == ".mp3") or ext == ".mp3":
            try:
                tags = ID3(str(p))
                for key in tags:
                    if key.startswith("APIC"):
                        apic = tags[key]
                        return apic.data, apic.mime or "image/jpeg"
            except ID3NoHeaderError:
                return None

        # 5. Fallback based on extension
        elif ext in [".m4a", ".mp4", ".aac"]:
            m_audio = MP4(str(p))
            covrs = m_audio.get("covr", [])
            if covrs:
                c = covrs[0]
                mime = "image/png" if getattr(c, "imageformat", None) == MP4Cover.FORMAT_PNG else "image/jpeg"
                return bytes(c), mime

        elif ext == ".flac":
            f_audio = FLAC(str(p))
            if f_audio.pictures:
                pic = f_audio.pictures[0]
                return pic.data, pic.mime or "image/jpeg"

        elif ext == ".wav":
            w_audio = WAVE(str(p))
            if w_audio.tags:
                for key in w_audio.tags:
                    if key.startswith("APIC"):
                        apic = w_audio.tags[key]
                        return apic.data, apic.mime or "image/jpeg"

    except Exception:
        pass

    return None


def embed_cover_art(file_path: Path | str, image_bytes: bytes, mime_type: str = "image/jpeg") -> bool:
    """Embed cover art image bytes into audio file tags (MP3, FLAC, M4A, WAVE)."""
    p = Path(file_path)
    if not p.exists() or not image_bytes:
        return False

    try:
        st = p.stat()
        if not (st.st_mode & stat.S_IWRITE):
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass

    ext = p.suffix.lower()
    try:
        audio = mutagen.File(str(p))

        # 1. MP4 / M4A / AAC container
        if isinstance(audio, MP4):
            cov_fmt = MP4Cover.FORMAT_PNG if "png" in mime_type.lower() else MP4Cover.FORMAT_JPEG
            audio["covr"] = [MP4Cover(image_bytes, imageformat=cov_fmt)]
            audio.save()
            return True

        # 2. FLAC container
        elif isinstance(audio, FLAC):
            audio.clear_pictures()
            pic = Picture()
            pic.type = 3
            pic.mime = mime_type
            pic.desc = "Cover"
            pic.data = image_bytes
            audio.add_picture(pic)
            audio.save()
            return True

        # 3. WAVE container (save into RIFF ID3 chunk, do NOT use raw ID3.save())
        elif isinstance(audio, WAVE):
            if audio.tags is None:
                audio.add_tags()
            audio.tags.delall("APIC")
            audio.tags.add(
                APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,  # Front Cover
                    desc="Cover",
                    data=image_bytes,
                )
            )
            audio.save()
            return True

        # 4. MP3 container (or fallback if audio is MP3/None with .mp3 extension)
        elif isinstance(audio, MP3) or (audio is None and ext == ".mp3") or ext == ".mp3":
            try:
                tags = ID3(str(p))
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("APIC")
            tags.add(
                APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,  # Front Cover
                    desc="Cover",
                    data=image_bytes,
                )
            )
            tags.save(str(p))
            return True

        # 5. Fallback based on extension
        elif ext in [".m4a", ".mp4", ".aac"]:
            m_audio = MP4(str(p))
            cov_fmt = MP4Cover.FORMAT_PNG if "png" in mime_type.lower() else MP4Cover.FORMAT_JPEG
            m_audio["covr"] = [MP4Cover(image_bytes, imageformat=cov_fmt)]
            m_audio.save()
            return True

        elif ext == ".flac":
            f_audio = FLAC(str(p))
            f_audio.clear_pictures()
            pic = Picture()
            pic.type = 3
            pic.mime = mime_type
            pic.desc = "Cover"
            pic.data = image_bytes
            f_audio.add_picture(pic)
            f_audio.save()
            return True

        elif ext == ".wav":
            w_audio = WAVE(str(p))
            if w_audio.tags is None:
                w_audio.add_tags()
            w_audio.tags.delall("APIC")
            w_audio.tags.add(
                APIC(
                    encoding=3,
                    mime=mime_type,
                    type=3,
                    desc="Cover",
                    data=image_bytes,
                )
            )
            w_audio.save()
            return True

    except Exception:
        return False

    return False


def fetch_cover_art_auto(
    track_or_artist: Any,
    title_or_tracks: Any = None,
    album: str = "",
    repo: Optional[Any] = None,
) -> Optional[Tuple[bytes, str]]:
    """Automatically fetch cover art from local library sharing (1st) or iTunes Search API (2nd)."""
    if isinstance(track_or_artist, dict):
        track = track_or_artist
        artist = track.get("artist") or ""
        title = track.get("title") or ""
        album = track.get("album") or ""
        all_tracks = title_or_tracks if isinstance(title_or_tracks, list) else None
        repo = repo or (title_or_tracks if hasattr(title_or_tracks, "get_connection") else None)
        track_path = track.get("file_path") or ""
    else:
        artist = str(track_or_artist or "")
        title = str(title_or_tracks or "")
        all_tracks = None
        track_path = ""

    # 1st Priority: Local album / folder sharing with existing cover art
    if all_tracks and (album or track_path):
        track_parent = Path(track_path).parent if track_path else None
        for cand in all_tracks:
            if not cand.get("has_cover_art"):
                continue
            cand_path = cand.get("file_path")
            if not cand_path or cand_path == track_path:
                continue
            # Match by album name or parent folder
            same_album = bool(album and cand.get("album") and cand.get("album") == album)
            same_folder = bool(track_parent and Path(cand_path).parent == track_parent)
            if same_album or same_folder:
                found = extract_cover_bytes_from_file(cand_path)
                if found:
                    return found

    if repo and album:
        try:
            with repo.get_connection() as conn:
                row = conn.execute(
                    """
                    SELECT file_path FROM tracks
                    WHERE is_missing = 0 AND has_cover_art = 1
                      AND album = ? AND album != ''
                    LIMIT 1
                    """,
                    (album,),
                ).fetchone()
                if row:
                    found = extract_cover_bytes_from_file(row["file_path"])
                    if found:
                        return found
        except Exception:
            pass

    # 2nd Priority: iTunes Search API (Free high-resolution artwork)
    query_term = f"{artist} {title}".strip()
    if not query_term:
        query_term = title.strip()
    if not query_term:
        return None

    try:
        encoded_term = urllib.parse.quote(query_term)
        url = f"https://itunes.apple.com/search?term={encoded_term}&entity=song&country=KR&limit=5"
        req = urllib.request.Request(url, headers={"User-Agent": "mp3_playlist_check/0.3.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        results = data.get("results", [])
        if results:
            artwork_url = results[0].get("artworkUrl100")
            if artwork_url:
                # Replace 100x100 with 600x600 for high resolution
                hi_res_url = artwork_url.replace("100x100bb.jpg", "600x600bb.jpg")
                img_req = urllib.request.Request(hi_res_url, headers={"User-Agent": "mp3_playlist_check/0.3.0"})
                with urllib.request.urlopen(img_req, timeout=5) as img_resp:
                    img_bytes = img_resp.read()
                    if img_bytes:
                        return img_bytes, "image/jpeg"
    except Exception:
        pass

    return None
