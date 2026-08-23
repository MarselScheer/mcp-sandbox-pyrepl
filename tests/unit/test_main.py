"""Tests for main.py — the entry point that wires everything together.

The main module is kept thin — it just reads config, wires dependencies,
and starts the server. All business logic lives in injectable components.
"""

from __future__ import annotations

import signal
from pathlib import Path
from typing import Any

from main import (
    DEFAULT_CONFIG,
    _merge_config,
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


class TestSetupSignalHandlers:
    """Signal handlers for graceful shutdown."""

    def test_setup_signal_handlers_registers_handlers(self) -> None:
        registered: dict[int, Any] = {}

        def fake_register(signum: int, handler: Any) -> None:
            registered[signum] = handler

        setup_signal_handlers(register=fake_register)

        assert signal.SIGINT in registered
        assert signal.SIGTERM in registered


# ──────────────────────────────────────────────────────────────────────
# Config merging
# ──────────────────────────────────────────────────────────────────────


class TestMergeConfig:
    """Merging user config into defaults."""

    def test_merge_config_merges_images(self) -> None:
        user_config: dict[str, Any] = {
            "sandbox": {
                "images": {
                    "3.13": "sandbox-base:3.13",
                },
            }
        }

        result = _merge_config(user_config, dict(DEFAULT_CONFIG))

        # Original images preserved, new one added
        sandbox = result["sandbox"]
        assert sandbox["images"]["3.12"] == "sandbox-base:3.12"
        assert sandbox["images"]["3.13"] == "sandbox-base:3.13"

    def test_merge_config_merges_defaults(self) -> None:
        user_config: dict[str, Any] = {
            "sandbox": {
                "defaults": {
                    "timeout": 60,
                },
            }
        }

        result = _merge_config(user_config, dict(DEFAULT_CONFIG))

        sandbox = result["sandbox"]
        assert sandbox["defaults"]["timeout"] == 60
        # Other defaults preserved
        assert sandbox["defaults"]["python_version"] == "3.12"

    def test_merge_config_overrides_data_dir(self) -> None:
        user_config: dict[str, Any] = {
            "sandbox": {
                "data_dir": "/custom/data/path",
            }
        }

        result = _merge_config(user_config, dict(DEFAULT_CONFIG))

        assert result["sandbox"]["data_dir"] == "/custom/data/path"


# ──────────────────────────────────────────────────────────────────────
# Config loading error handling
# ──────────────────────────────────────────────────────────────────────


class TestLoadConfigErrors:
    """Error handling in configuration loading."""

    def test_load_config_malformed_yaml_falls_back_to_defaults(
        self, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "bad_config.yaml"
        config_path.write_text("sandbox:\n  images:\n    invalid_yaml: [unclosed")

        config = load_config(str(config_path))

        assert "sandbox" in config
        assert "3.12" in config["sandbox"]["images"]
