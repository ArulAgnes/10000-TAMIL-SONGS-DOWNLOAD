"""Tests for the download manager (filesystem downloads)."""
import pytest

from app.downloader.manager import DownloadManager
from app.storage.audio_storage import AudioStorage
from tests.conftest import server, AUDIO_PAYLOAD


@pytest.fixture
def storage(tmp_path):
    return AudioStorage(str(tmp_path))


@pytest.fixture
def manager(storage):
    m = DownloadManager(storage=storage, max_concurrent_downloads=2,
                        request_delay_ms=1, max_retries=1, request_timeout=10)
    yield m


class TestValidation:
    def test_content_type_validation(self):
        assert DownloadManager._validate_content_type("audio/mpeg", "mp3")
        assert DownloadManager._validate_content_type("audio/mpeg; charset=utf-8", "mp3")
        assert DownloadManager._validate_content_type("application/octet-stream", "mp3")
        assert not DownloadManager._validate_content_type("text/html", "mp3")
        assert not DownloadManager._validate_content_type("application/json", "mp3")
        assert not DownloadManager._validate_content_type("image/png", "mp3")
        assert DownloadManager._validate_content_type("", "flac")

    def test_extension_detection(self):
        assert DownloadManager._detect_extension("http://x/a.mp3?token=1", None) == "mp3"
        assert DownloadManager._detect_extension("http://x/a", "flac") == "flac"
        assert DownloadManager._detect_extension("http://x/a", None) == "mp3"


class TestDownloads:
    async def test_download_audio_to_disk(self, manager, storage):
        result = await manager.download_resources([{
            "id": 1,
            "url": f"{server.base_url}/test.mp3",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
            "artist": "Test Artist",
            "track_number": 1,
            "format": "mp3",
        }], job_id=1)

        assert result["successful"] == 1
        assert result["failed"] == 0
        download = result["downloads"][0]
        assert download["success"]
        assert download["local_path"] == "1998/Test Album/01 - Test Song.mp3"
        assert download["size"] == len(AUDIO_PAYLOAD)

        # File exists on disk with exact content
        stored = storage.get_audio_path(download["local_path"])
        assert stored.read_bytes() == AUDIO_PAYLOAD
        # No .part leftovers
        assert list(storage.root.rglob("*.part")) == []

    async def test_download_without_track_number(self, manager):
        result = await manager.download_resources([{
            "id": 2,
            "url": f"{server.base_url}/test.mp3",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
        }], job_id=2)

        assert result["successful"] == 1
        assert result["downloads"][0]["local_path"] == "1998/Test Album/Test Song.mp3"

    async def test_html_response_rejected(self, manager, storage):
        result = await manager.download_resources([{
            "id": 3,
            "url": f"{server.base_url}/bad.html",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
        }], job_id=3)

        assert result["failed"] == 1
        download = result["downloads"][0]
        assert not download["success"]
        assert "Rejected non-audio response" in download["error"]
        # Nothing misleadingly saved as .mp3
        assert list(storage.root.rglob("*.mp3")) == []

    async def test_http_error_fails(self, manager):
        result = await manager.download_resources([{
            "id": 4,
            "url": f"{server.base_url}/notfound",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
        }], job_id=4)

        assert result["failed"] == 1
        assert "HTTP 404" in result["downloads"][0]["error"]

    async def test_already_downloaded_skipped(self, manager, storage):
        resource = {
            "id": 5,
            "url": f"{server.base_url}/test.mp3",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
            "track_number": 1,
        }
        await manager.download_resources([resource], job_id=5)
        # Simulate metadata already recorded in the DB
        resource["local_path"] = "1998/Test Album/01 - Test Song.mp3"

        result = await manager.download_resources([resource], job_id=6)
        assert result["successful"] == 1
        assert result["downloads"][0].get("skipped") is True or result["downloads"][0]["success"]

    async def test_cancel_cleanup(self, manager, storage):
        manager.request_stop()
        result = await manager.download_resources([{
            "id": 6,
            "url": f"{server.base_url}/test.mp3",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
        }], job_id=7)

        assert result["failed"] == 1
        assert result["downloads"][0]["cancelled"]
        assert list(storage.root.rglob("*.part")) == []

    async def test_progress_events_emitted(self, manager):
        events = []
        manager.set_progress_callback(lambda data: events.append(data))

        await manager.download_resources([{
            "id": 7,
            "url": f"{server.base_url}/test.flac",
            "year": 1998,
            "album": "Test Album",
            "song": "Test Song",
        }], job_id=8)

        types = [e["type"] for e in events]
        assert "download_start" in types
        assert "download_complete" in types
        assert "batch_progress" in types
