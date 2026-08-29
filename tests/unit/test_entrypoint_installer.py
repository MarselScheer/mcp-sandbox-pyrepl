"""Tests for PackageInstaller — the uv pip install wrapper.

Because subprocess.run is injected (defaulting to the real thing), the
arrange phase is a 1-line fake — no mock.patch, no monkeypatch.
Behaviors: spec building, environment setup, result mapping, and error paths.
"""

from __future__ import annotations

import subprocess

from entrypoint import PackageInstaller

# ──────────────────────────────────────────────────────────────────────
# Fakes
# ──────────────────────────────────────────────────────────────────────


class FakeRunProcess:
    """A fake for subprocess.run — records the call, returns or raises as configured.

    The arrange phase stays at 1-2 lines: FakeRunProcess(result=...) or
    FakeRunProcess(error=TimeoutExpired(...)).
    """

    def __init__(
        self,
        result: subprocess.CompletedProcess[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._result = result
        self._error = error
        self.last_cmd: list[str] = []
        self.last_kwargs: dict[str, object] = {}

    def __call__(
        self, cmd: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        self.last_cmd = cmd
        self.last_kwargs = kwargs
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def ok_result(
    stdout: str = "Installed", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """A successful subprocess result."""
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=stdout,
        stderr=stderr,
    )


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


class TestPackageInstallerSpecBuilding:
    """Package dicts become uv pip install arguments."""

    def test_install_with_version_specifier(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"name": "pandas", "version": "2.0.3"}])

        assert result.error is None
        assert result.stdout == "Installed"
        assert run.last_cmd == ["uv", "pip", "install", "--no-cache", "pandas==2.0.3"]

    def test_install_without_version(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"name": "requests"}])

        assert result.error is None
        assert run.last_cmd == ["uv", "pip", "install", "--no-cache", "requests"]

    def test_install_multiple_packages_mixed(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        installer.install(
            [{"name": "requests"}, {"name": "pandas", "version": "2.0.3"}]
        )

        assert run.last_cmd == [
            "uv",
            "pip",
            "install",
            "--no-cache",
            "requests",
            "pandas==2.0.3",
        ]


class TestPackageInstallerEnvironment:
    """The venv is wired into the subprocess environment."""

    def test_install_sets_virtual_env_and_path(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        installer.install([{"name": "requests"}])

        env = run.last_kwargs["env"]
        assert isinstance(env, dict)
        assert env["VIRTUAL_ENV"] == "/session/venv"
        assert env["PATH"].startswith("/session/venv/bin:")

    def test_install_uses_custom_venv_path(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(venv_path="/custom/venv", run_process=run)

        installer.install([{"name": "requests"}])

        env = run.last_kwargs["env"]
        assert isinstance(env, dict)
        assert env["VIRTUAL_ENV"] == "/custom/venv"
        assert env["PATH"].startswith("/custom/venv/bin:")

    def test_install_runs_with_capture_and_timeout(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        installer.install([{"name": "requests"}])

        assert run.last_kwargs["capture_output"] is True
        assert run.last_kwargs["text"] is True
        assert run.last_kwargs["timeout"] == 120


class TestPackageInstallerErrorPaths:
    """Validation and failure handling."""

    def test_install_empty_packages_returns_error(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        result = installer.install([])

        assert result.error == "No packages specified."
        assert run.last_cmd == []  # subprocess never called

    def test_install_no_valid_specs_returns_error(self) -> None:
        run = FakeRunProcess(result=ok_result())
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"version": "1.0"}, {}])

        assert result.error == "No valid package specifications."
        assert run.last_cmd == []

    def test_install_timeout_returns_error(self) -> None:
        run = FakeRunProcess(
            error=subprocess.TimeoutExpired(cmd=["uv"], timeout=120)
        )
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"name": "requests"}])

        assert result.error == "Package installation timed out."
        assert result.stdout == ""

    def test_install_uv_not_found_returns_error(self) -> None:
        run = FakeRunProcess(error=FileNotFoundError())
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"name": "requests"}])

        assert result.error == "uv not found. Is it installed in the image?"

    def test_install_failure_returncode_sets_error(self) -> None:
        run = FakeRunProcess(
            result=subprocess.CompletedProcess(
                args=[],
                returncode=1,
                stdout="",
                stderr="error: no such package",
            )
        )
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"name": "requests"}])

        assert result.error == "error: no such package"
        assert result.stderr == "error: no such package"

    def test_install_success_propagates_stdout_and_stderr(self) -> None:
        run = FakeRunProcess(
            result=ok_result(stdout="Installed 2 packages", stderr="warning: foo")
        )
        installer = PackageInstaller(run_process=run)

        result = installer.install([{"name": "requests"}, {"name": "pandas"}])

        assert result.error is None
        assert result.stdout == "Installed 2 packages"
        assert result.stderr == "warning: foo"
