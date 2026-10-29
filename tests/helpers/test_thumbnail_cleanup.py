"""Regression coverage for concurrent thumbnail-cache invalidation."""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from music_assistant.helpers import images


async def test_cleanup_continues_when_enumerated_file_disappears(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An invalidated entry must not abort cleanup of the remaining cache."""
    thumb_dir = tmp_path / images._THUMB_CACHE_DIR
    thumb_dir.mkdir()
    vanished = thumb_dir / "vanished_src"
    retained = thumb_dir / "retained_thumb"
    vanished.write_bytes(b"source")
    retained.write_bytes(b"thumbnail")
    real_scandir = os.scandir

    def racing_scandir(path: str) -> Iterator[os.DirEntry[str]]:
        with real_scandir(path) as iterator:
            entries = list(iterator)
        vanished.unlink()
        return iter(entries)

    monkeypatch.setattr(os, "scandir", racing_scandir)
    assert await images.cleanup_thumb_cache(str(tmp_path), 0) == 1
    assert not retained.exists()


async def test_cleanup_keeps_newest_files_within_limit(tmp_path: Path) -> None:
    """Preserve the size limit, oldest-first ordering and non-file exclusion."""
    thumb_dir = tmp_path / images._THUMB_CACHE_DIR
    thumb_dir.mkdir()
    old = thumb_dir / "old"
    new = thumb_dir / "new"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    os.utime(old, (1, 1))
    os.utime(new, (2, 2))
    (thumb_dir / "directory").mkdir()
    assert await images.cleanup_thumb_cache(str(tmp_path), 3) == 1
    assert not old.exists()
    assert new.read_bytes() == b"new"
    assert await images.cleanup_thumb_cache(str(tmp_path), 3) == 0


async def test_cleanup_missing_directory_is_empty(tmp_path: Path) -> None:
    """A cache not created yet remains a successful no-op."""
    assert await images.cleanup_thumb_cache(str(tmp_path), 0) == 0


async def test_cleanup_preserves_permission_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only disappeared entries are tolerated, not unrelated stat failures."""
    (tmp_path / images._THUMB_CACHE_DIR).mkdir()

    class DeniedEntry:
        def is_file(self) -> bool:
            return True

        def stat(self) -> None:
            raise PermissionError("synthetic stat denial")

    monkeypatch.setattr(os, "scandir", lambda _: iter([DeniedEntry()]))
    with pytest.raises(PermissionError, match="synthetic stat denial"):
        await images.cleanup_thumb_cache(str(tmp_path), 0)
