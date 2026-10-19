"""Audio metadata tag normalization and standard filename renaming utilities."""
import re
from pathlib import Path
from typing import Optional

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1
from mutagen.mp4 import MP4


INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Sanitize string for Windows filename safety."""
    cleaned = INVALID_FILENAME_CHARS.sub("_", name)
    cleaned = cleaned.strip(". ")
    return cleaned or "Unknown"


def apply_fallback_tags_to_file(
    file_path: Path | str,
    artist: str,
    title: str,
    album: Optional[str] = None,
) -> bool:
    """Write artist, title, and album metadata to audio file tags (MP3, FLAC, M4A)."""
    p = Path(file_path)
    if not p.exists():
        return False

    ext = p.suffix.lower()
    try:
        if ext == ".mp3":
            try:
                tags = ID3(str(p))
            except ID3NoHeaderError:
                tags = ID3()
            tags.delall("TPE1")
            tags.delall("TIT2")
            if artist:
                tags.add(TPE1(encoding=3, text=artist))
            if title:
                tags.add(TIT2(encoding=3, text=title))
            if album:
                tags.delall("TALB")
                tags.add(TALB(encoding=3, text=album))
            tags.save(str(p))
            return True

        elif ext == ".flac":
            audio = FLAC(str(p))
            if artist:
                audio["artist"] = artist
            if title:
                audio["title"] = title
            if album:
                audio["album"] = album
            audio.save()
            return True

        elif ext in [".m4a", ".mp4", ".aac"]:
            audio = MP4(str(p))
            if artist:
                audio["\xa9ART"] = [artist]
            if title:
                audio["\xa9nam"] = [title]
            if album:
                audio["\xa9alb"] = [album]
            audio.save()
            return True

    except Exception:
        return False

    return False


def rename_file_standard(file_path: Path | str, artist: str, title: str) -> Path:
    """Rename audio file to standard '{artist} - {title}{ext}' with collision safety."""
    p = Path(file_path)
    if not p.exists():
        return p

    safe_artist = sanitize_filename(artist or "Unknown")
    safe_title = sanitize_filename(title or "Unknown")
    ext = p.suffix.lower()

    target_name = f"{safe_artist} - {safe_title}{ext}"
    target_path = p.parent / target_name

    # If filename is already identical (case-sensitive check)
    if p.resolve() == target_path.resolve():
        return p

    # Collision avoidance if a distinct file with the same name already exists
    counter = 1
    while target_path.exists() and target_path.resolve() != p.resolve():
        target_name = f"{safe_artist} - {safe_title} ({counter}){ext}"
        target_path = p.parent / target_name
        counter += 1

    p.rename(target_path)
    return target_path
