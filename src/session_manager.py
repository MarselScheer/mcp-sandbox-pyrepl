"""Session Manager — host-side lifecycle management of sandbox Docker containers.

Design notes:
- DockerClient is a Protocol defined by this module's consumer (SessionManager),
  not by the provider (docker-py). Any object that fits the shape is valid.
- SessionManagerConfig centralizes all configuration — no magic numbers.
- SessionManager is a rich domain model: it owns session state AND behavior.
"""

from __future__ import annotations

import contextlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

# ──────────────────────────────────────────────────────────────────────
# Docker Client Protocol — defined by the consumer
# ──────────────────────────────────────────────────────────────────────


class DockerClient(Protocol):
    """What SessionManager needs from Docker — expressed in domain terms.

    Any object (docker-py client, fake, mock) that satisfies this
    Protocol can be injected. No inheritance required.
    """

    def containers_create(
        self,
        image: str,
        command: str | None = ...,
        name: str | None = ...,
        user: str | None = ...,
        read_only: bool = ...,
        cap_drop: list[str] | None = ...,
        volumes: list[dict[str, Any]] | None = ...,
        network: str | None = ...,
        detach: bool = ...,
        tmpfs: dict[str, str] | None = ...,
    ) -> Any: ...

    def container_get(self, container_id: str) -> Any: ...

    def container_remove(self, container_id: str, force: bool = ...) -> None: ...

    def container_stop(self, container_id: str) -> None: ...

    def container_stdin(self, container_id: str) -> Any: ...

    def container_exec_run(
        self, container_id: str, cmd: list[str]
    ) -> dict[str, Any]: ...

    def container_rpc(
        self, container_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the container and read the response.

        Writes the request to the entrypoint's stdin and reads the
        response from stdout. Raises ConnectionError if no response
        is received within a reasonable time.
        """
        ...

    def network_disconnect(self, container_id: str, network: str = ...) -> None: ...

    def network_connect(self, container_id: str, network: str = ...) -> None: ...


# ──────────────────────────────────────────────────────────────────────
# Configuration — centralized, no magic numbers
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionManagerConfig:
    """All configurable values for SessionManager — single source of truth.

    No magic numbers in the code. Everything configurable lives here.
    """

    data_dir: Path = field(
        default_factory=lambda: Path.home() / ".mcp-sandbox-pyrepl" / "data"
    )
    image_registry: dict[str, str] = field(
        default_factory=lambda: {
            "3.9": "sandbox-base:3.9",
            "3.10": "sandbox-base:3.10",
            "3.11": "sandbox-base:3.11",
            "3.12": "sandbox-base:3.12",
            "3.13": "sandbox-base:3.13",
        }
    )
    default_python_version: str = "3.12"
    network_name: str = "bridge"
    container_user: str = "1000"


# ──────────────────────────────────────────────────────────────────────
# Session Manager — the host-side domain model
# ──────────────────────────────────────────────────────────────────────


@dataclass
class SessionMetadata:
    """Rich domain model for a session's state and metadata."""

    session_id: str
    container_id: str
    image: str
    python_version: str
    created_at: datetime
    status: str = "running"


class SessionManager:
    """Manages sandboxed REPL sessions backed by Docker containers.

    Receives a DockerClient via DI — no hardcoded dependencies.
    Session state is owned by this class (rich domain model).
    """

    def __init__(
        self,
        docker: DockerClient,
        config: SessionManagerConfig | None = None,
    ) -> None:
        self._docker = docker
        self._config = config or SessionManagerConfig()
        self._sessions: dict[str, SessionMetadata] = {}

    def create_session(
        self,
        python_version: str | None = None,
        image: str | None = None,
    ) -> str:
        """Create a new sandboxed REPL session.

        Returns a unique session_id.

        Args:
            python_version: Python version key from the image registry.
            image: Custom image override (takes precedence over python_version).

        Returns:
            A unique session identifier.
        """
        if image is None:
            version = python_version or self._config.default_python_version
            resolved_image = self._resolve_image(version)
        else:
            resolved_image = image

        session_id = self._generate_session_id()

        volumes = [
            {
                # Use a named volume for /data so Docker manages storage
                # instead of requiring a host-side bind mount. This avoids
                # permission errors when the MCP server runs inside a
                # Docker container (Docker-in-Docker scenario).
                "host_path": "",
                "container_path": "/data",
                "mode": "rw",
            },
            {
                "host_path": "",
                "container_path": "/session",
                "mode": "rw",
            },
        ]

        container = self._docker.containers_create(
            image=resolved_image,
            user=self._config.container_user,
            read_only=True,
            cap_drop=["ALL"],
            volumes=volumes,
            tmpfs={"/tmp": "rw,size=64m"},
            network=self._config.network_name,
            detach=True,
        )

        metadata = SessionMetadata(
            session_id=session_id,
            container_id=container.id,
            image=resolved_image,
            python_version=python_version or self._config.default_python_version,
            created_at=datetime.now(timezone.utc),
        )
        self._sessions[session_id] = metadata

        return session_id

    def end_session(self, session_id: str) -> None:
        """End a session: send shutdown, stop and remove the container, clean up.

        Idempotent — safe to call on already-ended or nonexistent sessions.
        """
        metadata = self._sessions.pop(session_id, None)
        if metadata is None:
            return

        with contextlib.suppress(Exception):
            self._send_shutdown(metadata.container_id)

        with contextlib.suppress(Exception):
            self._docker.container_stop(metadata.container_id)
            self._docker.container_remove(metadata.container_id, force=True)

    def list_sessions(self) -> dict[str, dict[str, Any]]:
        """Return all active sessions with their metadata."""
        return {
            sid: self._metadata_to_dict(meta) for sid, meta in self._sessions.items()
        }

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Return metadata for a specific session, or None if not found."""
        metadata = self._sessions.get(session_id)
        if metadata is None:
            return None
        return self._metadata_to_dict(metadata)

    def network_connect(self, session_id: str) -> None:
        """Connect the container's network (for package installation)."""
        metadata = self._sessions.get(session_id)
        if metadata is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        self._docker.network_connect(metadata.container_id, self._config.network_name)

    def network_disconnect(self, session_id: str) -> None:
        """Disconnect the container's network (for code execution)."""
        metadata = self._sessions.get(session_id)
        if metadata is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        self._docker.network_disconnect(
            metadata.container_id, self._config.network_name
        )

    def restart_session(self, session_id: str) -> None:
        """Restart a session by killing the old container and creating a new one.

        Used when a session is corrupted (hard timeout, etc.).
        """
        metadata = self._sessions.get(session_id)
        if metadata is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        # Kill the old container
        with contextlib.suppress(Exception):
            self._docker.container_stop(metadata.container_id)
            self._docker.container_remove(metadata.container_id, force=True)

        # Create a new container for the same session
        volumes = [
            {
                "host_path": "",
                "container_path": "/data",
                "mode": "rw",
            },
            {
                "host_path": "",
                "container_path": "/session",
                "mode": "rw",
            },
        ]

        container = self._docker.containers_create(
            image=metadata.image,
            user=self._config.container_user,
            read_only=True,
            cap_drop=["ALL"],
            volumes=volumes,
            tmpfs={"/tmp": "rw,size=64m"},
            network=self._config.network_name,
            detach=True,
        )

        new_meta = SessionMetadata(
            session_id=session_id,
            container_id=container.id,
            image=metadata.image,
            python_version=metadata.python_version,
            created_at=datetime.now(timezone.utc),
            status="restarted",
        )
        self._sessions[session_id] = new_meta

    def send_rpc(self, session_id: str, request: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request to the session container and read the response.

        Delegates to the Docker client's container_rpc which handles the
        stdin write + stdout read cycle through the container's entrypoint.
        """
        metadata = self._sessions.get(session_id)
        if metadata is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        return self._docker.container_rpc(metadata.container_id, request)

    def send_exec(
        self, session_id: str, code: str, timeout: float = 30.0
    ) -> dict[str, Any]:
        """Execute Python code in the session and return the result."""
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "exec",
            "params": {"code": code, "timeout": timeout},
        }
        response = self.send_rpc(session_id, request)
        # Extract the result sub-dict from the JSON-RPC response envelope
        return response.get("result", response)

    # ── File operations via docker exec ────────────────────────────

    def write_file(self, session_id: str, path: str, content: str) -> dict[str, Any]:
        """Write content to a file in the session's /data directory.

        Uses docker exec to interact with the container's /data volume,
        avoiding host-side bind mount issues (e.g., Docker-in-Docker).

        Args:
            session_id: Target session identifier.
            path: Relative path within /data.
            content: File content (text or base64-encoded bytes).

        Returns:
            Dict with success status.
        """
        import base64 as _b64

        metadata = self._sessions.get(session_id)
        if metadata is None:
            return {"success": False, "error": f"Session not found: {session_id}"}

        # Base64-encode the content to avoid shell escaping issues
        encoded = _b64.b64encode(content.encode("utf-8")).decode("ascii")

        script = (
            "import base64, os\n"
            f"data = base64.b64decode({json.dumps(encoded)})\n"
            f"p = {json.dumps(path)}\n"
            "full_path = os.path.join('/data', p)\n"
            "os.makedirs(os.path.dirname(full_path), exist_ok=True)\n"
            "with open(full_path, 'wb') as f:\n"
            "    f.write(data)\n"
            "print('OK')\n"
        )

        result = self._docker.container_exec_run(
            metadata.container_id, ["python3", "-c", script]
        )

        if result.get("exit_code") != 0:
            return {
                "success": False,
                "error": result.get("output", "Unknown error"),
            }
        return {"success": True}

    def read_file(self, session_id: str, path: str) -> dict[str, Any]:
        """Read a file from the session's /data directory.

        Uses docker exec to interact with the container's /data volume.

        Args:
            session_id: Target session identifier.
            path: Relative path within /data.

        Returns:
            Dict with content (text or base64-encoded bytes).
        """
        import base64 as _b64

        metadata = self._sessions.get(session_id)
        if metadata is None:
            return {"error": f"Session not found: {session_id}"}

        script = (
            "import base64, os, json as j\n"
            f"p = {json.dumps(path)}\n"
            "full_path = os.path.join('/data', p)\n"
            "if not os.path.exists(full_path):\n"
            "    print(j.dumps({'error': 'File not found'}))\n"
            "else:\n"
            "    with open(full_path, 'rb') as f:\n"
            "        data = f.read()\n"
            "    print(j.dumps({'content': base64.b64encode(data).decode('ascii')}))\n"
        )

        result = self._docker.container_exec_run(
            metadata.container_id, ["python3", "-c", script]
        )

        if result.get("exit_code") != 0:
            return {"error": result.get("output", "Unknown error")}

        try:
            output = result.get("output", "")
            parsed = json.loads(output.strip())
            if "error" in parsed:
                return {"error": parsed["error"]}
            encoded = parsed.get("content", "")
            raw = _b64.b64decode(encoded)
            try:
                return {"content": raw.decode("utf-8")}
            except UnicodeDecodeError:
                return {"content": encoded}
        except (json.JSONDecodeError, KeyError):
            return {"error": "Failed to parse file content"}

    def list_files(self, session_id: str, path: str = "") -> dict[str, Any]:
        """List files in the session's /data directory.

        Uses docker exec to interact with the container's /data volume.

        Args:
            session_id: Target session identifier.
            path: Optional subdirectory path within /data.

        Returns:
            Dict with files list.
        """
        metadata = self._sessions.get(session_id)
        if metadata is None:
            return {"error": f"Session not found: {session_id}"}

        script = (
            "import os, json as j\n"
            f"p = {json.dumps(path)}\n"
            "full_path = os.path.join('/data', p) if p else '/data'\n"
            "if not os.path.exists(full_path):\n"
            "    print(j.dumps({'files': []}))\n"
            "else:\n"
            "    entries = []\n"
            "    for name in sorted(os.listdir(full_path)):\n"
            "        entry_path = os.path.join(full_path, name)\n"
            "        st = os.stat(entry_path)\n"
            "        entries.append({\n"
            "            'name': name,\n"
            "            'type': 'directory' "
            "if os.path.isdir(entry_path) else 'file',\n"
            "            'size': st.st_size,\n"
            "        })\n"
            "    print(j.dumps({'files': entries}))\n"
        )

        result = self._docker.container_exec_run(
            metadata.container_id, ["python3", "-c", script]
        )

        if result.get("exit_code") != 0:
            return {"error": result.get("output", "Unknown error")}

        try:
            output = result.get("output", "")
            return json.loads(output.strip())
        except json.JSONDecodeError:
            return {"error": "Failed to parse file listing"}

    # ── Private helpers ──────────────────────────────────────────────

    def _resolve_image(self, python_version: str) -> str:
        image = self._config.image_registry.get(python_version)
        if image is None:
            available = ", ".join(sorted(self._config.image_registry))
            msg = (
                f"Python version '{python_version}' not available. "
                f"Available versions: {available}"
            )
            raise ValueError(msg)
        return image

    @staticmethod
    def _generate_session_id() -> str:
        return f"sess_{uuid.uuid4().hex[:12]}"

    def _send_shutdown(self, container_id: str) -> None:
        request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "shutdown",
            "params": {},
        }
        stdin = self._docker.container_stdin(container_id)
        line = json.dumps(request) + "\n"
        stdin.write(line)
        stdin.flush()

    @staticmethod
    def _metadata_to_dict(metadata: SessionMetadata) -> dict[str, Any]:
        return {
            "session_id": metadata.session_id,
            "container_id": metadata.container_id,
            "image": metadata.image,
            "python_version": metadata.python_version,
            "created_at": metadata.created_at.isoformat(),
            "status": metadata.status,
        }
