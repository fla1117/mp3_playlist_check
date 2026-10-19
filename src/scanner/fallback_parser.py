"""Fallback parser for extracting metadata from file names and directory paths."""
import re
from pathlib import Path
from typing import Optional, Tuple

# Pattern: Optional track number prefix, then Artist, delimiter (- or _), then Title
# Example: "01. 아이유 - 좋은 날.mp3" -> artist: "아이유", title: "좋은 날"
FILENAME_PATTERN = re.compile(
    r"^(?:\d+[\.\-\s_]+)?(?P<artist>.+?)\s*[-_–—]\s*(?P<title>.+)$"
)

# Leading track number removal: e.g. "03. 좋은 날" -> "좋은 날"
LEADING_NUM_RE = re.compile(r"^\d+[\.\-\s_]+\s*")


def parse_filename_fallback(file_path: Path | str) -> Tuple[Optional[str], Optional[str]]:
    """Parse artist and title from file name using regex pattern."""
    path = Path(file_path)
    stem = path.stem.strip()

    match = FILENAME_PATTERN.match(stem)
    if match:
        artist = match.group("artist").strip()
        title = match.group("title").strip()
        return artist if artist else None, title if title else None

    # If pattern doesn't match, strip leading track number and treat as title
    clean_stem = LEADING_NUM_RE.sub("", stem).strip()
    # Check parent folder: if parent folder doesn't look like root or numbers, could be artist
    parent_name = path.parent.name.strip()
    if parent_name and not LEADING_NUM_RE.match(parent_name) and len(parent_name) < 40:
        return parent_name, clean_stem if clean_stem else stem

    return None, clean_stem if clean_stem else stem
