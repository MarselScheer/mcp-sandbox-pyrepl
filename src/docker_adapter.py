"""Real Docker Client Adapter — wraps docker-py to satisfy the DockerClient Protocol.

Maps the SessionManager's domain-level Protocol methods (``containers_create``,
``container_get``, etc.) to the real docker-py SDK API (``client.containers.create``,
``client.containers.get``, etc.).

This adapter is the single boundary layer between domain code and the docker-py
library. Domain code never imports docker-py directly.
"""

from __future__ import annotations

import io
import socket
import uuid
from typing import Any

from docker import DockerClient as _DockerClient
from docker.models.containers import Container


class RealDockerClient:
    """Adapter that wraps the docker-py SDK to satisfy the DockerClient Protocol.

    Maps the SessionManager's Protocol methods to the real docker-py API.
    The docker-py library is encapsulated here — no other module imports it.
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
        """Create and start a container via the docker-py SDK.

        Translates the Protocol's volume format (list of dicts with
        ``host_path``/``container_path``/``mode``) to docker-py's volume
        format (dict mapping source to bind config). Empty ``host_path``
        values trigger auto-generated named volumes.
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
                # Auto-generated named volume — Docker copies the image's
                # pre-built contents (e.g. venv) into the volume.
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

        Returns a file-like object supporting ``.write()`` and ``.flush()``.
        Uses docker-py's ``attach_socket`` to get a raw socket, then wraps
        it in a ``TextIOWrapper`` for text I/O.
        """
        container = self.container_get(container_id)
        sock = container.attach_socket(params={"stdin": 1, "stream": 1, "logs": 1})
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

    def container_exec_run(self, container_id: str, cmd: list[str]) -> dict[str, Any]:
        """Run a command inside the container and return the result."""
        container = self._client.containers.get(container_id)
        result = container.exec_run(cmd)
        output = (
            result.output.decode("utf-8")
            if isinstance(result.output, bytes)
            else result.output
        )
        return {
            "exit_code": result.exit_code,
            "output": output,
        }

    def network_disconnect(self, container_id: str, network: str = "bridge") -> None:
        """Disconnect a container from a network."""
        net = self._client.networks.get(network)
        net.disconnect(container_id)

    def network_connect(self, container_id: str, network: str = "bridge") -> None:
        """Connect a container to a network.

        If the container is already connected to the network, this is a no-op
        (avoids Docker's 403 error for duplicate endpoint names).
        """
        container = self._client.containers.get(container_id)
        networks = container.attrs.get("NetworkSettings", {}).get("Networks", {})
        if network in networks:
            return  # Already connected
        net = self._client.networks.get(network)
        net.connect(container_id)

    def container_rpc(
        self, container_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the container's entrypoint and read the response.

        The entrypoint (PID 1) runs a JSON-RPC server that reads from stdin
        and writes responses to stdout.  This method sends one request and
        reads the response via that path.

        Why not use ``container_stdin()`` (attach_socket) for both sides?
        -----------------------------------------------------------------
        ``attach_socket`` gives you a raw bidirectional stream to the
        container's stdin/stdout/stderr, but Docker multiplexes stdout and
        stderr over that stream using an 8-byte frame header per chunk
        (stream type + length).  Parsing that correctly to separate
        application-level responses from stray output is fragile and
        over-engineered for a request-response pattern.

        Instead, this method decouples the write and read sides:

          Write side — docker exec writes to ``/proc/1/fd/0`` (PID 1's
          stdin).  This is equivalent to typing into the entrypoint's stdin.
          Linux allows any process in the same PID namespace to write to
          another process's file descriptors, so a docker exec subprocess
          can inject the request directly.

          Read side — ``container.logs()`` returns the entrypoint's stdout
          cleanly, already demuxed by Docker.  No frame parsing needed.

        This exercises the real JSON-RPC stdin/stdout path through the
        entrypoint, not a docker exec subprocess.
        """
        import json
        import time

        t0 = time.perf_counter()

        container = self._client.containers.get(container_id)
        request_json = json.dumps(request)

        # Write the request to PID 1's stdin via a docker exec subprocess.
        # /proc/1/fd/0 is the entrypoint process's stdin pipe. Writing to it
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

        # Short-poll + exponential backoff loop to read the JSON-RPC
        # response from the container's stdout. When the response is
        # already present, the first iteration reads it within ~10ms.
        # Under load, backoff scales up to 100ms per iteration.
        # The entrypoint's ThreadTimeoutStrategy has a hard_timeout
        # of 5s (for thread cleanup after timeout), so the total
        # timeout allows up to 10s to account for that overhead.
        backoff = 0.01  # 10ms initial
        max_backoff = 0.1  # 100ms max
        total_wait = 0.0
        timeout = 10.0
        while total_wait < timeout:
            logs = container.logs(stdout=True, stderr=False, tail=5).decode("utf-8")
            for line in reversed(logs.strip().split("\n")):
                line = line.strip()
                if not line:
                    continue
                try:
                    elapsed = time.perf_counter() - t0
                    import logging

                    logging.getLogger(__name__).info(
                        "TIMING container_rpc (%s method=%s): %.3fs",
                        container_id[:12],
                        request.get("method", "?"),
                        elapsed,
                    )
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue
            time.sleep(backoff)
            total_wait += backoff
            backoff = min(backoff * 1.5, max_backoff)

        elapsed = time.perf_counter() - t0
        msg = (
            f"No JSON-RPC response found in container logs after {elapsed:.3f}s: {logs}"
        )
        raise ConnectionError(msg)
