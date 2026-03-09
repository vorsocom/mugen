# Context Engine Authoring Guide

Status: Active
Last Updated: 2026-03-09
Audience: Downstream plugin authors, core maintainers

## Purpose

This guide explains how to extend muGen's runtime context seam safely.

Use it when you need to add tenant-scoped runtime context behavior through the
core context engine instead of legacy CTX/RAG hooks.

For architecture and control-plane intent, see `docs/context-engine-design.md`.
For the broader extension model, see `docs/extensions.md`.

## Runtime Flow

`DefaultContextEngine` runs one prepare phase and one commit phase.

Prepare flow:

1. resolve `ContextPolicy`
2. load bounded `ContextState`
3. collect candidates from registered contributors
4. apply guards
5. apply rankers
6. select within budget
7. compile the selected bundle into `CompletionRequest.messages`
8. emit retrieval/prefix cache entries when cache is enabled
9. record prepare traces when tracing is enabled

Commit flow:

1. validate the commit token
2. save bounded state
3. persist memory writes
4. update working-set cache entries
5. record commit traces

Use the prepare phase for runtime context selection. Use the commit phase for
post-turn persistence that depends on the final assistant-visible outcome.

## Choose The Right Collaborator

### `IContextContributor`

Use a contributor when you need to fetch or synthesize context before model
completion.

- Input: `ContextTurnRequest`, resolved `ContextPolicy`, current `ContextState`
- Output: `list[ContextCandidate]`
- Good fit: recent-turn replay, knowledge retrieval, ops overlays, memory recall
- Do not use when the behavior belongs after final response generation

### `IContextGuard`

Use a guard when you need to remove candidates before ranking/selection.

- Input: current candidate list plus request/policy/state
- Output: the candidate list that should continue
- Good fit: tenant isolation, sensitivity blocking, global-fallback safety
- Do not use for storage or retrieval

Important: the current engine records guard drops by comparing input and output
artifact IDs. If a guard leaves a candidate in the returned list, that
candidate continues through ranking and selection even if the guard attached a
drop reason to it.

### `IContextRanker`

Use a ranker when you need to score already-collected candidates.

- Input: current candidate list plus request/policy/state
- Output: the same candidates with updated ordering/score metadata
- Good fit: trust/freshness heuristics, domain-specific scoring
- Do not use to own retrieval or persistence

Multiple rankers may run in sequence. Each ranker receives the output of the
previous one.

### `IMemoryWriter`

Use a memory writer when you need post-turn long-term writeback after the final
assistant response is known.

- Input: request, prepared turn, completion result, final user responses, outcome
- Output: `list[MemoryWrite]`
- Good fit: episodic memory, preferences, facts, derived writeback
- Do not use for pre-turn recall; that belongs in a contributor

### `IContextCache`

Use a cache when you need provider-neutral working-set or retrieval caching.

- Input: namespace + tenant-safe key + payload
- Output: cached values or invalidation counts
- Good fit: working-set state hints, retrieval reuse, prefix fingerprints
- Do not use as the source of truth for state or memory

### `IContextTraceSink`

Use a trace sink when you need prepare/commit observability.

- Input: request plus prepared/commit payloads
- Output: side-effectful trace persistence only
- Good fit: trace rows, audit bridge writes, diagnostics
- Do not use for primary business persistence

### `IContextStateStore`

Use a state store when you need bounded, scope-partitioned conversation state.

- Input: one scoped request during prepare/commit
- Output: loaded or saved `ContextState`
- Good fit: current objective, unresolved slots, safety flags, recent-turn event log
- Do not use for long-term memory or evidence retrieval

### `IContextPolicyResolver`

Use a policy resolver when you need to turn scope and ACP-managed bindings into
one effective `ContextPolicy`.

- Input: `ContextTurnRequest`
- Output: resolved `ContextPolicy`
- Good fit: profile selection, budget/redaction/retention policy, contributor allow/deny
- Do not use to fetch per-turn evidence

## Authoring Contract

### Common Expectations

- Keep all runtime behavior tenant-scoped through `ContextScope`.
- Treat `ContextScope.tenant_id` as mandatory.
- Keep collaborator `name` values stable over time. They are used by bindings,
  traces, and operator-facing reasoning.
- Prefer explicit dependency injection through constructor args, with runtime DI
  fallback only where needed.

### Contributor Contract

Contributors emit `ContextCandidate` values that wrap `ContextArtifact`.

Each artifact should have:

- a stable `artifact_id`
- one of the currently compiled lanes:
  - `system_persona_policy`
  - `bounded_control_state`
  - `operational_overlay`
  - `evidence`
  - `recent_turn`
- a stable `kind`
- `ContextProvenance` with contributor and source metadata
- a realistic `estimated_token_cost`

Compilation behavior today:

- `system_persona_policy`, `bounded_control_state`, `operational_overlay`, and
  `evidence` compile into structured `system` messages
- `recent_turn` compiles into normal completion messages using its `role` and
  `content`
- unknown lanes sort after known lanes and are not compiled into completion
  messages by the current engine

Contributor filtering today:

- contributors with blank names are skipped
- `ContextPolicy.contributor_allow` and `contributor_deny` are enforced by the
  engine during collection
- `ContextPolicy.source_allow` and `source_deny` are resolved into policy, but
  the current `DefaultContextEngine` does not enforce them directly

Deduplication today uses `(artifact_id, provenance.source_kind)`. If more than
one candidate shares that pair, the higher-score candidate survives and the
other is dropped as a duplicate.

### Guard Contract

- Return only the candidates that should continue.
- Preserve candidate identity when passing candidates through.
- Treat guards as fail-closed for tenant and sensitivity boundaries.

The engine records guard drops under the guard's `name` in the dropped bundle
trace.

### Ranker Contract

- Set or update `ContextCandidate.score`.
- Keep scoring logic pure relative to the already-collected candidates.
- Assume selection still happens later under lane priority and budget limits.

The current engine sorts by lane priority first, then score, then candidate
priority. Rankers influence ordering within that selection model; they do not
replace it.

### Memory Writer Contract

- Write only during `commit_turn`.
- Derive writes from the completed turn outcome, not from speculative prepare
  data alone.
- Populate `MemoryWrite.provenance`, `scope_partition`, and TTL/tag metadata
  deliberately.

### Cache Contract

- Keep keys tenant-safe regardless of backing store.
- Support the namespaces the engine uses today:
  - `working_set`
  - `retrieval`
  - `prefix_fingerprint`

The built-in relational cache enforces keys in the form
`tenant:<uuid>:<rest-of-key>`. Custom caches should preserve the same tenant
partitioning guarantee even if their internal key format differs.

### Trace Sink Contract

- Record prepare/commit observability only when tracing is enabled.
- Preserve selected/dropped artifact provenance and commit outcomes.
- Keep trace side effects isolated from primary runtime correctness.

### State Store Contract

- Partition state by scope, not just tenant.
- Keep bounded state small and operationally useful.
- Save state during commit, after the final turn outcome is known.

### Policy Resolver Contract

- Resolve one effective policy per turn.
- Merge profile, policy row, contributor bindings, source bindings, and trace
  policy into one `ContextPolicy`.
- Keep defaults tenant-safe, especially under global fallback.

## Registration Path

Runtime collaborators are registered through an FW extension. The built-in
`core.fw.context_engine` extension is the reference shape.

Current registry cardinality:

- many contributors
- many guards
- many rankers
- many trace sinks
- one policy resolver
- one state store
- one memory writer
- one cache

Minimal registration pattern:

```python
from mugen.core import di
from mugen.core.contract.extension.fw import IFWExtension
from mugen.core.plugin.context_engine.service.registry import ContextComponentRegistry


class MyContextFWExtension(IFWExtension):
    @property
    def platforms(self) -> list[str]:
        return []

    async def setup(self, app) -> None:  # noqa: ARG002
        registry = di.container.get_required_ext_service(
            di.EXT_SERVICE_CONTEXT_COMPONENT_REGISTRY
        )
        registry.register_contributor(MyContributor(...))
        registry.register_guard(MyGuard(...))
        registry.register_ranker(MyRanker(...))
```

If you need to replace the policy resolver, state store, memory writer, or
cache, set that single-slot collaborator intentionally and document the
ownership boundary. Do not silently register competing implementations.

## Control-Plane Mapping

The context engine plugin resolves ACP-managed resources into runtime behavior.

- `ContextProfiles`
  - select assistant persona by `platform`, `channel_key`, and optional
    `client_profile_key`
- `ContextPolicies`
  - provide explicit budget, redaction, retention, contributor allow/deny,
    source allow/deny, trace, and cache settings
- `ContextContributorBindings`
  - contribute scope-aware contributor allow rules
- `ContextSourceBindings`
  - contribute scope-aware source-kind allow rules into resolved policy
- `ContextTracePolicies`
  - influence trace capture enablement and trace metadata

Current implementation detail:

- contributor allow/deny is enforced during collection
- source allow/deny is resolved into `ContextPolicy` and metadata, but it is not
  applied by `DefaultContextEngine` unless a collaborator consults it itself

## Practical Examples

Reference implementations in core:

- persona/policy system lane:
  `mugen.core.plugin.context_engine.service.contributor.PersonaPolicyContributor`
- bounded state lane:
  `mugen.core.plugin.context_engine.service.contributor.StateContributor`
- recent-turn replay:
  `mugen.core.plugin.context_engine.service.contributor.RecentTurnContributor`
- knowledge evidence retrieval:
  `mugen.core.plugin.context_engine.service.contributor.KnowledgePackContributor`
- channel/case/audit overlays:
  `ChannelOrchestrationContributor`, `OpsCaseContributor`, `AuditContributor`
- memory recall and writeback:
  `MemoryContributor`, `DefaultMemoryWriter`
- default guard/ranker/cache:
  `DefaultContextGuard`, `DefaultContextRanker`, `RelationalContextCache`
- default state/trace services:
  `RelationalContextStateStore`, `RelationalContextTraceSink`

Useful test coverage:

- `mugen_test/test_mugen_service_context_engine.py`
  - prepare/commit orchestration
  - selection, dedupe, budget drops, trace recording
- `mugen_test/test_mugen_context_engine_plugin_runtime.py`
  - policy resolver behavior
  - built-in contributor examples
  - cache, trace sink, memory writer, guard, and ranker behavior
- `mugen_test/test_mugen_context_engine_fw_ext.py`
  - runtime registry wiring

## Guardrails

- Keep all artifacts and persisted runtime records tenant-safe.
- Use stable contributor/source identifiers so traces and ACP bindings remain
  meaningful.
- Choose an existing compiled lane unless you are also changing the engine's
  message compiler.
- Set `estimated_token_cost` realistically; selection budgets depend on it.
- Do not rely on ranking alone to enforce safety. Use guards for hard vetoes.
- Do not rely on cache entries for authoritative state.
- Under `GLOBAL_TENANT_ID`, keep long-term memory partitioned by sender or
  conversation unless you are deliberately changing the safety model.
- Preserve provenance on selected evidence so downstream operators can explain
  why context was included.
- Expect dropped candidates to show up in bundle traces with explicit reasons
  such as duplicate, guard, or budget.

## When To Change Core Instead

Change only collaborators when you are adding domain-specific retrieval,
overlay, ranking, safety, tracing, or writeback behavior.

Change the core engine itself only when you need to alter:

- lane compilation semantics
- selection order/budget behavior
- commit-token semantics
- registry ownership model
- first-class enforcement of policy fields that the current engine only resolves

