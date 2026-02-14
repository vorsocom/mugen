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

## Required Validation Gates

Run these before merging DI changes:

```bash
poetry run pytest mugen_test/test_mugen_di_*.py
poetry run python -m unittest mugen_test.test_mugen_register_extensions mugen_test.test_mugen_run_clients mugen_test.test_mugen_create_quart_app
bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh
```
