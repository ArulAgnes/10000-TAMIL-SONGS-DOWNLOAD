"""Artist service: normalization, linking, search and index discovery.

Artists are created from display names seen during crawling and from artist
index pages. Every artist has a ``normalized_name`` (punctuation/case folded)
so variants like ``A.R. Rahman`` / ``A R Rahman`` resolve to one logical
artist while the original display name is preserved.
"""
import asyncio
import re
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable

from sqlalchemy import select, func, or_, distinct
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from app.database.config import AsyncSessionLocal
from app.models.database import (
    Artist, ArtistType, Song, Album, Category, Year, AudioResource,
    ResourceStatus, CrawlLog, JobStatus,
)
from app.utils import normalize_artist_name, artist_slug, split_artist_names
from app.crawler.engine import CrawlerEngine
from app.models.schemas import CrawlerConfig as CrawlerConfigSchema

logger = structlog.get_logger()

# Standard separators found inside a single "artist" field on audio sites.
_NAME_SPLIT_RE = re.compile(r";|,|\band\b|\bfeat(?:uring)?\.?|\bft\.?", re.I)


def split_artist_field(raw: Optional[str]) -> List[str]:
    """Split a combined artist field into individual display names."""
    if not raw:
        return []
    parts = _NAME_SPLIT_RE.split(raw)
    names = []
    for part in parts:
        name = re.sub(r"\s+", " ", part).strip(" -–—()[]")
        if name:
            names.append(name)
    return names


class ArtistService:
    """Service for managing artists."""

    def __init__(self):
        self.active_jobs: Dict[int, asyncio.Task] = {}
        self.progress_callbacks: Dict[int, List[Callable]] = {}

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------

    def register_progress_callback(self, job_id: int, callback: Callable):
        if job_id not in self.progress_callbacks:
            self.progress_callbacks[job_id] = []
        self.progress_callbacks[job_id].append(callback)

    def _on_progress(self, job_id: int, data: Dict[str, Any]):
        data["job_id"] = job_id
        if job_id in self.progress_callbacks:
            for cb in self.progress_callbacks[job_id]:
                try:
                    cb(data)
                except Exception as e:
                    logger.error("Artist progress callback error", error=str(e))

    # ------------------------------------------------------------------
    # Artist creation / lookup
    # ------------------------------------------------------------------

    async def get_or_create(
        self,
        db: AsyncSession,
        name: str,
        artist_type: ArtistType = ArtistType.UNKNOWN,
        source_url: Optional[str] = None,
    ) -> Artist:
        """Get an existing artist for a name or create a new one.

        Deduplication uses the normalized name. ``name`` is trimmed but
        otherwise preserved verbatim as the display name.
        """
        display = re.sub(r"\s+", " ", str(name or "")).strip()
        if not display:
            raise ValueError("Artist name is required")

        norm = normalize_artist_name(display)
        slug = artist_slug(display) or f"artist-{abs(hash(norm))}"

        result = await db.execute(
            select(Artist).where(Artist.normalized_name == norm)
        )
        artist = result.scalars().first()

        now = datetime.utcnow()
        if artist:
            artist.last_seen = now
            if source_url and not artist.source_url:
                artist.source_url = source_url
            if artist.artist_type == ArtistType.UNKNOWN and artist_type != ArtistType.UNKNOWN:
                artist.artist_type = artist_type
            return artist

        artist = Artist(
            name=display,
            normalized_name=norm,
            slug=slug,
            artist_type=artist_type,
            source_url=source_url,
            first_seen=now,
            last_seen=now,
        )
        db.add(artist)
        try:
            await db.flush()
        except Exception:
            # Slug collision (e.g. two different normalized names mapped to the
            # same slug) — reuse the existing row for the same normalized name.
            await db.rollback()
            result = await db.execute(
                select(Artist).where(Artist.normalized_name == norm)
            )
            artist = result.scalars().first()
            if artist:
                artist.last_seen = now
                return artist
            raise
        return artist

    async def link_song_artist(
        self,
        db: AsyncSession,
        song: Song,
        artist_field: Optional[str],
    ) -> Optional[Artist]:
        """Link a Song to its primary Artist (parsed from the artist field).

        Sets ``song.artist_id`` to the first parsed name. The full original
        field stays on ``song.artist`` for display.
        """
        names = split_artist_field(artist_field or song.artist)
        if not names:
            return None

        primary = await self.get_or_create(db, names[0], ArtistType.SINGER)
        song.artist_id = primary.id
        await db.flush()
        return primary

    async def link_album_artist(
        self,
        db: AsyncSession,
        album: Album,
    ) -> Optional[Artist]:
        """Link an Album to its primary artist and music director."""
        names = split_artist_field(album.artist)
        if names:
            artist = await self.get_or_create(db, names[0], ArtistType.ARTIST)
            album.artist_id = artist.id
            await db.flush()
        return album.artist

    # ------------------------------------------------------------------
    # Song counts
    # ------------------------------------------------------------------

    async def refresh_song_count(self, db: AsyncSession, artist_id: int) -> int:
        """Recompute the artist's song count from real Song rows."""
        count = await db.scalar(
            select(func.count(Song.id)).where(Song.artist_id == artist_id)
        ) or 0
        artist = await db.get(Artist, artist_id)
        if artist:
            artist.song_count = count
        return count

    async def refresh_all_song_counts(self, db: AsyncSession):
        rows = await db.execute(
            select(Song.artist_id, func.count(Song.id))
            .where(Song.artist_id.isnot(None))
            .group_by(Song.artist_id)
        )
        counts = dict(rows.all())
        artists = await db.execute(select(Artist))
        for artist in artists.scalars().all():
            artist.song_count = counts.get(artist.id, 0)
        await db.commit()

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    async def get_by_slug(self, db: AsyncSession, slug: str) -> Optional[Artist]:
        result = await db.execute(select(Artist).where(Artist.slug == slug))
        return result.scalars().first()

    async def get_by_id(self, db: AsyncSession, artist_id: int) -> Optional[Artist]:
        return await db.get(Artist, artist_id)

    async def search(
        self,
        db: AsyncSession,
        query: str,
        limit: int = 20,
    ) -> List[Artist]:
        """Database-backed artist autocomplete (never client-side filtering)."""
        term = f"%{query.strip()}%"
        result = await db.execute(
            select(Artist)
            .where(
                or_(
                    Artist.name.ilike(term),
                    Artist.normalized_name.ilike(term),
                    Artist.slug.ilike(term),
                )
            )
            .order_by(Artist.song_count.desc(), Artist.name.asc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_artists(
        self,
        db: AsyncSession,
        letter: Optional[str] = None,
        search: Optional[str] = None,
        sort: str = "name",
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[Artist], int]:
        """Paginated A-Z directory listing with filters.

        ``letter`` supports a single character or ``#`` (numbers/symbols).
        """
        query = select(Artist)
        count_query = select(func.count(Artist.id))

        def _apply_filters(stmt):
            if letter:
                if letter == "#":
                    stmt = stmt.where(
                        ~func.substr(func.lower(Artist.name), 1, 1).between(
                            "a", "z"
                        )
                    )
                else:
                    stmt = stmt.where(
                        func.lower(func.substr(Artist.name, 1, 1)) == letter.lower()
                    )
            if search:
                stmt = stmt.where(Artist.normalized_name.ilike(f"%{search.strip()}%"))
            return stmt

        count_query = _apply_filters(count_query)
        total = await db.scalar(count_query) or 0

        query = _apply_filters(query)
        if sort == "song_count":
            query = query.order_by(Artist.song_count.desc(), Artist.name.asc())
        else:
            query = query.order_by(Artist.name.asc())

        query = query.limit(limit).offset(offset)
        result = await db.execute(query)
        return result.scalars().all(), total

    async def get_artist_songs(
        self,
        db: AsyncSession,
        artist_id: int,
        year: Optional[int] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[Dict[str, Any]], int]:
        """Songs for an artist (optionally filtered by year), paginated.

        Joins Song -> Album -> Category -> Year to expose album title and year
        without N+1 queries.
        """
        base = (
            select(Song, Album, Year, func.count(distinct(AudioResource.id)).label("resource_count"))
            .join(Album, Song.album_id == Album.id)
            .join(Category, Album.category_id == Category.id)
            .join(Year, Category.year_id == Year.id)
            .outerjoin(AudioResource, AudioResource.song_id == Song.id)
            .where(Song.artist_id == artist_id)
            .group_by(Song.id, Album.id, Year.id)
        )

        count_base = (
            select(func.count(func.distinct(Song.id)))
            .join(Album, Song.album_id == Album.id)
            .join(Category, Album.category_id == Category.id)
            .join(Year, Category.year_id == Year.id)
            .where(Song.artist_id == artist_id)
        )

        if year is not None:
            base = base.where(Year.year == year)
            count_base = count_base.where(Year.year == year)

        total = await db.scalar(count_base) or 0
        base = base.order_by(Year.year.desc(), Album.title.asc(), Song.track_number.asc())
        base = base.limit(limit).offset(offset)
        result = await db.execute(base)

        songs = []
        for song, album, year, resource_count in result.all():
            songs.append({
                "id": song.id,
                "title": song.title,
                "album": album.title,
                "album_id": album.id,
                "year": year.year,
                "duration": song.duration,
                "duration_seconds": song.duration_seconds,
                "artist": song.artist,
                "track_number": song.track_number,
                "status": song.status.value if song.status else None,
                "resource_count": resource_count or 0,
                "source_url": song.url,
            })
        return songs, total

    async def get_artist_years(self, db: AsyncSession, artist_id: int) -> List[int]:
        """Distinct years in which the artist has songs, ascending."""
        result = await db.execute(
            select(distinct(Year.year))
            .join(Category, Category.year_id == Year.id)
            .join(Album, Album.category_id == Category.id)
            .join(Song, Song.album_id == Album.id)
            .where(Song.artist_id == artist_id)
            .order_by(Year.year.asc())
        )
        return [r[0] for r in result.all()]

    # ------------------------------------------------------------------
    # Artist analysis job (background)
    # ------------------------------------------------------------------

    async def start_analysis(self, db: AsyncSession, artist_id: int):
        """Start a background job that analyzes an artist's source page(s)."""
        artist = await db.get(Artist, artist_id)
        if not artist:
            raise ValueError(f"Artist {artist_id} not found")

        task = asyncio.create_task(self._run_analysis(artist_id))
        self.active_jobs[artist_id] = task
        return artist

    async def _run_analysis(self, artist_id: int):
        async with AsyncSessionLocal() as db:
            artist = await db.get(Artist, artist_id)
            if not artist:
                return
            log = CrawlLog(
                crawl_job_id=None,
                level="info",
                message=f"Analyzing artist: {artist.name}",
                url=artist.source_url,
            )
            db.add(log)

            if not artist.source_url:
                db.add(CrawlLog(
                    crawl_job_id=None,
                    level="warning",
                    message="Artist has no source URL; nothing to analyze",
                    url=artist.source_url,
                ))
                await db.commit()
                return

            from app.crawler.audio_crawler import AudioWebsiteCrawler
            config = CrawlerConfigSchema()
            crawler = AudioWebsiteCrawler(config)

            try:
                async with CrawlerEngine(crawler.engine_config) as engine:
                    found = await crawler.analyze_artist_page(
                        engine, artist.source_url, artist_id=artist_id,
                    )
                    db.add(CrawlLog(
                        crawl_job_id=None,
                        level="info",
                        message=f"Artist analysis found {len(found)} entries",
                        url=artist.source_url,
                    ))
                    await db.commit()
            except Exception as e:
                logger.error("Artist analysis failed", artist_id=artist_id, error=str(e))
                db.add(CrawlLog(
                    crawl_job_id=None,
                    level="error",
                    message=f"Artist analysis failed: {e}",
                    url=artist.source_url,
                    error_type=type(e).__name__,
                ))
                await db.commit()
            finally:
                if artist_id in self.active_jobs:
                    del self.active_jobs[artist_id]

    async def cancel_analysis(self, artist_id: int) -> bool:
        if artist_id in self.active_jobs:
            self.active_jobs[artist_id].cancel()
            return True
        return False

    # ------------------------------------------------------------------
    # Artist index discovery (metadata only — never downloads content)
    # ------------------------------------------------------------------

    async def discover_from_index(
        self,
        index_url: str,
        max_artists: int = 2000,
        artist_type: ArtistType = ArtistType.ARTIST,
    ) -> Dict[str, Any]:
        """Crawl an authorized/public artist index page and register artists.

        Only metadata (display name + source URL) is stored. No audio is
        fetched or downloaded.
        """
        from app.crawler.audio_crawler import AudioWebsiteCrawler

        config = CrawlerConfigSchema()
        crawler = AudioWebsiteCrawler(config)
        discovered = 0
        created = 0
        errors: List[str] = []

        async with AsyncSessionLocal() as db:
            try:
                async with CrawlerEngine(crawler.engine_config) as engine:
                    links = await crawler.discover_artist_links(engine, index_url)
                    for entry in links[:max_artists]:
                        name = entry.get("name")
                        url = entry.get("url")
                        if not name:
                            continue
                        discovered += 1
                        try:
                            await self.get_or_create(
                                db, name, artist_type, source_url=url
                            )
                            created += 1
                        except Exception as e:
                            errors.append(f"{name}: {e}")
                    await db.commit()
            except Exception as e:
                await db.rollback()
                errors.append(str(e))
                logger.error("Artist index discovery failed", url=index_url, error=str(e))

        return {
            "discovered": discovered,
            "created": created,
            "errors": errors,
        }
