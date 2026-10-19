"""Default artist alias seed data for bilingual/colloquial artist resolution."""
from typing import List, Tuple

DEFAULT_ARTIST_ALIASES: List[Tuple[str, str]] = [
    ("아이유", "iu"),
    ("아이유", "이지은"),
    ("방탄소년단", "bts"),
    ("블랙핑크", "blackpink"),
    ("뉴진스", "newjeans"),
    ("에스파", "aespa"),
    ("데이식스", "day6"),
    ("악뮤", "akmu"),
    ("악뮤", "악동뮤지션"),
    ("소녀시대", "girlsgeneration"),
    ("소녀시대", "snsd"),
    ("트와이스", "twice"),
    ("세븐틴", "seventeen"),
]

# Alias for backward compatibility
DEFAULT_SEEDS = DEFAULT_ARTIST_ALIASES
