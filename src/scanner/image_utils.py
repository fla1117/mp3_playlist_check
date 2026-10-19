"""Binary image header parsing and external cover art search utilities."""
import struct
from pathlib import Path
from typing import Optional, Tuple

EXTERNAL_COVER_FILENAMES = [
    "cover.jpg",
    "cover.jpeg",
    "cover.png",
    "folder.jpg",
    "folder.jpeg",
    "folder.png",
    "front.jpg",
    "front.png",
]


def _parse_image_dimensions(data: bytes) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Parse PNG or JPEG binary headers to obtain mime type, width, and height without PIL."""
    if not data or len(data) < 24:
        return None, None, None

    # PNG Check
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        w, h = struct.unpack(">II", data[16:24])
        return "image/png", w, h

    # JPEG Check
    if data[:2] == b"\xff\xd8":
        idx = 2
        length_data = len(data)
        while idx < length_data - 8:
            if data[idx] != 0xFF:
                idx += 1
                continue
            marker = data[idx + 1]
            # Baseline / Progressive DCT frame markers
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[idx + 5 : idx + 9])
                return "image/jpeg", w, h
            length = struct.unpack(">H", data[idx + 2 : idx + 4])[0]
            idx += 2 + length
        return "image/jpeg", None, None

    return None, None, None


# Alias for backward compatibility
_parse_image_header = _parse_image_dimensions


def _find_external_cover(parent_dir: Path) -> Tuple[int, Optional[str], Optional[int], Optional[int]]:
    """Check if external cover art exists in the directory."""
    for name in EXTERNAL_COVER_FILENAMES:
        img_path = parent_dir / name
        if img_path.is_file():
            try:
                with open(img_path, "rb") as f:
                    header = f.read(4096)
                mime, w, h = _parse_image_dimensions(header)
                return 2, mime, w, h
            except Exception:
                return 2, "image/jpeg", None, None
    return 0, None, None, None


# Alias for backward compatibility
_check_external_cover = _find_external_cover
