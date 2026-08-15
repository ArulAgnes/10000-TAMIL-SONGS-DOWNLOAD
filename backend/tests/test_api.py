"""End-to-end API tests: crawl metadata, download, filesystem storage,
audio serving, archives and statistics."""
import asyncio
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from app.database.config import init_db, AsyncSessionLocal
from app.models.database import (
    CrawlJob, Year, Category, Album, Song, AudioResource,
    JobStatus, ResourceStatus,
)
from tests.conftest import server, AUDIO_PAYLOAD


@pytest.fixture(autouse=True)
async def seeded_db():
    """Create tables and seed one year/album/song/resource (per test)."""
    await init_db()

    # Wipe any data left by previous tests (children first)
    async with AsyncSessionLocal() as cleanup:
        for model in (AudioResource, Song, Album, Category, Year, CrawlJob):
            await cleanup.execute(model.__table__.delete())
        await cleanup.commit()

    async with AsyncSessionLocal() as db:
        job = CrawlJob(
            base_url="http://fixture.local/category/{year}",
            start_year=1998, end_year=1998,
            status=JobStatus.COMPLETED,
            total_years=1, processed_years=1,
        )
        db.add(job)
        await db.flush()

        year = Year(crawl_job_id=job.id, year=1998, url="http://fixture.local/category/1998",
                    status=JobStatus.COMPLETED)
        db.add(year)
        await db.flush()

        category = Category(year_id=year.id, name="Songs", url="http://fixture.local/category/1998",
                            status=JobStatus.COMPLETED)
        db.add(category)
        await db.flush()

        album = Album(category_id=category.id, title="Test Album", url="http://fixture.local/album/1",
                      release_year=1998, status=JobStatus.COMPLETED)
        db.add(album)
        await db.flush()

        song = Song(album_id=album.id, title="Test Song", track_number=1,
                    artist="Test Artist", status=JobStatus.COMPLETED)
        db.add(song)
        await db.flush()

        resource = AudioResource(
            song_id=song.id, url=f"{server.base_url}/test.mp3", format="mp3",
            status=ResourceStatus.AVAILABLE,
        )
        db.add(resource)
        await db.commit()

        yield {
            "job_id": job.id, "year_id": year.id, "category_id": category.id,
            "album_id": album.id, "song_id": song.id, "resource_id": resource.id,
        }


@pytest.fixture
async def client():
    from app.main import create_app
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


class TestHealthAndStats:
    async def test_health(self, client):
        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    async def test_statistics_before_download(self, client):
        res = await client.get("/api/statistics")
        assert res.status_code == 200
        data = res.json()
        assert data["overview"]["total_years"] == 1
        assert data["overview"]["total_albums"] == 1
        assert data["overview"]["total_songs"] == 1
        assert data["overview"]["total_pending"] == 1
        assert data["overview"]["total_downloaded"] == 0
        assert data["overview"]["storage_used_bytes"] == 0


class TestDownloadAndStorage:
    async def test_download_song_to_filesystem(self, client, seeded_db):
        res = await client.post("/api/download/song", json={"song_id": seeded_db["song_id"]})
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "completed"
        assert data["year"] == 1998
        assert data["album"] == "Test Album"
        assert data["song"] == "Test Song"
        assert data["filename"] == "01 - Test Song.mp3"
        assert data["local_path"] == "1998/Test Album/01 - Test Song.mp3"
        assert data["file_size"] == len(AUDIO_PAYLOAD)

    async def test_audio_served_from_disk(self, client, seeded_db):
        await client.post("/api/download/song", json={"song_id": seeded_db["song_id"]})

        res = await client.get(f"/api/audio/{seeded_db['song_id']}")
        assert res.status_code == 200
        assert res.headers["content-type"].startswith("audio/mpeg")
        assert res.content == AUDIO_PAYLOAD

    async def test_audio_range_request(self, client, seeded_db):
        await client.post("/api/download/song", json={"song_id": seeded_db["song_id"]})

        res = await client.get(
            f"/api/audio/{seeded_db['song_id']}",
            headers={"Range": "bytes=0-99"},
        )
        assert res.status_code == 206
        assert len(res.content) == 100
        assert res.headers["content-range"] == f"bytes 0-99/{len(AUDIO_PAYLOAD)}"

    async def test_audio_404_when_not_downloaded(self, client, seeded_db):
        res = await client.get(f"/api/audio/{seeded_db['song_id']}")
        assert res.status_code == 404

    async def test_audio_404_unknown_song(self, client):
        res = await client.get("/api/audio/999999")
        assert res.status_code == 404

    async def test_statistics_after_download(self, client, seeded_db):
        await client.post("/api/download/song", json={"song_id": seeded_db["song_id"]})

        res = await client.get("/api/statistics")
        data = res.json()
        assert data["overview"]["total_downloaded"] == 1
        assert data["overview"]["total_pending"] == 0
        assert data["overview"]["storage_used_bytes"] == len(AUDIO_PAYLOAD)
        year_stats = {s["year"]: s for s in data["year_stats"]}
        assert year_stats[1998]["downloaded_count"] == 1
        assert year_stats[1998]["songs_count"] == 1


class TestArchives:
    async def test_create_and_download_year_archive(self, client, seeded_db):
        await client.post("/api/download/song", json={"song_id": seeded_db["song_id"]})

        res = await client.post("/api/archive/year", json={"year_id": seeded_db["year_id"]})
        assert res.status_code == 200
        archive = res.json()
        assert archive["name"] == "1998.zip"
        assert archive["archive_type"] == "year"
        assert archive["file_count"] == 1
        # No absolute paths leaked to the client
        assert not archive["path"].startswith("/") and ":" not in archive["path"]
        assert archive["download_url"].endswith(f"/api/archives/{archive['id']}/file")

        file_res = await client.get(archive["download_url"])
        assert file_res.status_code == 200
        assert file_res.headers["content-type"].startswith("application/zip")

        with zipfile.ZipFile(__import__("io").BytesIO(file_res.content)) as zf:
            names = zf.namelist()
            assert "1998/Test Album/01 - Test Song.mp3" in names

    async def test_album_and_years_archives(self, client, seeded_db):
        await client.post("/api/download/song", json={"song_id": seeded_db["song_id"]})

        res = await client.post("/api/archive/album", json={"album_id": seeded_db["album_id"]})
        assert res.status_code == 200
        assert res.json()["name"] == "Test Album.zip"

        res = await client.post("/api/archive/years", json={"start_year": 1998, "end_year": 1998})
        assert res.status_code == 200
        name = res.json()["name"]
        # The download auto-archive already created 1998-1998.zip, so the
        # endpoint's copy is de-duplicated with a suffix.
        assert name.startswith("1998-1998") and name.endswith(".zip")

    async def test_archive_404_for_missing_file(self, client):
        res = await client.get("/api/archives/999999/file")
        assert res.status_code == 404


class TestYearCounts:
    """Year totals must be derived from the actual album/song rows, never
    from stale counter columns."""

    async def test_year_total_songs_reflects_actual_rows(self, client, seeded_db):
        # Seed two more albums and five more songs in the same year so the
        # real count (7) differs from anything a stale counter could hold.
        async with AsyncSessionLocal() as db:
            for i in range(2):
                album = Album(
                    category_id=seeded_db["category_id"],
                    title=f"Extra Album {i}",
                    url=f"http://fixture.local/album/extra/{i}",
                    release_year=1998, status=JobStatus.COMPLETED,
                )
                db.add(album)
                await db.flush()
                for j in range(3):
                    db.add(Song(
                        album_id=album.id,
                        title=f"Extra Song {i}-{j}",
                        track_number=j + 1,
                        status=JobStatus.COMPLETED,
                    ))
            await db.commit()

        res = await client.get("/api/years")
        assert res.status_code == 200
        years = {y["year"]: y for y in res.json()}
        assert years[1998]["total_albums"] == 3
        assert years[1998]["total_songs"] == 7

    async def test_year_detail_counts_match_actual(self, client, seeded_db):
        res = await client.get(f"/api/years/{seeded_db['year_id']}")
        assert res.status_code == 200
        data = res.json()
        assert data["total_albums"] == 1
        assert data["total_songs"] == 1

    async def test_missing_album_returns_404(self, client):
        res = await client.get("/api/albums/999999")
        assert res.status_code == 404
        res = await client.get("/api/albums/999999/songs")
        assert res.status_code == 200
        assert res.json() == []

    async def test_missing_year_returns_404(self, client):
        res = await client.get("/api/years/999999")
        assert res.status_code == 404


class TestProgressClamping:
    """Progress percentages must never exceed 100, even with inconsistent
    counters (processed > total)."""

    async def test_job_progress_clamped(self, client):
        async with AsyncSessionLocal() as db:
            job = CrawlJob(
                base_url="http://fixture.local/category/{year}",
                start_year=1990, end_year=1995,
                status=JobStatus.RUNNING,
                total_years=6, processed_years=6,
                total_pages=10, processed_pages=900,
                total_albums=5, processed_albums=250,
                total_songs=100, processed_songs=700,
            )
            db.add(job)
            await db.commit()
            job_id = job.id

        res = await client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200
        data = res.json()
        for key in ("year_progress", "page_progress", "album_progress",
                    "song_progress", "overall_progress"):
            assert 0 <= data[key] <= 100, f"{key} = {data[key]}"

    async def test_year_progress_zero_when_no_total(self, client):
        async with AsyncSessionLocal() as db:
            job = CrawlJob(
                base_url="http://fixture.local/category/{year}",
                start_year=1990, end_year=1990,
                status=JobStatus.PENDING,
                total_years=0, processed_years=0,
            )
            db.add(job)
            await db.commit()
            job_id = job.id

        res = await client.get(f"/api/jobs/{job_id}")
        assert res.status_code == 200
        data = res.json()
        assert data["year_progress"] == 0
        assert data["overall_progress"] == 0


class TestIdempotentYears:
    """Analyzing the same year twice must reuse the canonical Year row."""

    async def test_reanalysis_reuses_year_row(self):
        from app.services.crawl_service import CrawlService
        service = CrawlService()

        async with AsyncSessionLocal() as db:
            job1 = CrawlJob(
                base_url="http://fixture.local/category/{year}",
                start_year=1990, end_year=1990,
                status=JobStatus.COMPLETED,
            )
            db.add(job1)
            await db.flush()
            job2 = CrawlJob(
                base_url="http://fixture.local/category/{year}",
                start_year=1990, end_year=1990,
                status=JobStatus.PENDING,
            )
            db.add(job2)
            await db.flush()

            first = await service._get_or_create_year(db, job1.id, 1990, "http://fixture.local/category/1990")
            second = await service._get_or_create_year(db, job2.id, 1990, "http://fixture.local/category/1990")
            await db.commit()

            assert first.id == second.id

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select, func
            count = await db.scalar(
                select(func.count(Year.id)).where(Year.year == 1990)
            )
            assert count == 1


class TestBackgroundDownloads:
    async def test_download_album_background(self, client, seeded_db):
        res = await client.post("/api/download/album", json={"album_id": seeded_db["album_id"]})
        assert res.status_code == 200
        data = res.json()
        job_id = data["job_id"]
        assert data["status"] == "running"
        assert data["estimated_files"] == 1

        # Poll until the background job completes
        progress = None
        for _ in range(50):
            await asyncio.sleep(0.1)
            progress_res = await client.get(f"/api/download/{job_id}/progress")
            progress = progress_res.json()
            if progress["status"] in ("completed", "failed", "cancelled"):
                break

        assert progress["status"] == "completed"
        assert progress["downloaded_files"] == 1
