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
  --suite <full|smoke> Select spec suite (default: full).
  --server-mode <shared|isolated>
                       Hypercorn lifecycle for ACP/Web specs (default: shared).
  --continue-on-error  Continue executing remaining specs after a failure.
  --ephemeral-db       Start a disposable Postgres instance (default).
  --no-ephemeral-db    Disable disposable Postgres for this run.
  -h, --help           Show this help message.

Config resolution order:
  1. MUGEN_E2E_CONFIG_FILE
  2. MUGEN_CONFIG_FILE
  3. mugen.e2e.toml (repository root)
EOF2
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

require_positive_int() {
  local value="$1"
  local field_name="$2"
  if [[ ! "$value" =~ ^[0-9]+$ || "$value" -le 0 ]]; then
    echo "ERROR: $field_name must be a positive integer (got: $value)" >&2
    exit 1
  fi
}

find_bin() {
  local name="$1"
  local fallback="${2:-}"
  if command -v "$name" >/dev/null 2>&1; then
    command -v "$name"
    return
  fi
  if [[ -n "$fallback" && -x "$fallback" ]]; then
    echo "$fallback"
    return
  fi
  echo ""
}

resolve_python_bin() {
  local candidate="${ACP_E2E_PYTHON_BIN:-python3}"

  if [[ -x "$candidate" ]]; then
    echo "$candidate"
    return
  fi

  if command -v "$candidate" >/dev/null 2>&1; then
    command -v "$candidate"
    return
  fi

  if command -v python >/dev/null 2>&1; then
    command -v python
    return
  fi

  echo "ERROR: could not find a usable python interpreter for E2E Hypercorn startup." >&2
  echo "Set ACP_E2E_PYTHON_BIN to a valid interpreter path." >&2
  exit 1
}

shell_join_quoted() {
  local arg output=""
  for arg in "$@"; do
    output+=$(printf '%q ' "$arg")
  done
  echo "${output% }"
}

escape_sed_replacement() {
  printf '%s' "$1" | sed -e 's/[&|]/\\&/g'
}

resolve_e2e_config_file() {
  local candidate=""

  if [[ -n "${MUGEN_E2E_CONFIG_FILE:-}" ]]; then
    candidate="$MUGEN_E2E_CONFIG_FILE"
  elif [[ -n "${MUGEN_CONFIG_FILE:-}" ]]; then
    candidate="$MUGEN_CONFIG_FILE"
  else
    candidate="mugen.e2e.toml"
  fi

  if [[ "$candidate" = /* ]]; then
    echo "$candidate"
  else
    echo "$REPO_ROOT/$candidate"
  fi
}

setup_ephemeral_db() {
  local source_config="$1"
  local python_bin="$2"
  local initdb_bin
  local pg_ctl_bin
  local createdb_bin

  initdb_bin="$(find_bin initdb /usr/lib/postgresql/16/bin/initdb)"
  pg_ctl_bin="$(find_bin pg_ctl /usr/lib/postgresql/16/bin/pg_ctl)"
  createdb_bin="$(find_bin createdb)"

  if [[ -z "$initdb_bin" || -z "$pg_ctl_bin" || -z "$createdb_bin" ]]; then
    echo "ERROR: --ephemeral-db requires initdb, pg_ctl, and createdb." >&2
    exit 1
  fi

  EPHEMERAL_PG_CTL_BIN="$pg_ctl_bin"
  EPHEMERAL_TMP_DIR="$(mktemp -d /tmp/mugen_e2e_ephemeral_db_XXXXXX)"
  EPHEMERAL_PGDATA="$EPHEMERAL_TMP_DIR/pgdata"
  EPHEMERAL_LOG="$EPHEMERAL_TMP_DIR/postgres.log"
  EPHEMERAL_CONFIG_FILE="$EPHEMERAL_TMP_DIR/mugen.e2e.toml"
  mkdir -p "$EPHEMERAL_PGDATA"

  "$initdb_bin" -D "$EPHEMERAL_PGDATA" -A trust >/dev/null

  EPHEMERAL_PORT=""
  for candidate_port in $(seq 55432 55450); do
    if "$pg_ctl_bin" \
      -D "$EPHEMERAL_PGDATA" \
      -o "-p $candidate_port -c listen_addresses='' -c unix_socket_directories='/tmp'" \
      -l "$EPHEMERAL_LOG" \
      start >/dev/null 2>&1; then
      EPHEMERAL_PORT="$candidate_port"
      break
    fi
  done

  if [[ -z "$EPHEMERAL_PORT" ]]; then
    echo "ERROR: could not start disposable Postgres (ports 55432-55450)." >&2
    if [[ -f "$EPHEMERAL_LOG" ]]; then
      tail -n 120 "$EPHEMERAL_LOG" >&2 || true
    fi
    exit 1
  fi

  EPHEMERAL_DB_NAME="mugen_e2e_${EPHEMERAL_PORT}_$$"
  "$createdb_bin" -h /tmp -p "$EPHEMERAL_PORT" "$EPHEMERAL_DB_NAME"
  EPHEMERAL_DB_URL="postgresql+psycopg://$(id -un)@/${EPHEMERAL_DB_NAME}?host=%2Ftmp&port=${EPHEMERAL_PORT}"

  "$python_bin" - "$source_config" "$EPHEMERAL_CONFIG_FILE" "$EPHEMERAL_DB_URL" <<'PY'
import sys

import tomlkit

source_config = sys.argv[1]
target_config = sys.argv[2]
db_url = sys.argv[3]

with open(source_config, "r", encoding="utf8") as handle:
    doc = tomlkit.parse(handle.read())

if "rdbms" not in doc:
    doc["rdbms"] = tomlkit.table()
rdbms = doc["rdbms"]

if "alembic" not in rdbms:
    rdbms["alembic"] = tomlkit.table()
if "sqlalchemy" not in rdbms:
    rdbms["sqlalchemy"] = tomlkit.table()

rdbms["alembic"]["url"] = db_url
rdbms["sqlalchemy"]["url"] = db_url

with open(target_config, "w", encoding="utf8") as handle:
    handle.write(tomlkit.dumps(doc))
PY

  echo "E2E EPHEMERAL DB: $EPHEMERAL_DB_NAME (port $EPHEMERAL_PORT)"
  echo "E2E EPHEMERAL CONFIG: $EPHEMERAL_CONFIG_FILE"
  echo "E2E MIGRATIONS: upgrade head"
  MUGEN_CONFIG_FILE="$EPHEMERAL_CONFIG_FILE" \
    "$python_bin" "$REPO_ROOT/scripts/run_migration_tracks.py" \
      --python "$python_bin" \
      --config-file "$EPHEMERAL_CONFIG_FILE" \
      upgrade head
}

start_shared_server() {
  if [[ -n "${SHARED_HYPERCORN_PID:-}" ]] && kill -0 "${SHARED_HYPERCORN_PID}" >/dev/null 2>&1; then
    return
  fi

  local startup_timeout_secs="${ACP_E2E_STARTUP_TIMEOUT_SECS:-30}"
  local health_url="http://127.0.0.1:8081/api/core/acp/v1/auth/.well-known/jwks.json"
  local started=0

  require_positive_int "$startup_timeout_secs" "ACP_E2E_STARTUP_TIMEOUT_SECS"

  SHARED_HYPERCORN_LOG="$(mktemp /tmp/mugen_e2e_shared_hypercorn_XXXXXX.log)"
  SHARED_HYPERCORN_CMD="$(shell_join_quoted env "PYTHONPATH=$E2E_PYTHONPATH" "MUGEN_CONFIG_FILE=$E2E_CONFIG_FILE" "$E2E_PYTHON_BIN" -m hypercorn --bind 127.0.0.1:8081 quartman)"

  echo "E2E SHARED HYPERCORN: $SHARED_HYPERCORN_CMD"
  bash -lc "$SHARED_HYPERCORN_CMD" >"$SHARED_HYPERCORN_LOG" 2>&1 &
  SHARED_HYPERCORN_PID="$!"
  echo "E2E SHARED HYPERCORN PID: $SHARED_HYPERCORN_PID"

  for _ in $(seq 1 "$startup_timeout_secs"); do
    if ! kill -0 "$SHARED_HYPERCORN_PID" >/dev/null 2>&1; then
      echo "ERROR: shared Hypercorn exited before becoming healthy." >&2
      echo "See log: $SHARED_HYPERCORN_LOG" >&2
      tail -n 120 "$SHARED_HYPERCORN_LOG" >&2 || true
      exit 1
    fi
    health_code="$(curl -sk -o /dev/null -w "%{http_code}" "$health_url" || true)"
    if [[ "$health_code" == "200" ]]; then
      started=1
      break
    fi
    sleep 1
  done

  if [[ "$started" -ne 1 ]]; then
    echo "ERROR: shared Hypercorn did not become healthy within ${startup_timeout_secs}s" >&2
    echo "See log: $SHARED_HYPERCORN_LOG" >&2
    tail -n 120 "$SHARED_HYPERCORN_LOG" >&2 || true
    exit 1
  fi
}

stop_shared_server() {
  if [[ -n "${SHARED_HYPERCORN_PID:-}" ]]; then
    kill "$SHARED_HYPERCORN_PID" >/dev/null 2>&1 || true
    wait "$SHARED_HYPERCORN_PID" >/dev/null 2>&1 || true
    SHARED_HYPERCORN_PID=""
  fi
  if [[ -n "${SHARED_HYPERCORN_LOG:-}" && -f "${SHARED_HYPERCORN_LOG:-}" ]]; then
    rm -f "$SHARED_HYPERCORN_LOG" >/dev/null 2>&1 || true
    SHARED_HYPERCORN_LOG=""
  fi
}

teardown_runtime() {
  stop_shared_server
  if [[ -n "${EPHEMERAL_PG_CTL_BIN:-}" && -n "${EPHEMERAL_PGDATA:-}" && -d "${EPHEMERAL_PGDATA:-}" ]]; then
    "$EPHEMERAL_PG_CTL_BIN" -D "$EPHEMERAL_PGDATA" -m fast stop >/dev/null 2>&1 || true
  fi
  if [[ -n "${EPHEMERAL_TMP_DIR:-}" && -d "${EPHEMERAL_TMP_DIR:-}" ]]; then
    rm -rf "$EPHEMERAL_TMP_DIR" >/dev/null 2>&1 || true
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
ACP_RUNNER="$REPO_ROOT/.codex/skills/acp-http-e2e-tester/scripts/run_acp_http_e2e.sh"
WEB_RUNNER="$REPO_ROOT/mugen_test/assets/e2e_specs/web/run_web_http_e2e.sh"
ACP_INVITE_RUNNER="$REPO_ROOT/mugen_test/assets/e2e_specs/acp/run_acp_invitation_redeem_e2e.sh"

PRINT_CONFIG=0
ONLY_FILTER=""
CONTINUE_ON_ERROR=0
SUITE="full"
SERVER_MODE="shared"
USE_EPHEMERAL_DB=1

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
    --suite)
      SUITE="$2"
      if [[ "$SUITE" != "full" && "$SUITE" != "smoke" ]]; then
        echo "ERROR: --suite must be one of: full, smoke" >&2
        exit 1
      fi
      shift 2
      ;;
    --server-mode)
      SERVER_MODE="$2"
      if [[ "$SERVER_MODE" != "shared" && "$SERVER_MODE" != "isolated" ]]; then
        echo "ERROR: --server-mode must be one of: shared, isolated" >&2
        exit 1
      fi
      shift 2
      ;;
    --continue-on-error)
      CONTINUE_ON_ERROR=1
      shift
      ;;
    --ephemeral-db)
      USE_EPHEMERAL_DB=1
      shift
      ;;
    --no-ephemeral-db)
      USE_EPHEMERAL_DB=0
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
require_cmd curl
require_cmd sed
require_cmd mktemp

if [[ ! -x "$ACP_RUNNER" ]]; then
  echo "ERROR: runner not found or not executable: $ACP_RUNNER" >&2
  exit 1
fi

if [[ ! -x "$WEB_RUNNER" ]]; then
  echo "ERROR: runner not found or not executable: $WEB_RUNNER" >&2
  exit 1
fi

if [[ ! -x "$ACP_INVITE_RUNNER" ]]; then
  echo "ERROR: runner not found or not executable: $ACP_INVITE_RUNNER" >&2
  exit 1
fi

E2E_PYTHON_BIN="$(resolve_python_bin)"
E2E_PYTHONPATH="$REPO_ROOT"
if [[ -n "${PYTHONPATH:-}" ]]; then
  E2E_PYTHONPATH="$REPO_ROOT:$PYTHONPATH"
fi
E2E_CONFIG_FILE="$(resolve_e2e_config_file)"
if [[ ! -f "$E2E_CONFIG_FILE" ]]; then
  echo "ERROR: e2e config file not found: $E2E_CONFIG_FILE" >&2
  echo "Set MUGEN_E2E_CONFIG_FILE (or MUGEN_CONFIG_FILE) or create mugen.e2e.toml." >&2
  exit 1
fi

trap teardown_runtime EXIT

if [[ "$USE_EPHEMERAL_DB" -eq 1 && "$PRINT_CONFIG" -ne 1 ]]; then
  setup_ephemeral_db "$E2E_CONFIG_FILE" "$E2E_PYTHON_BIN"
  E2E_CONFIG_FILE="$EPHEMERAL_CONFIG_FILE"
fi

echo "E2E CONFIG: $E2E_CONFIG_FILE"
echo "E2E SUITE: $SUITE"
echo "E2E SERVER MODE: $SERVER_MODE"

HYPERCORN_CMD="$(shell_join_quoted env "PYTHONPATH=$E2E_PYTHONPATH" "MUGEN_CONFIG_FILE=$E2E_CONFIG_FILE" "$E2E_PYTHON_BIN" -m hypercorn --bind 127.0.0.1:8081 quartman)"
HYPERCORN_CMD_ESCAPED="$(escape_sed_replacement "$HYPERCORN_CMD")"

declare -a FULL_SPECS=(
  "mugen_test/assets/e2e_specs/acp/acp-tenant-invitation-redeem.template.json"
  "mugen_test/assets/e2e_specs/acp/acp-e2e-dedup-ledger.template.json"
  "mugen_test/assets/e2e_specs/acp/acp-e2e-schema-registry.template.json"
  "mugen_test/assets/e2e_specs/audit/audit-e2e-correlation-observability.template.json"
  "mugen_test/assets/e2e_specs/ops_case/ops-case-e2e-lifecycle.template.json"
  "mugen_test/assets/e2e_specs/ops_sla/ops-sla-e2e-clock-lifecycle.template.json"
  "mugen_test/assets/e2e_specs/ops_workflow/ops-workflow-e2e-definition-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_workflow/ops-workflow-e2e-decision-request.template.json"
  "mugen_test/assets/e2e_specs/ops_metering/ops-metering-e2e-meter-definition-smoke.template.json"
  "mugen_test/assets/e2e_specs/billing/billing-e2e-account-product-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_vpn/ops-vpn-e2e-vendor-lifecycle.template.json"
  "mugen_test/assets/e2e_specs/knowledge_pack/knowledge-pack-e2e-pack-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_governance/ops-governance-e2e-policy-evaluate.template.json"
  "mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-aggregation.template.json"
  "mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-snapshot.template.json"
  "mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-snapshot-verify.template.json"
  "mugen_test/assets/e2e_specs/ops_reporting/ops-reporting-e2e-export.template.json"
  "mugen_test/assets/e2e_specs/ops_connector/ops-connector-e2e-http-json.template.json"
  "mugen_test/assets/e2e_specs/channel_orchestration/channel-orchestration-e2e-conversation.template.json"
  "mugen_test/assets/e2e_specs/channel_orchestration/channel-orchestration-e2e-blocklist.template.json"
  "mugen_test/assets/e2e_specs/web/web-e2e-rest-sse-core.template.json"
)

declare -a SMOKE_SPECS=(
  "mugen_test/assets/e2e_specs/acp/acp-e2e-dedup-ledger.template.json"
  "mugen_test/assets/e2e_specs/acp/acp-tenant-invitation-redeem.template.json"
  "mugen_test/assets/e2e_specs/ops_workflow/ops-workflow-e2e-definition-smoke.template.json"
  "mugen_test/assets/e2e_specs/ops_metering/ops-metering-e2e-meter-definition-smoke.template.json"
  "mugen_test/assets/e2e_specs/billing/billing-e2e-account-product-smoke.template.json"
  "mugen_test/assets/e2e_specs/knowledge_pack/knowledge-pack-e2e-pack-smoke.template.json"
  "mugen_test/assets/e2e_specs/web/web-e2e-rest-sse-core.template.json"
)

declare -a SPECS=()
if [[ "$SUITE" == "smoke" ]]; then
  SPECS=("${SMOKE_SPECS[@]}")
else
  SPECS=("${FULL_SPECS[@]}")
fi

render_spec() {
  local template="$1"
  local output="$2"
  local run_id="$3"
  local hypercorn_cmd_escaped="$4"

  local run_id_flat
  run_id_flat="$(echo "$run_id" | tr -cd '[:alnum:]_')"

  local case_title tracked_ref wf_key meter_code vendor_code
  local pack_key policy_code sender_key block_sender_key reporting_code snap_note
  local billing_account_code billing_product_code web_conversation_id web_text
  local acp_username acp_password invitee_email
  local acp_username_escaped acp_password_escaped invitee_email_escaped

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
  web_conversation_id="web_conv_${run_id_flat}"
  web_text="Web e2e message ${run_id}"
  acp_username="${ACP_E2E_USERNAME:-admin}"
  acp_password="${ACP_E2E_PASSWORD:-aDmin,123}"
  invitee_email="invitee.${run_id_flat}@example.com"
  acp_username_escaped="$(escape_sed_replacement "$acp_username")"
  acp_password_escaped="$(escape_sed_replacement "$acp_password")"
  invitee_email_escaped="$(escape_sed_replacement "$invitee_email")"

  sed \
    -e "s|__HYPERCORN_CMD__|${hypercorn_cmd_escaped}|g" \
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
    -e "s|__WEB_CONVERSATION_ID__|${web_conversation_id}|g" \
    -e "s|__WEB_TEXT__|${web_text}|g" \
    -e "s|__ACP_USERNAME__|${acp_username_escaped}|g" \
    -e "s|__ACP_PASSWORD__|${acp_password_escaped}|g" \
    -e "s|__INVITEE_EMAIL__|${invitee_email_escaped}|g" \
    "$template" > "$output"
}

RUNNER_ARGS=()
if [[ "$PRINT_CONFIG" -eq 1 ]]; then
  RUNNER_ARGS+=(--print-config)
fi

pass_count=0
fail_count=0
skip_count=0
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
  render_spec "$spec_path" "$rendered_spec" "$run_id" "$HYPERCORN_CMD_ESCAPED"

  echo
  echo "=== RUNNING: $spec_rel ==="
  echo "rendered: $rendered_spec"

  runner="$ACP_RUNNER"
  declare -a runner_extra_env=()
  use_shared_server_for_runner=0
  if [[ "$spec_rel" == *"/web/"* ]]; then
    runner="$WEB_RUNNER"
  elif [[ "$spec_rel" == *"/acp/acp-tenant-invitation-redeem.template.json" ]]; then
    runner="$ACP_INVITE_RUNNER"
  fi

  if [[ "$SERVER_MODE" == "shared" && "$PRINT_CONFIG" -ne 1 && "$runner" != "$ACP_INVITE_RUNNER" ]]; then
    use_shared_server_for_runner=1
    start_shared_server
  elif [[ "$SERVER_MODE" == "shared" && "$PRINT_CONFIG" -ne 1 && "$runner" == "$ACP_INVITE_RUNNER" ]]; then
    # Invitation flow owns SMTP + Hypercorn lifecycle and must run isolated.
    stop_shared_server
  fi

  if [[ "$use_shared_server_for_runner" -eq 1 && "$runner" == "$ACP_RUNNER" ]]; then
    runner_extra_env=("ACP_E2E_EXTERNAL_SERVER=1")
  elif [[ "$use_shared_server_for_runner" -eq 1 && "$runner" == "$WEB_RUNNER" ]]; then
    runner_extra_env=("WEB_E2E_EXTERNAL_SERVER=1")
  fi

  if env \
    MUGEN_E2E_CONFIG_FILE="$E2E_CONFIG_FILE" \
    MUGEN_CONFIG_FILE="$E2E_CONFIG_FILE" \
    "${runner_extra_env[@]}" \
    bash "$runner" --spec "$rendered_spec" "${RUNNER_ARGS[@]}"; then
    ((pass_count += 1))
  else
    run_exit_code="$?"
    if [[ "$run_exit_code" -eq 2 ]]; then
      ((skip_count += 1))
      echo "SKIPPED: $spec_rel"
    else
      ((fail_count += 1))
      if [[ "$CONTINUE_ON_ERROR" -ne 1 ]]; then
        rm -f "$rendered_spec"
        break
      fi
    fi
  fi

  rm -f "$rendered_spec"
  ((index += 1))
done

echo
echo "SUMMARY: passed=$pass_count failed=$fail_count skipped=$skip_count"
if [[ "$fail_count" -gt 0 ]]; then
  exit 1
fi
