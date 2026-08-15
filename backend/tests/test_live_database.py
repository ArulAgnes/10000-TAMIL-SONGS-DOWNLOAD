"""Regression tests against the live production SQLite database.

These tests are READ-ONLY: they connect directly to ``backend/audio_analyzer.db``
and assert that Year statistics reflect the actual album/song rows.

The test file is skipped when the production database is not present.
"""
import os
import sqlite3
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
LIVE_DB = BACKEND_DIR / "audio_analyzer.db"

pytestmark = pytest.mark.skipif(
    not LIVE_DB.exists(),
    reason="live production database not present",
)


@pytest.fixture(scope="module")
def db():
    conn = sqlite3.connect(str(LIVE_DB))
    conn.row_factory = sqlite3.Row
    yield conn
    conn.close()


def _year_ids_for(conn, year: int):
    return [r["id"] for r in conn.execute(
        "SELECT id FROM years WHERE year = ?", (year,)
    )]


class TestLiveYearCounts:
    def test_2003_has_8_albums(self, db):
        ids = _year_ids_for(db, 2003)
        assert ids, "2003 year record missing"
        total = sum(
            db.execute(
                """SELECT COUNT(DISTINCT a.id) AS n
                   FROM albums a JOIN categories c ON c.id = a.category_id
                   WHERE c.year_id = ?""", (year_id,)
            ).fetchone()["n"]
            for year_id in ids
        )
        assert total == 8

    def test_2003_has_527_songs(self, db):
        ids = _year_ids_for(db, 2003)
        assert ids, "2003 year record missing"
        total = sum(
            db.execute(
                """SELECT COUNT(DISTINCT s.id) AS n
                   FROM songs s
                   JOIN albums a ON a.id = s.album_id
                   JOIN categories c ON c.id = a.category_id
                   WHERE c.year_id = ?""", (year_id,)
            ).fetchone()["n"]
            for year_id in ids
        )
        assert total == 527

    def test_2003_year_row_totals_are_synced(self, db):
        ids = _year_ids_for(db, 2003)
        for year_id in ids:
            row = db.execute(
                "SELECT total_albums, total_songs FROM years WHERE id = ?",
                (year_id,),
            ).fetchone()
            assert row["total_albums"] == 8
            assert row["total_songs"] == 527

    def test_year_rows_unique_per_calendar_year(self, db):
        dupes = db.execute(
            "SELECT year, COUNT(*) AS n FROM years GROUP BY year HAVING n > 1"
        ).fetchall()
        assert dupes == []

    def test_album_156_has_39_songs(self, db):
        assert db.execute(
            "SELECT COUNT(*) FROM songs WHERE album_id = 156"
        ).fetchone()[0] == 39

    def test_album_158_has_69_songs(self, db):
        assert db.execute(
            "SELECT COUNT(*) FROM songs WHERE album_id = 158"
        ).fetchone()[0] == 69

    def test_totals_are_1623_albums_18230_songs(self, db):
        assert db.execute("SELECT COUNT(*) FROM albums").fetchone()[0] == 1623
        assert db.execute("SELECT COUNT(*) FROM songs").fetchone()[0] == 18230

    def test_zip_links_are_album_resources_not_song_urls(self, db):
        # Album-level ZIP links must live on albums.zip_url, not on songs.
        zipped = db.execute(
            "SELECT COUNT(*) FROM albums WHERE zip_url IS NOT NULL AND zip_url != ''"
        ).fetchone()[0]
        assert zipped > 0
        # Song rows named like the ZIP button exist from legacy crawls but the
        # canonical album.zip_url must be the download resource.
        row = db.execute(
            "SELECT zip_url FROM albums WHERE id = 156"
        ).fetchone()
        assert row["zip_url"] and "download-album" in row["zip_url"]


class TestLiveApiShapes:
    def test_year_by_number_returns_2003_entry(self, db):
        ids = _year_ids_for(db, 2003)
        assert ids == [17]  # canonical row after duplicate cleanup

    def test_songs_url_column_exists(self, db):
        cols = {r["name"] for r in db.execute("PRAGMA table_info(songs)")}
        assert "url" in cols  # schema drift fixed (model has Song.url)
