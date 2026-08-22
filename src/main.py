"""Main entry point for the MCP Sandbox PyREPL server.

Wires together configuration, Docker client, SessionManager, and MCP server
using the factory pattern. No business logic lives here — just composition.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────

DEFAULT_CONFIG = {
    "sandbox": {
        "images": {
            "3.9": "sandbox-base:3.9",
            "3.10": "sandbox-base:3.10",
            "3.11": "sandbox-base:3.11",
            "3.12": "sandbox-base:3.12",
            "3.13": "sandbox-base:3.13",
        },
        "defaults": {
            "python_version": "3.12",
            "timeout": 30,
        },
        "data_dir": str(Path.home() / ".mcp-sandbox-pyrepl" / "data"),
    }
}


def sanitize_config_path(config_path: str) -> str:
    """Resolve a config path relative to the project root if needed."""
    path = Path(config_path)
    if path.is_absolute():
        return str(path)
    # Try relative to project root
    project_root = Path(__file__).resolve().parent.parent
    return str(project_root / config_path)


def load_config(config_path: str | None = None) -> dict[str, Any]:
    """Load configuration from YAML file, falling back to defaults.

    Args:
        config_path: Optional path to config.yaml. If None or file doesn't
                     exist, returns default configuration.

    Returns:
        Dict with sandbox configuration.
    """
    if config_path is None:
        config_path = sanitize_config_path("config.yaml")

    path = Path(config_path)
    if not path.exists():
        logger.info("Config file not found at %s, using defaults", config_path)
        return dict(DEFAULT_CONFIG)

    try:
        with open(path) as f:
            config = yaml.safe_load(f)
        if config is None:
            return dict(DEFAULT_CONFIG)
        return _merge_config(config, dict(DEFAULT_CONFIG))
    except Exception as exc:
        logger.warning("Failed to load config: %s, using defaults", exc)
        return dict(DEFAULT_CONFIG)


def _merge_config(
    user_config: dict[str, Any], default_config: dict[str, Any]
) -> dict[str, Any]:
    """Merge user config into defaults, preserving user values."""
    result = dict(default_config)
    sandbox = user_config.get("sandbox", {})
    default_sandbox = result.get("sandbox", {})

    # Merge images
    images = sandbox.get("images", {})
    if images:
        default_sandbox["images"] = {
            **default_sandbox.get("images", {}),
            **images,
        }

    # Merge defaults
    user_defaults = sandbox.get("defaults", {})
    if user_defaults:
        default_sandbox["defaults"] = {
            **default_sandbox.get("defaults", {}),
            **user_defaults,
        }

    # Override data_dir if provided
    if "data_dir" in sandbox:
        default_sandbox["data_dir"] = sandbox["data_dir"]

    result["sandbox"] = default_sandbox
    return result


# ──────────────────────────────────────────────────────────────────────
# Docker client factory
# ──────────────────────────────────────────────────────────────────────


def create_docker_client() -> Any:
    """Create a Docker client using the docker-py library.

    Returns a ``RealDockerClient`` adapter that satisfies the
    ``DockerClient`` Protocol expected by ``SessionManager``.

    Returns:
        A ``RealDockerClient`` instance wrapping the docker-py client.

    Raises:
        RuntimeError: If Docker is not available.
    """
    try:
        import docker  # type: ignore[import-untyped]

        from docker_adapter import RealDockerClient

        raw_client = docker.from_env()
        # Verify Docker is reachable
        raw_client.ping()
        logger.info("Docker daemon is available")
        return RealDockerClient(raw_client)
    except Exception as exc:  # pragma: no cover — only reachable when Docker is unavailable; testing it would require monkeypatching (anti-pattern)
        msg = (
            f"Docker is not available: {exc}. "
            "Make sure Docker is installed and running."
        )
        raise RuntimeError(msg) from exc


# ──────────────────────────────────────────────────────────────────────
# Session manager factory
# ──────────────────────────────────────────────────────────────────────


def create_session_manager(
    config: dict[str, Any],
    docker_client: Any = None,
) -> Any:
    """Create a SessionManager from configuration.

    Args:
        config: Dict with sandbox configuration.
        docker_client: Optional Docker client. If None, creates one.

    Returns:
        A configured SessionManager instance.
    """
    from session_manager import SessionManager, SessionManagerConfig

    sandbox_config = config.get("sandbox", {})
    images = sandbox_config.get("images", {})
    defaults = sandbox_config.get("defaults", {})
    data_dir = sandbox_config.get("data_dir", DEFAULT_CONFIG["sandbox"]["data_dir"])

    sm_config = SessionManagerConfig(
        data_dir=Path(data_dir),
        image_registry=images,
        default_python_version=defaults.get(
            "python_version",
            DEFAULT_CONFIG["sandbox"]["defaults"]["python_version"],
        ),
    )

    if docker_client is None:
        docker_client = create_docker_client()
    return SessionManager(docker=docker_client, config=sm_config)


# ──────────────────────────────────────────────────────────────────────
# MCP app factory
# ──────────────────────────────────────────────────────────────────────


def create_mcp_app(
    config: dict[str, Any],
    docker_client: Any = None,
) -> Any:
    """Create the FastMCP application with all tools registered.

    Args:
        config: Dict with sandbox configuration.
        docker_client: Optional Docker client. If None, creates one.

    Returns:
        A configured FastMCP instance.
    """
    from mcp_server import create_mcp_app as _create_mcp_app

    session_manager = create_session_manager(config, docker_client=docker_client)
    sandbox_config = config.get("sandbox", {})
    images = sandbox_config.get("images", {})

    return _create_mcp_app(
        session_manager=session_manager,
        image_registry=images,
        server_name="mcp-sandbox-pyrepl",
    )


# ──────────────────────────────────────────────────────────────────────
# Signal handlers
# ──────────────────────────────────────────────────────────────────────


def setup_signal_handlers(
    signal_handler: Callable[[int, Any], None] | None = None,
    register: Callable[[int, Callable[[int, Any], None]], Any] | None = None,
) -> None:
    """Register signal handlers for graceful shutdown.

    Args:
        signal_handler: Optional custom handler function. If None, uses
                        default graceful shutdown handler.
        register: Optional signal registration function. Defaults to
                  signal.signal. Injected for testability.
    """
    import signal as signal_module

    handler = signal_handler or _default_shutdown_handler
    register_func = register or signal_module.signal

    register_func(signal_module.SIGINT, handler)
    register_func(signal_module.SIGTERM, handler)


def _default_shutdown_handler(signum: int, frame: Any) -> None:
    """Default signal handler for graceful shutdown."""
    _ = signum, frame
    logger.info("Shutdown signal received, exiting...")
    sys.exit(0)


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Main entry point for the MCP Sandbox PyREPL server."""
    import argparse

    parser = argparse.ArgumentParser(description="MCP Sandbox PyREPL Server")
    parser.add_argument(
        "--config",
        "-c",
        default=None,
        help="Path to config.yaml (default: config.yaml in project root)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    # Load config
    config = load_config(args.config)
    logger.info("Configuration loaded")

    # Setup signal handlers
    setup_signal_handlers()

    # Create and run the MCP app
    mcp_app = create_mcp_app(config)
    logger.info("Starting MCP Sandbox PyREPL server...")

    # Try to detect Docker availability
    try:
        create_docker_client()
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(1)

    # Run the server
    mcp_app.run()


if __name__ == "__main__":
    main()
