# Context Engine Authoring Guide

Status: Active
Last Updated: 2026-03-09
Audience: Downstream plugin authors, core maintainers

## Purpose

This guide explains how to extend muGen's runtime context seam safely.

Use it when you need tenant-scoped runtime context behavior through the core
context engine instead of legacy CTX/RAG hooks.

For hard runtime semantics, see `docs/context-engine-design.md`.
For the decision log behind the current design, see
`docs/context-engine-strengthening-decisions.md`.

## Read This First

Contract guarantee: the design doc defines the hard runtime contract.

Default engine behavior: the core `DefaultContextEngine` implements that
contract with one deterministic pipeline and one default selector.

Current core plugin implementation: `mugen.core.plugin.context_engine` is the
reference plugin. It is not the whole API surface.

If you are unsure whether a behavior belongs in core or in collaborator space,
prefer collaborator space first.

## Runtime Flow

Default engine behavior: prepare flow runs in this order:

1. resolve `ContextPolicy`
2. load bounded `ContextState`
3. collect candidates from registered contributors
4. enforce source policy
5. apply guards
6. apply rankers
7. deduplicate
8. select within budget
9. render selected artifacts into `CompletionRequest.messages`
10. emit retrieval/prefix cache entries when enabled
11. record prepare traces when enabled

Default engine behavior: commit flow runs in this order:

1. validate and acquire the issued commit token through `IContextCommitStore`
2. save bounded state
3. persist memory writes
4. update working-set cache entries
5. finalize the commit ledger
6. record commit traces

Use prepare for runtime context selection. Use commit for post-turn persistence
that depends on the final assistant-visible outcome.

## Choose The Right Collaborator

### `IContextContributor`

Use a contributor when you need to fetch or synthesize context before model
completion.

- Input: `ContextTurnRequest`, resolved `ContextPolicy`, current `ContextState`
- Output: `list[ContextCandidate]`
- Good fit: recent-turn replay, knowledge retrieval, ops overlays, memory recall
- Do not use for post-turn persistence

### `IContextGuard`

Use a guard when you need to veto or remove candidates before ranking and
selection.

- Input: current candidate list plus request/policy/state
- Output: `ContextGuardResult` preferred; `list[ContextCandidate]` is tolerated
  only as a compatibility shape
- Good fit: tenant isolation, sensitivity blocking, global-fallback safety
- Do not use for storage, retrieval, or ranking

### `IContextRanker`

Use a ranker when you need to score already-collected candidates.

- Input: current candidate list plus request/policy/state
- Output: the same candidates with updated ordering/score metadata
- Good fit: trust/freshness heuristics, domain-specific scoring
- Do not use to own retrieval or persistence

### `IContextArtifactRenderer`

Use a renderer when you need a selected artifact family to compile into a
different message shape without adding a new core lane.

- Input: selected candidates for one `render_class`
- Output: `list[CompletionMessage]`
- Good fit: structured system payloads, recent-turn replay, future MCP/skill
  presentation adapters
- Do not use for retrieval or selection

### `IContextPolicyResolver`

Use a policy resolver when you need to turn scope and ACP-managed bindings into
one effective `ContextPolicy`.

- Input: `ContextTurnRequest`
- Output: resolved `ContextPolicy`
- Good fit: profile selection, budget/redaction/retention policy, contributor
  allow/deny, source rules, trace capture flags
- Do not use to fetch per-turn evidence

### `IContextStateStore`

Use a state store when you need bounded, scope-partitioned conversation state.

- Input: one scoped request during prepare/commit
- Output: loaded or saved `ContextState`
- Good fit: current objective, unresolved slots, safety flags, routing state
- Do not use for long-term memory or recent-turn replay history

### `IContextCommitStore`

Use a commit store when you need replay-safe commit-token issuance and
validation.

- Input: prepare fingerprint plus scoped commit lifecycle operations
- Output: opaque tokens and `ContextCommitCheck`
- Good fit: issued tokens, expiry, replay-safe duplicate delivery, failure
  states
- Do not hide these semantics inside the state store

### `IMemoryWriter`

Use a memory writer when you need post-turn long-term writeback after the final
assistant response is known.

- Input: request, prepared turn, completion result, final user responses,
  outcome
- Output: `list[MemoryWrite]`
- Good fit: episodic memory, preferences, facts, derived writeback
- Do not use for pre-turn recall

### `IContextCache`

Use a cache when you need provider-neutral working-set or retrieval caching.

- Input: namespace + tenant-safe key + payload
- Output: cached values or invalidation counts
- Good fit: working-set state hints, retrieval reuse, prefix fingerprints
- Do not use as authoritative state

### `IContextTraceSink`

Use a trace sink when you need prepare/commit observability.

- Input: request plus prepared/commit payloads
- Output: trace persistence side effects only
- Good fit: trace rows, audit bridge writes, diagnostics
- Do not use for primary business persistence

## Contributor Contract

Contract guarantee: contributors emit `ContextCandidate` values that wrap
`ContextArtifact`.

Each artifact should declare:

- stable `artifact_id`
- one of the five core lane buckets
- stable `kind`
- realistic `estimated_token_cost`
- `ContextProvenance`
- `render_class` when the built-in lane mapping is not enough

### Lane vs Render Class

Contract guarantee: lane is a budgeting/ordering primitive.

Contract guarantee: `render_class` is the presentation hook.

Guidance:

- use an existing lane whenever the new source family fits the existing budget
  semantics;
- add a new renderer before you propose a new lane;
- change core lanes only when the new source family truly needs new selection
  semantics, not just different formatting.

### Source Identity

Contract guarantee: source policy and dedupe work best when contributors emit
`ContextSourceRef` explicitly.

Populate:

- `kind`
- `source_key` when operators need a stable allow/deny handle
- `source_id` when the backing record has its own stable ID
- `canonical_locator` when there is a natural external or cross-system locator
- `segment_id` for sub-document or sub-record fragments
- `locale` / `category` when policy should be able to target them

Do not rely on ad hoc metadata keys when a field already exists on
`ContextSourceRef`.

### Dedupe Expectations

Default engine behavior:

- ranking runs before dedupe;
- dedupe groups by lane + render class + canonical source identity;
- if canonical source identity is absent, the engine falls back to content
  fingerprinting.

Implication for authors: if you want cross-contributor dedupe to be stable, emit
stable source identity.

## Guard Contract

Contract guarantee: guards are for hard vetoes, not annotations.

Preferred behavior:

- return `ContextGuardResult`
- keep passed candidates untouched
- emit dropped candidates with explicit `selection_reason` and `reason_detail`

Compatibility behavior:

- returning `list[ContextCandidate]` still works
- candidates omitted from the returned list are treated as dropped

Do not rely on leaving a blocked candidate in the returned list with a drop
reason attached. That shape is no longer the primary contract.

## Ranker Contract

- set or update `ContextCandidate.score`
- keep scoring logic pure relative to the already-collected candidates
- assume selection still happens later under lane priority and budget limits

Current default engine behavior: selection sorts by lane priority first, then
score, then candidate priority. Rankers influence ordering inside that model;
they do not replace it.

## Renderer Contract

- declare stable `render_class`
- validate that the received candidates match the renderer's expectations
- produce only normalized `CompletionMessage` values
- keep provider-specific prompting out of the renderer contract

Current core plugin implementation:

- structured lane renderers emit one `system` message per lane bucket
- recent-turn renderer emits replay messages from stored `role` and `content`

## State vs History

Contract guarantee:

- `ContextState` is compact operational control state
- recent-turn replay remains event/history material

Keep in bounded state:

- objective
- entities
- constraints
- unresolved slots
- commitments
- safety flags
- routing
- explicit compact summaries

Keep in history/event material:

- user transcript
- assistant transcript
- replayable turn content
- evidence bodies and raw retrieval payloads

Do not automatically promote assistant text, raw transcript, or retrieval
evidence into durable state.

## Budget Contract

Contract guarantee: token estimation is a collaborator obligation.

Set `estimated_token_cost` realistically enough that:

- hard budgets stay deterministic
- lane reservations behave predictably
- trace explanations remain credible to operators

Default engine behavior supports:

- hard totals
- soft totals
- per-lane minima/maxima
- per-lane token reservations
- spillover control
- `budget_hints` that tighten but do not widen policy ceilings

Current core plugin implementation leaves `adaptive_trimming="none"` by
default.

## Commit Token Contract

Contract guarantee:

- prepare issues one opaque token
- commit validates scope binding and prepared fingerprint
- successful duplicates may replay stored results
- expiry and failed/in-flight states fail closed

Implications for authors:

- do not mint commit tokens yourself
- do not treat the token as a deterministic checksum
- do not write state or memory outside the commit path if you expect
  replay-safe semantics

## Trace Contract

- respect `trace_enabled`
- respect prepare vs commit capture flags
- respect selected vs dropped item capture flags
- keep trace persistence non-authoritative

Current core plugin implementation filters selected/dropped payloads before
persistent trace writes.

## Registration Path

Runtime collaborators are registered through an FW extension. The built-in
`core.fw.context_engine` extension is the reference shape.

Registry cardinality:

- many contributors
- many guards
- many rankers
- many renderers
- many trace sinks
- one policy resolver
- one state store
- one commit store
- one memory writer
- one cache

Single-owner guidance:

- treat policy resolver, state store, commit store, memory writer, and cache as
  one engine-visible owner each
- if you need multiple internal implementations, compose them behind one owner
  instead of registering silent competitors

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
        registry.register_renderer(MyRenderer(...), owner="my_plugin")
```

If you replace a single-owner collaborator, pass an explicit owner and document
that ownership boundary.

## ACP Inputs vs Current Plugin Mapping

### ACP Inputs The Engine Contract Understands

- profile selection inputs
- budget data
- redaction data
- retention data
- contributor allow/deny
- source rules
- trace capture flags

### Current Core Plugin Mapping

- `ContextProfiles`
  - select assistant persona by `platform`, `channel_key`, and optional
    `client_profile_key`
- `ContextPolicies`
  - provide budget, redaction, retention, contributor allow/deny, source
    allow/deny, trace, and cache settings
- `ContextContributorBindings`
  - contribute scope-aware contributor allow rules
- `ContextSourceBindings`
  - contribute scope-aware source allow rules with optional `source_key`,
    `locale`, and `category`
- `ContextTracePolicies`
  - influence prepare/commit capture and selected/dropped trace detail

Current core plugin implementation detail: `ContextSourceBindings` map to allow
rules. Deny rules still come from `ContextPolicies`.

## Reference Implementations

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
- default renderer, guard, ranker, cache, commit, state, and trace services:
  `StructuredLaneRenderer`, `RecentTurnMessageRenderer`,
  `DefaultContextGuard`, `DefaultContextRanker`, `RelationalContextCache`,
  `RelationalContextCommitStore`, `RelationalContextStateStore`,
  `RelationalContextTraceSink`

Useful test coverage:

- `mugen_test/test_mugen_service_context_engine.py`
- `mugen_test/test_mugen_context_engine_plugin_runtime.py`
- `mugen_test/test_mugen_context_engine_fw_ext.py`

## Guardrails

- keep all artifacts and persisted runtime records tenant-safe
- use stable contributor and source identifiers so policy and trace behavior
  stays explainable
- choose an existing lane unless you truly need new budget semantics
- choose a renderer before you propose a new lane
- set `estimated_token_cost` realistically
- use guards for hard safety boundaries
- do not rely on cache entries for authoritative state
- under `GLOBAL_TENANT_ID`, keep long-term memory partitioned by sender or
  conversation unless you are deliberately changing the safety model

## When To Change Core Instead

Change only collaborators when you are adding domain-specific retrieval,
overlay, ranking, safety, tracing, or writeback behavior.

Change the core engine only when you need to alter:

- source-policy enforcement semantics
- lane bucket semantics
- renderer dispatch semantics
- selection order/budget behavior
- commit-token lifecycle semantics
- registry ownership semantics
