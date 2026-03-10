# Agent Runtime Authoring Guide

Status: Active
Last Updated: 2026-03-10
Audience: Downstream plugin authors, core maintainers

## Purpose

This guide explains how to extend muGen's agent-runtime seam safely.

Use it when you need same-turn planning, capability execution, response
evaluation, background continuation, or run persistence through the core agent
runtime instead of hard-coding orchestration inside one plugin or message
handler.

For hard runtime semantics, see `docs/agent-runtime-design.md`.
If you are debugging why a collaborator did or did not affect a run, see
`docs/agent-runtime-debugging-playbook.md`.

## Read This First

Contract guarantee: the design doc defines the hard runtime contract.

Default engine behavior: the core `DefaultAgentRuntime` implements that
contract with one deterministic loop above four first-class seams.

Current core plugin implementation: `mugen.core.plugin.agent_runtime` is the
reference plugin. It is not the whole API surface.

If you are unsure whether behavior belongs in core runtime or collaborator
space, prefer collaborator space first.

## Runtime Flow

Default runtime behavior: current-turn flow runs in this order:

1. receive `PlanRunRequest` with `prepared_context`
2. resolve `AgentRuntimePolicy`
3. create or resume one `PreparedPlanRun`
4. list capabilities visible for that run
5. ask the selected planner for `PlanDecision`
6. execute capabilities or synthesize a response
7. ask the evaluator to judge the step, response, or run
8. append immutable step history
9. finalize one `PlanOutcome`

Default runtime behavior: background flow runs in this order:

1. load due run ids or due run rows
2. acquire one lease per run
3. rebuild `PlanRunRequest` from the stored request snapshot
4. execute the same loop with waiting enabled
5. release the lease

Use the agent runtime for orchestration. Keep context preparation and final
context commit in the context engine.

## Choose The Right Collaborator

### `IPlannerStrategy`

Use a planner strategy when you need to choose the next step.

- Input: `PlanRunRequest`, `PreparedPlanRun`, observations, effective policy
- Output: `PlanDecision`
- Good fit: tool selection, branching, deciding when to answer, deciding when
  to hand off, deciding when to spawn background work
- Do not use for capability execution or durable persistence

Planner rules:

- return decisions, not side effects;
- work against normalized capability keys and observation payloads;
- keep provider-specific prompt or tool-call shapes inside the strategy, not in
  core contracts;
- summarize rationale if useful, but do not persist raw chain-of-thought.

### `IEvaluatorStrategy`

Use an evaluator strategy when you need to judge whether the last step, draft
response, or terminal outcome was acceptable.

- Input: `EvaluationRequest`, effective policy, optional terminal outcome
- Output: `EvaluationResult`
- Good fit: retry vs replan vs escalate decisions, quality gates, policy-fit
  checks, deterministic or model-backed critics
- Do not use to mutate run state directly

Evaluator rules:

- judge the result; do not choose capabilities directly;
- prefer structured reasons and scores;
- use `recommended_decision` only as a hint, not as hidden control flow.

### `ICapabilityProvider`

Use a capability provider when you need to expose and execute one action
surface.

- Input for listing: request, run, policy
- Output for listing: `list[CapabilityDescriptor]`
- Input for execution: request, run, invocation, descriptor, policy
- Output for execution: `CapabilityResult`
- Good fit: ACP actions, external APIs, internal workflow actions, deterministic
  computation tools
- Do not use to choose when a capability should run

Capability-provider rules:

- keep descriptor keys stable;
- publish a real input schema when possible;
- use `metadata` for provider-private execution details;
- return normalized errors instead of leaking provider exceptions where
  possible.

### `IExecutionGuard`

Use an execution guard when you need a hard veto around capability execution.

- Input: request, run, invocation, descriptor, policy
- Output: raise or return normally
- Good fit: route allowlists, approval boundaries, tenant restrictions,
  dangerous side-effect suppression
- Do not use to build catalogs or run capabilities

Guard rules:

- fail closed;
- keep decisions deterministic where possible;
- explain rejections clearly because operators will debug from the raised error
  and persisted step history.

### `IResponseSynthesizer`

Use a response synthesizer when you need to turn a planner decision into final
user-visible response payloads.

- Input: request, run, decision, policy
- Output: `list[dict]`
- Good fit: multi-part payload shaping, structured response envelopes,
  future non-text response families
- Do not use to select the next action

### `IAgentTraceSink`

Use a trace sink when you need extra observability beyond the persisted step
table.

- Input: request, run, immutable step or final outcome
- Output: side-effect only
- Good fit: audit projections, metrics, external trace systems
- Do not use to affect runtime control flow

Trace-sink rules:

- treat sink writes as best-effort;
- never rely on a sink to make correctness decisions;
- prefer structured summaries over raw model reasoning text.

### `IAgentPolicyResolver`

Use a policy resolver when you need to turn route and runtime context into one
effective `AgentRuntimePolicy`.

- Input: `PlanRunRequest`
- Output: `AgentRuntimePolicy`
- Good fit: route enablement, planner/evaluator selection, capability
  allowlists, iteration budgets
- Do not use to execute capabilities or persist step history

Current reference implementation: `CodeConfiguredAgentPolicyResolver` reads
`mugen.agent_runtime` and route overrides keyed by exact `service_route_key`.

### `IPlanRunStore`

Use a run store when you need durable run persistence.

- Input: normalized run and step shapes
- Output: normalized run and cursor shapes
- Good fit: latest run snapshot, append-only step rows, leases, due-run lookup,
  idempotent finalize
- Do not use to embed planning or evaluation decisions

Run-store rules:

- preserve append-only step history;
- make finalize idempotent;
- keep leases explicit and replay-safe;
- persist structured decision/evaluation summaries, not raw chain-of-thought.

### `IAgentScheduler`

Use a scheduler when delayed background work needs an external or pluggable due
run policy.

- Input: limit, current time, run + desired wake-up time
- Output: due run ids or normalized wake-up timestamp
- Good fit: queue integration, delayed wake-ups, custom due ordering
- Do not use to own run persistence

## Policy Config

Current reference implementation recognizes this runtime-config shape:

```toml
[mugen.agent_runtime]
enabled = true
current_turn_enabled = true
background_enabled = false
planner_key = "llm_default"
evaluator_key = "llm_default"
response_synthesizer_key = "text_default"
capability_allow = ["acp__OpsCases__assign"]
max_iterations = 4
max_background_iterations = 8
lease_seconds = 60
wait_seconds_default = 30

[[mugen.agent_runtime.routes]]
service_route_key = "support.primary"
background_enabled = true
capability_allow = ["acp__OpsCases__assign", "acp__OpsCases__escalate"]
```

Current behavior notes:

- route matching is exact on `service_route_key`;
- route values overlay root defaults;
- an empty route allowlist inherits the default allowlist;
- planner, evaluator, and synthesizer selection is by exact `name`.

Current limitation: this policy surface is code-configured only. There is no
ACP admin resource for agent-runtime policy yet.

## Registration Path

Current reference implementation uses one plugin-owned registry:
`AgentComponentRegistry`.

Register one owner only for:

- `policy_resolver`
- `run_store`
- `scheduler`

Register zero or more implementations for:

- planners
- evaluators
- capability providers
- execution guards
- response synthesizers
- trace sinks

Current default registration happens in
`mugen.core.plugin.agent_runtime.fw_ext.AgentRuntimeFWExtension`.

## Reference Implementations

Use the current plugin components as the baseline examples:

- `LLMPlannerStrategy`
- `LLMEvaluationStrategy`
- `ACPActionCapabilityProvider`
- `AllowlistExecutionGuard`
- `TextResponseSynthesizer`
- `RelationalPlanRunStore`
- `RelationalAgentScheduler`
- `CodeConfiguredAgentPolicyResolver`

These are reference implementations, not locked architecture.

## Guardrails

- Keep ACP, database, and provider SDK details in plugin adapters, not in core
  contracts.
- Keep capability keys stable once planners or policies can reference them.
- Do not let planners write directly to storage or call ACP directly.
- Do not let evaluators mutate run state directly.
- Do not persist chain-of-thought in step payloads, metadata, or trace sinks.
- Treat response synthesis as presentation, not planning.
- Prefer route-scoped policy changes over hard-coded planner branching.

## When To Change Core Instead

Change core contracts only when at least one of these is true:

- a new stable intermediate representation is missing;
- the existing seams force provider-specific payloads into core;
- a collaborator needs data that should be universally available to all
  implementations;
- the runtime loop cannot express a stable orchestration state that more than
  one plugin or provider will need.

Do not change core just because the reference LLM planner or ACP capability
provider needs a one-off behavior. Add or replace a collaborator first.
