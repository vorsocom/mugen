# ACP Style Guide

This guide captures formatting conventions used throughout `mugen/core/plugin/acp`.

## Baseline Formatting
- Start modules with a double-quoted docstring summary.
  Example: `mugen/core/plugin/acp/api/crud.py:1`
- Use 4-space indentation, no tabs, and no trailing whitespace.
- Keep lines at the workspace formatter limit.
  In this repo, `.vscode/settings.json` configures Black with `--line-length 88`.
  Some legacy ACP lines are wider; use `--max-line-length 100` only when matching
  untouched legacy formatting is explicitly required.
- Prefer double quotes for strings and docstrings.

## Module Layout
- Use this top shape when applicable:
1. Module docstring
2. Optional `__all__`
3. Imports grouped with blank lines
4. Pylint pragmas
5. Helpers/classes/functions

Examples:
- Single-export module with `__all__`: `mugen/core/plugin/acp/service/tenant.py:3`
- Package export module with list-style `__all__`: `mugen/core/plugin/acp/model/__init__.py:3`
- Rich endpoint module with helpers and decorators: `mugen/core/plugin/acp/api/crud.py:25`

## Import Style
- Group imports in this order: stdlib, third-party, `mugen.*` internal.
  Example: `mugen/core/plugin/acp/api/crud.py:3`
- Use parenthesized multi-line imports when long.
  Example: `mugen/core/plugin/acp/contract/service/__init__.py:24`
- Keep one import per line unless grouped imports are natural and short.

## Typing and Signatures
- Add explicit type annotations for parameters and returns.
  Example: `mugen/core/plugin/acp/api/crud.py:60`
- Prefer modern unions (`| None`) in new ACP runtime code.
  Example: `mugen/core/plugin/acp/domain/tenant.py:17`
- For forward-referenced model symbols in `Mapped[...]` annotations, prefer
  `TYPE_CHECKING` imports over blanket inline ignores when practical.
  Examples:
  `mugen/core/plugin/billing/model/account.py:19`,
  `mugen/core/plugin/billing/model/price.py:26`,
  `mugen/core/plugin/billing/model/subscription.py:24`,
  `mugen/core/plugin/ops_vpn/model/vendor.py:25`
- Keep dependency-provider defaults as lambda providers in ACP endpoint/service style.
  Example: `mugen/core/plugin/acp/api/crud.py:65`

## Multi-line Formatting
- Break long calls/constructors with one argument per line and trailing commas.
  Example: `mugen/core/plugin/acp/model/global_role.py:20`
- Format long f-strings and descriptions by adjacent string literal wrapping.
  Example: `mugen/core/plugin/acp/api/action.py:72`

## Class and Dataclass Style
- Add class docstrings for all public classes.
  Example: `mugen/core/plugin/acp/service/authorization.py:24`
- For dataclass-style entity fields, separate fields with blank lines for readability.
  Example: `mugen/core/plugin/acp/domain/tenant.py:17`

## Pragmas and Comments
- Use targeted `# pylint: disable=...` lines close to the affected scope.
  Example: `mugen/core/plugin/acp/model/global_role.py:14`
- Keep comments concise and technical; avoid narrative comments unless needed.

## Test Style for ACP-adjacent Tests
- Keep module docstring plus lightweight namespace bootstrap when isolating plugin tests.
  Example: `mugen_test/test_acp_api_audit_emission.py:1`
- Keep test classes documented; prefer explicit assertions and clear fixture setup.
