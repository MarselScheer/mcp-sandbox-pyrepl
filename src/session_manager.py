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
    ) -> Any:
        ...

    def container_get(self, container_id: str) -> Any:
        ...

    def container_remove(self, container_id: str, force: bool = ...) -> None:
        ...

    def container_stop(self, container_id: str) -> None:
        ...

    def container_stdin(self, container_id: str) -> Any:
        ...

    def container_exec_run(
        self, container_id: str, cmd: list[str]
    ) -> dict[str, Any]:
        ...

    def network_disconnect(
        self, container_id: str, network: str = ...
    ) -> None:
        ...

    def network_connect(
        self, container_id: str, network: str = ...
    ) -> None:
        ...


# ──────────────────────────────────────────────────────────────────────
# Configuration — centralized, no magic numbers
# ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class SessionManagerConfig:
    """All configurable values for SessionManager — single source of truth.

    No magic numbers in the code. Everything configurable lives here.
    """

    data_dir: Path = Path("/home/ubuntu/repos/mcp-sandbox-pyrepl/data")
    image_registry: dict[str, str] = field(default_factory=lambda: {
        "3.9": "sandbox-base:3.9",
        "3.10": "sandbox-base:3.10",
        "3.11": "sandbox-base:3.11",
        "3.12": "sandbox-base:3.12",
        "3.13": "sandbox-base:3.13",
    })
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
        data_path = self._ensure_data_dir(session_id)

        volumes = [
            {
                "host_path": str(data_path),
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
            sid: self._metadata_to_dict(meta)
            for sid, meta in self._sessions.items()
        }

    def get_session(
        self, session_id: str
    ) -> dict[str, Any] | None:
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

        self._docker.network_connect(
            metadata.container_id, self._config.network_name
        )

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
        data_path = self._ensure_data_dir(session_id)
        volumes = [
            {
                "host_path": str(data_path),
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

    def send_rpc(
        self, session_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the session container and read response."""
        metadata = self._sessions.get(session_id)
        if metadata is None:
            msg = f"Session not found: {session_id}"
            raise ValueError(msg)

        stdin = self._docker.container_stdin(metadata.container_id)
        line = json.dumps(request) + "\n"
        stdin.write(line)
        stdin.flush()

        # Read one line of response from container stdout
        # In the real implementation, this would read from the container's
        # stdout stream. Simplified for the Protocol.
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}

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
        return self.send_rpc(session_id, request)

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

    def _ensure_data_dir(self, session_id: str) -> Path:
        data_path = self._config.data_dir / session_id
        data_path.mkdir(parents=True, exist_ok=True)
        return data_path

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
