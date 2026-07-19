"""Tests for main.py — the entry point that wires everything together.

The main module is kept thin — it just reads config, wires dependencies,
and starts the server. All business logic lives in injectable components.
"""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

from main import (
    create_mcp_app,
    create_session_manager,
    load_config,
    sanitize_config_path,
    setup_signal_handlers,
)

# ──────────────────────────────────────────────────���───────────────────
# Fake Docker Client
# ──────────────────────────────────────────────────────────────────────


class FakeDockerClient:
    """A minimal fake Docker client for testing main.py factories."""

    def containers_create(self, **kwargs: Any) -> Any:
        from tests.test_session_manager import FakeContainer

        image = kwargs.get("image", "")
        return FakeContainer(container_id="test-container", image=image)

    def container_get(self, container_id: str) -> Any:
        raise ValueError(f"Container {container_id} not found")

    def container_remove(self, container_id: str, force: bool = False) -> None:
        pass

    def container_stop(self, container_id: str) -> None:
        pass

    def container_stdin(self, container_id: str) -> Any:
        from io import StringIO

        return StringIO()

    def container_exec_run(self, container_id: str, cmd: list[str]) -> dict[str, Any]:
        return {"exit_code": 0, "output": ""}

    def network_disconnect(self, container_id: str, network: str = "bridge") -> None:
        pass

    def network_connect(self, container_id: str, network: str = "bridge") -> None:
        pass


# ──────────────────────────────────────────────────────────────────────
# Config loading
# ──────────────────────────────────────────────────────────────────────


class TestLoadConfig:
    """Loading configuration from YAML."""

    def test_load_config_returns_default_when_no_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nonexistent.yaml"

        config = load_config(str(config_path))

        assert "sandbox" in config
        assert "3.12" in config["sandbox"]["images"]

    def test_load_config_from_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "sandbox:\n"
            "  images:\n"
            '    "3.12": "sandbox-base:3.12"\n'
            "  defaults:\n"
            "    python_version: '3.12'\n"
            "    timeout: 30\n"
            '  data_dir: "/tmp/data"\n'
        )

        config = load_config(str(config_path))

        assert config["sandbox"]["images"]["3.12"] == "sandbox-base:3.12"
        assert config["sandbox"]["defaults"]["timeout"] == 30

    def test_sanitize_config_path_resolves_relative(self) -> None:
        result = sanitize_config_path("config.yaml")
        assert result.endswith("config.yaml")
        assert isinstance(result, str)


class TestCreateSessionManager:
    """Creating the SessionManager from config."""

    def test_create_session_manager_with_config(self, tmp_path: Path) -> None:
        config = {
            "sandbox": {
                "images": {"3.12": "sandbox-base:3.12"},
                "defaults": {"python_version": "3.12", "timeout": 30},
                "data_dir": str(tmp_path / "data"),
            }
        }
        docker = FakeDockerClient()

        sm = create_session_manager(config, docker_client=docker)

        assert sm is not None
        session_id = sm.create_session(python_version="3.12")
        assert session_id.startswith("sess_")

    def test_create_session_manager_with_defaults(self) -> None:
        config = {"sandbox": {}}
        docker = FakeDockerClient()

        sm = create_session_manager(config, docker_client=docker)

        assert sm is not None


class TestCreateMCPApp:
    """Creating the MCP app from the factory."""

    def test_create_mcp_app_returns_app(self, tmp_path: Path) -> None:
        config = {
            "sandbox": {
                "images": {"3.12": "sandbox-base:3.12"},
                "defaults": {"python_version": "3.12", "timeout": 30},
                "data_dir": str(tmp_path / "data"),
            }
        }
        docker = FakeDockerClient()

        mcp_app = create_mcp_app(config, docker_client=docker)

        assert mcp_app is not None


class TestSetupSignalHandlers:
    """Signal handlers for graceful shutdown."""

    def test_setup_signal_handlers_registers_handlers(self) -> None:
        registered: dict[int, Any] = {}

        def fake_register(signum: int, handler: Any) -> None:
            registered[signum] = handler

        setup_signal_handlers(register=fake_register)

        assert signal.SIGINT in registered
        assert signal.SIGTERM in registered
