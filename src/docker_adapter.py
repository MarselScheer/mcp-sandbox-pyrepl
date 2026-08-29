"""Real Docker Client Adapter — wraps docker-py to satisfy the DockerClient Protocol.

Maps the SessionManager's domain-level Protocol methods (``containers_create``,
``container_get``, etc.) to the real docker-py SDK API (``client.containers.create``,
``client.containers.get``, etc.).

This adapter is the single boundary layer between domain code and the docker-py
library. Domain code never imports docker-py directly.
"""

from __future__ import annotations

import io
import json
import logging
import socket
import struct
import uuid
from typing import Any

log = logging.getLogger(__name__)

from docker import DockerClient as _DockerClient
from docker.models.containers import Container


class DockerFrameReader:
    """Reads Docker-multiplexed frames from a socket.

    Docker multiplexes stdout/stderr over an attached socket using an
    8-byte frame header::

        Byte  0     : stream type  (1=stdout, 2=stderr)
        Bytes 1-3   : reserved (zero)
        Bytes 4-7   : payload length (big-endian uint32)
        Bytes 8..N  : payload bytes

    This class encapsulates the low-level ``recv`` mechanics:
    partial-read-aware accumulation and frame header parsing.
    It is stateless — the same instance can be reused across calls.
    """

    def recv_exact(self, sock: socket.socket, n: int) -> bytes:
        """Read exactly *n* bytes from a socket (partial-read-aware loop).

        TCP can split or coalesce data across ``recv()`` boundaries. This
        loops until all *n* bytes are collected or the connection closes.

        Args:
            sock: The socket to read from.
            n: Number of bytes to read.

        Returns:
            The requested *n* bytes.

        Raises:
            ConnectionError: If the connection is closed before all *n*
                             bytes are received.
        """
        chunks: list[bytes] = []
        while n > 0:
            chunk = sock.recv(n)
            if not chunk:
                msg = (
                    f"Connection closed after reading "
                    f"{sum(len(c) for c in chunks)} bytes, expected more"
                )
                raise ConnectionError(msg)
            chunks.append(chunk)
            n -= len(chunk)
        return b"".join(chunks)

    def read_frame(self, sock: socket.socket) -> tuple[int, bytes] | None:
        """Read one Docker-multiplexed frame from the socket.

        Returns:
            A ``(stream_type, payload)`` tuple on success, or ``None`` if
            the connection is closed (EOF).
        """
        header = sock.recv(8)
        if not header:
            return None
        if len(header) < 8:
            header = header + self.recv_exact(sock, 8 - len(header))
        stream_type = header[0]
        payload_len = struct.unpack(">I", header[4:8])[0]
        if payload_len == 0:
            return stream_type, b""
        payload = self.recv_exact(sock, payload_len)
        return stream_type, payload


class RealDockerClient:
    """Adapter that wraps the docker-py SDK to satisfy the DockerClient Protocol.

    Maps the SessionManager's Protocol methods to the real docker-py API.
    The docker-py library is encapsulated here — no other module imports it.
    """

    def __init__(
        self,
        docker_client: _DockerClient,
        frame_reader: type[DockerFrameReader] = DockerFrameReader,
    ) -> None:
        self._client = docker_client
        self._frame_reader = frame_reader()
        self._rpc_counter = 0

    def containers_create(
        self,
        image: str,
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
        """Remove a container and its auto-generated named volumes.

        Inspects the container's mounts before removal, collects named
        volume names (``Type == "volume"`` with a ``Name``), removes the
        container, then removes each volume. Volume removal failures are
        silently suppressed (e.g. in-use volumes on parallel test runs).
        """
        import contextlib

        container = self.container_get(container_id)
        # Collect named volume names before removing the container — Docker
        # API returns no mounts for a removed container.
        mounts = (container.attrs or {}).get("Mounts", [])
        volume_names = [
            m["Name"] for m in mounts if m.get("Type") == "volume" and m.get("Name")
        ]
        container.remove(force=force)
        for vol_name in volume_names:
            with contextlib.suppress(Exception):
                vol = self._client.volumes.get(vol_name)
                vol.remove()

    def container_stop(self, container_id: str) -> None:
        """Stop a container."""
        container = self.container_get(container_id)
        container.stop()

    def _attach_raw_socket(
        self, container_id: str, params: dict[str, int]
    ) -> socket.socket:
        """Attach to a container and return a raw bidirectional ``socket.socket``.

        Handles the ``SocketIO`` unwrapping required by docker-py 7.1.0+ on
        Python 3.14+, where ``attach_socket()`` returns a ``SocketIO`` object
        instead of a raw ``socket.socket``.

        Args:
            container_id: The container ID or name to attach to.
            params: Params passed through to ``container.attach_socket()``.

        Returns:
            A raw ``socket.socket`` connected to the container's stream(s).

        Raises:
            TypeError: If the attach result is an unexpected type that cannot
                       be unwrapped to a ``socket.socket``.
        """
        container = self.container_get(container_id)
        sock = container.attach_socket(params=params)
        if isinstance(sock, socket.socket):
            return sock  # pragma: no cover — classic docker-py (< 7.1.0) returns raw socket.socket; installed version returns SocketIO, so this branch is only taken on older installs
        if hasattr(sock, "_sock") and isinstance(sock._sock, socket.socket):
            return sock._sock
        msg = f"Unexpected attach result type: {type(sock)}"  # pragma: no cover — docker-py returns socket.socket or SocketIO; unexpected type = breaking API change
        raise TypeError(msg)  # pragma: no cover

    def container_stdin(self, container_id: str) -> io.TextIOBase:
        """Get a writable stream to the container's stdin.

        Returns a file-like object supporting ``.write()`` and ``.flush()``.
        Delegates socket extraction to :meth:`_attach_raw_socket`, then wraps
        the resulting ``socket.socket`` in a :class:`~io.TextIOWrapper`.

        Falls back to direct file-like object handling for unusual docker-py
        versions that do not return a ``socket.socket`` or ``SocketIO``.
        """
        try:
            sock = self._attach_raw_socket(
                container_id, params={"stdin": 1, "stream": 1, "logs": 1}
            )
        except TypeError:  # pragma: no cover — attach_socket always returns socket.socket or SocketIO; fallback only for unknown future docker-py versions
            # Attach result is neither a raw socket nor SocketIO — try
            # direct file-like object handling (unknown docker-py versions).
            container = self.container_get(container_id)
            sock = container.attach_socket(
                params={"stdin": 1, "stream": 1, "logs": 1}
            )
            if hasattr(sock, "write") and getattr(sock, "writable", lambda: True)():
                return sock  # type: ignore[return-value]
            msg = f"Unexpected stdin type: {type(sock)}"
            raise TypeError(msg) from None
        return io.TextIOWrapper(
            io.BufferedWriter(sock.makefile("wb")),
            encoding="utf-8",
            line_buffering=True,
        )

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

        Uses a single bidirectional ``attach_socket`` for both the write side
        (request bytes sent via ``sendall()`` to the container's stdin) and
        the read side (response read as Docker-multiplexed frames from the
        container's stdout/stderr).

        Replaces the previous two-legged approach (``docker exec`` subprocess
        for writes + ``container.logs()`` polling loop for reads), eliminating
        the subprocess overhead per call and the polling latency.
        """
        self._rpc_counter += 1
        request_id = self._rpc_counter
        request["id"] = request_id

        sock = self._attach_raw_socket(
            container_id,
            params={"stdin": 1, "stdout": 1, "stderr": 1, "stream": 1},
        )

        request_bytes = (json.dumps(request) + "\n").encode("utf-8")
        sock.sendall(request_bytes)

        # Set timeout to match the entrypoint's total allowed RPC duration.
        # The entrypoint's ThreadTimeoutStrategy has a hard_timeout of 5s
        # (for thread cleanup after timeout), so we allow up to 10s.
        sock.settimeout(10.0)

        while True:
            try:
                frame = self._frame_reader.read_frame(sock)
            except socket.timeout:
                msg = (
                    f"No JSON-RPC response within {10.0}s "
                    f"(container={container_id[:12]}, method={request.get('method', '?')})"
                )
                raise ConnectionError(msg) from None

            if frame is None:  # pragma: no cover — attach socket only closes if container dies mid-RPC; PID 1 doesn't exit during normal operation
                msg = (
                    f"Connection closed before response received "
                    f"(container={container_id[:12]}, method={request.get('method', '?')})"
                )
                raise ConnectionError(msg)

            stream_type, payload = frame
            if stream_type != 1:  # pragma: no cover — entrypoint never writes to stderr; defensive only
                continue

            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError:  # pragma: no cover — entrypoint always emits valid JSON on stdout; defensive only
                continue

            if isinstance(parsed, dict) and parsed.get("id") == request_id:
                log.info(
                    "TIMING container_rpc (%s method=%s id=%s): complete",
                    container_id[:12],
                    request.get("method", "?"),
                    request_id,
                )
                return parsed


# ── Static conformance verification ─────────────────────────────────────
# Type checker verifies that RealDockerClient structurally satisfies the
# DockerClient Protocol.  If a method is missing or has a wrong signature,
# mypy / pyright will flag it here.  Never executed at runtime.
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from session_manager import DockerClient

    _: DockerClient = cast(RealDockerClient, None)
