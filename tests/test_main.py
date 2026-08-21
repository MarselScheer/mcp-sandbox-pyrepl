"""Tests for main.py — the entry point that wires everything together.

The main module is kept thin — it just reads config, wires dependencies,
and starts the server. All business logic lives in injectable components.

Tests that require Docker skip gracefully when Docker is unavailable.
"""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

import pytest

from main import (
    create_mcp_app,
    create_session_manager,
    load_config,
    sanitize_config_path,
    setup_signal_handlers,
)

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

    def test_create_session_manager_with_config(
        self, docker_available: bool, tmp_path: Path
    ) -> None:
        if not docker_available:
            pytest.skip("Docker not available")
        import docker

        from docker_adapter import RealDockerClient

        config = {
            "sandbox": {
                "images": {"3.12": "sandbox-base:3.12"},
                "defaults": {"python_version": "3.12", "timeout": 30},
                "data_dir": str(tmp_path / "data"),
            }
        }
        raw_client = docker.from_env()
        adapter = RealDockerClient(raw_client)

        sm = create_session_manager(config, docker_client=adapter)

        assert sm is not None
        session_id = sm.create_session(python_version="3.12")
        assert session_id.startswith("sess_")

    def test_create_session_manager_with_defaults(
        self, docker_available: bool
    ) -> None:
        if not docker_available:
            pytest.skip("Docker not available")
        import docker

        from docker_adapter import RealDockerClient

        config = {"sandbox": {}}
        raw_client = docker.from_env()
        adapter = RealDockerClient(raw_client)

        sm = create_session_manager(config, docker_client=adapter)

        assert sm is not None


class TestCreateMCPApp:
    """Creating the MCP app from the factory."""

    def test_create_mcp_app_returns_app(
        self, docker_available: bool, tmp_path: Path
    ) -> None:
        if not docker_available:
            pytest.skip("Docker not available")
        import docker

        from docker_adapter import RealDockerClient

        config = {
            "sandbox": {
                "images": {"3.12": "sandbox-base:3.12"},
                "defaults": {"python_version": "3.12", "timeout": 30},
                "data_dir": str(tmp_path / "data"),
            }
        }
        raw_client = docker.from_env()
        adapter = RealDockerClient(raw_client)

        mcp_app = create_mcp_app(config, docker_client=adapter)

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
