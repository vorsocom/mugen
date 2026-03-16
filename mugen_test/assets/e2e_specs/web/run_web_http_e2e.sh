#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run web HTTP plugin e2e checks from a JSON spec.

Usage:
  run_web_http_e2e.sh --spec <path> [--print-config]

Exit codes:
  0  pass
  1  fail
  2  skipped (web unavailable in non-strict mode)

Strict mode:
  - Enabled automatically when CI=true
  - Can be enabled manually with WEB_E2E_STRICT=1

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

env_truthy() {
  local value="${1:-}"
  case "${value,,}" in
    1|true|yes|on)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

resolve_strict_mode() {
  local strict=0
  if [[ "${CI:-}" == "true" ]]; then
    strict=1
  fi

  if env_truthy "${WEB_E2E_STRICT:-0}"; then
    strict=1
  fi

  echo "$strict"
}

require_non_empty_string() {
  local value="$1"
  local field_name="$2"
  if [[ -z "$value" || "$value" == "null" ]]; then
    echo "ERROR: $field_name is required" >&2
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

require_http_code() {
  local value="$1"
  local field_name="$2"
  if [[ ! "$value" =~ ^[0-9]{3}$ ]]; then
    echo "ERROR: $field_name must be a 3-digit HTTP code (got: $value)" >&2
    exit 1
  fi
}

contains_code() {
  local code="$1"
  shift
  local candidate
  for candidate in "$@"; do
    if [[ "$candidate" == "$code" ]]; then
      return 0
    fi
  done
  return 1
}

parse_sse_events_file() {
  local sse_body_file="$1"
  jq -Rs '
    gsub("\r"; "")
    | split("\n\n")
    | map(select(length > 0))
    | map(
        reduce (split("\n")[]) as $line (
          {"id": null, "event": null, "data_lines": []};
          if ($line | startswith("id:")) then
            .id = ($line | sub("^id:[[:space:]]*"; ""))
          elif ($line | startswith("event:")) then
            .event = ($line | sub("^event:[[:space:]]*"; ""))
          elif ($line | startswith("data:")) then
            .data_lines += [($line | sub("^data:[[:space:]]*"; ""))]
          else
            .
          end
        )
        | .data_raw = (.data_lines | join("\n"))
        | .data = (try (.data_raw | fromjson) catch null)
        | del(.data_lines)
      )
    | map(select(.event != null and .event != ""))
  ' "$sse_body_file"
}

extract_http_status() {
  local headers_file="$1"
  awk '/^HTTP/{status=$2} END{print status}' "$headers_file"
}

extract_content_type() {
  local headers_file="$1"
  local value
  value="$(grep -i '^content-type:' "$headers_file" | tail -n 1 || true)"
  value="${value%$'\r'}"
  value="${value#*:}"
  value="${value#"${value%%[![:space:]]*}"}"
  echo "$value"
}

run_sse_request() {
  local output_headers_file="$1"
  local output_body_file="$2"
  shift 2

  local curl_rc=0
  curl -sk --no-buffer --max-time "$stream_timeout_secs" \
    -D "$output_headers_file" \
    -o "$output_body_file" \
    "$@" || curl_rc=$?

  if [[ "$curl_rc" -ne 0 && "$curl_rc" -ne 28 ]]; then
    echo "ERROR: SSE request failed (curl rc=$curl_rc)" >&2
    return 1
  fi
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

strict_mode="$(resolve_strict_mode)"
external_server=0
if env_truthy "${WEB_E2E_EXTERNAL_SERVER:-0}"; then
  external_server=1
fi

spawn_hypercorn="$(echo "$spec_json" | jq -r '.runtime.spawn_hypercorn // false')"
hypercorn_cmd="$(echo "$spec_json" | jq -r '.runtime.hypercorn_cmd // empty')"
health_url="$(echo "$spec_json" | jq -r '.runtime.health_url // (.auth.base_url + "/auth/.well-known/jwks.json")')"
startup_timeout_secs="$(echo "$spec_json" | jq -r '.runtime.startup_timeout_secs // 30')"

auth_base_url="$(echo "$spec_json" | jq -r '.auth.base_url // empty')"
auth_base_url="${auth_base_url%/}"
username="$(echo "$spec_json" | jq -r '.auth.username // empty')"
password="$(echo "$spec_json" | jq -r '.auth.password // empty')"

web_base_url="$(echo "$spec_json" | jq -r '.web.base_url // empty')"
web_base_url="${web_base_url%/}"

conversation_id="$(echo "$spec_json" | jq -r '.scenario.conversation_id // empty')"
message_text="$(echo "$spec_json" | jq -r '.scenario.text // empty')"
stream_timeout_secs="$(echo "$spec_json" | jq -r '.scenario.stream_timeout_secs // 12')"
client_message_id="e2e-${conversation_id}-$(date +%s)-$$"

required_ack_event="$(echo "$spec_json" | jq -r '.assertions.required_event_order[0] // "ack"')"
required_message_event="$(echo "$spec_json" | jq -r '.assertions.required_event_order[1] // "message"')"
message_create_expect_code="$(echo "$spec_json" | jq -r '.assertions.message_create_status // 202')"
unauth_expect_code="$(echo "$spec_json" | jq -r '.assertions.negative_statuses.unauthenticated_message // 401')"
missing_conversation_expect_code="$(echo "$spec_json" | jq -r '.assertions.negative_statuses.missing_conversation_id // 400')"
media_not_found_expect_code="$(echo "$spec_json" | jq -r '.assertions.negative_statuses.media_token_not_found // 404')"
availability_available_code="$(echo "$spec_json" | jq -r '.assertions.availability_status_available // 400')"
mapfile -t availability_unavailable_codes < <(
  echo "$spec_json" | jq -r '.assertions.availability_status_unavailable // [404, 501] | .[]'
)

require_positive_int "$startup_timeout_secs" "runtime.startup_timeout_secs"
require_positive_int "$stream_timeout_secs" "scenario.stream_timeout_secs"
require_non_empty_string "$auth_base_url" "auth.base_url"
require_non_empty_string "$username" "auth.username"
require_non_empty_string "$password" "auth.password"
require_non_empty_string "$web_base_url" "web.base_url"
require_non_empty_string "$conversation_id" "scenario.conversation_id"
require_non_empty_string "$message_text" "scenario.text"
require_non_empty_string "$required_ack_event" "assertions.required_event_order[0]"
require_non_empty_string "$required_message_event" "assertions.required_event_order[1]"
require_http_code "$message_create_expect_code" "assertions.message_create_status"
require_http_code "$unauth_expect_code" "assertions.negative_statuses.unauthenticated_message"
require_http_code "$missing_conversation_expect_code" "assertions.negative_statuses.missing_conversation_id"
require_http_code "$media_not_found_expect_code" "assertions.negative_statuses.media_token_not_found"
require_http_code "$availability_available_code" "assertions.availability_status_available"

if [[ "${#availability_unavailable_codes[@]}" -eq 0 ]]; then
  echo "ERROR: assertions.availability_status_unavailable must contain at least one status code" >&2
  exit 1
fi

for unavailable_code in "${availability_unavailable_codes[@]}"; do
  require_http_code "$unavailable_code" "assertions.availability_status_unavailable[]"
done

declare -a tmp_files=()

cleanup_server() {
  if [[ -n "${hypercorn_pid:-}" ]]; then
    kill "$hypercorn_pid" >/dev/null 2>&1 || true
    wait "$hypercorn_pid" >/dev/null 2>&1 || true
  fi

  if [[ "${#tmp_files[@]}" -gt 0 ]]; then
    rm -f "${tmp_files[@]}" >/dev/null 2>&1 || true
  fi
}
trap cleanup_server EXIT

echo "STRICT MODE: $strict_mode"

if [[ "$spawn_hypercorn" == "true" && "$external_server" -ne 1 ]]; then
  if [[ -z "$hypercorn_cmd" ]]; then
    echo "ERROR: runtime.hypercorn_cmd is required when runtime.spawn_hypercorn=true" >&2
    exit 1
  fi

  log_file="$(mktemp /tmp/web_http_e2e_hypercorn_XXXXXX.log)"
  tmp_files+=("$log_file")

  echo "SPAWN HYPERCORN: $hypercorn_cmd"
  bash -lc "$hypercorn_cmd" >"$log_file" 2>&1 &
  hypercorn_pid="$!"
  echo "HYPERCORN PID: $hypercorn_pid"

  started=0
  for _ in $(seq 1 "$startup_timeout_secs"); do
    if ! kill -0 "$hypercorn_pid" >/dev/null 2>&1; then
      echo "ERROR: Hypercorn process exited before becoming healthy." >&2
      echo "See log: $log_file" >&2
      tail -n 120 "$log_file" >&2 || true
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
    echo "ERROR: Hypercorn did not become healthy within ${startup_timeout_secs}s" >&2
    echo "See log: $log_file" >&2
    tail -n 120 "$log_file" >&2 || true
    exit 1
  fi
elif [[ "$spawn_hypercorn" == "true" && "$external_server" -eq 1 ]]; then
  echo "USING EXTERNAL SERVER: WEB_E2E_EXTERNAL_SERVER=1"
fi

jwks_out="$(mktemp /tmp/web_http_e2e_jwks_XXXXXX.json)"
tmp_files+=("$jwks_out")
jwks_code="$(curl -sk -o "$jwks_out" -w "%{http_code}" "$auth_base_url/auth/.well-known/jwks.json")"
echo "JWKS: $jwks_code"
if [[ "$jwks_code" != "200" ]]; then
  echo "ERROR: JWKS endpoint failed (HTTP $jwks_code)" >&2
  cat "$jwks_out" >&2
  exit 1
fi

login_payload="$(jq -cn --arg username "$username" --arg password "$password" '{Username:$username, Password:$password}')"
login_out="$(mktemp /tmp/web_http_e2e_login_XXXXXX.json)"
tmp_files+=("$login_out")
login_code="$(curl -sk -o "$login_out" -w "%{http_code}" \
  -H "Content-Type: application/json" \
  -X POST "$auth_base_url/auth/login" \
  -d "$login_payload")"
echo "LOGIN: $login_code"
if [[ "$login_code" != "200" ]]; then
  echo "ERROR: login failed (HTTP $login_code)" >&2
  cat "$login_out" >&2
  exit 1
fi

access_token="$(jq -r '.access_token // empty' "$login_out")"
if [[ -z "$access_token" ]]; then
  echo "ERROR: login response missing access_token" >&2
  cat "$login_out" >&2
  exit 1
fi

auth_header="Authorization: Bearer $access_token"

preflight_out="$(mktemp /tmp/web_http_e2e_preflight_XXXXXX.out)"
tmp_files+=("$preflight_out")
preflight_code="$(curl -sk -o "$preflight_out" -w "%{http_code}" \
  -H "$auth_header" \
  -X POST "$web_base_url/messages" \
  --data-urlencode "client_message_id=$client_message_id" \
  --data-urlencode "message_type=text" \
  --data-urlencode "text=availability-check")"
echo "PREFLIGHT WEB ENDPOINT: $preflight_code"

if [[ "$preflight_code" == "$availability_available_code" ]]; then
  :
elif contains_code "$preflight_code" "${availability_unavailable_codes[@]}"; then
  if [[ "$strict_mode" -eq 1 ]]; then
    echo "ERROR: web endpoint unavailable in strict mode (HTTP $preflight_code)." >&2
    cat "$preflight_out" >&2
    exit 1
  fi

  echo "SKIP: web endpoint unavailable (HTTP $preflight_code) in non-strict mode."
  exit 2
else
  echo "ERROR: unexpected web preflight status (HTTP $preflight_code)." >&2
  cat "$preflight_out" >&2
  exit 1
fi

negative_unauth_out="$(mktemp /tmp/web_http_e2e_negative_unauth_XXXXXX.out)"
tmp_files+=("$negative_unauth_out")
negative_unauth_code="$(curl -sk -o "$negative_unauth_out" -w "%{http_code}" \
  -X POST "$web_base_url/messages" \
  --data-urlencode "conversation_id=$conversation_id" \
  --data-urlencode "client_message_id=$client_message_id" \
  --data-urlencode "message_type=text" \
  --data-urlencode "text=$message_text")"
echo "NEGATIVE unauthenticated message: $negative_unauth_code"
if [[ "$negative_unauth_code" != "$unauth_expect_code" ]]; then
  echo "ERROR: unauthenticated POST /messages expected $unauth_expect_code got $negative_unauth_code" >&2
  cat "$negative_unauth_out" >&2
  exit 1
fi

negative_missing_conversation_out="$(mktemp /tmp/web_http_e2e_negative_missing_conversation_XXXXXX.out)"
tmp_files+=("$negative_missing_conversation_out")
negative_missing_conversation_code="$(curl -sk -o "$negative_missing_conversation_out" -w "%{http_code}" \
  -H "$auth_header" \
  -X POST "$web_base_url/messages" \
  --data-urlencode "client_message_id=$client_message_id" \
  --data-urlencode "message_type=text" \
  --data-urlencode "text=$message_text")"
echo "NEGATIVE missing conversation_id: $negative_missing_conversation_code"
if [[ "$negative_missing_conversation_code" != "$missing_conversation_expect_code" ]]; then
  echo "ERROR: missing conversation_id expected $missing_conversation_expect_code got $negative_missing_conversation_code" >&2
  cat "$negative_missing_conversation_out" >&2
  exit 1
fi

create_out="$(mktemp /tmp/web_http_e2e_create_XXXXXX.json)"
tmp_files+=("$create_out")
create_code="$(curl -sk -o "$create_out" -w "%{http_code}" \
  -H "$auth_header" \
  -X POST "$web_base_url/messages" \
  --data-urlencode "conversation_id=$conversation_id" \
  --data-urlencode "client_message_id=$client_message_id" \
  --data-urlencode "message_type=text" \
  --data-urlencode "text=$message_text")"
echo "CREATE MESSAGE: $create_code"
if [[ "$create_code" != "$message_create_expect_code" ]]; then
  echo "ERROR: message create expected $message_create_expect_code got $create_code" >&2
  cat "$create_out" >&2
  exit 1
fi

job_id="$(jq -r '.job_id // empty' "$create_out")"
if [[ -z "$job_id" ]]; then
  echo "ERROR: message create response missing job_id" >&2
  cat "$create_out" >&2
  exit 1
fi
echo "JOB ID: $job_id"

structured_attachment_path="$(mktemp /tmp/web_http_e2e_structured_attachment_XXXXXX.bin)"
tmp_files+=("$structured_attachment_path")
printf 'structured-attachment-payload' > "$structured_attachment_path"
structured_client_message_id="${client_message_id}-structured"
structured_parts_json="$(jq -cn --arg text "$message_text" '
  [
    {"type":"text","text":$text},
    {"type":"attachment","id":"a1","caption":"structured-e2e-caption"}
  ]
')"
structured_create_out="$(mktemp /tmp/web_http_e2e_create_structured_XXXXXX.json)"
tmp_files+=("$structured_create_out")
structured_create_code="$(curl -sk -o "$structured_create_out" -w "%{http_code}" \
  -H "$auth_header" \
  -X POST "$web_base_url/messages" \
  -F "conversation_id=$conversation_id" \
  -F "client_message_id=$structured_client_message_id" \
  -F "composition_mode=message_with_attachments" \
  -F "parts=$structured_parts_json" \
  -F "files[a1]=@${structured_attachment_path};type=application/octet-stream")"
echo "CREATE STRUCTURED MESSAGE: $structured_create_code"
if [[ "$structured_create_code" != "$message_create_expect_code" ]]; then
  echo "ERROR: structured message create expected $message_create_expect_code got $structured_create_code" >&2
  cat "$structured_create_out" >&2
  exit 1
fi
structured_job_id="$(jq -r '.job_id // empty' "$structured_create_out")"
if [[ -z "$structured_job_id" ]]; then
  echo "ERROR: structured message create response missing job_id" >&2
  cat "$structured_create_out" >&2
  exit 1
fi
echo "STRUCTURED JOB ID: $structured_job_id"

structured_negative_out="$(mktemp /tmp/web_http_e2e_negative_structured_empty_XXXXXX.out)"
tmp_files+=("$structured_negative_out")
structured_negative_client_message_id="${client_message_id}-structured-empty"
structured_negative_code="$(curl -sk -o "$structured_negative_out" -w "%{http_code}" \
  -H "$auth_header" \
  -X POST "$web_base_url/messages" \
  --data-urlencode "conversation_id=$conversation_id" \
  --data-urlencode "client_message_id=$structured_negative_client_message_id" \
  --data-urlencode "composition_mode=message_with_attachments" \
  --data-urlencode "parts=[]")"
echo "NEGATIVE structured empty payload: $structured_negative_code"
if [[ "$structured_negative_code" != "400" ]]; then
  echo "ERROR: structured empty payload expected 400 got $structured_negative_code" >&2
  cat "$structured_negative_out" >&2
  exit 1
fi

encoded_conversation_id="$(jq -rn --arg value "$conversation_id" '$value | @uri')"
events_url="$web_base_url/events?conversation_id=$encoded_conversation_id"

sse_headers_file="$(mktemp /tmp/web_http_e2e_sse_headers_XXXXXX.txt)"
sse_body_file="$(mktemp /tmp/web_http_e2e_sse_body_XXXXXX.txt)"
tmp_files+=("$sse_headers_file" "$sse_body_file")
run_sse_request "$sse_headers_file" "$sse_body_file" -H "$auth_header" "$events_url"

sse_status_code="$(extract_http_status "$sse_headers_file")"
sse_content_type="$(extract_content_type "$sse_headers_file")"
echo "SSE STREAM: status=$sse_status_code content_type=${sse_content_type:-<missing>}"
if [[ "$sse_status_code" != "200" ]]; then
  echo "ERROR: SSE stream expected HTTP 200 got $sse_status_code" >&2
  cat "$sse_body_file" >&2
  exit 1
fi

if [[ "${sse_content_type,,}" != *"text/event-stream"* ]]; then
  echo "ERROR: SSE stream missing text/event-stream content type" >&2
  cat "$sse_headers_file" >&2
  exit 1
fi

sse_events_json="$(parse_sse_events_file "$sse_body_file")"
ack_index="$(echo "$sse_events_json" | jq -r --arg event_name "$required_ack_event" --arg job_id "$job_id" '
  (to_entries | map(select(.value.event == $event_name and (.value.data.job_id // "") == $job_id)) | first | .key) // empty
')"
message_index="$(echo "$sse_events_json" | jq -r --arg event_name "$required_message_event" --arg job_id "$job_id" '
  (
    to_entries
    | map(
        select(
          .value.event == $event_name
          and (.value.data.job_id // "") == $job_id
          and (.value.data.message.type // "") == "text"
          and (((.value.data.message.content // "") | tostring | gsub("[[:space:]]+"; "")) | length > 0)
        )
      )
    | first
    | .key
  ) // empty
')"

if [[ ! "$ack_index" =~ ^[0-9]+$ ]]; then
  echo "ERROR: missing $required_ack_event event for job_id=$job_id" >&2
  echo "$sse_events_json" | jq . >&2
  exit 1
fi
if [[ ! "$message_index" =~ ^[0-9]+$ ]]; then
  echo "ERROR: missing $required_message_event event with non-empty text for job_id=$job_id" >&2
  echo "$sse_events_json" | jq . >&2
  exit 1
fi
if (( ack_index >= message_index )); then
  echo "ERROR: expected $required_ack_event before $required_message_event for job_id=$job_id" >&2
  echo "$sse_events_json" | jq . >&2
  exit 1
fi

ack_event_id="$(echo "$sse_events_json" | jq -r --arg event_name "$required_ack_event" --arg job_id "$job_id" '
  first(.[] | select(.event == $event_name and (.data.job_id // "") == $job_id) | .id) // empty
')"
message_event_id="$(echo "$sse_events_json" | jq -r --arg event_name "$required_message_event" --arg job_id "$job_id" '
  first(
    .[]
    | select(
      .event == $event_name
      and (.data.job_id // "") == $job_id
      and (.data.message.type // "") == "text"
      and (((.data.message.content // "") | tostring | gsub("[[:space:]]+"; "")) | length > 0)
    )
    | .id
  ) // empty
')"
echo "ASSERT EVENT ORDER: $required_ack_event(id=$ack_event_id) before $required_message_event(id=$message_event_id)"

replay_headers_file="$(mktemp /tmp/web_http_e2e_replay_headers_XXXXXX.txt)"
replay_body_file="$(mktemp /tmp/web_http_e2e_replay_body_XXXXXX.txt)"
tmp_files+=("$replay_headers_file" "$replay_body_file")
run_sse_request \
  "$replay_headers_file" \
  "$replay_body_file" \
  -H "$auth_header" \
  -H "Last-Event-ID: $ack_event_id" \
  "$events_url&last_event_id=0"

replay_status_code="$(extract_http_status "$replay_headers_file")"
replay_content_type="$(extract_content_type "$replay_headers_file")"
echo "REPLAY STREAM: status=$replay_status_code content_type=${replay_content_type:-<missing>}"
if [[ "$replay_status_code" != "200" ]]; then
  echo "ERROR: replay stream expected HTTP 200 got $replay_status_code" >&2
  cat "$replay_body_file" >&2
  exit 1
fi

if [[ "${replay_content_type,,}" != *"text/event-stream"* ]]; then
  echo "ERROR: replay stream missing text/event-stream content type" >&2
  cat "$replay_headers_file" >&2
  exit 1
fi

replay_events_json="$(parse_sse_events_file "$replay_body_file")"
if [[ "$(echo "$replay_events_json" | jq -r '
  def event_num:
    ((.id // "") | capture("(?<n>[0-9]+)$")? | .n | tonumber?);
  any(.[]; (event_num == 1))
')" == "true" ]]; then
  echo "ERROR: replay stream unexpectedly included event id=1" >&2
  echo "$replay_events_json" | jq . >&2
  exit 1
fi

if [[ "$(echo "$replay_events_json" | jq -r '
  def event_num:
    ((.id // "") | capture("(?<n>[0-9]+)$")? | .n | tonumber?);
  any(.[]; ((event_num // 0) > 1))
')" != "true" ]]; then
  echo "ERROR: replay stream did not include any event with id > 1" >&2
  echo "$replay_events_json" | jq . >&2
  exit 1
fi
echo "ASSERT REPLAY: event id=1 omitted and newer events returned"

negative_media_out="$(mktemp /tmp/web_http_e2e_negative_media_XXXXXX.out)"
tmp_files+=("$negative_media_out")
negative_media_code="$(curl -sk -o "$negative_media_out" -w "%{http_code}" \
  -H "$auth_header" \
  "$web_base_url/media/not-real-token")"
echo "NEGATIVE invalid media token: $negative_media_code"
if [[ "$negative_media_code" != "$media_not_found_expect_code" ]]; then
  echo "ERROR: invalid media token expected $media_not_found_expect_code got $negative_media_code" >&2
  cat "$negative_media_out" >&2
  exit 1
fi

echo "SUCCESS: web HTTP e2e checks passed"
