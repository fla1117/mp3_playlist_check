"""SQLite Database Repository for tracks, aliases, FTS5, and YouTube cache."""
import json
import re
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple, Any

from rapidfuzz import fuzz

from src.config import DEFAULT_DB_PATH
from src.matcher.normalizer import (
    normalize_text,
    extract_title_variants,
    extract_artist_variants,
    extract_features,
)

DEFAULT_SEEDS = [
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


class Repository:
    """Database repository wrapping SQLite interactions."""

    def __init__(self, db_path: Optional[Path | str] = None):
        self._alias_cache: Dict[str, str] = {}
        if db_path is None:
            self.db_path = DEFAULT_DB_PATH
        else:
            self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        """Create a new SQLite connection with Row factory enabled."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _load_alias_cache(self) -> None:
        """Load all aliases into in-memory dictionary for O(1) canonical resolution without N+1 queries."""
        cache: Dict[str, str] = {}
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT canonical_norm_artist, alias_norm_artist FROM artist_aliases"
            ).fetchall()
            for r in rows:
                canon = r["canonical_norm_artist"]
                alias = r["alias_norm_artist"]
                cache[alias] = canon
                cache[canon] = canon
        self._alias_cache = cache

    def init_db(self) -> None:
        """Initialize database schema and seed default aliases."""
        schema_file = Path(__file__).parent / "schema.sql"
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at {schema_file}")

        with open(schema_file, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            # Seed aliases
            for canonical, alias in DEFAULT_SEEDS:
                canon_norm = normalize_text(canonical)
                alias_norm = normalize_text(alias)
                conn.execute(
                    """
                    INSERT OR IGNORE INTO artist_aliases (canonical_norm_artist, alias_norm_artist)
                    VALUES (?, ?)
                    """,
                    (canon_norm, alias_norm),
                )
            conn.commit()
        self._load_alias_cache()

    # --- Artist Aliases ---

    def add_alias(self, canonical: str, alias: str) -> None:
        """Register a canonical artist and its alias."""
        canon_norm = normalize_text(canonical)
        alias_norm = normalize_text(alias)
        with self.get_connection() as conn:
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
        with self.get_connection() as conn:
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
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT canonical_norm_artist, alias_norm_artist FROM artist_aliases ORDER BY canonical_norm_artist, alias_norm_artist"
            ).fetchall()
            return [dict(r) for r in rows]

    def resolve_canonical_artist(self, raw_or_norm_artist: str) -> str:
        """Resolve an artist string to its canonical normalized form in O(1) via in-memory cache."""
        norm = normalize_text(raw_or_norm_artist)
        if not norm:
            return ""
        return self._alias_cache.get(norm, norm)

    # --- Tracks CRUD ---

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
        with self.get_connection() as conn:
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
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE file_path = ?", (file_path,)
            ).fetchone()
            return dict(row) if row else None

    def get_track_by_partial_hash(self, partial_hash: str) -> Optional[Dict[str, Any]]:
        """Find an existing track with the same partial hash (for moved files)."""
        with self.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM tracks WHERE partial_hash = ? ORDER BY is_missing DESC LIMIT 1",
                (partial_hash,),
            ).fetchone()
            return dict(row) if row else None

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
        with self.get_connection() as conn:
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
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM tracks").fetchall()
            return {r["file_path"]: dict(r) for r in rows}

    def mark_missing_tracks(self, directory: str, found_paths: Set[str]) -> int:
        """Mark tracks located inside directory but not in found_paths as is_missing = 1.
        
        Uses Path.is_relative_to to prevent false positives for sibling folders with matching prefixes (e.g. Pop vs PopRock).
        """
        dir_path = Path(directory).resolve()
        with self.get_connection() as conn:
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
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO scan_errors (file_path, error_message) VALUES (?, ?)",
                (file_path, str(error_message)),
            )
            conn.commit()

    def get_scan_errors(self) -> List[Dict[str, Any]]:
        """Retrieve scan errors."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM scan_errors ORDER BY id DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_all_active_tracks(self) -> List[Dict[str, Any]]:
        """Retrieve all non-missing tracks."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tracks WHERE is_missing = 0"
            ).fetchall()
            return [dict(r) for r in rows]

    # --- Search & Hybrid Candidate Retrieval ---

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
                with self.get_connection() as conn:
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
        # This guarantees bilingual variants and punctuation differences aren't missed
        active_tracks = self.get_all_active_tracks()
        q_title_variants = extract_title_variants(query_title)
        q_artist_variants = extract_artist_variants(query_artist) if query_artist else set()
        canon_query_artist = self.resolve_canonical_artist(query_artist) if query_artist else ""

        scored_tracks: List[Tuple[float, Dict[str, Any]]] = []
        for t in active_tracks:
            if t["id"] in candidates_by_id:
                continue

            t_norm_title = t["norm_title"]
            t_norm_artist = t["norm_artist"]
            t_canon_artist = self.resolve_canonical_artist(t["norm_artist"])

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

    # --- YouTube Cache ---

    def get_cached_youtube(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve YouTube video info from cache."""
        with self.get_connection() as conn:
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

    def save_youtube_cache(self, info: Dict[str, Any]) -> None:
        """Save YouTube metadata into cache."""
        chapters_json = None
        if info.get("chapters"):
            chapters_json = json.dumps(info["chapters"], ensure_ascii=False)

        with self.get_connection() as conn:
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

    # --- Statistics & Quality Audit (FR-10) ---

    def get_stats(self) -> Dict[str, Any]:
        """Return library statistics."""
        with self.get_connection() as conn:
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

    def get_missing_covers(self) -> List[Dict[str, Any]]:
        """Return active tracks without any cover art (has_cover_art = 0)."""
        with self.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM tracks WHERE is_missing = 0 AND has_cover_art = 0 ORDER BY artist, title"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_missing_tags(self) -> List[Dict[str, Any]]:
        """Return active tracks with missing metadata or fallback tag source."""
        with self.get_connection() as conn:
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

    def get_duplicates(self) -> List[Dict[str, Any]]:
        """Return active tracks that are duplicates, with advanced alias and featuring resolution."""
        with self.get_connection() as conn:
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

            canon_artists = {self.resolve_canonical_artist(a) for a in raw_artists if a}
            if not canon_artists and t.get("norm_artist"):
                canon_artists.add(self.resolve_canonical_artist(t["norm_artist"]))

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
                    rep_artist = cluster[0].get("norm_artist") or (sorted(cluster[0]["_canon_artists"])[0] if cluster[0]["_canon_artists"] else "")
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

    def delete_track_by_id(self, track_id: int) -> bool:
        """Permanently delete track by ID from database."""
        with self.get_connection() as conn:
            cursor = conn.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
            conn.commit()
            return cursor.rowcount > 0

    def delete_tracks_by_ids(self, track_ids: List[int]) -> int:
        """Permanently delete multiple tracks by their IDs."""
        if not track_ids:
            return 0
        with self.get_connection() as conn:
            placeholders = ",".join("?" for _ in track_ids)
            cursor = conn.execute(f"DELETE FROM tracks WHERE id IN ({placeholders})", track_ids)
            conn.commit()
            return cursor.rowcount
