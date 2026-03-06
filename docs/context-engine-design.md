# Context Engine Design

Status: Active
Last Updated: 2026-03-06
Audience: Core maintainers, plugin authors, downstream platform teams

## Purpose

This document defines the clean-break context runtime introduced in core. It
replaces the legacy CTX/RAG split with a first-class service boundary that is
provider-neutral, tenant-safe, and plugin-composable.

## Design Goals

- keep clean architecture boundaries intact;
- make tenant scope mandatory on every turn;
- support bounded state, retrieval, memory writeback, provenance, and cache
  hints as one runtime;
- compile into the normalized completion contract instead of provider-specific
  prompt code;
- keep MCP and Skills native at the contract level without shipping a
  first-party transport/executor in v1.

## Core Runtime Contract

The core contract package is `mugen.core.contract.context`.

Primary primitives:

- `ContextScope`: stable tenant/conversation/work-item scope
- `ContextTurnRequest`: normalized turn input
- `ContextArtifact` / `ContextCandidate`: typed contributor output with
  provenance
- `ContextState`: bounded control state per scoped conversation
- `ContextBundle`: selected + dropped artifacts, policy, cache hints, trace
- `PreparedContextTurn`: normalized completion request plus commit token
- `ContextCommitResult`: post-turn persistence outcome

Primary interfaces:

- `IContextEngine`
- `IContextContributor`
- `IContextGuard`
- `IContextRanker`
- `IMemoryWriter`
- `IContextCache`
- `IContextTraceSink`
- `IContextPolicyResolver`
- `IContextStateStore`

The engine contract is two-phase:

1. `prepare_turn(request)` selects and compiles context.
2. `commit_turn(...)` persists post-turn effects after the final user-visible
   response is known.

## Assembly Model

Required lanes:

1. system/persona/policy
2. bounded control state
3. operational overlays
4. tenant knowledge / evidence
5. recent interaction window
6. current user message

Compilation order into `CompletionRequest.messages` is:

1. system/persona/policy
2. bounded control state
3. operational overlays
4. selected evidence with provenance
5. recent turns
6. current user message

Selection priority is slightly different under tight budgets: recent turns are
kept ahead of lower-value evidence so the runtime does not lose the active
conversation thread before dropping optional retrieval.

## Default Engine Responsibilities

`DefaultContextEngine` is the provider-neutral orchestration layer. It:

- resolves policy from scope/config;
- loads bounded conversation state;
- collects typed candidates from registered contributors;
- applies guards and rankers;
- trims selection to a budget envelope;
- compiles the selected bundle into normalized completion messages;
- emits prefix fingerprints and cache hints;
- validates commit tokens before persistence;
- commits state, memory writes, traces, and cache updates.

The engine owns structure, not provider-specific prompting.

## Default Plugin Composition

The `context_engine` core plugin provides:

- FW token: `core.fw.context_engine`
- runtime collaborator registry via `EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY`
- ACP resource contribution for:
  - `ContextProfiles`
  - `ContextPolicies`
  - `ContextContributorBindings`
  - `ContextSourceBindings`
  - `ContextTracePolicies`
- plugin-owned migration track for runtime/control-plane schema:
  `plugins/context_engine/alembic.ini` with version table
  `mugen.alembic_version_context_engine`

Built-in contributors include:

- persona/policy
- bounded state
- recent turns
- knowledge pack evidence
- channel orchestration overlays
- ops case overlays
- audit trace overlays
- structured memory recall

## Tenant Isolation and Global Fallback

`ContextScope.tenant_id` is always populated.

Resolution policy:

- resolved ingress routing uses the resolved tenant;
- `missing_identifier` and `missing_binding` may fall back to
  `GLOBAL_TENANT_ID`;
- platforms with no routing subsystem may opt into deterministic global
  fallback;
- explicit negative routing outcomes still fail closed.

Every cache key includes tenant identity. Provenance also carries tenant
metadata, and traces record whether the turn was `resolved` or
`fallback_global`.

Fallback-global turns use stricter defaults:

- working-set state and recent-turn history remain scope-partitioned;
- long-term memory recall/writeback requires sender or conversation partitioning
  by default;
- no implicit tenant-wide shared recall is allowed.

## Provenance and Safety

Every selected artifact keeps provenance, and the bundle trace records:

- what was selected;
- what was dropped;
- why it was dropped (duplicate, guard, budget, and so on).

Retrieved evidence is compiled as structured messages with explicit provenance
instead of raw prompt-string interpolation. The intent is to reduce
instruction-following from retrieved content by construction.

## Caching

The default cache interface supports three namespaces used by the engine:

- `working_set`
- `retrieval`
- `prefix_fingerprint`

Cache policy is controlled by `ContextPolicy`; cache behavior is not owned by
the text handler.

## Messaging Integration

`DefaultMessagingService` and the built-in text handler now delegate context work
to `IContextEngine`.

High-level text flow:

1. normalize inbound text/composed/media context
2. run CP extensions
3. `context_engine.prepare_turn(...)`
4. completion gateway call with normalized request
5. run RPP extensions
6. run CT extensions
7. `context_engine.commit_turn(...)`
8. return normalized user-visible responses

## MCP and Skills Position

The runtime is MCP/Skills-native at the contract level only in v1.

That means:

- source kinds, bindings, provenance, and artifacts can represent MCP- or
  skill-derived context;
- no first-party MCP transport or Skills executor is part of this refactor;
- future adapters should compose through contributor/policy bindings rather than
  changing the engine interface.

## Migration Note

Legacy CTX/RAG extension categories are removed. Any downstream code still using
`type = "ctx"` or `type = "rag"` must migrate to:

- message-lifecycle extensions (`fw`, `ipc`, `mh`, `rpp`, `ct`) where
  appropriate; or
- context engine contributors/guards/rankers/caches/writers for runtime context
  behavior.
