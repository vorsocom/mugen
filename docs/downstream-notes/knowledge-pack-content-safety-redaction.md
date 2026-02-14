# Knowledge Pack Content Safety Redaction

- Status: draft
- Owner: downstream plugin team
- Last Updated: 2026-02-14

## Context

Published knowledge may include PII, secrets, or regulated text fragments.
`knowledge_pack` governance controls publish state but does not provide
domain-specific redaction policy enforcement for every downstream channel.

## Decision

- Add downstream redaction policy checks before indexing searchable text.
- Keep a denylist/regex/rule engine for sensitive token classes.
- Block indexing of non-compliant revisions and route to remediation workflow.
- Apply lightweight response-time masking for snippet rendering as defense in
  depth.

## Core vs Downstream Boundary

- Core responsibilities:
  - Maintain approval/publish workflow and audit metadata.
  - Preserve immutable published revisions.
- Downstream responsibilities:
  - Define sensitive-content classes and detection rules.
  - Enforce pre-index redaction and retrieval-time masking.
  - Operate remediation queues and policy exception flow.
- Why this boundary:
  - Safety policy taxonomy and legal requirements vary by domain and region.

## Implementation Sketch

### Data Model

Add downstream safety artifacts, for example:

- `downstream_kp_redaction_rule`
  - `rule_id UUID PRIMARY KEY`
  - `rule_type TEXT NOT NULL`
  - `pattern TEXT NOT NULL`
  - `severity TEXT NOT NULL`
  - `is_active BOOLEAN NOT NULL`
- `downstream_kp_redaction_audit`
  - `knowledge_entry_revision_id UUID NOT NULL`
  - `rule_id UUID NOT NULL`
  - `action TEXT NOT NULL` (`masked`, `blocked`, `allowed`)
  - `occurred_at timestamptz NOT NULL`

### Services / APIs

- Pre-index pipeline:
  1. Detect sensitive tokens.
  2. Apply masking or block based on severity.
  3. Write audit record and index only allowed text.
- Retrieval pipeline:
  - Re-apply lightweight mask before snippet response.
  - Include internal safety flag for observability, not user payload.

### Operational Notes

- Version redaction rules and support hot reload.
- Re-scan index after major rule updates.
- Document escalation path for false positives/false negatives.

## Validation

- Unit tests for rule matching and masking behavior.
- Integration tests proving blocked content is never indexed.
- Replay tests on historical revisions after rule updates.
- Audit tests proving every redaction decision is recorded.

## Risks / Open Questions

- False positives can hide important policy guidance.
- False negatives can leak sensitive data to channels.
- Regional compliance differences may require per-tenant rule overlays.
