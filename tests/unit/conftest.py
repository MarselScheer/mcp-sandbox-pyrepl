"""Shared fixtures and fakes for unit tests."""

from __future__ import annotations

import pytest

from entrypoint import (
    ExecResult,
    Namespace,
    NoOpTimeoutStrategy,
    RPCDispatcher,
    RPCDispatcherConfig,
)


class FakePackageInstaller:
    """A fake package installer for testing — no subprocess calls."""

    def __init__(self, result: ExecResult | None = None) -> None:
        self._result = result
        self.last_packages: list[dict[str, str]] = []

    def install(self, packages: list[dict[str, str]]) -> ExecResult:
        self.last_packages = packages
        if self._result is not None:
            return self._result
        return ExecResult(stdout=f"Installed {len(packages)} package(s)")


@pytest.fixture
def stub_dispatcher() -> RPCDispatcher:
    """A dispatcher wired with no-op fakes for routing-only tests."""
    return RPCDispatcher(
        namespace=Namespace(),
        timeout_strategy=NoOpTimeoutStrategy(),
        installer=FakePackageInstaller(),
        config=RPCDispatcherConfig(),
    )