"""Crawl service for managing crawl jobs."""
import asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable

from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.database.config import AsyncSessionLocal
from app.models.database import (
    CrawlJob, Year, Category, Album, Song, AudioResource,
    CrawlLog, FailedUrl, JobStatus, ResourceStatus
)
from app.models.schemas import CrawlerConfig, AnalyzeRequest
from app.crawler.audio_crawler import AudioWebsiteCrawler
from app.crawler.engine import CrawlerEngine

logger = structlog.get_logger()


class CrawlService:
    """Service for managing crawl operations."""
    
    def __init__(self):
        self.active_jobs: Dict[int, AudioWebsiteCrawler] = {}
        self.progress_callbacks: Dict[int, List[Callable]] = {}
    
    async def create_crawl_job(
        self,
        db: AsyncSession,
        request: AnalyzeRequest
    ) -> CrawlJob:
        """Create a new crawl job."""
        config_dict = request.config.dict() if request.config else {}
        
        job = CrawlJob(
            base_url=request.base_url,
            start_year=request.start_year,
            end_year=request.end_year,
            status=JobStatus.PENDING,
            total_years=request.end_year - request.start_year + 1,
            config=config_dict
        )
        
        db.add(job)
        await db.flush()
        await db.refresh(job)
        
        logger.info(
            "Created crawl job",
            job_id=job.id,
            base_url=request.base_url,
            years=f"{request.start_year}-{request.end_year}"
        )
        
        return job
    
    async def start_crawl(self, db: AsyncSession, job_id: int):
        """Start a crawl job."""
        job = await db.get(CrawlJob, job_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")
        
        # Update status
        job.status = JobStatus.RUNNING
        await db.commit()
        
        # Create crawler
        config = CrawlerConfig(**job.config) if job.config else CrawlerConfig()
        crawler = AudioWebsiteCrawler(config)
        crawler.set_progress_callback(lambda data: self._on_progress(job_id, data))
        self.active_jobs[job_id] = crawler

        # Start crawl in background (uses its own DB session — the request
        # session closes once the response is sent).
        asyncio.create_task(self._run_crawl(job_id, crawler))

        return job
    
    async def _run_crawl(self, job_id: int, crawler: AudioWebsiteCrawler):
        """Run the crawl operation."""
        async with AsyncSessionLocal() as db:
            job = await db.get(CrawlJob, job_id)
            if not job:
                return

            try:
                async with CrawlerEngine(crawler.engine_config) as engine:
                    # Generate year URLs
                    year_urls = crawler.generate_year_urls(
                        job.base_url,
                        job.start_year,
                        job.end_year
                    )

                    for year, url in year_urls:
                        if crawler._stop_requested:
                            break

                        # Create or get year record
                        year_record = await self._get_or_create_year(db, job_id, year, url)

                        # Crawl year
                        year_result = await crawler.crawl_year(engine, year, url, job_id)

                        # Update year record + job page totals
                        year_record.total_pages = year_result["pages"][-1]["page"] if year_result["pages"] else 0
                        year_record.status = JobStatus.COMPLETED
                        job.total_pages = (job.total_pages or 0) + year_record.total_pages
                        job.processed_pages = (job.processed_pages or 0) + year_record.total_pages
                        await db.commit()

                        # Save albums
                        for album_info in year_result["albums"]:
                            await self._save_album(db, year_record.id, album_info)

                        # Update job progress
                        job.processed_years += 1
                        await db.commit()

                        # Analyze albums
                        for album_info in year_result["albums"]:
                            if crawler._stop_requested:
                                break

                            try:
                                album_details = await crawler.analyze_album(
                                    engine,
                                    album_info.url,
                                    job_id,
                                    album_info.title
                                )
                            except Exception as e:
                                logger.error(
                                    "Album analysis failed",
                                    job_id=job_id,
                                    album_url=album_info.url,
                                    error=str(e),
                                )
                                album_details = None

                            if album_details:
                                await self._update_album_details(db, album_info.url, album_details)

                                # Save songs
                                for song_info in album_details.songs:
                                    song = await self._save_song(db, album_info.url, song_info)
                                    if song:
                                        job.processed_songs += 1

                                        # Save audio resources found on the song page
                                        for resource in song_info.audio_resources:
                                            await self._save_audio_resource(db, song.id, resource)

                            job.processed_albums += 1
                            await db.commit()

                        # Refresh the year counters from the actual database so
                        # /api/years reflects real data immediately, and sync
                        # the job totals to the real discovered counts.
                        album_count, song_count = await self._refresh_year_counts(db, year_record.id)
                        job.total_albums = (job.total_albums or 0) + album_count
                        job.total_songs = (job.total_songs or 0) + song_count
                        await db.commit()

                    # Mark job complete
                    if not crawler._stop_requested:
                        job.status = JobStatus.COMPLETED
                        job.completed_at = datetime.utcnow()
                    else:
                        job.status = JobStatus.CANCELLED

                    await db.commit()

            except Exception as e:
                logger.error("Crawl failed", job_id=job_id, error=str(e))
                job.status = JobStatus.FAILED
                await db.commit()

                # Log error
                log = CrawlLog(
                    crawl_job_id=job_id,
                    level="error",
                    message=f"Crawl failed: {str(e)}",
                    error_type=type(e).__name__,
                    error_details=str(e)
                )
                db.add(log)
                await db.commit()

            finally:
                # Cleanup
                if job_id in self.active_jobs:
                    del self.active_jobs[job_id]
    
    async def _get_or_create_year(
        self,
        db: AsyncSession,
        job_id: int,
        year: int,
        url: str
    ) -> Year:
        """Get or create year record (idempotent per year number).

        The year number is the canonical key: analyzing the same calendar year
        in a later crawl job reuses (and refreshes) the existing record instead
        of creating a duplicate ``years`` row.
        """
        result = await db.execute(
            select(Year).where(Year.crawl_job_id == job_id, Year.year == year)
        )
        year_record = result.scalar_one_or_none()

        if not year_record:
            # Reuse an existing record for this calendar year (from an earlier
            # crawl job) so duplicates never pile up. Existing albums/categories
            # stay attached to the same canonical Year row.
            result = await db.execute(
                select(Year).where(Year.year == year).order_by(Year.id)
            )
            year_record = result.scalars().first()

        if year_record:
            year_record.crawl_job_id = job_id
            year_record.url = url
            year_record.status = JobStatus.RUNNING
            return year_record

        year_record = Year(
            crawl_job_id=job_id,
            year=year,
            url=url,
            status=JobStatus.RUNNING
        )
        db.add(year_record)
        await db.flush()
        return year_record
    
    async def _save_album(self, db: AsyncSession, year_id: int, album_info):
        """Save album to database (idempotent per album URL)."""
        # Create category if needed
        result = await db.execute(
            select(Category).where(Category.url == album_info.category_url)
        )
        category = result.scalar_one_or_none()

        if not category:
            category = Category(
                year_id=year_id,
                name=f"Category {album_info.discovery_page}",
                url=album_info.category_url,
                page_number=album_info.discovery_page
            )
            db.add(category)
            await db.flush()

        # Get or create album (album URLs are unique in the database)
        result = await db.execute(
            select(Album).where(Album.url == album_info.url)
        )
        album = result.scalar_one_or_none()

        if not album:
            album = Album(
                category_id=category.id,
                title=album_info.title,
                url=album_info.url,
                cover_image_url=album_info.cover_image,
                canonical_url=album_info.url,
                status=JobStatus.PENDING
            )
            db.add(album)
            await db.flush()
        elif album.category_id != category.id:
            album.category_id = category.id

        return album
    
    async def _update_album_details(
        self,
        db: AsyncSession,
        album_url: str,
        details
    ):
        """Update album with full details."""
        result = await db.execute(select(Album).where(Album.url == album_url))
        album = result.scalar_one_or_none()
        
        if album:
            album.title = details.title
            album.release_year = details.release_year
            album.artist = details.artist
            album.music_director = details.music_director
            album.genre = details.genre
            album.description = details.description
            album.cover_image_url = details.cover_image_url
            album.zip_url = details.zip_url
            album.status = JobStatus.COMPLETED
            album.analyzed_at = datetime.utcnow()
            await db.commit()
    
    async def _save_song(self, db: AsyncSession, album_url: str, song_info) -> Optional[Song]:
        """Save song to database (idempotent per album + song page URL)."""
        result = await db.execute(select(Album).where(Album.url == album_url))
        album = result.scalar_one_or_none()

        if not album:
            return None

        # De-duplicate: song pages are unique per album, and so is the title.
        conditions = [Song.album_id == album.id]
        if song_info.url:
            conditions.append(Song.url == song_info.url)
        else:
            conditions.append(Song.title == song_info.title)

        result = await db.execute(select(Song).where(*conditions))
        song = result.scalar_one_or_none()

        if song:
            # Refresh metadata on re-crawl
            song.title = song_info.title or song.title
            song.url = song_info.url or song.url
            song.track_number = song_info.track_number or song.track_number
            song.duration = song_info.duration or song.duration
            song.artist = song_info.artist or song.artist
            if song_info.audio_resources:
                song.status = JobStatus.COMPLETED
            await db.flush()
            return song

        song = Song(
            album_id=album.id,
            title=song_info.title,
            url=song_info.url,
            track_number=song_info.track_number,
            duration=song_info.duration,
            artist=song_info.artist,
            status=JobStatus.COMPLETED if song_info.audio_resources else JobStatus.PENDING,
        )
        db.add(song)
        await db.flush()
        return song

    async def _save_audio_resource(
        self,
        db: AsyncSession,
        song_id: int,
        resource
    ):
        """Save audio resource to database, linked to its song."""
        if not song_id or not resource.url:
            return

        # Dedup: skip if this song already has this resource URL
        existing = await db.execute(
            select(AudioResource).where(
                AudioResource.song_id == song_id,
                AudioResource.url == resource.url,
            )
        )
        if existing.scalar_one_or_none():
            return

        audio = AudioResource(
            song_id=song_id,
            url=resource.url,
            format=resource.format,
            bitrate=resource.bitrate,
            file_size=resource.file_size,
            canonical_url=resource.url,
            status=ResourceStatus.AVAILABLE
        )
        db.add(audio)
        await db.flush()

    async def _refresh_year_counts(self, db: AsyncSession, year_id: int) -> tuple[int, int]:
        """Recompute album/song counters on a year row from the real data.

        Returns the ``(album_count, song_count)`` used to keep the parent
        ``CrawlJob`` totals in sync with what is actually stored.
        """
        album_count = await db.scalar(
            select(func.count(func.distinct(Album.id)))
            .join(Category, Category.id == Album.category_id)
            .where(Category.year_id == year_id)
        )
        song_count = await db.scalar(
            select(func.count(func.distinct(Song.id)))
            .join(Album, Album.id == Song.album_id)
            .join(Category, Category.id == Album.category_id)
            .where(Category.year_id == year_id)
        )
        album_count = album_count or 0
        song_count = song_count or 0

        year_record = await db.get(Year, year_id)
        if year_record:
            year_record.total_albums = album_count
            year_record.total_songs = song_count
            await db.commit()

        return album_count, song_count
    
    def _on_progress(self, job_id: int, data: Dict[str, Any]):
        """Handle progress update."""
        if job_id in self.progress_callbacks:
            for callback in self.progress_callbacks[job_id]:
                try:
                    callback(data)
                except Exception as e:
                    logger.error("Progress callback error", error=str(e))
    
    def register_progress_callback(self, job_id: int, callback: Callable):
        """Register a progress callback for a job."""
        if job_id not in self.progress_callbacks:
            self.progress_callbacks[job_id] = []
        self.progress_callbacks[job_id].append(callback)
    
    async def stop_crawl(self, job_id: int) -> bool:
        """Stop a running crawl job."""
        if job_id in self.active_jobs:
            self.active_jobs[job_id].request_stop()
            return True
        return False
    
    async def get_job_progress(self, db: AsyncSession, job_id: int) -> Dict[str, Any]:
        """Get current progress of a crawl job.

        Every percentage is clamped to ``0 <= p <= 100`` so the UI can never
        display impossible values (e.g. 850%). Counters come from the job
        columns updated during the crawl.
        """
        job = await db.get(CrawlJob, job_id)
        if not job:
            return None

        def clamp(value: float) -> float:
            return max(0.0, min(100.0, value))

        total_years = job.total_years or 0
        total_pages = job.total_pages or 0
        total_albums = job.total_albums or 0
        total_songs = job.total_songs or 0

        processed_years = job.processed_years or 0
        processed_pages = job.processed_pages or 0
        processed_albums = job.processed_albums or 0
        processed_songs = job.processed_songs or 0

        # Overall = weighted average of the four sub-progresses, only over
        # tasks the job actually tracks. Guaranteed <= 100 after clamping.
        sub_progresses = []
        for processed, total in (
            (processed_years, total_years),
            (processed_pages, total_pages),
            (processed_albums, total_albums),
            (processed_songs, total_songs),
        ):
            if total > 0:
                sub_progresses.append(min(processed, total) / total * 100)

        overall = sum(sub_progresses) / len(sub_progresses) if sub_progresses else 0

        return {
            "job_id": job_id,
            "status": job.status.value,
            "total_years": total_years,
            "processed_years": processed_years,
            "year_progress": clamp((processed_years / total_years * 100) if total_years else 0),
            "total_pages": total_pages,
            "processed_pages": processed_pages,
            "page_progress": clamp((processed_pages / total_pages * 100) if total_pages else 0),
            "total_albums": total_albums,
            "processed_albums": processed_albums,
            "album_progress": clamp((processed_albums / total_albums * 100) if total_albums else 0),
            "total_songs": total_songs,
            "processed_songs": processed_songs,
            "song_progress": clamp((processed_songs / total_songs * 100) if total_songs else 0),
            "overall_progress": clamp(overall),
        }
