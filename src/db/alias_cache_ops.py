"""Database operations for artist alias management and YouTube metadata caching."""
import json
from typing import Any, Dict, List, Optional

from src.matcher.normalizer import normalize_text


class AliasCacheOpsMixin:
    """Mixin providing artist alias resolution and YouTube cache operations."""

    _alias_cache: Dict[str, str]

    def _load_alias_cache(self) -> None:
        """Load all aliases into in-memory dictionary for O(1) canonical resolution without N+1 queries."""
        cache: Dict[str, str] = {}
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT canonical_norm_artist, alias_norm_artist FROM artist_aliases"
            ).fetchall()
            for r in rows:
                canon = r["canonical_norm_artist"]
                alias = r["alias_norm_artist"]
                cache[alias] = canon
                cache[canon] = canon
        self._alias_cache = cache

    _refresh_alias_cache = _load_alias_cache

    def add_alias(self, canonical: str, alias: str) -> None:
        """Register a canonical artist and its alias."""
        canon_norm = normalize_text(canonical)
        alias_norm = normalize_text(alias)
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                INSERT OR REPLACE INTO artist_aliases (canonical_norm_artist, alias_norm_artist)
                VALUES (?, ?)
                """,
                (canon_norm, alias_norm),
            )
            conn.commit()
        self._alias_cache[alias_norm] = canon_norm
        self._alias_cache[canon_norm] = canon_norm

    def delete_alias(self, alias: str) -> bool:
        """Delete an alias from the database and refresh the in-memory cache."""
        alias_norm = normalize_text(alias)
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute(
                "DELETE FROM artist_aliases WHERE alias_norm_artist = ?",
                (alias_norm,),
            )
            conn.commit()
            deleted = cursor.rowcount > 0
        if deleted and alias_norm in self._alias_cache:
            del self._alias_cache[alias_norm]
        return deleted

    def get_aliases(self) -> List[Dict[str, Any]]:
        """Retrieve all artist aliases."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT canonical_norm_artist, alias_norm_artist FROM artist_aliases ORDER BY canonical_norm_artist, alias_norm_artist"
            ).fetchall()
            return [dict(r) for r in rows]

    get_all_aliases = get_aliases

    def resolve_canonical_artist(self, raw_or_norm_artist: str) -> str:
        """Resolve an artist string to its canonical normalized form in O(1) via in-memory cache."""
        norm = normalize_text(raw_or_norm_artist)
        if not norm:
            return ""
        return self._alias_cache.get(norm, norm)

    def are_artists_equivalent(self, artist_a: str, artist_b: str) -> bool:
        """Check if two artist names resolve to the same canonical artist."""
        canon_a = self.resolve_canonical_artist(artist_a)
        canon_b = self.resolve_canonical_artist(artist_b)
        return bool(canon_a and canon_b and canon_a == canon_b)

    def get_cached_youtube(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve YouTube video info from cache."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM youtube_cache WHERE video_id = ?", (video_id,)
            ).fetchone()
            if row:
                d = dict(row)
                if d.get("chapters_json"):
                    try:
                        d["chapters"] = json.loads(d["chapters_json"])
                    except json.JSONDecodeError:
                        d["chapters"] = None
                return d
            return None

    get_youtube_cache = get_cached_youtube

    def save_youtube_cache(self, info: Dict[str, Any]) -> None:
        """Save YouTube metadata into cache."""
        chapters_json = None
        if info.get("chapters"):
            chapters_json = json.dumps(info["chapters"], ensure_ascii=False)

        with self.get_connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                INSERT OR REPLACE INTO youtube_cache (
                    video_id, raw_title, uploader, yt_artist, yt_track, duration_sec, chapters_json, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    info["video_id"],
                    info.get("raw_title", ""),
                    info.get("uploader", ""),
                    info.get("yt_artist", ""),
                    info.get("yt_track", ""),
                    info.get("duration_sec", 0.0),
                    chapters_json,
                ),
            )
            conn.commit()

    set_youtube_cache = save_youtube_cache
