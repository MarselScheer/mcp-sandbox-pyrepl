## 1. Add missing scenario tests to TestInstallPackages (test_mcp_server.py)

- [ ] 1.1 Add test for version-specific package install: call `install_packages` with `[{"name": "markupsafe", "version": "2.1.0"}]`, then `execute_python` to verify `import markupsafe; markupsafe.__version__` returns `"2.1.0"`
- [ ] 1.2 Add test for multi-package install: call `install_packages` with two packages `[{"name": "six"}, {"name": "pytz"}]`, then `execute_python` to verify both are importable
- [ ] 1.3 Strengthen `test_install_packages_connects_and_disconnects_network`: after install completes, call `execute_python` with a network access attempt (e.g., `urllib.request.urlopen`) and assert it fails with a network error, proving network was disconnected

## 2. Strengthen existing smoke-level tests to verify importability

- [ ] 2.1 In `test_install_single_package`: after install succeeds, call `execute_python` to import the installed package (e.g., `import numpy; print(numpy.__version__)`) and verify it succeeds with a version string — replacing the current response-format-only assertions

## 3. Convert test_packages.py to use MCPToolHandler

- [ ] 3.1 Convert `test_install_and_use_package` in `test_packages.py` to use `MCPToolHandler.install_packages` instead of direct `container.exec_run` — keep the same container-scoped fixture (`class_container`) for session creation, then exercise the tool handler
- [ ] 3.2 Verify `test_package_isolation_between_sessions` stays as-is (uses two separate sessions, tests Docker-level isolation — doesn't go through the handler)

## 4. Run and verify

- [ ] 4.1 Run the integration test suite (`pytest tests/integration/`) and confirm all tests pass, including new and modified ones
- [ ] 4.2 Run the full test suite (`pytest tests/`) to check for regressions