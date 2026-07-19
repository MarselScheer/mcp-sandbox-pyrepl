"""Tests for the execution timeout mechanism.

The ThreadTimeoutStrategy composes namespace execution with a timeout.
We test the behavior: what happens when code times out, and what happens
when the session is corrupted.
"""

from __future__ import annotations

from entrypoint import (
    Namespace,
    NoOpTimeoutStrategy,
    ThreadTimeoutStrategy,
)


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
            namespace, "import time; time.sleep(10)", timeout=0.1
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
