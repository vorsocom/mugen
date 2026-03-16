# Downstream Architecture Conformance

Status: Active  
Last Updated: 2026-03-16  
Audience: Downstream application teams, plugin maintainers, AI coding agents

This guide defines the minimum architecture rules a downstream muGen
application should preserve. It is intentionally explicit so teams can extend
the framework safely even when work is being done quickly, collaboratively, or
through AI-assisted "vibe coding".

## Why This Exists

muGen is already split into enforceable layers. If downstream teams put product
logic in the wrong place, they usually do not get a better framework; they get
a private fork with unclear ownership and painful upstream merges.

Core architecture boundaries are enforced in:

- `mugen_test/test_mugen_core_architecture_boundaries.py`

This guide explains how downstream code should fit around those boundaries.

## Non-Negotiable Rules

1. Do not add downstream business logic under `mugen/core`.
2. Do not edit `mugen/core` when the same outcome can be achieved through
   config, extensions, ACP contributors, context-engine collaborators,
   agent-runtime collaborators, or downstream workers.
3. Keep downstream packages in their own import namespace, for example
   `acme_extension` or `my_org_support`.
4. Keep downstream schema in plugin-owned migration tracks under
   `rdbms.migration_tracks.plugins`, never in core `migrations/versions`.
5. Treat ACP resources and actions as the system-of-record API for core-owned
   domains. Do not bypass core plugin contracts with direct writes unless the
   design explicitly calls for downstream-owned storage.
6. Use strict core tokens for shipped runtime extensions. For downstream
   ACP-aligned framework plugins, declare unique `fw` tokens plus
   `name`/`namespace`/`contrib` metadata in `mugen.modules.extensions`.
   Do not assume arbitrary extension-class loading is available unless the
   runtime registry support exists.

## Core Layer Model To Preserve

The important `mugen/core` boundaries are:

- **Domain/use-case layer:** pure business/use-case logic; no Quart, DI,
  gateway, runtime, or concrete service imports.
- **Contract layer:** ports and normalized DTOs only; no implementation-layer
  imports.
- **Service layer:** orchestration behind contracts; should not import plugin
  implementations or concrete adapters.
- **Client/gateway adapters:** transport/provider integration code; should not
  import API or runtime layers.
- **Bootstrap/runtime orchestration:** assembles the app, DI, and phase-A/B
  runtime behavior without hard-wiring direct adapter imports into the wrong
  layers.

If your downstream change breaks those assumptions, it is a core-framework
change and should be treated as such.

## Where Downstream Code Should Go

Recommended downstream layout:

```text
acme_extension/
├── __init__.py
├── contrib.py
├── fw_ext.py
├── ipc_ext.py
├── response_ext.py
├── model/
├── service/
├── worker/
└── migrations/
```

Use the right seam for the job:

- **FW extension / ACP-aligned plugin:** new resources, actions, admin routes,
  plugin runtime binding, or contributor registration.
- **IPC extension:** typed asynchronous work, ingress handlers, scheduled jobs,
  or queue-driven command handling.
- **MH / CP / RPP / CT extension:** messaging-path customization.
- **Context-engine collaborator:** context policy, retrieval, ranking,
  rendering, cache, trace, or commit behavior.
- **Agent-runtime collaborator:** planning, evaluation, capability listing,
  execution guards, schedulers, and response synthesis.
- **Downstream worker/service package:** product-specific workflows, external
  side effects, projections, notifications, SLA/escalation actions, reporting,
  and domain integrations.

## Conformance Checklist

Use this checklist before merging downstream work:

1. The new code lives outside `mugen/core`.
2. `mugen.toml` registers new framework/plugin entries under
   `mugen.modules.extensions`.
3. Any new model-bearing package is assigned to a plugin-owned migration track.
4. Core plugin behavior is extended through ACP/resources/actions or supported
   collaborator seams rather than direct table writes.
5. Retrieval/context changes were implemented in the context-engine seam, not
   by reintroducing legacy CTX/RAG patterns.
6. Agent behavior changes were implemented in the agent-runtime seam, not by
   embedding planning logic into unrelated messaging code.
7. Platform-specific runtime behavior uses the existing web or shared-ingress
   contracts instead of inventing a parallel transport path.
8. The change does not require importing core plugin implementations into core
   service or contract layers.
9. Downstream provenance is tracked in project-root `downstream.toml` with
   `schema_version`, `[app]`, and `[upstream]` metadata. `upstream.sync_ref`
   points to the exact merged upstream commit, and `upstream.sync_tag` is used
   only when that sync corresponds to a tag.
10. The architecture-boundary tests still pass.
11. Downstream docs were updated if the extension point, plugin shape, or
    operational workflow changed.

## Safe Defaults For AI-Assisted Changes

When an AI agent or quick prototype is making downstream changes, default to
these decisions:

- create a new downstream package instead of editing `mugen/core`;
- keep upstream/downstream provenance in project-root `downstream.toml`
  rather than in runtime config, `pyproject.toml`, or executable Python
  metadata files;
- use `mugen.modules.extensions` for framework/plugin metadata and runtime
  tokens that already exist;
- keep all downstream schema in a dedicated plugin track;
- prefer ACP actions/resources over direct writes to core-owned tables;
- prefer downstream services/workers for product policy and side effects;
- consult the relevant design doc before adding new context-engine or
  agent-runtime behavior.

If the work needs a brand-new runtime extension token or generic extension
class loading path, treat that as upstream framework work.

If the change still appears to require `mugen/core` edits after those defaults,
stop and decide whether the work is actually an upstream framework change.

## Read In This Order

1. [`docs/apps.md`](./apps.md)
2. [`docs/services.md`](./services.md)
3. [`docs/extensions.md`](./extensions.md)
4. [`docs/migration-track-separation.md`](./migration-track-separation.md)
5. [`docs/context-engine-design.md`](./context-engine-design.md) and
   [`docs/context-engine-authoring.md`](./context-engine-authoring.md) when the
   change affects context/runtime assembly
6. [`docs/agent-runtime-design.md`](./agent-runtime-design.md) and
   [`docs/agent-runtime-authoring.md`](./agent-runtime-authoring.md) when the
   change affects planning or background execution

For domain-specific downstream orchestration guidance, continue into
[`docs/downstream-notes/README.md`](./downstream-notes/README.md).
