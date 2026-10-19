"""Audio metadata extractor using mutagen with Mojibake recovery and cover art detection."""
import re
import struct
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import mutagen
from mutagen.flac import FLAC, Picture
from mutagen.id3 import ID3, APIC
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE

from src.matcher.normalizer import (
    clean_noise,
    extract_features,
    extract_version_tag,
    normalize_text,
    recover_mojibake,
)
from src.scanner.fallback_parser import parse_filename_fallback
from src.scanner.image_utils import (
    EXTERNAL_COVER_FILENAMES,
    _find_external_cover,
    _parse_image_dimensions,
)

# Aliases for internal and backward compatibility
_parse_image_header = _parse_image_dimensions
_check_external_cover = _find_external_cover


def _clean_str(val: Any) -> Optional[str]:
    """Extract clean string from tag value."""
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        if not val:
            return None
        val = val[0]
    s = str(val).strip()
    return recover_mojibake(s) if s else None


def _parse_int(val: Any) -> Optional[int]:
    """Parse integer from tag value (e.g. '3/12' -> 3)."""
    if val is None:
        return None
    if isinstance(val, (list, tuple)):
        if not val:
            return None
        val = val[0]
    if isinstance(val, int):
        return val
    s = str(val).strip()
    match = re.match(r"^(\d+)", s)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def extract_metadata(file_path: Path | str, partial_hash: str) -> Dict[str, Any]:
    """Extract full metadata, specs, cover art, and normalized fields for an audio file."""
    path = Path(file_path).resolve()
    file_stat = path.stat()
    file_size = file_stat.st_size
    mtime = file_stat.st_mtime
    file_ext = path.suffix.lower().lstrip(".")

    # Mutagen File Load
    audio = mutagen.File(str(path))
    if audio is None:
        raise ValueError(f"Unsupported or corrupted audio file: {path}")

    # Raw tag values
    raw_artist = None
    raw_album_artist = None
    raw_title = None
    raw_album = None
    raw_year = None
    raw_track_no = None
    raw_disc_no = 1
    raw_genre = None

    has_cover_art = 0
    cover_mime = None
    cover_width = None
    cover_height = None

    # Handle different container tags
    tags = getattr(audio, "tags", None)

    if tags is not None:
        # 1. MP3 / ID3
        if isinstance(audio, MP3) or isinstance(tags, ID3):
            raw_title = _clean_str(tags.get("TIT2"))
            raw_artist = _clean_str(tags.get("TPE1"))
            raw_album_artist = _clean_str(tags.get("TPE2"))
            raw_album = _clean_str(tags.get("TALB"))
            raw_year = _parse_int(tags.get("TDRC") or tags.get("TYER"))
            raw_track_no = _parse_int(tags.get("TRCK"))
            raw_disc_no = _parse_int(tags.get("TPOS")) or 1
            raw_genre = _clean_str(tags.get("TCON"))

            # APIC cover art
            apic_frames = tags.getall("APIC")
            if apic_frames:
                frame = apic_frames[0]
                has_cover_art = 1
                mime, w, h = _parse_image_header(frame.data)
                cover_mime = mime or getattr(frame, "mime", "image/jpeg")
                cover_width = w
                cover_height = h

        # 2. FLAC
        elif isinstance(audio, FLAC):
            raw_title = _clean_str(tags.get("title"))
            raw_artist = _clean_str(tags.get("artist"))
            raw_album_artist = _clean_str(tags.get("albumartist") or tags.get("album_artist"))
            raw_album = _clean_str(tags.get("album"))
            raw_year = _parse_int(tags.get("date"))
            raw_track_no = _parse_int(tags.get("tracknumber"))
            raw_disc_no = _parse_int(tags.get("discnumber")) or 1
            raw_genre = _clean_str(tags.get("genre"))

            if audio.pictures:
                pic = audio.pictures[0]
                has_cover_art = 1
                mime, w, h = _parse_image_header(pic.data)
                cover_mime = mime or pic.mime
                cover_width = w or pic.width
                cover_height = h or pic.height

        # 3. MP4 / M4A / AAC
        elif isinstance(audio, MP4):
            raw_title = _clean_str(tags.get("\xa9nam"))
            raw_artist = _clean_str(tags.get("\xa9ART"))
            raw_album_artist = _clean_str(tags.get("aART"))
            raw_album = _clean_str(tags.get("\xa9alb"))
            raw_year = _parse_int(tags.get("\xa9day"))
            raw_genre = _clean_str(tags.get("\xa9gen"))

            trkn = tags.get("trkn")
            if trkn and isinstance(trkn, list) and trkn[0]:
                raw_track_no = trkn[0][0]
            disk = tags.get("disk")
            if disk and isinstance(disk, list) and disk[0]:
                raw_disc_no = disk[0][0]

            covr = tags.get("covr")
            if covr and isinstance(covr, list) and covr[0]:
                has_cover_art = 1
                img_data = bytes(covr[0])
                mime, w, h = _parse_image_header(img_data)
                cover_mime = mime or ("image/png" if covr[0].imageformat == MP4Cover.FORMAT_PNG else "image/jpeg")
                cover_width = w
                cover_height = h

        # 4. OggVorbis
        elif isinstance(audio, OggVorbis):
            raw_title = _clean_str(tags.get("title"))
            raw_artist = _clean_str(tags.get("artist"))
            raw_album_artist = _clean_str(tags.get("albumartist"))
            raw_album = _clean_str(tags.get("album"))
            raw_year = _parse_int(tags.get("date"))
            raw_track_no = _parse_int(tags.get("tracknumber"))
            raw_disc_no = _parse_int(tags.get("discnumber")) or 1
            raw_genre = _clean_str(tags.get("genre"))

        # Generic / WAVE
        else:
            raw_title = _clean_str(tags.get("title") or tags.get("TIT2"))
            raw_artist = _clean_str(tags.get("artist") or tags.get("TPE1"))
            raw_album = _clean_str(tags.get("album") or tags.get("TALB"))

    # Check external folder cover art if no embedded cover
    if has_cover_art == 0:
        ext_has, ext_mime, ext_w, ext_h = _check_external_cover(path.parent)
        if ext_has:
            has_cover_art = ext_has
            cover_mime = ext_mime
            cover_width = ext_w
            cover_height = ext_h

    # Fallback to file name if title or artist is missing
    tag_source = "ID3"
    fb_artist, fb_title = parse_filename_fallback(path)

    has_tag_title = bool(raw_title)
    has_tag_artist = bool(raw_artist)

    if not has_tag_title:
        raw_title = fb_title or path.stem

    if not raw_artist and fb_artist:
        raw_artist = fb_artist

    if not has_tag_title and not has_tag_artist:
        tag_source = "FILENAME_FALLBACK"
    elif not has_tag_title or not has_tag_artist:
        tag_source = "MIXED"

    # Audio specifications
    duration_sec = 0.0
    bitrate_kbps = 0
    sample_rate_hz = 0

    if audio.info:
        duration_sec = round(float(getattr(audio.info, "length", 0.0)), 2)
        bitrate = getattr(audio.info, "bitrate", None)
        if bitrate:
            bitrate_kbps = int(bitrate // 1000)
        elif duration_sec > 0:
            bitrate_kbps = int((file_size * 8) / (duration_sec * 1000))

        sample_rate_hz = int(getattr(audio.info, "sample_rate", 0))

    # Normalized fields
    cleaned_title = clean_noise(raw_title or "")
    version_tag, no_ver_title = extract_version_tag(cleaned_title)
    feat_list, clean_core_title = extract_features(no_ver_title)
    norm_title = normalize_text(clean_core_title)
    norm_artist = normalize_text(raw_artist or "")
    feat_artists = ", ".join(feat_list) if feat_list else None

    return {
        "file_path": str(path),
        "file_name": path.name,
        "file_ext": file_ext,
        "file_size": file_size,
        "mtime": mtime,
        "partial_hash": partial_hash,
        "is_missing": 0,
        "tag_source": tag_source,
        "artist": raw_artist,
        "album_artist": raw_album_artist,
        "title": raw_title,
        "album": raw_album,
        "release_year": raw_year,
        "track_number": raw_track_no,
        "disc_number": raw_disc_no,
        "genre": raw_genre,
        "has_cover_art": has_cover_art,
        "cover_mime": cover_mime,
        "cover_width": cover_width,
        "cover_height": cover_height,
        "duration_sec": duration_sec,
        "bitrate_kbps": bitrate_kbps,
        "sample_rate_hz": sample_rate_hz,
        "norm_artist": norm_artist,
        "norm_title": norm_title,
        "feat_artists": feat_artists,
        "version_tag": version_tag,
    }
