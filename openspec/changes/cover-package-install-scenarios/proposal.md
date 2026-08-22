## Why

The package management spec defines 7 scenarios, but only 5 are tested — and the two at the MCP tool handler level (`test_mcp_server.py`) never verify that packages are actually importable after installation. This leaves version-specific install, multi-package install, and network isolation after install without proper end-to-end verification through the tool interface that users call.

## What Changes

- Add MCP tool-level integration tests that cover the two untested spec scenarios:
  - **Version-specific install**: install `pandas==2.0.0`, verify `pandas.__version__` returns `"2.0.0"`
  - **Multi-package install**: install `numpy` + `scipy==1.11.0` in a single call, verify both importable
- Strengthen the existing `test_install_packages_connects_and_disconnects_network` test to actually verify that:
  - Network is disconnected after install completes
  - Subsequent `execute_python` code that attempts network access fails
- Convert the existing direct-Docker tests in `test_packages.py` to go through `MCPToolHandler.install_packages` (the tool contract) rather than calling `container.exec_run` directly, so they test the actual public API

## Capabilities

This change adds no new capabilities and modifies no existing requirements. It is a pure test-coverage improvement — all scenarios are already specified in the package management spec. Set `skip_specs: true` in the change's `.openspec.yaml`.

### New Capabilities

None.

### Modified Capabilities

None. All scenarios are already specified in `openspec/specs/package-management/spec.md`. This change only adds missing tests for existing requirements.

## Impact

- **Tests**: New and modified tests in `tests/integration/test_mcp_server.py` (MCP tool handler level)
- **Potential**: If the MCP tool handler's `install_packages` method doesn't fully work with version specifiers or multi-package calls, these tests will reveal that gap and may require minor fixes to the handler or the `PackageInstaller`