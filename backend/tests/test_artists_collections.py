"""Tests for artist normalization, duration parsing and the Artists API."""
import asyncio
import os
from datetime import datetime

import pytest
from httpx import AsyncClient, ASGITransport

from app.utils import (
    normalize_artist_name,
    artist_slug,
    split_artist_names,
    parse_duration_seconds,
    format_duration_seconds,
)


@pytest.fixture(autouse=True)
async def _init_tables():
    """Create tables before each test (mirrors test_api.py's autouse seed)."""
    from app.database.config import init_db, AsyncSessionLocal
    from app.models.database import (
        CrawlJob, Year, Category, Album, Song, AudioResource, Artist,
    )
    await init_db()
    async with AsyncSessionLocal() as cleanup:
        for model in (AudioResource, Song, Album, Artist, Category, Year, CrawlJob):
            await cleanup.execute(model.__table__.delete())
        await cleanup.commit()


@pytest.fixture
async def client():
    from app.main import create_app
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
async def seeded_artists(client):
    from app.database.config import AsyncSessionLocal
    from app.models.database import (
        CrawlJob, Year, Category, Album, Song, JobStatus,
    )
    from app.services.artist_service import ArtistService

    svc = ArtistService()
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
                    artist="A.R. Rahman", duration="4:05", duration_seconds=245,
                    status=JobStatus.COMPLETED)
        db.add(song)
        await db.flush()

        artist = await svc.link_song_artist(db, song, "A.R. Rahman")
        await svc.refresh_song_count(db, artist.id)
        await db.commit()
        yield {"job_id": job.id, "artist_id": artist.id, "song_id": song.id}


# ---------------------------------------------------------------------------
# Normalization / slug utilities
# ---------------------------------------------------------------------------

class TestArtistNormalization:
    def test_normalize_punctuation_and_case(self):
        assert normalize_artist_name("A.R. Rahman") == "a r rahman"
        assert normalize_artist_name("A R Rahman") == "a r rahman"
        assert normalize_artist_name("A.R.Rahman") == "a r rahman"
        assert normalize_artist_name("A.R Rahman") == "a r rahman"

    def test_normalize_empty(self):
        assert normalize_artist_name("") == ""
        assert normalize_artist_name(None) == ""

    def test_normalize_keeps_other_chars(self):
        assert normalize_artist_name("Ilaiyaraaja") == "ilaiyaraaja"
        assert normalize_artist_name("  S. P. Balasubrahmanyam  ") == "s p balasubrahmanyam"

    def test_slug(self):
        assert artist_slug("A.R. Rahman") == "a-r-rahman"
        assert artist_slug("Ilaiyaraaja") == "ilaiyaraaja"
        assert artist_slug("A R Rahman") == "a-r-rahman"

    def test_split_artist_names(self):
        assert split_artist_names("A; B; C") == ["A", "B", "C"]
        assert split_artist_names("A, B") == ["A", "B"]
        assert split_artist_names("A & B") == ["A", "B"]
        assert split_artist_names("A and B") == ["A", "B"]
        assert split_artist_names("A feat. B") == ["A", "B"]
        assert split_artist_names("A ft. B") == ["A", "B"]
        assert split_artist_names("Single") == ["Single"]
        assert split_artist_names("") == []


# ---------------------------------------------------------------------------
# Duration parsing / formatting
# ---------------------------------------------------------------------------

class TestDuration:
    def test_parse_mm_ss(self):
        assert parse_duration_seconds("4:05") == 245

    def test_parse_hh_mm_ss(self):
        assert parse_duration_seconds("1:02:03") == 3723

    def test_parse_words(self):
        assert parse_duration_seconds("4m 5s") == 245
        assert parse_duration_seconds("4 min 5 sec") == 245

    def test_parse_plain_seconds(self):
        assert parse_duration_seconds("245") == 245

    def test_parse_invalid_never_raises(self):
        assert parse_duration_seconds("not-a-duration") is None
        assert parse_duration_seconds("") is None
        assert parse_duration_seconds(None) is None

    def test_format(self):
        assert format_duration_seconds(245) == "04:05"
        assert format_duration_seconds(3723) == "1:02:03"
        assert format_duration_seconds(0) == "00:00"
        assert format_duration_seconds(None) == "--:--"


# ---------------------------------------------------------------------------
# Artists API
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_artists_list_and_detail(client, seeded_artists):
    res = await client.get("/api/artists?letter=A")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    artist = data["artists"][0]
    assert artist["name"] == "A.R. Rahman"
    assert artist["slug"] == "a-r-rahman"

    res = await client.get("/api/artists/a-r-rahman")
    assert res.status_code == 200
    assert res.json()["song_count"] == 1


@pytest.mark.asyncio
async def test_artists_search_db_backed(client, seeded_artists):
    res = await client.get("/api/artists/search?q=rahman")
    assert res.status_code == 200
    assert res.json()["total"] == 1

    res = await client.get("/api/artists/search?q=zzzz")
    assert res.json()["total"] == 0


@pytest.mark.asyncio
async def test_artist_songs_with_duration_and_year_filter(client, seeded_artists):
    res = await client.get("/api/artists/a-r-rahman/songs")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    song = data["songs"][0]
    assert song["title"] == "Test Song"
    assert song["duration_seconds"] == 245
    assert song["year"] == 1998

    res = await client.get("/api/artists/a-r-rahman/songs?year=1999")
    assert res.json()["total"] == 0


@pytest.mark.asyncio
async def test_artist_years(client, seeded_artists):
    res = await client.get("/api/artists/a-r-rahman/years")
    assert res.status_code == 200
    assert res.json() == [1998]


@pytest.mark.asyncio
async def test_artist_404(client):
    res = await client.get("/api/artists/does-not-exist")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_search_includes_artists(client, seeded_artists):
    res = await client.post("/api/search", json={"query": "rahman", "search_type": "all"})
    assert res.status_code == 200
    types = [r["type"] for r in res.json()["results"]]
    assert "artist" in types


# ---------------------------------------------------------------------------
# Multi-year collection
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collection_requires_valid_year_range(client):
    res = await client.post("/api/collections", json={
        "base_url": "http://fixture.local/category/{year}",
        "start_year": 2000,
        "end_year": 1999,
    })
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_collection_create_and_status(client):
    res = await client.post("/api/collections", json={
        "base_url": "http://fixture.local/category/{year}",
        "start_year": 1998,
        "end_year": 1998,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("pending", "running", "completed")
    job_id = data["job_id"]

    res = await client.get(f"/api/collections/{job_id}/progress")
    assert res.status_code == 200
    progress = res.json()
    assert progress["job_id"] == job_id
    assert "progress_percentage" in progress

    res = await client.get(f"/api/collections/{job_id}")
    assert res.status_code == 200
    assert res.json()["job_id"] == job_id

    # Wait for the background crawl to reach a terminal state so the DB
    # connection is released before the next test (fixture.local fails fast).
    for _ in range(100):
        status_res = await client.get(f"/api/collections/{job_id}")
        if status_res.json()["status"] in ("completed", "failed", "cancelled"):
            break
        await asyncio.sleep(0.1)


@pytest.mark.asyncio
async def test_collection_404(client):
    res = await client.get("/api/collections/99999")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Collection archive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_collection_archive_no_files_fails_gracefully(client, seeded_artists):
    res = await client.post("/api/collections", json={
        "base_url": "http://fixture.local/category/{year}",
        "start_year": 1998,
        "end_year": 1998,
        "archive_prefix": "Tamil_Songs_",
    })
    assert res.status_code == 200
    job_id = res.json()["job_id"]

    # Wait for the background crawl to finish (releases the DB lock)
    for _ in range(100):
        status_res = await client.get(f"/api/collections/{job_id}")
        if status_res.json()["status"] in ("completed", "failed", "cancelled"):
            break
        await asyncio.sleep(0.1)

    res = await client.get(f"/api/collections/{job_id}/archive")
    # No archive yet -> 404 until generation completes
    assert res.status_code == 404
