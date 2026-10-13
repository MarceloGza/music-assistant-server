# Spotify transient startup and stderr completion hotfix

This overlay is based on personal `c7eecf09ce3315de065013bfd9214333e7cc35a6`
and the actual deployed 2.10.4 image
`sha256:3ca3417255387185c6491459f997c4a9028c58351752c905eff4e35467f464c8`.
Verify that the Dockerfile base tag still resolves to this ID before building.
No bundled engine, dependency, queue, speaker, provider configuration, authentication
or schema changes are included. The previous five-second process-exit repair stays intact.

The adapter permits one delayed fresh attempt only for a recorded I/O/audio-key timeout
before any source bytes are yielded. Partial streams, invalid credentials, generic
failures and cancellation are not replayed. Both attempts preserve URI and seek.
The inner generator is closed synchronously. The process helper retains buffered
stderr after child exit, and the adapter awaits that reader before declaring success:
a fatal packet diagnostic is not a successful stream just because exit status is zero.

This does not solve upstream CDN/key-service availability, persistent failure, or
midstream source delivery. Errors remain visible; it does not claim physical audio
acceptance, House Connect recovery, speaker transport or AirPlay transition repair.

Validation uses real harmless children and actual bundled-binary warm-cache streams
into an ffmpeg null sink. Provider audio is never retained. Run:

```
python -m pytest tests/providers/spotify tests/helpers tests/controllers/streams -q
SKIP=no-commit-to-branch pre-commit run --all-files
```

Use a nonroot isolated validation runtime for filesystem permission controls.
A preexisting installed environment can be selected with `UV_PROJECT_ENVIRONMENT`
and `UV_NO_SYNC=1`; do not upgrade production dependencies for test setup.

Deployment requires exact before-state, protected consistent settings/DB-family backup,
isolated integrity/restore verification and guarded rollback to the retained image.
Only the MA Compose image may change. Immediately before a restart verify all household
queues, satellite media players and assist sessions idle through authenticated native
state; busy or unknown defers deployment under the latest continuation instruction.
Check provider/player configuration and unrelated
fleet identities before/after; preserve HA/frontend and Jarvis. Actual source duration
and authenticated HA-MA consumer readback are separate from HTTP health.
