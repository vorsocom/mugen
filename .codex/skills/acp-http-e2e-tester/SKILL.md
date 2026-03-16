---
name: acp-http-e2e-tester
description: Run repeatable ACP plugin HTTP end-to-end checks in mugen using Hypercorn and curl. Use when validating a new or changed ACP-based plugin resource/action surface, reproducing API behavior regressions, or confirming expected HTTP status/body behavior for tenant-scoped CRUD and `$action` transitions.
---

# ACP HTTP E2E Tester

## Overview

Run a deterministic ACP HTTP test flow from a JSON spec.
Use one script for auth, tenant discovery, entity create/lookup, action execution, event assertions, and negative/positive create checks.

## Workflow

1. Create or copy a spec JSON file.
2. Optionally enable Hypercorn spawn in the spec for one-command runs.
3. Run the script and review the status lines and assertion output.
4. Treat any non-zero exit as a failing e2e check.

## Commands

Run from repository root:

```bash
bash .codex/skills/acp-http-e2e-tester/scripts/run_acp_http_e2e.sh \
  --spec .codex/skills/acp-http-e2e-tester/references/ops-case-example.json
```

Print effective config without executing HTTP calls:

```bash
bash .codex/skills/acp-http-e2e-tester/scripts/run_acp_http_e2e.sh \
  --spec .codex/skills/acp-http-e2e-tester/references/spec-template.json \
  --print-config
```

## Spec Format

Start from:
`references/spec-template.json`

Use:
`references/ops-case-example.json`

Key fields:
- `runtime.spawn_hypercorn`: start/stop Hypercorn inside the script.
- `runtime.hypercorn_cmd`: exact command used when spawn is enabled.
- `base_url`: ACP API base path, usually `http://127.0.0.1:8081/api/core/acp/v1`.
- `credentials`: login username/password (inject test credentials at runtime; do
  not commit real secrets).
- `tenant_id`: optional; if null, first tenant from `Tenants` is used.
- `entity_set`: target collection under tenant route.
- `create_payload`: JSON payload for entity create.
- `lookup`: identify created entity by field/value.
- `actions`: ordered entity `$action` calls; payload supports placeholders:
  `__ROW_VERSION__`, `__ENTITY_ID__`, `__TENANT_ID__`, `__USER_ID__`.
- `assertions`: optional final checks (`final_status`, expected event sequence).
- `negative_creates` and `positive_creates`: optional create-path checks on any entity set.

## Output Expectations

The script prints one line per step:
- HTTP status for each endpoint
- entity id / row-version / status progression
- assertion pass/fail lines for final status and event sequence

Exit code:
- `0`: all checks passed
- non-zero: one or more HTTP or assertion failures

## Operating Rules

- Keep specs plugin-specific; do not hardcode business routing policy in the script.
- Use `negative_creates` to verify validation behavior (expected 4xx) for newly added schemas.
- Keep `lookup.value` unique per run (timestamp suffix) to avoid selecting stale rows.
- If running with spawned Hypercorn, confirm the command uses the correct interpreter and `PYTHONPATH` for local dependencies.
- Keep reference specs sanitized; avoid committing machine-specific absolute
  paths or real credentials.
