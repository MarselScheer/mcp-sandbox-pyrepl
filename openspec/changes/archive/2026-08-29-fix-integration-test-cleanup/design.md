## Context

See `proposal.md` for motivation. Current state:

- `RealDockerClient.containers_create()` creates named Docker volumes (`vol_<uuid>`) for `/data` and `/session` when `host_path` is empty. These are auto-generated names, not anonymous volumes.
- `RealDockerClient.container_remove()` only calls `container.remove(force=force)` — Docker's `v=True` flag (`remove(force=force, v=True)`) only cleans up **anonymous** volumes, not named ones.
- The `session_manager` fixture in `conftest.py` creates a `SessionManager` and returns it directly (function-return pattern, not a generator). No teardown logic exists.
- Some integration tests create sessions via `session_manager.create_session()` inside test methods without calling `end_session()` in a `finally` block — these sessions leak.
- The `class_container` fixture uses the generator-yield pattern, so sessions are cleaned up, but the temp `data_dir` is never removed.

## Goals / Non-Goals

**Goals:**
- Named Docker volumes (`vol_<uuid>`) are removed when their owning container is removed via `RealDockerClient.container_remove()`.
- The `session_manager` fixture in `conftest.py` cleans up all remaining sessions on teardown (defensive — catches any test that forgets to call `end_session()`).
- The temp `data_dir` directories created by `session_manager` and `class_container` fixtures are removed on teardown.

**Non-Goals:**
- No changes to the cleanup logic in `SessionManager.end_session()` itself — it already calls `container_remove()`. The fix is at the adapter layer.
- No changes to individual test methods — the fixture-level cleanup handles any leakage.
- No production-side session tracking outside of tests (e.g., production `SessionManager` already calls `end_session()`).

## Decisions

### Decision 1: Volume cleanup in `container_remove()`, not in `end_session()`

**Choice:** Inspect the container's `Mounts` in `container_remove()` and remove named volumes after the container is removed.

**Rationale:** The observation of which volumes belong to the container can only happen before the container is removed (Docker API returns no mounts for a removed container). `SessionManager._create_container()` creates the volumes — the naming convention `vol_<uuid>` is local to `RealDockerClient`. Cleaning up in `container_remove()` keeps the cleanup co-located with the creation, which is the correct abstraction boundary.

**Alternatives considered:**
- Track volumes in `SessionManager._sessions` metadata — rejected because it would require the session manager to know about Docker volume implementation details, violating the DockerClient Protocol abstraction.
- Pass `v=True` to `container.remove()` — rejected because Docker's `v` flag only handles anonymous volumes, not named ones.

### Decision 2: Inspect all mounts, not just known volume names

**Choice:** Iterate all `Mounts` entries with `Type == "volume"` and remove any that have a `Name`.

**Rationale:** This handles not just `/data` and `/session` but any future volumes added to `_create_container()`. It's defensive: if someone adds a third volume in `_create_container()`, it gets cleaned up automatically.

**Alternatives considered:**
- Track the volume names explicitly — rejected because it couples `container_remove()` to `_create_container()`'s internal structure.

### Decision 3: Generator-based fixture teardown for `session_manager`

**Choice:** Convert `session_manager` fixture from `-> SessionManager` return pattern to `Generator[SessionManager, None, None]` yield pattern, with teardown logic after `yield`.

**Rationale:** Pytest's fixture finalization is the right mechanism for cleanup. The generator-yield pattern runs teardown code even if a test raises an exception. The `class_container` fixture already uses this pattern, so this is consistent.

**`session_manager` teardown:**
1. Iterate `manager.list_sessions()` and call `manager.end_session(sid)` for each.
2. Remove the `data_dir` via `shutil.rmtree(path)`.

**`class_container` teardown:** Add `shutil.rmtree(path)` after the existing `manager.end_session()` call.

### Decision 4: `contextlib.suppress` for volume removal

**Choice:** Wrap each `vol.remove()` call in `contextlib.suppress(Exception)`.

**Rationale:** A volume that fails to remove (e.g., in use by another container) should not prevent other volumes from being cleaned up. This mirrors the existing pattern in `SessionManager.end_session()` which uses `contextlib.suppress(Exception)` for container stop/remove.

## Risks / Trade-offs

- **[Risk] Volume removal failure on parallel test runs**: If two tests share a container (via `class_container`), volumes may still be in use. → Mitigation: `contextlib.suppress(Exception)` — the volume removal silently fails, and the volume will be cleaned up when the second container is removed.
- **[Risk] Volume name collision**: Unlikely with UUID-based names but theoretically possible. → Mitigation: UUID hex with 12 chars provides ~2^48 collision space — negligible risk.
- **[Trade-off] Inspecting mounts adds a Docker API call**: `container.attrs` is already cached on the `Container` object after `container_get()`, so this is a dict lookup with no extra network call.