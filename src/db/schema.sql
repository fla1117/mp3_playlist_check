-- tracks table
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 1. File system & sync management
    file_path TEXT NOT NULL UNIQUE,          -- Absolute file path
    file_name TEXT NOT NULL,                 -- File name with extension
    file_ext TEXT NOT NULL,                  -- Format extension (mp3, flac, m4a, etc.)
    file_size INTEGER NOT NULL,              -- File size in bytes
    mtime REAL NOT NULL,                     -- File modification time
    partial_hash TEXT NOT NULL,              -- SHA256 of head 64KB + tail 64KB + size
    is_missing INTEGER DEFAULT 0,            -- 0: active, 1: missing/deleted
    tag_source TEXT DEFAULT 'ID3',           -- 'ID3', 'FILENAME_FALLBACK', 'MIXED'

    -- 2. Audio metadata
    artist TEXT,                             -- Original artist
    album_artist TEXT,                       -- Album artist
    title TEXT,                              -- Original track title
    album TEXT,                              -- Album name
    release_year INTEGER,                    -- Release year (YYYY)
    track_number INTEGER,                    -- Track number
    disc_number INTEGER DEFAULT 1,           -- Disc number
    genre TEXT,                              -- Genre

    -- 3. Cover art
    has_cover_art INTEGER NOT NULL DEFAULT 0,-- 0: None, 1: Embedded, 2: External (cover.jpg/folder.jpg)
    cover_mime TEXT,                         -- image/jpeg, image/png
    cover_width INTEGER,                     -- Thumbnail width px
    cover_height INTEGER,                    -- Thumbnail height px

    -- 4. Audio specification
    duration_sec REAL NOT NULL,              -- Duration in seconds
    bitrate_kbps INTEGER,                    -- Bitrate in kbps
    sample_rate_hz INTEGER,                  -- Sample rate in Hz

    -- 5. Normalized search fields
    norm_artist TEXT NOT NULL,               -- Normalized artist (lowercase, no space/punctuation)
    norm_title TEXT NOT NULL,                -- Normalized title (no feat/noise/version)
    feat_artists TEXT,                       -- Extracted featured artists (JSON or comma separated)
    version_tag TEXT DEFAULT 'studio',       -- 'studio', 'live', 'inst', 'remix', 'acoustic', 'cover'

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_tracks_norm_title ON tracks(norm_title);
CREATE INDEX IF NOT EXISTS idx_tracks_norm_artist ON tracks(norm_artist);
CREATE INDEX IF NOT EXISTS idx_tracks_partial_hash ON tracks(partial_hash);
CREATE INDEX IF NOT EXISTS idx_tracks_has_cover ON tracks(has_cover_art);
CREATE INDEX IF NOT EXISTS idx_tracks_is_missing ON tracks(is_missing);

-- FTS5 Virtual Table
CREATE VIRTUAL TABLE IF NOT EXISTS tracks_fts USING fts5(
    artist,
    title,
    norm_artist,
    norm_title,
    album,
    content='tracks',
    content_rowid='id',
    tokenize='unicode61'
);

-- FTS Synchronization Triggers
CREATE TRIGGER IF NOT EXISTS tracks_ai AFTER INSERT ON tracks BEGIN
    INSERT INTO tracks_fts(rowid, artist, title, norm_artist, norm_title, album)
    VALUES (new.id, new.artist, new.title, new.norm_artist, new.norm_title, new.album);
END;

CREATE TRIGGER IF NOT EXISTS tracks_ad AFTER DELETE ON tracks BEGIN
    INSERT INTO tracks_fts(tracks_fts, rowid, artist, title, norm_artist, norm_title, album)
    VALUES ('delete', old.id, old.artist, old.title, old.norm_artist, old.norm_title, old.album);
END;

CREATE TRIGGER IF NOT EXISTS tracks_au AFTER UPDATE ON tracks BEGIN
    INSERT INTO tracks_fts(tracks_fts, rowid, artist, title, norm_artist, norm_title, album)
    VALUES ('delete', old.id, old.artist, old.title, old.norm_artist, old.norm_title, old.album);
    INSERT INTO tracks_fts(rowid, artist, title, norm_artist, norm_title, album)
    VALUES (new.id, new.artist, new.title, new.norm_artist, new.norm_title, new.album);
END;

-- Artist Aliases Table
CREATE TABLE IF NOT EXISTS artist_aliases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_norm_artist TEXT NOT NULL,     -- Canonical normalized artist name (e.g. '아이유')
    alias_norm_artist TEXT NOT NULL UNIQUE   -- Alias normalized artist name (e.g. 'iu', '이지은')
);
CREATE INDEX IF NOT EXISTS idx_alias_canonical ON artist_aliases(canonical_norm_artist);
CREATE INDEX IF NOT EXISTS idx_alias_norm ON artist_aliases(alias_norm_artist);

-- YouTube Cache Table
CREATE TABLE IF NOT EXISTS youtube_cache (
    video_id TEXT PRIMARY KEY,               -- YouTube Video ID (11 chars)
    raw_title TEXT NOT NULL,
    uploader TEXT,
    yt_artist TEXT,
    yt_track TEXT,
    duration_sec REAL,
    chapters_json TEXT,                      -- JSON string of chapters
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Scan Errors Table
CREATE TABLE IF NOT EXISTS scan_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    error_message TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
