"""JSON-RPC helpers for integration tests.

Provides rpc_call() for sending JSON-RPC requests to the container's
entrypoint via stdin/stdout and reading responses. Exercises the real
JSON-RPC communication path (not docker exec).
"""

from __future__ import annotations

from typing import Any

from docker import DockerClient as _DockerClient

from docker_adapter import RealDockerClient


def rpc_call(
    docker_client: _DockerClient, container_id: str, request: dict[str, Any]
) -> dict[str, Any]:
    """Send a JSON-RPC request to the container's entrypoint and return the response.

    Exercises the real JSON-RPC stdin/stdout communication path through the
    entrypoint (not docker exec). This is how the production code communicates
    with the sandbox container.
    """
    adapter = RealDockerClient(docker_client)
    return adapter.container_rpc(container_id, request)
