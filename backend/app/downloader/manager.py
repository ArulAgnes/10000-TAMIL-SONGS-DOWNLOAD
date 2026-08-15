"""Download manager for authorized audio resources.

The downloader streams HTTP audio resources directly to the filesystem through
``AudioStorage`` (never through SQL):

    HTTP audio resource
            ↓
        Downloader
            ↓
        AudioStorage
            ↓
    audio_collection/<year>/<album>/<song>.mp3

Safety rules enforced here:
- only URLs that were discovered by the crawler and marked available are
  downloaded (no arbitrary URL fetching)
- content-type validation (HTML/text responses are rejected)
- audio extension validation
- response size validation (partial/truncated files fail)
- retries with exponential backoff on transient errors
- per-domain-style rate limiting and bounded concurrency
- graceful cancellation with cleanup of incomplete ``.part`` files
"""
import asyncio
import os
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Callable
from urllib.parse import urlparse, unquote

import httpx
import aiofiles
import structlog

from app.storage.audio_storage import AudioStorage, AudioStorageError, ALLOWED_EXTENSIONS

logger = structlog.get_logger()

USER_AGENT = os.getenv("USER_AGENT", "AudioCollectionAnalyzer/1.0")

BLOCKED_CONTENT_TYPES = {
    "text/html", "text/plain", "text/xml", "text/csv",
    "application/json", "application/xml", "application/pdf",
    "application/x-httpd-php", "application/javascript",
}

ZIP_CONTENT_TYPES = {
    "application/zip", "application/x-zip-compressed",
    "application/x-compressed", "application/x-zip",
}


class DownloadError(Exception):
    """Base download failure."""


class DownloadCancelled(DownloadError):
    """Download was cancelled by the user."""


class DownloadHttpError(DownloadError):
    """Non-200 HTTP response."""


class DownloadContentTypeError(DownloadError):
    """Response is not audio content."""


class DownloadSizeError(DownloadError):
    """Downloaded size does not match expectations."""


def _is_retryable_status(status: int) -> bool:
    return status in (408, 425, 429) or status >= 500


class DownloadManager:
    """Manager for downloading authorized audio resources to the filesystem."""

    def __init__(
        self,
        storage: Optional[AudioStorage] = None,
        max_concurrent_downloads: Optional[int] = None,
        request_timeout: Optional[float] = None,
        max_retries: Optional[int] = None,
        request_delay_ms: Optional[int] = None,
        archive_dir: Optional[str] = None,
    ):
        self.storage = storage or AudioStorage()
        self.archive_dir = Path(
            archive_dir or os.getenv("ARCHIVE_DIR", "./archives")
        ).resolve()
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.max_concurrent_downloads = int(
            max_concurrent_downloads if max_concurrent_downloads is not None
            else os.getenv("MAX_CONCURRENCY", "5")
        )
        self.request_timeout = float(
            request_timeout if request_timeout is not None
            else os.getenv("REQUEST_TIMEOUT", "30")
        )
        self.max_retries = int(
            max_retries if max_retries is not None
            else os.getenv("MAX_RETRIES", "3")
        )
        self.request_delay_ms = int(
            request_delay_ms if request_delay_ms is not None
            else os.getenv("REQUEST_DELAY_MS", "500")
        )

        self._semaphore = asyncio.Semaphore(self.max_concurrent_downloads)
        self._stop_requested = False
        self._rate_lock = asyncio.Lock()
        self._last_request_at = 0.0

        self.progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.request_timeout, connect=10.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            headers={"User-Agent": USER_AGENT},
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_progress_callback(self, callback: Callable[[Dict[str, Any]], None]):
        """Set a callback invoked with progress events."""
        self.progress_callback = callback

    def request_stop(self):
        """Request a graceful stop of all downloads."""
        self._stop_requested = True

    async def close(self):
        """Close the underlying HTTP client."""
        await self._client.aclose()

    def _emit_progress(self, data: Dict[str, Any]):
        if self.progress_callback:
            try:
                self.progress_callback(data)
            except Exception as e:
                logger.error("Progress callback error", error=str(e))

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    async def _rate_limit(self):
        async with self._rate_lock:
            now = time.monotonic()
            elapsed = now - self._last_request_at
            wait = (self.request_delay_ms / 1000.0) - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request_at = time.monotonic()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _extension_from_url(url: str) -> Optional[str]:
        path = unquote(urlparse(url).path)
        ext = Path(path).suffix.lower().lstrip(".")
        return ext if ext in ALLOWED_EXTENSIONS else None

    @staticmethod
    def _validate_content_type(content_type: str, extension: Optional[str]) -> bool:
        """Reject obviously non-audio responses."""
        ct = (content_type or "").lower().split(";")[0].strip()
        if not ct:
            # No content-type header: fall back to extension check
            return extension in ALLOWED_EXTENSIONS
        if ct in BLOCKED_CONTENT_TYPES or ct.startswith("text/") or ct.startswith("image/"):
            return False
        if ct.startswith("audio/"):
            return True
        if ct in ("application/octet-stream", "application/force-download",
                  "application/mp3", "application/x-mp3", "application/ogg"):
            return True
        if ct in ("video/mpeg", "video/mp4") and extension in ("mp3", "m4a", "aac"):
            return True
        return False

    @staticmethod
    def _validate_zip_content_type(content_type: str) -> bool:
        """Reject responses that are clearly not an archive (e.g. HTML pages)."""
        ct = (content_type or "").lower().split(";")[0].strip()
        if not ct:
            return True  # trust the URL/discovery
        if ct in BLOCKED_CONTENT_TYPES or ct.startswith("text/") or ct.startswith("image/"):
            return False
        if ct in ZIP_CONTENT_TYPES:
            return True
        if ct in ("application/octet-stream", "application/force-download"):
            return True
        return False

    @staticmethod
    def _detect_extension(url: str, declared: Optional[str]) -> str:
        ext = DownloadManager._extension_from_url(url)
        if ext:
            return ext
        if declared:
            return AudioStorage.sanitize_extension(declared)
        return "mp3"

    # ------------------------------------------------------------------
    # Single file download
    # ------------------------------------------------------------------

    async def _download_one(
        self,
        resource: Dict[str, Any],
        job_id: int,
        index: int,
        total: int,
    ) -> Dict[str, Any]:
        """Download a single resource with retries, validation and cleanup."""
        url = resource["url"]
        resource_id = resource.get("id")
        year = resource.get("year")
        album = resource.get("album")
        song = resource.get("song")
        artist = resource.get("artist")
        track_number = resource.get("track_number")
        expected_size = resource.get("expected_size")

        result = {
            "resource_id": resource_id,
            "url": url,
            "success": False,
            "bytes_downloaded": 0,
            "local_path": None,
            "filename": None,
            "extension": None,
            "size": 0,
            "error": None,
            "cancelled": False,
            "year": year,
            "album": album,
            "song": song,
            "artist": artist,
        }

        # Already downloaded to the filesystem? Skip re-download.
        existing = resource.get("local_path")
        if existing and self.storage.audio_exists(existing):
            size = self.storage.audio_size(existing)
            result.update({
                "success": True,
                "local_path": existing,
                "filename": Path(existing).name,
                "extension": AudioStorage.sanitize_extension(Path(existing).suffix),
                "size": size,
                "bytes_downloaded": 0,
            })
            self._emit_progress({
                "type": "download_complete",
                "job_id": job_id,
                "resource_id": resource_id,
                "current": index + 1,
                "total": total,
                "url": url,
                "local_path": existing,
                "filename": Path(existing).name,
                "size": size,
                "song": song, "album": album, "year": year,
                "skipped": True,
            })
            return result

        extension = self._detect_extension(url, resource.get("format"))
        if track_number:
            track = f"{int(track_number):02d} - {song}" if song else f"{int(track_number):02d} - track"
        else:
            track = song or "track"

        rel_path = self.storage.build_relative_path(year, album, track, extension)

        self._emit_progress({
            "type": "download_start",
            "job_id": job_id,
            "resource_id": resource_id,
            "current": index + 1,
            "total": total,
            "url": url,
            "filename": f"{Path(rel_path).name}",
            "song": song, "album": album, "year": year, "artist": artist,
        })

        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            if self._stop_requested:
                result.update({"error": "Download stopped by user", "cancelled": True})
                break

            try:
                await self._download_attempt(
                    result, url, rel_path, expected_size, job_id, resource_id,
                    song=song, album=album, year=year,
                )
                break
            except DownloadCancelled:
                result.update({"error": "Download stopped by user", "cancelled": True})
                break
            except DownloadContentTypeError as e:
                last_error = str(e)
                break  # not retryable
            except DownloadSizeError as e:
                last_error = str(e)
                break  # not retryable
            except DownloadHttpError as e:
                last_error = str(e)
                if not _is_retryable_status(getattr(e, "status", 0)):
                    break
            except (httpx.HTTPError, AudioStorageError, OSError, asyncio.TimeoutError) as e:
                last_error = str(e)

            if attempt < self.max_retries:
                backoff = (2 ** attempt) + 0.5
                self._emit_progress({
                    "type": "download_retry",
                    "job_id": job_id,
                    "resource_id": resource_id,
                    "current": index + 1,
                    "total": total,
                    "url": url,
                    "attempt": attempt + 1,
                    "error": last_error,
                    "song": song, "album": album, "year": year,
                })
                await asyncio.sleep(backoff)

        if not result["success"]:
            result["error"] = result["error"] or last_error or "Unknown download error"
            self._emit_progress({
                "type": "download_failed",
                "job_id": job_id,
                "resource_id": resource_id,
                "current": index + 1,
                "total": total,
                "url": url,
                "filename": f"{Path(rel_path).name}",
                "error": result["error"],
                "song": song, "album": album, "year": year,
            })

        return result

    async def _download_attempt(
        self,
        result: Dict[str, Any],
        url: str,
        rel_path: str,
        expected_size: Optional[int],
        job_id: int,
        resource_id: Optional[int],
        song: Optional[str],
        album: Optional[str],
        year: Optional[int],
    ):
        """One streaming download attempt (streams to ``.part``, then renames)."""
        async with self._semaphore:
            await self._rate_limit()
            if self._stop_requested:
                raise DownloadCancelled("Download stopped by user")

            async with self._client.stream("GET", url) as response:
                if response.status_code != 200:
                    err = DownloadHttpError(f"HTTP {response.status_code}")
                    err.status = response.status_code  # type: ignore[attr-defined]
                    raise err

                content_type = response.headers.get("content-type", "")
                extension = self._detect_extension(str(response.url), result.get("extension"))
                if not self._validate_content_type(content_type, extension):
                    raise DownloadContentTypeError(
                        f"Rejected non-audio response (content-type: {content_type or 'unknown'})"
                    )

                content_length = int(response.headers.get("content-length", 0) or 0)
                if expected_size and content_length and expected_size != content_length:
                    logger.warning(
                        "Content-length differs from discovered size",
                        url=url, expected=expected_size, actual=content_length,
                    )

                total = content_length or expected_size or 0
                downloaded = {"bytes": 0}

                def on_progress(byte_count: int):
                    downloaded["bytes"] = byte_count
                    if total and byte_count % (256 * 1024) < 64 * 1024:
                        self._emit_progress({
                            "type": "download_progress",
                            "job_id": job_id,
                            "resource_id": resource_id,
                            "url": url,
                            "downloaded": byte_count,
                            "total": total,
                            "percentage": (byte_count / total * 100) if total else 0,
                            "filename": f"{Path(rel_path).name}",
                            "song": song, "album": album, "year": year,
                        })

                stop_event = type(
                    "StopFlag", (), {
                        "is_set": lambda _: self._stop_requested,
                    }
                )()

                try:
                    saved = await self.storage.save_audio(
                        chunk_iterator=response.aiter_bytes(chunk_size=128 * 1024),
                        relative_path=rel_path,
                        expected_size=content_length or None,
                        progress_callback=on_progress,
                        stop_event=stop_event,
                    )
                except AudioStorageError as e:
                    if self._stop_requested:
                        raise DownloadCancelled(str(e))
                    raise DownloadSizeError(str(e))

                result.update({
                    "success": True,
                    "bytes_downloaded": downloaded["bytes"],
                    "local_path": saved["relative_path"],
                    "filename": saved["filename"],
                    "extension": AudioStorage.sanitize_extension(Path(saved["filename"]).suffix),
                    "size": saved["size"],
                    "error": None,
                })

                self._emit_progress({
                    "type": "download_complete",
                    "job_id": job_id,
                    "resource_id": resource_id,
                    "current": None,
                    "total": None,
                    "url": url,
                    "local_path": saved["relative_path"],
                    "filename": saved["filename"],
                    "size": saved["size"],
                    "song": song, "album": album, "year": year,
                })

    # ------------------------------------------------------------------
    # Batch downloads
    # ------------------------------------------------------------------

    async def download_resources(
        self,
        resources: List[Dict[str, Any]],
        job_id: int,
    ) -> Dict[str, Any]:
        """Download multiple resources with bounded concurrency."""
        results = {
            "total": len(resources),
            "successful": 0,
            "failed": 0,
            "cancelled": 0,
            "total_bytes": 0,
            "downloads": [],
        }

        if not resources:
            return results

        semaphore = asyncio.Semaphore(self.max_concurrent_downloads)

        async def guarded(resource: Dict[str, Any], index: int) -> Dict[str, Any]:
            async with semaphore:
                return await self._download_one(resource, job_id, index, len(resources))

        tasks = [guarded(r, i) for i, r in enumerate(resources)]
        completed = await asyncio.gather(*tasks)

        for r in completed:
            results["downloads"].append(r)
            if r.get("success"):
                results["successful"] += 1
                results["total_bytes"] += r.get("size", 0)
            else:
                results["failed"] += 1
                if r.get("cancelled"):
                    results["cancelled"] += 1

            self._emit_progress({
                "type": "batch_progress",
                "job_id": job_id,
                "current": len(results["downloads"]),
                "total": len(resources),
                "successful": results["successful"],
                "failed": results["failed"],
                "total_bytes": results["total_bytes"],
            })

        return results

    # ------------------------------------------------------------------
    # Album ZIP downloads
    # ------------------------------------------------------------------

    @staticmethod
    def archive_relative_path(
        year: Optional[int],
        album_id: int,
        album_name: Optional[str],
    ) -> str:
        """Relative path of an album ZIP inside the archive directory."""
        safe_year = AudioStorage.sanitize_segment(str(year), "Unknown Year")
        safe_name = AudioStorage.sanitize_segment(album_name, "album")
        return f"{safe_year}/{album_id}-{safe_name}.zip"

    def resolve_archive_relative(self, relative_path: str) -> Path:
        """Resolve a relative archive path, guarding against path traversal."""
        target = (self.archive_dir / relative_path).resolve()
        try:
            target.relative_to(self.archive_dir)
        except ValueError:
            raise DownloadError(f"Archive path escapes archive dir: {relative_path}")
        return target

    async def _download_zip_attempt(
        self,
        target: Dict[str, Any],
        rel_path: str,
        job_id: int,
        index: int,
        total: int,
    ) -> Dict[str, Any]:
        """One streaming download attempt for an album ZIP archive."""
        url = target["zip_url"]
        result = {
            "zip_url": url,
            "album_id": target.get("album_id"),
            "album_name": target.get("album_name"),
            "year": target.get("year"),
            "success": False,
            "relative_path": rel_path,
            "filename": None,
            "size": 0,
            "error": None,
            "skipped": False,
        }

        final_path = self.resolve_archive_relative(rel_path)
        if final_path.exists():
            result.update({
                "success": True,
                "filename": final_path.name,
                "size": final_path.stat().st_size,
                "skipped": True,
            })
            return result

        final_path.parent.mkdir(parents=True, exist_ok=True)
        part_path = final_path.with_suffix(final_path.suffix + ".part")

        self._emit_progress({
            "type": "zip_download_start",
            "job_id": job_id,
            "album_id": target.get("album_id"),
            "album_name": target.get("album_name"),
            "year": target.get("year"),
            "current": index + 1,
            "total": total,
            "url": url,
            "filename": final_path.name,
        })

        try:
            async with self._semaphore:
                await self._rate_limit()
                if self._stop_requested:
                    raise DownloadCancelled("Download stopped by user")

                async with self._client.stream("GET", url) as response:
                    if response.status_code != 200:
                        err = DownloadHttpError(f"HTTP {response.status_code}")
                        err.status = response.status_code  # type: ignore[attr-defined]
                        raise err

                    content_type = response.headers.get("content-type", "")
                    if not self._validate_zip_content_type(content_type):
                        raise DownloadContentTypeError(
                            f"Rejected non-archive response (content-type: {content_type or 'unknown'})"
                        )

                    content_length = int(response.headers.get("content-length", 0) or 0)
                    size = 0
                    async with aiofiles.open(part_path, "wb") as out:
                        async for chunk in response.aiter_bytes(chunk_size=128 * 1024):
                            if self._stop_requested:
                                raise DownloadCancelled("Download stopped by user")
                            await out.write(chunk)
                            size += len(chunk)
                            if content_length and size % (256 * 1024) < 64 * 1024:
                                self._emit_progress({
                                    "type": "zip_download_progress",
                                    "job_id": job_id,
                                    "album_id": target.get("album_id"),
                                    "album_name": target.get("album_name"),
                                    "year": target.get("year"),
                                    "url": url,
                                    "downloaded": size,
                                    "total": content_length,
                                    "percentage": (size / content_length * 100) if content_length else 0,
                                    "filename": final_path.name,
                                })

                    if content_length and size != content_length:
                        raise DownloadSizeError(
                            f"Size mismatch: expected {content_length}, got {size}"
                        )

                    part_path.replace(final_path)
                    result.update({
                        "success": True,
                        "filename": final_path.name,
                        "size": size,
                    })

                    self._emit_progress({
                        "type": "zip_download_complete",
                        "job_id": job_id,
                        "album_id": target.get("album_id"),
                        "album_name": target.get("album_name"),
                        "year": target.get("year"),
                        "current": index + 1,
                        "total": total,
                        "url": url,
                        "filename": final_path.name,
                        "size": size,
                    })

        except (DownloadCancelled, DownloadContentTypeError, DownloadSizeError) as e:
            result["error"] = str(e)
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise
        except (httpx.HTTPError, OSError, asyncio.TimeoutError) as e:
            result["error"] = str(e)
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise

        return result

    async def _download_zip_one(
        self,
        target: Dict[str, Any],
        job_id: int,
        index: int,
        total: int,
    ) -> Dict[str, Any]:
        """Download a single album ZIP with retries."""
        rel_path = self.archive_relative_path(
            target.get("year"),
            target["album_id"],
            target.get("album_name"),
        )
        if target.get("relative_path"):
            rel_path = target["relative_path"]

        result = {
            "zip_url": target["zip_url"],
            "album_id": target.get("album_id"),
            "album_name": target.get("album_name"),
            "year": target.get("year"),
            "success": False,
            "relative_path": rel_path,
            "filename": None,
            "size": 0,
            "error": None,
            "skipped": False,
        }

        last_error: Optional[str] = None
        for attempt in range(self.max_retries + 1):
            if self._stop_requested:
                result.update({"error": "Download stopped by user"})
                break
            try:
                return await self._download_zip_attempt(
                    target, rel_path, job_id, index, total
                )
            except DownloadCancelled:
                result.update({"error": "Download stopped by user"})
                break
            except (DownloadContentTypeError, DownloadSizeError) as e:
                last_error = str(e)
                break
            except DownloadHttpError as e:
                last_error = str(e)
                if not _is_retryable_status(getattr(e, "status", 0)):
                    break
            except (httpx.HTTPError, DownloadError, OSError, asyncio.TimeoutError) as e:
                last_error = str(e)

            if attempt < self.max_retries:
                backoff = (2 ** attempt) + 0.5
                self._emit_progress({
                    "type": "zip_download_retry",
                    "job_id": job_id,
                    "album_id": target.get("album_id"),
                    "album_name": target.get("album_name"),
                    "year": target.get("year"),
                    "url": target["zip_url"],
                    "attempt": attempt + 1,
                    "error": last_error,
                })
                await asyncio.sleep(backoff)

        result["error"] = result["error"] or last_error or "Unknown download error"
        self._emit_progress({
            "type": "zip_download_failed",
            "job_id": job_id,
            "album_id": target.get("album_id"),
            "album_name": target.get("album_name"),
            "year": target.get("year"),
            "current": index + 1,
            "total": total,
            "url": target["zip_url"],
            "filename": f"{Path(rel_path).name}",
            "error": result["error"],
        })
        return result

    async def download_zips(
        self,
        targets: List[Dict[str, Any]],
        job_id: int,
    ) -> Dict[str, Any]:
        """Download multiple album ZIPs with bounded concurrency."""
        results = {
            "total": len(targets),
            "successful": 0,
            "failed": 0,
            "total_bytes": 0,
            "downloads": [],
        }

        if not targets:
            return results

        semaphore = asyncio.Semaphore(self.max_concurrent_downloads)

        async def guarded(target: Dict[str, Any], index: int) -> Dict[str, Any]:
            async with semaphore:
                return await self._download_zip_one(target, job_id, index, len(targets))

        tasks = [guarded(t, i) for i, t in enumerate(targets)]
        completed = await asyncio.gather(*tasks)

        for r in completed:
            results["downloads"].append(r)
            if r.get("success"):
                results["successful"] += 1
                results["total_bytes"] += r.get("size", 0)
            else:
                results["failed"] += 1

            self._emit_progress({
                "type": "zip_batch_progress",
                "job_id": job_id,
                "current": len(results["downloads"]),
                "total": len(targets),
                "successful": results["successful"],
                "failed": results["failed"],
            })

        return results

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup_temp_files(self, max_age_hours: int = 24):
        """Clean up stale ``.part`` files."""
        self.storage.cleanup_parts(max_age_seconds=max_age_hours * 3600)

    def get_download_path(self, year: Optional[int] = None, album: Optional[str] = None) -> Path:
        """Return the storage root subdirectory for a year/album."""
        path = self.storage.root
        if year is not None:
            path = path / str(year)
        if album is not None:
            path = path / AudioStorage.sanitize_segment(album, "Unknown Album")
        path.mkdir(parents=True, exist_ok=True)
        return path
