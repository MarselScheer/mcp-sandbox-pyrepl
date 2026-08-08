## 1. Spike — Verify attach_socket behavior

- [x] 1.1 Write a standalone script that creates a container with the sandbox-base image, calls `attach_socket(params={stdout: 1, stream: 1})`, reads from the socket, and logs whether 8-byte Docker frame headers appear. Document the finding in a comment or the design doc.

## 2. Source adapter — Rewrite `container_rpc` in `src/docker_adapter.py`

- [x] 2.1 Remove the `import time` and the `time.sleep(0.3)` call from `container_rpc()`
- [x] 2.2 Implement the new `container_rpc()`: open a stdout-only attach socket (`container.attach_socket({stdout: 1, stream: 1})`), create a `_DockerFrameReader` for reading frames, write the request to stdin via `docker exec sh -c echo '...' > /proc/1/fd/0`, read the response via `_DockerFrameReader`, close the socket
- [x] 2.3 Add a fallback: if the socket read times out, check `container.logs()` as a safety net before raising `ConnectionError`
- [x] 2.4 Handle edge cases in the read loop: skip non-JSON lines, return the first valid JSON object from the stream

## 3. Test adapter — Mirror changes in `tests/docker_adapter.py`

- [x] 3.1 Apply the same `container_rpc()` changes to the test copy of `RealDockerClient` in `tests/docker_adapter.py`
- [x] 3.2 Verify the test copy stays in sync with the source copy — if the source interface changes (e.g., error types), update the test copy accordingly

## 4. Unit tests — Update `FakeDockerClient` in `tests/test_session_manager.py`

- [x] 4.1 Verify that `FakeDockerClient.container_rpc()` still satisfies the `DockerClient` Protocol — no interface changes expected, but confirm
- [x] 4.2 Update the fake if error propagation semantics changed (new error types, etc.)

## 5. Integration tests — Verify end-to-end with real Docker

- [x] 5.1 Run `test_entrypoint_server.py` tests to confirm the entrypoint still works correctly with stdin/stdout
- [x] 5.2 Run `test_integration_execution.py` tests to confirm code execution works end-to-end with the new `container_rpc()`
- [x] 5.3 Run `test_integration_session.py` tests to confirm session lifecycle (create/shutdown) still works
- [x] 5.4 Run the full test suite: `python -m pytest tests/ -v` and confirm no regressions