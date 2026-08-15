"""API routes for the audio collection analyzer."""
import re
from datetime import datetime
from typing import List, Optional, Dict

import aiofiles
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body, Request, WebSocket
from fastapi.responses import FileResponse, Response
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database.config import get_db, AsyncSessionLocal
from app.models.database import (
    CrawlJob, Year, Category, Album, Song, AudioResource,
    DownloadJob, Archive, CrawlLog, FailedUrl, JobStatus, ResourceStatus,
)
from app.models.schemas import (
    AnalyzeRequest, AnalyzeResponse, CrawlProgress,
    YearResponse, YearDetailResponse,
    CategoryResponse,
    AlbumResponse, AlbumDetailResponse,
    SongResponse, SongDetailResponse,
    AudioResourceResponse,
    DownloadRequest, DownloadResponse, DownloadProgress,
    SongDownloadRequest, AlbumDownloadRequest, YearDownloadRequest,
    YearsDownloadRequest,
    ArchiveResponse, YearArchiveRequest, AlbumArchiveRequest,
    YearsArchiveRequest,
    SearchRequest, SearchResponse, SearchResult,
    DashboardStatistics, StatisticsOverview, YearStatistics,
    FailedUrlResponse, WebSocketMessage,
)
from app.services.crawl_service import CrawlService
from app.services.download_service import DownloadService
from app.storage.audio_storage import AudioStorage, AudioStorageError
from app.archive.generator import ArchiveError

router = APIRouter()
crawl_service = CrawlService()
download_service = DownloadService()

RANGE_RE = re.compile(r"bytes=(\d*)-(\d*)")


def _parse_range(range_header: str, file_size: int) -> Optional[tuple[int, int]]:
    """Parse an HTTP ``Range: bytes=...`` header into ``(start, end)``.

    Returns None when the header is unparseable or the range is
    unsatisfiable. Suffix ranges (``bytes=-N``) are supported.
    """
    match = RANGE_RE.match(range_header.strip())
    if not match:
        return None
    start_s, end_s = match.groups()
    try:
        if start_s:
            start, end = int(start_s), int(end_s) if end_s else file_size - 1
        else:
            suffix = int(end_s)
            start, end = max(file_size - suffix, 0), file_size - 1
    except ValueError:
        return None
    if start >= file_size or start > end:
        return None
    return start, min(end, file_size - 1)


# ============================================================================
# Analysis/Crawling Routes
# ============================================================================

@router.post("/analyze", response_model=AnalyzeResponse)
async def start_analysis(
    request: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
):
    """Start a new website analysis/crawl job."""
    if request.start_year > request.end_year:
        raise HTTPException(400, "Start year must be less than or equal to end year")

    job = await crawl_service.create_crawl_job(db, request)
    await crawl_service.start_crawl(db, job.id)

    return AnalyzeResponse(
        job_id=job.id,
        status=job.status,
        message="Analysis started successfully",
        base_url=request.base_url,
        start_year=request.start_year,
        end_year=request.end_year,
        created_at=job.created_at
    )


@router.get("/jobs/{job_id}", response_model=CrawlProgress)
async def get_job_status(
    job_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get status and progress of a crawl job."""
    progress = await crawl_service.get_job_progress(db, job_id)
    if not progress:
        raise HTTPException(404, "Job not found")

    return CrawlProgress(
        job_id=job_id,
        status=progress["status"],
        total_years=progress["total_years"],
        processed_years=progress["processed_years"],
        year_progress=progress["year_progress"],
        total_pages=progress["total_pages"],
        processed_pages=progress["processed_pages"],
        page_progress=progress["page_progress"],
        total_albums=progress["total_albums"],
        processed_albums=progress["processed_albums"],
        album_progress=progress["album_progress"],
        total_songs=progress["total_songs"],
        processed_songs=progress["processed_songs"],
        song_progress=progress["song_progress"],
        overall_progress=progress["overall_progress"],
        current_year=None,
        current_page=None,
        current_album=None,
        current_song=None,
        current_activity=None,
        started_at=None,
        estimated_completion=None,
        elapsed_seconds=None
    )


@router.post("/jobs/{job_id}/stop")
async def stop_job(job_id: int):
    """Stop a running crawl job."""
    success = await crawl_service.stop_crawl(job_id)
    if not success:
        raise HTTPException(404, "Job not found or not running")
    return {"message": "Job stop requested"}


# ============================================================================
# Year Routes
# ============================================================================

def _album_count_subq():
    return (
        select(
            Category.year_id.label("year_id"),
            func.count(func.distinct(Album.id)).label("album_count"),
        )
        .join(Album, Album.category_id == Category.id)
        .group_by(Category.year_id)
    ).subquery()


def _song_count_subq():
    return (
        select(
            Category.year_id.label("year_id"),
            func.count(func.distinct(Song.id)).label("song_count"),
        )
        .join(Album, Album.category_id == Category.id)
        .join(Song, Song.album_id == Album.id)
        .group_by(Category.year_id)
    ).subquery()


async def _year_totals(
    db: AsyncSession, year_ids: List[int]
) -> Dict[int, tuple[int, int]]:
    """Return ``{year_id: (album_count, song_count)}`` computed from the
    actual database relationships (never stale counters)."""
    if not year_ids:
        return {}

    album_subq = _album_count_subq()
    album_counts = await db.execute(
        select(album_subq.c.year_id, album_subq.c.album_count)
        .where(album_subq.c.year_id.in_(year_ids))
    )
    song_subq = _song_count_subq()
    song_counts = await db.execute(
        select(song_subq.c.year_id, song_subq.c.song_count)
        .where(song_subq.c.year_id.in_(year_ids))
    )

    album_map = dict(album_counts.all())
    song_map = dict(song_counts.all())
    return {
        year_id: (album_map.get(year_id, 0), song_map.get(year_id, 0))
        for year_id in year_ids
    }


def _year_response(year: Year, album_count: int, song_count: int) -> YearResponse:
    return YearResponse(
        id=year.id,
        crawl_job_id=year.crawl_job_id,
        year=year.year,
        url=year.url,
        status=year.status,
        total_pages=year.total_pages,
        total_albums=album_count,
        total_songs=song_count,
        created_at=year.created_at,
        completed_at=year.completed_at,
    )


@router.get("/years", response_model=List[YearResponse])
async def list_years(
    job_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db)
):
    """List all discovered years with real album/song counts."""
    query = select(Year)
    if job_id:
        query = query.where(Year.crawl_job_id == job_id)

    result = await db.execute(query.order_by(Year.year.desc()))
    years = result.scalars().all()

    totals = await _year_totals(db, [y.id for y in years])
    return [
        _year_response(y, *totals.get(y.id, (0, 0)))
        for y in years
    ]


@router.get("/years/{year_id}", response_model=YearDetailResponse)
async def get_year(
    year_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific year.

    ``Year.categories`` is eagerly loaded with ``selectinload`` so Pydantic
    serialization never triggers a lazy load (MissingGreenlet).
    """
    result = await db.execute(
        select(Year)
        .where(Year.id == year_id)
        .options(selectinload(Year.categories))
    )
    year = result.scalars().first()
    if not year:
        raise HTTPException(404, "Year not found")

    album_count, song_count = (await _year_totals(db, [year.id]))[year.id]
    response = YearDetailResponse(
        id=year.id,
        crawl_job_id=year.crawl_job_id,
        year=year.year,
        url=year.url,
        status=year.status,
        total_pages=year.total_pages,
        total_albums=album_count,
        total_songs=song_count,
        created_at=year.created_at,
        completed_at=year.completed_at,
        categories=[CategoryResponse.model_validate(c) for c in year.categories],
    )

    return response


@router.get("/years/by-year/{year}", response_model=List[YearResponse])
async def get_year_by_number(
    year: int,
    db: AsyncSession = Depends(get_db)
):
    """Get year(s) by year number with real album/song counts."""
    result = await db.execute(select(Year).where(Year.year == year))
    years = result.scalars().all()

    totals = await _year_totals(db, [y.id for y in years])
    return [
        _year_response(y, *totals.get(y.id, (0, 0)))
        for y in years
    ]


# ============================================================================
# Album Routes
# ============================================================================

@router.get("/albums", response_model=List[AlbumResponse])
async def list_albums(
    year_id: Optional[int] = None,
    category_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """List albums with optional filtering."""
    query = select(Album)

    if year_id:
        query = query.join(Category).where(Category.year_id == year_id)
    if category_id:
        query = query.where(Album.category_id == category_id)
    if search:
        query = query.where(Album.title.ilike(f"%{search}%"))

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    albums = result.scalars().all()

    return [AlbumResponse.model_validate(a) for a in albums]


@router.get("/albums/{album_id}", response_model=AlbumDetailResponse)
async def get_album(
    album_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific album."""
    result = await db.execute(
        select(Album)
        .where(Album.id == album_id)
        .options(selectinload(Album.songs))
    )
    album = result.scalars().first()
    if not album:
        raise HTTPException(404, "Album not found")

    return AlbumDetailResponse.model_validate(album)


@router.get("/albums/{album_id}/songs", response_model=List[SongResponse])
async def get_album_songs(
    album_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get songs for an album."""
    result = await db.execute(
        select(Song).where(Song.album_id == album_id)
    )
    songs = result.scalars().all()

    return [SongResponse.model_validate(s) for s in songs]


# ============================================================================
# Song Routes
# ============================================================================

@router.get("/songs", response_model=List[SongResponse])
async def list_songs(
    album_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """List songs with optional filtering."""
    query = select(Song)

    if album_id:
        query = query.where(Song.album_id == album_id)
    if search:
        query = query.where(Song.title.ilike(f"%{search}%"))

    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    songs = result.scalars().all()

    return [SongResponse.model_validate(s) for s in songs]


@router.get("/songs/{song_id}", response_model=SongDetailResponse)
async def get_song(
    song_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get detailed information about a specific song.

    ``Song.audio_resources`` is eagerly loaded with ``selectinload`` so
    Pydantic serialization never triggers a lazy load (MissingGreenlet).
    """
    result = await db.execute(
        select(Song)
        .where(Song.id == song_id)
        .options(selectinload(Song.audio_resources))
    )
    song = result.scalars().first()
    if not song:
        raise HTTPException(404, "Song not found")

    return SongDetailResponse.model_validate(song)


# ============================================================================
# Audio File Serving (filesystem, safe path resolution, HTTP range support)
# ============================================================================

@router.get("/audio/{song_id}")
async def get_audio_file(song_id: int, request: Request):
    """Serve a downloaded audio file from the filesystem.

    Resolves the stored relative path and verifies it stays inside
    ``AUDIO_STORAGE_PATH`` so arbitrary filesystem access is impossible.
    Supports HTTP range requests (streaming / seeking).
    """
    async with AsyncSessionLocal() as db:
        song = await db.get(Song, song_id)
        if not song:
            raise HTTPException(404, "Song not found")

        result = await db.execute(
            select(AudioResource)
            .where(
                AudioResource.song_id == song_id,
                AudioResource.status == ResourceStatus.DOWNLOADED,
                AudioResource.local_path.isnot(None),
            )
            .order_by(AudioResource.id)
        )
        resource = result.scalars().first()

    if not resource or not resource.local_path:
        raise HTTPException(404, "Audio file has not been downloaded yet")

    try:
        path = download_service.storage.get_audio_path(resource.local_path)
    except AudioStorageError:
        raise HTTPException(404, "Invalid audio path")
    except OSError:
        raise HTTPException(404, "Audio file not found")

    if not path.is_file():
        raise HTTPException(404, "Audio file missing from filesystem")

    extension = resource.extension or "mp3"
    media_types = {
        "mp3": "audio/mpeg", "flac": "audio/flac", "wav": "audio/wav",
        "aac": "audio/aac", "m4a": "audio/mp4", "ogg": "audio/ogg",
        "wma": "audio/x-ms-wma", "opus": "audio/ogg",
    }
    media_type = media_types.get(extension, "application/octet-stream")
    file_size = path.stat().st_size

    range_header = request.headers.get("range")
    if range_header:
        parsed = _parse_range(range_header, file_size)
        if parsed is not None:
            start, end = parsed
            length = end - start + 1
            async with aiofiles.open(path, "rb") as f:
                await f.seek(start)
                body = await f.read(length)
            return Response(
                body,
                status_code=206,
                media_type=media_type,
                headers={
                    "Accept-Ranges": "bytes",
                    "Content-Range": f"bytes {start}-{end}/{file_size}",
                    "Content-Length": str(length),
                },
            )

    return FileResponse(
        path,
        media_type=media_type,
        filename=resource.filename or path.name,
        content_disposition_type="inline",
        headers={"Accept-Ranges": "bytes"},
    )


# ============================================================================
# Download Routes
# ============================================================================

@router.post("/download/song", response_model=DownloadResponse)
async def download_song(
    request: Optional[SongDownloadRequest] = Body(default=None),
    song_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db)
):
    """Download a single song to the filesystem (waits for completion)."""
    song_id = request.song_id if request else song_id
    if not song_id:
        raise HTTPException(422, "song_id is required")

    song = await db.get(Song, song_id)
    if not song:
        raise HTTPException(404, "Song not found")

    job = await download_service.create_download_job(db, job_type="song", resource_id=song_id)
    summary = await download_service.download_song_now(db, job.id)

    file_info = next((f for f in summary.get("files", []) if f.get("success")), None)

    if summary.get("status") == JobStatus.COMPLETED.value and file_info:
        return DownloadResponse(
            job_id=job.id,
            status=JobStatus.COMPLETED,
            message="Download completed",
            estimated_files=1,
            created_at=job.created_at,
            year=file_info.get("year"),
            album=file_info.get("album"),
            song=file_info.get("song"),
            filename=file_info.get("filename"),
            local_path=file_info.get("local_path"),
            file_size=file_info.get("size"),
        )

    error = summary.get("error") or (file_info or {}).get("error") or "Download failed"
    raise HTTPException(400, error)


@router.post("/download/album", response_model=DownloadResponse)
async def download_album(
    request: Optional[AlbumDownloadRequest] = Body(default=None),
    album_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db)
):
    """Create a download job for an album (background)."""
    album_id = request.album_id if request else album_id
    if not album_id:
        raise HTTPException(422, "album_id is required")

    result = await db.execute(
        select(func.count(func.distinct(AudioResource.id)))
        .join(Song, Song.id == AudioResource.song_id)
        .where(Song.album_id == album_id)
    )
    count = result.scalar() or 0

    album = await db.get(Album, album_id)
    if album and album.zip_url:
        count += 1

    job = await download_service.create_download_job(
        db, job_type="album", resource_id=album_id
    )
    await download_service.start_download(db, job.id)

    return DownloadResponse(
        job_id=job.id,
        status=JobStatus.RUNNING,
        message="Download started",
        estimated_files=count,
        created_at=job.created_at
    )


@router.post("/download/year", response_model=DownloadResponse)
async def download_year(
    request: Optional[YearDownloadRequest] = Body(default=None),
    year_id: Optional[int] = Query(default=None),
    db: AsyncSession = Depends(get_db)
):
    """Create a download job for a year (background)."""
    year_id = request.year_id if request else year_id
    if not year_id:
        raise HTTPException(422, "year_id is required")

    result = await db.execute(
        select(func.count(func.distinct(AudioResource.id)))
        .join(Song, Song.id == AudioResource.song_id)
        .join(Album, Album.id == Song.album_id)
        .join(Category, Category.id == Album.category_id)
        .where(Category.year_id == year_id)
    )
    count = result.scalar() or 0

    zip_count = await db.execute(
        select(func.count(Album.id))
        .join(Category, Category.id == Album.category_id)
        .where(
            Category.year_id == year_id,
            Album.zip_url.isnot(None),
            Album.zip_url != "",
        )
    )
    count += zip_count.scalar() or 0

    job = await download_service.create_download_job(
        db, job_type="year", year_ids=[year_id]
    )
    await download_service.start_download(db, job.id)

    return DownloadResponse(
        job_id=job.id,
        status=JobStatus.RUNNING,
        message="Download started",
        estimated_files=count,
        created_at=job.created_at
    )


@router.post("/download/years", response_model=DownloadResponse)
async def download_years(
    request: YearsDownloadRequest = Body(...),
    db: AsyncSession = Depends(get_db)
):
    """Create a download job for multiple years (background)."""
    if request.start_year > request.end_year:
        raise HTTPException(400, "start_year must be <= end_year")

    result = await db.execute(
        select(func.count(func.distinct(AudioResource.id)))
        .join(Song, Song.id == AudioResource.song_id)
        .join(Album, Album.id == Song.album_id)
        .join(Category, Category.id == Album.category_id)
        .join(Year, Year.id == Category.year_id)
        .where(Year.year.between(request.start_year, request.end_year))
    )
    count = result.scalar() or 0

    job = await download_service.create_download_job(
        db,
        job_type="years",
        start_year=request.start_year,
        end_year=request.end_year
    )
    await download_service.start_download(db, job.id)

    return DownloadResponse(
        job_id=job.id,
        status=JobStatus.RUNNING,
        message="Download started",
        estimated_files=count,
        created_at=job.created_at
    )


@router.get("/download/{job_id}/progress", response_model=DownloadProgress)
async def get_download_progress(
    job_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get progress of a download job."""
    progress = await download_service.get_download_progress(db, job_id)
    if not progress:
        raise HTTPException(404, "Job not found")

    return DownloadProgress(
        job_id=job_id,
        status=progress["status"],
        total_files=progress["total_files"],
        downloaded_files=progress["downloaded_files"],
        failed_files=progress["failed_files"],
        total_size_bytes=progress["total_size_bytes"],
        downloaded_size_bytes=progress["downloaded_size_bytes"],
        progress_percentage=progress["progress_percentage"],
        current_file=progress["current_file"],
        speed_mbps=None,
        eta_seconds=None
    )


@router.post("/download/{job_id}/cancel")
async def cancel_download(job_id: int):
    """Cancel a download job."""
    success = await download_service.cancel_download(job_id)
    if not success:
        raise HTTPException(404, "Job not found or not running")
    return {"message": "Download cancelled"}


# ============================================================================
# Archive Routes
# ============================================================================

@router.post("/archive/year", response_model=ArchiveResponse)
async def create_year_archive(
    request: YearArchiveRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a ``<year>.zip`` archive from the filesystem collection."""
    result = await download_service.create_year_archive(db, request.year_id)
    return await _archive_response(db, result)


@router.post("/archive/album", response_model=ArchiveResponse)
async def create_album_archive(
    request: AlbumArchiveRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create an ``<Album>.zip`` archive from the filesystem collection."""
    result = await download_service.create_album_archive(db, request.album_id)
    return await _archive_response(db, result)


@router.post("/archive/years", response_model=ArchiveResponse)
async def create_years_archive(
    request: YearsArchiveRequest,
    db: AsyncSession = Depends(get_db)
):
    """Create a ``<start>-<end>.zip`` archive from the filesystem collection."""
    if request.start_year > request.end_year:
        raise HTTPException(400, "start_year must be <= end_year")
    result = await download_service.create_years_archive(
        db, request.start_year, request.end_year
    )
    return await _archive_response(db, result)


async def _archive_response(db: AsyncSession, result: dict) -> ArchiveResponse:
    """Build an ArchiveResponse from an archive generation result."""
    if not result.get("success"):
        raise HTTPException(400, result.get("error") or "Archive creation failed")

    archive_id = result.get("archive_id")
    if not archive_id:
        raise HTTPException(500, "Archive record missing")

    archive = await db.get(Archive, archive_id)
    if not archive:
        raise HTTPException(404, "Archive not found")

    return _serialize_archive(archive)


@router.get("/archives", response_model=List[ArchiveResponse])
async def list_archives(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """List available archives."""
    result = await db.execute(
        select(Archive)
        .order_by(Archive.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    archives = result.scalars().all()

    return [_serialize_archive(a) for a in archives]


@router.get("/archive/{archive_id}", response_model=ArchiveResponse)
async def get_archive(
    archive_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get archive information."""
    archive = await db.get(Archive, archive_id)
    if not archive:
        raise HTTPException(404, "Archive not found")

    return _serialize_archive(archive)


@router.get("/archive/{archive_id}/download")
async def download_archive(
    archive_id: int,
    db: AsyncSession = Depends(get_db)
):
    """Get download URL for an archive."""
    archive = await db.get(Archive, archive_id)
    if not archive:
        raise HTTPException(404, "Archive not found")

    archive.download_count += 1
    archive.last_downloaded_at = datetime.utcnow()
    await db.commit()

    return {
        "archive_id": archive_id,
        "download_url": f"/api/archives/{archive_id}/file",
        "expires_at": archive.expires_at
    }


@router.get("/archives/{archive_id}/file")
async def get_archive_file(archive_id: int):
    """Serve an archive ZIP file (safe path resolution, range supported)."""
    async with AsyncSessionLocal() as db:
        archive = await db.get(Archive, archive_id)
        if not archive:
            raise HTTPException(404, "Archive not found")

        try:
            path = download_service.archive_generator.resolve_archive_path(archive.path)
        except ArchiveError:
            raise HTTPException(404, "Invalid archive path")

    if not path.is_file():
        raise HTTPException(404, "Archive file missing from filesystem")

    return FileResponse(
        path,
        media_type="application/zip",
        filename=archive.name,
        content_disposition_type="attachment",
    )


def _serialize_archive(archive: Archive) -> ArchiveResponse:
    return ArchiveResponse(
        id=archive.id,
        download_job_id=archive.download_job_id,
        archive_type=archive.archive_type,
        name=archive.name,
        path=archive.path,
        size_bytes=archive.size_bytes,
        file_count=archive.file_count,
        year_start=archive.year_start,
        year_end=archive.year_end,
        created_at=archive.created_at,
        expires_at=archive.expires_at,
        download_url=f"/api/archives/{archive.id}/file",
    )


# ============================================================================
# Search Routes
# ============================================================================

@router.post("/search", response_model=SearchResponse)
async def search(
    request: SearchRequest,
    db: AsyncSession = Depends(get_db)
):
    """Search across songs, albums, and artists."""
    results = []
    query_term = f"%{request.query}%"

    # Search songs
    if request.search_type in ("all", "song"):
        song_query = (
            select(Song, Album, Year)
            .select_from(Song)
            .join(Album, Song.album_id == Album.id)
            .join(Category, Album.category_id == Category.id)
            .join(Year, Category.year_id == Year.id)
        )

        if request.year:
            song_query = song_query.where(Year.year == request.year)

        song_query = song_query.where(
            or_(
                Song.title.ilike(query_term),
                Song.artist.ilike(query_term)
            )
        ).limit(request.limit)

        song_result = await db.execute(song_query)
        for song, album, year in song_result.all():
            results.append(SearchResult(
                type="song",
                id=song.id,
                title=song.title,
                subtitle=album.title,
                year=year.year,
                url=song.url if hasattr(song, 'url') else None,
                status=song.status.value,
                relevance_score=1.0
            ))

    # Search albums
    if request.search_type in ("all", "album"):
        album_query = (
            select(Album, Year)
            .select_from(Album)
            .join(Category, Album.category_id == Category.id)
            .join(Year, Category.year_id == Year.id)
        )

        if request.year:
            album_query = album_query.where(Year.year == request.year)

        album_query = album_query.where(
            or_(
                Album.title.ilike(query_term),
                Album.artist.ilike(query_term),
                Album.music_director.ilike(query_term)
            )
        ).limit(request.limit)

        album_result = await db.execute(album_query)
        for album, year in album_result.all():
            results.append(SearchResult(
                type="album",
                id=album.id,
                title=album.title,
                subtitle=album.artist,
                year=year.year,
                url=album.url,
                status=album.status.value,
                relevance_score=0.9
            ))

    return SearchResponse(
        query=request.query,
        total_results=len(results),
        results=results,
        limit=request.limit,
        offset=request.offset
    )


# ============================================================================
# Statistics Routes
# ============================================================================

@router.get("/statistics", response_model=DashboardStatistics)
async def get_statistics(db: AsyncSession = Depends(get_db)):
    """Get dashboard statistics."""
    # Overview counts
    crawl_jobs_count = await db.scalar(select(func.count(CrawlJob.id))) or 0
    years_count = await db.scalar(select(func.count(Year.id))) or 0
    albums_count = await db.scalar(select(func.count(Album.id))) or 0
    songs_count = await db.scalar(select(func.count(Song.id))) or 0
    resources_count = await db.scalar(select(func.count(AudioResource.id))) or 0
    downloaded_count = await db.scalar(
        select(func.count(AudioResource.id))
        .where(AudioResource.status == ResourceStatus.DOWNLOADED)
    ) or 0
    failed_count = await db.scalar(
        select(func.count(AudioResource.id))
        .where(AudioResource.status == ResourceStatus.FAILED)
    ) or 0
    pending_count = await db.scalar(
        select(func.count(AudioResource.id))
        .where(AudioResource.status.in_([
            ResourceStatus.DISCOVERED,
            ResourceStatus.AVAILABLE,
            ResourceStatus.ANALYZING,
        ]))
    ) or 0

    overview = StatisticsOverview(
        total_crawl_jobs=crawl_jobs_count,
        total_years=years_count,
        total_albums=albums_count,
        total_songs=songs_count,
        total_audio_resources=resources_count,
        total_downloaded=downloaded_count,
        total_pending=pending_count,
        total_failed=failed_count,
        storage_used_bytes=download_service.storage.storage_size()
    )

    # Per-year statistics (subqueries avoid join multiplication)
    year_album_counts = await db.execute(
        select(Year.year, func.count(func.distinct(Album.id)).label("albums"))
        .join(Category, Category.year_id == Year.id)
        .join(Album, Album.category_id == Category.id)
        .group_by(Year.year)
    )
    year_song_counts = await db.execute(
        select(Year.year, func.count(func.distinct(Song.id)).label("songs"))
        .join(Category, Category.year_id == Year.id)
        .join(Album, Album.category_id == Category.id)
        .join(Song, Song.album_id == Album.id)
        .group_by(Year.year)
    )
    year_resource_counts = await db.execute(
        select(Year.year, func.count(func.distinct(AudioResource.id)).label("resources"))
        .join(Category, Category.year_id == Year.id)
        .join(Album, Album.category_id == Category.id)
        .join(Song, Song.album_id == Album.id)
        .join(AudioResource, AudioResource.song_id == Song.id)
        .group_by(Year.year)
    )
    year_downloaded_counts = await db.execute(
        select(Year.year, func.count(func.distinct(AudioResource.id)).label("downloaded"))
        .join(Category, Category.year_id == Year.id)
        .join(Album, Album.category_id == Category.id)
        .join(Song, Song.album_id == Album.id)
        .join(AudioResource, AudioResource.song_id == Song.id)
        .where(AudioResource.status == ResourceStatus.DOWNLOADED)
        .group_by(Year.year)
    )
    year_failed_counts = await db.execute(
        select(Year.year, func.count(func.distinct(AudioResource.id)).label("failed"))
        .join(Category, Category.year_id == Year.id)
        .join(Album, Album.category_id == Category.id)
        .join(Song, Song.album_id == Album.id)
        .join(AudioResource, AudioResource.song_id == Song.id)
        .where(AudioResource.status == ResourceStatus.FAILED)
        .group_by(Year.year)
    )

    albums_map = {r.year: r.albums for r in year_album_counts.all()}
    songs_map = {r.year: r.songs for r in year_song_counts.all()}
    resources_map = {r.year: r.resources for r in year_resource_counts.all()}
    downloaded_map = {r.year: r.downloaded for r in year_downloaded_counts.all()}
    failed_map = {r.year: r.failed for r in year_failed_counts.all()}

    all_years = sorted(
        set(albums_map) | set(songs_map) | set(resources_map)
        | set(downloaded_map) | set(failed_map), reverse=True
    )
    year_stats = [
        YearStatistics(
            year=y,
            albums_count=albums_map.get(y, 0),
            songs_count=songs_map.get(y, 0),
            resources_count=resources_map.get(y, 0),
            downloaded_count=downloaded_map.get(y, 0),
            failed_count=failed_map.get(y, 0),
        )
        for y in all_years
    ]

    # Recent jobs
    recent_jobs_result = await db.execute(
        select(CrawlJob).order_by(CrawlJob.created_at.desc()).limit(5)
    )
    recent_jobs = [
        {
            "id": job.id,
            "base_url": job.base_url,
            "status": job.status.value,
            "created_at": job.created_at.isoformat()
        }
        for job in recent_jobs_result.scalars().all()
    ]

    return DashboardStatistics(
        overview=overview,
        year_stats=year_stats,
        recent_jobs=recent_jobs
    )


# ============================================================================
# Failed URLs Routes
# ============================================================================

@router.get("/failed-urls", response_model=List[FailedUrlResponse])
async def list_failed_urls(
    job_id: Optional[int] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db)
):
    """List failed URLs."""
    query = select(FailedUrl)
    if job_id:
        query = query.where(FailedUrl.crawl_job_id == job_id)

    query = query.order_by(FailedUrl.created_at.desc()).limit(limit).offset(offset)
    result = await db.execute(query)
    failed_urls = result.scalars().all()

    return [FailedUrlResponse.model_validate(f) for f in failed_urls]


# ============================================================================
# WebSocket for real-time progress
# ============================================================================

@router.websocket("/ws/progress/{job_id}")
async def websocket_progress(
    websocket: WebSocket,
    job_id: int
):
    """WebSocket endpoint for real-time progress updates."""
    await websocket.accept()

    async def send_progress(data: dict):
        await websocket.send_json(data)

    # Register callback
    crawl_service.register_progress_callback(job_id, send_progress)
    download_service.register_progress_callback(job_id, send_progress)

    try:
        while True:
            # Keep connection alive and handle client messages
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except Exception:
        pass
    finally:
        # Unregister callback on disconnect
        if job_id in crawl_service.progress_callbacks:
            crawl_service.progress_callbacks[job_id].remove(send_progress)
