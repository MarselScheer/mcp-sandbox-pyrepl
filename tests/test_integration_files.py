"""Integration tests for file I/O within the container via /data volume.

Validates that file operations work correctly through the container's /data
named volume. All file I/O goes through docker exec since /data is managed
by Docker as a named volume (no host-side bind mount).
"""

from __future__ import annotations

from typing import Any

import docker
import pytest

from session_manager import SessionManager


def _exec(container_id: str, code: str) -> dict[str, Any]:
    """Execute Python code inside the container and return result."""
    docker_client = docker.from_env()
    result = docker_client.containers.get(container_id).exec_run(
        ["python3", "-c", code]
    )
    output = (
        result.output.decode("utf-8")
        if isinstance(result.output, bytes)
        else result.output
    )
    return {"exit_code": result.exit_code, "output": output}


@pytest.mark.integration
class TestFileIO:
    """File I/O in the container's /data named volume.

    Uses a class-scoped container to eliminate per-test container
    startup overhead. All tests share one container since they
    do not test session isolation.
    """

    def test_host_writes_file_container_reads(
        self,
        class_container: dict,
    ) -> None:
        """Write a file to /data via docker exec, container reads it."""
        manager = class_container["manager"]
        session_id = class_container["session_id"]
        container_id = class_container["container_id"]

        # Write a file via the SessionManager's write_file (docker exec)
        result = manager.write_file(
            session_id, "hello.txt", "Hello from the host!"
        )
        assert result.get("success"), f"write_file failed: {result}"

        # Verify the container can read it via docker exec
        read_result = _exec(
            container_id,
            "print(open('/data/hello.txt').read())",
        )
        assert read_result["exit_code"] == 0
        assert "Hello from the host!" in read_result["output"]

    def test_container_writes_file_host_reads(
        self,
        class_container: dict,
    ) -> None:
        """Container writes a file to /data/, verify via docker exec."""
        container_id = class_container["container_id"]
        session_id = class_container["session_id"]
        manager = class_container["manager"]

        # Write a file inside the container's /data/ directory
        write_result = _exec(
            container_id,
            "open('/data/output.txt', 'w').write('Hello from container!')",
        )
        assert write_result["exit_code"] == 0

        # Read the file via the SessionManager's read_file (docker exec)
        read_result = manager.read_file(session_id, "output.txt")
        assert "error" not in read_result, f"read_file failed: {read_result}"
        assert read_result["content"] == "Hello from container!"

    def test_list_files(
        self,
        class_container: dict,
    ) -> None:
        """Listing files in /data via docker exec."""
        container_id = class_container["container_id"]
        session_id = class_container["session_id"]
        manager = class_container["manager"]

        # Write a file via docker exec and verify it shows up via list_files
        write_result = _exec(
            container_id,
            "open('/data/test_list.txt', 'w').write('list me')",
        )
        assert write_result["exit_code"] == 0

        # List files via the SessionManager's list_files (docker exec)
        list_result = manager.list_files(session_id)
        assert "error" not in list_result, f"list_files failed: {list_result}"
        filenames = [e["name"] for e in list_result["files"]]
        assert "test_list.txt" in filenames
