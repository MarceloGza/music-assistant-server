"""Regression tests for librespot stdout ending before its process exits."""

from __future__ import annotations

import asyncio
import sys
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest
from music_assistant_models.errors import AudioError

from music_assistant.helpers.process import AsyncProcess
from music_assistant.providers.spotify.backends.librespot import LibrespotBackend

if TYPE_CHECKING:
    from pathlib import Path

    from music_assistant.providers.spotify.provider import SpotifyProvider


@pytest.mark.parametrize("exit_delay", [0, 0.2, 0.5])
async def test_clean_exit_after_stdout_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, exit_delay: float
) -> None:
    """A successful child closing stdout before exit must not fail the audio stream."""
    backend, processes = _backend(tmp_path, monkeypatch, exit_delay=exit_delay)
    chunks = [chunk async for chunk in backend.stream_spotify_uri("spotify:track:fixture")]
    assert b"".join(chunks) == b"ogg-fixture"
    assert processes[0].returncode == 0


async def test_nonzero_exit_after_stdout_eof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An actual failed exit must remain an audio error with its real status."""
    backend, processes = _backend(tmp_path, monkeypatch, exit_code=7)
    with pytest.raises(AudioError, match="exit code 7"):
        async for _chunk in backend.stream_spotify_uri("spotify:track:fixture"):
            pass
    assert processes[0].returncode == 7


async def test_hung_exit_is_bounded_and_reaped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A child keeping alive after EOF must fail within the bound and be cleaned up."""
    backend, processes = _backend(tmp_path, monkeypatch, exit_delay=60, close_stderr=True)
    async with asyncio.timeout(15):
        with pytest.raises(AudioError, match="did not exit after audio ended"):
            async for _chunk in backend.stream_spotify_uri("spotify:track:fixture"):
                pass
    assert processes[0].returncode is not None


async def test_cancellation_during_exit_wait_reaps_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling the consumer while awaiting termination must not leak its child."""
    backend, processes = _backend(tmp_path, monkeypatch, exit_delay=60, close_stderr=True)
    stream = backend.stream_spotify_uri("spotify:track:fixture")
    assert await anext(stream) == b"ogg-fixture"
    task = asyncio.create_task(anext(stream))
    await asyncio.sleep(0.05)
    task.cancel()
    async with asyncio.timeout(15):
        with pytest.raises(asyncio.CancelledError):
            await task
    assert processes[0].returncode is not None


async def test_fatal_decoder_error_still_terminates_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A fatal decoder report must still terminate playback and propagate failure."""
    backend, processes = _backend(
        tmp_path, monkeypatch, exit_delay=60, stderr="ERROR unable to read audio\n"
    )
    async with asyncio.timeout(15):
        with pytest.raises(AudioError, match="exit code -15"):
            async for _chunk in backend.stream_spotify_uri("spotify:track:fixture"):
                pass
    assert processes[0].returncode == -15


def _backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    exit_delay: float = 0.2,
    exit_code: int = 0,
    close_stderr: bool = False,
    stderr: str = "",
) -> tuple[LibrespotBackend, list[AsyncProcess]]:
    """Route the real adapter/process helper through a harmless fixture child."""
    provider = MagicMock()
    provider.cache_dir = str(tmp_path)
    backend = LibrespotBackend(cast("SpotifyProvider", provider))
    backend._librespot_bin = sys.executable
    child = (
        "import os,time,sys;os.write(1,b'ogg-fixture');os.close(1);"
        f"os.write(2,{stderr.encode()!r});"
        + ("os.close(2);" if close_stderr else "")
        + f"time.sleep({exit_delay});sys.exit({exit_code})"
    )
    processes: list[AsyncProcess] = []

    def spawn(_args: list[str], **kwargs: Any) -> AsyncProcess:
        process = AsyncProcess([sys.executable, "-c", child], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("music_assistant.providers.spotify.backends.librespot.AsyncProcess", spawn)
    return backend, processes
