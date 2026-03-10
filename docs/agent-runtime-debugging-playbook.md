# Agent Runtime Debugging Playbook

Status: Draft
Last Updated: 2026-03-10
Audience: operators, on-call engineers, core maintainers, downstream plugin authors

## Purpose

This playbook is for production incidents where the assistant appears to have
ignored the agent runtime, chosen the wrong tool, stalled in background mode,
or returned a terminal outcome that does not match expectations.

Use it for questions such as:

- Why did this route bypass the agent runtime and go straight to completion?
- Why did the planner choose the wrong next action?
- Why did a capability fail or not appear in the catalog?
- Why did the evaluator force retry, replan, or handoff?
- Why did a background run never resume?
- Why did a current-turn run produce a final outcome but future-turn state still
  look wrong?

This guide is about agent-runtime behavior, not generic model debugging.

## If You Only Have 5 Minutes

Use this checklist before you read any deeper section.

1. Confirm whether the request was actually agent-runtime eligible.
   Check `mugen.agent_runtime.enabled`, the resolved `service_route_key`, and
   whether current-turn or background mode was enabled for that route.
2. Confirm the request mode.
   `current_turn` and `background` have different allowed behaviors.
3. Inspect the durable run row.
   Check `status`, `policy_json`, `run_state_json`, `current_sequence_no`,
   `next_wakeup_at`, `lease_owner`, `lease_expires_at`, and
   `final_outcome_json`.
4. Inspect the step history in order.
   Look at decision, observation, and evaluation rows in
   `agent_runtime_plan_step`.
5. Confirm which planner and evaluator were actually selected.
   `planner_key` or `evaluator_key` mismatch falls back to the first registered
   implementation.
6. Confirm the visible capability catalog.
   `policy.capability_allow` and execution guards can both block tools.
7. Distinguish terminal outcome classes.
   `HANDOFF`, `FAILED`, `WAITING`, and `SPAWNED_BACKGROUND` are different
   incidents.
8. For same-turn incidents, remember context-engine commit still runs after the
   agent runtime returns its terminal outcome.

## Mental Model

Operational sequence in the default runtime:

```text
Messaging ingress
  -> ContextEngine.prepare_turn(...)
  -> PlanRunRequest
  -> Agent policy resolution
  -> PreparedPlanRun create/resume
  -> capability listing
  -> planner decision
  -> capability execution or response synthesis
  -> evaluator judgment
  -> append step history
  -> finalize PlanOutcome
  -> ContextEngine.commit_turn(...)
```

Background sequence in the default runtime:

```text
Worker trigger
  -> due run lookup
  -> lease acquisition
  -> request reconstruction from stored snapshot
  -> planner / executor / evaluator loop
  -> waiting or terminal outcome
  -> lease release
```

Treat these as authoritative for one run:

- `PlanRunRequest.service_route_key`
- resolved `AgentRuntimePolicy`
- durable `PreparedPlanRun` fields
- ordered `PlanRunStep` rows
- final `PlanOutcome`

Treat these as suggestive, not authoritative:

- logs from trace sinks, because sink failures are best-effort and non-fatal;
- absence of a capability from one planner response, because planner strategy,
  allowlist filtering, or provider listing could all be involved.

## Where To Look First

Start in this order:

1. route enablement and mode
2. durable run row
3. append-only step history
4. capability catalog and guards
5. planner/evaluator selection
6. background lease state
7. context-engine commit result if the same-turn response looked right but later
   state looked wrong

## Debugging Route Bypass and Direct Completion Fallback

### Symptom

The user got a normal completion response, but no agent-runtime loop appears to
have run.

### Likely layers involved

- `DefaultTextMHExtension`
- `IAgentRuntime.is_enabled_for_request(...)`
- policy resolution

### What to inspect

- whether `core.fw.agent_runtime` was enabled at startup;
- whether the message had a prepared context turn;
- `PlanRunRequest.mode`
- `PlanRunRequest.service_route_key`
- resolved `AgentRuntimePolicy.enabled`
- resolved `current_turn_enabled`

### Common root causes

- route not enabled in `mugen.agent_runtime`;
- missing or unexpected `service_route_key`;
- agent runtime service not wired into messaging;
- request had no prepared context, so same-turn execution was not eligible.

## Debugging Wrong Planner or Evaluator Selection

### Symptom

The runtime used a different strategy than expected, or behavior looks like the
deterministic fallback instead of the configured model-backed strategy.

### What to inspect

- `policy_json.planner_key`
- `policy_json.evaluator_key`
- registered strategy `name` values
- whether the registry actually has any evaluators

### How to reason about it

- if `planner_key` does not match a registered planner name exactly, the first
  registered planner wins;
- if no evaluator is registered, the core evaluation engine falls back
  deterministically.

## Debugging Missing, Blocked, or Failing Capabilities

### Symptom

The planner asked for a capability that failed as `unknown_capability`,
`unsupported_capability`, `validation_failed:*`, or was rejected by policy.

### What to inspect

- `request.available_capabilities`
- `policy.capability_allow`
- descriptor keys in `IAgentExecutor.list_capabilities(...)`
- step payload for the decision row
- step payload for the observation row
- execution guard errors

### Common root causes

- provider did not list the capability for this route;
- allowlist filtering removed the descriptor before planning;
- provider `supports(...)` did not match the chosen key;
- input schema validation failed;
- ACP action metadata was missing or the handler was absent.

### Fix paths

- fix the capability key or provider `supports(...)` logic;
- widen the route allowlist if the route should expose that capability;
- fix provider metadata or ACP handler registration;
- fix the planner prompt or decision mapping if it is hallucinating keys that
  do not exist.

## Debugging Guard Rejections

### Symptom

Execution never starts, or a capability attempt becomes immediate failure or
handoff after a guard rejection.

### What to inspect

- route allowlist policy
- guard implementation order
- raised error text
- decision row plus missing observation rows

### How to reason about it

The default allowlist guard is a hard veto. If the capability is not allowed
for the route, there should be no successful execution observation afterward.

## Debugging Waiting and Background Resume Problems

### Symptom

A background run stays in `WAITING`, never wakes up, or appears stuck behind a
lease.

### What to inspect

- `agent_runtime_plan_run.status`
- `next_wakeup_at`
- `lease_owner`
- `lease_expires_at`
- `policy_json.lease_seconds`
- scheduler due-run output
- whether the worker uses the expected lease owner string

### Common root causes

- wake-up time is still in the future;
- lease is still active for another owner;
- scheduler returns no due ids;
- request snapshot could not be resumed because the run was already finalized.

### Step-by-step investigation

1. Confirm the run is not terminal.
2. Confirm `next_wakeup_at <= now` for waiting runs.
3. Confirm `lease_expires_at <= now` or that the same owner is retrying.
4. Inspect the last decision row.
   If it is `WAIT`, check whether the scheduler normalized the wake-up time.
5. Inspect the next attempted lease acquisition.

## Debugging `SPAWN_BACKGROUND`, `HANDOFF`, and `STOP`

### Symptom

The runtime ended, but not with the outcome the operator expected.

### What to inspect

- terminal `PlanOutcome.status`
- last decision row
- evaluation row just before terminal outcome
- `background_run_id` on `SPAWNED_BACKGROUND`
- `error_message` on `HANDOFF` or `FAILED`

### How to reason about it

- `SPAWNED_BACKGROUND` means the current run completed after creating a second
  run;
- `HANDOFF` means agency stopped intentionally or because evaluation escalated;
- `STOPPED` means the planner ended the run without further work;
- `FAILED` means the runtime exhausted iterations or hit an unrecoverable path.

## Debugging Same-Turn Outcome vs Context Commit Confusion

### Symptom

The user saw a good answer, but the next turn still forgot something or other
context-engine side effects did not happen.

### Likely layers involved

- agent runtime terminal outcome
- `DefaultTextMHExtension`
- `IContextEngine.commit_turn(...)`

### How to reason about it

The agent runtime only produces the same-turn outcome. The context engine still
owns the post-turn commit boundary. A correct `PlanOutcome` does not prove the
context commit succeeded.

### What to inspect

- agent terminal outcome
- context commit result or commit logs
- any context-engine trace or commit-ledger rows

## Debugging Run Persistence Problems

### Symptom

Run state or history looks incomplete, duplicated, or out of order.

### What to inspect

- `current_sequence_no`
- ordered `agent_runtime_plan_step.sequence_no`
- `row_version`
- `final_outcome_json`

### Common root causes

- caller resumed an old run snapshot and lost a row-version race;
- terminal finalize was attempted twice and correctly returned the first
  outcome;
- step payload inspection ignored sequence ordering.

### Contract note

Finalization is idempotent by design. Duplicate finalize attempts are not a
data-corruption bug by themselves.

## Plugin-Author Quick Guide

### My planner is registered but never selected

- check `policy.planner_key`
- check the planner `name`
- remember fallback goes to the first registered planner

### My evaluator appears to do nothing

- check whether any evaluator was registered at all
- inspect evaluation step rows
- remember the core engine can fall back deterministically

### My capability provider lists tools but execution still fails

- check `supports(...)`
- check allowlist filtering
- check guard rejections
- check descriptor metadata needed by the provider

### My background runs never wake up

- inspect `next_wakeup_at`
- inspect lease state
- inspect scheduler due-run output

### My trace sink has gaps

- trace sinks are best-effort
- inspect durable step rows first
- then inspect logs for sink exceptions

## Final Checklists

### Route-bypass incident

- route key confirmed
- policy enabled confirmed
- current-turn enabled confirmed
- prepared context confirmed
- runtime service wiring confirmed

### Wrong-tool incident

- capability catalog inspected
- allowlist inspected
- guard behavior inspected
- planner decision row inspected
- provider `supports(...)` confirmed

### Stuck-background incident

- status confirmed non-terminal
- wake-up time compared to now
- lease state inspected
- scheduler due-run result inspected
- last decision row inspected

### Good-answer-but-bad-next-turn incident

- terminal plan outcome inspected
- context commit result inspected
- context trace or commit ledger inspected

## Final Mental Model

If the question is "what did the planner decide," inspect decision rows.
If the question is "what actually executed," inspect observation rows.
If the question is "why did the runtime continue or stop," inspect evaluation
rows.
If the question is "why did future turns still look wrong," inspect the context
engine commit path after the agent runtime finished.
