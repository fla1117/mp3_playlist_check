"""Database operations for library quality audit: missing covers, missing tags, and duplicates."""
import re
from typing import Any, Dict, List, Set

from src.matcher.normalizer import (
    extract_artist_variants,
    extract_features,
    normalize_text,
)


class AuditOpsMixin:
    """Mixin providing database queries for quality audit and deduplication."""

    def get_missing_covers(self) -> List[Dict[str, Any]]:
        """Return active tracks without any cover art (has_cover_art = 0)."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM tracks WHERE is_missing = 0 AND has_cover_art = 0 ORDER BY artist, title"
            ).fetchall()
            return [dict(r) for r in rows]

    get_missing_cover_tracks = get_missing_covers

    def get_missing_tags(self) -> List[Dict[str, Any]]:
        """Return active tracks with missing metadata or fallback tag source."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                """
                SELECT * FROM tracks
                WHERE is_missing = 0 AND (
                    artist IS NULL OR artist = '' OR
                    title IS NULL OR title = '' OR
                    album IS NULL OR album = '' OR
                    release_year IS NULL OR
                    tag_source = 'FILENAME_FALLBACK'
                )
                ORDER BY file_path
                """
            ).fetchall()
            return [dict(r) for r in rows]

    get_missing_metadata_tracks = get_missing_tags

    def get_duplicates(self) -> List[Dict[str, Any]]:
        """Return active tracks that are duplicates, with advanced alias and featuring resolution."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM tracks WHERE is_missing = 0 AND norm_title != ''"
            ).fetchall()
            tracks = [dict(r) for r in rows]

        # Group by normalized clean title first
        title_groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in tracks:
            # Extract features from title to get core title
            feat_in_title, no_feat_title = extract_features(t.get("title") or "")
            core_title = no_feat_title or t.get("title") or t.get("norm_title") or ""
            clean_title = normalize_text(core_title) or t.get("norm_title") or ""
            if not clean_title:
                continue

            # Gather all artist candidates for this track
            raw_artists: Set[str] = set()
            if t.get("artist"):
                raw_artists.update(extract_artist_variants(t["artist"]))
            if t.get("album_artist"):
                raw_artists.update(extract_artist_variants(t["album_artist"]))
            for f in feat_in_title:
                raw_artists.update(extract_artist_variants(f))
            if t.get("feat_artists"):
                for part in re.split(r"[,&/]", str(t["feat_artists"])):
                    p = part.strip()
                    if p:
                        raw_artists.update(extract_artist_variants(p))

            canon_artists = {self.resolve_canonical_artist(a) for a in raw_artists if a}  # type: ignore[attr-defined]
            if not canon_artists and t.get("norm_artist"):
                canon_artists.add(self.resolve_canonical_artist(t["norm_artist"]))  # type: ignore[attr-defined]

            t["_clean_title"] = clean_title
            t["_canon_artists"] = canon_artists

            title_groups.setdefault(clean_title, []).append(t)

        duplicate_results: List[Dict[str, Any]] = []

        # Within each title group, cluster tracks that share at least one canonical artist
        for clean_title, grp_tracks in title_groups.items():
            if len(grp_tracks) < 2:
                continue

            n = len(grp_tracks)
            parent = list(range(n))

            def find(i: int) -> int:
                while parent[i] != i:
                    parent[i] = parent[parent[i]]
                    i = parent[i]
                return i

            def union(i: int, j: int) -> None:
                root_i = find(i)
                root_j = find(j)
                if root_i != root_j:
                    parent[root_i] = root_j

            for i in range(n):
                for j in range(i + 1, n):
                    artists_i = grp_tracks[i]["_canon_artists"]
                    artists_j = grp_tracks[j]["_canon_artists"]
                    if artists_i and artists_j and (artists_i & artists_j):
                        union(i, j)

            # Collect clusters
            clusters: Dict[int, List[Dict[str, Any]]] = {}
            for i in range(n):
                root = find(i)
                clusters.setdefault(root, []).append(grp_tracks[i])

            FORMAT_WEIGHTS = {
                "flac": 10,
                "wav": 8,
                "m4a": 6,
                "mp3": 4,
                "ogg": 3,
                "aac": 2,
            }
            for cluster in clusters.values():
                if len(cluster) >= 2:
                    # Sort by quality:
                    # 1. Format weight (flac > wav > m4a > mp3 > ogg > aac)
                    # 2. Bitrate (kbps)
                    # 3. Has cover art (1 or 0)
                    # 4. Cover resolution (width * height)
                    # 5. File size (bytes)
                    # 6. ID ASC
                    cluster.sort(
                        key=lambda r: (
                            -FORMAT_WEIGHTS.get((r.get("file_ext") or "").lower().lstrip("."), 1),
                            -(r.get("bitrate_kbps") or 0),
                            -(1 if (r.get("has_cover_art") or 0) > 0 else 0),
                            -((r.get("cover_width") or 0) * (r.get("cover_height") or 0)),
                            -(r.get("file_size") or 0),
                            r["id"],
                        )
                    )
                    # Assign a consistent norm_artist / norm_title group identifier
                    rep_artist = cluster[0].get("norm_artist") or (
                        sorted(cluster[0]["_canon_artists"])[0] if cluster[0]["_canon_artists"] else ""
                    )
                    rep_title = clean_title
                    dup_group_key = f"{rep_artist}___{rep_title}"
                    for c in cluster:
                        c["norm_artist"] = rep_artist
                        c["norm_title"] = rep_title
                        c["dup_group_key"] = dup_group_key
                        # Clean temporary internal keys
                        c.pop("_clean_title", None)
                        c.pop("_canon_artists", None)
                        duplicate_results.append(c)

        return duplicate_results
