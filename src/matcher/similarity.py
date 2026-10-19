"""Similarity calculation, scoring functions, and candidate evaluation helpers."""
from __future__ import annotations
from typing import Any, Dict, Optional, Tuple

from rapidfuzz import fuzz

from src.config import (
    DURATION_SCORE_BRACKETS,
    DURATION_SCORE_FALLBACK,
    DURATION_TOLERANCE_EXACT,
    PENALTY_VERSION,
    THRESHOLD_EXACT,
    THRESHOLD_PARTIAL,
    WEIGHT_ARTIST,
    WEIGHT_DURATION,
    WEIGHT_TITLE,
)
from src.matcher.models import MatchStatus
from src.matcher.normalizer import (
    extract_artist_variants,
    extract_title_variants,
    normalize_text,
)

FORMAT_QUALITY_WEIGHTS = {
    "flac": 10,
    "wav": 8,
    "m4a": 6,
    "mp3": 4,
    "ogg": 3,
    "aac": 2,
}


def calculate_duration_score(yt_duration: float, local_duration: float) -> Tuple[float, float]:
    """Calculate duration score (0-100) and delta t."""
    if yt_duration <= 0 or local_duration <= 0:
        return 80.0, 0.0  # Neutral if duration info unavailable

    delta_t = abs(yt_duration - local_duration)
    for max_sec, score in DURATION_SCORE_BRACKETS:
        if delta_t <= max_sec:
            return score, delta_t

    return DURATION_SCORE_FALLBACK, delta_t


def calculate_title_score(
    yt_title: str,
    local_track: Dict[str, Any],
    yt_title_variants: Optional[set] = None,
) -> float:
    """Calculate title similarity score (0-100) supporting bilingual sub-tokens."""
    if not yt_title_variants:
        yt_title_variants = extract_title_variants(yt_title)

    loc_norm_title = local_track.get("norm_title", "")
    loc_title_raw = local_track.get("title", "")
    loc_title_variants = extract_title_variants(loc_title_raw)
    if loc_norm_title:
        loc_title_variants.add(loc_norm_title)

    # 1. Exact match between any variants -> 100
    for yt_var in yt_title_variants:
        if yt_var in loc_title_variants:
            return 100.0

    # 2. Fuzzy similarity across variant pairs
    best_score = 0.0
    for yt_var in yt_title_variants:
        for loc_var in loc_title_variants:
            if not yt_var or not loc_var:
                continue
            if len(yt_var) >= 3 and len(loc_var) >= 3:
                if yt_var in loc_var or loc_var in yt_var:
                    best_score = max(best_score, 95.0)

            set_ratio = fuzz.token_set_ratio(yt_var, loc_var)
            sort_ratio = fuzz.token_sort_ratio(yt_var, loc_var)
            ratio = fuzz.ratio(yt_var, loc_var)
            best_score = max(best_score, set_ratio, sort_ratio, ratio)

    return min(100.0, round(best_score, 2))


def calculate_artist_score(
    repo: Any,
    yt_artist: str,
    local_track: Dict[str, Any],
    raw_yt_title: str = "",
    uploader: str = "",
) -> float:
    """Calculate artist similarity score (0-100) with alias resolution and title containment."""
    loc_raw_artist = local_track.get("artist", "")
    loc_norm_artist = local_track.get("norm_artist", "")

    canon_loc = repo.resolve_canonical_artist(loc_norm_artist) if repo else loc_norm_artist
    canon_yt = repo.resolve_canonical_artist(yt_artist) if repo and yt_artist else ""

    if canon_yt and canon_loc and canon_yt == canon_loc:
        return 100.0

    loc_variants = extract_artist_variants(loc_raw_artist)
    if loc_norm_artist:
        loc_variants.add(loc_norm_artist)
    if repo:
        canon_loc_subs = {repo.resolve_canonical_artist(v) for v in loc_variants if v}
        loc_variants.update(canon_loc_subs)

    yt_variants = extract_artist_variants(yt_artist) if yt_artist else set()
    if repo:
        canon_yt_subs = {repo.resolve_canonical_artist(v) for v in yt_variants if v}
        yt_variants.update(canon_yt_subs)

    for l_var in loc_variants:
        if l_var in yt_variants:
            return 100.0

    norm_raw_title = normalize_text(raw_yt_title)
    norm_uploader = normalize_text(uploader)

    for l_var in loc_variants:
        if len(l_var) >= 2:
            if l_var in norm_raw_title or l_var in norm_uploader:
                return 95.0

    best_score = 0.0
    for l_var in loc_variants:
        for y_var in yt_variants:
            if not l_var or not y_var:
                continue
            ratio = fuzz.ratio(l_var, y_var)
            best_score = max(best_score, ratio)

    return min(100.0, round(best_score, 2))


def evaluate_candidate(
    repo: Any,
    local_track: Dict[str, Any],
    yt_title: str,
    yt_artist: str,
    yt_duration: float,
    yt_version: str,
    raw_yt_title: str,
    uploader: str,
) -> Tuple[float, float, float, float, float, float]:
    """Compute all score components for a candidate track."""
    s_title = calculate_title_score(yt_title, local_track)
    s_artist = calculate_artist_score(repo, yt_artist, local_track, raw_yt_title, uploader)
    s_duration, delta_t = calculate_duration_score(yt_duration, local_track.get("duration_sec", 0.0))

    loc_version = local_track.get("version_tag", "studio") or "studio"
    p_version = 0.0
    if yt_version != loc_version:
        p_version = PENALTY_VERSION

    s_total = (
        WEIGHT_TITLE * s_title
        + WEIGHT_ARTIST * s_artist
        + WEIGHT_DURATION * s_duration
        - p_version
    )
    s_total = max(0.0, min(100.0, round(s_total, 2)))
    return s_total, s_title, s_artist, s_duration, p_version, delta_t


def get_match_status(s_tot: float, p_ver: float, s_dur: float, d_t: float) -> MatchStatus:
    """Classify candidate based on total score, version penalty, and duration delta."""
    if s_tot >= THRESHOLD_EXACT and p_ver == 0.0 and s_dur >= 80.0 and d_t <= DURATION_TOLERANCE_EXACT:
        return MatchStatus.EXACT_MATCH
    elif s_tot >= THRESHOLD_PARTIAL:
        return MatchStatus.PARTIAL_MATCH
    else:
        return MatchStatus.NOT_FOUND


def _quality_sort_key(item: Any) -> Tuple[int, float, int, int, int]:
    """Sort key for prioritizing candidates by status, score, format, bitrate, and cover presence."""
    s_tot, _, _, s_dur, p_ver, d_t, _, cand = item
    status = get_match_status(s_tot, p_ver, s_dur, d_t)
    status_order = {
        MatchStatus.EXACT_MATCH: 3,
        MatchStatus.PARTIAL_MATCH: 2,
        MatchStatus.NOT_FOUND: 1,
    }[status]

    ext = (cand.get("file_ext") or "").lower()
    fmt_priority = FORMAT_QUALITY_WEIGHTS.get(ext, 1)
    bitrate = cand.get("bitrate_kbps", 0) or 0
    has_cover = 1 if (cand.get("has_cover_art", 0) or 0) > 0 else 0

    return (status_order, s_tot, fmt_priority, bitrate, has_cover)
