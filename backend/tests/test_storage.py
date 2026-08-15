"""Tests for the filesystem audio storage service."""
import os

import pytest

from app.storage.audio_storage import AudioStorage, AudioStorageError


@pytest.fixture
def storage(tmp_path):
    return AudioStorage(str(tmp_path))


class TestSanitization:
    def test_invalid_chars_replaced(self):
        assert AudioStorage.sanitize_segment('a/b\\c:d*e?f"g<h>i|j') == "a_b_c_d_e_f_g_h_i_j"

    def test_control_chars_removed(self):
        assert AudioStorage.sanitize_segment("song\x00\x01\x02name") == "songname"

    def test_traversal_segments_sanitized(self):
        assert AudioStorage.sanitize_segment("../..") != "../.."
        assert "/" not in AudioStorage.sanitize_segment("../../etc")
        assert "\\" not in AudioStorage.sanitize_segment("..\\..\\etc")

    def test_reserved_names_prefixed(self):
        assert AudioStorage.sanitize_segment("CON") == "_CON"
        assert AudioStorage.sanitize_segment("com1") == "_com1"

    def test_empty_falls_back(self):
        assert AudioStorage.sanitize_segment("", "Unknown Album") == "Unknown Album"
        assert AudioStorage.sanitize_segment("...", "Unknown") == "Unknown"

    def test_extension_sanitized(self):
        assert AudioStorage.sanitize_extension("mp3") == "mp3"
        assert AudioStorage.sanitize_extension(".FLAC") == "flac"
        assert AudioStorage.sanitize_extension("exe") == "mp3"
        assert AudioStorage.sanitize_extension(None) == "mp3"

    def test_filename_keeps_valid_extension(self):
        assert AudioStorage.sanitize_filename("01 - Song?.mp3") == "01 - Song.mp3"
        assert AudioStorage.sanitize_filename("02 - Other?.exe") == "02 - Other.mp3"

    def test_build_relative_path(self, storage):
        p = storage.build_relative_path(1998, "Test Album", "01 - Song", "mp3")
        assert p == "1998/Test Album/01 - Song.mp3"

    def test_build_relative_path_fallbacks(self, storage):
        assert storage.build_relative_path(None, "Album", "Track", "mp3").startswith("Unknown Year/Album/")
        assert storage.build_relative_path(1998, None, "Track", "mp3").endswith("1998/Unknown Album/Track.mp3")
        assert storage.build_relative_path(1998, "Album", "Track", None).endswith("Track.mp3")


class TestPathResolution:
    def test_resolve_stays_in_root(self, storage):
        path = storage.resolve_path("1998/Album/01 - Song.mp3")
        assert str(path).startswith(str(storage.root))

    def test_traversal_blocked(self, storage):
        with pytest.raises(AudioStorageError):
            storage.resolve_path("../outside.mp3")
        with pytest.raises(AudioStorageError):
            storage.resolve_path("1998/../../secret.mp3")
        with pytest.raises(AudioStorageError):
            storage.resolve_path("")

    def test_exists_and_size(self, storage, tmp_path):
        rel = "1998/Album/01 - Song.mp3"
        target = storage.resolve_path(rel)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x" * 100)
        assert storage.audio_exists(rel)
        assert storage.audio_size(rel) == 100
        assert not storage.audio_exists("1999/Album/01 - Song.mp3")

    def test_delete(self, storage):
        rel = "1998/A/01 - Song.mp3"
        target = storage.resolve_path(rel)
        target.parent.mkdir(parents=True)
        target.write_bytes(b"x")
        assert storage.delete_audio(rel)
        assert not target.exists()
        assert not storage.delete_audio(rel)


class TestSaveAudio:
    async def test_save_streams_and_renames(self, storage):
        async def chunks():
            for _ in range(4):
                yield b"0123456789" * 100

        result = await storage.save_audio(chunks(), "1998/Album/01 - Song.mp3", expected_size=4000)
        assert result["relative_path"] == "1998/Album/01 - Song.mp3"
        assert result["size"] == 4000
        assert result["absolute_path"].startswith(str(storage.root))

        # No .part file left behind
        assert list(storage.root.rglob("*.part")) == []
        assert storage.audio_exists("1998/Album/01 - Song.mp3")

    async def test_size_mismatch_fails_and_cleans_part(self, storage):
        async def chunks():
            yield b"12345"

        with pytest.raises(AudioStorageError):
            await storage.save_audio(chunks(), "1998/Album/01 - Song.mp3", expected_size=100)

        assert list(storage.root.rglob("*.part")) == []
        assert not storage.audio_exists("1998/Album/01 - Song.mp3")

    async def test_duplicate_names_suffixed(self, storage):
        async def chunks():
            yield b"12345"

        first = await storage.save_audio(chunks(), "1998/Album/01 - Song.mp3")
        second = await storage.save_audio(chunks(), "1998/Album/01 - Song.mp3")

        assert first["relative_path"] == "1998/Album/01 - Song.mp3"
        assert second["relative_path"] == "1998/Album/01 - Song (1).mp3"
        assert storage.audio_exists(first["relative_path"])
        assert storage.audio_exists(second["relative_path"])

    async def test_stop_event_cancels_and_cleans(self, storage):
        class StopFlag:
            def is_set(self):
                return True

        async def chunks():
            yield b"12345"

        with pytest.raises(AudioStorageError):
            await storage.save_audio(chunks(), "1998/Album/01 - Song.mp3", stop_event=StopFlag())

        assert list(storage.root.rglob("*.part")) == []

    def test_storage_size(self, storage):
        (storage.root / "1998").mkdir(parents=True)
        (storage.root / "1998" / "a.mp3").write_bytes(b"a" * 10)
        (storage.root / "1998" / "b.mp3").write_bytes(b"b" * 20)
        assert storage.storage_size() == 30

    def test_cleanup_parts(self, storage):
        (storage.root / "1998").mkdir(parents=True)
        part = storage.root / "1998" / "a.mp3.part"
        part.write_bytes(b"x")
        import time as _time
        os.utime(part, (_time.time() - 7200, _time.time() - 7200))
        storage.cleanup_parts(max_age_seconds=3600)
        assert not part.exists()
