"""Data models for matching results and status classification."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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
