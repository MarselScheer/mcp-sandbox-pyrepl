## 1. Add missing scenario tests to TestInstallPackages (test_mcp_server.py)

- [x] 1.1 Add test for version-specific package install: call `install_packages` with `[{"name": "markupsafe", "version": "2.1.0"}]`, then `execute_python` to verify `import markupsafe; markupsafe.__version__` returns `"2.1.0"`
- [x] 1.2 Add test for multi-package install: call `install_packages` with two packages `[{"name": "six"}, {"name": "pytz"}]`, then `execute_python` to verify both are importable
- [x] 1.3 Strengthen `test_install_packages_connects_and_disconnects_network`: after install completes, call `execute_python` with a network access attempt and assert it fails with a network error, proving network was disconnected

## 2. Strengthen existing smoke-level tests to verify importability

- [x] 2.1 Delete `test_install_single_package` (was superseded by `test_version_specific_install` and `test_multi_package_install` — redundant, adds no unique coverage)

## 3. Convert test_packages.py to use MCPToolHandler

- [x] 3.1 Convert `test_install_and_use_package` in `test_packages.py` to use `MCPToolHandler.install_packages` instead of direct `container.exec_run` — keep the same container-scoped fixture (`class_container`) for session creation, then exercise the tool handler
- [x] 3.2 Verify `test_package_isolation_between_sessions` stays as-is (uses two separate sessions, tests Docker-level isolation — doesn't go through the handler)

## 4. Run and verify

- [x] 4.1 Run the integration test suite (`pytest tests/integration/`) and confirm all tests pass, including new and modified ones
- [x] 4.2 Run the full test suite (`pytest tests/`) to check for regressions