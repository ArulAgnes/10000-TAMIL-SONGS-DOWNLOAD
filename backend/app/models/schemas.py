"""Pydantic schemas for API requests and responses."""
from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from app.models.database import JobStatus, ResourceStatus, ArtistType, ArchiveStatus


# Crawler Configuration
class CrawlerConfig(BaseModel):
    max_concurrency: int = Field(default=5, ge=1, le=20)
    request_timeout: int = Field(default=30, ge=5, le=120)
    max_retries: int = Field(default=3, ge=0, le=10)
    request_delay_ms: int = Field(default=500, ge=0, le=5000)
    user_agent: str = Field(default="AudioCollectionAnalyzer/1.0")
    respect_robots_txt: bool = Field(default=True)
    follow_redirects: bool = Field(default=True)


# Analysis Requests
class AnalyzeRequest(BaseModel):
    base_url: str = Field(..., description="Base URL pattern with {year} placeholder")
    start_year: int = Field(..., ge=1900, le=2100)
    end_year: int = Field(..., ge=1900, le=2100)
    config: Optional[CrawlerConfig] = Field(default=None)
    
    class Config:
        json_schema_extra = {
            "example": {
                "base_url": "https://example.com/category/latest-tamil-songs/{year}",
                "start_year": 1990,
                "end_year": 2026,
                "config": {
                    "max_concurrency": 5,
                    "request_timeout": 30,
                    "max_retries": 3,
                    "request_delay_ms": 500
                }
            }
        }


class AnalyzeResponse(BaseModel):
    job_id: int
    status: JobStatus
    message: str
    base_url: str
    start_year: int
    end_year: int
    created_at: datetime


# Progress/Status
class CrawlProgress(BaseModel):
    job_id: int
    status: JobStatus
    
    # Overall progress
    total_years: int
    processed_years: int
    total_pages: int
    processed_pages: int
    total_albums: int
    processed_albums: int
    total_songs: int
    processed_songs: int
    
    # Percentages
    year_progress: float
    page_progress: float
    album_progress: float
    song_progress: float
    overall_progress: float
    
    # Current activity
    current_year: Optional[int] = None
    current_page: Optional[int] = None
    current_album: Optional[str] = None
    current_song: Optional[str] = None
    current_activity: Optional[str] = None
    
    # Timing
    started_at: Optional[datetime] = None
    estimated_completion: Optional[datetime] = None
    elapsed_seconds: Optional[int] = None


# Year Schemas
class YearBase(BaseModel):
    year: int
    url: str
    status: JobStatus
    total_pages: int
    total_albums: int
    total_songs: int


class YearResponse(YearBase):
    id: int
    crawl_job_id: int
    created_at: datetime
    completed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class YearDetailResponse(YearResponse):
    categories: List["CategoryResponse"] = []


# Category Schemas
class CategoryBase(BaseModel):
    name: str
    url: str
    page_number: int
    status: JobStatus


class CategoryResponse(CategoryBase):
    id: int
    year_id: int
    discovered_at: datetime
    
    class Config:
        from_attributes = True


class CategoryDetailResponse(CategoryResponse):
    albums: List["AlbumResponse"] = []


# Album Schemas
class AlbumBase(BaseModel):
    title: str
    url: str
    release_year: Optional[int]
    artist: Optional[str]
    music_director: Optional[str]
    genre: Optional[str]
    description: Optional[str]
    cover_image_url: Optional[str]
    zip_url: Optional[str]
    zip_status: ResourceStatus
    status: JobStatus


class AlbumResponse(AlbumBase):
    id: int
    category_id: int
    analyzed_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class AlbumDetailResponse(AlbumResponse):
    songs: List["SongResponse"] = []


# Song Schemas
class SongBase(BaseModel):
    title: str
    track_number: Optional[int]
    duration: Optional[str]
    duration_seconds: Optional[int] = None
    artist: Optional[str]
    lyrics: Optional[str]
    status: JobStatus


class SongResponse(SongBase):
    id: int
    album_id: int
    
    class Config:
        from_attributes = True


class SongDetailResponse(SongResponse):
    audio_resources: List["AudioResourceResponse"] = []


# Audio Resource Schemas
class AudioResourceBase(BaseModel):
    url: str
    format: Optional[str]
    bitrate: Optional[str]
    file_size: Optional[int]
    content_type: Optional[str]
    status: ResourceStatus


class AudioResourceResponse(AudioResourceBase):
    id: int
    song_id: int
    local_path: Optional[str]
    filename: Optional[str]
    extension: Optional[str]
    downloaded_at: Optional[datetime]
    download_attempts: int
    last_error: Optional[str]
    
    class Config:
        from_attributes = True


# Download Requests
class DownloadRequest(BaseModel):
    resource_type: str = Field(..., pattern="^(song|album|year|years)$")
    resource_id: Optional[int] = None
    year_ids: Optional[List[int]] = None
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    include_zip: bool = Field(default=True, description="Include official ZIP if available")
    organize_by_year: bool = Field(default=True)
    organize_by_album: bool = Field(default=True)


class SongDownloadRequest(BaseModel):
    song_id: int


class AlbumDownloadRequest(BaseModel):
    album_id: int


class YearDownloadRequest(BaseModel):
    year_id: int


class YearsDownloadRequest(BaseModel):
    start_year: int
    end_year: int


class DownloadResponse(BaseModel):
    job_id: int
    status: JobStatus
    message: str
    estimated_files: int
    created_at: datetime
    # Populated for completed single-file downloads
    year: Optional[int] = None
    album: Optional[str] = None
    song: Optional[str] = None
    filename: Optional[str] = None
    local_path: Optional[str] = None
    file_size: Optional[int] = None


class DownloadProgress(BaseModel):
    job_id: int
    status: JobStatus
    total_files: int
    downloaded_files: int
    failed_files: int
    total_size_bytes: int
    downloaded_size_bytes: int
    progress_percentage: float
    current_file: Optional[str]
    speed_mbps: Optional[float]
    eta_seconds: Optional[int]


# Archive Schemas
class ArchiveResponse(BaseModel):
    id: int
    download_job_id: Optional[int]
    crawl_job_id: Optional[int] = None
    archive_type: Optional[str]
    name: str
    path: str
    size_bytes: int
    file_count: int
    year_start: Optional[int]
    year_end: Optional[int]
    status: Optional[str] = None
    error_message: Optional[str] = None
    completed_at: Optional[datetime] = None
    created_at: datetime
    expires_at: Optional[datetime]
    download_url: Optional[str]
    
    class Config:
        from_attributes = True


class YearArchiveRequest(BaseModel):
    year_id: int


class AlbumArchiveRequest(BaseModel):
    album_id: int


class YearsArchiveRequest(BaseModel):
    start_year: int
    end_year: int


class CollectionArchiveRequest(BaseModel):
    prefix: str = Field(default="", max_length=80, description="Archive name prefix, e.g. Tamil_Songs_")
    start_year: Optional[int] = None
    end_year: Optional[int] = None


# ============================================================================
# Artist Schemas
# ============================================================================

class ArtistResponse(BaseModel):
    id: int
    name: str
    normalized_name: str
    slug: str
    artist_type: Optional[str] = None
    source_url: Optional[str] = None
    song_count: int
    first_seen: Optional[datetime] = None
    last_seen: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ArtistListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    artists: List[ArtistResponse]


class ArtistSongResponse(BaseModel):
    id: int
    title: str
    album: Optional[str] = None
    album_id: Optional[int] = None
    year: Optional[int] = None
    duration: Optional[str] = None
    duration_seconds: Optional[int] = None
    artist: Optional[str] = None
    track_number: Optional[int] = None
    status: Optional[str] = None
    resource_count: int = 0
    source_url: Optional[str] = None

    class Config:
        from_attributes = True


class ArtistSongsResponse(BaseModel):
    artist: ArtistResponse
    total: int
    limit: int
    offset: int
    songs: List[ArtistSongResponse]


class ArtistAnalyzeRequest(BaseModel):
    artist_id: int
    artist_url: Optional[str] = Field(
        default=None,
        description="Optional artist source URL to analyze (updates the artist record)",
    )


class ArtistDiscoverRequest(BaseModel):
    index_url: str = Field(..., description="Artist index page URL (e.g. https://site.com/artists)")
    artist_type: Optional[ArtistType] = ArtistType.ARTIST
    max_artists: int = Field(default=2000, ge=1, le=50000)


# ============================================================================
# Multi-year Collection Schemas
# ============================================================================

class CollectionCreateRequest(BaseModel):
    base_url: str = Field(..., description="Base URL pattern with {year} placeholder")
    start_year: int = Field(..., ge=1900, le=2100)
    end_year: int = Field(..., ge=1900, le=2100)
    archive_prefix: Optional[str] = Field(default="", max_length=80)
    config: Optional[CrawlerConfig] = Field(default=None)


class CollectionResponse(BaseModel):
    job_id: int
    status: str
    years: List[int]
    start_year: int
    end_year: int
    base_url: str
    message: str
    created_at: datetime


class CollectionProgress(BaseModel):
    job_id: int
    status: str
    total_years: int
    completed_years: int
    total_albums: int
    total_songs: int
    total_resources: int
    failed_urls: int
    skipped_urls: int
    current_year: Optional[int]
    current_album: Optional[str]
    current_song: Optional[str]
    progress_percentage: float
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    elapsed_seconds: Optional[int]
    estimated_remaining_seconds: Optional[int]
    error_message: Optional[str]


# Search Schemas
class SearchRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=200)
    search_type: Optional[str] = Field(default="all", pattern="^(all|song|album|artist|year)$")
    year: Optional[int] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class SearchResult(BaseModel):
    type: str
    id: int
    title: str
    subtitle: Optional[str]
    year: Optional[int]
    url: Optional[str]
    status: Optional[str]
    relevance_score: float


class SearchResponse(BaseModel):
    query: str
    total_results: int
    results: List[SearchResult]
    limit: int
    offset: int


# Statistics Schemas
class StatisticsOverview(BaseModel):
    total_crawl_jobs: int
    total_years: int
    total_albums: int
    total_songs: int
    total_audio_resources: int
    total_downloaded: int
    total_pending: int
    total_failed: int
    storage_used_bytes: int


class YearStatistics(BaseModel):
    year: int
    albums_count: int
    songs_count: int
    resources_count: int
    downloaded_count: int
    failed_count: int


class DashboardStatistics(BaseModel):
    overview: StatisticsOverview
    year_stats: List[YearStatistics]
    recent_jobs: List[Dict[str, Any]]


# Error Log Schemas
class FailedUrlResponse(BaseModel):
    id: int
    url: str
    url_type: str
    error_code: Optional[int]
    error_message: Optional[str]
    retry_count: int
    max_retries_reached: bool
    created_at: datetime
    last_attempt: datetime
    
    class Config:
        from_attributes = True


# WebSocket Messages
class WebSocketMessage(BaseModel):
    type: str
    job_id: Optional[int]
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# Update forward references
YearDetailResponse.model_rebuild()
CategoryDetailResponse.model_rebuild()
AlbumDetailResponse.model_rebuild()
SongDetailResponse.model_rebuild()
