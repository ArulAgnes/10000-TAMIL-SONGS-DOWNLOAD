"""Filesystem audio storage service.

Audio files are stored on the filesystem under a configurable root directory
(``AUDIO_STORAGE_PATH``, default ``./audio_collection``). The database stores
metadata and relative paths only; it never stores audio binary data.

Layout::

    audio_collection/
    ├── <year>/
    │   └── <album>/
    │       └── <track>.<ext>
    ├── Unknown Year/...
    └── ...
"""
import os
import re
from pathlib import Path
from typing import AsyncIterator, Optional

import aiofiles
import structlog

logger = structlog.get_logger()

INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
ALLOWED_EXTENSIONS = {"mp3", "flac", "wav", "aac", "m4a", "ogg", "wma", "opus"}
MAX_SEGMENT_LENGTH = 150
MAX_FILENAME_LENGTH = 200


class AudioStorageError(Exception):
    """Raised when a storage operation fails."""


class AudioStorage:
    """Manage physical audio files on the filesystem.

    All public path arguments are interpreted as paths *relative* to the
    storage root. Every resolved path is verified to stay inside the root so
    path traversal (``../../``) is impossible.
    """

    def __init__(self, root_dir: Optional[str] = None):
        root = root_dir or os.getenv("AUDIO_STORAGE_PATH", "./audio_collection")
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Sanitization
    # ------------------------------------------------------------------

    @staticmethod
    def sanitize_segment(name: str, fallback: str = "Untitled", max_length: int = MAX_SEGMENT_LENGTH) -> str:
        """Sanitize a single path segment (year / album / track base name)."""
        name = CONTROL_CHARS.sub("", str(name or ""))
        name = INVALID_FILENAME_CHARS.sub("_", name)
        name = re.sub(r"\s+", " ", name).strip()
        name = name.strip(" .")
        # Windows reserved names (CON, PRN, AUX, NUL, COM1..9, LPT1..9)
        if name.split(".")[0].upper() in RESERVED_WINDOWS_NAMES:
            name = f"_{name}"
        if not name:
            name = fallback
        if len(name) > max_length:
            name = name[:max_length].rstrip(" ._")
        return name or fallback

    @classmethod
    def sanitize_extension(cls, ext: Optional[str]) -> str:
        """Normalize an audio extension; fall back to mp3."""
        ext = (ext or "").lower().strip().lstrip(".")
        if ext not in ALLOWED_EXTENSIONS:
            ext = "mp3"
        return ext

    @classmethod
    def sanitize_filename(cls, filename: str, fallback: str = "track", max_length: int = MAX_FILENAME_LENGTH) -> str:
        """Sanitize a full filename, preserving a valid extension."""
        stem, ext = os.path.splitext(cls.sanitize_segment(filename, fallback, max_length))
        ext = cls.sanitize_extension(ext)
        return f"{stem[: max_length - len(ext) - 1].rstrip(' ._')}.{ext}"

    # ------------------------------------------------------------------
    # Path building / resolution
    # ------------------------------------------------------------------

    def build_relative_path(
        self,
        year: Optional[int],
        album: Optional[str],
        track: str,
        extension: Optional[str] = None,
    ) -> str:
        """Build ``<year>/<album>/<track>.<ext>`` with safe fallbacks.

        ``year`` missing  -> ``Unknown Year/<album>/...``
        ``album`` missing -> ``<year>/Unknown Album/...``
        """
        year_seg = self.sanitize_segment(str(year), "Unknown Year") if year is not None else "Unknown Year"
        if not str(year).isdigit():
            year_seg = "Unknown Year"
        album_seg = self.sanitize_segment(album, "Unknown Album")
        track_seg = self.sanitize_segment(track, "track")
        ext = self.sanitize_extension(extension)
        return f"{year_seg}/{album_seg}/{track_seg}.{ext}"

    def resolve_path(self, relative_path: str) -> Path:
        """Resolve a relative path and verify it stays inside the root."""
        if not relative_path:
            raise AudioStorageError("Empty relative path")
        resolved = (self.root / relative_path).resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise AudioStorageError(f"Path escapes audio storage root: {relative_path}")
        return resolved

    def get_audio_path(self, relative_path: str) -> Path:
        """Return the absolute path for a stored relative path."""
        return self.resolve_path(relative_path)

    def audio_exists(self, relative_path: str) -> bool:
        """Check whether an audio file exists."""
        return self.resolve_path(relative_path).is_file()

    def audio_size(self, relative_path: str) -> int:
        """Return the size of a stored file in bytes."""
        return self.resolve_path(relative_path).stat().st_size

    def delete_audio(self, relative_path: str) -> bool:
        """Delete a stored audio file. Returns True if deleted."""
        try:
            path = self.resolve_path(relative_path)
        except AudioStorageError:
            return False
        if path.exists() and path.is_file():
            path.unlink(missing_ok=True)
            return True
        return False

    def unique_path(self, relative_path: str) -> Path:
        """Return a path that does not collide with an existing file."""
        target = self.resolve_path(relative_path)
        if not target.exists():
            return target
        stem, ext = os.path.splitext(target.name)
        for i in range(1, 10000):
            candidate = target.with_name(f"{stem} ({i}){ext}")
            if not candidate.exists():
                return candidate
        raise AudioStorageError(f"Could not find a unique filename for {relative_path}")

    # ------------------------------------------------------------------
    # Saving
    # ------------------------------------------------------------------

    async def save_audio(
        self,
        chunk_iterator: AsyncIterator[bytes],
        relative_path: str,
        expected_size: Optional[int] = None,
        progress_callback: Optional[callable] = None,
        stop_event: Optional[object] = None,
    ) -> dict:
        """Stream audio chunks to ``<name>.part`` and atomically rename to the
        final path only after a successful, size-verified download.

        Args:
            chunk_iterator: async iterator yielding ``bytes`` chunks.
            relative_path: destination path relative to the storage root.
            expected_size: expected total size in bytes (verified when given).
            progress_callback: sync callable ``(downloaded_bytes) -> None``.
            stop_event: object with ``is_set()`` checked between chunks.

        Returns:
            Dict with ``relative_path``, ``absolute_path``, ``size`` and
            ``filename`` (the de-duplicated final values).

        Raises:
            AudioStorageError: on size mismatch or write failure. Partial
                ``.part`` files are always cleaned up.
        """
        target = self.unique_path(relative_path)
        part = target.with_name(f"{target.name}.part")
        part.parent.mkdir(parents=True, exist_ok=True)

        downloaded = 0
        try:
            async with aiofiles.open(part, "wb") as f:
                async for chunk in chunk_iterator:
                    if stop_event is not None and stop_event.is_set():
                        raise AudioStorageError("Download stopped by user")
                    if not chunk:
                        continue
                    await f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback:
                        progress_callback(downloaded)

            if downloaded <= 0:
                raise AudioStorageError("Downloaded file is empty")

            if expected_size is not None and expected_size > 0 and downloaded != expected_size:
                raise AudioStorageError(
                    f"Size mismatch: expected {expected_size} bytes, got {downloaded} bytes"
                )

            part.replace(target)
            return {
                "relative_path": str(target.relative_to(self.root).as_posix()),
                "absolute_path": str(target),
                "size": downloaded,
                "filename": target.name,
            }
        except Exception:
            part.unlink(missing_ok=True)
            raise

    # ------------------------------------------------------------------
    # Maintenance / stats
    # ------------------------------------------------------------------

    def cleanup_parts(self, max_age_seconds: int = 3600):
        """Delete stale ``*.part`` files left behind by interrupted downloads."""
        now = __import__("time").time()
        for part in self.root.rglob("*.part"):
            try:
                if now - part.stat().st_mtime > max_age_seconds:
                    part.unlink(missing_ok=True)
            except OSError:
                continue

    def storage_size(self) -> int:
        """Total size in bytes of all stored audio files."""
        total = 0
        for path in self.root.rglob("*"):
            if path.is_file() and not path.name.endswith(".part"):
                try:
                    total += path.stat().st_size
                except OSError:
                    continue
        return total
