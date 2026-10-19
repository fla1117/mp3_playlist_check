"""Matcher and Normalizer module."""
from src.matcher.normalizer import (
    clean_noise,
    extract_version_tag,
    extract_features,
    normalize_text,
    extract_title_variants,
    extract_artist_variants,
    recover_mojibake,
    split_artist_title_candidates,
)
from src.matcher.scorer import MatcherEngine, MatchResult, MatchStatus

__all__ = [
    "clean_noise",
    "extract_version_tag",
    "extract_features",
    "normalize_text",
    "extract_title_variants",
    "extract_artist_variants",
    "recover_mojibake",
    "split_artist_title_candidates",
    "MatcherEngine",
    "MatchResult",
    "MatchStatus",
]
