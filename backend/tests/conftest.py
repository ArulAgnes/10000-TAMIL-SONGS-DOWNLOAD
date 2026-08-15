"""Shared pytest fixtures and environment for backend tests.

Environment is configured BEFORE app modules are imported so the engine,
storage root and app settings point at isolated test locations.
"""
import os
import shutil
import threading
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

TEST_ROOT = BACKEND_DIR / "test_audio_collection"
TEST_ARCHIVES = BACKEND_DIR / "test_archives"
TEST_DB = BACKEND_DIR / "test_audio_analyzer.db"

os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB.as_posix()}"
os.environ["AUDIO_STORAGE_PATH"] = str(TEST_ROOT)
os.environ["ARCHIVE_DIR"] = str(TEST_ARCHIVES)
os.environ["TEMP_DIR"] = str(BACKEND_DIR / "test_temp")
os.environ["MAX_CONCURRENCY"] = "3"
os.environ["REQUEST_TIMEOUT"] = "15"
os.environ["MAX_RETRIES"] = "2"
os.environ["REQUEST_DELAY_MS"] = "10"


def _cleanup():
    for path in (TEST_ROOT, TEST_ARCHIVES, TEST_DB,
                 BACKEND_DIR / "test_temp"):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists():
            path.unlink()


_cleanup()


AUDIO_PAYLOAD = (b"ID3\x03\x00\x00\x00\x00\x00\x00FAKE_AUDIO_DATA_0123456789_"
                 b"abcdefghijklmnopqrstuvwxyz" * 2048)


class FixtureHandler(BaseHTTPRequestHandler):
    """Serves a synthetic audio file and a couple of bad responses."""

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/test.mp3"):
            body = AUDIO_PAYLOAD
            self.send_response(200)
            self.send_header("Content-Type", "audio/mpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/test.flac"):
            body = b"fLaC" + AUDIO_PAYLOAD
            self.send_response(200)
            self.send_header("Content-Type", "audio/flac")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/bad.html"):
            body = b"<html><body>not audio</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/error500"):
            self.send_response(500)
            self.end_headers()
        elif self.path.startswith("/notfound"):
            self.send_response(404)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


class FixtureServer:
    """Small HTTP server in a thread serving the fixture site."""

    def __init__(self):
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        self._thread.start()

    def stop(self):
        self._server.shutdown()
        self._server.server_close()


server = FixtureServer()
server.start()


@pytest.fixture(scope="session", autouse=True)
def stop_fixture_server():
    yield
    server.stop()


@pytest.fixture(autouse=True)
def clean_filesystem_dirs():
    """Wipe shared filesystem dirs before each test so downloaded files and
    generated archives from earlier tests cannot leak into later ones."""
    for path in (TEST_ROOT, TEST_ARCHIVES):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    yield
