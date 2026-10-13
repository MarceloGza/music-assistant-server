"""Transient startup recovery through the real adapter and harmless children."""

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
    from collections.abc import AsyncGenerator
    from pathlib import Path

    from music_assistant.providers.spotify.provider import SpotifyProvider


async def test_startup_io_failure_recovers_without_duplicate_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The captured no-output I/O failure gets one fresh attempt at the same seek."""
    provider = MagicMock()
    provider.cache_dir = str(tmp_path)
    provider.available = False
    backend = LibrespotBackend(cast("SpotifyProvider", provider))
    backend._librespot_bin = sys.executable
    processes: list[AsyncProcess] = []
    arguments: list[list[str]] = []
    failure = (
        "import os,time;os.write(2,b'ERROR Unable to read audio file: "
        "Passthrough Decoder Error: I/O error\\n');time.sleep(60)"
    )
    success = "import os;os.write(1,b'ogg-fixture')"

    def spawn(args: list[str], **kwargs: Any) -> AsyncProcess:
        arguments.append(args)
        process = AsyncProcess(
            [sys.executable, "-c", failure if not processes else success], **kwargs
        )
        processes.append(process)
        return process

    monkeypatch.setattr("music_assistant.providers.spotify.backends.librespot.AsyncProcess", spawn)
    chunks = [chunk async for chunk in backend.stream_spotify_uri("spotify:track:fixture", 30)]
    assert b"".join(chunks) == b"ogg-fixture"
    assert len(processes) == 2
    assert arguments[0] == arguments[1]
    assert arguments[0][-2:] == ["--start-position", "30"]
    assert [p.returncode for p in processes] == [-15, 0]


@pytest.mark.parametrize(
    ("stderr", "payload", "exit_code", "expected_attempts"),
    [
        ("ERROR Unable to read audio file: Passthrough Decoder Error: I/O error\n", b"", 7, 2),
        ("ERROR Audio key response timeout\n", b"", 7, 2),
        (
            "ERROR Unable to read audio file: Passthrough Decoder Error: I/O error\n",
            b"partial",
            7,
            1,
        ),
        ("ERROR INVALID_CREDENTIALS\nERROR Passthrough Decoder Error: I/O error\n", b"", 7, 1),
        ("ERROR unrelated failure\n", b"", 7, 1),
        ('ERROR Skipping to next track: PassthroughDecoder("I/O error")\n', b"partial", 0, 1),
        ("", b"", 7, 1),
    ],
)
async def test_retry_is_bounded_and_preserves_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stderr: str,
    payload: bytes,
    exit_code: int,
    expected_attempts: int,
) -> None:
    """Only recognized no-output transport failures get one retry, then fail visibly."""
    provider = MagicMock()
    provider.cache_dir = str(tmp_path)
    provider.available = True
    backend = LibrespotBackend(cast("SpotifyProvider", provider))
    backend._librespot_bin = sys.executable
    processes: list[AsyncProcess] = []
    child = (
        f"import os,time,sys;os.write(1,{payload!r});time.sleep(0.05);"
        f"os.write(2,{stderr.encode()!r});sys.exit({exit_code})"
    )

    def spawn(_args: list[str], **kwargs: Any) -> AsyncProcess:
        process = AsyncProcess([sys.executable, "-c", child], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("music_assistant.providers.spotify.backends.librespot.AsyncProcess", spawn)
    received = bytearray()
    with pytest.raises(AudioError):  # noqa: PT012 - retain bytes yielded before failure
        async for chunk in backend.stream_spotify_uri("spotify:track:fixture"):
            received.extend(chunk)
    assert len(processes) == expected_attempts
    assert bytes(received) == payload
    assert all(p.returncode is not None for p in processes)
    if "INVALID_CREDENTIALS" in stderr:
        provider.unload_with_error.assert_called_once()


async def test_fatal_packet_report_is_not_success_when_child_already_exited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The captured exit-zero packet error must not become clean stream completion."""
    provider = MagicMock()
    provider.cache_dir = str(tmp_path)
    backend = LibrespotBackend(cast("SpotifyProvider", provider))
    backend._librespot_bin = sys.executable

    class ExitedProcess(AsyncProcess):
        async def iter_stderr(self) -> AsyncGenerator[str]:
            """Read diagnostics only once the harmless child has exited."""
            assert self.proc is not None
            await self.proc.wait()
            async for line in super().iter_stderr():
                yield line

    child = (
        "import os;os.write(1,b'partial');os.write(2,b'ERROR Skipping to next track, "
        'unable to get next packet: PassthroughDecoder("I/O error")\\n\')'
    )

    def spawn(_args: list[str], **kwargs: Any) -> AsyncProcess:
        return ExitedProcess([sys.executable, "-c", child], **kwargs)

    monkeypatch.setattr("music_assistant.providers.spotify.backends.librespot.AsyncProcess", spawn)
    with pytest.raises(AudioError):
        _ = [chunk async for chunk in backend.stream_spotify_uri("spotify:track:fixture")]


async def test_cancellation_during_retry_backoff_does_not_spawn_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling the delayed retry propagates cancellation and leaves no child."""
    provider = MagicMock()
    provider.cache_dir = str(tmp_path)
    provider.available = False
    retry_announced = asyncio.Event()

    def warning(message: str, *_args: Any) -> None:
        if "retrying once" in message:
            retry_announced.set()

    provider.logger.warning.side_effect = warning
    backend = LibrespotBackend(cast("SpotifyProvider", provider))
    backend._librespot_bin = sys.executable
    processes: list[AsyncProcess] = []
    child = "import os;os.write(2,b'ERROR Unable to read audio file: Passthrough Decoder Error: I/O error\\n')"

    def spawn(_args: list[str], **kwargs: Any) -> AsyncProcess:
        process = AsyncProcess([sys.executable, "-c", child], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr("music_assistant.providers.spotify.backends.librespot.AsyncProcess", spawn)
    stream = backend.stream_spotify_uri("spotify:track:fixture")
    task = asyncio.create_task(anext(stream))
    async with asyncio.timeout(10):
        await retry_announced.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(processes) == 1
    assert processes[0].returncode is not None


async def test_consumer_close_reaps_inner_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Closing the public iterator must synchronously close its inner child."""
    provider = MagicMock()
    provider.cache_dir = str(tmp_path)
    backend = LibrespotBackend(cast("SpotifyProvider", provider))
    backend._librespot_bin = sys.executable
    processes: list[AsyncProcess] = []

    def spawn(_args: list[str], **kwargs: Any) -> AsyncProcess:
        process = AsyncProcess(
            [
                sys.executable,
                "-c",
                "import os,time;os.write(1,b'partial');os.close(1);os.close(2);time.sleep(60)",
            ],
            **kwargs,
        )
        processes.append(process)
        return process

    monkeypatch.setattr("music_assistant.providers.spotify.backends.librespot.AsyncProcess", spawn)
    stream = backend.stream_spotify_uri("spotify:track:fixture")
    assert await anext(stream) == b"partial"
    async with asyncio.timeout(15):
        await stream.aclose()
    assert processes[0].returncode is not None
