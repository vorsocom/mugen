#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run ACP invitation redeem e2e checks with SMTP token capture.

Usage:
  run_acp_invitation_redeem_e2e.sh --spec <path> [--print-config]

Requirements:
  - curl
  - jq
  - bash
  - python (or set ACP_E2E_PYTHON_BIN)

Config source resolution order:
  1. MUGEN_E2E_CONFIG_FILE
  2. MUGEN_CONFIG_FILE
  3. mugen.e2e.toml (repository root)
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
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

  echo "ERROR: could not find a usable python interpreter." >&2
  echo "Set ACP_E2E_PYTHON_BIN to a valid interpreter path." >&2
  exit 1
}

line_count() {
  local file_path="$1"
  if [[ ! -f "$file_path" ]]; then
    echo "0"
    return
  fi
  wc -l < "$file_path" | tr -d '[:space:]'
}

extract_token_for_recipient_since() {
  local capture_file="$1"
  local recipient_email="$2"
  local after_line="$3"
  local python_bin="$4"

  "$python_bin" - "$capture_file" "$recipient_email" "$after_line" <<'PY'
import json
import re
import sys
from email import policy
from email.parser import Parser
from urllib.parse import parse_qs, urlparse

capture_file = sys.argv[1]
recipient_email = sys.argv[2].strip().lower()
after_line = int(sys.argv[3])

token_value = ""

try:
    with open(capture_file, "r", encoding="utf8") as handle:
        for idx, line in enumerate(handle, start=1):
            if idx <= after_line:
                continue
            line = line.strip()
            if not line:
                continue

            record = json.loads(line)
            recipients = [
                str(x).strip().lower().lstrip("<").rstrip(">")
                for x in record.get("rcpt_to", [])
            ]
            if recipient_email not in recipients:
                continue

            raw_message = str(record.get("data", ""))
            message = Parser(policy=policy.default).parsestr(raw_message)

            if message.is_multipart():
                body_parts = []
                for part in message.walk():
                    if part.get_content_type() == "text/plain":
                        content = part.get_content()
                        if not isinstance(content, str):
                            content = str(content)
                        body_parts.append(content)
                body = "\n".join(body_parts)
            else:
                content = message.get_content()
                body = content if isinstance(content, str) else str(content)

            match = re.search(r"InviteUrl:\s*(\S+)", body)
            if match is None:
                continue

            invite_url = match.group(1).strip()
            tokens = parse_qs(urlparse(invite_url).query).get("token", [])
            if tokens:
                token_value = tokens[0]
except (OSError, json.JSONDecodeError):
    pass

if token_value:
    print(token_value)
    raise SystemExit(0)

raise SystemExit(1)
PY
}

wait_for_token_for_recipient() {
  local capture_file="$1"
  local recipient_email="$2"
  local after_line="$3"
  local python_bin="$4"
  local timeout_secs="${5:-10}"

  local attempts=$((timeout_secs * 4))
  local token
  for _ in $(seq 1 "$attempts"); do
    if token="$(extract_token_for_recipient_since \
      "$capture_file" "$recipient_email" "$after_line" "$python_bin")"; then
      echo "$token"
      return 0
    fi
    sleep 0.25
  done

  return 1
}

spec_path=""
print_config=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec)
      spec_path="$2"
      shift 2
      ;;
    --print-config)
      print_config=1
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

if [[ -z "$spec_path" ]]; then
  echo "ERROR: --spec is required" >&2
  usage
  exit 1
fi

if [[ ! -f "$spec_path" ]]; then
  echo "ERROR: spec file not found: $spec_path" >&2
  exit 1
fi

require_cmd bash
require_cmd curl
require_cmd jq
require_cmd mktemp

python_bin="$(resolve_python_bin)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
SMTP_SINK="$SCRIPT_DIR/smtp_sink.py"
if [[ ! -f "$SMTP_SINK" ]]; then
  echo "ERROR: SMTP sink script not found: $SMTP_SINK" >&2
  exit 1
fi

resolve_repo_path() {
  local candidate="$1"
  if [[ "$candidate" = /* ]]; then
    echo "$candidate"
  else
    echo "$REPO_ROOT/$candidate"
  fi
}

resolve_source_config_file() {
  if [[ -n "${MUGEN_E2E_CONFIG_FILE:-}" ]]; then
    resolve_repo_path "$MUGEN_E2E_CONFIG_FILE"
    return
  fi

  if [[ -n "${MUGEN_CONFIG_FILE:-}" ]]; then
    resolve_repo_path "$MUGEN_CONFIG_FILE"
    return
  fi

  echo "$REPO_ROOT/mugen.e2e.toml"
}

spec_json="$(cat "$spec_path")"
if [[ "$print_config" -eq 1 ]]; then
  echo "$spec_json" | jq .
  exit 0
fi

base_url="$(echo "$spec_json" | jq -r '.base_url // empty')"
base_url="${base_url%/}"
username="$(echo "$spec_json" | jq -r '.credentials.username // empty')"
password="$(echo "$spec_json" | jq -r '.credentials.password // empty')"
tenant_id="$(echo "$spec_json" | jq -r '.tenant_id // empty')"
if [[ "$tenant_id" == "null" ]]; then
  tenant_id=""
fi
invitee_email="$(echo "$spec_json" | jq -r '.create_payload.Email // empty')"
health_url="$(echo "$spec_json" | jq -r \
  '.runtime.health_url // (.base_url + "/auth/.well-known/jwks.json")')"
startup_timeout_secs="$(echo "$spec_json" | jq -r \
  '.runtime.startup_timeout_secs // 30')"

if [[ -z "$base_url" || "$base_url" == "null" ]]; then
  echo "ERROR: base_url is required in spec." >&2
  exit 1
fi
if [[ -z "$username" || "$username" == "null" ]]; then
  echo "ERROR: credentials.username is required in spec." >&2
  exit 1
fi
if [[ -z "$password" || "$password" == "null" ]]; then
  echo "ERROR: credentials.password is required in spec." >&2
  exit 1
fi
if [[ -z "$invitee_email" || "$invitee_email" == "null" ]]; then
  echo "ERROR: create_payload.Email is required in spec." >&2
  exit 1
fi
if [[ ! "$startup_timeout_secs" =~ ^[0-9]+$ || "$startup_timeout_secs" -le 0 ]]; then
  echo "ERROR: runtime.startup_timeout_secs must be a positive integer." >&2
  exit 1
fi

scenario_field() {
  local scenario_name="$1"
  local field_name="$2"
  echo "$spec_json" | jq -r \
    --arg name "$scenario_name" \
    --arg field "$field_name" \
    '.redeem_scenarios[] | select(.name == $name) | .[$field] // empty' \
    | tail -n 1
}

scenario_path() {
  local scenario_name="$1"
  local tenant_id_value="$2"
  local invitation_id_value="$3"
  local template
  template="$(scenario_field "$scenario_name" "path")"
  if [[ -z "$template" ]]; then
    echo ""
    return
  fi
  template="${template//__TENANT_ID__/$tenant_id_value}"
  template="${template//__ENTITY_ID__/$invitation_id_value}"
  echo "$template"
}

expect_redeem_success="$(scenario_field "redeem_success" "expect_code")"
expect_replay_conflict="$(scenario_field "redeem_replay_conflict" "expect_code")"
expect_expired_conflict="$(scenario_field "redeem_expired_conflict" "expect_code")"
expect_mismatch_forbidden="$(scenario_field \
  "redeem_email_mismatch_forbidden" "expect_code")"
expect_expired_status="$(scenario_field \
  "redeem_expired_conflict" "expect_status_after")"

for expected_code in \
  "$expect_redeem_success" \
  "$expect_replay_conflict" \
  "$expect_expired_conflict" \
  "$expect_mismatch_forbidden"; do
  if [[ ! "$expected_code" =~ ^[0-9]{3}$ ]]; then
    echo "ERROR: scenario expected HTTP code is missing or invalid." >&2
    exit 1
  fi
done

if [[ "$(scenario_field "redeem_success" "auth")" != "bearer_invitee" ]]; then
  echo "ERROR: redeem_success auth must be bearer_invitee." >&2
  exit 1
fi
if [[ "$(scenario_field "redeem_replay_conflict" "auth")" != "bearer_invitee" ]]; then
  echo "ERROR: redeem_replay_conflict auth must be bearer_invitee." >&2
  exit 1
fi
if [[ "$(scenario_field "redeem_expired_conflict" "auth")" != "bearer_invitee" ]]; then
  echo "ERROR: redeem_expired_conflict auth must be bearer_invitee." >&2
  exit 1
fi
if [[ "$(scenario_field "redeem_email_mismatch_forbidden" "auth")" \
  != "bearer_non_matching_user" ]]; then
  echo "ERROR: redeem_email_mismatch_forbidden auth must be bearer_non_matching_user." >&2
  exit 1
fi

run_id="$(date +%Y%m%d_%H%M%S)_$$"
run_id_flat="$(echo "$run_id" | tr -cd '[:alnum:]_')"

non_matching_email="nomatch_${run_id_flat}@example.com"
invitee_username="invitee_${run_id_flat}"
non_matching_username="nomatch_${run_id_flat}"
user_password="Invitee,123"

invite_base_url="${ACP_E2E_INVITE_BASE_URL:-https://acp-e2e.local/invite}"
invite_ttl_seconds="${ACP_E2E_INVITE_TTL_SECONDS:-2}"
if [[ ! "$invite_ttl_seconds" =~ ^[0-9]+$ || "$invite_ttl_seconds" -le 0 ]]; then
  echo "ERROR: ACP_E2E_INVITE_TTL_SECONDS must be a positive integer." >&2
  exit 1
fi

tmp_dir="$(mktemp -d /tmp/acp_invitation_redeem_e2e_XXXXXX)"
smtp_capture_file="$tmp_dir/smtp_capture.jsonl"
smtp_ready_file="$tmp_dir/smtp_ready.json"
smtp_log="$tmp_dir/smtp_sink.log"
hypercorn_log="$tmp_dir/hypercorn.log"
temp_config_file="$tmp_dir/mugen.e2e.toml"

hypercorn_pid=""
smtp_pid=""

cleanup() {
  if [[ -n "$hypercorn_pid" ]]; then
    kill "$hypercorn_pid" >/dev/null 2>&1 || true
    wait "$hypercorn_pid" >/dev/null 2>&1 || true
  fi
  if [[ -n "$smtp_pid" ]]; then
    kill "$smtp_pid" >/dev/null 2>&1 || true
    wait "$smtp_pid" >/dev/null 2>&1 || true
  fi
  if [[ -d "$tmp_dir" ]]; then
    rm -rf "$tmp_dir"
  fi
}
trap cleanup EXIT

echo "START SMTP SINK"
"$python_bin" "$SMTP_SINK" \
  --host 127.0.0.1 \
  --port 0 \
  --output "$smtp_capture_file" \
  --ready-file "$smtp_ready_file" >"$smtp_log" 2>&1 &
smtp_pid="$!"

smtp_ready=0
for _ in $(seq 1 100); do
  if [[ -f "$smtp_ready_file" ]]; then
    smtp_ready=1
    break
  fi
  if ! kill -0 "$smtp_pid" >/dev/null 2>&1; then
    echo "ERROR: SMTP sink exited before initialization." >&2
    cat "$smtp_log" >&2 || true
    exit 1
  fi
  sleep 0.1
done
if [[ "$smtp_ready" -ne 1 ]]; then
  echo "ERROR: SMTP sink did not signal readiness." >&2
  cat "$smtp_log" >&2 || true
  exit 1
fi

smtp_port="$(jq -r '.port // empty' "$smtp_ready_file")"
if [[ ! "$smtp_port" =~ ^[0-9]+$ || "$smtp_port" -le 0 ]]; then
  echo "ERROR: SMTP sink returned invalid port." >&2
  cat "$smtp_ready_file" >&2 || true
  exit 1
fi
echo "SMTP SINK PORT: $smtp_port"

source_config="$(resolve_source_config_file)"
if [[ ! -f "$source_config" ]]; then
  echo "ERROR: source config not found: $source_config" >&2
  echo "Set MUGEN_E2E_CONFIG_FILE (or MUGEN_CONFIG_FILE) or create mugen.e2e.toml." >&2
  exit 1
fi
echo "SOURCE CONFIG: $source_config"

"$python_bin" - "$source_config" "$temp_config_file" "$smtp_port" \
  "$invite_base_url" "$invite_ttl_seconds" <<'PY'
import sys

import tomlkit

source_path = sys.argv[1]
target_path = sys.argv[2]
smtp_port = int(sys.argv[3])
invite_base_url = sys.argv[4]
invite_ttl_seconds = int(sys.argv[5])

with open(source_path, "r", encoding="utf8") as handle:
    doc = tomlkit.parse(handle.read())

doc["mugen"]["modules"]["core"]["gateway"]["email"] = (
    "mugen.core.gateway.email.smtp:SMTPEmailGateway"
)

if "smtp" not in doc:
    doc["smtp"] = tomlkit.table()

smtp = doc["smtp"]
smtp["host"] = "127.0.0.1"
smtp["port"] = smtp_port
smtp["username"] = ""
smtp["password"] = ""
smtp["default_from"] = "noreply@example.com"
smtp["timeout_seconds"] = 10.0
smtp["use_ssl"] = False
smtp["starttls"] = False
smtp["starttls_required"] = False

doc["acp"]["tenant_invitation_ttl_seconds"] = invite_ttl_seconds
doc["acp"]["tenant_invitation_invite_base_url"] = invite_base_url

with open(target_path, "w", encoding="utf8") as handle:
    handle.write(tomlkit.dumps(doc))
PY

echo "START HYPERCORN"
pythonpath="$REPO_ROOT"
if [[ -n "${PYTHONPATH:-}" ]]; then
  pythonpath="$REPO_ROOT:$PYTHONPATH"
fi
env \
  PYTHONPATH="$pythonpath" \
  MUGEN_CONFIG_FILE="$temp_config_file" \
  "$python_bin" -m hypercorn --bind 127.0.0.1:8081 quartman \
  >"$hypercorn_log" 2>&1 &
hypercorn_pid="$!"
echo "HYPERCORN PID: $hypercorn_pid"

healthy=0
for _ in $(seq 1 "$startup_timeout_secs"); do
  if ! kill -0 "$hypercorn_pid" >/dev/null 2>&1; then
    echo "ERROR: Hypercorn exited before becoming healthy." >&2
    tail -n 120 "$hypercorn_log" >&2 || true
    exit 1
  fi
  health_code="$(curl -sk -o /dev/null -w "%{http_code}" "$health_url" || true)"
  if [[ "$health_code" == "200" ]]; then
    healthy=1
    break
  fi
  sleep 1
done
if [[ "$healthy" -ne 1 ]]; then
  echo "ERROR: Hypercorn did not become healthy within ${startup_timeout_secs}s." >&2
  tail -n 120 "$hypercorn_log" >&2 || true
  exit 1
fi
echo "HEALTH: 200"

login_user() {
  local in_username="$1"
  local in_password="$2"
  local output_file="$3"

  local payload
  payload="$(jq -cn \
    --arg username "$in_username" \
    --arg password "$in_password" \
    '{Username: $username, Password: $password}')"

  local code
  code="$(curl -sk \
    -o "$output_file" \
    -w "%{http_code}" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/auth/login" \
    -d "$payload")"
  if [[ "$code" != "200" ]]; then
    echo "ERROR: login failed for user=$in_username (HTTP $code)." >&2
    cat "$output_file" >&2 || true
    exit 1
  fi

  local token user_id
  token="$(jq -r '.access_token // empty' "$output_file")"
  user_id="$(jq -r '.user_id // empty' "$output_file")"
  if [[ -z "$token" || -z "$user_id" ]]; then
    echo "ERROR: login response missing token or user_id for user=$in_username." >&2
    cat "$output_file" >&2 || true
    exit 1
  fi

  echo "$token|$user_id"
}

admin_login="$(login_user "$username" "$password" "$tmp_dir/login_admin.json")"
admin_token="${admin_login%%|*}"
admin_user_id="${admin_login##*|}"
admin_auth_header="Authorization: Bearer $admin_token"
echo "LOGIN ADMIN: 200 user_id=$admin_user_id"

if [[ -z "$tenant_id" ]]; then
  tenant_id="$(curl -sk -H "$admin_auth_header" "$base_url/Tenants" \
    | jq -r '.value[0].Id // empty')"
fi

if [[ -z "$tenant_id" ]]; then
  resolve_tenant_id_by_slug() {
    local slug="$1"
    local tenant_result
    local resolved_tenant_id=""

    for _ in $(seq 1 20); do
      tenant_result="$(curl -sk -H "$admin_auth_header" "$base_url/Tenants")"
      resolved_tenant_id="$(echo "$tenant_result" | jq -r --arg slug "$slug" \
        '.value[] | select(.Slug == $slug) | .Id' | tail -n 1)"
      if [[ -n "$resolved_tenant_id" ]]; then
        echo "$resolved_tenant_id"
        return 0
      fi
      sleep 0.5
    done

    return 1
  }

  tenant_suffix="$(date +%Y%m%d%H%M%S)"
  tenant_slug="e2e-invite-${tenant_suffix}"
  tenant_payload="$(jq -cn \
    --arg suffix "$tenant_suffix" \
    --arg slug "$tenant_slug" \
    '{Name:("E2E Invite Tenant " + $suffix), Slug:$slug}')"
  tenant_create_code="$(curl -sk \
    -o "$tmp_dir/create_tenant.out" \
    -w "%{http_code}" \
    -H "$admin_auth_header" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/Tenants" \
    -d "$tenant_payload")"
  if [[ "$tenant_create_code" != "201" ]]; then
    echo "ERROR: tenant bootstrap failed (HTTP $tenant_create_code)." >&2
    cat "$tmp_dir/create_tenant.out" >&2 || true
    exit 1
  fi
  tenant_id="$(jq -r '.Id // empty' "$tmp_dir/create_tenant.out")"
  if [[ -z "$tenant_id" ]]; then
    if ! tenant_id="$(resolve_tenant_id_by_slug "$tenant_slug")"; then
      echo "ERROR: tenant bootstrap returned 201 but tenant lookup by slug failed." >&2
      cat "$tmp_dir/create_tenant.out" >&2 || true
      exit 1
    fi
  fi
fi

if [[ -z "$tenant_id" ]]; then
  echo "ERROR: could not resolve tenant_id." >&2
  exit 1
fi
echo "TENANT: $tenant_id"

provision_user() {
  local in_username="$1"
  local in_password="$2"
  local in_email="$3"
  local first_name="$4"
  local last_name="$5"
  local result_file="$6"

  local payload
  payload="$(jq -cn \
    --arg username "$in_username" \
    --arg password "$in_password" \
    --arg login_email "$in_email" \
    --arg first_name "$first_name" \
    --arg last_name "$last_name" \
    '{
      username: $username,
      password: $password,
      login_email: $login_email,
      first_name: $first_name,
      last_name: $last_name
    }')"

  local code
  code="$(curl -sk \
    -o "$result_file" \
    -w "%{http_code}" \
    -H "$admin_auth_header" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/Users/\$action/provision" \
    -d "$payload")"

  if [[ "$code" != "204" ]]; then
    echo "ERROR: user provision failed for $in_email (HTTP $code)." >&2
    cat "$result_file" >&2 || true
    exit 1
  fi
}

provision_user \
  "$invitee_username" \
  "$user_password" \
  "$invitee_email" \
  "Invitee" \
  "User" \
  "$tmp_dir/provision_invitee.out"
echo "PROVISION INVITEE: 204"

provision_user \
  "$non_matching_username" \
  "$user_password" \
  "$non_matching_email" \
  "No" \
  "Match" \
  "$tmp_dir/provision_non_matching.out"
echo "PROVISION NON-MATCHING: 204"

invitee_login="$(login_user \
  "$invitee_username" "$user_password" "$tmp_dir/login_invitee.json")"
invitee_token="${invitee_login%%|*}"
invitee_user_id="${invitee_login##*|}"
invitee_auth_header="Authorization: Bearer $invitee_token"
echo "LOGIN INVITEE: 200 user_id=$invitee_user_id"

non_matching_login="$(login_user \
  "$non_matching_username" "$user_password" "$tmp_dir/login_non_matching.json")"
non_matching_token="${non_matching_login%%|*}"
non_matching_user_id="${non_matching_login##*|}"
non_matching_auth_header="Authorization: Bearer $non_matching_token"
echo "LOGIN NON-MATCHING: 200 user_id=$non_matching_user_id"

resolve_invited_invitation_id() {
  local target_email="$1"
  local invitation_id

  for _ in $(seq 1 40); do
    invitation_id="$(curl -sk \
      -H "$admin_auth_header" \
      "$base_url/tenants/$tenant_id/TenantInvitations" \
      | jq -r --arg email "$target_email" \
        '.value | map(select(.Email == $email and .Status == "invited")) | last | .Id // empty')"
    if [[ -n "$invitation_id" ]]; then
      echo "$invitation_id"
      return 0
    fi
    sleep 0.25
  done
  return 1
}

create_invitation_for_email() {
  local target_email="$1"
  local result_file="$2"

  local before_line_count
  before_line_count="$(line_count "$smtp_capture_file")"

  local payload
  payload="$(jq -cn --arg email "$target_email" '{Email:$email}')"

  local code
  code="$(curl -sk \
    -o "$result_file" \
    -w "%{http_code}" \
    -H "$admin_auth_header" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/tenants/$tenant_id/TenantInvitations" \
    -d "$payload")"
  if [[ "$code" != "201" ]]; then
    echo "ERROR: invitation create failed for $target_email (HTTP $code)." >&2
    cat "$result_file" >&2 || true
    exit 1
  fi

  local created_invitation_id
  if ! created_invitation_id="$(resolve_invited_invitation_id "$target_email")"; then
    echo "ERROR: unable to resolve created invitation id for $target_email." >&2
    exit 1
  fi

  local token
  if ! token="$(wait_for_token_for_recipient \
    "$smtp_capture_file" "$target_email" "$before_line_count" "$python_bin" 12)"; then
    echo "ERROR: could not capture invitation token for $target_email." >&2
    cat "$smtp_capture_file" >&2 || true
    exit 1
  fi

  echo "$created_invitation_id|$token"
}

run_redeem_scenario() {
  local scenario_name="$1"
  local bearer_header="$2"
  local invitation_id="$3"
  local token_value="$4"

  local expect_code path
  expect_code="$(scenario_field "$scenario_name" "expect_code")"
  path="$(scenario_path "$scenario_name" "$tenant_id" "$invitation_id")"

  if [[ -z "$path" ]]; then
    echo "ERROR: scenario path missing for $scenario_name." >&2
    exit 1
  fi

  local payload
  payload="$(jq -cn --arg token "$token_value" '{Token:$token}')"

  local output_file code
  output_file="$tmp_dir/${scenario_name}.out"
  code="$(curl -sk \
    -o "$output_file" \
    -w "%{http_code}" \
    -H "$bearer_header" \
    -H "Content-Type: application/json" \
    -X POST "$base_url$path" \
    -d "$payload")"

  echo "SCENARIO $scenario_name: $code"
  if [[ "$code" != "$expect_code" ]]; then
    echo "ERROR: scenario $scenario_name expected $expect_code got $code." >&2
    cat "$output_file" >&2 || true
    exit 1
  fi
}

initial_invitation="$(create_invitation_for_email \
  "$invitee_email" "$tmp_dir/create_invitation_initial.out")"
initial_invitation_id="${initial_invitation%%|*}"
initial_token="${initial_invitation##*|}"
echo "INVITATION INITIAL: id=$initial_invitation_id"

run_redeem_scenario \
  "redeem_success" \
  "$invitee_auth_header" \
  "$initial_invitation_id" \
  "$initial_token"

run_redeem_scenario \
  "redeem_replay_conflict" \
  "$invitee_auth_header" \
  "$initial_invitation_id" \
  "$initial_token"

expired_invitation="$(create_invitation_for_email \
  "$invitee_email" "$tmp_dir/create_invitation_expired.out")"
expired_invitation_id="${expired_invitation%%|*}"
expired_token="${expired_invitation##*|}"
echo "INVITATION EXPIRED TARGET: id=$expired_invitation_id"

sleep_secs=$((invite_ttl_seconds + 1))
echo "WAIT FOR EXPIRY: ${sleep_secs}s"
sleep "$sleep_secs"

run_redeem_scenario \
  "redeem_expired_conflict" \
  "$invitee_auth_header" \
  "$expired_invitation_id" \
  "$expired_token"

if [[ -n "$expect_expired_status" ]]; then
  expired_status="$(curl -sk \
    -H "$admin_auth_header" \
    "$base_url/tenants/$tenant_id/TenantInvitations/$expired_invitation_id" \
    | jq -r '.Status // empty')"
  echo "ASSERT EXPIRED STATUS: expected=$expect_expired_status actual=$expired_status"
  if [[ "$expired_status" != "$expect_expired_status" ]]; then
    echo "ERROR: expired invitation status mismatch." >&2
    exit 1
  fi
fi

mismatch_invitation="$(create_invitation_for_email \
  "$invitee_email" "$tmp_dir/create_invitation_mismatch.out")"
mismatch_invitation_id="${mismatch_invitation%%|*}"
mismatch_token="${mismatch_invitation##*|}"
echo "INVITATION MISMATCH TARGET: id=$mismatch_invitation_id"

run_redeem_scenario \
  "redeem_email_mismatch_forbidden" \
  "$non_matching_auth_header" \
  "$mismatch_invitation_id" \
  "$mismatch_token"

echo "SUCCESS: ACP invitation redeem e2e checks passed"
