# Dependency Injection Maintenance

This note documents the core DI structure in `mugen/core/di/__init__.py` and the checks that should stay green when changing it.

## Core Structure

- `_PROVIDER_SPECS`: declarative metadata for each provider (`module_path`, interface, constructor bindings, optional platform gating).
- `_PROVIDER_BUILD_ORDER`: explicit provider build sequence after config and logging are initialized.
- `_build_provider(...)`: single generic provider builder used by `_build_container()`.

Keep `logging_gateway` as the bootstrap provider and keep the remaining providers in `_PROVIDER_BUILD_ORDER` dependency-safe order.

## Canonical Provider Tokens

Runtime config values under `mugen.modules.core.*` must use these token values
from `mugen/core/di/provider_registry.py` (never module paths):

| Config Key | Allowed Tokens |
| --- | --- |
| `mugen.modules.core.gateway.logging` | `standard` |
| `mugen.modules.core.gateway.completion` | `bedrock`, `deterministic`, `groq`, `openai`, `sambanova` |
| `mugen.modules.core.gateway.email` | `ses`, `smtp` |
| `mugen.modules.core.gateway.knowledge` | `chromadb`, `milvus`, `pinecone`, `pgvector`, `qdrant`, `weaviate` |
| `mugen.modules.core.gateway.storage.keyval` | `relational` |
| `mugen.modules.core.gateway.storage.media` | `default` |
| `mugen.modules.core.gateway.storage.relational` | `sqlalchemy` |
| `mugen.modules.core.gateway.storage.web_runtime` | `relational` |
| `mugen.modules.core.service.ipc` | `default` |
| `mugen.modules.core.service.messaging` | `default` |
| `mugen.modules.core.service.nlp` | `default` |
| `mugen.modules.core.service.platform` | `default` |
| `mugen.modules.core.service.user` | `default` |
| `mugen.modules.core.client.matrix` | `default` |
| `mugen.modules.core.client.web` | `default` |
| `mugen.modules.core.client.whatsapp` | `default` |

## Runtime Shutdown Timeout Contract

- `mugen.runtime.provider_shutdown_timeout_seconds` is required and must be `> 0`.
- `mugen.runtime.shutdown_timeout_seconds` is required and must be `> 0`.
- DI shutdown paths do not silently fall back to legacy default timeout values when these settings are missing/invalid.
- Invalid timeout configuration must fail bootstrap validation before runtime startup.
- Provider/container shutdown failures are fail-closed and must raise `ContainerShutdownError`.
- Shutdown failure signals are structured as `ProviderShutdownFailure` entries and are logged at error level.

## Runtime Bootstrap Contract

- Runtime bootstrap parsing is contract-owned in:
  - `mugen/core/contract/runtime_bootstrap.py`
- Adapter/runtime layers must consume that contract parser directly (no runtime-layer parser ownership).
- The parser is strict fail-closed. Required fields:
  - `mugen.runtime.profile` (`platform_full`)
  - `mugen.runtime.provider_readiness_timeout_seconds` (`> 0`)
  - `mugen.runtime.provider_shutdown_timeout_seconds` (`> 0`)
  - `mugen.runtime.shutdown_timeout_seconds` (`> 0`)
  - `mugen.runtime.phase_b.startup_timeout_seconds` (`> 0`)
- Legacy optional parser switches (`require_*`) are removed. Callers must treat these
  controls as unconditionally required.

## Readiness Failure Surfacing

- DI readiness configuration/parse failures must surface as `ProviderBootstrapError`
  (not raw `RuntimeError`) through `ensure_container_readiness_async()`.
- App bootstrap (`phase_a`) must convert container readiness failures into
  `BootstrapConfigError` with deterministic phase state/error updates.

## Phase-B Shutdown Semantics

- Phase-B shutdown is fail-closed for timeout paths.
- Unresolved platform/client task cancellation timeouts must leave runtime status degraded with explicit timeout errors.
- Shutdown adapters must not mask degraded timeout outcomes by writing `stopped` after unresolved task timeouts.
- DI container shutdown failures must propagate to orchestration (no warning-only continuation).
- Cached injector state is cleared only after successful deterministic shutdown.

## Layering Contract

Core DI participates in a strict clean-architecture contract that is enforced by tests:

- `mugen.core.domain.use_case` must remain infrastructure-free:
  - no imports from Quart, DI container, clients, gateways, services, runtime/bootstrap adapters.
- `mugen.core.contract.*` defines ports only:
  - no imports from concrete implementation packages.
- Bootstrap/orchestration (`mugen/__init__.py`, `quartman.py`) coordinates contracts + DI and should not directly import concrete clients/gateways/services.
- Adapters (`mugen.core.client.*`, `mugen.core.gateway.*`) must not import API-layer modules.

When changing DI/provider wiring, maintain these boundaries first, then update implementation.

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

## Repo-Wide Status

Done:

- Core DI provider construction is unified under `_PROVIDER_SPECS` +
  `_build_provider(...)`.
- Extension-service injector API is hardened (`has_ext_service`,
  `get_required_ext_service`, sentinel-aware `get_ext_service`,
  optional atomic bulk registration).
- ACP and non-ACP runtime modules now use module-level provider callables for DI
  defaults instead of inline `lambda: di.container...` signatures and direct
  constructor fallback expressions.
- Import-time DI safety is covered by:
  - `mugen_test/test_acp_di_runtime_regression.py`
  - `mugen_test/test_mugen_di_runtime_import_regression.py`
- Constructor fallback behavior is covered by:
  - `mugen_test/test_mugen_di_constructor_fallbacks.py`
- CI test gate (which includes DI coverage) exists at:
  - `.github/workflows/test-gates.yml`

Remaining:

- `di.container` is still used intentionally at runtime in provider callables and
  extension setup paths; this is expected and currently required for lazy container
  behavior.
- Keep extending focused regression tests when new modules adopt DI defaults so
  import-time safety and constructor fallback semantics remain locked.

## Required Validation Gates

Run these before merging DI changes:

```bash
poetry run pytest mugen_test/test_mugen_di_*.py
poetry run python -m unittest mugen_test.test_mugen_register_extensions mugen_test.test_mugen_run_clients mugen_test.test_mugen_create_quart_app
bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh
```
