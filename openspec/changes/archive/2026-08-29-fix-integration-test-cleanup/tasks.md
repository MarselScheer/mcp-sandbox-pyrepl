## 1. Volume cleanup in RealDockerClient

- [x] 1.1 Update `RealDockerClient.container_remove()` to inspect container mounts before removal, collect named volume names (`Type == "volume"` with a `Name`), then remove each volume after the container is removed, wrapped in `contextlib.suppress(Exception)`

## 2. Fixture cleanup in conftest.py

- [x] 2.1 Convert `session_manager` fixture from function-return to generator-yield pattern: after `yield manager`, iterate `manager.list_sessions()` and call `manager.end_session(sid)` for each remaining session, then remove the temp `data_dir` via `shutil.rmtree(path)` — add `import shutil` at the top of the file
- [x] 2.2 Update `class_container` fixture to also clean up the temp `data_dir` via `shutil.rmtree(path)` after the session teardown

## 3. Write failing tests first (outside-in)

- [x] 3.1 Write integration test that creates a session via `session_manager`, ends it, then verifies no named Docker volumes (`vol_<uuid>`) remain — this test will fail before the fix
- [x] 3.2 Write integration test that creates a session via `session_manager` fixture (without explicit `end_session`), completes the test, then verifies the container and volumes are cleaned up by the fixture teardown

## 4. Verify

- [x] 4.1 Run integration tests (`make test-integration` or equivalent) and confirm all pass
- [x] 4.2 Run `docker volume ls` before and after tests to confirm no named volumes leak (`vol_<uuid>`)