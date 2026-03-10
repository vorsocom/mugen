# Context Engine User Stories

Status: Draft
Last Updated: 2026-03-09
Audience: downstream plugin authors, platform/integration teams,
operators/debuggers, core maintainers

## Purpose

This guide explains the context engine through turns that look like real
operating traffic instead of abstract interface notes.

Use `docs/context-engine-design.md` for hard runtime semantics.
Use `docs/context-engine-authoring.md` for collaborator authoring and
registration.
Use this guide when you need to answer questions such as:

- Why did this tenant get that persona?
- Why did one evidence item survive and another get dropped?
- Why is this fact in `bounded_control_state` instead of `evidence` or memory?
- What actually happens between `prepare_turn(...)` and `commit_turn(...)`?
- Where should a downstream plugin implement new behavior?

Story-driven documentation matters here because the context engine has two
separate mental models:

- runtime collaborators decide how context is resolved, loaded, collected,
  filtered, scored, rendered, cached, traced, and persisted;
- compiled lanes are the stable buckets the engine selects and compiles into the
  normalized `CompletionRequest`.

Those are not the same thing.

A contributor can feed an existing lane.
Multiple contributors can feed the same lane.
Guards, rankers, cache, memory writers, commit stores, and trace sinks do not
create lanes at all.

### Runtime collaborators vs compiled lanes

Runtime collaborators in the contract:

- `IContextPolicyResolver`
- `IContextStateStore`
- `IContextContributor`
- `IContextGuard`
- `IContextRanker`
- `IContextArtifactRenderer`
- `IContextCommitStore`
- `IContextCache`
- `IMemoryWriter`
- `IContextTraceSink`

Stable compiled lanes in the contract:

1. `system_persona_policy`
2. `bounded_control_state`
3. `operational_overlay`
4. `recent_turn`
5. `evidence`

The current user message is not a lane.
The default engine appends it after compiled context.

### Prepare phase vs commit phase

Prepare phase is read-heavy and selection-heavy:

1. resolve `ContextPolicy`
2. load `ContextState`
3. collect `ContextCandidate` values from contributors
4. enforce source policy
5. apply guards
6. apply rankers
7. deduplicate
8. select within budget
9. render selected artifacts into `CompletionRequest.messages`
10. issue one opaque commit token
11. emit cache hints and prepare traces

Commit phase is write-heavy and outcome-aware:

1. validate the prepared turn through `IContextCommitStore`
2. persist bounded state
3. persist memory writes
4. update cache entries
5. finalize the commit ledger
6. record commit traces

If an RPP extension changes the final text, or a CT extension fires, that
happens outside the engine but before `commit_turn(...)`.
That is why commit-phase collaborators should reason about the final
user-visible outcome, not just the raw completion payload.

### Read this guide in order

- Start with the story-to-layer matrix.
- Jump to the story for the collaborator you are changing or debugging.
- Use the final synthesis section as a quick design and debugging reference.

### One-line flow

```text
Ingress -> ContextTurnRequest
        -> policy resolver
        -> state store load
        -> contributors
        -> source policy
        -> guards
        -> rankers
        -> dedupe + budget selection
        -> renderers
        -> CompletionRequest

Completion gateway -> RPP -> CT
                   -> commit store validation
                   -> state save + memory write + cache update + trace write
```

## Story-to-layer matrix

| Story title | Main layer/collaborator highlighted | Business problem | Key compiled lanes exercised | Prepare or commit emphasis | Who should read it |
| --- | --- | --- | --- | --- | --- |
| VIP concierge policy without code changes | `IContextPolicyResolver` | Same tenant needs different persona, source policy, and trace behavior by channel/profile | `system_persona_policy`, `recent_turn`, `evidence` | Prepare | platform teams, operators, plugin authors |
| Fragmented airport-pickup reschedule stays coherent | `IContextStateStore` and `bounded_control_state` | The assistant must keep unresolved slots and objective coherent across turns | `system_persona_policy`, `bounded_control_state`, `recent_turn` | Both, with state focus | plugin authors, operators |
| Refund answer comes from approved knowledge | `IContextContributor` | The assistant should answer from governed evidence instead of guessing | `system_persona_policy`, `evidence`, `recent_turn` | Prepare | plugin authors, integration teams |
| Fallback-global turns do not leak tenant data | `IContextGuard` | Anonymous fallback traffic must not see tenant memory or cross-tenant artifacts | `system_persona_policy`, `evidence` | Prepare | operators, security-minded authors |
| Fresh outage notice outranks stale fragments | `IContextRanker` | Evidence order must prefer newer, higher-trust material | `system_persona_policy`, `evidence`, `recent_turn` | Prepare | plugin authors, operators |
| Smallest sufficient working set | compiler / bundle assembly in `DefaultContextEngine` | A turn needs persona, state, overlays, recent turns, and evidence without overfilling budget | all five lanes | Prepare | core maintainers, advanced authors |
| Repeat branch-hours queries stay tenant-safe | `IContextCache` | Repeated turns need reusable retrieval/prefix hints without becoming authoritative state | `system_persona_policy`, `evidence` | Both | platform teams, operators |
| Durable seating preference only after confirmation | `IMemoryWriter` | Preferences belong in long-term memory only after the final outcome is known | `system_persona_policy`, `evidence`, `recent_turn` | Commit | plugin authors, operators |
| Reconstructing why a waiver was declined | `IContextTraceSink` | Operators need selected and dropped artifact reasoning after the fact | depends on turn; example uses `system_persona_policy`, `operational_overlay`, `evidence`, `recent_turn` | Both, with trace focus | operators, maintainers |
| End-to-end delayed-arrival replan | end-to-end engine orchestration | One turn exercises scope, policy, state, overlays, evidence, ranking, commit, and trace together | all five lanes | Both | everyone |
| ACP control plane changes runtime behavior | ACP-backed resolver inputs to `DefaultContextPolicyResolver` | Runtime behavior should change by data, not code deploys | usually `system_persona_policy`, then whichever lanes bindings enable | Prepare | platform teams, maintainers |

## Story 1 — VIP concierge policy without code changes

### Why this story exists

A large share of context-engine debugging is really policy-resolution debugging.
The turn "looks wrong" because the wrong profile, policy, binding, or trace
policy was selected before any contributor ran.

### Real-world scenario

Tenant `Asteria Travel` serves:

- browser chat for standard concierge requests;
- a tenant workflow split between `valet.customer_inbox` and `valet.core`;
- a downstream VIP messaging bridge that stamps
  `service_route_key="valet.customer_inbox"` and
  `client_profile_key="vip-sms"` into ingress metadata.

A guest on the VIP bridge expects a tighter persona, narrower evidence set, and
stronger trace capture than a casual browser user.

### Problem to solve

The same core messaging path must behave differently for the same tenant based
on scope and ingress metadata, without branching provider code or hard-coding
prompt text in the message handler.

### Why this layer is the right tool

`IContextPolicyResolver` is the correct place because the runtime needs one
effective `ContextPolicy` before any state load, candidate collection, source
enforcement, guard pass, or budgeting can happen.

Why not:

- not a contributor: contributors should consume policy, not decide it;
- not a guard: guards veto candidates after collection and cannot choose
  persona, budget, or trace policy.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "platform": "web",
  "channel_id": "vip-concierge",
  "sender_id": "guest-8841",
  "conversation_id": "conv-775"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "crm_binding"
  },
  "ingress_route": {
    "service_route_key": "valet.customer_inbox",
    "client_profile_key": "vip-sms"
  },
  "locale": "en-US",
  "category": "travel-policy"
}

user_message = "Can you move tonight's airport pickup and confirm lounge access?"

relevant prior state = none
linked business objects = none
```

### Prepare-phase walkthrough

1. `prepare_turn(...)` calls `IContextPolicyResolver.resolve_policy(request)`
   first.
2. In the current core plugin, `DefaultContextPolicyResolver` lists active
   `ContextProfiles`, active `ContextPolicies`, active
   `ContextContributorBindings`, active `ContextSourceBindings`, and active
   `ContextTracePolicies` for the tenant.
3. The resolver selects the most specific `ContextProfile` match by `platform`,
   `channel_key`, optional `service_route_key`, and optional
   `client_profile_key`.
4. It selects the linked `ContextPolicy` if the profile references one;
   otherwise it falls back to the tenant default or the built-in default
   policy.
5. It merges contributor allow rules, source allow rules, and trace capture
   flags into one effective `ContextPolicy`.
6. The state store loads `ContextState`. In this example there is no existing
   bounded snapshot.
7. Contributors run against the resolved policy. `PersonaPolicyContributor`
   emits one `system_persona_policy` artifact. `RecentTurnContributor` may emit
   zero items. `KnowledgePackContributor` emits `evidence` candidates from
   tenant-scoped published revisions.
8. Source policy runs before guards. Evidence whose `ContextSourceRef` does not
   match the resolved allow rules is dropped with `DROPPED_SOURCE_POLICY`.
9. Guards and rankers run next. The resolved VIP budget then limits evidence
   count and total prefix size.
10. The compiler renders selected artifacts by `render_class` and appends the
    current user message last.

Rough compiled shape:

```text
CompletionRequest = {
  "messages": [
    {
      "role": "system",
      "content": {
        "context_lane": "system_persona_policy",
        "render_class": "system_persona_policy_items",
        "items": [
          {
            "kind": "persona_policy",
            "content": {
              "persona": "White-glove travel desk",
              "policy_key": "vip-tight"
            }
          }
        ]
      }
    },
    {
      "role": "system",
      "content": {
        "context_lane": "evidence",
        "render_class": "evidence_items",
        "items": [
          {
            "kind": "knowledge_span",
            "content": {
              "excerpt": "...approved lounge access rule..."
            }
          }
        ]
      }
    },
    {
      "role": "user",
      "content": "Can you move tonight's airport pickup and confirm lounge access?"
    }
  ],
  "vendor_params": {
    "context_cache_hints": {
      "prefix_fingerprint": "<fingerprint>"
    },
    "context_policy": {
      "profile_name": "vip-sms",
      "persona": "White-glove travel desk",
      "trace_policy_name": "vip-trace"
    }
  }
}
```

### Compiled lanes used

- `system_persona_policy`: carries the resolved persona, selected policy key,
  and policy-facing budget/redaction context.
- `recent_turn`: only used if there is recent history for this scoped
  conversation.
- `evidence`: carries approved knowledge excerpts allowed by tenant source
  policy.

### Assistant outcome

The model sees the VIP persona first, then the approved lounge and pickup
evidence, then the guest message.
The user gets a channel-appropriate answer without any downstream platform code
deciding the persona or evidence set directly.

### Commit-phase walkthrough

1. `commit_turn(...)` validates the opaque commit token against tenant scope,
   scope key, prepared fingerprint, lifecycle state, and expiry.
2. The state store persists the next bounded snapshot revision for this scope
   and appends user and assistant events to history.
3. No special durable memory write is required in this example.
4. If cache is enabled, the engine updates the `working_set` namespace for this
   scope.
5. If trace capture is enabled, the trace sink records a commit-stage trace.
6. The engine intentionally does not persist raw retrieval payloads into
   `ContextState`.

### Operator/debugger view

An operator should inspect:

- resolved `profile_name`, `policy_key`, and `trace_policy_name`;
- selected and dropped evidence items in prepare trace;
- dropped source-policy items whose `ContextSourceRef` did not match the VIP
  allow rules;
- `tenant_resolution` carried into persona content and state routing metadata.
- `service_route_key` carried into policy metadata and bounded-state routing.

### Plugin-author takeaway

If a tenant needs different persona, source policy, retention, or trace
behavior by channel, service route, or client profile, put that in the policy
resolver inputs. Do not hide it inside contributors or message handlers.

### Contract vs current implementation notes

- Contract guarantee: one effective `ContextPolicy` is resolved before state
  load and candidate collection.
- Contract guarantee: source policy is engine-enforced, not advisory.
- Default engine behavior: prepare starts with policy resolution, then state
  load, then contributors.
- Current core plugin implementation: `DefaultContextPolicyResolver` reads
  `ContextProfiles`, `ContextPolicies`, `ContextContributorBindings`,
  `ContextSourceBindings`, and `ContextTracePolicies`.
- Illustrative example: `vip-sms`, `vip-tight`, and the persona text are
  scenario values, not fixed core defaults.

## Story 2 — Fragmented airport-pickup reschedule stays coherent

### Why this story exists

Authors often confuse bounded control state with transcript replay.
They solve a slot-tracking problem with `recent_turn` when the real requirement
is compact operational state.

### Real-world scenario

Tenant `Meridian Chauffeur` handles airport pickups over messaging.
A traveler sends three fragmented turns across a moving car connection:

1. "Need to move my pickup."
2. "Actually make it 05:30."
3. "Terminal 5, not Terminal 3."

The assistant should keep the pickup objective and unresolved slots coherent
without replaying an unlimited transcript.

### Problem to solve

The runtime needs one compact, scope-partitioned state object that survives
turns and can be compiled cheaply into the next prompt.

### Why this layer is the right tool

`IContextStateStore` plus the `bounded_control_state` lane is the right place
because the data is operational conversation state: current objective, entities,
unresolved slots, commitments, and routing.

Why not:

- not `recent_turn`: history is replay material, not compact control state;
- not long-term memory: pickup-slot progress is per-conversation working state,
  not durable preference memory.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "22222222-2222-2222-2222-222222222222",
  "platform": "telegram",
  "channel_id": "airport-desk",
  "sender_id": "guest-5510",
  "conversation_id": "pickup-118"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "transport_binding"
  }
}

user_message = "Terminal 5, not Terminal 3."

relevant prior state = {
  "current_objective": "Reschedule airport pickup",
  "entities": {
    "pickup_reference": "PU-4491",
    "pickup_time": "05:30"
  },
  "unresolved_slots": [
    "terminal"
  ],
  "summary": "Pickup reschedule in progress for PU-4491."
}
```

### Prepare-phase walkthrough

1. Policy resolution selects the standard airport-desk profile and budget.
2. The state store loads the bounded snapshot by tenant-scoped `scope_key`.
3. `StateContributor` emits one `bounded_control_state` artifact from that
   snapshot.
4. `RecentTurnContributor` emits a small replay window from the event log so
   the model still sees the last few utterances.
5. Guards and source policy have little to do here because the main signal is
   internal state plus recent history.
6. Ranking keeps the state artifact high-priority inside
   `bounded_control_state`.
7. Selection enforces the default `max_items=1` behavior for
   `bounded_control_state`, so the turn gets one compact state view, not
   multiple competing snapshots.
8. The compiler renders bounded state as one structured `system` message and
   recent turns as replay messages, then appends the new user message.

Rough compiled shape:

```text
CompletionRequest.messages ~= [
  {
    "role": "system",
    "content": {
      "context_lane": "bounded_control_state",
      "items": [
        {
          "kind": "state_snapshot",
          "content": {
            "current_objective": "Reschedule airport pickup",
            "entities": {
              "pickup_reference": "PU-4491",
              "pickup_time": "05:30"
            },
            "unresolved_slots": ["terminal"]
          }
        }
      ]
    }
  },
  {"role": "user", "content": "Need to move my pickup."},
  {"role": "assistant", "content": "Sure. What time should I use?"},
  {"role": "user", "content": "Terminal 5, not Terminal 3."}
]
```

### Compiled lanes used

- `system_persona_policy`: keeps the assistant in the dispatch-concierge role.
- `bounded_control_state`: carries the compact pickup-progress snapshot.
- `recent_turn`: replays the last few turn events needed for local continuity.

### Assistant outcome

The model can answer "Understood. I now have pickup `PU-4491`, time `05:30`,
terminal `5`" instead of asking for the pickup time again.

### Commit-phase walkthrough

1. The commit store validates the prepared token.
2. The state store persists the next revision for the same scope and appends the
   user and assistant events to `ContextEventLog`.
3. In the current core plugin implementation,
   `RelationalContextStateStore.save(...)` updates `current_objective`, routing
   metadata, revision, and event history, and preserves existing state fields
   unless another collaborator or service changes them.
4. Cache and trace updates happen normally if enabled.
5. The engine intentionally does not copy the full transcript into
   `ContextState`.

### Operator/debugger view

If the assistant re-asks for already-known pickup details, inspect:

- the loaded `ContextState.revision`;
- whether the expected `scope_key` resolved to the right conversation;
- the rendered `bounded_control_state` lane in prepare trace;
- the event log rows for missing or out-of-order recent turns.

### Plugin-author takeaway

Use bounded state for compact operational facts that must survive turns.
Use recent-turn history for replay.
Do not expect the core state store to perform domain-specific slot extraction
unless you implement that logic in a collaborator or adjacent business service.

### Contract vs current implementation notes

- Contract guarantee: bounded state and recent-turn history are distinct stores
  with different purposes.
- Contract guarantee: `bounded_control_state` is a stable lane bucket.
- Default engine behavior: the engine loads state before contributors run and
  compiles at most one bounded-state item unless policy changes that lane
  budget.
- Current core plugin implementation: `RelationalContextStateStore` persists
  revisioned snapshots and appends event-log rows, but it does not ship a
  domain-specific slot-filling algorithm.
- Illustrative example: the pickup fields are example state content for a
  downstream concierge workflow.

## Story 3 — Refund answer comes from approved knowledge

### Why this story exists

The contributor seam is where retrieval belongs.
Without that seam, teams either guess in the model prompt or smuggle retrieval
into unrelated layers.

### Real-world scenario

Tenant `Northlight Journeys` runs a concierge assistant for booking support.
A guest asks whether a partially used package can still receive a refund.

The tenant publishes governed refund guidance in `knowledge_pack`.
The assistant should answer from that governed evidence, not from general model
priors.

### Problem to solve

The runtime needs tenant-scoped, channel-aware, locale-aware evidence candidates
before the model is called.

### Why this layer is the right tool

`IContextContributor` is the right tool because retrieval is prepare-phase input
assembly.
The contributor can fetch or synthesize `ContextCandidate` values with
provenance and realistic token estimates.

Why not:

- not a guard: a guard can drop evidence but should not fetch it;
- not a memory writer: writeback happens after the turn and cannot supply
  evidence for the current answer.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "33333333-3333-3333-3333-333333333333",
  "platform": "web",
  "channel_id": "refund-desk",
  "sender_id": "guest-9021",
  "conversation_id": "refund-77"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "booking_binding"
  },
  "locale": "en-US",
  "category": "refunds"
}

user_message = "Can I get a refund if one leg of the package was already used?"

relevant prior state = none
linked business objects = booking exists outside the engine; only refund policy
text is pulled into context
```

### Prepare-phase walkthrough

1. Policy resolution enables the `knowledge_pack` contributor and allows
   approved refund sources for this channel.
2. The state store returns no bounded state for this example.
3. `KnowledgePackContributor.collect(...)` lists published revisions for the
   tenant, channel, locale, and category.
4. For each revision, it emits an `evidence` candidate with:
   - `kind="knowledge_span"`
   - `render_class="evidence_items"`
   - `ContextSourceRef.kind="knowledge_pack_revision"`
   - locale and category on the source ref
   - governed provenance and estimated token cost
5. Source policy runs before guards. If the tenant only allows refund-category
   revisions, non-matching evidence is dropped before the model sees it.
6. The guard pass checks tenant and sensitivity labels.
7. The ranker scores the surviving evidence, then selection keeps only the top
   evidence items allowed by budget.
8. The compiler renders the evidence lane into one structured `system` message
   and appends the user message last.

Rough evidence payload:

```text
{
  "context_lane": "evidence",
  "render_class": "evidence_items",
  "items": [
    {
      "artifact_id": "knowledge:9af...",
      "kind": "knowledge_span",
      "summary": "Partially used concierge package refunds are limited to...",
      "content": {
        "excerpt": "Partially used concierge package refunds are limited to...",
        "channel": "refund-desk",
        "locale": "en-US",
        "category": "refunds",
        "published_at": "2026-02-18T09:30:00+00:00"
      },
      "provenance": {
        "contributor": "knowledge_pack",
        "source_kind": "knowledge_pack_revision"
      }
    }
  ]
}
```

### Compiled lanes used

- `system_persona_policy`: defines refund-desk behavior and budget.
- `recent_turn`: may replay the immediately preceding clarification exchange.
- `evidence`: carries the governed refund guidance.

### Assistant outcome

The assistant answers from approved refund guidance and can cite the correct
policy direction instead of improvising a refund rule.

### Commit-phase walkthrough

1. The commit token is validated.
2. The state store appends user and assistant events for later replay.
3. No evidence is written back into bounded state.
4. Cache and trace updates occur if enabled.
5. The engine intentionally does not turn raw knowledge-pack excerpts into
   durable memory automatically.

### Operator/debugger view

If the answer looks like a guess, inspect:

- whether `knowledge_pack` was allowed by contributor bindings or policy;
- whether the `ContextSourceRef` on candidates matched the resolved allow rules;
- whether evidence was dropped by source policy, guard, or budget;
- the final `evidence_items` rendered into the compiled request.

### Plugin-author takeaway

Fetch tenant-scoped evidence in a contributor.
Emit explicit provenance and `ContextSourceRef`.
Let the engine enforce source policy and budget after retrieval.

### Contract vs current implementation notes

- Contract guarantee: contributors emit `ContextCandidate` values with
  provenance and token metadata.
- Contract guarantee: source policy evaluates against `ContextSourceRef`, not
  collaborator-specific ad hoc metadata.
- Default engine behavior: contributors run before guards, rankers, dedupe, and
  selection.
- Current core plugin implementation: `KnowledgePackContributor` retrieves
  published revisions and emits `knowledge_span` artifacts in the `evidence`
  lane.
- Illustrative example: refund-category revisions are example tenant data, not
  built-in framework content.

## Story 4 — Fallback-global turns do not leak tenant data

### Why this story exists

Global fallback is necessary in some ingress paths, but it is also one of the
easiest places to accidentally leak tenant or user data if guard behavior is
unclear.

### Real-world scenario

A hotel concierge widget is reachable before the platform can positively resolve
a tenant.
A guest opens the widget anonymously and asks a pre-sales question.

The turn falls back to `GLOBAL_TENANT_ID`.
The assistant may answer from public knowledge, but it must not recall
tenant-specific loyalty data or any other tenant's booking context.

### Problem to solve

The runtime must fail closed on unsafe candidates while still allowing safe
public context.

### Why this layer is the right tool

`IContextGuard` is the right tool because the issue is a hard veto boundary:
cross-tenant artifacts, blocked sensitivity, and unsafe global memory should be
removed before ranking and compilation.

Why not:

- not the contributor layer alone: contributors may not see all unsafe
  conditions or all candidate sources;
- not the policy resolver alone: the resolver defines policy, but the engine
  still needs a hard runtime enforcement pass over concrete candidates.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "00000000-0000-0000-0000-000000000000",
  "platform": "web",
  "channel_id": "anonymous-entry",
  "sender_id": null,
  "conversation_id": null
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "fallback_global",
    "reason_code": "missing_binding",
    "source": "ingress_router"
  }
}

user_message = "What is your cancellation policy before I book?"

relevant prior state = none
linked business objects = none
```

### Prepare-phase walkthrough

1. Policy resolution returns the fallback-global policy for `GLOBAL_TENANT_ID`.
2. The state store loads only the snapshot for this exact global scope. There is
   no tenant-shared conversation state.
3. Contributors may emit:
   - public `knowledge_pack` evidence;
   - memory candidates if long-term memory exists for the global tenant;
   - persona policy.
4. Source policy keeps only allowed public source families.
5. `DefaultContextGuard` applies three important checks:
   - drop any candidate whose provenance `tenant_id` does not equal the request
     scope tenant;
   - drop candidates whose sensitivity intersects blocked labels;
   - under `GLOBAL_TENANT_ID`, drop `memory` candidates when the scope has no
     `sender_id` or `conversation_id`.
6. Rankers and budget selection continue with the remaining safe candidates
   only.
7. The compiler emits a request that contains public policy and public evidence,
   then the user message.

### Compiled lanes used

- `system_persona_policy`: tells the model this is a public, fallback-global
  turn.
- `evidence`: contains only safe public guidance that survived source policy and
  guard checks.

### Assistant outcome

The assistant can answer a public cancellation-policy question without leaking
loyalty history, booking details, or another tenant's evidence.

### Commit-phase walkthrough

1. The commit token is validated against the fallback-global scope.
2. The state store appends event-log rows scoped to this fallback-global
   conversation only.
3. `DefaultMemoryWriter` writes nothing because the turn is global and has no
   sender or conversation partition.
4. Cache and trace updates remain tenant-prefixed to `GLOBAL_TENANT_ID`.
5. Nothing is persisted that would create implicit tenant-wide shared memory
   recall.

### Operator/debugger view

If an anonymous turn appears to know too much, inspect:

- `tenant_resolution.mode` and `reason_code`;
- dropped guard reasons such as `tenant_id_mismatch` and
  `global_memory_requires_partition`;
- whether any contributor emitted candidates with the wrong provenance tenant;
- whether traces show a global scope with unexpected selected memory artifacts.

### Plugin-author takeaway

Use guards for hard runtime safety boundaries.
If the failure mode is "this candidate must never reach compilation," it
belongs in a guard.

### Contract vs current implementation notes

- Contract guarantee: `ContextScope.tenant_id` is always populated, even under
  fallback-global behavior.
- Contract guarantee: blocked artifacts do not reach completion compilation.
- Default engine behavior: source policy runs before guards; guards run before
  ranking and selection.
- Current core plugin implementation: `DefaultContextGuard` enforces provenance
  tenant match, blocked sensitivity labels, and partition-required global memory
  behavior.
- Illustrative example: the anonymous booking widget is one fallback-global
  scenario, not the only one.

## Story 5 — Fresh outage notice outranks stale fragments

### Why this story exists

Ranking is often misunderstood as "prompt formatting."
It is not.
Ranking decides candidate order before budget selection.

### Real-world scenario

A resort operations desk has three evidence candidates for the same guest
question:

- a newly approved airport-transfer outage notice;
- an older FAQ fragment about normal pickup timing;
- a stale baggage-policy excerpt.

All three are valid evidence.
Only the most relevant, highest-value items should survive the evidence budget.

### Problem to solve

The engine must prefer fresher, higher-trust evidence within the already-
collected candidate set.

### Why this layer is the right tool

`IContextRanker` is the right tool because the engine already has candidates.
The problem is now ordering, not retrieval and not formatting.

Why not:

- not the contributor: the contributor should surface the evidence set, not
  decide final evidence order across the whole turn;
- not the compiler: the compiler should render the selected set, not score it.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "44444444-4444-4444-4444-444444444444",
  "platform": "matrix",
  "channel_id": "ops-concierge",
  "sender_id": "guest-4401",
  "conversation_id": "case-ops-91"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "ops_binding"
  },
  "locale": "en-US",
  "category": "transfer-ops"
}

user_message = "Is the airport pickup running tonight or should I expect a delay?"

relevant prior state = none
linked business objects = none
```

### Prepare-phase walkthrough

1. Policy resolution enables the standard evidence contributors for this tenant
   and category.
2. The state store returns no bounded snapshot for this example.
3. Contributors emit three `evidence` candidates.
4. Source policy allows all three because they come from approved
   `knowledge_pack_revision` sources.
5. Guards pass them because they are tenant-safe and not blocked by sensitivity
   policy.
6. The ranker computes ordering inside the collected set.
   Example default-ranker inputs:
   - outage notice: high trust, freshness `1.0`, normal token cost;
   - old FAQ: similar trust, lower freshness;
   - stale baggage excerpt: lower freshness and weaker category fit.
7. Selection then applies evidence budget after ranking.
   If `max_evidence_items=1`, only the top evidence item survives.
8. The compiler renders the top evidence into the final `evidence` system
   message.

Selected vs dropped example:

```text
selected:
- evidence/outage-notice-2026-03-09

dropped:
- evidence/faq-airport-pickup-normal-hours -> dropped_budget lane_max_items:evidence
- evidence/baggage-policy-2025-11-01 -> dropped_budget lane_max_items:evidence
```

### Compiled lanes used

- `system_persona_policy`: frames the response as an operations update.
- `recent_turn`: may carry the immediately previous clarification exchange.
- `evidence`: contains the ranked outage notice and any other evidence budget
  allows.

### Assistant outcome

The user sees the approved outage notice first.
The answer leads with the current exception instead of the stale steady-state
FAQ.

### Commit-phase walkthrough

1. The commit store validates the prepared turn.
2. State and event-log writes happen normally.
3. No ranking data is persisted as authoritative business state.
4. Trace, if enabled, records which evidence ranked high enough to survive and
   which was dropped by budget.
5. Cache updates are independent of rank score semantics.

### Operator/debugger view

If stale evidence wins, inspect:

- candidate freshness and trust values in prepare trace;
- whether ranking happened inside one lane or whether a lane-priority issue is
  actually the real cause;
- whether evidence was dropped by ranking order plus budget, not by source
  policy;
- whether `max_evidence_items` is tighter than expected.

### Plugin-author takeaway

Use a ranker to order candidates that already exist.
Do not use a ranker to own retrieval or to bypass lane budgets.

### Contract vs current implementation notes

- Contract guarantee: rankers score already-collected candidates and selection
  still happens later.
- Default engine behavior: selection sorts by lane priority first, then score,
  then candidate priority.
- Current core plugin implementation: `DefaultContextRanker` weights lane
  bonus, trust, freshness, candidate priority, and token cost.
- Illustrative example: the outage, FAQ, and baggage excerpts are sample
  evidence candidates inside the same `evidence` lane.

## Story 6 — Smallest sufficient working set

### Why this story exists

The context engine is not just a retrieval fan-in.
Its main value is choosing the smallest sufficient working set from several
different context families.

### Real-world scenario

A guest disputes a late-arrival fee.
The assistant needs:

- the resolved persona and policy;
- the current bounded state;
- the linked ops case summary;
- the last few turns;
- one or two evidence items about fee-waiver policy.

It does not need every case event, every audit event, and every historical
transcript line.

### Problem to solve

The runtime must assemble a multi-lane context bundle that is sufficient,
explainable, and budget-compliant.

### Why this layer is the right tool

Compiler and bundle assembly in `DefaultContextEngine` is the correct place
because only the engine sees:

- all lanes together;
- source-policy and guard outcomes;
- dedupe state;
- lane budgets;
- final render order.

Why not:

- not a contributor: contributors should not guess final prompt shape across
  other contributors;
- not a renderer: renderers format selected artifacts but do not select them.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "55555555-5555-5555-5555-555555555555",
  "platform": "web",
  "channel_id": "waiver-desk",
  "sender_id": "guest-2003",
  "conversation_id": "waiver-41",
  "case_id": "b7f7d0d0-66ef-4a66-9a93-18e4b0ce42af"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "case_binding"
  }
}

budget_hints = {
  "max_total_tokens": 1200,
  "max_prefix_tokens": 900,
  "max_evidence_items": 2
}

user_message = "The flight landed at 01:05. Can you waive the late-arrival fee?"

relevant prior state = {
  "current_objective": "Assess waiver request",
  "summary": "Guest disputes fee after delayed arrival."
}

linked business objects = {
  "ops_case": "CASE-2048"
}
```

### Prepare-phase walkthrough

1. Policy resolution selects the waiver-desk policy.
2. The engine tightens that policy with `budget_hints`; it never widens policy
   ceilings.
3. The state store loads the current bounded snapshot.
4. Contributors emit:
   - `system_persona_policy` from `PersonaPolicyContributor`;
   - `bounded_control_state` from `StateContributor`;
   - `operational_overlay` from `OpsCaseContributor`;
   - `recent_turn` replay from `RecentTurnContributor`;
   - `evidence` from `KnowledgePackContributor`.
5. Source policy removes any evidence source that is not approved for the
   waiver-desk profile.
6. Guards drop unsafe candidates.
7. Rankers score surviving candidates.
8. Dedupe removes duplicates by lane, render class, and canonical source
   identity.
9. Selection fills lane minima first, then spillover, until hard ceilings are
   reached.
10. The engine builds `ContextBundle` with selected candidates, dropped
    candidates, cache hints, and trace payload.
11. The compiler groups selected candidates by `render_class` and renders them
    in selected order.

Selected vs dropped example:

```text
ContextBundle = {
  "selected_candidates": [
    "persona-policy:waiver-tight",
    "bounded-state",
    "case:b7f7d0d0-66ef-4a66-9a93-18e4b0ce42af",
    "recent-turn:451",
    "recent-turn:452",
    "knowledge:fee-waiver-policy-v7",
    "knowledge:late-arrival-exception-v3"
  ],
  "dropped_candidates": [
    {
      "artifact_id": "knowledge:general-fee-policy-v2",
      "reason": "dropped_budget",
      "detail": "lane_max_items:evidence"
    },
    {
      "artifact_id": "knowledge:fee-waiver-policy-v6",
      "reason": "dropped_duplicate",
      "detail": "duplicate_source_artifact"
    }
  ]
}
```

Rough compiled message order:

```text
[
  {"role": "system", "content": {"context_lane": "system_persona_policy"}},
  {"role": "system", "content": {"context_lane": "bounded_control_state"}},
  {"role": "system", "content": {"context_lane": "operational_overlay"}},
  {"role": "user", "content": "...previous guest turn..."},
  {"role": "assistant", "content": "...previous assistant turn..."},
  {"role": "system", "content": {"context_lane": "evidence"}},
  {"role": "user", "content": "The flight landed at 01:05. Can you waive the late-arrival fee?"}
]
```

### Compiled lanes used

- `system_persona_policy`: persona plus resolved policy framing.
- `bounded_control_state`: current waiver objective and compact state.
- `operational_overlay`: linked case status and recent case events.
- `recent_turn`: local replay window.
- `evidence`: waiver-policy excerpts that survived source policy, dedupe,
  ranking, and budget.

### Assistant outcome

The model gets a compact, lane-structured working set instead of a transcript
dump.
The answer can reason about the current case, recent dialogue, and approved
waiver policy without exceeding budget.

### Commit-phase walkthrough

1. The commit token is validated.
2. The state store writes the next revision and appends user and assistant turn
   events.
3. Memory writeback happens only if a memory writer derives durable writes from
   the final outcome.
4. Cache updates record the current working-set fingerprint.
5. Trace sinks record the selected and dropped artifact reasoning if trace
   capture is enabled.
6. The engine intentionally does not persist compiler formatting as
   authoritative state.

### Operator/debugger view

When a turn feels "too long" or "missing something," inspect:

- `budget_hints` versus resolved budget;
- selected versus dropped items and their reason details;
- dedupe winners and losers;
- render order by `render_class`;
- whether the missing artifact was never collected, got blocked, or lost in
  selection.

### Plugin-author takeaway

Selection and compilation are engine concerns.
Contributors should emit good candidates.
Renderers should format selected candidates.
Neither should try to replace the bundle-assembly step.

### Contract vs current implementation notes

- Contract guarantee: lane buckets are selection and budgeting primitives, not
  presentation APIs.
- Contract guarantee: artifacts route through renderers by `render_class`.
- Default engine behavior: dedupe runs after ranking and before budget
  selection; the current user message is always appended last.
- Current core plugin implementation: built-in structured lanes render as one
  `system` message per lane bucket, while `recent_turn` replays as normal
  completion messages.
- Illustrative example: the selected and dropped artifact IDs are
  representative, not fixed framework outputs.

## Story 7 — Repeat branch-hours queries stay tenant-safe

### Why this story exists

Cache behavior is easy to overstate.
The engine has a cache seam, but cache entries are hints and working-set
records, not authoritative state.

### Real-world scenario

A concierge tenant gets repeated questions about branch or amenity hours from
the same scoped conversation.
Teams want repeatable prefix and retrieval hints without risking cross-tenant
bleed or using cache as a source of truth.

### Problem to solve

The runtime needs tenant-safe cache keys and provider-neutral cache hints while
keeping correctness independent of cache availability.

### Why this layer is the right tool

`IContextCache` is the right layer because cache is an optional optimization and
working-set hint store.

Why not:

- not the state store: state is authoritative per-conversation control state;
- not a contributor: contributors may use cache internally, but the shared
  runtime cache contract should stay tenant-safe and non-authoritative.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "66666666-6666-6666-6666-666666666666",
  "platform": "web",
  "channel_id": "hours-desk",
  "sender_id": "guest-117",
  "conversation_id": "hours-12"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "hotel_binding"
  },
  "locale": "en-US",
  "category": "hours"
}

user_message = "What time does the spa close tonight?"

relevant prior state = none
linked business objects = none
```

### Prepare-phase walkthrough

1. Policy resolution keeps `cache_enabled=True`.
2. Contributors assemble the normal working set, typically persona plus one or
   more evidence items.
3. Selection and compilation run normally.
4. The compiler places `context_cache_hints.prefix_fingerprint` in
   `CompletionRequest.vendor_params`.
5. After compilation, the engine writes two cache namespaces if a cache is
   registered:
   - `retrieval`
   - `prefix_fingerprint`
6. The keys are tenant-prefixed and scope-partitioned.

Current helper shapes:

```text
tenant:<tenant_id>:retrieval:<scope_key>:<request_hash>
tenant:<tenant_id>:prefix_fingerprint:<scope_key>:<prefix_fingerprint>
```

7. A later identical or near-identical turn in the same scope can produce the
   same prefix fingerprint when the selected prefix is unchanged.
8. The cache write is best-effort; failure logs a warning and does not change
   selection correctness.

### Compiled lanes used

- `system_persona_policy`: stable persona and policy framing.
- `evidence`: branch-hours or amenity-hours guidance.

### Assistant outcome

The user gets the same answer quality whether cache succeeds or fails.
When downstream infrastructure honors prefix hints, repeated turns can benefit
from stable prompt-prefix reuse without changing engine correctness.

### Commit-phase walkthrough

1. The commit token is validated.
2. State is saved and event history is appended normally.
3. If cache is enabled, the engine writes the `working_set` namespace for this
   scope.
4. The current helper shape is:

```text
tenant:<tenant_id>:working_set:<scope_key>
```

5. If operators clear history for the scope, the current `clear_history` path
   invalidates `working_set`, `retrieval`, and `prefix_fingerprint` namespaces
   for that scope prefix.
6. The engine intentionally does not treat cache entries as commit authority.

### Operator/debugger view

Inspect:

- whether cache keys are tenant-prefixed;
- whether repeated turns in the same scope produce the same
  `prefix_fingerprint`;
- whether cache failures only produced warnings instead of behavior changes;
- whether a clear-history operation invalidated all three namespaces for the
  scope.

### Plugin-author takeaway

Treat cache as an optimization seam.
Keep keys tenant-safe.
Do not make cache correctness a prerequisite for safe context behavior.

### Contract vs current implementation notes

- Contract guarantee: trace and cache are non-authoritative collaborators.
- Contract guarantee: cache keys remain tenant-safe.
- Default engine behavior: cache failures are warnings, not selection or commit
  authority.
- Current core plugin implementation: the default engine writes `retrieval`,
  `prefix_fingerprint`, and `working_set` entries, but it does not currently
  read those entries during prepare to short-circuit collection.
- Illustrative example: the hours query is a repeatable caching scenario, not a
  special core feature.

## Story 8 — Durable seating preference only after confirmation

### Why this story exists

Memory writeback is the most common place to accidentally persist too much, too
early, or in the wrong partition.

### Real-world scenario

A guest tells a travel concierge:
"I prefer aisle seats on overnight trips."

The assistant confirms the preference.
Only after that final user-visible outcome should the runtime write durable
memory.

### Problem to solve

The runtime needs outcome-aware long-term writeback that is replay-safe and
scope-partitioned.

### Why this layer is the right tool

`IMemoryWriter` is the right tool because memory is a commit-phase concern.
It should depend on the final assistant-visible result and a validated commit
token.

Why not:

- not a contributor: contributors recall memory before completion; they do not
  persist it;
- not the state store: durable preferences are not compact per-conversation
  control state.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "77777777-7777-7777-7777-777777777777",
  "platform": "web",
  "channel_id": "preferences-desk",
  "sender_id": "guest-510",
  "conversation_id": "prefs-88"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "profile_binding"
  }
}

user_message = "I prefer aisle seats on overnight trips."

relevant prior state = none
linked business objects = none
```

### Prepare-phase walkthrough

1. Policy resolution chooses the standard preference-capture profile.
2. The state store loads the current bounded snapshot.
3. Contributors may emit:
   - persona policy;
   - recent-turn replay;
   - existing memory recall in `evidence` if long-term memory is allowed.
4. Guards, rankers, and selection run normally.
5. The compiler produces a normal `CompletionRequest`.
6. The model returns a confirmation such as "Noted. I'll prefer aisle seats on
   overnight trips."

### Compiled lanes used

- `system_persona_policy`: frames the assistant as a concierge that can
  acknowledge preferences.
- `recent_turn`: may replay the prior preference-related exchange.
- `evidence`: may include prior durable memory if this guest already has stored
  preferences.

### Assistant outcome

The user sees a confirmation, and only then does the runtime commit durable
memory.

### Commit-phase walkthrough

1. The commit store validates the prepared token and moves the ledger into the
   committing state.
2. The state store persists bounded state and appends event-log rows.
3. `DefaultMemoryWriter.persist(...)` runs only when
   `outcome is TurnOutcome.COMPLETED`.
4. In the current core plugin implementation, `DefaultMemoryWriter` derives:
   - one `EPISODE` write for the completed exchange;
   - one `PREFERENCE` write when the user message contains `i prefer `;
   - one `FACT` write when the user message contains `my name is `.
5. The writer persists memory with:
   - `scope_partition`
   - `commit_token`
   - provenance
   - subject
   - optional TTL
6. If the turn is fallback-global with no `sender_id` or `conversation_id`, the
   current default writer persists nothing.
7. Cache and trace updates happen after memory writeback.

Rough memory-write shape:

```text
MemoryWrite = {
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

### Operator/debugger view

If an expected preference did not persist, inspect:

- turn outcome: only `completed` turns persist in the default writer;
- whether the scope had a sender or conversation partition under global
  fallback;
- the commit result memory writes;
- the persisted memory row's `commit_token`, `scope_partition`, and provenance.

### Plugin-author takeaway

Durable memory belongs after commit validation and final-response handling.
Keep recall and writeback in separate collaborators.

### Contract vs current implementation notes

- Contract guarantee: memory writeback is post-turn and commit-phase.
- Contract guarantee: successful duplicate delivery may replay a stored commit
  result instead of re-running persistence.
- Default engine behavior: memory writer runs after state save and before commit
  finalization.
- Current core plugin implementation: `DefaultMemoryWriter` uses simple text
  heuristics for `EPISODE`, `PREFERENCE`, and `FACT` writes.
- Current core plugin implementation detail: the default writer does not
  currently consult `policy.retention.allow_long_term_memory`; memory recall is
  gated in `MemoryContributor`, but writeback policy may need downstream
  tightening.
- Illustrative example: seating preference capture is a realistic durable-memory
  case, not the only one.

## Story 9 — Reconstructing why a waiver was declined

### Why this story exists

When operators say "the assistant made the wrong call," they usually need
provenance and dropped-artifact reasoning, not just the final answer text.

### Real-world scenario

A guest asks for a waiver after a late arrival.
The assistant declines.
Operations wants to know whether the decline came from:

- missing evidence,
- dropped evidence,
- stale case state,
- source-policy filtering,
- or an actual model judgment on the selected bundle.

### Problem to solve

The runtime needs prepare and commit observability that is scoped, explainable,
and safe to disable.

### Why this layer is the right tool

`IContextTraceSink` is the right collaborator because trace is observability
side effect, not primary business persistence.

Why not:

- not a guard: guards decide drops but do not own trace storage;
- not a cache: cache is ephemeral optimization, not explainable diagnostics.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "88888888-8888-8888-8888-888888888888",
  "platform": "web",
  "channel_id": "waiver-desk",
  "sender_id": "guest-991",
  "conversation_id": "waiver-509",
  "case_id": "3ba2f4e3-4f26-4443-9a4f-9f3f7abca831"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "case_binding"
  }
}

user_message = "Can you waive the no-show fee?"

relevant prior state = {
  "current_objective": "Assess fee waiver",
  "summary": "Guest disputes no-show classification."
}

linked business objects = {
  "ops_case": "CASE-509"
}
```

### Prepare-phase walkthrough

1. Policy resolution selects the waiver profile and a trace policy that enables
   prepare capture plus selected and dropped item capture.
2. Contributors emit persona, state, case overlay, recent turns, and evidence.
3. Source policy, guards, rankers, dedupe, and selection produce a final
   selected set plus a dropped set.
4. The engine builds `bundle.trace` with:
   - `scope`
   - `selected`
   - `dropped`
5. Each selected or dropped item includes:
   - `artifact_id`
   - `lane`
   - `render_class`
   - `kind`
   - `contributor`
   - `score`
   - `reason`
   - `detail`
   - source identity
6. `RelationalContextTraceSink.record_prepare(...)` filters selected and dropped
   payloads according to trace policy and persists a `ContextTrace` row with
   `stage="prepare"`.

Rough dropped-item example:

```text
{
  "artifact_id": "knowledge:general-fee-policy-v2",
  "lane": "evidence",
  "contributor": "knowledge_pack",
  "reason": "dropped_budget",
  "detail": "lane_max_items:evidence",
  "source": {
    "kind": "knowledge_pack_revision",
    "source_key": "general-fee-policy"
  }
}
```

### Compiled lanes used

- `system_persona_policy`: waiver policy and assistant framing.
- `bounded_control_state`: compact waiver-progress state.
- `operational_overlay`: linked case details.
- `recent_turn`: local replay window.
- `evidence`: approved waiver-policy excerpts.

### Assistant outcome

The assistant declines or escalates based on the selected working set.
If the outcome is wrong, operators can see whether the wrong evidence was
selected or whether the right evidence never reached compilation.

### Commit-phase walkthrough

1. The commit store validates and acquires the commit token.
2. State, memory, and cache side effects run.
3. The trace sink records a second `ContextTrace` row with `stage="commit"`.
4. The commit payload contains:
   - `completion_model`
   - `completion_stop_reason`
   - `final_user_responses`
   - `outcome`
   - serialized `ContextCommitResult`
5. In the current core plugin implementation, the trace sink can also bridge
   the event into `AuditBizTraceEvent`.
6. Trace failure is non-authoritative; it should not redefine business
   correctness.

### Operator/debugger view

Inspect in order:

1. prepare-stage selected and dropped items;
2. source identities and contributor names on the evidence lane;
3. dedupe winners and losers;
4. commit-stage outcome and final user-visible response;
5. whether trace policy suppressed selected or dropped payload capture.

### Plugin-author takeaway

If you need explainability, write it through a trace sink.
Do not overload state, cache, or business tables with diagnostics payloads.

### Contract vs current implementation notes

- Contract guarantee: trace capture is controlled by `ContextPolicy`.
- Contract guarantee: trace failures do not redefine business correctness.
- Default engine behavior: prepare and commit trace recording are separate
  toggles.
- Current core plugin implementation: `RelationalContextTraceSink` stores
  `ContextTrace` rows and optionally writes audit bridge events.
- Illustrative example: the waiver case and dropped evidence items are
  representative diagnostic payloads.

## Story 10 — End-to-end delayed-arrival replan

### Why this story exists

Most real turns are not "just retrieval" or "just state."
They cross policy, state, overlays, history, evidence, ranking, and commit.

### Real-world scenario

Tenant `Asteria Travel` handles a high-value airport-transfer case.
A guest sends:

"Flight LX214 landed late. Move pickup to 01:30 and tell the driver I have two
extra bags."

The turn already has:

- a resolved tenant;
- a linked work item and case;
- recent messaging history;
- a bounded state snapshot;
- published baggage and transfer policy evidence;
- a stored vehicle preference from a prior successful turn.

### Problem to solve

The engine must assemble the right cross-lane working set, let downstream
messaging continue through completion/RPP/CT, and then persist the right
post-turn side effects safely.

### Why this layer is the right tool

This story highlights the full engine orchestration, because no single
collaborator owns the whole problem.

Why not:

- not any one contributor: no contributor can see all final budget and render
  decisions;
- not the messaging handler alone: messaging orchestrates the turn, but the
  context engine owns context preparation and commit semantics.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "platform": "telegram",
  "channel_id": "vip-concierge",
  "sender_id": "guest-8841",
  "conversation_id": "pickup-991",
  "case_id": "6a09f01a-9e6a-48b3-9a2e-cbb6c4edbe8e",
  "workflow_id": "wf-airport-77"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "vip_router"
  },
  "locale": "en-US",
  "category": "transfer-ops"
}

user_message = "Flight LX214 landed late. Move pickup to 01:30 and tell the driver I have two extra bags."

relevant prior state = {
  "current_objective": "Coordinate airport pickup",
  "entities": {
    "pickup_reference": "PU-991",
    "driver_assignment": "pending"
  },
  "unresolved_slots": [],
  "summary": "VIP pickup in progress."
}

linked business objects = {
  "ops_case": "CASE-7781",
  "work_item": "trace-linked",
  "memory": "SUV preference"
}
```

### Prepare-phase walkthrough

1. The message handler normalizes ingress into `ContextTurnRequest`.
2. `prepare_turn(...)` resolves policy first. The VIP profile selects the
   concierge persona, evidence policy, trace flags, and budgets.
3. The state store loads the bounded snapshot for the scoped conversation.
4. Contributors emit candidates:
   - `PersonaPolicyContributor` -> `system_persona_policy`
   - `StateContributor` -> `bounded_control_state`
   - `ChannelOrchestrationContributor` -> `operational_overlay`
   - `OpsCaseContributor` -> `operational_overlay`
   - `RecentTurnContributor` -> `recent_turn`
   - `KnowledgePackContributor` -> `evidence`
   - `MemoryContributor` -> `evidence`
5. Source policy removes any evidence source not allowed for the VIP transfer
   category.
6. Guards enforce tenant match and sensitivity blocking. If a memory record came
   from the wrong tenant, it would stop here.
7. Rankers score the surviving candidates.
   Inside `evidence`, the current baggage exception bulletin can outrank an
   older general baggage FAQ.
8. Dedupe removes duplicates by lane, render class, and canonical source
   identity.
9. Selection fills lane minima first and then spillover. A realistic selected
   set is:
   - persona policy
   - one bounded-state snapshot
   - one or two operational overlays
   - two recent-turn messages
   - one vehicle-preference memory item
   - one baggage-policy evidence item
10. The compiler renders structured lanes as `system` messages, replays recent
    turns as normal completion messages, then appends the current user message.
11. The engine issues one commit token, computes a `prefix_fingerprint`, writes
    cache hints, and records prepare trace if enabled.

Rough compiled shape:

```text
CompletionRequest.messages ~= [
  {"role": "system", "content": {"context_lane": "system_persona_policy"}},
  {"role": "system", "content": {"context_lane": "bounded_control_state"}},
  {"role": "system", "content": {"context_lane": "operational_overlay"}},
  {"role": "assistant", "content": "I can adjust that. What arrival time should I use?"},
  {"role": "user", "content": "01:30. Also two extra bags."},
  {"role": "system", "content": {"context_lane": "evidence"}},
  {
    "role": "user",
    "content": "Flight LX214 landed late. Move pickup to 01:30 and tell the driver I have two extra bags."
  }
]
```

### Compiled lanes used

- `system_persona_policy`: VIP concierge persona and effective policy.
- `bounded_control_state`: compact pickup-progress state.
- `operational_overlay`: linked conversation routing, work item, and ops case.
- `recent_turn`: last few replay messages for local continuity.
- `evidence`: memory recall plus approved transfer-policy evidence.

### Assistant outcome

The assistant can say:
"Pickup `PU-991` is moved to `01:30`. I've noted two extra bags and will pass
that to the driver assignment team. Your SUV preference is already on file."

That answer depends on several lanes working together, but the user only sees
one coherent response.

### Commit-phase walkthrough

1. After completion, the messaging path may run RPP extensions and CT
   extensions.
   Those are outside the context engine, but they happen before commit, so
   commit sees the final user-visible response and final outcome.
2. `commit_turn(...)` validates the prepared token and begins the commit ledger
   transition.
3. The state store writes the next state revision and appends user and assistant
   events.
4. The memory writer decides whether this turn creates new durable memory.
   In this example it may only add an `EPISODE` record, because the user did
   not express a new durable preference.
5. Cache writes the `working_set` entry for this scope.
6. The commit ledger finalizes as committed.
7. The trace sink records the commit-stage payload.
8. Raw transcripts and evidence bodies remain event/history or evidence
   material; they are not automatically promoted into bounded state.

### Operator/debugger view

For an end-to-end failure, inspect in this order:

1. `ContextScope` and `tenant_resolution`
2. resolved profile and policy
3. loaded state revision
4. contributors that emitted nothing
5. source-policy drops
6. guard drops
7. rank order inside each lane
8. selected versus dropped artifacts
9. compiled message order
10. commit result, memory writes, cache updates, and traces

### Plugin-author takeaway

Think in phases:

- prepare is for assembling the smallest sufficient working set;
- commit is for replay-safe persistence based on the final assistant-visible
  result.

If the behavior belongs in only one of those phases, keep it there.

### Contract vs current implementation notes

- Contract guarantee: the runtime is two-phase and commit uses an opaque token.
- Contract guarantee: the five lane buckets are stable selection primitives.
- Default engine behavior: prepare order is resolver -> state -> contributors ->
  source policy -> guards -> rankers -> dedupe -> selection -> compilation ->
  cache/trace.
- Current core plugin implementation: the built-in plugin wires persona, state,
  orchestration, case, audit, knowledge, memory, recent-turn, cache, commit,
  and trace collaborators through `core.fw.context_engine`.
- Illustrative example: the delayed-arrival pickup case is a realistic
  concierge flow, not a special built-in vertical.

## Story 11 — ACP control plane changes runtime behavior

### Why this story exists

The strongest operational value of the default engine is that downstream teams
can change runtime behavior by ACP-managed data instead of by code deploy.

### Real-world scenario

A platform team adds a new high-touch cruise-desk channel.
They need:

- a different persona;
- a stricter evidence allowlist;
- `ops_case` overlays turned on;
- dropped-item trace capture enabled.

They want the next turn to behave differently without replacing contributors or
changing the messaging handler.

### Problem to solve

The runtime must translate ACP-managed resource changes into a new effective
`ContextPolicy` on the next turn.

### Why this layer is the right tool

This is a policy-resolver and control-plane story.
The right change surface is ACP-managed profile, policy, binding, and trace
rows.

Why not:

- not hard-coded branch logic in a contributor;
- not a core engine change, because the contract already supports this
  variation.

### Inputs to the turn

```text
ContextScope = {
  "tenant_id": "99999999-9999-9999-9999-999999999999",
  "platform": "web",
  "channel_id": "cruise-desk",
  "sender_id": "guest-330",
  "conversation_id": "cruise-11"
}

ingress_metadata = {
  "tenant_resolution": {
    "mode": "resolved",
    "source": "crm_binding"
  },
  "ingress_route": {
    "service_route_key": "valet.customer_inbox",
    "client_profile_key": "vip-cruise"
  },
  "locale": "en-US",
  "category": "vip-benefits"
}

user_message = "Can you confirm onboard concierge access for my suite?"
```

Relevant ACP changes before the turn:

```text
ContextProfiles:
- { "name": "vip-cruise", "platform": "web", "channel_key": "cruise-desk", "service_route_key": "valet.customer_inbox", "client_profile_key": "vip-cruise", "policy_id": "..." }

ContextPolicies:
- { "policy_key": "vip-cruise-tight", "contributor_allow": ["persona_policy", "recent_turns", "knowledge_pack", "ops_case"], "source_deny": ["memory_record"] }

ContextContributorBindings:
- { "contributor_key": "ops_case", "platform": "web", "channel_key": "cruise-desk", "is_enabled": true }

ContextSourceBindings:
- { "source_kind": "knowledge_pack_revision", "source_key": "vip-benefits", "platform": "web", "channel_key": "cruise-desk", "locale": "en-US", "category": "vip-benefits", "is_enabled": true }

ContextTracePolicies:
- { "name": "vip-debug", "capture_prepare": true, "capture_commit": true, "capture_selected_items": true, "capture_dropped_items": true }
```

### Prepare-phase walkthrough

1. The next turn enters through the same engine boundary with no code change.
2. `DefaultContextPolicyResolver` reads the updated ACP rows.
3. The new `ContextProfile` wins because it is more specific than the tenant
   default on `platform`, `channel_key`, `service_route_key`, and
   `client_profile_key`.
4. The linked `ContextPolicy` changes:
   - persona metadata
   - contributor allowlist
   - source deny rules
   - budget and trace settings
5. `ContextContributorBindings` allow `ops_case` participation for this
   channel.
6. `ContextSourceBindings` create allow rules for the
   `knowledge_pack_revision` source family and the `vip-benefits` source
   key/category.
7. Source policy still follows contract semantics:
   - allow rules may come from bindings or policy kinds;
   - deny rules still come from policy rows;
   - candidates missing required structured source identity are dropped rather
     than implicitly allowed.
8. Contributors, guards, rankers, selection, and compilation run against that
   newly resolved policy.
9. The compiled lanes differ immediately on the next turn because different
   contributors and evidence sources are now in play.

### Compiled lanes used

- `system_persona_policy`: reflects the new profile and policy immediately.
- `operational_overlay`: appears if the new contributor bindings enable
  `ops_case`.
- `recent_turn`: still provides local continuity if recent history exists.
- `evidence`: now reflects the new source bindings and deny rules.

### Assistant outcome

Without a deploy, the cruise-desk channel now speaks in the new persona, sees
only approved VIP-benefits evidence, includes case overlay when available, and
records the richer trace detail operators requested.

### Commit-phase walkthrough

1. Commit behavior is unchanged structurally; the same token validation and
   persistence flow applies.
2. What changes is which trace payloads and cache hints exist because the
   selected set changed during prepare.
3. If a different selected set changes the final model answer, the stored state
   history and traces will reflect the new control-plane choice.
4. No collaborator registration changed at runtime in this story; only ACP data
   changed.

### Operator/debugger view

If the ACP update "did nothing," inspect:

- which `ContextProfile` actually matched the scope;
- whether the incoming turn really carried the expected `service_route_key`;
- whether the incoming turn really carried the expected `client_profile_key`;
- the resolved `policy_key` in persona content or trace metadata;
- contributor allow/deny results;
- source-policy drops, especially `missing_source_ref` versus `source_allow`.

### Plugin-author takeaway

When the behavior change is tenant-, channel-, or profile-specific and the
contract already supports it, prefer ACP-managed control-plane inputs over code
changes.

### Contract vs current implementation notes

- Contract guarantee: the policy resolver returns one effective
  `ContextPolicy`.
- Contract guarantee: source policy is engine-enforced and fail-closed when
  structured identity is required but missing.
- Default engine behavior: policy resolution happens on every prepare call, so
  control-plane changes affect the next turn.
- Current core plugin implementation: `ContextSourceBindings` map to allow
  rules; deny rules still come from `ContextPolicies.source_deny`.
- Illustrative example: the cruise-desk profile and policy names are sample ACP
  rows.

## Final synthesis

### Common design heuristics

- Start with `ContextScope` and effective `ContextPolicy`, not with prompt
  wording.
- Keep lane semantics stable. A new source family usually needs a new
  contributor or renderer, not a new lane.
- Use `bounded_control_state` for compact operational state, `recent_turn` for
  replay, and `evidence` for retrieved facts or memory recall.
- Emit explicit `ContextSourceRef` whenever operators might need allow/deny
  control or stable dedupe.
- Treat provenance and tenant isolation as required data, not optional metadata.
- Keep prepare-phase collaborators read-oriented and commit-phase collaborators
  write-oriented.

### Common anti-patterns

- Fetch evidence inside a guard or ranker.
- Put final prompt formatting into a contributor.
- Store full transcript or raw evidence bodies in `ContextState`.
- Use cache as authoritative state.
- Depend on lane names as presentation APIs instead of using `render_class`.
- Assume the default memory writer is sufficient for domain-critical extraction
  logic without review.
- Assume global fallback can safely share memory without sender or conversation
  partitioning.

### Choosing the right collaborator checklist

- If you need to choose persona, budget, trace flags, contributor allowlists,
  or source rules by scope, use `IContextPolicyResolver`.
- If you need compact, revisioned, per-scope control state, use
  `IContextStateStore`.
- If you need pre-completion retrieval or synthesized context, use
  `IContextContributor`.
- If you need a hard veto or sensitivity boundary, use `IContextGuard`.
- If you need to score already-collected candidates, use `IContextRanker`.
- If you need a new compiled message shape without changing lane semantics, use
  `IContextArtifactRenderer`.
- If you need replay-safe commit validation, use `IContextCommitStore`.
- If you need non-authoritative working-set or retrieval hints, use
  `IContextCache`.
- If you need durable post-turn memory derived from the final outcome, use
  `IMemoryWriter`.
- If you need diagnostics and provenance persistence, use `IContextTraceSink`.

### Debugging checklist

1. Confirm `ContextScope` first.
2. Confirm `tenant_resolution` and whether the turn is resolved or
   fallback-global.
3. Confirm the resolved profile, policy, trace flags, and contributor/source
   allowlists.
4. Check whether the expected contributor emitted candidates at all.
5. Check source-policy drops before investigating guards.
6. Check guard drops before investigating ranking.
7. Check ranking and dedupe before blaming budget.
8. Check selected versus dropped candidates and their `reason_detail`.
9. Check compiled render order and final `CompletionRequest.messages`.
10. Check commit ledger state, expiry, and fingerprint mismatch if commit
    fails.
11. Check state revision, memory writes, cache namespaces, and trace rows after
    commit.

### If you need X, use Y

| If you need... | Use... |
| --- | --- |
| tenant/channel/profile-specific persona and policy | `IContextPolicyResolver` |
| compact working facts for the current conversation | `IContextStateStore` + `bounded_control_state` |
| replayable short-term conversation history | `recent_turn` via contributor + renderer |
| governed retrieval or operational overlays before completion | `IContextContributor` |
| hard safety blocking | `IContextGuard` |
| evidence ordering within a lane | `IContextRanker` |
| a different compiled message shape | `IContextArtifactRenderer` |
| replay-safe commit authorization | `IContextCommitStore` |
| reusable non-authoritative hints | `IContextCache` |
| durable preference/fact/episode writeback | `IMemoryWriter` |
| post-turn forensic visibility | `IContextTraceSink` |

### Final mental model

The context engine is not "the prompt builder."
It is the tenant-safe, provenance-aware, two-phase runtime that:

- resolves the effective policy for one turn;
- loads compact operational state;
- collects candidate context from multiple collaborators;
- enforces source policy and safety;
- ranks, deduplicates, and budgets the working set;
- compiles the selected set into normalized completion messages;
- and commits replay-safe post-turn side effects after the final outcome is
  known.
