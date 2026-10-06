# Spotify process-exit hotfix for 2.10.4

This maintenance branch is intentionally based on upstream tag `2.10.4`, commit
`e30a4974ba951f38e21bea8d502af3b903df992c`. It is not an upstream dev merge or
an upgrade to a newer release.

The Spotify librespot adapter now waits up to five seconds for a still-running
child after audio stdout ends, before checking its exit status. Genuine errors,
fatal decoder termination, cancellation and subprocess cleanup remain active.
There are no queue, speaker, IP, Sendspin, schema, dependency or authentication
changes.

Validation:

```sh
python -m pytest tests/providers/spotify tests/helpers/test_process.py tests/controllers/streams -q
SKIP=no-commit-to-branch pre-commit run --all-files
```

The new tests use real harmless child processes, not real Spotify accounts or
household speakers. No provider audio is retained.

The image is a one-module overlay on the retained production image, preserving
all bundled binaries, dependencies and unrelated server code. Before building,
verify the retained base image ID is exactly:

`sha256:f8e25836cee73c7277f29a0dca804fbaa05f832a71616d15d50e337b04d4d0c8`

The build additionally rejects a mismatched original adapter hash.

```sh
docker build -f deploy/spotify-exit-status/Dockerfile \
  --build-arg SOURCE_REVISION="$(git rev-parse HEAD)" \
  -t local/music-assistant:2.10.4-spotify-exit-status .
```

Deploy only the Music Assistant service, after preserving its effective Compose
declarations, settings and a consistent database backup. Keep the original image
and root-owned guarded rollback inputs. This build is host-local; the local base
name is not a public registry image. Do not enable upstream release workflows or
update other home-automation services to install it.

Post-deployment acceptance must include exact image/source readback, provider
readiness, real streaming without storing audio, and queue observations. The
synthetic clean-EOF regression alone does not establish all audible playback or
network behavior. Existing decoder I/O errors and speaker reconnects are separate
problems; this fix does not suppress them.
