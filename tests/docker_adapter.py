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


class _DockerFrameReader:
    """Reads Docker-multiplexed frames, stripping 8-byte frame headers.

    Docker's ``attach_socket`` with ``params={stdout: 1, stream: 1}``
    still multiplexes output into frames with an 8-byte header:
      byte 0:    stream type (1=stdout, 2=stderr)
      bytes 1-3: padding (zeros)
      bytes 4-7: payload length (big-endian uint32)

    This reader strips those headers and returns only stdout payloads.
    """

    def __init__(self, raw: socket.SocketIO | socket.socket) -> None:
        self._raw = raw

    def read(self, timeout: float = 30.0) -> bytes:
        """Read all stdout frames until timeout or EOF.

        Sets a timeout on the underlying socket, then reads frames until
        no more data arrives within the timeout window.
        """
        # Set timeout on the underlying socket.
        # _sock is a private attribute of SocketIO; getattr falls back
        # if the caller passed a plain socket instead.
        raw = getattr(self._raw, '_sock', self._raw)
        if isinstance(raw, socket.socket):
            raw.settimeout(timeout)

        chunks: list[bytes] = []
        try:
            while True:
                header = self._raw.read(8)
                if not header or len(header) < 8:
                    break  # EOF
                stream_type = header[0]
                payload_len = int.from_bytes(header[4:8], "big")
                if payload_len == 0:
                    continue
                payload = self._raw.read(payload_len)
                if stream_type == 1:  # stdout
                    chunks.append(payload)
                # stderr (stream type 2) is discarded
        except TimeoutError:
            pass  # No more data — return what we have

        return b"".join(chunks)

    def close(self) -> None:
        """Close the underlying socket."""
        self._raw.close()


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

        Uses a hybrid approach based on spike findings (see design.md):
        - **Write**: ``docker exec sh -c echo '...' > /proc/1/fd/0`` — proven
          reliable via shell redirection (Python ``open()`` fails with OSError,
          but ``sh -c echo`` avoids it)
        - **Read**: stdout-only ``attach_socket`` with ``_DockerFrameReader`` —
          blocks until the response arrives, no race condition, no ``time.sleep``

        This replaces the earlier combined attach-socket approach (stdin+stdout),
        which was abandoned because writing to stdin via the attach socket does
        not deliver data to the container in this Docker setup.
        """
        container = self._client.containers.get(container_id)
        request_json = json.dumps(request)

        # Open a stdout-only attach socket and wrap it in a frame reader.
        # Docker multiplexes even stdout-only output with 8-byte frame headers.
        sock = container.attach_socket(
            params={"stdout": 1, "stream": 1}
        )
        reader = _DockerFrameReader(sock)

        # Write the request to PID 1's stdin via docker exec with shell
        # redirection.  The shell's echo built-in opens /proc/1/fd/0 via the
        # shell's own /proc access, which avoids the OSError seen with a
        # separate Python open() call.
        safe_json = request_json.replace("'", "'\\\'\'")
        self.container_exec_run(
            container_id,
            ["sh", "-c", f"echo '{safe_json}' > /proc/1/fd/0"],
        )

        # Read the response from stdout with a generous timeout.
        # The response should arrive immediately after the entrypoint processes
        # the request — no sleep or polling needed.
        payload = reader.read(timeout=30.0)
        reader.close()

        # Parse the first valid JSON object from the payload
        for line in payload.decode("utf-8").split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        # Fallback: check container logs as a safety net.
        # The entrypoint might have written the response but the socket didn't
        # deliver it in time (edge case under extreme load).
        logs = container.logs(stdout=True, stderr=True, tail=10).decode(
            "utf-8"
        )
        for line in reversed(logs.strip().split("\n")):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue

        msg = f"No JSON-RPC response found in attach socket or container logs: {logs}"
        raise ConnectionError(msg)
