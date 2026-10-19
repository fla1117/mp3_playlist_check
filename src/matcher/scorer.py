"""Quantitative scoring engine and 3-tier matching decision system."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.repository import Repository
from src.matcher.normalizer import (
    clean_noise,
    extract_artist_variants,
    extract_features,
    extract_title_variants,
    extract_version_tag,
    normalize_text,
    split_artist_title_candidates,
)


class MatchStatus(str, Enum):
    """3-Tier match status classification."""
    EXACT_MATCH = "EXACT_MATCH"
    PARTIAL_MATCH = "PARTIAL_MATCH"
    NOT_FOUND = "NOT_FOUND"


@dataclass
class MatchResult:
    """Detailed matching result for a single YouTube query."""
    status: MatchStatus
    score: float
    title_score: float
    artist_score: float
    duration_score: float
    version_penalty: float
    reason: Optional[str] = None
    yt_query: Dict[str, Any] = field(default_factory=dict)
    matched_track: Optional[Dict[str, Any]] = None
    all_candidates: List[Dict[str, Any]] = field(default_factory=list)


FORMAT_QUALITY_WEIGHTS = {
    "flac": 10,
    "wav": 8,
    "m4a": 6,
    "mp3": 4,
    "ogg": 3,
    "aac": 2,
}


class MatcherEngine:
    """Engine for candidate retrieval, quantitative scoring, and multi-track prioritization."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def calculate_duration_score(
        self, yt_duration: float, local_duration: float
    ) -> Tuple[float, float]:
        """Calculate duration score (0-100) and delta t."""
        if yt_duration <= 0 or local_duration <= 0:
            return 80.0, 0.0  # Neutral if duration info unavailable

        delta_t = abs(yt_duration - local_duration)
        for max_sec, score in DURATION_SCORE_BRACKETS:
            if delta_t <= max_sec:
                return score, delta_t

        return DURATION_SCORE_FALLBACK, delta_t

    def calculate_title_score(
        self,
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
                # If one is substring of another and reasonably long
                if len(yt_var) >= 3 and len(loc_var) >= 3:
                    if yt_var in loc_var or loc_var in yt_var:
                        best_score = max(best_score, 95.0)

                set_ratio = fuzz.token_set_ratio(yt_var, loc_var)
                sort_ratio = fuzz.token_sort_ratio(yt_var, loc_var)
                ratio = fuzz.ratio(yt_var, loc_var)
                best_score = max(best_score, set_ratio, sort_ratio, ratio)

        return min(100.0, round(best_score, 2))

    def calculate_artist_score(
        self,
        yt_artist: str,
        local_track: Dict[str, Any],
        raw_yt_title: str = "",
        uploader: str = "",
    ) -> float:
        """Calculate artist similarity score (0-100) with alias resolution and title containment."""
        loc_raw_artist = local_track.get("artist", "")
        loc_norm_artist = local_track.get("norm_artist", "")

        # Canonical aliases
        canon_loc = self.repo.resolve_canonical_artist(loc_norm_artist)
        canon_yt = self.repo.resolve_canonical_artist(yt_artist) if yt_artist else ""

        if canon_yt and canon_loc and canon_yt == canon_loc:
            return 100.0

        # Check local artist variants against YouTube artist variants
        loc_variants = extract_artist_variants(loc_raw_artist)
        if loc_norm_artist:
            loc_variants.add(loc_norm_artist)
        # Apply canonical alias resolution to all local sub-tokens
        canon_loc_subs = {self.repo.resolve_canonical_artist(v) for v in loc_variants if v}
        loc_variants.update(canon_loc_subs)

        yt_variants = extract_artist_variants(yt_artist) if yt_artist else set()
        # Apply canonical alias resolution to all YouTube sub-tokens
        canon_yt_subs = {self.repo.resolve_canonical_artist(v) for v in yt_variants if v}
        yt_variants.update(canon_yt_subs)

        for l_var in loc_variants:
            if l_var in yt_variants:
                return 100.0

        # Check containment in YouTube raw title or uploader
        norm_raw_title = normalize_text(raw_yt_title)
        norm_uploader = normalize_text(uploader)

        for l_var in loc_variants:
            if len(l_var) >= 2:
                if l_var in norm_raw_title or l_var in norm_uploader:
                    return 95.0

        # Fuzzy comparison
        best_score = 0.0
        for l_var in loc_variants:
            for y_var in yt_variants:
                if not l_var or not y_var:
                    continue
                ratio = fuzz.ratio(l_var, y_var)
                best_score = max(best_score, ratio)

        return min(100.0, round(best_score, 2))

    def evaluate_candidate(
        self,
        local_track: Dict[str, Any],
        yt_title: str,
        yt_artist: str,
        yt_duration: float,
        yt_version: str,
        raw_yt_title: str,
        uploader: str,
    ) -> Tuple[float, float, float, float, float, float]:
        """Compute all score components for a candidate track."""
        s_title = self.calculate_title_score(yt_title, local_track)
        s_artist = self.calculate_artist_score(yt_artist, local_track, raw_yt_title, uploader)
        s_duration, delta_t = self.calculate_duration_score(yt_duration, local_track.get("duration_sec", 0.0))

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

    def match(
        self,
        raw_title: str,
        uploader: str = "",
        yt_artist: Optional[str] = None,
        yt_track: Optional[str] = None,
        duration_sec: float = 0.0,
    ) -> MatchResult:
        """Execute hybrid search, bidirectional scoring, and 3-tier classification."""
        cleaned_yt = clean_noise(raw_title)
        yt_version, no_ver_title = extract_version_tag(cleaned_yt)
        feat_list, clean_core_title = extract_features(no_ver_title)

        # Generate query pairs
        # 1. Official YouTube Music metadata pair (if available)
        query_pairs: List[Tuple[str, str]] = []
        if yt_artist and yt_track:
            query_pairs.append((yt_artist, yt_track))

        # 2. Bidirectional split of video title (Artist - Title vs Title - Artist)
        split_pairs = split_artist_title_candidates(clean_core_title)
        for a, t in split_pairs:
            if (a, t) not in query_pairs:
                query_pairs.append((a, t))

        # If uploader is provided and title didn't have artist
        if uploader and len(query_pairs) == 1 and not query_pairs[0][0]:
            clean_upl = clean_noise(uploader).replace(" - Topic", "").replace("Official", "").strip()
            query_pairs.append((clean_upl, clean_core_title))

        # Retrieve candidates from repository for all query pairs
        candidate_map: Dict[int, Dict[str, Any]] = {}
        for a_cand, t_cand in query_pairs:
            cands = self.repo.search_candidates(t_cand or clean_core_title, a_cand or uploader)
            for c in cands:
                candidate_map[c["id"]] = c

        all_candidates = list(candidate_map.values())
        if not all_candidates:
            # Fallback check against all active tracks if repository is small
            all_candidates = self.repo.get_all_active_tracks()

        # Score each candidate across all query pairs
        scored_candidates: List[Tuple[float, float, float, float, float, float, str, Dict[str, Any]]] = []

        for cand in all_candidates:
            best_cand_score: Optional[Tuple[float, float, float, float, float, float, str]] = None
            for a_cand, t_cand in query_pairs:
                s_tot, s_tit, s_art, s_dur, p_ver, d_t = self.evaluate_candidate(
                    local_track=cand,
                    yt_title=t_cand or clean_core_title,
                    yt_artist=a_cand or uploader,
                    yt_duration=duration_sec,
                    yt_version=yt_version,
                    raw_yt_title=raw_title,
                    uploader=uploader,
                )
                if best_cand_score is None or s_tot > best_cand_score[0]:
                    best_cand_score = (s_tot, s_tit, s_art, s_dur, p_ver, d_t, a_cand)

            if best_cand_score:
                scored_candidates.append((*best_cand_score, cand))

        if not scored_candidates:
            return MatchResult(
                status=MatchStatus.NOT_FOUND,
                score=0.0,
                title_score=0.0,
                artist_score=0.0,
                duration_score=0.0,
                version_penalty=0.0,
                reason="로컬 라이브러리에 일치하는 곡이 없습니다.",
                yt_query={
                    "raw_title": raw_title,
                    "uploader": uploader,
                    "duration_sec": duration_sec,
                    "version_tag": yt_version,
                },
                matched_track=None,
                all_candidates=[],
            )

        # Classify each candidate's status
        def _get_status(s_tot: float, p_ver: float, s_dur: float, d_t: float) -> MatchStatus:
            if s_tot >= THRESHOLD_EXACT and p_ver == 0.0 and s_dur >= 80.0 and d_t <= DURATION_TOLERANCE_EXACT:
                return MatchStatus.EXACT_MATCH
            elif s_tot >= THRESHOLD_PARTIAL:
                return MatchStatus.PARTIAL_MATCH
            else:
                return MatchStatus.NOT_FOUND

        def _sort_key(item):
            s_tot, _, _, s_dur, p_ver, d_t, _, cand = item
            status = _get_status(s_tot, p_ver, s_dur, d_t)
            status_order = {
                MatchStatus.EXACT_MATCH: 3,
                MatchStatus.PARTIAL_MATCH: 2,
                MatchStatus.NOT_FOUND: 1,
            }[status]

            ext = cand.get("file_ext", "").lower()
            fmt_priority = FORMAT_QUALITY_WEIGHTS.get(ext, 1)
            bitrate = cand.get("bitrate_kbps", 0) or 0
            has_cover = 1 if (cand.get("has_cover_art", 0) or 0) > 0 else 0

            return (status_order, s_tot, fmt_priority, bitrate, has_cover)

        scored_candidates.sort(key=_sort_key, reverse=True)

        top_cand = scored_candidates[0]
        s_tot, s_tit, s_art, s_dur, p_ver, d_t, _, best_track = top_cand
        final_status = _get_status(s_tot, p_ver, s_dur, d_t)

        reason = None
        if final_status == MatchStatus.EXACT_MATCH:
            reason = "보유 중인 곡입니다."
        elif final_status == MatchStatus.PARTIAL_MATCH:
            reasons = []
            loc_ver = best_track.get("version_tag", "studio")
            if p_ver > 0:
                loc_ver_str = "Studio 원곡" if loc_ver == "studio" else f"{loc_ver.capitalize()} 버전"
                yt_ver_str = f"{yt_version.capitalize()} 버전"
                reasons.append(
                    f"YouTube 영상은 [{yt_ver_str}]으로 감지되었으나, 로컬 DB에는 [{loc_ver_str}]만 존재합니다."
                )
            if s_dur < 80.0 or d_t > DURATION_TOLERANCE_EXACT:
                reasons.append(
                    f"재생시간 차이가 큽니다 (YouTube: {duration_sec:.0f}초 vs 로컬: {best_track.get('duration_sec', 0.0):.0f}초, 차이: {d_t:.0f}초)."
                )
            if not reasons:
                reasons.append("동일 또는 유사 곡이 있으나 세부 정보(곡명/아티스트 유사도)가 부분 일치합니다.")
            reason = " ".join(reasons)
        else:
            reason = "로컬 라이브러리에 없는 곡입니다."

        ranked_tracks = [item[7] for item in scored_candidates if _get_status(item[0], item[4], item[3], item[5]) != MatchStatus.NOT_FOUND]

        return MatchResult(
            status=final_status,
            score=s_tot,
            title_score=s_tit,
            artist_score=s_art,
            duration_score=s_dur,
            version_penalty=p_ver,
            reason=reason,
            yt_query={
                "raw_title": raw_title,
                "uploader": uploader,
                "duration_sec": duration_sec,
                "version_tag": yt_version,
            },
            matched_track=best_track if final_status != MatchStatus.NOT_FOUND else None,
            all_candidates=ranked_tracks,
        )
