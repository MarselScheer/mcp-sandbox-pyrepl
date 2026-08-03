"""Real Docker Client Adapter for integration tests.

Wraps the docker-py SDK to satisfy the SessionManager's DockerClient Protocol.
Also provides a container_rpc method for bidirectional JSON-RPC communication
with the container's entrypoint via docker exec.
"""

from __future__ import annotations

import io
import json
import socket
import uuid
from typing import Any

from docker import DockerClient as _DockerClient
from docker.models.containers import Container


class RealDockerClient:
    """Adapter that wraps the docker-py SDK to satisfy the DockerClient Protocol.

    Maps the SessionManager's Protocol methods to the real docker-py API.
    """

    def __init__(self, docker_client: _DockerClient) -> None:
        self._client = docker_client

    def containers_create(
        self,
        image: str,
        command: str | None = None,
        name: str | None = None,
        user: str | None = None,
        read_only: bool = False,
        cap_drop: list[str] | None = None,
        volumes: list[dict[str, Any]] | None = None,
        network: str | None = None,
        detach: bool = True,
        tmpfs: dict[str, str] | None = None,
    ) -> Container:
        """Create a container via the docker-py SDK.

        Returns a Container object (which has .id, .short_id, etc.).
        """
        docker_volumes: dict[str, dict[str, Any]] = {}
        for vol in volumes or []:
            host_path = vol.get("host_path", "")
            container_path = vol.get("container_path", "")
            mode = vol.get("mode", "rw")
            if host_path:
                docker_volumes[host_path] = {
                    "bind": container_path,
                    "mode": mode,
                }
            else:
                # Use an auto-generated named volume so Docker copies the
                # image's contents (e.g. the pre-built venv) into the volume.
                vol_name = f"vol_{uuid.uuid4().hex[:12]}"
                docker_volumes[vol_name] = {
                    "bind": container_path,
                    "mode": mode,
                }

        created = self._client.containers.create(
            image=image,
            command=command,
            name=name,
            user=user,
            read_only=read_only,
            cap_drop=cap_drop,
            volumes=docker_volumes,
            tmpfs=tmpfs,
            network=network,
            detach=detach,
            stdin_open=True,
        )
        created.start()
        return created

    def container_get(self, container_id: str) -> Container:
        """Get a container by ID."""
        return self._client.containers.get(container_id)

    def container_remove(self, container_id: str, force: bool = False) -> None:
        """Remove a container."""
        container = self.container_get(container_id)
        container.remove(force=force)

    def container_stop(self, container_id: str) -> None:
        """Stop a container."""
        container = self.container_get(container_id)
        container.stop()

    def container_stdin(self, container_id: str) -> io.TextIOBase:
        """Get a writable stream to the container's stdin.

        Returns a file-like object supporting .write() and .flush().
        Uses docker-py's attach_socket to get a raw socket, then wraps
        it in a BufferedWriter for text I/O.
        """

        container = self.container_get(container_id)
        sock = container.attach_socket(
            params={"stdin": 1, "stream": 1, "logs": 1}
        )
        # attach_socket returns a socket-like object; wrap it for text I/O
        if isinstance(sock, socket.socket):
            return io.TextIOWrapper(
                io.BufferedWriter(sock.makefile("wb")),
                encoding="utf-8",
                line_buffering=True,
            )
        # Some versions return a file-like object directly
        if hasattr(sock, "write"):
            return sock  # type: ignore[return-value]
        msg = f"Unexpected stdin type: {type(sock)}"
        raise TypeError(msg)

    def container_exec_run(
        self, container_id: str, cmd: list[str]
    ) -> dict[str, Any]:
        """Run a command inside the container."""
        result = self._client.containers.get(container_id).exec_run(cmd)
        output = (
            result.output.decode("utf-8")
            if isinstance(result.output, bytes)
            else result.output
        )
        return {
            "exit_code": result.exit_code,
            "output": output,
        }

    def network_disconnect(
        self, container_id: str, network: str = "bridge"
    ) -> None:
        """Disconnect a container from a network."""
        net = self._client.networks.get(network)
        net.disconnect(container_id)

    def network_connect(
        self, container_id: str, network: str = "bridge"
    ) -> None:
        """Connect a container to a network."""
        net = self._client.networks.get(network)
        net.connect(container_id)

    def container_rpc(
        self, container_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the container's entrypoint and read the response.

        Sends a JSON-RPC request to the container's entrypoint and reads the response.

        Uses docker exec to write the request to the entrypoint's stdin
        (/proc/1/fd/0 — PID 1 is the entrypoint), then reads the response
        from container logs. The entrypoint writes JSON-RPC responses to
        stdout, which Docker captures and makes available via logs().

        This exercises the real JSON-RPC stdin/stdout path through the
        entrypoint, not a docker exec subprocess.
        """
        container = self._client.containers.get(container_id)
        request_json = json.dumps(request)

        # Write the JSON-RPC request directly to PID 1's stdin via docker exec.
        # /proc/1/fd/0 is the entrypoint process's stdin pipe — writing to it
        # is equivalent to writing to the container's attached stdin.
        write_script = (
            "import os\n"
            f"req = {json.dumps(request_json)}\n"
            "with open('/proc/1/fd/0', 'w') as f:\n"
            "    f.write(req + '\\n')\n"
            "    f.flush()\n"
            "    os.fsync(f.fileno())\n"
        )
        container.exec_run(["python3", "-c", write_script])

        # Give the entrypoint a moment to process and flush the response
        import time

        time.sleep(0.3)

        # Read the response from container logs.
        # The entrypoint writes JSON-RPC responses to stdout, which Docker
        # captures and returns via logs(). We look for the last JSON line.
        logs = container.logs(stdout=True, stderr=False, tail=5).decode("utf-8")

        for line in reversed(logs.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        msg = f"No JSON-RPC response found in container logs: {logs}"
        raise ConnectionError(msg)
