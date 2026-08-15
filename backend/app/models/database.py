"""SQLAlchemy database models for audio collection analyzer."""
from datetime import datetime
from enum import Enum as PyEnum
from typing import Optional

from sqlalchemy import (
    String, DateTime, ForeignKey, Text,
    Boolean, Enum, JSON, UniqueConstraint, Index, BigInteger, Integer
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.config import Base


class JobStatus(str, PyEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ResourceStatus(str, PyEnum):
    DISCOVERED = "discovered"
    ANALYZING = "analyzing"
    AVAILABLE = "available"
    DOWNLOADING = "downloading"
    DOWNLOADED = "downloaded"
    FAILED = "failed"
    UNAUTHORIZED = "unauthorized"
    PROTECTED = "protected"


class CrawlJob(Base):
    __tablename__ = "crawl_jobs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    start_year: Mapped[int] = mapped_column(Integer, nullable=False)
    end_year: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Progress tracking
    total_years: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    processed_years: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    processed_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_albums: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    processed_albums: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_songs: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    processed_songs: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    
    # Configuration
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=True)
    
    # Relationships
    years: Mapped[list["Year"]] = relationship("Year", back_populates="crawl_job", cascade="all, delete-orphan")
    logs: Mapped[list["CrawlLog"]] = relationship("CrawlLog", back_populates="crawl_job", cascade="all, delete-orphan")


class Year(Base):
    __tablename__ = "years"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crawl_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("crawl_jobs.id"), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=True)
    
    # Statistics
    total_pages: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_albums: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_songs: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    crawl_job: Mapped["CrawlJob"] = relationship("CrawlJob", back_populates="years")
    categories: Mapped[list["Category"]] = relationship("Category", back_populates="year", cascade="all, delete-orphan")
    
    __table_args__ = (UniqueConstraint('crawl_job_id', 'year', name='unique_year_per_job'),)


class Category(Base):
    __tablename__ = "categories"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_id: Mapped[int] = mapped_column(Integer, ForeignKey("years.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False)
    page_number: Mapped[int] = mapped_column(Integer, default=1, nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=True)
    
    # Discovery info
    discovered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    
    # Relationships
    year: Mapped["Year"] = relationship("Year", back_populates="categories")
    albums: Mapped[list["Album"]] = relationship("Album", back_populates="category", cascade="all, delete-orphan")
    
    __table_args__ = (UniqueConstraint('year_id', 'url', name='unique_category_url'),)


class Album(Base):
    __tablename__ = "albums"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(Integer, ForeignKey("categories.id"), nullable=False)
    
    # Album metadata
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    release_year: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    artist: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    music_director: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    genre: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Download info
    zip_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    zip_status: Mapped[ResourceStatus] = mapped_column(Enum(ResourceStatus), default=ResourceStatus.DISCOVERED, nullable=True)
    
    # Status
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=True)
    analyzed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Deduplication
    canonical_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    # Relationships
    category: Mapped["Category"] = relationship("Category", back_populates="albums")
    songs: Mapped[list["Song"]] = relationship("Song", back_populates="album", cascade="all, delete-orphan")
    
    __table_args__ = (UniqueConstraint('url', name='unique_album_url'),)


class Song(Base):
    __tablename__ = "songs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    album_id: Mapped[int] = mapped_column(Integer, ForeignKey("albums.id"), nullable=False)
    
    # Song metadata
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    track_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    artist: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    lyrics: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Status
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=True)
    
    # Relationships
    album: Mapped["Album"] = relationship("Album", back_populates="songs")
    audio_resources: Mapped[list["AudioResource"]] = relationship("AudioResource", back_populates="song", cascade="all, delete-orphan")


class AudioResource(Base):
    __tablename__ = "audio_resources"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    song_id: Mapped[int] = mapped_column(Integer, ForeignKey("songs.id"), nullable=False)
    
    # Resource info
    url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    format: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # mp3, flac, etc.
    bitrate: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # 320kbps, etc.
    file_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Status
    status: Mapped[ResourceStatus] = mapped_column(Enum(ResourceStatus), default=ResourceStatus.DISCOVERED, nullable=True)
    
    # Download tracking (filesystem storage — audio is never stored in SQL)
    local_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)      # relative: 1998/Album/01 - Song.mp3
    filename: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)        # final file name on disk
    extension: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)        # mp3, flac, ...
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    download_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Deduplication
    canonical_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, index=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    
    # Relationships
    song: Mapped["Song"] = relationship("Song", back_populates="audio_resources")
    
    __table_args__ = (UniqueConstraint('song_id', 'url', name='unique_resource_per_song'),)


class DownloadJob(Base):
    __tablename__ = "download_jobs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False)  # song, album, year, years
    
    # Targets
    year_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("years.id"), nullable=True)
    album_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("albums.id"), nullable=True)
    song_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("songs.id"), nullable=True)
    target_years: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)  # For multi-year downloads
    
    # Status
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.PENDING, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Progress
    total_files: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    downloaded_files: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    failed_files: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    total_size_bytes: Mapped[int] = mapped_column(BigInteger, default=0, nullable=True)
    
    # Archive info
    archive_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    archive_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    archive_size: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    
    # Error tracking
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Archive(Base):
    __tablename__ = "archives"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    download_job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("download_jobs.id"), nullable=True)
    archive_type: Mapped[str] = mapped_column(String(20), default="year", nullable=True)  # year, album, years, download
    
    # Archive metadata
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    path: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Content info
    year_start: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    year_end: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    album_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Access tracking
    download_count: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    last_downloaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class CrawlLog(Base):
    __tablename__ = "crawl_logs"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    crawl_job_id: Mapped[int] = mapped_column(Integer, ForeignKey("crawl_jobs.id"), nullable=False)
    
    # Log entry
    level: Mapped[str] = mapped_column(String(20), default="info", nullable=True)  # debug, info, warning, error
    message: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    error_details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    
    # Relationships
    crawl_job: Mapped["CrawlJob"] = relationship("CrawlJob", back_populates="logs")


class FailedUrl(Base):
    __tablename__ = "failed_urls"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    url: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    url_type: Mapped[str] = mapped_column(String(50), nullable=False)  # category, album, song, resource
    
    # Failure info
    error_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=True)
    max_retries_reached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=True)
    
    # Context
    crawl_job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("crawl_jobs.id"), nullable=True)
    parent_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    last_attempt: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=True)
    
    __table_args__ = (Index('idx_failed_url_job', 'crawl_job_id', 'url'),)