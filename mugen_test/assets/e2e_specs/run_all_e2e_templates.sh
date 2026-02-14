#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Run ACP HTTP E2E template specs with automatic unique placeholder injection.

Usage:
  mugen_test/assets/e2e_specs/run_all_e2e_templates.sh [options]

Options:
  --print-config       Validate rendered specs only (no HTTP execution).
  --only <substring>   Run only specs whose path contains substring.
  --continue-on-error  Continue executing remaining specs after a failure.
  -h, --help           Show this help message.
EOF2
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
RUNNER="$REPO_ROOT/.codex/skills/acp-http-e2e-tester/scripts/run_acp_http_e2e.sh"

PRINT_CONFIG=0
ONLY_FILTER=""
CONTINUE_ON_ERROR=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --print-config)
      PRINT_CONFIG=1
      shift
      ;;
    --only)
      ONLY_FILTER="$2"
      shift 2
      ;;
    --continue-on-error)
      CONTINUE_ON_ERROR=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

require_cmd bash
require_cmd sed
require_cmd mktemp

if [[ ! -x "$RUNNER" ]]; then
  echo "ERROR: runner not found or not executable: $RUNNER" >&2
  exit 1
fi

declare -a SPECS=(
  "mugen_test/assets/e2e_specs/ops_case/ops-case-e2e-lifecycle.template.json"
  "mugen_test/assets/e2e_specs/ops_sla/ops-sla-e2e-clock-lifecycle.template.json"
  "mugen_test/assets/e2e_specs/ops_workflow/ops-workflow-e2e-definition-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_metering/ops-metering-e2e-meter-definition-smoke.template.json"
  "mugen_test/assets/e2e_specs/billing/billing-e2e-account-product-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_vpn/ops-vpn-e2e-vendor-lifecycle.template.json"
  "mugen_test/assets/e2e_specs/knowledge_pack/knowledge-pack-e2e-pack-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_governance/ops-governance-e2e-policy-evaluate.template.json"
  "mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-aggregation.template.json"
  "mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-snapshot.template.json"
  "mugen_test/assets/e2e_specs/channel_orchestration/channel-orchestration-e2e-conversation.template.json"
  "mugen_test/assets/e2e_specs/channel_orchestration/channel-orchestration-e2e-blocklist.template.json"
)

render_spec() {
  local template="$1"
  local output="$2"
  local run_id="$3"

  local run_id_flat
  run_id_flat="$(echo "$run_id" | tr -cd '[:alnum:]_')"

  local case_title tracked_ref wf_key meter_code vendor_code
  local pack_key policy_code sender_key block_sender_key reporting_code snap_note
  local billing_account_code billing_product_code

  case_title="E2E OpsCase ${run_id}"
  tracked_ref="OPS-SLA-${run_id}"
  wf_key="wf_${run_id_flat}"
  meter_code="mtr_${run_id_flat}"
  billing_account_code="acct_${run_id_flat}"
  billing_product_code="prd_${run_id_flat}"
  vendor_code="vpn_${run_id_flat}"
  pack_key="kp_${run_id_flat}"
  policy_code="gov_${run_id_flat}"
  sender_key="E2E-CHORCH-${run_id}"
  block_sender_key="E2E-CHORCH-BLOCK-${run_id}"
  reporting_code="ops_reporting_e2e_${run_id_flat}"
  snap_note="Ops reporting snapshot lifecycle e2e ${run_id}"

  sed \
    -e "s|__CASE_TITLE__|${case_title}|g" \
    -e "s|__TRACKED_REF__|${tracked_ref}|g" \
    -e "s|__WF_KEY__|${wf_key}|g" \
    -e "s|__METER_CODE__|${meter_code}|g" \
    -e "s|__BILLING_ACCOUNT_CODE__|${billing_account_code}|g" \
    -e "s|__BILLING_PRODUCT_CODE__|${billing_product_code}|g" \
    -e "s|__VENDOR_CODE__|${vendor_code}|g" \
    -e "s|__PACK_KEY__|${pack_key}|g" \
    -e "s|__POLICY_CODE__|${policy_code}|g" \
    -e "s|__SENDER_KEY__|${sender_key}|g" \
    -e "s|__BLOCK_SENDER_KEY__|${block_sender_key}|g" \
    -e "s|__CODE__|${reporting_code}|g" \
    -e "s|__SNAP_NOTE__|${snap_note}|g" \
    "$template" > "$output"
}

RUNNER_ARGS=()
if [[ "$PRINT_CONFIG" -eq 1 ]]; then
  RUNNER_ARGS+=(--print-config)
fi

pass_count=0
fail_count=0
index=1

for spec_rel in "${SPECS[@]}"; do
  if [[ -n "$ONLY_FILTER" && "$spec_rel" != *"$ONLY_FILTER"* ]]; then
    continue
  fi

  spec_path="$REPO_ROOT/$spec_rel"
  if [[ ! -f "$spec_path" ]]; then
    echo "ERROR: template not found: $spec_rel" >&2
    ((fail_count += 1))
    if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
      break
    fi
    continue
  fi

  run_id="$(date +%Y%m%d_%H%M%S)_${index}"
  rendered_spec="$(mktemp "/tmp/acp_http_e2e_${index}_XXXXXX.json")"
  render_spec "$spec_path" "$rendered_spec" "$run_id"

  echo
  echo "=== RUNNING: $spec_rel ==="
  echo "rendered: $rendered_spec"

  if bash "$RUNNER" --spec "$rendered_spec" "${RUNNER_ARGS[@]}"; then
    ((pass_count += 1))
  else
    ((fail_count += 1))
    if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
      rm -f "$rendered_spec"
      break
    fi
  fi

  rm -f "$rendered_spec"
  ((index += 1))
done

echo
echo "SUMMARY: passed=$pass_count failed=$fail_count"
if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
