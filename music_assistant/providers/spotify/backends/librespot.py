"""Librespot playback backend for the Spotify music provider."""

from __future__ import annotations

import asyncio
import os
from collections import deque
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING

from music_assistant_models.enums import ContentType
from music_assistant_models.errors import AudioError, LoginFailed
from music_assistant_models.media_items import AudioFormat

from music_assistant.constants import VERBOSE_LOG_LEVEL
from music_assistant.helpers.process import AsyncProcess
from music_assistant.providers.spotify.constants import (
    CONF_LIBRESPOT_CREDENTIALS,
    CREDENTIALS_FILE,
)
from music_assistant.providers.spotify.helpers import get_librespot_binary

from .base import SpotifyPlaybackBackend

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from music_assistant_models.enums import MediaType
    from music_assistant_models.streamdetails import StreamDetails

    from music_assistant.helpers.json import SerializableType


class _TransientStartupError(AudioError):
    """A source transport failure before any audio was yielded."""


class LibrespotBackend(SpotifyPlaybackBackend):
    """
    Fetches Spotify audio through the bundled librespot fork.

    One short-lived ``librespot --single-track`` process per item, yielding the
    original Ogg Vorbis stream (passthrough, no decode).
    """

    _librespot_bin: str | None = None

    def source_audio_format(self, media_type: MediaType) -> AudioFormat:
        """
        Return the format of the Spotify source.

        librespot hands over Spotify's own file untouched, so this describes the
        delivered bytes as well. It fetches the highest quality the account is
        entitled to, which for a Premium account is 320 kbps Ogg Vorbis.

        :param media_type: Unused: librespot fetches every item the same way.
        """
        return AudioFormat(
            content_type=ContentType.OGG,
            codec_type=ContentType.VORBIS,
            sample_rate=44100,
            bit_depth=16,
            channels=2,
            bit_rate=320,
        )

    async def setup(self) -> None:
        """
        Validate the librespot binary and install the stored playback credential.

        :raises LoginFailed: When no playback credential is configured, which requires
            the user to re-run the setup flow.
        """
        # a missing binary is a platform problem, not an auth problem: let the
        # RuntimeError surface as a plain setup failure
        self._librespot_bin = await get_librespot_binary()
        credentials = self.provider.get_setup_value(CONF_LIBRESPOT_CREDENTIALS)
        if not credentials:
            # Spotify's login5 refuses credentials minted with any client id other than the one
            # librespot presents, so installs predating the dedicated playback credential (and
            # anything cached from before) cannot stream and must authorize playback again.
            raise LoginFailed(
                "Spotify playback authorization required",
                translation_key="playback_auth_required",
                translation_owner="provider.spotify",
            )
        await asyncio.to_thread(
            self._write_librespot_credentials, self.provider.cache_dir, str(credentials)
        )

    async def stream_spotify_uri(
        self,
        spotify_uri: str,
        seek_position: int = 0,
        *,
        streamdetails: StreamDetails | None = None,
        continuation: bool = False,
    ) -> AsyncGenerator[bytes]:
        """
        Yield the Ogg Vorbis audio for one Spotify URI.

        :param spotify_uri: Canonical Spotify URI (``spotify:track:<id>`` or
            ``spotify:episode:<id>``).
        :param seek_position: Position in seconds to start from.
        :param streamdetails: Unused: every item is fetched on its own.
        :param continuation: Unused: every item is fetched on its own.
        """
        for attempt in range(2):
            try:
                async with aclosing(self._stream_once(spotify_uri, seek_position)) as stream:
                    async for chunk in stream:
                        yield chunk
                return
            except _TransientStartupError:
                if attempt:
                    raise
                self.logger.warning("Transient Spotify startup failure; retrying once before audio")
                await asyncio.sleep(1)

    async def get_diagnostics(self) -> dict[str, SerializableType]:
        """Return diagnostic details about the backend."""
        return {"librespot_available": self._librespot_bin is not None}

    async def _stream_once(self, spotify_uri: str, seek_position: int) -> AsyncGenerator[bytes]:
        """Yield one source attempt, preserving fatal errors and process cleanup."""
        # librespot's --single-track parser wants its own spotify://type:id form
        librespot_uri = spotify_uri.replace("spotify:", "spotify://", 1)
        self.logger.log(VERBOSE_LOG_LEVEL, "Start streaming %s using librespot", spotify_uri)
        if not self._librespot_bin:
            raise AudioError("Spotify playback could not be set up")

        args = [
            self._librespot_bin,
            "--cache",
            self.provider.cache_dir,
            "--disable-audio-cache",
            "--passthrough",
            "--bitrate",
            "320",
            "--backend",
            "pipe",
            "--single-track",
            librespot_uri,
            "--disable-discovery",
            "--dither",
            "none",
        ]
        if seek_position:
            args += ["--start-position", str(int(seek_position))]

        async with AsyncProcess(
            args,
            stdout=True,
            stderr=True,
            name="librespot",
        ) as librespot_proc:
            log_history: deque[str] = deque(maxlen=10)
            yielded_audio = False
            transient_failure = False
            fatal_failure = False
            invalid_credentials = False
            logger = self.logger
            provider = self.provider

            async def log_librespot_output() -> None:
                """Log librespot's output, and end the process when it reports a fatal error."""
                nonlocal transient_failure, invalid_credentials, fatal_failure
                async for line in librespot_proc.iter_stderr():
                    log_history.append(line)
                    invalid_credentials |= "INVALID_CREDENTIALS" in line
                    transient_failure |= (
                        "Passthrough Decoder Error: I/O error" in line
                        or "Audio key response timeout" in line
                    )
                    if "ERROR" in line or "WARNING" in line:
                        logger.warning("[librespot] %s", line)
                        if "INVALID_CREDENTIALS" in line and provider.available:
                            # Spotify refused the stored playback credential: surface this as an
                            # auth failure so the provider asks for re-authorization instead of
                            # reporting every track as unplayable. The availability check keeps
                            # concurrent/queued streams from each scheduling their own unload.
                            provider.unload_with_error(
                                LoginFailed(
                                    "Spotify playback authorization required",
                                    translation_key="playback_auth_required",
                                    translation_owner="provider.spotify",
                                )
                            )
                        if "unable to" in line.lower() or "skipping" in line.lower():
                            fatal_failure = True
                            # if librespot reports a fatal error (e.g. unable to load
                            # or read audio), terminate the process to avoid hanging
                            # indefinitely as it won't produce any audio output.
                            # NOTE: we terminate the underlying process directly instead
                            # of calling close() because this task IS the stderr reader
                            # and close() would try to await itself.
                            if librespot_proc.proc and librespot_proc.proc.returncode is None:
                                librespot_proc.proc.terminate()
                            return
                    else:
                        logger.log(VERBOSE_LOG_LEVEL, "[librespot] %s", line)

            stderr_reader = asyncio.create_task(log_librespot_output())
            librespot_proc.attach_stderr_reader(stderr_reader)
            # yield from librespot's stdout
            async for chunk in librespot_proc.iter_chunked():
                yielded_audio |= bool(chunk)
                yield chunk

            # Pipe EOF can precede process exit; a pending status is not a playback failure.
            if librespot_proc.returncode is None:
                assert librespot_proc.proc is not None
                try:
                    await asyncio.wait_for(librespot_proc.proc.wait(), timeout=5)
                except TimeoutError as err:
                    raise AudioError(
                        "Spotify playback process did not exit after audio ended"
                    ) from err

            # A fatal diagnostic can race with a successful single-track process exit.
            try:
                await asyncio.wait_for(stderr_reader, timeout=5)
            except TimeoutError as err:
                raise AudioError("Spotify playback diagnostics did not finish after exit") from err

            if librespot_proc.returncode != 0 or fatal_failure:
                error_type = (
                    _TransientStartupError
                    if transient_failure and not yielded_audio and not invalid_credentials
                    else AudioError
                )
                raise error_type(
                    f"Spotify stopped playing this track unexpectedly "
                    f"(exit code {librespot_proc.returncode})"
                )

    @staticmethod
    def _write_librespot_credentials(cache_dir: str, credentials: str) -> None:
        """Write the stored credential to librespot's cache, replacing any stale one."""
        Path(cache_dir).mkdir(parents=True, exist_ok=True)
        credentials_file = os.path.join(cache_dir, CREDENTIALS_FILE)
        with open(credentials_file, "w", encoding="utf-8") as fileobj:
            fileobj.write(credentials)
