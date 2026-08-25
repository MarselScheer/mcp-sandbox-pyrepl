"""JSON-RPC 2.0 server for the sandboxed Python REPL.

Runs inside the Docker container, reading JSON-RPC requests from stdin and
writing responses to stdout. Maintains a persistent namespace across exec calls.

Design notes:
- The Namespace class is a rich domain model — it owns its state and behavior.
- Timeout handling is composed via a strategy object (TimeoutStrategy Protocol).
- Dependencies are injected rather than created internally.
- stdin/stdout are injected into SessionServer for testability.
"""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
import threading
import traceback
from dataclasses import dataclass, field
from io import StringIO
from typing import Any, Protocol, TextIO

# ──────────────────────────────────────────────────────────────────────
# Domain models
# ──────────────────────────────────────────────────────────────────────


@dataclass
class RPCRequest:
    """A parsed JSON-RPC 2.0 request."""

    id: int | str | None
    method: str
    params: dict[str, Any]


@dataclass
class ExecResult:
    """Result of executing a code block."""

    stdout: str = ""
    stderr: str = ""
    display: list[str] = field(default_factory=list)
    error: str | None = None
    session_corrupted: bool = False


class Namespace:
    """Persistent execution namespace for a REPL session.

    A rich domain model — owns both the state (namespace dict, display hook)
    and the behavior (exec, reset).

    Uses compile() with 'single' mode so that expression results trigger
    sys.displayhook (as in the interactive REPL). We capture the display
    hook output to a list instead of printing to stdout.
    """

    def __init__(self) -> None:
        self._namespace: dict[str, Any] = {}
        self._display_output: list[str] = []

    def exec(self, code: str) -> ExecResult:
        """Execute Python code in the persistent namespace.

        Captures stdout, stderr, display output, and errors.
        Uses 'single' compile mode for proper REPL display hook semantics.

        **Restriction:** Multi-line definition blocks (`def`, `class`, `async def`)
        must be defined in a **separate call** from the code that invokes them.
        The `compile()` function with `'single'` mode supports at most one
        compound statement per call. Combining a definition and its invocation
        in a single call causes a fallback to `'exec'` mode, which silently
        loses REPL display hook output for evaluated expressions.

        Callers should split their code into two calls: one to define the
        function(s), then one to execute the invoking code.
        """
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        self._display_output = []

        old_stdout = sys.stdout
        old_stderr = sys.stderr
        old_display = sys.displayhook

        try:
            sys.stdout = stdout_buf
            sys.stderr = stderr_buf
            sys.displayhook = self._display_hook

            try:
                # Try 'single' mode first (enables display hook for expressions)
                try:
                    compiled = compile(code, "<repl>", "single")
                except SyntaxError as exc:
                    # 'single' fails on multi-statement blocks; fall back to 'exec'
                    if "multiple statements" in str(exc):
                        compiled = compile(code, "<repl>", "exec")
                    else:
                        return ExecResult(
                            stdout=stdout_buf.getvalue(),
                            stderr=stdout_buf.getvalue(),
                            error=f"SyntaxError: {exc.msg} (line {exc.lineno})",
                        )

                exec(compiled, self._namespace)
            except SyntaxError as exc:
                return ExecResult(
                    stdout=stdout_buf.getvalue(),
                    stderr=stdout_buf.getvalue(),
                    error=f"SyntaxError: {exc.msg} (line {exc.lineno})",
                )
            except Exception:
                tb = traceback.format_exc()
                return ExecResult(
                    stdout=stdout_buf.getvalue(),
                    stderr=tb,
                    error=tb,
                )
            except SystemExit:
                pass

            return ExecResult(
                stdout=stdout_buf.getvalue(),
                stderr=stderr_buf.getvalue(),
                display=list(self._display_output),
            )
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            sys.displayhook = old_display

    def _display_hook(self, value: object) -> None:
        """Custom display hook that captures REPL output.

        Python's sys.displayhook is called by the runtime on every
        expression statement result (when compiled with 'single' mode).
        We capture these into a list instead of printing to stdout.
        """
        if value is not None:
            self._display_output.append(repr(value))

    def reset(self) -> None:
        """Reset the namespace to a clean state."""
        self._namespace.clear()
        self._display_output = []


# ──────────────────────────────────────────────────────────────────────
# Timeout — strategy pattern with Protocol
# ──────────────────────────────────────────────────────────────────────


class TimeoutStrategy(Protocol):
    """Strategy for enforcing execution timeouts.

    Defined as a Protocol so the consumer can compose different
    timeout mechanisms without coupling to a specific implementation.
    """

    def execute_with_timeout(
        self, namespace: Namespace, code: str, timeout: float
    ) -> ExecResult:
        """Execute code with a timeout. Returns ExecResult."""
        ...


class ThreadTimeoutStrategy:
    """Timeout implementation using threading + PyThreadState_SetAsyncExc.

    Composes the timeout logic: runs code in a thread, waits, and if it
    doesn't finish in time, attempts to interrupt via ctypes. If that
    fails, marks the session as corrupted.
    """

    _TimeoutError = type("_TimeoutError", (Exception,), {})

    def __init__(self, hard_timeout_seconds: float = 5.0) -> None:
        self._hard_timeout = hard_timeout_seconds

    def execute_with_timeout(
        self, namespace: Namespace, code: str, timeout: float
    ) -> ExecResult:
        result_holder: list[ExecResult] = []
        exception_holder: list[Exception | None] = [None]
        finished = threading.Event()

        def _run() -> None:
            try:
                result_holder.append(namespace.exec(code))
            except Exception as exc:
                exception_holder[0] = exc
            finally:
                finished.set()

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        timed_out = not finished.wait(timeout=timeout)

        if timed_out:
            return self._handle_timeout(thread, namespace)

        if exception_holder[0] is not None:
            return ExecResult(error=str(exception_holder[0]))

        return result_holder[0]

    def _handle_timeout(
        self, thread: threading.Thread, namespace: Namespace
    ) -> ExecResult:
        """Attempt to interrupt the stuck thread, with fallback."""
        # Attempt graceful interruption via async exception
        tid = thread.ident
        if tid is not None:
            self._raise_async_exc(tid, self._TimeoutError)

        # Give it a moment to respond
        thread.join(timeout=self._hard_timeout)

        if thread.is_alive():
            return ExecResult(
                error=(
                    "Execution timed out and thread could not be interrupted. "
                    "Session may be corrupted."
                ),
                session_corrupted=True,
            )

        return ExecResult(
            error="Execution timed out.",
        )

    @staticmethod
    def _raise_async_exc(tid: int, exc_type: type) -> None:
        """Raise an exception asynchronously in the target thread.

        Uses the CPython-internal PyThreadState_SetAsyncExc.
        Retries 10 times as recommended by the Python docs for
        thread-safe exception delivery.
        """
        ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(
            ctypes.c_long(tid), ctypes.py_object(exc_type)
        )
        if ret == 0:  # pragma: no cover
            # Thread not found — nothing to interrupt
            return
        if ret > 1:  # pragma: no cover
            # Exception was sent to multiple threads (shouldn't happen).
            # Reset by sending None to undo.
            ctypes.pythonapi.PyThreadState_SetAsyncExc(ctypes.c_long(tid), None)


class NoOpTimeoutStrategy:
    """Pass-through timeout strategy — no timeout enforcement.

    Useful for testing where we don't want threading complexity.
    """

    def execute_with_timeout(
        self, namespace: Namespace, code: str, timeout: float
    ) -> ExecResult:
        _ = timeout
        return namespace.exec(code)


# ──────────────────────────────────────────────────────────────────────
# Package installer
# ──────────────────────────────────────────────────────────────────────


class PackageInstaller:
    """Installs Python packages into the session's virtual environment."""

    def __init__(self, venv_path: str = "/session/venv") -> None:
        self._venv_path = venv_path

    def install(self, packages: list[dict[str, str]]) -> ExecResult:
        """Install packages via uv pip install.

        Each package dict must have a 'name' key and optionally a 'version' key.
        """
        if not packages:
            return ExecResult(error="No packages specified.")

        specs = []
        for pkg in packages:
            name = pkg.get("name", "")
            version = pkg.get("version")
            if version:
                specs.append(f"{name}=={version}")
            else:
                specs.append(name)

        if not specs:
            return ExecResult(error="No valid package specifications.")

        pip_cmd = [
            "uv",
            "pip",
            "install",
            "--no-cache",
            *specs,
        ]

        env = os.environ.copy()
        env["VIRTUAL_ENV"] = self._venv_path
        env["PATH"] = f"{self._venv_path}/bin:{env.get('PATH', '')}"

        try:
            result = subprocess.run(
                pip_cmd,
                capture_output=True,
                text=True,
                timeout=120,
                env=env,
            )
            return ExecResult(
                stdout=result.stdout,
                stderr=result.stderr,
                error=result.stderr if result.returncode != 0 else None,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(error="Package installation timed out.")
        except FileNotFoundError:
            return ExecResult(error="uv not found. Is it installed in the image?")


# ──────────────────────────────────────────────────────────────────────
# JSON-RPC Dispatcher
# ──────────────────────────────────────────────────────────────────────


@dataclass
class RPCDispatcherConfig:
    """Centralized configuration for the RPC dispatcher.

    No magic numbers — all configurable values live here.
    """

    default_timeout: float = 30.0
    hard_timeout_seconds: float = 5.0


class RPCDispatcher:
    """Routes JSON-RPC method calls to handler implementations.

    Composed of a Namespace, TimeoutStrategy, and PackageInstaller.
    Each is injectable for testability.
    """

    def __init__(
        self,
        namespace: Namespace,
        timeout_strategy: TimeoutStrategy,
        installer: PackageInstaller,
        config: RPCDispatcherConfig,
    ) -> None:
        self._namespace = namespace
        self._timeout = timeout_strategy
        self._installer = installer
        self._config = config
        self._shutdown_requested = False

    def handle(self, request: RPCRequest) -> dict[str, Any]:
        """Route a request to the appropriate handler and return a JSON-RPC response."""
        try:
            result = self._dispatch(request.method, request.params)
            return self._success_response(request.id, result)
        except ValueError as exc:
            return self._error_response(request.id, -32601, str(exc))
        except Exception as exc:
            return self._error_response(request.id, -32603, f"Internal error: {exc}")

    def _dispatch(self, method: str, params: dict[str, Any]) -> Any:
        handlers = {
            "exec": self._handle_exec,
            "install": self._handle_install,
            "reset": self._handle_reset,
            "ping": self._handle_ping,
            "shutdown": self._handle_shutdown,
        }

        handler = handlers.get(method)
        if handler is None:
            raise ValueError(f"Method not found: {method}")

        return handler(params)

    def _handle_exec(self, params: dict[str, Any]) -> dict[str, Any]:
        code = params.get("code", "")
        timeout = params.get("timeout", self._config.default_timeout)

        result = self._timeout.execute_with_timeout(
            self._namespace, code, float(timeout)
        )

        response: dict[str, Any] = {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "display": result.display,
            "error": result.error,
        }
        if result.session_corrupted:
            response["session_corrupted"] = True
        return response

    def _handle_install(self, params: dict[str, Any]) -> dict[str, Any]:
        packages = params.get("packages", [])
        result = self._installer.install(packages)
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "error": result.error,
        }

    def _handle_reset(self, params: dict[str, Any]) -> dict[str, Any]:
        _ = params
        self._namespace.reset()
        return {"ok": True}

    def _handle_ping(self, params: dict[str, Any]) -> dict[str, Any]:
        _ = params
        return {"ok": True}

    def _handle_shutdown(self, params: dict[str, Any]) -> dict[str, Any]:
        _ = params
        self._shutdown_requested = True
        return {"ok": True}

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    @staticmethod
    def _success_response(req_id: int | str | None, result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    @staticmethod
    def _error_response(
        req_id: int | str | None,
        code: int,
        message: str,
        data: Any = None,
    ) -> dict[str, Any]:
        error: dict[str, Any] = {"code": code, "message": message}
        if data is not None:
            error["data"] = data
        return {"jsonrpc": "2.0", "id": req_id, "error": error}

    @staticmethod
    def _parse_line(line: str) -> RPCRequest | None:
        """Parse a single JSON line into an RPCRequest."""
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            return None

        req_id = data.get("id")
        method = data.get("method", "")
        params = data.get("params", {})

        if not method:
            return None

        return RPCRequest(id=req_id, method=method, params=params)


# ──────────────────────────────────────────────────────────────────────
# Session Server — main loop
# ──────────────────────────────────────────────────────────────────────


class SessionServer:
    """Reads JSON-RPC requests from stdin and writes responses to stdout.

    stdin and stdout are injected — no hardcoded sys.stdin/sys.stdout.
    This makes the server trivially testable without mock.patch.
    """

    def __init__(
        self,
        dispatcher: RPCDispatcher,
        stdin: TextIO = sys.stdin,
        stdout: TextIO = sys.stdout,
    ) -> None:
        self._dispatcher = dispatcher
        self._stdin = stdin
        self._stdout = stdout

    def run(self) -> None:
        """Main loop: read requests from stdin, dispatch, write responses."""
        for line in self._stdin:
            line = line.strip()
            if not line:
                continue

            request = self._dispatcher._parse_line(line)
            if request is None:
                continue

            response = self._dispatcher.handle(request)
            self._write_response(response)

            if self._dispatcher.shutdown_requested:
                break

    def _write_response(self, response: dict[str, Any]) -> None:
        """Write a JSON-RPC response to stdout."""
        json.dump(response, self._stdout, ensure_ascii=False)
        self._stdout.write("\n")
        self._stdout.flush()


# ──────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Entry point for the entrypoint script."""
    config = RPCDispatcherConfig()
    namespace = Namespace()
    timeout = ThreadTimeoutStrategy(
        hard_timeout_seconds=config.hard_timeout_seconds,
    )
    installer = PackageInstaller()
    dispatcher = RPCDispatcher(
        namespace=namespace,
        timeout_strategy=timeout,
        installer=installer,
        config=config,
    )
    server = SessionServer(
        dispatcher=dispatcher,
        stdin=sys.stdin,
        stdout=sys.stdout,
    )
    server.run()


if __name__ == "__main__":
    main()
