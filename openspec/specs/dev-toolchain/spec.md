# Dev Toolchain

## Purpose

Developer toolchain configuration for the Python repl sandbox project. Provides
standardized tooling for testing, linting, formatting, type checking, and
unified developer workflows.

## Requirements

### Requirement: pytest Test Runner
The system SHALL use pytest as the test runner with coverage reporting.

#### Scenario: Run all tests
- **GIVEN** the project repository
- **WHEN** the developer runs `make test`
- **THEN** all tests are executed with pytest
- **AND** coverage reports are generated

### Requirement: ruff Linting and Formatting
The system SHALL use ruff for both linting and code formatting.

#### Scenario: Lint all source code
- **GIVEN** the project repository
- **WHEN** the developer runs `make lint`
- **THEN** ruff checks all source files for lint violations

#### Scenario: Format all source code
- **GIVEN** the project repository
- **WHEN** the developer runs `make format`
- **THEN** ruff formats all source files in place

### Requirement: ty Static Type Checking
The system SHALL use `ty` for static type checking.

#### Scenario: Run type checker
- **GIVEN** the project repository
- **WHEN** the developer runs `make typecheck`
- **THEN** `ty` checks all source files for type errors

### Requirement: Makefile Unified Workflow
The system SHALL provide a Makefile that unifies the developer workflow.

#### Scenario: Run all quality checks
- **GIVEN** the project repository
- **WHEN** the developer runs `make check`
- **THEN** all quality checks (lint, typecheck, test) are executed in sequence