"""Smoke tests to verify the development toolchain is installed and working."""

import importlib


def test_pytest_is_importable() -> None:
    """Verify pytest is installed and importable."""
    import pytest  # noqa: F401


def test_ruff_is_importable() -> None:
    """Verify ruff is installed and importable."""
    importlib.import_module("ruff")


def test_ty_is_importable() -> None:
    """Verify ty is installed and importable."""
    importlib.import_module("ty")
