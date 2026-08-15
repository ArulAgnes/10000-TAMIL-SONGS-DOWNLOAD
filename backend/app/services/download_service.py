"""Download service for managing download jobs.

Downloads stream from the network directly to the filesystem via
``AudioStorage``. The database records metadata (status, relative path,
filename, size) — never audio bytes.
"""
import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.models.database import (
    DownloadJob, Archive, Year, Album, Song, AudioResource, Category,
    JobStatus, ResourceStatus,
)
from app.downloader.manager import DownloadManager
from app.archive.generator import ArchiveGenerator
from app.storage.audio_storage import AudioStorage

logger = structlog.get_logger()


class DownloadService:
    """Service for managing download operations."""

    def __init__(
        self,
        storage: Optional[AudioStorage] = None,
        archive_dir: Optional[str] = None,
    ):
        self.storage = storage or AudioStorage()
        self.archive_dir = archive_dir or os.getenv("ARCHIVE_DIR", "./archives")
        self.download_manager = DownloadManager(self.storage)
        self.archive_generator = ArchiveGenerator(archive_dir=self.archive_dir)

        self.active_jobs: Dict[int, asyncio.Task] = {}
        self.progress_callbacks: Dict[int, List[Callable]] = {}
        self._last_progress: Dict[int, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Progress callbacks
    # ------------------------------------------------------------------

    def register_progress_callback(self, job_id: int, callback: Callable):
        """Register a progress callback for a job."""
        if job_id not in self.progress_callbacks:
            self.progress_callbacks[job_id] = []
        self.progress_callbacks[job_id].append(callback)

    def _on_progress(self, job_id: int, data: Dict[str, Any]):
        """Handle a progress event (download manager or archive generator)."""
        data["job_id"] = job_id
        self._last_progress[job_id] = data
        if job_id in self.progress_callbacks:
            for callback in self.progress_callbacks[job_id]:
                try:
                    callback(data)
                except Exception as e:
                    logger.error("Progress callback error", error=str(e))

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    async def create_download_job(
        self,
        db: AsyncSession,
        job_type: str,
        resource_id: Optional[int] = None,
        year_ids: Optional[List[int]] = None,
        start_year: Optional[int] = None,
        end_year: Optional[int] = None,
    ) -> DownloadJob:
        """Create a new download job."""
        job = DownloadJob(
            job_type=job_type,
            year_id=year_ids[0] if year_ids else None,
            album_id=resource_id if job_type == "album" else None,
            song_id=resource_id if job_type == "song" else None,
            target_years=(
                list(range(start_year, end_year + 1))
                if start_year and end_year else year_ids
            ),
            status=JobStatus.PENDING,
            created_at=datetime.utcnow(),
        )
        db.add(job)
        await db.flush()
        await db.refresh(job)
        return job

    async def start_download(self, db: AsyncSession, job_id: int):
        """Start a download job in the background."""
        job = await db.get(DownloadJob, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        job.status = JobStatus.RUNNING
        await db.commit()

        # Run in a background task with its own DB session (the request
        # session closes once the response is sent).
        task = asyncio.create_task(self._run_download(job_id))
        self.active_jobs[job_id] = task
        return job

    async def download_song_now(self, db: AsyncSession, job_id: int) -> Dict[str, Any]:
        """Run a single-song download to completion and return the summary."""
        job = await db.get(DownloadJob, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        job.status = JobStatus.RUNNING
        await db.commit()
        return await self._run_download(job_id, db=db)

    # ------------------------------------------------------------------
    # Core download run
    # ------------------------------------------------------------------

    async def _run_download(self, job_id: int, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        """Run the download operation for a job."""
        own_session = db is None
        if db is None:
            from app.database.config import AsyncSessionLocal
            db = AsyncSessionLocal()

        summary = {"job_id": job_id, "status": JobStatus.FAILED.value, "files": []}

        try:
            job = await db.get(DownloadJob, job_id)
            resources = await self._collect_resources(db, job)
            zip_targets = await self._collect_zip_targets(db, job)
            job.total_files = len(resources) + len(zip_targets)
            await db.commit()

            if not resources and not zip_targets:
                job.status = JobStatus.COMPLETED
                job.completed_at = datetime.utcnow()
                await db.commit()
                summary.update({"status": JobStatus.COMPLETED.value, "files": []})
                return summary

            # Wire archive generator progress into the same job feed
            self.archive_generator.set_progress_callback(
                lambda data: self._on_progress(job_id, data)
            )

            results = await self.download_manager.download_resources(
                resources=resources,
                job_id=job_id,
            )
            zip_results = await self.download_manager.download_zips(
                targets=zip_targets,
                job_id=job_id,
            )

            # Record filesystem metadata in the database
            await self._apply_results(db, job, results)
            await self._record_zip_archives(db, job, zip_results)

            successful = results["successful"] + zip_results["successful"]
            failed = results["failed"] + zip_results["failed"]
            job.downloaded_files = successful
            job.failed_files = failed
            job.total_size_bytes = results["total_bytes"] + zip_results["total_bytes"]
            await db.commit()

            summary.update({
                "status": JobStatus.COMPLETED.value,
                "files": results["downloads"] + zip_results["downloads"],
            })

            # Generate an archive for the downloaded files
            if results["successful"] > 0:
                archive_result = await self._create_archive_for_job(db, job, results)
                if archive_result.get("success"):
                    job.archive_path = archive_result.get("relative_path")
                    job.archive_name = archive_result.get("archive_name")
                    job.archive_size = archive_result.get("archive_size")
                    await db.commit()

            if failed > 0 and successful == 0:
                job.status = JobStatus.FAILED
                job.error_message = "All downloads failed"
            else:
                job.status = JobStatus.COMPLETED
            job.completed_at = datetime.utcnow()
            await db.commit()

            logger.info(
                "Download job completed",
                job_id=job_id,
                files=successful,
                bytes=job.total_size_bytes,
            )

        except asyncio.CancelledError:
            job.status = JobStatus.CANCELLED
            job.error_message = "Download cancelled"
            await db.commit()
            summary.update({"status": JobStatus.CANCELLED.value})
        except Exception as e:
            logger.error("Download failed", job_id=job_id, error=str(e))
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            await db.commit()
            summary.update({"status": JobStatus.FAILED.value, "error": str(e)})

        finally:
            if job_id in self.active_jobs:
                del self.active_jobs[job_id]
            if own_session:
                await db.close()

        return summary

    async def _apply_results(self, db: AsyncSession, job: DownloadJob, results: Dict[str, Any]):
        """Write filesystem metadata back to AudioResource rows."""
        by_resource = {r.get("resource_id"): r for r in results["downloads"]}
        if not by_resource:
            return

        ids = list(by_resource.keys())
        result = await db.execute(
            select(AudioResource).where(AudioResource.id.in_(ids))
        )
        for resource in result.scalars().all():
            r = by_resource.get(resource.id)
            if not r:
                continue
            resource.download_attempts += 1
            if r.get("success"):
                resource.status = ResourceStatus.DOWNLOADED
                resource.local_path = r.get("local_path")
                resource.filename = r.get("filename")
                resource.extension = r.get("extension")
                resource.file_size = r.get("size") or resource.file_size
                resource.downloaded_at = datetime.utcnow()
                resource.last_error = None
            else:
                resource.status = ResourceStatus.FAILED
                resource.last_error = r.get("error")

        await db.commit()

    async def _collect_resources(self, db: AsyncSession, job: DownloadJob) -> List[Dict[str, Any]]:
        """Collect audio resources based on job type."""
        base = (
            select(Song, AudioResource, Album, Year)
            .join(AudioResource, AudioResource.song_id == Song.id)
            .join(Album, Song.album_id == Album.id)
            .join(Category, Album.category_id == Category.id)
            .join(Year, Category.year_id == Year.id)
            .where(AudioResource.status.in_([
                ResourceStatus.AVAILABLE,
                ResourceStatus.DOWNLOADED,
            ]))
        )

        if job.job_type == "song":
            base = base.where(Song.id == job.song_id)
        elif job.job_type == "album":
            base = base.where(Album.id == job.album_id)
        elif job.job_type == "year":
            base = base.where(Year.id == job.year_id)
        elif job.job_type == "years":
            base = base.where(Year.year.in_(job.target_years or []))

        result = await db.execute(base)
        resources = []
        seen_urls = set()

        for song, resource, album, year in result.all():
            if resource.url in seen_urls:
                continue
            seen_urls.add(resource.url)
            track_number = song.track_number
            resources.append({
                "id": resource.id,
                "song_id": song.id,
                "url": resource.url,
                "year": year.year,
                "album": album.title,
                "song": song.title,
                "artist": song.artist or album.artist,
                "track_number": track_number,
                "format": resource.format,
                "expected_size": resource.file_size,
                "local_path": resource.local_path,
                "status": resource.status.value,
            })

        return resources

    async def _collect_zip_targets(
        self,
        db: AsyncSession,
        job: DownloadJob,
    ) -> List[Dict[str, Any]]:
        """Collect album ZIP targets (``zip_url``) based on job type.

        Albums without a discovered ZIP link are skipped; ``song`` jobs never
        include ZIPs.
        """
        if job.job_type == "song":
            return []

        base = (
            select(Album, Year)
            .join(Category, Album.category_id == Category.id)
            .join(Year, Category.year_id == Year.id)
            .where(Album.zip_url.isnot(None), Album.zip_url != "")
        )

        if job.job_type == "album":
            base = base.where(Album.id == job.album_id)
        elif job.job_type == "year":
            base = base.where(Year.id == job.year_id)
        elif job.job_type == "years":
            base = base.where(Year.year.in_(job.target_years or []))

        result = await db.execute(base)
        targets = []
        for album, year in result.all():
            targets.append({
                "zip_url": album.zip_url,
                "album_id": album.id,
                "album_name": album.title,
                "year": year.year,
            })
        return targets

    async def _record_zip_archives(
        self,
        db: AsyncSession,
        job: DownloadJob,
        zip_results: Dict[str, Any],
    ) -> None:
        """Record downloaded album ZIPs as Archive metadata rows."""
        for r in zip_results.get("downloads", []):
            if not r.get("success") or not r.get("filename"):
                continue

            existing = await db.execute(
                select(Archive).where(
                    Archive.name == r["filename"],
                    Archive.source_url == r["zip_url"],
                )
            )
            if existing.scalars().first():
                # Do not create duplicate metadata for an already-downloaded ZIP
                continue

            archive = Archive(
                download_job_id=job.id,
                archive_type="album",
                name=r["filename"],
                path=r["relative_path"],
                source_url=r["zip_url"],
                size_bytes=r["size"],
                file_count=1,
                year_start=r["year"],
                year_end=r["year"],
            )
            db.add(archive)

        await db.commit()

    async def _create_archive_for_job(
        self,
        db: AsyncSession,
        job: DownloadJob,
        results: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create an archive of the files just downloaded."""
        source_files = []
        years = set()

        for r in results["downloads"]:
            local_path = r.get("local_path")
            if not r.get("success") or not local_path:
                continue
            try:
                abs_path = self.storage.get_audio_path(local_path)
            except Exception:
                continue
            if not abs_path.is_file():
                continue
            source_files.append({"path": str(abs_path), "arcname": local_path})
            parts = local_path.split("/")
            if parts and parts[0].isdigit():
                years.add(int(parts[0]))

        if not source_files:
            return {"success": False, "error": "No files to archive"}

        archive_name = f"{min(years)}-{max(years)}.zip" if years else f"audio-{job.id}.zip"
        archive_result = await self.archive_generator.create_zip_archive(
            source_files=source_files,
            archive_name=archive_name,
            job_id=job.id,
        )

        if archive_result["success"]:
            archive = Archive(
                download_job_id=job.id,
                archive_type=job.job_type,
                name=archive_result["archive_name"],
                path=archive_result["relative_path"],
                size_bytes=archive_result["archive_size"],
                file_count=archive_result["file_count"],
                year_start=min(years) if years else None,
                year_end=max(years) if years else None,
            )
            db.add(archive)
            await db.commit()

        return archive_result

    # ------------------------------------------------------------------
    # Standalone archives (from the filesystem)
    # ------------------------------------------------------------------

    async def create_year_archive(self, db: AsyncSession, year_id: int) -> Dict[str, Any]:
        """Create ``<year>.zip`` for a year stored on the filesystem."""
        year = await db.get(Year, year_id)
        if not year:
            raise ValueError(f"Year {year_id} not found")

        result = await self.archive_generator.create_year_archive(
            year.year, self.storage.root
        )
        return await self._record_archive(db, result, "year", year_start=year.year)

    async def create_album_archive(self, db: AsyncSession, album_id: int) -> Dict[str, Any]:
        """Create ``<Album>.zip`` for an album stored on the filesystem."""
        album = await db.get(Album, album_id)
        if not album:
            raise ValueError(f"Album {album_id} not found")

        year = None
        category = await db.get(Category, album.category_id)
        if category:
            year_record = await db.get(Year, category.year_id)
            if year_record:
                year = year_record.year

        album_dir = self.storage.root / str(year) if year is not None \
            else self.storage.root / "Unknown Year"
        album_dir = album_dir / album.title

        result = await self.archive_generator.create_album_archive(
            album.title, album_dir
        )
        return await self._record_archive(
            db, result, "album", year_start=year, year_end=year
        )

    async def create_years_archive(
        self, db: AsyncSession, start_year: int, end_year: int
    ) -> Dict[str, Any]:
        """Create ``<start>-<end>.zip`` for a range of years."""
        if start_year > end_year:
            raise ValueError("start_year must be <= end_year")

        result = await self.archive_generator.create_multi_year_archive(
            list(range(start_year, end_year + 1)), self.storage.root
        )
        return await self._record_archive(
            db, result, "years", year_start=start_year, year_end=end_year
        )

    async def _record_archive(
        self,
        db: AsyncSession,
        result: Dict[str, Any],
        archive_type: str,
        year_start: Optional[int] = None,
        year_end: Optional[int] = None,
    ) -> Dict[str, Any]:
        if not result.get("success"):
            return result

        archive = Archive(
            download_job_id=None,
            archive_type=archive_type,
            name=result["archive_name"],
            path=result["relative_path"],
            size_bytes=result["archive_size"],
            file_count=result["file_count"],
            year_start=year_start,
            year_end=year_end,
        )
        db.add(archive)
        await db.commit()

        return {
            **result,
            "archive_id": archive.id,
            "relative_path": result["relative_path"],
        }

    # ------------------------------------------------------------------
    # Progress / cancellation
    # ------------------------------------------------------------------

    async def get_download_progress(self, db: AsyncSession, job_id: int) -> Dict[str, Any]:
        """Get current progress of a download job."""
        job = await db.get(DownloadJob, job_id)
        if not job:
            return None

        progress = 0
        if job.total_files > 0:
            progress = min(
                100.0,
                ((job.downloaded_files + job.failed_files) / job.total_files) * 100,
            )

        last = self._last_progress.get(job_id, {})
        downloaded_size = last.get("downloaded", 0)
        current_file = last.get("filename")
        song = last.get("song")
        album = last.get("album")
        year = last.get("year")

        return {
            "job_id": job_id,
            "status": job.status.value,
            "total_files": job.total_files,
            "downloaded_files": job.downloaded_files,
            "failed_files": job.failed_files,
            "total_size_bytes": job.total_size_bytes,
            "downloaded_size_bytes": downloaded_size,
            "progress_percentage": progress,
            "current_file": current_file,
            "song": song,
            "album": album,
            "year": year,
            "archive_name": job.archive_name,
            "archive_size": job.archive_size,
            "error_message": job.error_message,
        }

    async def cancel_download(self, job_id: int) -> bool:
        """Cancel a running download job."""
        self.download_manager.request_stop()

        if job_id in self.active_jobs:
            self.active_jobs[job_id].cancel()
            return True
        return False
