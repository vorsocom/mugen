# Context Engine Design

Status: Active
Last Updated: 2026-03-09
Audience: Core maintainers, plugin authors, downstream platform teams

## Purpose

This document defines the context runtime introduced in core. It replaces the
legacy CTX/RAG split with one provider-neutral, tenant-safe, plugin-composable
service boundary.

Use this document for hard runtime semantics. Use
`docs/context-engine-authoring.md` for collaborator authoring and registration.
Use `docs/context-engine-user-stories.md` for story-driven runtime walkthroughs
that show how these guarantees behave on real turns.
Use `docs/context-engine-strengthening-decisions.md` for the decision log that
explains why the current design took this shape.

## Design Goals

- keep clean architecture boundaries intact;
- make tenant scope mandatory on every turn;
- support bounded state, retrieval, memory writeback, provenance, cache hints,
  and traceability as one runtime;
- compile into the normalized completion contract instead of provider-specific
  prompt code;
- preserve plugin composition as the default extension model;
- keep lane semantics stable while allowing renderer evolution;
- treat tenant isolation and provenance as more important than convenience.

## Hard Contract

Contract guarantee: the core context contract lives in
`mugen.core.contract.context`.

Primary primitives:

- `ContextScope`: stable tenant/conversation/work-item scope.
- `ContextTurnRequest`: normalized turn input.
- `ContextArtifact` / `ContextCandidate`: typed contributor output with
  provenance and budget metadata.
- `ContextSourceRef` / `ContextSourceRule`: typed source identity and
  engine-enforced allow/deny rules.
- `ContextState`: bounded control state per scoped conversation.
- `ContextBundle`: selected + dropped artifacts, policy, cache hints, trace.
- `PreparedContextTurn`: normalized completion request plus opaque commit token.
- `ContextCommitResult`: post-turn persistence outcome.

Primary ports:

- `IContextEngine`
- `IContextContributor`
- `IContextGuard`
- `IContextRanker`
- `IContextArtifactRenderer`
- `IContextPolicyResolver`
- `IContextStateStore`
- `IContextCommitStore`
- `IMemoryWriter`
- `IContextCache`
- `IContextTraceSink`

Contract guarantee: domain/use-case code remains infrastructure-free. Contracts
remain ports only and do not import plugin/runtime implementations.

Contract guarantee: the runtime is two-phase.

1. `prepare_turn(request)` resolves policy, assembles context, compiles a
   normalized completion request, and issues one opaque commit token.
2. `commit_turn(...)` validates that prepared turn, persists post-turn state,
   memory, trace, and cache side effects, and returns `ContextCommitResult`.

## Lane Buckets

Contract guarantee: the core engine recognizes five stable lane buckets.

1. `system_persona_policy`
2. `bounded_control_state`
3. `operational_overlay`
4. `recent_turn`
5. `evidence`

The current user message is not a lane. It is always appended after compiled
context.

Contract guarantee: lane buckets are selection and budgeting primitives, not
presentation APIs.

Contract guarantee: artifacts may also declare `render_class`. The compiler
routes selected artifacts through `IContextArtifactRenderer` by `render_class`.
This is the extensibility seam for new source families and output layouts.

Default engine behavior: if a built-in lane has no explicit `render_class`, the
engine uses the built-in mapping:

- `system_persona_policy` -> `system_persona_policy_items`
- `bounded_control_state` -> `bounded_control_state_items`
- `operational_overlay` -> `operational_overlay_items`
- `recent_turn` -> `recent_turn_messages`
- `evidence` -> `evidence_items`

Contract guarantee: prepare fails closed if a selected artifact resolves to an
unknown render class or to a lane with no valid renderer path.

## Prepare Pipeline

Default engine behavior: `DefaultContextEngine` executes prepare in this order:

1. resolve `ContextPolicy`
2. load `ContextState`
3. collect contributor candidates
4. enforce source policy
5. apply guards
6. apply rankers
7. deduplicate
8. select within budget
9. render selected artifacts into `CompletionRequest.messages`
10. emit cache hints and prepare trace

## Operational Walkthroughs

For end-to-end examples that connect resolver, state, contributors, source
policy, guards, rankers, compilation, cache, memory, and trace behavior, see
`docs/context-engine-user-stories.md`.

Contract guarantee: blocked artifacts do not reach completion compilation.

Current core plugin implementation: the built-in plugin contributes persona,
bounded state, orchestration overlays, ops-case overlays, audit overlays,
recent turns, knowledge evidence, and memory recall.

## Source Policy Model

Contract guarantee: source policy is engine-enforced, not advisory.

`ContextPolicy` may include:

- `source_allow`
- `source_deny`
- `source_rules`

`source_allow` and `source_deny` are kind-level shortcuts. `source_rules` is
the first-class form and may match:

- `kind`
- `source_key`
- `locale`
- `category`

Contract guarantee: source policy evaluates against contributor-emitted
`ContextSourceRef`, not against collaborator-specific metadata conventions.

Contract guarantee: if an allow rule requires structured identity beyond kind
and a candidate does not provide a matching `ContextSourceRef`, that candidate
is dropped rather than implicitly allowed.

Current core plugin implementation: ACP `ContextSourceBindings` resolve into
allow rules. Policy row `source_allow` / `source_deny` resolve into kind-level
rules.

## Provenance and Dedupe

Contract guarantee: provenance and dedupe use separate identities.

- artifact identity: `artifact_id` scoped to the contributor's output domain.
- contributor identity: stable contributor `name`.
- source identity: `ContextSourceRef`.
- trace identity: `trace_id` and tenant-scoped scope metadata.

Default engine behavior: dedupe happens after ranking and before budget
selection.

Default engine behavior: the dedupe group is built from lane + render class +
canonical source identity. When no canonical source identity is available, the
engine falls back to a content fingerprint.

Contract guarantee: dropped duplicates are traceable. The dropped candidate
records the dedupe group and the surviving winner.

## Budget and Selection Contract

Contract guarantee: `ContextBudget` defines hard ceilings for selection and
compilation.

Hard ceilings:

- `max_total_tokens`
- `max_selected_artifacts`
- `max_recent_turns`
- `max_recent_messages`
- `max_evidence_items`
- `max_prefix_tokens`

Default engine behavior: `soft_max_total_tokens` is a preferred ceiling used
for spillover selection after lane minima. Hard ceilings still win.

Contract guarantee: `ContextLaneBudget` may define per-lane:

- `min_items`
- `max_items`
- `reserved_tokens`
- `allow_spillover`

Default engine behavior:

- lane minima are filled first in stable lane order;
- lane reservations hold token headroom for lanes that still have remaining
  candidates;
- spillover then fills remaining capacity in lane order and ranked order;
- `budget_hints` can tighten an existing policy budget but do not widen it.

Current core plugin implementation: `adaptive_trimming` exists on the contract
but defaults to `"none"`. No built-in adaptive trimmer is shipped yet.

## Commit Token Lifecycle

Contract guarantee: commit tokens are opaque issued handles, not deterministic
hashes.

Contract guarantee: commit validation is delegated through `IContextCommitStore`
and must bind:

- tenant scope
- scope key / state handle
- prepared fingerprint
- lifecycle state
- expiry

Contract guarantee: successful duplicate delivery is replay-safe. If the same
prepared turn is committed again after a successful commit, the stored commit
result may be replayed instead of re-running persistence.

Contract guarantee: commit failure is fail-closed. Expired, mismatched,
in-flight, or previously failed tokens do not authorize a new commit.

Current core plugin implementation: the relational commit ledger tracks
`prepared`, `committing`, `committed`, and `failed`.

## State vs History

Contract guarantee: bounded state and recent-turn history are distinct
stores with different purposes.

`ContextState` is for compact operational control state such as:

- current objective
- entities
- constraints
- unresolved slots
- commitments
- safety flags
- routing
- explicit summary/metadata

`recent_turn` history is event material used for replay and reconstruction.

Contract guarantee:

- recent-turn replay comes from event/history storage, not from `ContextState`;
- raw assistant output is not automatically promoted into bounded state;
- automatic transcript promotion into durable state is not part of the core
  contract.

Current core plugin implementation: assistant and user turn material is written
to `ContextEventLog`, while `ContextState` stays compact and revisioned.

## Trace and Cache

Contract guarantee: trace and cache are non-authoritative collaborators.

Trace:

- prepare/commit trace capture is controlled by `ContextPolicy`;
- selected and dropped item capture can be toggled independently;
- trace failures do not redefine business correctness.

Cache:

- cache keys remain tenant-safe;
- the engine may use `retrieval`, `prefix_fingerprint`, and `working_set`
  namespaces;
- cache failures are warnings, not commit authority.

## Registry Ownership

Contract guarantee: the registry distinguishes multi-register and single-owner
collaborators.

Multi-register:

- contributors
- guards
- rankers
- renderers
- trace sinks

Single-owner:

- policy resolver
- state store
- commit store
- memory writer
- cache

Default engine behavior: competing single-owner registrations fail closed with
an explicit owner conflict. The intended extension model is one engine-visible
owner that may compose internal sub-collaborators if needed.

## Messaging Integration

`DefaultMessagingService` and the built-in text handler delegate context work to
`IContextEngine`.

High-level flow:

1. normalize inbound text/composed/media context
2. run CP extensions
3. `context_engine.prepare_turn(...)`
4. completion gateway call with normalized request
5. run RPP extensions
6. run CT extensions
7. `context_engine.commit_turn(...)`
8. return normalized user-visible responses

## Default Plugin Composition

Current core plugin implementation:

- FW token: `core.fw.context_engine`
- runtime collaborator registry via `EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY`
- ACP resources:
  - `ContextProfiles`
  - `ContextPolicies`
  - `ContextContributorBindings`
  - `ContextSourceBindings`
  - `ContextTracePolicies`
- plugin-owned migration track:
  `plugins/context_engine/alembic.ini` with version table
  `mugen.alembic_version_context_engine`

This plugin is the reference implementation, not the whole contract.

## Tenant Isolation and Global Fallback

Contract guarantee: `ContextScope.tenant_id` is always populated.

Resolution policy:

- resolved ingress routing uses the resolved tenant;
- `missing_identifier` and `missing_binding` may fall back to
  `GLOBAL_TENANT_ID`;
- platforms with no routing subsystem may opt into deterministic global
  fallback;
- explicit negative routing outcomes still fail closed.

Fallback-global turns use stricter defaults:

- working-set state and recent-turn history remain scope-partitioned;
- long-term memory recall/writeback requires sender or conversation partitioning
  by default;
- no implicit tenant-wide shared recall is allowed.

## MCP and Skills Position

The runtime is MCP/Skills-native at the contract level only in v1.

That means:

- source kinds, bindings, provenance, and artifacts can represent MCP- or
  skill-derived context;
- no first-party MCP transport or Skills executor is part of this refactor;
- future adapters should compose through contributors, renderers, and policy
  bindings rather than changing the engine interface.

## Migration Note

Legacy CTX/RAG extension categories are removed. Any downstream code still using
`type = "ctx"` or `type = "rag"` must migrate to:

- message-lifecycle extensions (`fw`, `ipc`, `mh`, `rpp`, `ct`) where
  appropriate; or
- context engine contributors/guards/rankers/renderers/caches/writers for
  runtime context behavior.
