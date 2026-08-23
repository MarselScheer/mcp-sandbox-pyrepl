## Why

Integration tests leave behind Docker containers and named Docker volumes after completion. Containers are removed when `end_session()` is explicitly called, but some tests create sessions via fixtures that don't always invoke `end_session()`, and the auto-generated named Docker volumes (`vol_<uuid>`) for `/data` and `/session` are never cleaned up — they accumulate with each test run.

The spec for session lifecycle already requires cleanup, but the implementation (specifically `RealDockerClient.container_remove()`) only removes the container, not the volumes. The test fixtures also lack defensive cleanup of leftover sessions and temp directories.

## What Changes

- **`RealDockerClient.container_remove()`**: Inspect the container's mounts before removal, collect auto-generated named volume names (`vol_<uuid>`), remove the container, then remove each volume.
- **`conftest.py` `session_manager` fixture**: Convert from function-return to generator-yield pattern. On teardown: iterate all remaining sessions via `list_sessions()` and call `end_session()` for each, then remove the temp data directory via `shutil.rmtree`.
- **`conftest.py` `class_container` fixture**: Also clean up the temp data directory on teardown.

## Capabilities

No spec-level behavior changes. The existing session-lifecycle spec already states "AND cleans up the session's /data directory" — this change just makes the implementation actually do it.

- `skip_specs: true` set in `.openspec.yaml`

## Impact

- **`src/docker_adapter.py`**: `container_remove()` — add volume inspection and cleanup.
- **`tests/integration/conftest.py`**: `session_manager` fixture — generator-based teardown with session cleanup and temp dir removal. `class_container` fixture — temp dir cleanup.