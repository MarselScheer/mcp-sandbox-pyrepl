## Context

The `Namespace.exec()` method in `src/entrypoint.py` uses `compile()` with `'single'` mode to enable REPL display hook behavior (capturing evaluated expression results as the `display` list). When multi-line `def`/`class` blocks are present alongside invoking code, `'single'` mode fails with "multiple statements found while compiling a single statement" — the current fallback to `'exec'` mode silently loses display hook output.

This is a known CPython constraint: `compile()` with `'single'` mode accepts at most one compound statement (e.g., one `def`, one `class`, one `if` block) and cannot have multiple statement groups. The fix chosen for this change is documentation: callers must define `def`/`class` blocks in a separate `execute_python()` call from the code that uses them.

See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**
- Clearly inform callers of the `execute_python` MCP tool that `def`/`class`/async `def` blocks require a separate call from the invoking code
- Improve the `Namespace.exec()` docstring so future maintainers understand the restriction
- All existing tests and behaviors remain unchanged

**Non-Goals:**
- No changes to the compilation or execution logic in `entrypoint.py`
- No new parameters or API changes to tool signatures
- No automatic code splitting (that would be a future enhancement)
- No changes to spec requirements — this is purely documentation

## Decisions

| Decision | Rationale |
|---|---|
| **Docstring-only** — no code changes | The restriction is inherent to CPython's `compile()` with `'single'` mode. Automatically splitting code is a non-trivial engineering effort that would need to handle string literals containing `def`, nested definitions, and decorators. Documentation is the simplest fix that addresses the immediate problem (callers getting surprising results). |
| **Document at both the MCP tool and Namespace levels** | The MCP tool docstring is what callers (MCP clients, AI agents) see as the API contract. The Namespace docstring is for internal maintainers. Both levels are important — the MCP one for correctness expectations, the Namespace one for code comprehension. |
| **No test changes** | This change doesn't alter any runtime behavior. Adding tests for "the docstring says X" is brittle and provides no behavioral verification. |

## Risks / Trade-offs

- **[No enforced constraint]** The restriction is communicated via documentation only. A caller that doesn't read the docstring will still get silently incorrect behavior (missing display output). Mitigation: The error message from `compile()` with `'single'` mode is descriptive enough ("multiple statements found") to clue in an attentive caller. A future enhancement could detect this case and return a descriptive error message.
- **[Very small scope]** Documenting without any automatic handling leaves some user frustration unaddressed. This is an acceptable trade-off for the minimal effort/risk ratio. Revisit if this comes up frequently.

## Open Questions

None. The scope is clear and the approach is straightforward.