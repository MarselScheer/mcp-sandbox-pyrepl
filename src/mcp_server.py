"""MCP Server — FastMCP tool handlers for the sandboxed Python REPL.

Design notes:
- SessionManager is injected via DI (no hardcoded dependencies).
- MCPToolHandler contains all tool handler methods as plain callables.
- The FastMCP app is created by the factory, keeping tool registration
  separate from handler logic.
"""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP


class MCPToolHandler:
    """Tool handler methods for the MCP sandbox server.

    Each method corresponds to an MCP tool. SessionManager is injected
    so handlers are trivially testable without mock.patch.
    """

    def __init__(
        self,
        session_manager: Any,
        image_registry: dict[str, str],
    ) -> None:
        self._sm = session_manager
        self._image_registry = image_registry

    def create_session(
        self,
        python_version: str | None = None,
        image: str | None = None,
    ) -> dict[str, Any]:
        """Create a new sandboxed Python REPL session.

        Args:
            python_version: Python version to use (e.g., "3.12").
                          Defaults to the SessionManager's configured default.
            image: Optional custom Docker image override (takes precedence
                   over python_version).

        Returns:
            Dict with session_id and metadata.
        """
        kwargs: dict[str, Any] = {}
        if image is not None:
            kwargs["image"] = image
        elif python_version is not None:
            kwargs["python_version"] = python_version
        # else: pass neither — SessionManager uses its config default

        session_id = self._sm.create_session(**kwargs)
        info = self._sm.get_session(session_id)
        return {"session_id": session_id, **(info or {})}

    def execute_python(
        self,
        session_id: str,
        code: str,
        timeout: int = 30,
    ) -> dict[str, Any]:
        """Execute Python code in a session.

        **Important:** Multi-line definition blocks (`def`, `class`, `async def`)
        must be defined in a **separate call** from the code that invokes them.
        The underlying `compile()` with `'single'` mode supports at most one
        compound statement per call. Combining a definition and its invocation
        in a single call will silently lose REPL display hook output for
        evaluated expressions.

        Correct usage:
            execute_python(session_id, code="def double(x):\\n    return x * 2")
            result = execute_python(session_id, code="double(21)")
            # result.display == ["42"]

        Incorrect (display output lost):
            result = execute_python(
                session_id, code="def double(x):\\n    return x * 2\\ndouble(21)"
            )
            # result.display == []  — display hook not triggered

        Args:
            session_id: Target session identifier.
            code: Python code to execute.
            timeout: Maximum execution time in seconds.

        Returns:
            Dict with stdout, stderr, display output, and error.
        """
        result = self._sm.send_exec(session_id, code, timeout=float(timeout))

        response: dict[str, Any] = {
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "display": result.get("display", []),
            "error": result.get("error"),
        }

        if result.get("session_corrupted"):
            response["session_reset"] = True
            self._sm.restart_session(session_id)

        return response

    def install_packages(
        self,
        session_id: str,
        packages: list[dict[str, str]],
    ) -> dict[str, Any]:
        """Install Python packages in a session.

        Temporarily enables network access for the container.

        Each package dict must have a ``"name"`` key (the package name)
        and may optionally have a ``"version"`` key for exact version pinning
        (joined with ``==``).

        Example:
            install_packages(
                session_id="sess_abc",
                packages=[{"name": "pandas"}, {"name": "scipy", "version": "1.11.0"}],
            )

        Args:
            session_id: Target session identifier.
            packages: List of dicts, each with a ``"name"`` key and
                      optionally a ``"version"`` key.

        Returns:
            Dict with success status and output.
        """
        self._sm.network_connect(session_id)
        try:
            result = self._sm.send_rpc(
                session_id,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "install",
                    "params": {"packages": packages},
                },
            )
        except Exception as exc:
            result = {"error": str(exc), "stdout": "", "stderr": ""}
        finally:
            self._sm.network_disconnect(session_id)

        return {
            "success": result.get("error") is None,
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "error": result.get("error"),
        }

    def list_sessions(self) -> dict[str, Any]:
        """List all active sessions.

        Returns:
            Dict with sessions key containing session metadata.
        """
        return {"sessions": self._sm.list_sessions()}

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Get information about a specific session.

        Args:
            session_id: The session identifier.

        Returns:
            Session metadata dict, or None if not found.
        """
        return self._sm.get_session(session_id)

    def end_session(self, session_id: str) -> dict[str, Any]:
        """End a session and clean up resources.

        Args:
            session_id: The session identifier.

        Returns:
            Dict with success status.
        """
        self._sm.end_session(session_id)
        return {"success": True}

    def list_python_versions(self) -> dict[str, Any]:
        """List available Python versions and custom images.

        Returns:
            Dict with versions key containing the image registry.
        """
        return {"versions": dict(self._image_registry)}

    def write_file(self, session_id: str, path: str, content: str) -> dict[str, Any]:
        """Write content to a file in the session's data directory.

        Delegates to SessionManager.write_file() which uses docker exec
        to interact with the container's /data volume. This avoids host-side
        bind mount issues (e.g., Docker-in-Docker).

        Args:
            session_id: Target session identifier.
            path: Relative path within the data directory.
            content: File content (text or base64-encoded bytes).

        Returns:
            Dict with success status.
        """
        return self._sm.write_file(session_id, path, content)

    def read_file(self, session_id: str, path: str) -> dict[str, Any]:
        """Read a file from the session's data directory.

        Delegates to SessionManager.read_file() which uses docker exec
        to interact with the container's /data volume.

        Args:
            session_id: Target session identifier.
            path: Relative path within the data directory.

        Returns:
            Dict with content (text or base64-encoded bytes).
        """
        return self._sm.read_file(session_id, path)

    def list_files(self, session_id: str, path: str = "") -> dict[str, Any]:
        """List files in the session's data directory.

        Delegates to SessionManager.list_files() which uses docker exec
        to interact with the container's /data volume.

        Args:
            session_id: Target session identifier.
            path: Optional subdirectory path.

        Returns:
            Dict with files list.
        """
        return self._sm.list_files(session_id, path)


# ──────────────────────────────────────────────────────────────────────
# Factory
# ──────────────────────────────────────────────────────────────────────


def create_mcp_app(
    session_manager: Any,
    image_registry: dict[str, str],
    server_name: str = "mcp-sandbox-pyrepl",
) -> FastMCP:
    """Create and configure the FastMCP application.

    Args:
        session_manager: The SessionManager instance.
        image_registry: Image registry mapping.
        server_name: MCP server name.

    Returns:
        Configured FastMCP app with all tools registered.
    """
    handler = MCPToolHandler(
        session_manager=session_manager, image_registry=image_registry
    )

    mcp = FastMCP(server_name)

    mcp.add_tool(handler.create_session, name="create_session")
    mcp.add_tool(handler.execute_python, name="execute_python")
    mcp.add_tool(handler.install_packages, name="install_packages")
    mcp.add_tool(handler.list_sessions, name="list_sessions")
    mcp.add_tool(handler.get_session, name="get_session")
    mcp.add_tool(handler.end_session, name="end_session")
    mcp.add_tool(handler.list_python_versions, name="list_python_versions")
    mcp.add_tool(handler.write_file, name="write_file")
    mcp.add_tool(handler.read_file, name="read_file")
    mcp.add_tool(handler.list_files, name="list_files")

    return mcp
