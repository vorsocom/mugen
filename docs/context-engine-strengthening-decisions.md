# Context Engine Strengthening Decisions

Status: Active
Last Updated: 2026-03-09
Audience: Core maintainers, plugin authors

This note records the decisions taken while hardening the context engine. The
design doc is the contract. The authoring guide is the extension guide. This
note explains the choices behind the current shape.

## 1. Source Policy Is Engine-Enforced

Decision:

- contributor allow/deny remains collection-time filtering
- source allow/deny and `ContextSourceRule` are enforced by the engine
- contributors emit facts through `ContextSourceRef`; they do not enforce source
  policy themselves

Why:

- keeps policy central and explainable
- avoids bypassable collaborator-local enforcement
- makes source-key / locale / category rules first-class

## 2. Registry Uses Single Visible Owners For Core Runtime Slots

Decision:

- contributors, guards, rankers, renderers, and trace sinks remain multi-register
- policy resolver, state store, commit store, memory writer, and cache are
  single-owner slots
- competing single-owner registrations fail closed with explicit owner
  diagnostics

Why:

- avoids silent replacement
- preserves clean ownership boundaries
- still allows composite internals behind one owner

## 3. Lanes Stay Stable; Renderers Carry Presentation Extensibility

Decision:

- keep five stable lane buckets in core
- extend compilation through `render_class` + `IContextArtifactRenderer`
- fail prepare if a selected artifact resolves to an unknown renderer path

Why:

- keeps budgeting and selection semantics stable
- avoids frequent core rewrites for every new source family
- gives plugin authors a safe evolution seam

## 4. Dedupe Uses Canonical Source Identity First

Decision:

- dedupe after ranking
- dedupe by lane + render class + canonical source identity
- fall back to content fingerprint only when no canonical source identity exists

Why:

- same-source duplicates collapse deterministically even if contributors present
  them differently
- traces can explain both the dedupe group and the winner

## 5. Budgeting Now Distinguishes Hard Ceilings, Soft Ceilings, And Lane Reservations

Decision:

- keep one default deterministic selector in core
- add `soft_max_total_tokens`
- add per-lane minima, maxima, token reservations, and spillover control
- let `budget_hints` tighten, but not widen, policy ceilings

Why:

- preserves operator explainability
- makes lane retention under pressure explicit
- leaves adaptive trimming as future collaborator/core work instead of
  over-generalizing now

## 6. Commit Tokens Are Issued Lifecycle Handles

Decision:

- use `IContextCommitStore`
- issue opaque tokens at prepare time
- bind them to scope and prepared fingerprint
- track `prepared`, `committing`, `committed`, and `failed`
- replay successful duplicates from stored commit results

Why:

- deterministic hashes were forgeable and replay-blind
- commit lifecycle belongs in its own port, not inside the state store

## 7. State And History Stay Separate

Decision:

- `ContextState` remains compact control state
- transcript/replay data stays in history/event storage
- assistant output is not auto-promoted into durable state

Why:

- bounded state stays operationally useful
- replay and provenance remain reconstructable
- avoids accidental durable transcript bloat

## 8. Docs Now Distinguish Contract, Default, And Reference

Decision:

- design doc states hard guarantees
- authoring guide states collaborator obligations and extension guidance
- this note records why the current design looks the way it does

Why:

- reduces accidental coupling to the current core plugin
- makes future refactors safer for downstream authors

## 9. Resolver Inputs Stay First-Class

Decision:

- policy selection inputs remain explicit resolver inputs
- `service_route_key` is treated as a first-class business-surface selector
- `client_profile_key` remains transport identity and is not repurposed

Why:

- keeps workflow-surface selection out of contributor-local metadata
- preserves a clean split between transport identity and business routing
- makes profile and binding matching explainable in production debugging
