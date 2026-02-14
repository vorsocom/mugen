# Dependency Injection Maintenance

This note documents the core DI structure in `mugen/core/di/__init__.py` and the checks that should stay green when changing it.

## Core Structure

- `_PROVIDER_SPECS`: declarative metadata for each provider (`module_path`, interface, constructor bindings, optional platform gating).
- `_PROVIDER_BUILD_ORDER`: explicit provider build sequence after config and logging are initialized.
- `_build_provider(...)`: single generic provider builder used by `_build_container()`.

Keep `logging_gateway` as the bootstrap provider and keep the remaining providers in `_PROVIDER_BUILD_ORDER` dependency-safe order.

## Extension Services

- Extension service keys used by ACP are core-owned constants in `mugen/core/di/__init__.py`:
  - `EXT_SERVICE_ADMIN_REGISTRY`
  - `EXT_SERVICE_ADMIN_SVC_JWT`
  - `EXT_SERVICE_ADMIN_SVC_AUTH`
- ACP modules should keep DI defaults as module-level callables that resolve from
  `di.container` at call time (not import time).
- ACP modules should build namespaced ACP keys via `AdminNs` instead of inline
  `f"{namespace}:..."` concatenation.
- Injector helpers in `mugen/core/di/injector.py`:
  - `register_ext_service(...)`
  - `register_ext_services(..., atomic=False)`
  - `get_ext_service(...)`
  - `get_required_ext_service(...)`
  - `has_ext_service(...)`

`register_ext_services(..., atomic=True)` applies all-or-nothing semantics for
bulk extension registration.

`get_ext_service(...)` supports an explicit default value. Passing `None` as the
default now returns `None` when the key is missing.

## Constructor Fallback Pattern

For extension/service constructors that allow dependency overrides:

- Accept explicit constructor args for testability (for example `config=None`,
  `logging_gateway=None`).
- Resolve defaults through module-level provider callables (for example
  `_config_provider()`), not inline `... else di.container.<dep>` expressions.
- Keep fallback resolution runtime-only by calling provider functions in
  `__init__`, never at import-time.

Reference regression coverage:

- `mugen_test/test_mugen_di_constructor_fallbacks.py`

## Required Validation Gates

Run these before merging DI changes:

```bash
poetry run pytest mugen_test/test_mugen_di_*.py
poetry run python -m unittest mugen_test.test_mugen_register_extensions mugen_test.test_mugen_run_clients mugen_test.test_mugen_create_quart_app
bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh
```
