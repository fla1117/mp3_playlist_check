"""SQLite Database Repository wrapping track operations, audit operations, and alias caching."""
import sqlite3
from pathlib import Path
from typing import Dict, Optional

from src.config import DEFAULT_DB_PATH
from src.db.alias_cache_ops import AliasCacheOpsMixin
from src.db.audit_ops import AuditOpsMixin
from src.db.seed_data import DEFAULT_ARTIST_ALIASES, DEFAULT_SEEDS
from src.db.track_ops import TrackOpsMixin
from src.matcher.normalizer import normalize_text


class Repository(TrackOpsMixin, AuditOpsMixin, AliasCacheOpsMixin):
    """Database repository wrapping SQLite interactions using modular mixins."""

    def __init__(self, db_path: Optional[Path | str] = None) -> None:
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

    _get_conn = get_connection

    def init_db(self) -> None:
        """Initialize database schema and seed default aliases."""
        schema_file = Path(__file__).parent / "schema.sql"
        if not schema_file.exists():
            raise FileNotFoundError(f"Schema file not found at {schema_file}")

        with open(schema_file, "r", encoding="utf-8") as f:
            schema_sql = f.read()

        with self.get_connection() as conn:
            conn.executescript(schema_sql)
            self._seed_default_aliases(conn)
            conn.commit()
        self._load_alias_cache()

    _init_db = init_db

    def _seed_default_aliases(self, conn: sqlite3.Connection) -> None:
        """Seed default artist aliases into the database."""
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


__all__ = [
    "Repository",
    "TrackOpsMixin",
    "AuditOpsMixin",
    "AliasCacheOpsMixin",
    "DEFAULT_ARTIST_ALIASES",
    "DEFAULT_SEEDS",
]
