from __future__ import annotations
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Set, TYPE_CHECKING

from src.config import PARTIAL_HASH_CHUNK_SIZE, SUPPORTED_EXTENSIONS
if TYPE_CHECKING:
    from src.db.repository import Repository
from src.scanner.tag_extractor import extract_metadata


@dataclass
class ScanSummary:
    """Summary metrics of a scan run."""
    total_files: int = 0
    added: int = 0
    updated: int = 0
    moved: int = 0
    skipped: int = 0
    missing: int = 0
    errors: int = 0


def calculate_partial_hash(file_path: Path | str) -> str:
    """Calculate SHA256 of first 64KB + last 64KB + file size for fast identity & move detection."""
    path = Path(file_path)
    file_size = path.stat().st_size
    hasher = hashlib.sha256()

    with open(path, "rb") as f:
        if file_size <= PARTIAL_HASH_CHUNK_SIZE * 2:
            data = f.read()
            hasher.update(data)
        else:
            head = f.read(PARTIAL_HASH_CHUNK_SIZE)
            hasher.update(head)
            f.seek(file_size - PARTIAL_HASH_CHUNK_SIZE)
            tail = f.read(PARTIAL_HASH_CHUNK_SIZE)
            hasher.update(tail)

    hasher.update(str(file_size).encode("utf-8"))
    return hasher.hexdigest()


def scan_directory(
    directory: Path | str,
    repo: Repository,
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> ScanSummary:
    """Scan directory recursively, perform incremental sync, and record moves/deletions."""
    target_dir = Path(directory).resolve()
    if not target_dir.exists() or not target_dir.is_dir():
        raise ValueError(f"Directory not found or is not a directory: {target_dir}")

    summary = ScanSummary()
    found_files: list[Path] = []

    # 1. Discover all matching audio files
    for p in target_dir.rglob("*"):
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS:
            found_files.append(p)

    summary.total_files = len(found_files)
    scanned_paths: Set[str] = set()

    # Pre-fetch all existing tracks for O(1) in-memory sync without repeated DB connection overhead
    existing_tracks_by_path = repo.get_all_tracks_by_path()

    # 2. Process each file incrementally
    for idx, path in enumerate(found_files, start=1):
        resolved_path = str(path.resolve())
        scanned_paths.add(resolved_path)

        if progress_callback:
            progress_callback(path.name, idx, summary.total_files)

        try:
            stat = path.stat()
            file_size = stat.st_size
            mtime = stat.st_mtime

            existing_track = existing_tracks_by_path.get(resolved_path)

            # Check if unchanged (same path, mtime, file_size and active)
            if (
                existing_track
                and existing_track.get("is_missing") == 0
                and abs(existing_track.get("mtime", 0.0) - mtime) < 0.001
                and existing_track.get("file_size") == file_size
            ):
                summary.skipped += 1
                continue

            # Compute partial hash for new or modified file
            partial_hash = calculate_partial_hash(path)

            # Check if this file was moved/renamed from another location
            if not existing_track:
                moved_candidate = repo.get_track_by_partial_hash(partial_hash)
                if moved_candidate and not Path(moved_candidate["file_path"]).exists():
                    repo.update_track_path(
                        old_path=moved_candidate["file_path"],
                        new_path=resolved_path,
                        new_name=path.name,
                        new_ext=path.suffix.lower().lstrip("."),
                        mtime=mtime,
                        file_size=file_size,
                    )
                    existing_tracks_by_path[resolved_path] = moved_candidate
                    summary.moved += 1
                    continue

            # Extract tags and upsert
            track_data = extract_metadata(path, partial_hash)
            repo.upsert_track(track_data)
            existing_tracks_by_path[resolved_path] = track_data

            if existing_track:
                summary.updated += 1
            else:
                summary.added += 1

        except Exception as e:
            repo.record_scan_error(resolved_path, str(e))
            summary.errors += 1

    # 3. Mark missing/deleted files
    missing_marked = repo.mark_missing_tracks(str(target_dir), scanned_paths)
    summary.missing = missing_marked

    return summary


def sync_single_file(file_path: Path | str, repo: Repository) -> Optional[int]:
    """Scan and update a single file's metadata and cover art in the database."""
    p = Path(file_path).resolve()
    if not p.exists():
        return None
    phash = calculate_partial_hash(p)
    track_data = extract_metadata(p, phash)
    return repo.upsert_track(track_data)
