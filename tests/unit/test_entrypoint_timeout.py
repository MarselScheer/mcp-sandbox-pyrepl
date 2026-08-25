"""Tests for the execution timeout mechanism.

The ThreadTimeoutStrategy composes namespace execution with a timeout.
We test the behavior: what happens when code times out, and what happens
when the session is corrupted.
"""

from __future__ import annotations

from entrypoint import (
    ExecResult,
    Namespace,
    NoOpTimeoutStrategy,
    ThreadTimeoutStrategy,
)


class _RaisingNamespace:
    """A namespace stub that raises on exec.

    Used to test the defensive ``except Exception`` path in
    ``ThreadTimeoutStrategy.execute_with_timeout._run()``, which captures
    unexpected exceptions that propagate *out of* ``namespace.exec()``
    (as opposed to exceptions handled *inside* ``Namespace.exec()``).
    """

    def exec(self, code: str) -> ExecResult:
        _ = code
        msg = "Simulated internal error"
        raise RuntimeError(msg)


class TestNoOpTimeoutStrategy:
    """The NoOp strategy is a pass-through — useful as a building block."""

    def test_executes_code_without_timeout(self) -> None:
        namespace = Namespace()
        strategy = NoOpTimeoutStrategy()

        result = strategy.execute_with_timeout(namespace, "2 + 2", timeout=30)

        assert result.display == ["4"]
        assert result.error is None

    def test_ignores_timeout_value(self) -> None:
        namespace = Namespace()
        strategy = NoOpTimeoutStrategy()

        result = strategy.execute_with_timeout(namespace, "print('hi')", timeout=0)

        assert result.stdout == "hi\n"


class TestThreadTimeoutStrategy:
    """Behavior-driven tests for the thread-based timeout strategy."""

    def test_quick_code_completes_normally(self) -> None:
        namespace = Namespace()
        strategy = ThreadTimeoutStrategy(hard_timeout_seconds=1.0)

        result = strategy.execute_with_timeout(namespace, "2 + 2", timeout=10)

        assert result.display == ["4"]
        assert result.error is None

    def test_code_that_times_out_returns_error(self) -> None:
        namespace = Namespace()
        strategy = ThreadTimeoutStrategy(hard_timeout_seconds=0.5)

        result = strategy.execute_with_timeout(
            namespace, "x = 0\nwhile True: x += 1", timeout=0.1
        )

        assert result.error is not None
        assert "timed out" in result.error.lower()

    def test_multiple_quick_executions_work(self) -> None:
        namespace = Namespace()
        strategy = ThreadTimeoutStrategy(hard_timeout_seconds=1.0)

        strategy.execute_with_timeout(namespace, "x = 1", timeout=10)
        strategy.execute_with_timeout(namespace, "x += 1", timeout=10)
        result = strategy.execute_with_timeout(namespace, "print(x)", timeout=10)

        assert result.stdout == "2\n"

    def test_state_preserved_after_normal_timeout(self) -> None:
        """A normal timeout (thread interrupted) doesn't corrupt the session."""
        namespace = Namespace()
        strategy = ThreadTimeoutStrategy(hard_timeout_seconds=1.0)

        strategy.execute_with_timeout(
            namespace, "import time; time.sleep(10)", timeout=0.1
        )

        # Subsequent execution should still work
        result = strategy.execute_with_timeout(
            namespace, "print('recovered')", timeout=10
        )
        assert result.stdout == "recovered\n"

    def test_exception_from_namespace_is_captured(self) -> None:
        """When namespace.exec() raises an unexpected exception, it's captured.

        ``Namespace.exec()`` handles standard Python errors internally
        (e.g. ``ZeroDivisionError``) and returns an ``ExecResult`` with
        the error string set.  But if an unexpected ``Exception`` propagates
        *out of* ``exec()``, the ``_run()`` thread catches it in the
        ``except Exception as exc: exception_holder[0] = exc`` clause and
        returns it as the error.  This tests that defensive path.
        """
        namespace = _RaisingNamespace()
        strategy = ThreadTimeoutStrategy(hard_timeout_seconds=1.0)

        result = strategy.execute_with_timeout(namespace, "any code", timeout=10)

        assert result.error is not None
        assert "Simulated internal error" in result.error
        assert result.session_corrupted is False

    def test_timed_out_thread_is_interrupted(self) -> None:
        """When the async exception interrupts the thread, the plain timeout error is returned.

        After the soft timeout fires, ``_handle_timeout`` raises a
        ``_TimeoutError`` via ``PyThreadState_SetAsyncExc`` in the stuck
        thread.  If the thread responds (e.g. a tight Python loop is
        interrupted at a bytecode instruction boundary), it catches the
        exception in ``_run()``'s ``except Exception`` clause, sets the
        ``finished`` event, and terminates.  ``thread.join()`` then sees a
        dead thread, so ``_handle_timeout`` returns the plain
        ``ExecResult(error="Execution timed out.")`` **without**
        ``session_corrupted=True``.

        ``"x = 0\\nwhile True: x += 1"`` is used instead of a single-line
        ``while True: pass`` because the latter raises ``SyntaxError`` in
        ``'single'`` compile mode (not "multiple statements", so it doesn't
        fall through to ``'exec'``).  The multi-line version triggers the
        ``'exec'`` fallback and creates a tight busy loop that is reliably
        interruptible by ``PyThreadState_SetAsyncExc``.

        This test verifies that specific outcome through the public
        ``execute_with_timeout`` interface.
        """
        namespace = Namespace()
        strategy = ThreadTimeoutStrategy(hard_timeout_seconds=2.0)

        result = strategy.execute_with_timeout(
            namespace, "x = 0\nwhile True: x += 1", timeout=0.1
        )

        assert result.error == "Execution timed out."
        assert result.session_corrupted is False
