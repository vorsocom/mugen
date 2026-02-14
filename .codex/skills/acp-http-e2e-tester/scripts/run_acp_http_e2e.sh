#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run ACP HTTP plugin e2e checks from a JSON spec.

Usage:
  run_acp_http_e2e.sh --spec <path> [--print-config]

Requirements:
  - curl
  - jq
  - bash
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $cmd" >&2
    exit 1
  fi
}

replace_placeholders() {
  local json_payload="$1"
  local rv="$2"
  local eid="$3"
  local tid="$4"
  local uid="$5"

  echo "$json_payload" | jq -c \
    --arg rv "$rv" \
    --arg eid "$eid" \
    --arg tid "$tid" \
    --arg uid "$uid" '
      def repl:
        if type == "string" then
          gsub("__ROW_VERSION__"; $rv)
          | gsub("__ENTITY_ID__"; $eid)
          | gsub("__TENANT_ID__"; $tid)
          | gsub("__USER_ID__"; $uid)
        elif type == "array" then map(repl)
        elif type == "object" then with_entries(.value |= repl)
        else .
        end;
      repl
      | if (.RowVersion? | type) == "string" and (.RowVersion | test("^[0-9]+$"))
        then .RowVersion = (.RowVersion | tonumber)
        else .
        end
    '
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

require_cmd curl
require_cmd jq

spec_json="$(cat "$spec_path")"

if [[ "$print_config" -eq 1 ]]; then
  echo "$spec_json" | jq .
  exit 0
fi

base_url="$(echo "$spec_json" | jq -r '.base_url')"
username="$(echo "$spec_json" | jq -r '.credentials.username')"
password="$(echo "$spec_json" | jq -r '.credentials.password')"
entity_set="$(echo "$spec_json" | jq -r '.entity_set')"
create_payload="$(echo "$spec_json" | jq -c '.create_payload')"
lookup_field="$(echo "$spec_json" | jq -r '.lookup.field // "Title"')"
lookup_value="$(echo "$spec_json" | jq -r '.lookup.value // empty')"
status_field="$(echo "$spec_json" | jq -r '.status_field // "Status"')"

spawn_hypercorn="$(echo "$spec_json" | jq -r '.runtime.spawn_hypercorn // false')"
hypercorn_cmd="$(echo "$spec_json" | jq -r '.runtime.hypercorn_cmd // empty')"
health_url="$(echo "$spec_json" | jq -r '.runtime.health_url // (.base_url + "/auth/.well-known/jwks.json")')"
startup_timeout_secs="$(echo "$spec_json" | jq -r '.runtime.startup_timeout_secs // 30')"

if [[ -z "$base_url" || "$base_url" == "null" ]]; then
  echo "ERROR: base_url is required" >&2
  exit 1
fi
if [[ -z "$username" || "$username" == "null" || -z "$password" || "$password" == "null" ]]; then
  echo "ERROR: credentials.username and credentials.password are required" >&2
  exit 1
fi
if [[ -z "$entity_set" || "$entity_set" == "null" ]]; then
  echo "ERROR: entity_set is required" >&2
  exit 1
fi
if [[ -z "$create_payload" || "$create_payload" == "null" ]]; then
  echo "ERROR: create_payload is required" >&2
  exit 1
fi

cleanup_server() {
  if [[ -n "${hypercorn_pid:-}" ]]; then
    kill "$hypercorn_pid" >/dev/null 2>&1 || true
    wait "$hypercorn_pid" >/dev/null 2>&1 || true
  fi
}
trap cleanup_server EXIT

if [[ "$spawn_hypercorn" == "true" ]]; then
  if [[ -z "$hypercorn_cmd" ]]; then
    echo "ERROR: runtime.hypercorn_cmd is required when runtime.spawn_hypercorn=true" >&2
    exit 1
  fi
  log_file="/tmp/acp_http_e2e_hypercorn.log"
  echo "SPAWN HYPERCORN: $hypercorn_cmd"
  bash -lc "$hypercorn_cmd" >"$log_file" 2>&1 &
  hypercorn_pid="$!"
  echo "HYPERCORN PID: $hypercorn_pid"

  started=0
  for _ in $(seq 1 "$startup_timeout_secs"); do
    health_code="$(curl -sk -o /dev/null -w "%{http_code}" "$health_url" || true)"
    if [[ "$health_code" == "200" ]]; then
      started=1
      break
    fi
    sleep 1
  done
  if [[ "$started" -ne 1 ]]; then
    echo "ERROR: Hypercorn did not become healthy within ${startup_timeout_secs}s" >&2
    echo "See log: $log_file" >&2
    exit 1
  fi
fi

jwks_code="$(curl -sk -o /tmp/acp_http_e2e_jwks.json -w "%{http_code}" "$base_url/auth/.well-known/jwks.json")"
echo "JWKS: $jwks_code"
if [[ "$jwks_code" != "200" ]]; then
  echo "ERROR: jwks endpoint failed" >&2
  exit 1
fi

login_json="$(curl -sk -H "Content-Type: application/json" -X POST "$base_url/auth/login" -d "{\"Username\":\"$username\",\"Password\":\"$password\"}")"
access_token="$(echo "$login_json" | jq -r '.access_token // empty')"
user_id="$(echo "$login_json" | jq -r '.user_id // empty')"
if [[ -z "$access_token" || -z "$user_id" ]]; then
  echo "ERROR: login failed to return access_token/user_id" >&2
  echo "$login_json" >&2
  exit 1
fi
echo "LOGIN: 200"

auth_header="Authorization: Bearer $access_token"
tenant_id="$(echo "$spec_json" | jq -r '.tenant_id // empty')"
if [[ -z "$tenant_id" || "$tenant_id" == "null" ]]; then
  tenant_id="$(curl -sk -H "$auth_header" "$base_url/Tenants" | jq -r '.value[0].Id // empty')"
fi
if [[ -z "$tenant_id" ]]; then
  echo "ERROR: could not determine tenant_id" >&2
  exit 1
fi
echo "TENANT: $tenant_id"

create_code="$(curl -sk -o /tmp/acp_http_e2e_create.out -w "%{http_code}" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_id/$entity_set" \
  -d "$create_payload")"
echo "CREATE $entity_set: $create_code"
if [[ "$create_code" != "201" ]]; then
  echo "ERROR: create failed" >&2
  cat /tmp/acp_http_e2e_create.out >&2
  exit 1
fi

if [[ -z "$lookup_value" || "$lookup_value" == "null" ]]; then
  lookup_value="$(echo "$create_payload" | jq -r --arg f "$lookup_field" '.[$f] // empty')"
fi
if [[ -z "$lookup_value" ]]; then
  echo "ERROR: could not determine lookup.value; set lookup.value in spec" >&2
  exit 1
fi

entity_json="$(curl -sk -H "$auth_header" "$base_url/tenants/$tenant_id/$entity_set" \
  | jq -c --arg f "$lookup_field" --arg v "$lookup_value" '.value[] | select(.[$f] == $v)' \
  | tail -n1)"
entity_id="$(echo "$entity_json" | jq -r '.Id // empty')"
row_version="$(echo "$entity_json" | jq -r '.RowVersion // empty')"
if [[ -z "$entity_id" || -z "$row_version" ]]; then
  echo "ERROR: could not resolve created entity via lookup ${lookup_field}=${lookup_value}" >&2
  exit 1
fi
entity_status="$(echo "$entity_json" | jq -r --arg sf "$status_field" '.[$sf] // ""')"
echo "ENTITY ID: $entity_id | ROW_VERSION: $row_version | ${status_field}: $entity_status"

actions_count="$(echo "$spec_json" | jq -r '.actions | length')"
if [[ "$actions_count" -gt 0 ]]; then
  for i in $(seq 0 $((actions_count - 1))); do
    step="$(echo "$spec_json" | jq -c ".actions[$i]")"
    action_name="$(echo "$step" | jq -r '.name')"
    target="$(echo "$step" | jq -r '.target // "entity"')"
    expect_code="$(echo "$step" | jq -r '.expect_code // 204')"
    payload_template="$(echo "$step" | jq -c '.payload // {}')"
    payload="$(replace_placeholders "$payload_template" "$row_version" "$entity_id" "$tenant_id" "$user_id")"

    if [[ "$target" == "entity_set" ]]; then
      action_url="$base_url/tenants/$tenant_id/$entity_set/\$action/$action_name"
    else
      action_url="$base_url/tenants/$tenant_id/$entity_set/$entity_id/\$action/$action_name"
    fi

    code="$(curl -sk -o "/tmp/acp_http_e2e_action_${i}.out" -w "%{http_code}" \
      -H "$auth_header" -H "Content-Type: application/json" \
      -X POST "$action_url" -d "$payload")"
    echo "ACTION $action_name: $code"
    if [[ "$code" != "$expect_code" ]]; then
      echo "ERROR: action $action_name expected $expect_code got $code" >&2
      cat "/tmp/acp_http_e2e_action_${i}.out" >&2
      exit 1
    fi

    if [[ "$target" == "entity" ]]; then
      entity_json="$(curl -sk -H "$auth_header" "$base_url/tenants/$tenant_id/$entity_set/$entity_id")"
      row_version="$(echo "$entity_json" | jq -r '.RowVersion // empty')"
      entity_status="$(echo "$entity_json" | jq -r --arg sf "$status_field" '.[$sf] // ""')"
      echo "STATE AFTER $action_name: ROW_VERSION=$row_version ${status_field}=$entity_status"
    fi
  done
fi

expected_final_status="$(echo "$spec_json" | jq -r '.assertions.final_status // empty')"
if [[ -n "$expected_final_status" ]]; then
  entity_json="$(curl -sk -H "$auth_header" "$base_url/tenants/$tenant_id/$entity_set/$entity_id")"
  current_final_status="$(echo "$entity_json" | jq -r --arg sf "$status_field" '.[$sf] // ""')"
  echo "ASSERT FINAL STATUS: expected=$expected_final_status actual=$current_final_status"
  if [[ "$current_final_status" != "$expected_final_status" ]]; then
    echo "ERROR: final status mismatch" >&2
    exit 1
  fi
fi

expected_seq_count="$(echo "$spec_json" | jq -r '.assertions.expected_event_sequence | length // 0')"
if [[ "$expected_seq_count" -gt 0 ]]; then
  event_set="$(echo "$spec_json" | jq -r '.assertions.event_entity_set')"
  event_id_field="$(echo "$spec_json" | jq -r '.assertions.event_entity_id_field // "CaseId"')"
  event_type_field="$(echo "$spec_json" | jq -r '.assertions.event_type_field // "EventType"')"

  expected_seq="$(echo "$spec_json" | jq -r '.assertions.expected_event_sequence | join(",")')"
  actual_seq="$(curl -sk -H "$auth_header" "$base_url/tenants/$tenant_id/$event_set" \
    | jq -r --arg idf "$event_id_field" --arg id "$entity_id" --arg tf "$event_type_field" \
      '.value[] | select(.[$idf] == $id) | .[$tf]' \
    | paste -sd, -)"
  echo "ASSERT EVENT SEQUENCE: expected=$expected_seq actual=$actual_seq"
  if [[ "$actual_seq" != "$expected_seq" ]]; then
    echo "ERROR: event sequence mismatch" >&2
    exit 1
  fi
fi

neg_count="$(echo "$spec_json" | jq -r '.negative_creates | length // 0')"
if [[ "$neg_count" -gt 0 ]]; then
  for i in $(seq 0 $((neg_count - 1))); do
    step="$(echo "$spec_json" | jq -c ".negative_creates[$i]")"
    name="$(echo "$step" | jq -r '.name // empty')"
    if [[ -z "$name" ]]; then
      name="negative_${i}"
    fi
    set_name="$(echo "$step" | jq -r '.entity_set')"
    expect_code="$(echo "$step" | jq -r '.expect_code')"
    payload_template="$(echo "$step" | jq -c '.payload // {}')"
    payload="$(replace_placeholders "$payload_template" "$row_version" "$entity_id" "$tenant_id" "$user_id")"

    code="$(curl -sk -o "/tmp/acp_http_e2e_negative_${i}.out" -w "%{http_code}" \
      -H "$auth_header" -H "Content-Type: application/json" \
      -X POST "$base_url/tenants/$tenant_id/$set_name" -d "$payload")"
    echo "NEGATIVE CREATE $name: $code"
    if [[ "$code" != "$expect_code" ]]; then
      echo "ERROR: negative create $name expected $expect_code got $code" >&2
      cat "/tmp/acp_http_e2e_negative_${i}.out" >&2
      exit 1
    fi
  done
fi

pos_count="$(echo "$spec_json" | jq -r '.positive_creates | length // 0')"
if [[ "$pos_count" -gt 0 ]]; then
  for i in $(seq 0 $((pos_count - 1))); do
    step="$(echo "$spec_json" | jq -c ".positive_creates[$i]")"
    name="$(echo "$step" | jq -r '.name // empty')"
    if [[ -z "$name" ]]; then
      name="positive_${i}"
    fi
    set_name="$(echo "$step" | jq -r '.entity_set')"
    expect_code="$(echo "$step" | jq -r '.expect_code // 201')"
    payload_template="$(echo "$step" | jq -c '.payload // {}')"
    payload="$(replace_placeholders "$payload_template" "$row_version" "$entity_id" "$tenant_id" "$user_id")"

    code="$(curl -sk -o "/tmp/acp_http_e2e_positive_${i}.out" -w "%{http_code}" \
      -H "$auth_header" -H "Content-Type: application/json" \
      -X POST "$base_url/tenants/$tenant_id/$set_name" -d "$payload")"
    echo "POSITIVE CREATE $name: $code"
    if [[ "$code" != "$expect_code" ]]; then
      echo "ERROR: positive create $name expected $expect_code got $code" >&2
      cat "/tmp/acp_http_e2e_positive_${i}.out" >&2
      exit 1
    fi
  done
fi

echo "SUCCESS: ACP HTTP e2e checks passed"
