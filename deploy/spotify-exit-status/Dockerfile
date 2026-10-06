# Build only on a host retaining the verified original 2.10.4 image.
FROM local/unraid-preserved/music-assistant:20261004
ARG SOURCE_REVISION
LABEL org.opencontainers.image.source="https://github.com/MarceloGza/music-assistant-server" \
      io.marchgg.music-assistant.hotfix="spotify-exit-status" \
      io.marchgg.music-assistant.hotfix.revision="${SOURCE_REVISION}"
RUN python -c "import hashlib,pathlib; p=pathlib.Path('/app/venv/lib/python3.14/site-packages/music_assistant/providers/spotify/backends/librespot.py'); assert hashlib.sha256(p.read_bytes()).hexdigest() == 'f60463a5408cd7631a7be6e7f80bcf8ee46dd9f4e94c14eae7d4f550534595f0'"
COPY music_assistant/providers/spotify/backends/librespot.py /app/venv/lib/python3.14/site-packages/music_assistant/providers/spotify/backends/librespot.py
RUN python -m py_compile /app/venv/lib/python3.14/site-packages/music_assistant/providers/spotify/backends/librespot.py
