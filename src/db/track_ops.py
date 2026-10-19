"""Database operations for track records, scan tracking, FTS search, and statistics."""
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from rapidfuzz import fuzz

from src.matcher.normalizer import (
    extract_artist_variants,
    extract_title_variants,
)


class TrackOpsMixin:
    """Mixin providing track CRUD, path updates, scan errors, stats, and search operations."""

    def upsert_track(self, track: Dict[str, Any]) -> int:
        """Insert or update a track record."""
        defaults = {
            "file_path": "",
            "file_name": "",
            "file_ext": "",
            "file_size": 0,
            "mtime": 0.0,
            "partial_hash": "",
            "is_missing": 0,
            "tag_source": "ID3",
            "artist": None,
            "album_artist": None,
            "title": None,
            "album": None,
            "release_year": None,
            "track_number": None,
            "disc_number": 1,
            "genre": None,
            "has_cover_art": 0,
            "cover_mime": None,
            "cover_width": None,
            "cover_height": None,
            "duration_sec": 0.0,
            "bitrate_kbps": 0,
            "sample_rate_hz": 0,
            "norm_artist": "",
            "norm_title": "",
            "feat_artists": None,
            "version_tag": "studio",
        }
        track_data = {**defaults, **track}
        sql = """
        INSERT INTO tracks (
            file_path, file_name, file_ext, file_size, mtime, partial_hash,
            is_missing, tag_source, artist, album_artist, title, album,
            release_year, track_number, disc_number, genre,
            has_cover_art, cover_mime, cover_width, cover_height,
            duration_sec, bitrate_kbps, sample_rate_hz,
            norm_artist, norm_title, feat_artists, version_tag,
            updated_at
        ) VALUES (
            :file_path, :file_name, :file_ext, :file_size, :mtime, :partial_hash,
            :is_missing, :tag_source, :artist, :album_artist, :title, :album,
            :release_year, :track_number, :disc_number, :genre,
            :has_cover_art, :cover_mime, :cover_width, :cover_height,
            :duration_sec, :bitrate_kbps, :sample_rate_hz,
            :norm_artist, :norm_title, :feat_artists, :version_tag,
            CURRENT_TIMESTAMP
        )
        ON CONFLICT(file_path) DO UPDATE SET
            file_name = excluded.file_name,
            file_ext = excluded.file_ext,
            file_size = excluded.file_size,
            mtime = excluded.mtime,
            partial_hash = excluded.partial_hash,
            is_missing = 0,
            tag_source = excluded.tag_source,
            artist = excluded.artist,
            album_artist = excluded.album_artist,
            title = excluded.title,
            album = excluded.album,
            release_year = excluded.release_year,
            track_number = excluded.track_number,
            disc_number = excluded.disc_number,
            genre = excluded.genre,
            has_cover_art = excluded.has_cover_art,
            cover_mime = excluded.cover_mime,
            cover_width = excluded.cover_width,
            cover_height = excluded.cover_height,
            duration_sec = excluded.duration_sec,
            bitrate_kbps = excluded.bitrate_kbps,
            sample_rate_hz = excluded.sample_rate_hz,
            norm_artist = excluded.norm_artist,
            norm_title = excluded.norm_title,
            feat_artists = excluded.feat_artists,
            version_tag = excluded.version_tag,
            updated_at = CURRENT_TIMESTAMP
        """
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute(sql, track_data)
            conn.commit()
            if cursor.lastrowid:
                return cursor.lastrowid
            # If updated via conflict
            row = conn.execute(
                "SELECT id FROM tracks WHERE file_path = ?", (track_data["file_path"],)
            ).fetchone()
            return row["id"] if row else 0

    def get_track_by_path(self, file_path: str) -> Optional[Dict[str, Any]]:
        """Find track by absolute file path."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM tracks WHERE file_path = ?", (file_path,)
            ).fetchone()
            return dict(row) if row else None

    def get_track_by_partial_hash(self, partial_hash: str) -> Optional[Dict[str, Any]]:
        """Find an existing track with the same partial hash (for moved files)."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            row = conn.execute(
                "SELECT * FROM tracks WHERE partial_hash = ? ORDER BY is_missing DESC LIMIT 1",
                (partial_hash,),
            ).fetchone()
            return dict(row) if row else None

    find_by_partial_hash = get_track_by_partial_hash

    def update_track_path(
        self,
        old_path: str,
        new_path: str,
        new_name: str,
        new_ext: str,
        mtime: float,
        file_size: int,
    ) -> None:
        """Update file path when file moved or renamed."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                """
                UPDATE tracks
                SET file_path = ?, file_name = ?, file_ext = ?, mtime = ?, file_size = ?, is_missing = 0, updated_at = CURRENT_TIMESTAMP
                WHERE file_path = ?
                """,
                (new_path, new_name, new_ext, mtime, file_size, old_path),
            )
            conn.commit()

    def get_all_tracks_by_path(self) -> Dict[str, Dict[str, Any]]:
        """Retrieve all tracks indexed by absolute file path in O(1) for incremental scanning."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute("SELECT * FROM tracks").fetchall()
            return {r["file_path"]: dict(r) for r in rows}

    def mark_missing_tracks(self, directory: str, found_paths: Set[str]) -> int:
        """Mark tracks located inside directory but not in found_paths as is_missing = 1.
        
        Uses Path.is_relative_to to prevent false positives for sibling folders with matching prefixes (e.g. Pop vs PopRock).
        """
        dir_path = Path(directory).resolve()
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT id, file_path FROM tracks WHERE is_missing = 0"
            ).fetchall()
            marked_count = 0
            for r in rows:
                p_path = Path(r["file_path"]).resolve()
                try:
                    if p_path.is_relative_to(dir_path) and str(p_path) not in found_paths:
                        conn.execute(
                            "UPDATE tracks SET is_missing = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                            (r["id"],),
                        )
                        marked_count += 1
                except ValueError:
                    pass
            conn.commit()
            return marked_count

    def record_scan_error(self, file_path: str, error_message: str) -> None:
        """Log a corrupt or unreadable file in scan_errors table."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            conn.execute(
                "INSERT INTO scan_errors (file_path, error_message) VALUES (?, ?)",
                (file_path, str(error_message)),
            )
            conn.commit()

    log_scan_error = record_scan_error

    def get_scan_errors(self) -> List[Dict[str, Any]]:
        """Retrieve scan errors."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM scan_errors ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_scan_errors(self) -> None:
        """Clear all records from scan_errors table."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            conn.execute("DELETE FROM scan_errors")
            conn.commit()

    def get_all_active_tracks(self) -> List[Dict[str, Any]]:
        """Retrieve all non-missing tracks."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            rows = conn.execute(
                "SELECT * FROM tracks WHERE is_missing = 0"
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_track_by_id(self, track_id: int) -> bool:
        """Permanently delete track by ID from database."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            cursor = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_tracks_by_ids(self, track_ids: List[int]) -> int:
        """Permanently delete multiple tracks by their IDs."""
        if not track_ids:
            return 0
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            placeholders = ",".join("?" for _ in track_ids)
            cursor = conn.execute(f"DELETE FROM tracks WHERE id IN ({placeholders})", track_ids)
            conn.commit()
            return cursor.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Return library statistics."""
        with self.get_connection() as conn:  # type: ignore[attr-defined]
            total_active = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE is_missing = 0"
            ).fetchone()[0]
            total_missing = conn.execute(
                "SELECT COUNT(*) FROM tracks WHERE is_missing = 1"
            ).fetchone()[0]

            # Format distribution
            format_rows = conn.execute(
                "SELECT file_ext, COUNT(*) as cnt FROM tracks WHERE is_missing = 0 GROUP BY file_ext"
            ).fetchall()
            by_format = {r["file_ext"]: r["cnt"] for r in format_rows}

            # Cover art distribution
            cover_rows = conn.execute(
                "SELECT has_cover_art, COUNT(*) as cnt FROM tracks WHERE is_missing = 0 GROUP BY has_cover_art"
            ).fetchall()
            cover_dist = {0: 0, 1: 0, 2: 0}
            for r in cover_rows:
                cover_dist[r["has_cover_art"]] = r["cnt"]

            # Errors count
            err_count = conn.execute("SELECT COUNT(*) FROM scan_errors").fetchone()[0]

            return {
                "total_active": total_active,
                "total_missing": total_missing,
                "by_format": by_format,
                "cover_art": {
                    "none": cover_dist.get(0, 0),
                    "embedded": cover_dist.get(1, 0),
                    "folder": cover_dist.get(2, 0),
                },
                "total_errors": err_count,
            }

    def search_candidates(
        self, query_title: str, query_artist: str = "", limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Retrieve candidate tracks using FTS5 and RapidFuzz pre-filtering."""
        candidates_by_id: Dict[int, Dict[str, Any]] = {}

        # 1. FTS5 Search
        fts_tokens: List[str] = []
        for word in query_title.split():
            clean_word = "".join(ch for ch in word if ch.isalnum())
            if clean_word:
                fts_tokens.append(f'"{clean_word}"')
        if query_artist:
            for word in query_artist.split():
                clean_word = "".join(ch for ch in word if ch.isalnum())
                if clean_word:
                    fts_tokens.append(f'"{clean_word}"')

        if fts_tokens:
            fts_query = " OR ".join(fts_tokens)
            try:
                with self.get_connection() as conn:  # type: ignore[attr-defined]
                    rows = conn.execute(
                        """
                        SELECT t.* FROM tracks t
                        JOIN tracks_fts f ON t.id = f.rowid
                        WHERE tracks_fts MATCH ? AND t.is_missing = 0
                        LIMIT ?
                        """,
                        (fts_query, limit),
                    ).fetchall()
                    for r in rows:
                        candidates_by_id[r["id"]] = dict(r)
            except sqlite3.OperationalError:
                pass

        # 2. In-memory RapidFuzz pre-filtering across active tracks
        active_tracks = self.get_all_active_tracks()
        q_title_variants = extract_title_variants(query_title)
        q_artist_variants = extract_artist_variants(query_artist) if query_artist else set()
        canon_query_artist = (
            self.resolve_canonical_artist(query_artist) if query_artist else ""  # type: ignore[attr-defined]
        )

        scored_tracks: List[Tuple[float, Dict[str, Any]]] = []
        for t in active_tracks:
            if t["id"] in candidates_by_id:
                continue

            t_norm_title = t["norm_title"]
            t_norm_artist = t["norm_artist"]
            t_canon_artist = self.resolve_canonical_artist(t["norm_artist"])  # type: ignore[attr-defined]

            # Check title variant exact or high ratio
            title_score = 0.0
            for q_var in q_title_variants:
                if q_var == t_norm_title or q_var in t_norm_title or t_norm_title in q_var:
                    title_score = max(title_score, 90.0)
                else:
                    ratio = fuzz.token_set_ratio(q_var, t_norm_title)
                    if ratio > title_score:
                        title_score = ratio

            # Check artist variant exact or alias
            artist_score = 0.0
            if canon_query_artist and t_canon_artist and canon_query_artist == t_canon_artist:
                artist_score = 100.0
            else:
                for a_var in q_artist_variants:
                    if a_var == t_norm_artist or a_var in t_norm_artist or t_norm_artist in a_var:
                        artist_score = max(artist_score, 90.0)
                    else:
                        ratio = fuzz.ratio(a_var, t_norm_artist)
                        if ratio > artist_score:
                            artist_score = ratio

            # Pre-filter heuristic
            if title_score >= 50.0 or (title_score >= 40.0 and artist_score >= 50.0):
                combined = title_score * 0.7 + artist_score * 0.3
                scored_tracks.append((combined, t))

        # Sort remaining by combined score descending
        scored_tracks.sort(key=lambda x: x[0], reverse=True)
        for _, t in scored_tracks[:limit]:
            if len(candidates_by_id) >= limit:
                break
            candidates_by_id[t["id"]] = t

        return list(candidates_by_id.values())

    search_fts_candidates = search_candidates
