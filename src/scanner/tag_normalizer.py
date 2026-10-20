"""Audio metadata tag normalization and standard filename renaming utilities."""
import os
import re
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import mutagen
from mutagen.flac import FLAC
from mutagen.id3 import ID3, ID3NoHeaderError, TALB, TIT2, TPE1
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4
from mutagen.wave import WAVE


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
    """Write artist, title, and album metadata to audio file tags (MP3, FLAC, M4A, WAVE)."""
    p = Path(file_path)
    if not p.exists():
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
            if artist:
                audio["\xa9ART"] = [artist]
            if title:
                audio["\xa9nam"] = [title]
            if album:
                audio["\xa9alb"] = [album]
            audio.save()
            return True

        # 2. FLAC container
        elif isinstance(audio, FLAC):
            if artist:
                audio["artist"] = artist
            if title:
                audio["title"] = title
            if album:
                audio["album"] = album
            audio.save()
            return True

        # 3. WAVE container (save into RIFF ID3 chunk, do NOT use raw ID3.save())
        elif isinstance(audio, WAVE):
            if audio.tags is None:
                audio.add_tags()
            if artist:
                audio.tags.add(TPE1(encoding=3, text=artist))
            if title:
                audio.tags.add(TIT2(encoding=3, text=title))
            if album:
                audio.tags.add(TALB(encoding=3, text=album))
            audio.save()
            return True

        # 4. MP3 container (or fallback if audio is MP3/None with .mp3 extension)
        elif isinstance(audio, MP3) or (audio is None and ext == ".mp3") or ext == ".mp3":
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

        # 5. Fallback based on extension
        elif ext in [".m4a", ".mp4", ".aac"]:
            m_audio = MP4(str(p))
            if artist:
                m_audio["\xa9ART"] = [artist]
            if title:
                m_audio["\xa9nam"] = [title]
            if album:
                m_audio["\xa9alb"] = [album]
            m_audio.save()
            return True

        elif ext == ".flac":
            f_audio = FLAC(str(p))
            if artist:
                f_audio["artist"] = artist
            if title:
                f_audio["title"] = title
            if album:
                f_audio["album"] = album
            f_audio.save()
            return True

        elif ext == ".wav":
            w_audio = WAVE(str(p))
            if w_audio.tags is None:
                w_audio.add_tags()
            if artist:
                w_audio.tags.add(TPE1(encoding=3, text=artist))
            if title:
                w_audio.tags.add(TIT2(encoding=3, text=title))
            if album:
                w_audio.tags.add(TALB(encoding=3, text=album))
            w_audio.save()
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

    try:
        st = p.stat()
        if not (st.st_mode & stat.S_IWRITE):
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass

    p.rename(target_path)
    return target_path


AUDIO_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".aac", ".ogg", ".wma"}


def parse_underscore_filename(file_path_or_name: Path | str) -> Optional[tuple[str, str]]:
    """Parse '[artist]_[title].[ext]' filename where stem contains exactly one underscore and no ' - '.

    Returns (artist, title) tuple if valid, otherwise None.
    """
    stem = Path(file_path_or_name).stem
    if stem.count("_") == 1 and " - " not in stem:
        parts = stem.split("_")
        artist = parts[0].strip()
        title = parts[1].strip()
        if artist and title:
            return (artist, title)
    return None


def standardize_underscore_filename(file_path: Path | str, auto_tag: bool = False) -> Optional[Path]:
    """Standardize an underscore-named file ('Artist_Title.ext') to standard 'Artist - Title.ext'.

    Validates with parse_underscore_filename(file_path). If None, returns None.
    Uses rename_file_standard(file_path, artist, title) which already handles Windows Read-Only attribute clearance and collision avoidance (1).
    If auto_tag is True and the file exists, calls apply_fallback_tags_to_file(new_path, artist, title).
    Returns new_path (Path object).
    """
    parsed = parse_underscore_filename(file_path)
    if parsed is None:
        return None

    p = Path(file_path)
    if not p.exists():
        return None

    artist, title = parsed
    new_path = rename_file_standard(p, artist, title)
    if auto_tag and new_path.exists():
        apply_fallback_tags_to_file(new_path, artist, title)
    return new_path


def batch_standardize_underscore_directory(
    dir_path: Path | str,
    repo: Optional[Any] = None,
    auto_tag: bool = False,
    recursive: bool = False,
) -> dict:
    """Scan dir_path for audio files (.mp3, .flac, .m4a, .wav, .aac, .ogg, .wma) and rename underscore files.

    For each file where parse_underscore_filename matches:
      - Renames using standardize_underscore_filename.
      - If repo is provided and the file was renamed:
        - Calls repo.update_track_path(...).
    Returns dict:
      {"total_found": len(matched), "renamed": renamed_count, "failed": fail_count, "errors": errors_list, "renamed_files": [(str(old), str(new)), ...]}.
    """
    p = Path(dir_path)
    if not p.exists() or not p.is_dir():
        return {
            "total_found": 0,
            "renamed": 0,
            "failed": 0,
            "errors": [f"Directory not found: {dir_path}"],
            "renamed_files": [],
        }

    if recursive:
        files = [f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]
    else:
        files = [f for f in p.iterdir() if f.is_file() and f.suffix.lower() in AUDIO_EXTENSIONS]

    matched = [f for f in files if parse_underscore_filename(f) is not None]

    renamed_count = 0
    fail_count = 0
    errors_list: list[str] = []
    renamed_files: list[tuple[str, str]] = []

    for f in matched:
        old_path = f
        try:
            new_path = standardize_underscore_filename(old_path, auto_tag=auto_tag)
            if new_path and new_path != old_path:
                if repo is not None:
                    try:
                        st = new_path.stat()
                        repo.update_track_path(
                            old_path=str(old_path),
                            new_path=str(new_path),
                            new_name=new_path.name,
                            new_ext=new_path.suffix.lstrip(".").lower(),
                            mtime=st.st_mtime,
                            file_size=st.st_size,
                        )
                    except Exception:
                        pass
                renamed_count += 1
                renamed_files.append((str(old_path), str(new_path)))
            else:
                fail_count += 1
                errors_list.append(f"Failed to rename: {old_path}")
        except Exception as e:
            fail_count += 1
            errors_list.append(f"{old_path} -> {type(e).__name__}: {e}")

    return {
        "total_found": len(matched),
        "renamed": renamed_count,
        "failed": fail_count,
        "errors": errors_list,
        "renamed_files": renamed_files,
    }
