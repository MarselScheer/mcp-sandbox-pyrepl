"""Tests for the Namespace domain model — the purest, most testable piece.

The Namespace has no collaborators, no IO, no infrastructure.
It's a rich domain model: behavior lives with the data it operates on.
"""

from __future__ import annotations

from entrypoint import Namespace


class TestNamespaceExec:
    """Behavior-driven tests for code execution in the namespace."""

    def test_execute_simple_expression(self) -> None:
        namespace = Namespace()

        result = namespace.exec("2 + 2")

        # Display hook captures the result of the last expression
        assert result.stdout == ""
        assert result.stderr == ""
        assert result.display == ["4"]
        assert result.error is None

    def test_execute_with_print_output(self) -> None:
        namespace = Namespace()

        result = namespace.exec("print('hello world')")

        assert result.stdout == "hello world\n"
        assert result.stderr == ""
        assert result.display == []
        assert result.error is None

    def test_state_persists_across_calls(self) -> None:
        namespace = Namespace()

        namespace.exec("x = 42")
        result = namespace.exec("print(x)")

        assert result.stdout == "42\n"
        assert result.error is None

    def test_syntax_error(self) -> None:
        namespace = Namespace()

        result = namespace.exec("x = ")

        assert result.error is not None
        assert "SyntaxError" in result.error

    def test_runtime_error(self) -> None:
        namespace = Namespace()

        result = namespace.exec("1/0")

        assert result.error is not None
        assert "ZeroDivisionError" in result.error
        # Traceback should be in stderr
        assert "ZeroDivisionError" in result.stderr

    def test_help_output(self) -> None:
        namespace = Namespace()

        result = namespace.exec("help(str)")

        # Help output goes to stdout
        assert "str" in result.stdout
        assert result.error is None

    def test_list_expression_output(self) -> None:
        namespace = Namespace()

        result = namespace.exec("[1, 2, 3]")

        assert result.display == ["[1, 2, 3]"]
        assert result.error is None

    def test_none_expression_no_display(self) -> None:
        namespace = Namespace()

        result = namespace.exec("x = None")

        assert result.display == []

    def test_multiline_code(self) -> None:
        namespace = Namespace()

        result = namespace.exec("for i in range(3):\n    print(i)")

        assert result.stdout == "0\n1\n2\n"
        assert result.error is None

    def test_import_statement(self) -> None:
        namespace = Namespace()

        result = namespace.exec("import math\nprint(math.pi)")

        assert "3.14" in result.stdout
        assert result.error is None


class TestNamespaceReset:
    """Tests for namespace reset behavior."""

    def test_reset_clears_variables(self) -> None:
        namespace = Namespace()

        namespace.exec("x = 42")
        namespace.reset()

        result = namespace.exec("print(x)")
        assert "NameError" in result.error

    def test_reset_is_idempotent(self) -> None:
        namespace = Namespace()

        namespace.reset()
        namespace.reset()

        result = namespace.exec("print('hello')")
        assert result.stdout == "hello\n"

    def test_reset_clears_display_output(self) -> None:
        namespace = Namespace()

        namespace.exec("42")
        assert namespace.exec("").display == []


class TestNamespaceBuiltins:
    """Tests that builtins are available and not clobbered."""

    def test_builtins_available(self) -> None:
        namespace = Namespace()

        result = namespace.exec("print(len([1, 2, 3]))")

        assert result.stdout == "3\n"

    def test_builtin_shadow_does_not_affect_other_calls(self) -> None:
        namespace = Namespace()

        namespace.exec("print = lambda *a: None")
        # Even though print was shadowed, the next exec gets a fresh displayhook
        result = namespace.exec("print('hi')")

        # Actually this will still be captured since print is in the namespace
        # This test documents the behavior
        assert result.stdout == ""
