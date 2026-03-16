# Agent Runtime Design

Status: Active
Last Updated: 2026-03-10
Audience: Core maintainers, plugin authors, downstream platform teams

## Purpose

This document defines the agent runtime introduced in core. It adds one
provider-neutral, plugin-composable orchestration boundary above the context
engine for same-turn agency and resumable background execution.

Use this document for hard runtime semantics. Use
`docs/agent-runtime-authoring.md` for collaborator authoring and registration.
Use `docs/agent-runtime-debugging-playbook.md` when you need a deterministic
operator workflow for diagnosing route bypass, planner decisions, capability
execution failures, or stuck background runs.

## Design Goals

- keep clean architecture boundaries intact;
- keep context assembly and post-turn context commit owned by the context
  engine;
- support same-turn plan-act-evaluate loops without freezing the system to one
  planning style or one provider;
- support resumable background execution with durable state and leases;
- keep capability execution provider-neutral even when ACP is the default
  implementation;
- persist structured step history and policy snapshots without persisting raw
  chain-of-thought;
- make policy and strategy selection route-scoped and replaceable.

## Hard Contract

Contract guarantee: the core agent-runtime contract lives in
`mugen.core.contract.agent`.

Primary primitives:

- `PlanRunRequest`: normalized request envelope for current-turn or background
  execution.
- `PreparedPlanRun`: durable run handle with current policy snapshot, cursor,
  status, metadata, and optional lease/outcome state.
- `PlanRunState`: mutable run state owned by the runtime and run store.
- `PlanDecision`: planner-selected next action.
- `PlanObservation`: normalized observation produced between planner steps.
- `EvaluationRequest` / `EvaluationResult`: evaluator request and judgment
  shapes.
- `PlanOutcome`: terminal or externally visible outcome for one run.
- `CapabilityDescriptor` / `CapabilityInvocation` / `CapabilityResult`:
  provider-neutral capability catalog and execution shapes.
- `PlanLease`: background execution lease.
- `PlanRunCursor` / `PlanRunStep`: append-only run-history cursor and step row.

Primary ports:

- `IPlanningEngine`
- `IEvaluationEngine`
- `IAgentExecutor`
- `IPlanRunStore`
- `IAgentRuntime`
- `IAgentPolicyResolver`
- `IPlannerStrategy`
- `IEvaluatorStrategy`
- `ICapabilityProvider`
- `IExecutionGuard`
- `IResponseSynthesizer`
- `IAgentTraceSink`
- `IAgentScheduler`

Contract guarantee: the runtime is split across five first-class seams.

1. `IPlanningEngine` prepares or resumes runs and delegates decision-making to
   named planner strategies.
2. `IEvaluationEngine` judges step, response, and terminal outcomes.
3. `IAgentExecutor` lists capabilities and executes one normalized invocation.
4. `IPlanRunStore` persists run snapshots, append-only steps, leases, and final
   outcomes.
5. `IAgentRuntime` coordinates the loop above those four seams.

Contract guarantee: planners choose, evaluators judge, executors execute, and
run stores persist. Those responsibilities must not collapse into one
implementation boundary.

Contract guarantee: contracts are centered on stable intermediate
representations, not ACP DTOs, vendor tool-call payloads, or one prompt shape.

## Clean Architecture Boundary

Contract guarantee: core contract and core service layers do not import plugin
models or ACP runtime services.

Allowed core dependencies:

- normalized completion contract types such as `CompletionResponse`;
- normalized prepared context contract types such as `PreparedContextTurn`;
- stable context primitives such as `ContextScope`.

Plugin-owned concerns remain outside core contracts:

- ACP registry and action handler discovery;
- relational table models for durable run rows;
- runtime-config parsing details;
- background scheduling adapters;
- framework extension registration.

Current core implementation: the default runtime in
`mugen.core.service.agent_runtime` depends on the registry-facing ports only.
The reference plugin in `mugen.core.plugin.agent_runtime` owns the relational,
ACP, and framework adapters.

## Runtime Modes

Contract guarantee: the runtime supports two execution modes.

1. `PlanRunMode.CURRENT_TURN`
2. `PlanRunMode.BACKGROUND`

Current-turn mode requires a prepared context turn and produces one terminal
`PlanOutcome` for the live request.

Background mode resumes or continues durable runs from the run store and may
finish, hand off, fail, stop, or return to waiting.

Contract guarantee: same-turn waiting is not allowed. A planner decision of
`WAIT` during current-turn execution becomes terminal handoff rather than an
open wait.

## Runtime Loop

Default runtime behavior: `DefaultAgentRuntime` executes this sequence for
same-turn requests:

```text
Messaging ingress
  -> ContextEngine.prepare_turn(...)
  -> PlanRunRequest(mode=current_turn, prepared_context=...)
  -> IAgentRuntime.is_enabled_for_request(...)
  -> IPlanningEngine.prepare_run(...)
  -> IAgentExecutor.list_capabilities(...)
  -> loop:
       IPlanningEngine.next_decision(...)
       if EXECUTE_ACTION:
         IAgentExecutor.execute_capability(...)
         IEvaluationEngine.evaluate_step(...)
       if RESPOND:
         IResponseSynthesizer.synthesize(...)
         IEvaluationEngine.evaluate_response(...)
       if SPAWN_BACKGROUND:
         IPlanningEngine.prepare_run(background_request)
       if WAIT/HANDOFF/STOP:
         finalize terminal outcome
  -> IPlanRunStore.finalize_run(...)
  -> IPlanningEngine.finalize_run(...)
  -> return PlanOutcome
  -> ContextEngine.commit_turn(...)
```

Contract guarantee: the context engine remains the prepare and commit boundary
for the live message. The agent runtime does not replace context preparation and
does not own context-engine commit.

Default runtime behavior: background batches execute this sequence:

```text
Worker or scheduler trigger
  -> IAgentRuntime.run_background_batch(owner=...)
  -> IAgentScheduler.due_run_ids(...) or IPlanRunStore.list_runnable_runs(...)
  -> IPlanRunStore.acquire_lease(...)
  -> restore PlanRunRequest from request snapshot
  -> IAgentExecutor.list_capabilities(...)
  -> same plan-act-evaluate loop with allow_wait=True
  -> IPlanRunStore.release_lease(...)
```

## Decision Contract

Contract guarantee: planners return one `PlanDecisionKind` from this stable
set:

- `RESPOND`
- `EXECUTE_ACTION`
- `WAIT`
- `HANDOFF`
- `SPAWN_BACKGROUND`
- `DELEGATE`
- `STOP`

Decision semantics:

- `RESPOND`: produce a user-visible answer and run response evaluation.
- `EXECUTE_ACTION`: execute one or more normalized capability invocations and
  run step evaluation.
- `WAIT`: persist a wake-up point for background mode. In current-turn mode,
  this becomes handoff because live requests cannot remain waiting.
- `HANDOFF`: stop agency and surface a human or external handoff outcome.
- `SPAWN_BACKGROUND`: create a new background run and complete the current run.
- `DELEGATE`: background-only hierarchical delegation. Create child runs,
  persist a join barrier, and resume the parent after required children finish.
- `STOP`: terminate without further action.

Contract guarantee: decisions describe what should happen next. They do not
perform execution side effects directly.

Current reference behavior: `DELEGATE` is rejected for live current-turn runs.
If a live route needs multi-agent work, it must first `SPAWN_BACKGROUND` a
coordinator continuation run.

## Evaluation Contract

Contract guarantee: evaluators return one `EvaluationStatus` from this stable
set:

- `PASS`
- `FAIL`
- `RETRY`
- `REPLAN`
- `ESCALATE`

Default runtime behavior:

- `PASS` continues or finalizes normally.
- `RETRY` and `REPLAN` feed a structured evaluation observation back into the
  next planner iteration.
- `ESCALATE` becomes terminal handoff.
- `FAIL` becomes terminal failure.

Current default behavior: if no evaluator strategy is registered, the core
evaluation engine falls back deterministically:

- failed capability results become `REPLAN`;
- blank draft responses become `RETRY`;
- failed terminal outcomes become `ESCALATE`;
- all other cases become `PASS`.

## Capability Contract

Contract guarantee: planners do not see ACP actions directly. They see
normalized `CapabilityDescriptor` values.

Capability descriptors carry:

- stable `key`;
- human-readable `title` and optional `description`;
- normalized `input_schema`;
- optional idempotency metadata;
- `side_effect_class`;
- `approval_required`;
- provider-private metadata.

Current default behavior: the reference plugin exposes ACP resource actions as
capabilities using the key shape:

`acp__<entity_set>__<action_name>`

Current default behavior: the core executor filters listed capabilities through
`policy.capability_allow` before the planner sees them. The allowlist is also
enforced again by the default execution guard before execution.

Contract guarantee: execution guards may veto execution but do not resolve the
capability catalog or perform execution.

## Persistence Contract

Contract guarantee: `IPlanRunStore` owns four durable concerns:

1. latest run snapshot
2. append-only step history
3. background leases and wake-up eligibility
4. idempotent terminal outcome persistence

Current reference plugin behavior:

- `agent_runtime_plan_run` stores one row per run with request snapshot, policy
  snapshot, mutable run state, lineage fields (`parent_run_id`, `root_run_id`,
  `agent_key`, `spawned_by_step_no`), join state, current sequence number,
  wake-up timestamp, lease state, and final outcome.
- `agent_runtime_plan_step` stores one immutable row per step with
  `sequence_no`, `step_kind`, payload, and timestamp.

Current reference behavior: waiting parent runs with join state are not treated
as runnable again until all required child runs are terminal.

Contract guarantee: finalization is idempotent. Once `final_outcome_json` is
present, later finalize attempts return the existing outcome instead of
replacing it.

Contract guarantee: the persisted step and outcome payloads are structured
summaries. Raw chain-of-thought is not a supported persistence shape.

## Policy Model

Current reference plugin behavior: policy is code-configured from
`mugen.agent_runtime` and optional `mugen.agent_runtime.routes[]` entries.

Recognized policy fields:

- `enabled`
- `current_turn_enabled`
- `background_enabled`
- `agent_key`
- `planner_key`
- `evaluator_key`
- `response_synthesizer_key`
- `capability_allow`
- `delegate_agent_allow`
- `max_iterations`
- `max_background_iterations`
- `lease_seconds`
- `wait_seconds_default`

Current reference behavior: agent definitions may also be code-configured under
`mugen.agent_runtime.agents[]`. Route policy or explicit request `agent_key`
selects the effective agent identity, then route values override that agent’s
defaults.

Current route-selection behavior:

- exact `service_route_key` match only;
- route values overlay defaults from `mugen.agent_runtime`;
- empty route `capability_allow` inherits the default allowlist;
- route metadata records the selected `service_route_key`.

Contract guarantee: the control plane for planning and evaluation is not ACP
managed yet. ACP-managed profiles and policies remain future additive work, not
the current contract.

## Registry Ownership

Current reference plugin behavior: runtime composition uses one shared
`AgentComponentRegistry`.

Single-owner slots:

- `policy_resolver`
- `run_store`
- `scheduler`

Multi-register slots:

- `planners`
- `evaluators`
- `capability_providers`
- `execution_guards`
- `response_synthesizers`
- `trace_sinks`

Contract guarantee: conflicting single-owner registrations fail closed.

## Default Plugin Composition

Current reference plugin behavior:

- `CodeConfiguredAgentPolicyResolver`
- `RelationalPlanRunStore`
- `RelationalAgentScheduler`
- `LLMPlannerStrategy`
- `LLMEvaluationStrategy`
- `ACPActionCapabilityProvider`
- `AllowlistExecutionGuard`
- `TextResponseSynthesizer`

Current default planner behavior:

- uses the normalized completion gateway;
- merges capability descriptors into vendor tool parameters;
- converts model tool calls into `EXECUTE_ACTION`;
- otherwise returns `RESPOND`.

Current default evaluator behavior:

- uses the normalized completion gateway;
- expects compact JSON verdicts for prompted evaluation;
- falls back deterministically when the model call fails or returns invalid
  output.

## Observability and Trace

Contract guarantee: trace sinks are optional and best-effort. Trace sink
failures are logged and do not fail the run.

Current default behavior: immutable step rows are appended for:

- planner decisions
- capability observations
- evaluator results

Current default behavior: the terminal outcome is persisted separately on the
run row and is also offered to any registered trace sinks.

These persisted payloads are the primary debugging surface until a richer
operator UI exists.

## Messaging Integration

Current default behavior: `DefaultTextMHExtension` builds a `PlanRunRequest`
after `ContextEngine.prepare_turn(...)`.

If `IAgentRuntime.is_enabled_for_request(...)` returns `False`, the handler
falls back to the legacy single-pass completion path.

If it returns `True`, the handler calls `run_current_turn(...)` and then uses
the terminal `PlanOutcome` when it later commits the context turn.

Contract guarantee: context-engine commit still happens once per message after
the final assistant-visible outcome is known.

## What This Runtime Is Not

- It is not a replacement for the context engine.
- It is not an ACP-managed planning control plane yet.
- It is not a domain workflow engine for long-lived business processes.
- It is not a persistence surface for raw reasoning traces.
- It is not tied to one planner, one evaluator, one model provider, or ACP as
  the only capability substrate.
