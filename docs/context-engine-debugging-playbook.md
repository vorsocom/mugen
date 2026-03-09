# Context Engine Debugging Playbook

Status: Draft
Last Updated: 2026-03-09
Audience: operators, on-call engineers, core maintainers, downstream plugin authors

## Purpose

This playbook is for production incidents where the assistant appears to have
used the wrong context, ignored the right context, or persisted the wrong
post-turn side effect.

Use it for questions such as:

- Why did the assistant answer from stale evidence?
- Why did the wrong tenant profile or persona apply?
- Why did a candidate get dropped?
- Why did bounded state not influence the answer?
- Why did a fallback-global turn behave differently?
- Why did memory writeback happen or not happen?
- Why did a repeated turn miss cache reuse?
- Why did commit fail after prepare succeeded?
- Why did a contributor appear to do nothing?

This guide is about context-runtime behavior, not generic model debugging.

Bad model behavior and bad context preparation are different failure classes:

- bad context preparation means the model received the wrong `CompletionRequest`
  or a materially incomplete one;
- bad model behavior means the compiled context bundle was reasonable, but the
  completion result was still poor;
- commit/writeback problems affect future turns even when the current response
  looked acceptable.

Prepare-phase debugging asks:

- what scope was used;
- what `ContextPolicy` resolved;
- what `ContextState` loaded;
- which `ContextCandidate` values were collected;
- what was dropped by source policy, guard, dedupe, or budget;
- what was finally compiled into `CompletionRequest.messages`.

Commit-phase debugging asks:

- whether the opaque commit token was still valid for this scope and prepared
  fingerprint;
- whether state, memory, cache, and trace persistence ran successfully;
- whether the final turn outcome changed what was persisted.

Traces and provenance matter because the context engine is tenant-scoped and
fail-closed. A bad answer is not enough to diagnose the problem. Operators need
to know:

- which tenant scope the turn actually ran under;
- which collaborators produced the selected artifacts;
- which source identity each artifact claimed;
- which candidates were dropped and why;
- whether the failure was in prepare, completion, or commit.

## If You Only Have 5 Minutes

Use this checklist before you read any deeper section.

1. Confirm `tenant_resolution.mode` in `ingress_metadata`.
   `resolved` and `fallback_global` are different incidents.
2. Confirm `ContextScope`.
   A changed `conversation_id`, `sender_id`, `case_id`, or `workflow_id`
   changes the `scope_key` and therefore changes state, recent-turn history,
   cache partitions, and memory partition matching.
3. Confirm the active policy/profile.
   Inspect `PreparedContextTurn.bundle.policy` and
   `CompletionRequest.vendor_params["context_policy"]` if present.
4. Confirm prepare selected anything in the expected lanes.
   Check `system_persona_policy`, `bounded_control_state`, `operational_overlay`,
   `recent_turn`, and `evidence`.
5. Inspect selected versus dropped artifacts.
   Look for obvious `dropped_source_policy`, `dropped_guard`,
   `dropped_duplicate`, and `dropped_budget`.
6. Check evidence freshness and provenance.
   A stale answer often starts with a stale or low-trust selected `evidence`
   artifact.
7. Check whether bounded state existed at all.
   If `bundle.state` is `null` and no `bounded_control_state` artifact was
   selected, the model could not use bounded state.
8. Check whether recent-turn replay existed.
   If the user’s clarification is missing from `recent_turn`, forgetting it is
   expected.
9. Check the commit outcome.
   A correct response with a failed commit explains why the next turn forgot it.
10. Check for obvious guard drops.
    Cross-tenant artifacts, blocked sensitivity, and unpartitioned global
    memory are dropped before ranking.
11. Check for obvious budget drops.
    `lane_max_items:*`, `max_prefix_tokens`, and `soft_max_total_tokens` are
    common reasons a useful artifact never reached compilation.

## Mental Model

Operational sequence in the default runtime:

```text
Messaging ingress
  -> ContextScope resolution
  -> ContextTurnRequest
  -> IContextPolicyResolver.resolve_policy(...)
  -> IContextStateStore.load(...)
  -> IContextContributor.collect(...)
  -> source policy enforcement
  -> IContextGuard.apply(...)
  -> IContextRanker.rank(...)
  -> dedupe
  -> budget selection
  -> IContextArtifactRenderer.render(...)
  -> CompletionRequest.messages
  -> completion gateway
  -> RPP extensions
  -> CT extensions
  -> IContextCommitStore.begin_commit(...)
  -> IContextStateStore.save(...)
  -> IMemoryWriter.persist(...)
  -> IContextCache.put(...)
  -> IContextCommitStore.complete_commit(...)
  -> IContextTraceSink.record_commit(...)
```

### Prepare vs commit in practice

- Prepare is where bad context is usually introduced.
- Commit is where future-turn problems are introduced.
- The built-in text handler still attempts commit after completion failure.
  That means state/history can change even on a failed completion path.
- The built-in text handler logs commit failures and does not surface them to
  the user directly. A user can see a plausible answer while the next turn
  still forgets it.

### What evidence is trustworthy

Treat these as authoritative for the current turn:

- `ContextScope`
- resolved `ContextPolicy`
- `PreparedContextTurn.bundle.state`
- `PreparedContextTurn.bundle.selected_candidates`
- `PreparedContextTurn.bundle.dropped_candidates`
- compiled `CompletionRequest.messages`
- `ContextCommitResult`
- persisted `ContextTrace` rows when trace capture is enabled

Treat these as suggestive, not authoritative:

- absence of a contributor’s artifacts in a trace
  because the contributor may have been disabled, denied by policy, returned no
  candidates, failed and been logged, or had trace capture suppressed;
- `policy.metadata`
  because it is convenience metadata, not the full effective runtime decision
  surface;
- cache presence
  because the default engine writes cache hints and working-set records but does
  not read them during prepare.

### Common runtime artifacts

Example `ContextScope`:

```text
{
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "platform": "telegram",
  "channel_id": "vip-concierge",
  "room_id": "pickup-991",
  "sender_id": "guest-8841",
  "conversation_id": "pickup-991",
  "case_id": "6a09f01a-9e6a-48b3-9a2e-cbb6c4edbe8e",
  "workflow_id": "wf-airport-77"
}
```

Example selected artifact row:

```text
{
  "artifact_id": "knowledge:9af0",
  "lane": "evidence",
  "render_class": "evidence_items",
  "kind": "knowledge_span",
  "contributor": "knowledge_pack",
  "score": 79.4,
  "reason": "selected",
  "detail": null,
  "source": {
    "kind": "knowledge_pack_revision",
    "source_key": "airport-transfer-outage",
    "source_id": "9af0",
    "canonical_locator": "knowledge-pack-revision:9af0",
    "segment_id": "7",
    "locale": "en-US",
    "category": "transfer-ops"
  }
}
```

Example dropped artifact row:

```text
{
  "artifact_id": "memory:12",
  "lane": "evidence",
  "render_class": "evidence_items",
  "kind": "memory",
  "contributor": "memory",
  "score": 73.0,
  "reason": "dropped_policy",
  "detail": "global_memory_requires_partition",
  "source": {
    "kind": "memory_record",
    "source_key": "12"
  }
}
```

Example `ContextState`:

```text
{
  "current_objective": "Reschedule airport pickup",
  "entities": {
    "pickup_reference": "PU-4491",
    "pickup_time": "01:30"
  },
  "unresolved_slots": [],
  "routing": {
    "conversation_id": "pickup-991",
    "case_id": "6a09f01a-9e6a-48b3-9a2e-cbb6c4edbe8e",
    "tenant_resolution": {
      "mode": "resolved",
      "source": "vip_router"
    }
  },
  "summary": "VIP pickup in progress.",
  "revision": 8
}
```

Example commit result:

```text
{
  "commit_token": "ctxcmt_7f3d...",
  "state_revision": 9,
  "memory_writes": [],
  "cache_updates": {
    "working_set": "tenant:11111111-1111-1111-1111-111111111111:working_set:8f..."
  },
  "warnings": []
}
```

Example memory write:

```text
{
  "write_type": "preference",
  "content": {
    "statement": "I prefer aisle seats on overnight trips."
  },
  "scope_partition": {
    "platform": "web",
    "channel_id": "preferences-desk",
    "sender_id": "guest-510",
    "conversation_id": "prefs-88"
  },
  "subject": "guest-510"
}
```

Example cache namespaces and keys:

```text
working_set:
tenant:<tenant_id>:working_set:<scope_key>

retrieval:
tenant:<tenant_id>:retrieval:<scope_key>:<request_hash>

prefix_fingerprint:
tenant:<tenant_id>:prefix_fingerprint:<scope_key>:<prefix_fingerprint>
```

## Where to look first

| Symptom | Most likely layer | Key evidence to inspect | Typical root causes | First actions |
| --- | --- | --- | --- | --- |
| Answered with stale info | `IContextContributor`, `IContextRanker`, selection budget | selected `evidence`, dropped `evidence`, provenance freshness/trust | stale knowledge revision, newer evidence not retrieved, newer evidence ranked lower, budget kept only stale item | inspect selected and dropped `evidence` rows first |
| Ignored an active case/workflow | `IContextStateStore`, `OpsCaseContributor`, `ChannelOrchestrationContributor`, compiler | `bundle.state`, selected `operational_overlay`, `ContextScope.case_id`, `workflow_id` | wrong scope, missing case link, contributor returned nothing, overlay dropped by budget | confirm scope before touching rankers |
| Forgot user’s recent clarification | `RecentTurnContributor`, state store | selected `recent_turn`, event-log rows, `max_recent_messages` | commit failed on prior turn, new scope key, recent-turn budget too tight | compare current scope to prior turn and inspect event log |
| Mentioned data from the wrong tenant | guard, provenance, fallback handling | candidate provenance tenant, guard drops, `tenant_resolution` mode | contributor emitted wrong `tenant_id`, provenance missing, unsafe global fallback assumption | stop and inspect selected provenance first |
| Had the right evidence but still answered badly | completion/RPP/CT path, not context selection | compiled `CompletionRequest.messages`, selected artifacts, final completion text | model judgment issue, RPP changed answer, CT side effect unrelated | verify compiled request before changing contributors |
| Wrote a bad preference into memory | `IMemoryWriter`, final turn outcome | commit result, memory rows, user message, final response | default writer heuristic matched too broadly, wrong partition, outcome unexpectedly `completed` | inspect commit-stage trace and persisted memory rows |
| Repeated a previously dropped mistake | memory/state persistence, not current prepare only | commit result, memory rows, state revision, clear-history usage | bad memory write, bad bounded-state save, clear-history did not clear memory | inspect prior commit before current prepare |
| Prepare succeeded but commit failed | commit store, state/memory/cache persistence | commit warnings, logs, commit ledger row, commit-stage trace | expired token, scope mismatch, prepared mismatch, storage failure | inspect commit ledger and logs |
| Behavior changed after control-plane edits | policy resolver | resolved profile/policy, contributor/source allow rules, trace policy | different profile match, different ACP policy row, trace policy change, source bindings change | capture effective policy for one good and one bad turn |
| Contributor appears registered but has no effect | resolver, contributor, source policy, guard, budget | contributor allowlist, selected/dropped artifacts, logs | contributor denied, exception swallowed, no data returned, all output later dropped | check allow/deny and logs before changing ranking |

## Debugging policy resolution and profile selection

### Symptom

The assistant used the wrong persona, wrong evidence policy, wrong budget, or
different trace behavior than expected.

### Likely layers involved

- `IContextPolicyResolver`
- ACP-managed `ContextProfiles`
- ACP-managed `ContextPolicies`
- ACP-managed `ContextContributorBindings`
- ACP-managed `ContextSourceBindings`
- ACP-managed `ContextTracePolicies`

### What to inspect

- `ContextScope`
- `ingress_metadata["ingress_route"]["client_profile_key"]` when present
- `PreparedContextTurn.bundle.policy`
- `CompletionRequest.vendor_params["context_policy"]`
- active `ContextProfiles`, `ContextPolicies`, `ContextContributorBindings`,
  `ContextSourceBindings`, `ContextTracePolicies` rows for the tenant

Example resolved policy shape:

```text
{
  "profile_key": "vip-sms",
  "policy_key": "vip-tight",
  "contributor_allow": [
    "persona_policy",
    "state",
    "knowledge_pack",
    "recent_turns"
  ],
  "source_rules": [
    {
      "effect": "allow",
      "kind": "knowledge_pack_revision",
      "source_key": "airport-transfer",
      "locale": "en-US",
      "category": "transfer-ops"
    },
    {
      "effect": "deny",
      "kind": "memory_record"
    }
  ],
  "trace_enabled": true,
  "cache_enabled": true,
  "metadata": {
    "profile_name": "vip-sms",
    "persona": "White-glove travel desk",
    "trace_policy_name": "vip-debug"
  }
}
```

### How to reason about the evidence

- If `profile_key` or `policy_key` is already wrong in the prepared bundle, the
  rest of the turn is downstream of a resolver problem.
- If the policy is correct but the compiled request still looks wrong, move on
  to contributor, guard, or selection debugging.
- If the trace policy capture flags differ from expectation, missing trace items
  may be policy, not runtime failure.

### Common root causes

- wrong `client_profile_key` or missing one in ingress metadata;
- scope matched a more general `ContextProfile` than expected;
- profile pointed at a different `ContextPolicy` row than intended;
- policy changed `contributor_allow`, `source_allow`, `source_deny`, or budget;
- control-plane edits changed the tenant default policy;
- current implementation detail: trace policy selection is tenant-level and the
  resolver uses the first active `ContextTracePolicy` row it receives;
- current implementation detail: contributor-binding `priority` exists on ACP
  rows but is not consulted by the default engine for execution order.

### Step-by-step investigation

1. Capture `ContextScope` and `ingress_metadata`.
2. Confirm whether the turn is `resolved` or `fallback_global`.
3. Read the prepared bundle policy before looking at the completion output.
4. Compare the prepared policy against the expected profile and policy rows.
5. Confirm the incoming `client_profile_key` if the tenant expects
   client-profile-specific behavior.
6. Compare the matched scope fields against profile fields:
   `platform`, `channel_key`, `client_profile_key`.
7. Inspect contributor and source binding rows for the same tenant.
8. If trace capture differs from expectation, inspect `ContextTracePolicies`.
9. Only after policy is confirmed should you inspect selected/dropped artifacts.

### Example trace interpretation

```text
{
  "scope": {
    "tenant_id": "11111111-1111-1111-1111-111111111111",
    "platform": "web",
    "channel_id": "vip-concierge"
  },
  "selected": [
    {
      "artifact_id": "persona-policy:default",
      "lane": "system_persona_policy",
      "contributor": "persona_policy",
      "source": {
        "kind": "context_policy",
        "source_key": "default"
      }
    }
  ]
}
```

If the operator expected `vip-tight` and the selected persona artifact already
points to `default`, do not debug rankers or evidence first. The resolver chose
the wrong policy.

### Fix paths

- operator/config fixes:
  correct `ContextProfile` matching rows, policy links, source bindings, or
  ingress metadata that carries `client_profile_key`
- plugin-author fixes:
  if a downstream resolver replacement exists, confirm it preserves the core
  contract and returns one effective `ContextPolicy`
- core-engine fixes:
  only if the matching rules or trace-policy selection behavior itself is wrong

### Contract vs implementation notes

- contract guarantee: one effective `ContextPolicy` is resolved before state
  load and candidate collection
- default engine behavior: prepare starts with policy resolution
- current implementation detail: profile matching considers `platform`,
  `channel_key`, `client_profile_key`, then `is_default`
- current implementation detail: policy selection uses the profile-linked policy
  first, then a default policy row, then the first available policy row

## Debugging missing or bad bounded state

### Symptom

The assistant ignores the active conversation objective, asks for information it
already had, or behaves as if the turn started from scratch.

### Likely layers involved

- `IContextStateStore`
- `StateContributor`
- `bounded_control_state`
- `RecentTurnContributor`

### What to inspect

- `ContextScope`
- `PreparedContextTurn.bundle.state`
- selected `bounded_control_state` artifact
- recent `ContextStateSnapshot` row for the scope
- recent `ContextEventLog` rows for the scope

### How to reason about the evidence

- If `bundle.state` is `null`, the engine did not load bounded state.
- If `bundle.state` exists but no `bounded_control_state` artifact was selected,
  selection or compilation removed it later.
- If the bounded state artifact exists but contains only the current user
  message as `current_objective`, the store may be behaving as designed but the
  state is not rich enough to help.

### Common root causes

- scope changed, so `scope_key` changed and state partition moved;
- prior commit failed, so no new snapshot revision was persisted;
- state store contains only shallow state because no domain-specific state
  enrichment exists;
- bounded state was present but the model mostly depended on recent turns or
  overlays instead;
- current implementation detail: `RelationalContextStateStore.save(...)`
  preserves most existing fields and sets `current_objective` from the current
  user message rather than running domain-specific slot extraction.

### Step-by-step investigation

1. Compare the bad turn’s `ContextScope` with the prior successful turn.
2. Confirm whether `conversation_id`, `sender_id`, `case_id`, or `workflow_id`
   changed.
3. Inspect `bundle.state`.
4. Inspect the selected `bounded_control_state` candidate in the prepare trace.
5. Inspect the corresponding `ContextStateSnapshot` row and its `revision`.
6. Inspect recent `ContextEventLog` rows for the same `scope_key`.
7. If the snapshot is shallow but correct, do not treat that as a load failure.
   It may be a state-authoring problem instead.

### Example trace interpretation

```text
{
  "selected": [
    {
      "artifact_id": "bounded-state",
      "lane": "bounded_control_state",
      "kind": "state_snapshot",
      "detail": null
    }
  ],
  "scope": {
    "conversation_id": "pickup-118"
  }
}
```

If the trace shows `bounded-state` selected but the content lacks the pickup
reference the operator expected, the problem is earlier than selection. Inspect
the persisted snapshot row next.

### Fix paths

- operator/config fixes:
  correct the scope fields or upstream case/workflow linking that should
  partition turns together
- plugin-author fixes:
  enrich `ContextState` through domain-specific logic instead of expecting the
  default store to infer slots from arbitrary text
- core-engine fixes:
  only if the state store loads the wrong scope row or the engine fails to emit
  the state artifact when `state` is present

### Contract vs implementation notes

- contract guarantee: bounded state and recent-turn history are distinct stores
- default engine behavior: state loads before contributors run
- current implementation detail: the default store appends user and assistant
  events to `ContextEventLog` and writes a shallow bounded snapshot

## Debugging contributor recall failures

### Symptom

A contributor is registered but appears to have produced no useful effect.

### Likely layers involved

- `IContextContributor`
- policy resolver contributor allow/deny
- source policy
- guard
- selection budget

### What to inspect

- `PreparedContextTurn.bundle.policy.contributor_allow`
- `PreparedContextTurn.bundle.policy.contributor_deny`
- selected and dropped artifacts for the contributor
- application logs for contributor exceptions
- relevant backing rows or services for the contributor’s domain

### How to reason about the evidence

- If the contributor name is not allowed, it never ran.
- If the contributor ran and emitted artifacts, traces can confirm whether they
  were later dropped.
- If there are no contributor artifacts anywhere and no relevant drops, absence
  alone is suggestive. The contributor may have returned `[]`, failed and been
  logged, or had no matching source data.

### Common root causes

- contributor denied by `contributor_allow` or `contributor_deny`;
- contributor returned no candidates because the request had no matching domain
  key such as `case_id`, `trace_id`, or relevant locale/category;
- contributor raised an exception and the default engine logged a warning and
  continued;
- contributor produced artifacts that source policy or guards removed;
- contributor produced artifacts, but budget or dedupe dropped them later.

### Step-by-step investigation

1. Confirm the contributor’s stable `name`.
2. Confirm the resolved policy allows that contributor.
3. Inspect selected and dropped artifacts for that contributor.
4. If none exist, inspect logs for `"Context contributor failed"`.
5. Inspect the contributor’s upstream lookup inputs:
   `trace_id`, `case_id`, `locale`, `category`, `sender_id`, or scope partition.
6. If the contributor did emit artifacts, move to source-policy, guard, dedupe,
   or budget debugging instead of rewriting the contributor first.

### Example trace interpretation

```text
{
  "dropped": [
    {
      "artifact_id": "knowledge:old-44",
      "contributor": "knowledge_pack",
      "reason": "dropped_budget",
      "detail": "lane_max_items:evidence"
    }
  ]
}
```

This is not a contributor failure. The contributor worked. Selection later
removed its artifact.

### Fix paths

- operator/config fixes:
  correct contributor bindings, category/locale metadata, or linked business
  object IDs
- plugin-author fixes:
  emit better `ContextSourceRef`, provenance, trust/freshness, and token-cost
  metadata; log or test no-data paths clearly
- core-engine fixes:
  only if the engine skipped an allowed contributor or mishandled contributor
  exceptions

### Contract vs implementation notes

- contract guarantee: contributors emit `ContextCandidate` values
- default engine behavior: contributors run after policy resolution and state
  load, before source policy and guards
- current implementation detail: contributor exceptions are logged and skipped;
  they do not fail prepare by default

## Debugging source-policy drops

### Symptom

The expected artifact was collected by a contributor but was dropped before
guards and ranking.

### Likely layers involved

- source policy enforcement in `DefaultContextEngine`
- `ContextSourceRef`
- `ContextSourceRule`
- policy resolver and source bindings

### What to inspect

- dropped candidates with `dropped_source_policy`
- `detail` values such as `source_deny`, `source_allow`, and
  `missing_source_ref`
- resolved `ContextPolicy.source_rules`
- candidate `source` identity

### How to reason about the evidence

- `dropped_source_policy` means the contributor worked and emitted a candidate.
- `source_deny` means a deny rule matched.
- `source_allow` means allow rules existed and the candidate did not match any.
- `missing_source_ref` means an allow rule required structured source identity
  beyond kind and the candidate did not provide a matching `ContextSourceRef`.

### Common root causes

- contributor emitted only `source_kind` and omitted `source_key`, `locale`, or
  `category` needed for allow-rule matching;
- `ContextSourceBindings` or policy rows changed the allow/deny surface;
- operator expected kind-level allow behavior, but the rule required more
  structured identity;
- contributor emitted the wrong source identity for the underlying record.

### Step-by-step investigation

1. Inspect the dropped artifact row.
2. Confirm the `detail` value.
3. Inspect the candidate `source` block and compare it with the resolved
   `source_rules`.
4. If the row shows `missing_source_ref`, inspect the contributor’s emitted
   `ContextSourceRef`.
5. If the row shows `source_deny`, inspect the deny rule that matched.
6. Only after source-policy fit is confirmed should you inspect guards or
   ranking.

### Example trace interpretation

```text
{
  "artifact_id": "knowledge:44",
  "contributor": "knowledge_pack",
  "reason": "dropped_source_policy",
  "detail": "missing_source_ref",
  "source": null
}
```

This is not a retrieval failure. It means the artifact did not carry the source
identity required by the effective allow rules.

### Fix paths

- operator/config fixes:
  correct source bindings or policy rows if they are narrower than intended
- plugin-author fixes:
  emit the required `ContextSourceRef` fields consistently
- core-engine fixes:
  only if a correct `ContextSourceRef` is still being mismatched

### Contract vs implementation notes

- contract guarantee: source policy is engine-enforced, not advisory
- contract guarantee: allow/deny evaluation is based on `ContextSourceRef`
- default engine behavior: source policy runs before guards

## Debugging guard over-blocking and under-blocking

### Symptom

Expected artifacts disappeared, or unsafe artifacts reached compilation.

### Likely layers involved

- `IContextGuard`
- provenance
- redaction policy
- fallback-global handling

### What to inspect

- dropped candidates with `dropped_guard`, `dropped_policy`, or
  `dropped_tenant_mismatch`
- artifact provenance tenant and sensitivity
- `ContextPolicy.redaction`
- `tenant_resolution.mode`

### How to reason about the evidence

- `dropped_tenant_mismatch` is strong evidence that provenance tenant isolation
  worked.
- `dropped_policy` with `global_memory_requires_partition` is expected for
  unpartitioned global memory on fallback-global turns.
- If unsafe content reached compilation, inspect whether provenance `tenant_id`
  was missing or incorrect. The default guard only blocks tenant mismatch when
  a provenance tenant is present.

### Common root causes

- contributor emitted wrong provenance tenant;
- contributor omitted sensitivity labels or provenance tenant;
- blocked sensitivity labels were configured too broadly;
- fallback-global turn tried to recall unpartitioned memory;
- operator expected source policy to do what only a guard can do.

### Step-by-step investigation

1. Confirm whether the turn was `resolved` or `fallback_global`.
2. Inspect all dropped guard-related rows.
3. Inspect the selected artifacts that should have been blocked.
4. Read each selected artifact’s provenance tenant and sensitivity labels.
5. Compare those fields with the resolved scope tenant and redaction policy.
6. If the artifact lacked the metadata the guard needed, move to contributor
   debugging.

### Example trace interpretation

```text
{
  "dropped": [
    {
      "artifact_id": "memory:12",
      "contributor": "memory",
      "reason": "dropped_policy",
      "detail": "global_memory_requires_partition"
    },
    {
      "artifact_id": "audit:trace-77",
      "contributor": "audit",
      "reason": "dropped_guard",
      "detail": "blocked_sensitivity"
    }
  ]
}
```

This confirms the guard path is functioning. Do not debug rankers until you
understand why the artifacts were blocked.

### Fix paths

- operator/config fixes:
  narrow blocked sensitivity labels, fix routing so the turn is not
  fallback-global, or disable unsafe sources through policy
- plugin-author fixes:
  emit correct provenance tenant and sensitivity metadata
- core-engine fixes:
  only if the guard misapplies a correct policy

### Contract vs implementation notes

- contract guarantee: blocked artifacts do not reach completion compilation
- default engine behavior: guards run after source policy and before ranking
- current implementation detail: `DefaultContextGuard` enforces tenant mismatch,
  blocked sensitivity, and unpartitioned global-memory blocking

## Debugging ranker ordering surprises

### Symptom

A worse candidate survived while a better one in the same lane lost.

### Likely layers involved

- `IContextRanker`
- selection ordering
- evidence freshness/trust metadata

### What to inspect

- selected and dropped candidates in the same lane
- `score`, `priority`, `trust`, `freshness`, and `estimated_token_cost`
- lane of each candidate

### How to reason about the evidence

- Rankers matter inside the engine’s selection model, not outside it.
- The default selector sorts by lane priority first, then score, then priority.
- A ranker cannot make `evidence` outrank `bounded_control_state` or
  `system_persona_policy`.

### Common root causes

- operator expected a ranker to override lane priority;
- contributor emitted low freshness or low trust for the newer evidence;
- selected candidate had better score after cost penalty;
- ranking looked wrong, but the real issue was lane budget or dedupe.

### Step-by-step investigation

1. Restrict the comparison to candidates in the same lane first.
2. Compare their scores and raw artifact metadata.
3. Confirm whether the losing candidate was actually dropped by budget or
   dedupe after scoring.
4. If cross-lane ordering is the complaint, inspect lane choice before ranker
   logic.

### Example trace interpretation

```text
selected:
- artifact_id=knowledge:outage-2026-03-09 lane=evidence score=79.4

dropped:
- artifact_id=knowledge:faq-normal-hours lane=evidence reason=dropped_budget detail=lane_max_items:evidence score=76.8
```

This is expected if the outage notice legitimately outranked the FAQ.

### Fix paths

- operator/config fixes:
  widen lane budget if one evidence item is too strict for the tenant use case
- plugin-author fixes:
  adjust trust/freshness emission or custom ranker scoring
- core-engine fixes:
  only if sort order differs from the documented lane-priority then score model

### Contract vs implementation notes

- contract guarantee: rankers score already-collected candidates
- default engine behavior: selection sorts by lane priority first, then score,
  then candidate priority
- current implementation detail: `DefaultContextRanker` adds lane bonus, trust,
  freshness, candidate priority, and token-cost penalty

## Debugging budget trimming surprises

### Symptom

A useful artifact was collected but did not survive selection.

### Likely layers involved

- selection budget
- lane budgets
- `budget_hints`

### What to inspect

- dropped candidates with `dropped_budget`
- `ContextPolicy.budget`
- `request.budget_hints`
- lane counts and selected artifact counts

### How to reason about the evidence

- `lane_max_items:*` means lane-local trimming, not retrieval failure.
- `max_prefix_tokens` and `max_total_tokens` are hard ceilings.
- `soft_max_total_tokens` affects spillover selection only.
- `lane_reserved_tokens` means the selector preserved headroom for other lanes.

### Common root causes

- policy budget too small for the channel;
- `budget_hints` tightened policy ceilings unexpectedly;
- evidence lane max too low;
- reserved tokens protected another lane;
- operator expected `recent_turn` or `evidence` spillover when it was disabled.

### Step-by-step investigation

1. Read the resolved `ContextPolicy.budget`.
2. Compare it with `request.budget_hints`.
3. Read dropped budget reasons exactly as recorded.
4. Check whether the artifact was competing within its own lane or across the
   total token ceiling.
5. If the artifact lost to reserved tokens, inspect which other lane still had
   remaining candidates.

### Example trace interpretation

```text
{
  "artifact_id": "knowledge:general-fee-policy-v2",
  "reason": "dropped_budget",
  "detail": "lane_reserved_tokens"
}
```

Do not diagnose this as bad ranking first. The selector withheld capacity for
another lane.

### Fix paths

- operator/config fixes:
  adjust policy budget, lane budgets, or channel-specific profile limits
- plugin-author fixes:
  reduce token cost by summarizing content more tightly
- core-engine fixes:
  only if reserved-token or spillover behavior is incorrect

### Contract vs implementation notes

- contract guarantee: `ContextBudget` defines hard ceilings
- default engine behavior: lane minima fill first, then spillover
- current implementation detail: `budget_hints` can tighten an existing budget
  but do not widen it

## Debugging dedupe surprises

### Symptom

An artifact disappeared even though budget should have allowed it, or the wrong
duplicate survived.

### Likely layers involved

- dedupe
- contributor-emitted `ContextSourceRef`
- render class choice

### What to inspect

- dropped candidates with `dropped_duplicate`
- `metadata.dedupe.group`
- `metadata.dedupe.winner_artifact_id`
- source identity and render class on both winner and loser

### How to reason about the evidence

- Dedupe happens after ranking.
- The highest-ranked candidate in the dedupe group wins.
- Candidates only dedupe together if lane and render class match and source
  identity or content fingerprint matches.

### Common root causes

- two contributors emitted the same logical source into the same lane;
- contributor omitted stable source identity, forcing content-fingerprint
  dedupe;
- operator expected dedupe across lanes, which does not happen;
- a lower-quality winner had the higher score before dedupe.

### Step-by-step investigation

1. Read the dropped duplicate row.
2. Note the winner artifact ID and contributor.
3. Compare source identity payloads for winner and loser.
4. Compare their scores to see why the winner survived.
5. If the wrong candidate won, move back to ranking or contributor metadata.

### Example trace interpretation

```text
{
  "artifact_id": "knowledge:fee-waiver-policy-v6",
  "reason": "dropped_duplicate",
  "detail": "duplicate_source_artifact",
  "metadata": {
    "dedupe": {
      "winner_artifact_id": "knowledge:fee-waiver-policy-v7",
      "winner_contributor": "knowledge_pack"
    }
  }
}
```

This is expected if both revisions mapped to the same canonical source identity
and `v7` ranked higher.

### Fix paths

- operator/config fixes:
  none, unless source bindings or policy are causing the wrong source family to
  compete
- plugin-author fixes:
  emit stable `ContextSourceRef` values so dedupe is explainable and deliberate
- core-engine fixes:
  only if dedupe groups are formed incorrectly

### Contract vs implementation notes

- contract guarantee: dropped duplicates are traceable
- default engine behavior: dedupe uses lane + render class + canonical source
  identity, falling back to content fingerprint

## Debugging compiler and lane surprises

### Symptom

The selected bundle looks correct, but the compiled messages still look wrong,
or prepare fails late with a renderer error.

### Likely layers involved

- compiler in `DefaultContextEngine`
- `IContextArtifactRenderer`
- lane and `render_class` assignment

### What to inspect

- selected candidates in order
- each selected artifact’s lane and `render_class`
- compiled `CompletionRequest.messages`
- any prepare-time runtime error about missing renderer or unexpected lane

### How to reason about the evidence

- Collaborators and lanes are not the same thing.
- The compiler groups selected candidates by `render_class`, not by contributor.
- Structured lanes render as `system` messages.
- `recent_turn` renders as replayable completion messages.

### Common root causes

- contributor emitted the wrong lane or `render_class`;
- selected candidate used a renderer that is not registered;
- operator expected one candidate per message when the renderer intentionally
  groups many items into one message;
- wrong behavior is actually in the completion model or RPP stage, not the
  compiler.

### Step-by-step investigation

1. Read selected candidates in bundle order.
2. For each selected candidate, note lane and `render_class`.
3. Compare that order to the actual compiled messages.
4. If compilation failed, identify the missing or mismatched renderer.
5. If compilation succeeded and looks correct, move to completion/RPP debugging.

### Example trace interpretation

```text
selected:
- persona-policy:strict -> render_class=system_persona_policy_items
- bounded-state -> render_class=bounded_control_state_items
- recent-turn:451 -> render_class=recent_turn_messages
- knowledge:9af0 -> render_class=evidence_items
```

Compiled output should therefore include:

- one `system` message for `system_persona_policy`
- one `system` message for `bounded_control_state`
- replay messages from `recent_turn`
- one `system` message for `evidence`
- the current user message last

### Fix paths

- operator/config fixes:
  none, unless a policy or contributor binding is selecting an unexpected
  artifact family
- plugin-author fixes:
  correct lane and `render_class` emission; register the matching renderer
- core-engine fixes:
  only if the compiler misorders or misgroups valid selected artifacts

### Contract vs implementation notes

- contract guarantee: prepare fails closed if no valid renderer exists
- default engine behavior: the current user message is always appended after
  compiled context
- current implementation detail: built-in structured lanes render as one system
  message per `render_class`

## Debugging cache misses and stale cache behavior

### Symptom

Operators expected repeated turns to reuse prior work, but there is no observed
cache benefit or a cache record looks stale.

### Likely layers involved

- `IContextCache`
- cache key construction
- clear-history path

### What to inspect

- `ContextPolicy.cache_enabled`
- cache namespaces: `retrieval`, `prefix_fingerprint`, `working_set`
- tenant-prefixed cache keys
- cache TTL and hit counters
- clear-history activity for the scope

### How to reason about the evidence

- In the current default engine, cache writes are real but cache reads are not
  part of prepare selection.
- A missing cache hit does not explain a wrong selected bundle unless a custom
  contributor or external provider consumes those hints.
- Cache failures during commit appear in `ContextCommitResult.warnings`.

### Common root causes

- expectation mismatch: default engine writes cache hints but does not read them
  during prepare;
- wrong tenant-prefixed key or wrong scope key;
- expired cache row;
- clear-history invalidated all three scope namespaces;
- cache disabled by policy.

### Step-by-step investigation

1. Confirm whether cache is enabled in the resolved policy.
2. Inspect the prepare-phase `retrieval` and `prefix_fingerprint` rows.
3. Inspect the commit-phase `working_set` row.
4. Confirm tenant prefix and `scope_key`.
5. Check whether clear-history ran for the same scope.
6. If the complaint is “same question, same answer, but no reuse,” confirm
   whether any downstream component actually reads the prefix hint.

### Example trace interpretation

```text
working_set:
tenant:11111111-1111-1111-1111-111111111111:working_set:8f...

retrieval:
tenant:11111111-1111-1111-1111-111111111111:retrieval:8f...:1d...

prefix_fingerprint:
tenant:11111111-1111-1111-1111-111111111111:prefix_fingerprint:8f...:4c...
```

If those rows exist but prepare did not reuse them, that is expected in the
current default engine.

### Fix paths

- operator/config fixes:
  correct cache enablement or investigate clear-history/invalidation activity
- plugin-author fixes:
  only if a custom contributor or provider integration is supposed to consume
  cache entries and is not doing so
- core-engine fixes:
  only if cache writes, tenant-safe keying, or invalidation are incorrect

### Contract vs implementation notes

- contract guarantee: cache is non-authoritative
- default engine behavior: cache failures log warnings and do not fail prepare
  or commit
- current implementation detail: the default engine writes cache records but
  does not read them during prepare

## Debugging commit-token and commit persistence failures

### Symptom

Prepare succeeded, but commit failed or later replay behavior is wrong.

### Likely layers involved

- `IContextCommitStore`
- `IContextStateStore`
- `IMemoryWriter`
- `IContextCache`
- `IContextTraceSink`

### What to inspect

- commit ledger row
- `prepared.commit_token`
- `prepared.state_handle`
- prepared fingerprint
- `ContextCommitResult`
- logs from the built-in text handler

### How to reason about the evidence

- Prepare and commit are separate phases.
- A correct completion does not imply a successful commit.
- If commit fails in the built-in text handler, the user may still see the
  response because the failure is logged as a warning.

### Common root causes

- expired token;
- scope mismatch;
- prepared state mismatch;
- prepared fingerprint mismatch;
- commit already in progress;
- previous commit failed;
- state, memory, cache, or trace persistence raised an exception during commit.

### Step-by-step investigation

1. Read the exact commit failure message.
2. Inspect the commit ledger row for the token:
   `scope_key`, `prepared_fingerprint`, `commit_state`, `expires_at`,
   `last_error`, `result_json`.
3. Compare the request scope with the prepared scope.
4. Compare the computed prepared fingerprint with the ledger fingerprint.
5. If token validation passed, inspect state, memory, cache, and trace writes in
   order.
6. If the commit had already succeeded once, check for replay-safe result
   reuse.

### Example trace interpretation

```text
{
  "commit_token": "ctxcmt_abcd",
  "commit_state": "failed",
  "last_error": "expired",
  "scope_key": "8f...",
  "prepared_fingerprint": "4d..."
}
```

If the token is expired, debugging selection or ranking is wasted effort.

### Fix paths

- operator/config fixes:
  reduce end-to-end delay, correct retry behavior, or inspect storage health
- plugin-author fixes:
  preserve the opaque token and prepared request unchanged between prepare and
  commit
- core-engine fixes:
  only if the ledger transitions or replay behavior are incorrect

### Contract vs implementation notes

- contract guarantee: commit tokens are opaque and bound to scope, fingerprint,
  lifecycle state, and expiry
- contract guarantee: successful duplicate delivery may replay the stored result
- current implementation detail: the relational ledger uses `prepared`,
  `committing`, `committed`, and `failed`

## Debugging memory writeback mistakes

### Symptom

A bad preference or fact was persisted, or an expected write never happened.

### Likely layers involved

- `IMemoryWriter`
- commit outcome
- memory recall contributor on later turns

### What to inspect

- `TurnOutcome`
- `ContextCommitResult.memory_writes`
- persisted `ContextMemoryRecord` rows
- current user message and final assistant-visible response
- selected artifacts used as provenance

### How to reason about the evidence

- Memory writeback is commit-phase only.
- Missing writeback on a `completed` turn is a writer or persistence problem.
- Missing writeback on `completion_failed`, `cancelled`, `blocked`, or
  `no_response` is expected in the default writer.

### Common root causes

- operator assumed any acknowledged fact would persist, but the default writer
  only uses simple string heuristics;
- turn outcome was not `completed`;
- fallback-global turn lacked sender or conversation partition;
- write persisted, but later recall missed it because scope partition did not
  match;
- clear-history was used and operators assumed it deleted durable memory; it
  does not.

### Step-by-step investigation

1. Confirm the turn outcome.
2. Inspect `ContextCommitResult.memory_writes`.
3. Inspect persisted memory rows for `commit_token`, `subject`,
   `scope_partition`, and `provenance`.
4. Compare the later recall scope against the memory row partition.
5. If the complaint is “it should not have written this,” inspect the exact user
   text that triggered the heuristic.

### Example trace interpretation

```text
{
  "memory_writes": [
    {
      "write_type": "preference",
      "content": {
        "statement": "I prefer tea and my name is Alex"
      },
      "subject": "user-1"
    },
    {
      "write_type": "fact",
      "content": {
        "statement": "I prefer tea and my name is Alex"
      },
      "subject": "user-1"
    }
  ]
}
```

This is expected in the current default writer because the same sentence
contains both `i prefer ` and `my name is `.

### Fix paths

- operator/config fixes:
  disable or tighten long-term memory usage through policy where appropriate
- plugin-author fixes:
  replace the default heuristic writer for domain-critical memory extraction
- core-engine fixes:
  only if commit ordering or persistence semantics are wrong

### Contract vs implementation notes

- contract guarantee: memory writeback is post-turn and commit-phase
- default engine behavior: memory writer runs after state save
- current implementation detail: `DefaultMemoryWriter` writes one `EPISODE` on
  `completed` turns and adds `PREFERENCE` / `FACT` writes by simple text match

## Debugging trace interpretation mistakes

### Symptom

Operators draw the wrong conclusion from a trace, especially when selected or
dropped items appear to be missing.

### Likely layers involved

- `IContextTraceSink`
- trace policy
- prepare versus commit trace stages

### What to inspect

- `ContextPolicy.trace_enabled`
- `trace_capture_prepare`
- `trace_capture_commit`
- `trace_capture_selected`
- `trace_capture_dropped`
- `ContextTrace` rows for both stages
- `AuditBizTraceEvent` rows when audit bridging is enabled

### How to reason about the evidence

- A missing selected or dropped list does not prove there were no selected or
  dropped items. The trace policy may have suppressed capture.
- `ContextTrace` is the primary source for context-engine selected/dropped item
  detail.
- `AuditBizTraceEvent` is useful for timeline correlation, not for full context
  bundle reconstruction.

### Common root causes

- operator inspected only commit-stage traces and expected prepare-stage
  selected/dropped detail there;
- trace policy disabled selected or dropped capture;
- trace sink failed and only a warning was logged;
- operator used audit timeline events as if they were full context traces.

### Step-by-step investigation

1. Confirm the resolved trace policy in the prepared bundle.
2. Inspect prepare-stage `ContextTrace`.
3. Inspect commit-stage `ContextTrace`.
4. If selected/dropped payloads are absent, confirm capture flags before
   concluding the sink lost data.
5. Use `AuditBizTraceEvent` only to correlate timing, not to replace the
   prepare trace.

### Example trace interpretation

```text
prepare ContextTrace:
{
  "stage": "prepare",
  "payload": {
    "scope": {
      "tenant_id": "11111111-1111-1111-1111-111111111111"
    }
  },
  "selected_items": null,
  "dropped_items": null
}
```

This does not prove prepare selected nothing. It can also mean
`trace_capture_selected=false` and `trace_capture_dropped=false`.

### Fix paths

- operator/config fixes:
  enable selected/dropped trace capture for the affected tenant when needed
- plugin-author fixes:
  if a custom trace sink exists, confirm it preserves policy-controlled capture
  semantics
- core-engine fixes:
  only if trace payload filtering or stage routing is incorrect

### Contract vs implementation notes

- contract guarantee: trace capture is controlled by `ContextPolicy`
- default engine behavior: prepare and commit trace recording are separate
- current implementation detail: `RelationalContextTraceSink` also writes
  `AuditBizTraceEvent` rows when the audit service is present

## Debugging fallback-global behavior and tenant-safety

### Symptom

The bot forgot tenant-specific context or preferences, or an operator suspects
cross-tenant leakage on an unresolved-routing turn.

### Likely layers involved

- scope resolution
- guard
- memory contributor
- policy resolver

### What to inspect

- `ingress_metadata["tenant_resolution"]`
- `ContextScope.tenant_id`
- selected and dropped `memory` artifacts
- provenance tenant on all selected artifacts
- guard drops for tenant mismatch and global memory policy

### How to reason about the evidence

- `fallback_global` is not a soft variant of resolved tenant behavior.
- Under fallback-global routing, recall is intentionally stricter.
- A customer complaint that “the bot forgot my preferences” may be a correct
  isolation outcome, not a memory bug.
- What must never happen: a selected artifact with another tenant’s provenance
  reaches compilation.

### Common root causes

- ingress route failed to resolve tenant, so scope fell back to
  `GLOBAL_TENANT_ID`;
- operator expected tenant-scoped memory during global fallback;
- contributor emitted missing or wrong provenance tenant;
- global unpartitioned memory was correctly blocked;
- contributor recalled no tenant-specific data because the turn was global.

### Step-by-step investigation

1. Confirm `tenant_resolution.mode`.
2. Confirm whether the scope tenant is `GLOBAL_TENANT_ID`.
3. Inspect selected artifacts for provenance tenant.
4. Inspect dropped artifacts for `tenant_id_mismatch` and
   `global_memory_requires_partition`.
5. If the complaint is “forgot my preferences,” inspect whether the turn was
   globally scoped before touching memory persistence.
6. If the complaint is data leakage, stop and inspect selected artifact
   provenance before any model analysis.

### Example trace interpretation

```text
{
  "tenant_resolution": {
    "mode": "fallback_global",
    "reason_code": "missing_binding",
    "source": "ingress_router"
  },
  "dropped": [
    {
      "artifact_id": "memory:991",
      "reason": "dropped_policy",
      "detail": "global_memory_requires_partition"
    }
  ]
}
```

This explains why a user-specific preference was not recalled. It is an
expected safety result, not automatically a bug.

### Fix paths

- operator/config fixes:
  fix tenant routing and bindings so the turn resolves normally
- plugin-author fixes:
  ensure contributors always emit provenance tenant and partition-sensitive
  recall rules
- core-engine fixes:
  only if fallback-global turns are not isolated correctly

### Contract vs implementation notes

- contract guarantee: `ContextScope.tenant_id` is mandatory on every turn
- contract guarantee: explicit negative routing outcomes fail closed; only
  allowed fallback reasons resolve to global fallback
- current implementation detail: the default guard blocks `memory` artifacts on
  global turns with no sender or conversation partition

## Debugging an end-to-end airport-pickup incident

### Symptom

A customer asks to reschedule an airport pickup:

> "Flight LX214 landed late. Move pickup to 01:30 and tell the driver I have two extra bags."

The assistant ignores the active booking and responds as if this were a new
request.

### Likely layers involved

- `IContextStateStore`
- `StateContributor`
- `ChannelOrchestrationContributor`
- `OpsCaseContributor`
- `RecentTurnContributor`
- selection budget
- compiler

### What to inspect

- `ContextScope`
- `bundle.state`
- selected `bounded_control_state`
- selected `operational_overlay`
- selected `recent_turn`
- selected and dropped `evidence`
- commit result from the prior turn
- cache rows only as secondary evidence

### How to reason about the evidence

This incident can come from several different places:

- missing bounded state because the scope changed;
- contributor recall failure because no `case_id` or `trace_id` reached the turn;
- correct artifacts collected but dropped by budget;
- compiler rendered the wrong lane family;
- current response is fine but the prior commit failed, so history/state never
  updated.

### Common root causes

- `conversation_id` changed between turns, creating a new `scope_key`;
- prior commit failed, so `ContextStateSnapshot` stayed stale;
- `OpsCaseContributor` returned nothing because `case_id` was absent;
- `bounded_control_state` existed but only contained the last raw user message,
  not a richer pickup snapshot;
- evidence or overlays were dropped by `max_prefix_tokens` or lane max;
- operator assumed stale cache was reused, but the default engine does not read
  cache during prepare.

### Step-by-step investigation

1. Compare current and prior `ContextScope`.
2. Check whether `conversation_id`, `case_id`, or `workflow_id` changed.
3. Inspect the prior turn’s commit result.
4. If prior commit failed, stop there. That explains missing state/history on
   the current turn.
5. If prior commit succeeded, inspect current `bundle.state`.
6. Inspect the selected `bounded_control_state` artifact.
7. Inspect whether `operational_overlay` includes the linked work item or case.
8. Inspect `recent_turn` to confirm the earlier pickup clarification exists.
9. Inspect dropped items for `lane_max_items`, `max_prefix_tokens`, and
   `dropped_duplicate`.
10. Compare selected candidates with compiled messages.
11. Only if the compiled request looks correct should you blame the model or RPP.

### Example trace interpretation

```text
prepare trace:
{
  "selected": [
    {
      "artifact_id": "persona-policy:vip-tight",
      "lane": "system_persona_policy"
    },
    {
      "artifact_id": "knowledge:airport-transfer",
      "lane": "evidence"
    }
  ],
  "dropped": [
    {
      "artifact_id": "bounded-state",
      "lane": "bounded_control_state",
      "reason": "dropped_budget",
      "detail": "max_prefix_tokens"
    },
    {
      "artifact_id": "case:6a09f01a-9e6a-48b3-9a2e-cbb6c4edbe8e",
      "lane": "operational_overlay",
      "reason": "dropped_budget",
      "detail": "max_prefix_tokens"
    }
  ]
}
```

This is not a contributor failure. State and case overlay were present, then
trimmed by budget.

### Fix paths

- operator/config fixes:
  correct scope partitioning or widen the affected tenant’s budget
- plugin-author fixes:
  reduce token cost of large overlays or populate richer bounded state so it can
  win earlier in selection
- core-engine fixes:
  only if selection or compilation ignored valid lane priority and budget rules

### Contract vs implementation notes

- contract guarantee: prepare is deterministic given the request and registered
  collaborators
- default engine behavior: lane priority puts `bounded_control_state` ahead of
  `evidence`, but hard token ceilings still win
- current implementation detail: cache writes do not short-circuit prepare

## The model was bad vs the context was bad

Use this split before changing collaborators.

The context was bad when:

- the wrong policy/profile resolved;
- the needed lane was absent;
- the wrong candidate was selected;
- the right candidate was dropped;
- the compiled messages omitted required context;
- the turn ran under `fallback_global` when operators assumed tenant resolution.

The model was bad when:

- selected and compiled context looks correct;
- provenance, freshness, state, and recent turns all support the expected answer;
- no RPP or CT extension materially changed the result;
- the completion still ignored or misused the supplied context.

The current turn was fine but future turns will be bad when:

- prepare succeeded and the user-visible response was acceptable;
- commit failed, so state/history/memory/cache/trace writes did not persist;
- the next turn therefore behaves as if the previous turn never happened.

Practical rule:

- inspect the compiled `CompletionRequest.messages` before blaming the model;
- inspect the commit result before blaming memory/state recall on the next turn.

## Plugin-author quick guide

### My contributor is registered but not selected

- Confirm the contributor `name` is allowed by the resolved policy.
- Confirm it emitted any candidates at all.
- Inspect source-policy, guard, dedupe, and budget drops before changing scoring.
- Current implementation detail: contributor execution order is registry
  registration order from `ContextEngineFWExtension`, not ACP binding priority.

### My guard is not dropping what I expected

- Check whether the artifact actually carries the tenant or sensitivity metadata
  the guard needs.
- Remember that source policy runs before guards.
- If the candidate never existed, this is not a guard problem.

### My ranker score changes do not move selection as expected

- Check whether the candidates compete inside the same lane.
- Lane priority still beats score.
- Budget or dedupe may be the real deciding step.

### My memory writer is not persisting writes

- Confirm the outcome is `completed`.
- Confirm the scope is not fallback-global without sender/conversation
  partitioning.
- Confirm persistence succeeded during commit, not just derivation in memory.

### My cache is being bypassed

- Confirm whether you mean cache writes or cache reads.
- The default engine writes cache records but does not read them during prepare.
- If your plugin depends on cache reads, that logic must exist in your
  contributor or adjacent integration.

### My trace sink is missing data

- Check trace policy capture flags first.
- Check whether you are looking at `ContextTrace` or `AuditBizTraceEvent`.
- `AuditBizTraceEvent` is a timeline bridge, not the full selected/dropped item
  store.

## Final checklists

### Cross-tenant leakage incident

- Confirm `tenant_resolution.mode`
- Confirm selected artifact provenance tenant on every selected item
- Inspect dropped `dropped_tenant_mismatch` rows
- Inspect contributors for missing provenance tenant
- Confirm no fallback-global turn selected tenant-scoped memory

### Stale-evidence incident

- Inspect selected `evidence`
- Compare freshness/trust of selected versus dropped evidence
- Inspect `dropped_budget` and `dropped_duplicate`
- Confirm current source bindings and source policy
- Confirm newer evidence was actually retrieved

### Forgotten-state incident

- Compare current and prior `ContextScope`
- Inspect prior commit result
- Inspect current `bundle.state`
- Inspect selected `bounded_control_state`
- Inspect event-log rows and recent-turn selection

### Bad-memory-write incident

- Confirm turn outcome
- Inspect `ContextCommitResult.memory_writes`
- Inspect persisted memory row partition and subject
- Check whether clear-history was used and incorrectly assumed to clear memory
- Check whether default heuristic matching was too broad

### Commit failure incident

- Read exact commit error
- Inspect ledger row state, expiry, fingerprint, and scope key
- Confirm prepared token and state handle were reused unchanged
- Inspect state/memory/cache/trace persistence order
- Confirm whether a prior successful commit was replayed

### Post-control-plane-change regression

- Capture prepared policies for one good and one bad turn
- Compare profile selection inputs
- Compare contributor/source allow and deny rules
- Compare trace policy flags
- Check whether the regression is policy-only before changing contributors

## Final synthesis

### Common anti-patterns

- Blaming the model before inspecting the compiled request
- Using absence from trace as proof a contributor did not run
- Treating audit timeline rows as full context traces
- Treating cache as authoritative state
- Expecting `clear_history` to remove long-term memory
- Expecting rankers to override lane priority
- Expecting fallback-global turns to recall tenant-specific memory safely

### Debugging heuristics

- Scope first, not prompt first
- Policy before contributors
- Source policy before guards
- Guards before ranking
- Ranking before budget
- Prepare before commit for current-turn quality
- Commit before prepare for future-turn forgetting

### If symptom is X, inspect Y first

- Wrong persona or trace behavior -> resolved `ContextPolicy`
- Missing booking/case state -> `ContextScope` then `bundle.state`
- Forgot clarification -> prior commit result then event log
- Stale evidence -> selected and dropped `evidence`
- Cross-tenant concern -> selected provenance tenant and guard drops
- Bad future recall -> commit result and persisted state/memory rows

### When this is a core bug vs a plugin bug vs a config bug

- config bug:
  wrong ACP policy/profile/binding rows, wrong routing metadata, wrong tenant
  resolution, wrong budget, wrong trace capture settings
- plugin bug:
  contributor emitted bad provenance, wrong lane, wrong source identity,
  missing sensitivity, poor scoring metadata, or bad memory-write heuristics
- core bug:
  engine violated documented phase order, lane order, dedupe semantics, token
  validation semantics, or renderer routing semantics

### Final mental model

Most production incidents become tractable once you answer four questions in
order:

1. What exact scope and policy did this turn run under?
2. What exact artifacts were selected and dropped, with provenance and reasons?
3. What exact messages reached the completion gateway?
4. Did commit succeed, and what did it persist for the next turn?

If those four answers are solid, the remaining uncertainty is usually small:
either a collaborator bug, a control-plane/config error, or a model-quality
issue on an otherwise correct bundle.
