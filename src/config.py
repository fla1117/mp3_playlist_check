"""Configuration settings and constants for mp3_playlist_check."""
from pathlib import Path

# Absolute Project Root & Data Paths (independent of current working directory)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DEFAULT_DATA_DIR / "music_library.db"
SETTINGS_PATH = DEFAULT_DATA_DIR / "settings.json"

# Audio formats
SUPPORTED_EXTENSIONS = {".mp3", ".flac", ".m4a", ".wav", ".ogg", ".aac"}

# Scanning & Hashing
PARTIAL_HASH_CHUNK_SIZE = 64 * 1024  # 64 KB

# Matcher Weights & Penalties
WEIGHT_TITLE = 0.55
WEIGHT_ARTIST = 0.30
WEIGHT_DURATION = 0.15
PENALTY_VERSION = 20.0

# Matcher Decision Thresholds
THRESHOLD_EXACT = 85.0
THRESHOLD_PARTIAL = 70.0
DURATION_TOLERANCE_EXACT = 15.0  # seconds

# Duration Score Thresholds (Delta t in seconds)
DURATION_SCORE_BRACKETS = [
    (5.0, 100.0),
    (15.0, 80.0),
    (35.0, 50.0),
]
DURATION_SCORE_FALLBACK = 0.0

# YouTube Chapter Separation
CHAPTER_SPLIT_MIN_DURATION_SEC = 600.0  # 10 minutes
