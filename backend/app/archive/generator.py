"""ZIP archive generator for audio collections.

Archives are generated directly from the filesystem audio collection
(``audio_collection/``) — audio is never read into the database.

Layout inside archives follows the filesystem structure::

    1990.zip            -> 1990/Album A/01 - Song.mp3 ...
    Album A.zip         -> Album A/01 - Song.mp3 ...
    1990-2026.zip       -> 1990/Album A/... 1991/... 2026/...
"""
import os
import shutil
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

import structlog

from app.storage.audio_storage import AudioStorage, ALLOWED_EXTENSIONS

logger = structlog.get_logger()


class ArchiveError(Exception):
    """Raised when archive generation fails."""


class ArchiveCancelled(ArchiveError):
    """Raised when archive generation is cancelled by the user."""


class ArchiveGenerator:
    """Generator for ZIP archives of audio collections."""

    def __init__(
        self,
        archive_dir: str = None,
        temp_dir: str = None,
    ):
        self.archive_dir = Path(archive_dir or os.getenv("ARCHIVE_DIR", "./archives")).resolve()
        self.temp_dir = Path(temp_dir or os.getenv("TEMP_DIR", "./temp/archives")).resolve()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self.cancel_event: Optional[object] = None

    def set_progress_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set callback for progress updates."""
        self.progress_callback = callback

    def set_cancel_event(self, cancel_event: Optional[object]):
        """Set an object with ``is_set()`` to support cancellation."""
        self.cancel_event = cancel_event

    def _cancelled(self) -> bool:
        return bool(self.cancel_event is not None and self.cancel_event.is_set())

    def _emit_progress(self, data: Dict[str, Any]):
        if self.progress_callback:
            try:
                self.progress_callback(data)
            except Exception as e:
                logger.error("Progress callback error", error=str(e))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_arcname(arcname: str) -> str:
        """Sanitize an archive member name (no traversal, no absolute paths)."""
        arcname = arcname.replace("\\", "/").lstrip("/")
        parts = [p for p in arcname.split("/") if p not in ("", ".", "..")]
        return "/".join(parts)

    @staticmethod
    def _is_audio_file(path: Path) -> bool:
        return path.is_file() and not path.name.endswith(".part") \
            and path.suffix.lower().lstrip(".") in ALLOWED_EXTENSIONS

    @staticmethod
    def _unique_archive_path(directory: Path, name: str) -> Path:
        target = directory / name
        if not target.exists():
            return target
        stem, ext = os.path.splitext(name)
        for i in range(1, 1000):
            candidate = directory / f"{stem} ({i}){ext}"
            if not candidate.exists():
                return candidate
        raise ArchiveError(f"Could not find a unique archive name for {name}")

    # ------------------------------------------------------------------
    # ZIP creation
    # ------------------------------------------------------------------

    async def create_zip_archive(
        self,
        source_files: List[Dict[str, Any]],
        archive_name: str,
        job_id: Optional[int] = None,
        compression: int = zipfile.ZIP_DEFLATED,
        root_folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create a ZIP archive from source files.

        Args:
            source_files: list of dicts with ``path`` (absolute) and ``arcname``.
            archive_name: final ZIP file name (e.g. ``1990.zip``).
            job_id: optional download job ID for progress events.
            root_folder: optional top-level folder placed inside the ZIP (e.g.
                ``Tamil_Songs_1990-1992``). All members are nested under it.
                Defaults to no root folder (flat year/album layout).

        Returns:
            Dict with ``success``, ``archive_path`` (absolute),
            ``relative_path`` (archive name), ``archive_name``, ``archive_size``
            and ``file_count``.
        """
        result = {
            "success": False,
            "cancelled": False,
            "archive_path": None,
            "relative_path": None,
            "archive_name": None,
            "archive_size": 0,
            "file_count": 0,
            "error": None,
        }

        if not archive_name.endswith(".zip"):
            archive_name += ".zip"

        if root_folder:
            root_folder = self._safe_arcname(root_folder).rstrip("/")

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        temp_archive_path = self.temp_dir / archive_name
        final_archive_path = self._unique_archive_path(self.archive_dir, archive_name)

        try:
            self._emit_progress({
                "type": "archive_start",
                "job_id": job_id,
                "archive_name": archive_name,
                "total_files": len(source_files),
            })

            file_count = 0
            total_size = 0

            with zipfile.ZipFile(temp_archive_path, "w", compression=compression) as zf:
                for idx, file_info in enumerate(source_files):
                    if self._cancelled():
                        raise ArchiveCancelled("Archive creation cancelled")

                    file_path = Path(file_info["path"])
                    arcname = self._safe_arcname(file_info.get("arcname", file_path.name))
                    if root_folder:
                        arcname = f"{root_folder}/{arcname}"

                    if not file_path.is_file():
                        logger.warning("File not found, skipping", path=str(file_path))
                        continue

                    file_size = file_path.stat().st_size
                    total_size += file_size
                    zf.write(file_path, arcname)
                    file_count += 1

                    if idx % 10 == 0:
                        self._emit_progress({
                            "type": "archive_progress",
                            "job_id": job_id,
                            "current": idx + 1,
                            "total": len(source_files),
                            "current_file": arcname,
                        })

            shutil.move(str(temp_archive_path), str(final_archive_path))
            archive_size = final_archive_path.stat().st_size

            result.update({
                "success": True,
                "archive_path": str(final_archive_path),
                "relative_path": final_archive_path.name,
                "archive_name": final_archive_path.name,
                "archive_size": archive_size,
                "file_count": file_count,
            })

            self._emit_progress({
                "type": "archive_complete",
                "job_id": job_id,
                "archive_name": final_archive_path.name,
                "archive_size": archive_size,
                "file_count": file_count,
            })

            logger.info(
                "Archive created",
                archive_name=final_archive_path.name,
                file_count=file_count,
                size_bytes=archive_size,
            )

        except ArchiveCancelled as e:
            logger.info("Archive cancelled", archive_name=archive_name)
            result["cancelled"] = True
            result["error"] = str(e)
            if temp_archive_path.exists():
                temp_archive_path.unlink()
        except Exception as e:
            logger.error("Archive creation failed", error=str(e))
            result["error"] = str(e)
            if temp_archive_path.exists():
                temp_archive_path.unlink()

        return result

    # ------------------------------------------------------------------
    # Collection archives (from the audio filesystem root)
    # ------------------------------------------------------------------

    async def create_year_archive(
        self,
        year: int,
        audio_root: Path,
        job_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create ``<year>.zip`` containing ``<year>/Album/01 - Song.mp3``."""
        year_dir = audio_root / AudioStorage.sanitize_segment(str(year))
        if not year_dir.is_dir():
            return {"success": False, "error": f"Year directory not found: {year_dir}"}

        source_files = []
        for file_path in sorted(year_dir.rglob("*")):
            if self._is_audio_file(file_path):
                rel = file_path.relative_to(audio_root).as_posix()
                source_files.append({"path": str(file_path), "arcname": rel})

        if not source_files:
            return {"success": False, "error": f"No audio files found for year {year}"}

        return await self.create_zip_archive(
            source_files=source_files,
            archive_name=f"{year}.zip",
            job_id=job_id,
        )

    async def create_multi_year_archive(
        self,
        years: List[int],
        audio_root: Path,
        job_id: Optional[int] = None,
        prefix: Optional[str] = None,
        root_folder: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Create ``<prefix><start>-<end>.zip`` containing year/album/... structure.

        Args:
            years: year numbers to include (only existing year dirs are added).
            audio_root: filesystem audio collection root.
            job_id: optional job ID for progress events.
            prefix: optional archive name prefix, e.g. ``Tamil_Songs_`` for
                ``Tamil_Songs_1990-1992.zip``.
            root_folder: optional top-level folder inside the ZIP, e.g.
                ``Tamil_Songs_1990-1992``.
        """
        source_files = []
        for year in sorted(years):
            year_dir = audio_root / AudioStorage.sanitize_segment(str(year))
            if not year_dir.is_dir():
                continue
            for file_path in sorted(year_dir.rglob("*")):
                if self._is_audio_file(file_path):
                    rel = file_path.relative_to(audio_root).as_posix()
                    source_files.append({"path": str(file_path), "arcname": rel})

        if not source_files:
            return {"success": False, "error": "No audio files found for specified years"}

        prefix = (prefix or "").strip().rstrip("_- ")
        if prefix:
            prefix = f"{prefix}_"
        name = f"{prefix}{min(years)}-{max(years)}.zip"
        return await self.create_zip_archive(
            source_files=source_files,
            archive_name=name,
            job_id=job_id,
            root_folder=root_folder,
        )

    async def create_album_archive(
        self,
        album_name: str,
        album_dir: Path,
        job_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create ``<Album>.zip`` containing ``Album/01 - Song.mp3``."""
        if not album_dir.is_dir():
            return {"success": False, "error": f"Album directory not found: {album_dir}"}

        source_files = []
        album_seg = AudioStorage.sanitize_segment(album_name, "Unknown Album")
        for file_path in sorted(album_dir.iterdir()):
            if self._is_audio_file(file_path):
                source_files.append({
                    "path": str(file_path),
                    "arcname": f"{album_seg}/{file_path.name}",
                })

        if not source_files:
            return {"success": False, "error": f"No audio files found for album {album_name}"}

        return await self.create_zip_archive(
            source_files=source_files,
            archive_name=f"{album_seg}.zip",
            job_id=job_id,
        )

    # ------------------------------------------------------------------
    # Archive management
    # ------------------------------------------------------------------

    def list_archives(self) -> List[Dict[str, Any]]:
        """List all created archives."""
        archives = []
        for archive_path in self.archive_dir.glob("*.zip"):
            stat = archive_path.stat()
            archives.append({
                "name": archive_path.name,
                "path": str(archive_path),
                "size": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime),
                "modified": datetime.fromtimestamp(stat.st_mtime),
            })
        return sorted(archives, key=lambda x: x["created"], reverse=True)

    def resolve_archive_path(self, relative_path: str) -> Path:
        """Resolve an archive path and keep it inside the archive directory."""
        path = (self.archive_dir / relative_path).resolve()
        try:
            path.relative_to(self.archive_dir)
        except ValueError:
            raise ArchiveError(f"Archive path escapes archive dir: {relative_path}")
        return path

    def delete_archive(self, archive_name: str) -> bool:
        """Delete an archive by name."""
        archive_path = self.archive_dir / archive_name
        if archive_path.exists():
            try:
                archive_path.unlink()
                return True
            except Exception as e:
                logger.error("Failed to delete archive", error=str(e))
        return False

    def cleanup_old_archives(self, max_age_days: int = 7):
        """Delete archives older than the given number of days."""
        cutoff = time.time() - (max_age_days * 24 * 3600)
        for archive_path in self.archive_dir.glob("*.zip"):
            try:
                if archive_path.stat().st_mtime < cutoff:
                    archive_path.unlink()
                    logger.info("Deleted old archive", archive=archive_path.name)
            except Exception as e:
                logger.error("Cleanup error", path=str(archive_path), error=str(e))
