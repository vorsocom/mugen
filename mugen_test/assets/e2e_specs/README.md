# ACP HTTP E2E Spec Templates

These JSON files are input specs for:

`bash .codex/skills/acp-http-e2e-tester/scripts/run_acp_http_e2e.sh --spec <path>`

To run the whole template suite with automatic unique placeholder injection:

`bash mugen_test/assets/e2e_specs/run_all_e2e_templates.sh`

## Plugin Coverage

- `acp`: `acp/acp-tenant-invitation-redeem.template.json`
- `ops_case`: `ops_case/ops-case-e2e-lifecycle.template.json`
- `ops_sla`: `ops_sla/ops-sla-e2e-clock-lifecycle.template.json`
- `ops_workflow`: `ops_workflow/ops-workflow-e2e-definition-smoke.template.json`
- `ops_metering`: `ops_metering/ops-metering-e2e-meter-definition-smoke.template.json`
- `billing`: `billing/billing-e2e-account-product-smoke.template.json`
- `ops_vpn`: `ops_vpn/ops-vpn-e2e-vendor-lifecycle.template.json`
- `knowledge_pack`: `knowledge_pack/knowledge-pack-e2e-pack-smoke.template.json`
- `ops_governance`: `ops_governance/ops-governance-e2e-policy-evaluate.template.json`
- `ops_reporting`:
  - `ops_reporting/ops-reporting-e2e-aggregation.template.json`
  - `ops_reporting/ops-reporting-e2e-snapshot.template.json`
- `channel_orchestration`:
  - `channel_orchestration/channel-orchestration-e2e-conversation.template.json`
  - `channel_orchestration/channel-orchestration-e2e-blocklist.template.json`
- `web`: `web/web-e2e-rest-sse-core.template.json`

## Usage Notes

- Treat these as templates; copy to `/tmp` and inject unique values for keys/codes.
- The e2e runner only substitutes these placeholders automatically:
  - `__ROW_VERSION__`
  - `__ENTITY_ID__`
  - `__TENANT_ID__`
  - `__USER_ID__`
- Custom placeholders like `__WF_KEY__` must be replaced before running.
- `run_all_e2e_templates.sh` auto-renders these placeholders:
  - `__CASE_TITLE__`
  - `__TRACKED_REF__`
  - `__WF_KEY__`
  - `__METER_CODE__`
  - `__BILLING_ACCOUNT_CODE__`
  - `__BILLING_PRODUCT_CODE__`
  - `__VENDOR_CODE__`
  - `__PACK_KEY__`
  - `__POLICY_CODE__`
  - `__SENDER_KEY__`
  - `__BLOCK_SENDER_KEY__`
  - `__CODE__`
  - `__SNAP_NOTE__`
  - `__WEB_CONVERSATION_ID__`
  - `__WEB_TEXT__`
  - `__ACP_USERNAME__`
  - `__ACP_PASSWORD__`
  - `__INVITEE_EMAIL__`
- ACP invitation-redeem template notes:
  - `redeem_scenarios` captures authenticated redeem checks
    (success/replay/expired/email-mismatch).
  - these scenarios are auto-run by
    `mugen_test/assets/e2e_specs/acp/run_acp_invitation_redeem_e2e.sh` when
    orchestrated from `run_all_e2e_templates.sh`.
  - the ACP invitation runner starts a local SMTP sink to capture outbound
    invite emails and extracts the redeem token from `InviteUrl` in the
    message body.

## Web E2E Behavior

- Web specs are executed by:
  - `bash mugen_test/assets/e2e_specs/web/run_web_http_e2e.sh --spec <path>`
- Web runner strict mode:
  - enabled automatically when `CI=true`
  - can be enabled manually with `WEB_E2E_STRICT=1`
- Web runner exit codes:
  - `0`: pass
  - `1`: fail
  - `2`: skipped (web unavailable in non-strict mode)
- `run_all_e2e_templates.sh` summary reports `passed`, `failed`, and `skipped`.
- Only `failed` specs fail the overall orchestrator exit status.
