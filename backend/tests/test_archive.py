"""Tests for the ZIP archive generator (filesystem -> zip)."""
import zipfile

import pytest

from app.archive.generator import ArchiveGenerator
from app.storage.audio_storage import AudioStorage


@pytest.fixture
def audio_root(tmp_path):
    root = AudioStorage(str(tmp_path / "audio_collection"))
    files = {
        "1998/Album A/01 - Song A.mp3": b"a" * 100,
        "1998/Album A/02 - Song B.mp3": b"b" * 100,
        "1998/Album B/01 - Song C.mp3": b"c" * 100,
        "1999/Album C/01 - Song D.flac": b"d" * 100,
    }
    for rel, content in files.items():
        path = root.resolve_path(rel)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    # Non-audio files should be excluded
    (root.resolve_path("1998/Album A/cover.jpg")).parent.mkdir(parents=True, exist_ok=True)
    (root.resolve_path("1998/Album A/cover.jpg")).write_bytes(b"jpeg")
    return root


@pytest.fixture
def generator(tmp_path):
    return ArchiveGenerator(
        archive_dir=str(tmp_path / "archives"),
        temp_dir=str(tmp_path / "temp"),
    )


class TestYearArchive:
    async def test_year_archive_structure(self, generator, audio_root):
        result = await generator.create_year_archive(1998, audio_root.root)
        assert result["success"]
        assert result["archive_name"] == "1998.zip"
        assert result["file_count"] == 3

        with zipfile.ZipFile(result["archive_path"]) as zf:
            names = set(zf.namelist())
            assert "1998/Album A/01 - Song A.mp3" in names
            assert "1998/Album A/02 - Song B.mp3" in names
            assert "1998/Album B/01 - Song C.mp3" in names
            assert not any("cover" in n for n in names)

    async def test_missing_year_fails(self, generator, audio_root):
        result = await generator.create_year_archive(2005, audio_root.root)
        assert not result["success"]


class TestMultiYearArchive:
    async def test_structure_includes_years(self, generator, audio_root):
        result = await generator.create_multi_year_archive([1998, 1999], audio_root.root)
        assert result["success"]
        assert result["archive_name"] == "1998-1999.zip"
        assert result["file_count"] == 4

        with zipfile.ZipFile(result["archive_path"]) as zf:
            names = set(zf.namelist())
            assert "1998/Album A/01 - Song A.mp3" in names
            assert "1999/Album C/01 - Song D.flac" in names

    async def test_prefix_naming(self, generator, audio_root):
        result = await generator.create_multi_year_archive(
            [1998, 1999], audio_root.root, prefix="Tamil_Songs_"
        )
        assert result["success"]
        assert result["archive_name"] == "Tamil_Songs_1998-1999.zip"

    async def test_root_folder_nested_layout(self, generator, audio_root):
        result = await generator.create_multi_year_archive(
            [1998, 1999],
            audio_root.root,
            root_folder="Tamil_Songs_1998-1999",
        )
        assert result["success"]
        with zipfile.ZipFile(result["archive_path"]) as zf:
            names = set(zf.namelist())
            assert "Tamil_Songs_1998-1999/1998/Album A/01 - Song A.mp3" in names
            assert "Tamil_Songs_1998-1999/1999/Album C/01 - Song D.flac" in names

    async def test_prefix_and_root_folder_combined(self, generator, audio_root):
        result = await generator.create_multi_year_archive(
            [1998],
            audio_root.root,
            prefix="Tamil_Songs_",
            root_folder="Tamil_Songs_1998-1998",
        )
        assert result["success"]
        assert result["archive_name"] == "Tamil_Songs_1998-1998.zip"
        with zipfile.ZipFile(result["archive_path"]) as zf:
            assert "Tamil_Songs_1998-1998/1998/Album A/01 - Song A.mp3" in zf.namelist()


class TestAlbumArchive:
    async def test_album_archive_structure(self, generator, audio_root):
        album_dir = audio_root.resolve_path("1998/Album A")
        result = await generator.create_album_archive("Album A", album_dir)
        assert result["success"]
        assert result["archive_name"] == "Album A.zip"
        assert result["file_count"] == 2

        with zipfile.ZipFile(result["archive_path"]) as zf:
            names = set(zf.namelist())
            assert "Album A/01 - Song A.mp3" in names
            assert "Album A/02 - Song B.mp3" in names


class TestArchiveSafety:
    async def test_arcname_traversal_blocked(self, generator, audio_root):
        source_files = [{
            "path": str(audio_root.resolve_path("1998/Album A/01 - Song A.mp3")),
            "arcname": "../../../../etc/passwd",
        }]
        result = await generator.create_zip_archive(source_files, "safe.zip")
        assert result["success"]

        with zipfile.ZipFile(result["archive_path"]) as zf:
            assert zf.namelist() == ["etc/passwd"]
            assert not any(".." in n for n in zf.namelist())

    async def test_archive_name_relative(self, generator, audio_root):
        result = await generator.create_year_archive(1998, audio_root.root)
        assert result["relative_path"] == "1998.zip"
        # No absolute paths exposed
        assert not result["relative_path"].startswith("/") or "\\" not in result["relative_path"]
