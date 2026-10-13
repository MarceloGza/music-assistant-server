# Same deployed 2.10.4 base; no dependency, binary or application upgrade.
FROM local/music-assistant:2.10.4-spotify-exit-c7eecf09
ARG SOURCE_REVISION
LABEL org.opencontainers.image.source="https://github.com/MarceloGza/music-assistant-server" \
      io.marchgg.music-assistant.hotfix="spotify-startup-retry-stderr" \
      io.marchgg.music-assistant.hotfix.revision="${SOURCE_REVISION}"
RUN python -c "import hashlib,pathlib; p=pathlib.Path('/app/venv/lib/python3.14/site-packages/music_assistant'); assert hashlib.sha256((p/'providers/spotify/backends/librespot.py').read_bytes()).hexdigest()=='4828c4e9297d454b3080c3a9278d0fe7193b0aec852aa6a87d656f0a2bb6b3e8'; assert hashlib.sha256((p/'helpers/process.py').read_bytes()).hexdigest()=='25be8a28fcbb82d0ef9bea46d8bea0605af5b5016107a62ca269b2d3ba02f933'"
COPY music_assistant/providers/spotify/backends/librespot.py /app/venv/lib/python3.14/site-packages/music_assistant/providers/spotify/backends/librespot.py
COPY music_assistant/helpers/process.py /app/venv/lib/python3.14/site-packages/music_assistant/helpers/process.py
RUN python -m py_compile /app/venv/lib/python3.14/site-packages/music_assistant/providers/spotify/backends/librespot.py /app/venv/lib/python3.14/site-packages/music_assistant/helpers/process.py
