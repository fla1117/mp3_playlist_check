"""Quantitative scoring engine and 3-tier matching decision system."""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.repository import Repository

from src.config import DURATION_TOLERANCE_EXACT
from src.matcher.models import MatchResult, MatchStatus
from src.matcher.normalizer import (
    clean_noise,
    extract_features,
    extract_version_tag,
    split_artist_title_candidates,
)
from src.matcher.similarity import (
    FORMAT_QUALITY_WEIGHTS,
    _quality_sort_key,
    calculate_artist_score,
    calculate_duration_score,
    calculate_title_score,
    evaluate_candidate,
    get_match_status,
)

# Re-exports for backwards compatibility
__all__ = [
    "FORMAT_QUALITY_WEIGHTS",
    "MatchResult",
    "MatchStatus",
    "MatcherEngine",
]


class MatcherEngine:
    """Engine for candidate retrieval, quantitative scoring, and multi-track prioritization."""

    def __init__(self, repo: Repository):
        self.repo = repo

    def calculate_duration_score(
        self, yt_duration: float, local_duration: float
    ) -> Tuple[float, float]:
        """Calculate duration score (0-100) and delta t."""
        return calculate_duration_score(yt_duration, local_duration)

    def calculate_title_score(
        self,
        yt_title: str,
        local_track: Dict[str, Any],
        yt_title_variants: Optional[set] = None,
    ) -> float:
        """Calculate title similarity score (0-100) supporting bilingual sub-tokens."""
        return calculate_title_score(yt_title, local_track, yt_title_variants)

    def calculate_artist_score(
        self,
        yt_artist: str,
        local_track: Dict[str, Any],
        raw_yt_title: str = "",
        uploader: str = "",
    ) -> float:
        """Calculate artist similarity score (0-100) with alias resolution and title containment."""
        return calculate_artist_score(self.repo, yt_artist, local_track, raw_yt_title, uploader)

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
        return evaluate_candidate(
            self.repo,
            local_track,
            yt_title,
            yt_artist,
            yt_duration,
            yt_version,
            raw_yt_title,
            uploader,
        )

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
        _, clean_core_title = extract_features(no_ver_title)

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

        scored_candidates.sort(key=_quality_sort_key, reverse=True)

        top_cand = scored_candidates[0]
        s_tot, s_tit, s_art, s_dur, p_ver, d_t, _, best_track = top_cand
        final_status = get_match_status(s_tot, p_ver, s_dur, d_t)

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

        ranked_tracks = [
            item[7]
            for item in scored_candidates
            if get_match_status(item[0], item[4], item[3], item[5]) != MatchStatus.NOT_FOUND
        ]

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
