#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run Billing runtime status and archived catalog HTTP E2E checks.

Usage:
  run_billing_runtime_archive_e2e.sh --spec <path> [--print-config]

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

if [[ -z "$spec_path" || ! -f "$spec_path" ]]; then
  echo "ERROR: --spec must name an existing file." >&2
  exit 1
fi

require_cmd curl
require_cmd jq
require_cmd mktemp

spec_json="$(<"$spec_path")"
if [[ "$print_config" -eq 1 ]]; then
  echo "$spec_json" | jq .
  exit 0
fi

base_url="$(echo "$spec_json" | jq -r '.base_url // empty')"
username="$(echo "$spec_json" | jq -r '.credentials.username // empty')"
password="$(echo "$spec_json" | jq -r '.credentials.password // empty')"
billing_namespace="$(echo "$spec_json" | jq -r '.billing_namespace // empty')"
product_code="$(echo "$spec_json" | jq -r '.catalog.product_code // empty')"
price_code="$(echo "$spec_json" | jq -r '.catalog.price_code // empty')"
reader_username="$(echo "$spec_json" | jq -r '.catalog_reader.username // empty')"
reader_password="$(echo "$spec_json" | jq -r '.catalog_reader.password // empty')"
reader_email="$(echo "$spec_json" | jq -r '.catalog_reader.email // empty')"
basic_username="$(echo "$spec_json" | jq -r '.authenticated_only.username // empty')"
basic_password="$(echo "$spec_json" | jq -r '.authenticated_only.password // empty')"
basic_email="$(echo "$spec_json" | jq -r '.authenticated_only.email // empty')"
spawn_hypercorn="$(echo "$spec_json" | jq -r '.runtime.spawn_hypercorn // false')"
hypercorn_cmd="$(echo "$spec_json" | jq -r '.runtime.hypercorn_cmd // empty')"
health_url="$(echo "$spec_json" | jq -r '.runtime.health_url // empty')"
startup_timeout_secs="$(echo "$spec_json" | jq -r '.runtime.startup_timeout_secs // 30')"

for required_value in \
  "$base_url" \
  "$username" \
  "$password" \
  "$billing_namespace" \
  "$product_code" \
  "$price_code" \
  "$reader_username" \
  "$reader_password" \
  "$reader_email" \
  "$basic_username" \
  "$basic_password" \
  "$basic_email"; do
  if [[ -z "$required_value" ]]; then
    echo "ERROR: Billing runtime/archive spec is missing a required value." >&2
    exit 1
  fi
done

if [[ ! "$startup_timeout_secs" =~ ^[0-9]+$ || "$startup_timeout_secs" -le 0 ]]; then
  echo "ERROR: runtime.startup_timeout_secs must be a positive integer." >&2
  exit 1
fi

tmp_dir="$(mktemp -d /tmp/billing_runtime_archive_e2e_XXXXXX)"
hypercorn_pid=""

cleanup() {
  if [[ -n "$hypercorn_pid" ]]; then
    kill "$hypercorn_pid" >/dev/null 2>&1 || true
    wait "$hypercorn_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

external_server=0
if env_truthy "${ACP_E2E_EXTERNAL_SERVER:-0}"; then
  external_server=1
fi

if [[ "$spawn_hypercorn" == "true" && "$external_server" -ne 1 ]]; then
  if [[ -z "$hypercorn_cmd" ]]; then
    echo "ERROR: runtime.hypercorn_cmd is required." >&2
    exit 1
  fi
  echo "SPAWN HYPERCORN: $hypercorn_cmd"
  bash -lc "$hypercorn_cmd" >"$tmp_dir/hypercorn.log" 2>&1 &
  hypercorn_pid="$!"
elif [[ "$spawn_hypercorn" == "true" ]]; then
  echo "USING EXTERNAL SERVER: ACP_E2E_EXTERNAL_SERVER=1"
fi

healthy=0
for _ in $(seq 1 "$startup_timeout_secs"); do
  if [[ -n "$hypercorn_pid" ]] && ! kill -0 "$hypercorn_pid" >/dev/null 2>&1; then
    echo "ERROR: Hypercorn exited before becoming healthy." >&2
    tail -n 120 "$tmp_dir/hypercorn.log" >&2 || true
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
  echo "ERROR: Billing E2E server did not become healthy." >&2
  exit 1
fi
echo "HEALTH: 200"

expect_code() {
  local label="$1"
  local expected="$2"
  local output_file="$3"
  shift 3

  local actual
  actual="$(curl -sk -o "$output_file" -w "%{http_code}" "$@")"
  echo "$label: $actual" >&2
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: $label expected HTTP $expected, got $actual." >&2
    cat "$output_file" >&2 || true
    exit 1
  fi
}

login_user() {
  local in_username="$1"
  local in_password="$2"
  local output_file="$3"
  local payload
  payload="$(jq -cn \
    --arg username "$in_username" \
    --arg password "$in_password" \
    '{Username:$username, Password:$password}')"

  expect_code \
    "LOGIN $in_username" \
    200 \
    "$output_file" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/auth/login" \
    -d "$payload"

  local token user_id
  token="$(jq -r '.access_token // empty' "$output_file")"
  user_id="$(jq -r '.user_id // empty' "$output_file")"
  if [[ -z "$token" || -z "$user_id" ]]; then
    echo "ERROR: login response omitted token or user_id." >&2
    exit 1
  fi
  echo "$token|$user_id"
}

provision_user() {
  local in_username="$1"
  local in_password="$2"
  local in_email="$3"
  local output_file="$4"
  local payload
  payload="$(jq -cn \
    --arg username "$in_username" \
    --arg password "$in_password" \
    --arg email "$in_email" \
    '{
      Username:$username,
      Password:$password,
      LoginEmail:$email,
      FirstName:"Billing",
      LastName:"E2E"
    }')"

  expect_code \
    "PROVISION $in_username" \
    204 \
    "$output_file" \
    -H "$admin_auth_header" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/Users/\$action/provision" \
    -d "$payload"
}

expect_code \
  "RUNTIME EXTENSIONS UNAUTHENTICATED" \
  401 \
  "$tmp_dir/runtime_unauthenticated.json" \
  "$base_url/runtime/extensions"

admin_login="$(login_user "$username" "$password" "$tmp_dir/login_admin.json")"
admin_token="${admin_login%%|*}"
admin_user_id="${admin_login##*|}"
admin_auth_header="Authorization: Bearer $admin_token"
usd_currency_id="e5855e26-4070-517a-9291-f6ae40dfbf10"

expect_code \
  "GET USD CURRENCY" \
  200 \
  "$tmp_dir/usd_currency.json" \
  -H "$admin_auth_header" \
  "$base_url/BillingCurrencyDefinitions/$usd_currency_id"
usd_currency_rv="$(jq -r '.RowVersion // empty' "$tmp_dir/usd_currency.json")"
if [[ -z "$usd_currency_rv" ]]; then
  echo "ERROR: USD Currency Definition omitted RowVersion." >&2
  exit 1
fi
activate_currency_payload="$(jq -cn \
  --argjson row_version "$usd_currency_rv" \
  '{RowVersion:$row_version}')"
expect_code \
  "ACTIVATE USD CURRENCY" \
  204 \
  "$tmp_dir/activate_usd_currency.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingCurrencyDefinitions/$usd_currency_id/\$action/activate" \
  -d "$activate_currency_payload"

expect_code \
  "RUNTIME EXTENSIONS ADMIN" \
  200 \
  "$tmp_dir/runtime_extensions.json" \
  -H "$admin_auth_header" \
  "$base_url/runtime/extensions"
if ! jq -e '
  .value == (.value | sort_by(.token))
  and any(.value[];
    .token == "core.fw.billing"
    and .extension_type == "fw"
    and .configured == true
    and .enabled == true
    and .available == true
    and .status == "registered"
    and .reason == null)
' "$tmp_dir/runtime_extensions.json" >/dev/null; then
  echo "ERROR: runtime extension collection contract assertion failed." >&2
  exit 1
fi

expect_code \
  "RUNTIME BILLING DETAIL" \
  200 \
  "$tmp_dir/runtime_billing.json" \
  -H "$admin_auth_header" \
  "$base_url/runtime/extensions/core.fw.billing"
if ! jq -e '
  .token == "core.fw.billing"
  and .available == true
  and .status == "registered"
  and (has("error") | not)
  and (has("exception") | not)
' "$tmp_dir/runtime_billing.json" >/dev/null; then
  echo "ERROR: runtime Billing detail contract assertion failed." >&2
  exit 1
fi

product_payload="$(jq -cn \
  --arg code "$product_code" \
  '{Code:$code, Name:("Archived E2E " + $code)}')"
expect_code \
  "CREATE PRODUCT" \
  201 \
  "$tmp_dir/create_product.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingProducts" \
  -d "$product_payload"

expect_code \
  "LOOKUP ACTIVE PRODUCT" \
  200 \
  "$tmp_dir/active_product.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$filter=Code eq '$product_code'" \
  --data-urlencode "\$top=1"
product_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/active_product.json")"
product_pre_archive_rv="$(jq -r '.value[0].RowVersion // empty' "$tmp_dir/active_product.json")"
if [[ -z "$product_id" || -z "$product_pre_archive_rv" ]]; then
  echo "ERROR: active Product lookup omitted Id or RowVersion." >&2
  exit 1
fi
if ! jq -e '
  .value[0].DeletedAt == null
  and .value[0].IsArchived == false
  and (.value[0] | has("TenantId") | not)
' "$tmp_dir/active_product.json" >/dev/null; then
  echo "ERROR: active Product lifecycle assertion failed." >&2
  exit 1
fi

price_payload="$(jq -cn \
  --arg product_id "$product_id" \
  --arg code "$price_code" \
  --arg currency_definition_id "$usd_currency_id" \
  '{
    ProductId:$product_id,
    Code:$code,
    PriceType:"one_time",
    CurrencyDefinitionId:$currency_definition_id,
    UnitAmount:2500
  }')"
expect_code \
  "CREATE PRICE" \
  201 \
  "$tmp_dir/create_price.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices" \
  -d "$price_payload"

expect_code \
  "LOOKUP ACTIVE PRICE" \
  200 \
  "$tmp_dir/active_price.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/BillingPrices" \
  --data-urlencode "\$filter=Code eq '$price_code'" \
  --data-urlencode "\$top=1"
price_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/active_price.json")"
price_pre_archive_rv="$(jq -r '.value[0].RowVersion // empty' "$tmp_dir/active_price.json")"
if [[ -z "$price_id" || -z "$price_pre_archive_rv" ]]; then
  echo "ERROR: active Price lookup omitted Id or RowVersion." >&2
  exit 1
fi
if ! jq -e '
  .value[0].DeletedAt == null
  and .value[0].IsArchived == false
  and (.value[0] | has("TenantId") | not)
' "$tmp_dir/active_price.json" >/dev/null; then
  echo "ERROR: active Price lifecycle assertion failed." >&2
  exit 1
fi

archive_price_payload="$(jq -cn \
  --argjson row_version "$price_pre_archive_rv" \
  '{RowVersion:$row_version}')"
expect_code \
  "ARCHIVE PRICE" \
  204 \
  "$tmp_dir/archive_price.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices/$price_id/\$action/archive" \
  -d "$archive_price_payload"

archive_product_payload="$(jq -cn \
  --argjson row_version "$product_pre_archive_rv" \
  '{RowVersion:$row_version}')"
expect_code \
  "ARCHIVE PRODUCT" \
  204 \
  "$tmp_dir/archive_product.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingProducts/$product_id/\$action/archive" \
  -d "$archive_product_payload"

expect_code \
  "ARCHIVED PRODUCT DISCOVERY" \
  200 \
  "$tmp_dir/archived_product.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$deleted=archived" \
  --data-urlencode "\$filter=Code eq '$product_code'" \
  --data-urlencode "\$orderby=Code desc" \
  --data-urlencode "\$top=1" \
  --data-urlencode "\$skip=0" \
  --data-urlencode "\$count=true"
product_archived_rv="$(jq -r \
  --arg id "$product_id" \
  '.value[] | select(.Id == $id) | .RowVersion // empty' \
  "$tmp_dir/archived_product.json")"
if ! jq -e \
  --arg id "$product_id" '
    ."@count" == 1
    and (.value | length) == 1
    and .value[0].Id == $id
    and .value[0].DeletedAt != null
    and .value[0].IsArchived == true
    and (.value[0].RowVersion | type) == "number"
    and (.value[0] | has("TenantId") | not)
  ' "$tmp_dir/archived_product.json" >/dev/null; then
  echo "ERROR: archived Product discovery assertion failed." >&2
  exit 1
fi

expect_code \
  "ARCHIVED PRICE DISCOVERY" \
  200 \
  "$tmp_dir/archived_price.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/BillingPrices" \
  --data-urlencode "\$deleted=archived" \
  --data-urlencode "\$filter=ProductId eq guid'$product_id'" \
  --data-urlencode "\$orderby=Code asc" \
  --data-urlencode "\$top=1" \
  --data-urlencode "\$skip=0" \
  --data-urlencode "\$count=true"
price_archived_rv="$(jq -r \
  --arg id "$price_id" \
  '.value[] | select(.Id == $id) | .RowVersion // empty' \
  "$tmp_dir/archived_price.json")"
if ! jq -e \
  --arg id "$price_id" \
  --arg product_id "$product_id" '
    ."@count" == 1
    and (.value | length) == 1
    and .value[0].Id == $id
    and .value[0].ProductId == $product_id
    and .value[0].DeletedAt != null
    and .value[0].IsArchived == true
    and (.value[0].RowVersion | type) == "number"
    and (.value[0] | has("TenantId") | not)
  ' "$tmp_dir/archived_price.json" >/dev/null; then
  echo "ERROR: archived Price discovery assertion failed." >&2
  exit 1
fi

if [[ -z "$product_archived_rv" || -z "$price_archived_rv" ]]; then
  echo "ERROR: archived discovery omitted current RowVersion." >&2
  exit 1
fi

expect_code \
  "ACTIVE VIEW EXCLUDES ARCHIVED PRODUCT" \
  200 \
  "$tmp_dir/active_excludes_product.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$deleted=active" \
  --data-urlencode "\$filter=Code eq '$product_code'" \
  --data-urlencode "\$count=true"
if ! jq -e '."@count" == 0 and (.value | length) == 0' \
  "$tmp_dir/active_excludes_product.json" >/dev/null; then
  echo "ERROR: active Product view included archived row." >&2
  exit 1
fi

expect_code \
  "ALL VIEW INCLUDES ARCHIVED PRODUCT" \
  200 \
  "$tmp_dir/all_product.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$deleted=all" \
  --data-urlencode "\$filter=Code eq '$product_code'" \
  --data-urlencode "\$count=true"
if ! jq -e '."@count" == 1 and .value[0].IsArchived == true' \
  "$tmp_dir/all_product.json" >/dev/null; then
  echo "ERROR: all Product view omitted archived row." >&2
  exit 1
fi

expect_code \
  "DISCOVER ACTIVE TENANT FOR ROUTE VALIDATION" \
  200 \
  "$tmp_dir/active_tenant.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/Tenants" \
  --data-urlencode "\$filter=Status eq 'active'" \
  --data-urlencode "\$top=1"
route_tenant_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/active_tenant.json")"
if [[ -z "$route_tenant_id" ]]; then
  route_tenant_slug="billing-runtime-route-${tmp_dir##*_}"
  route_tenant_payload="$(jq -cn --arg slug "$route_tenant_slug" \
    '{Name:"Billing runtime route validation",Slug:$slug}')"
  expect_code \
    "CREATE ACTIVE TENANT FOR ROUTE VALIDATION" \
    201 \
    "$tmp_dir/create_route_tenant.json" \
    -H "$admin_auth_header" \
    -H "Content-Type: application/json" \
    -X POST "$base_url/Tenants" \
    -d "$route_tenant_payload"
  expect_code \
    "LOOK UP ACTIVE TENANT FOR ROUTE VALIDATION" \
    200 \
    "$tmp_dir/active_tenant.json" \
    -G \
    -H "$admin_auth_header" \
    "$base_url/Tenants" \
    --data-urlencode "\$filter=Slug eq '$route_tenant_slug' and Status eq 'active'" \
    --data-urlencode "\$top=1"
  route_tenant_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/active_tenant.json")"
fi
if [[ -z "$route_tenant_id" ]]; then
  echo "ERROR: could not resolve an active tenant for route validation." >&2
  exit 1
fi

expect_code \
  "TENANT ARCHIVED PRODUCT ROUTE REJECTED" \
  400 \
  "$tmp_dir/tenant_product.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/tenants/$route_tenant_id/BillingProducts" \
  --data-urlencode "\$deleted=archived"

missing_tenant_id="38a8d553-547a-45a0-bb29-b7a4dbf1e60d"
expect_code \
  "CONFIRM NONEXISTENT TENANT" \
  404 \
  "$tmp_dir/missing_tenant.json" \
  -H "$admin_auth_header" \
  "$base_url/Tenants/$missing_tenant_id"
expect_code \
  "NONEXISTENT TENANT ARCHIVED PRODUCT ROUTE DENIED" \
  403 \
  "$tmp_dir/missing_tenant_product.json" \
  -G \
  -H "$admin_auth_header" \
  "$base_url/tenants/$missing_tenant_id/BillingProducts" \
  --data-urlencode "\$deleted=archived"

provision_user \
  "$reader_username" \
  "$reader_password" \
  "$reader_email" \
  "$tmp_dir/provision_reader.json"
reader_login="$(login_user \
  "$reader_username" \
  "$reader_password" \
  "$tmp_dir/login_reader.json")"
reader_token="${reader_login%%|*}"
reader_user_id="${reader_login##*|}"
reader_auth_header="Authorization: Bearer $reader_token"

catalog_role="$billing_namespace:catalog_reader"
roles_payload="$(jq -cn --arg role "$catalog_role" '{Roles:[$role]}')"
expect_code \
  "ASSIGN CATALOG READER" \
  204 \
  "$tmp_dir/assign_reader.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/Users/$reader_user_id/\$action/updateroles" \
  -d "$roles_payload"

provision_user \
  "$basic_username" \
  "$basic_password" \
  "$basic_email" \
  "$tmp_dir/provision_basic.json"
basic_login="$(login_user \
  "$basic_username" \
  "$basic_password" \
  "$tmp_dir/login_basic.json")"
basic_token="${basic_login%%|*}"
basic_auth_header="Authorization: Bearer $basic_token"

expect_code \
  "RUNTIME STATUS AUTHENTICATED ONLY" \
  200 \
  "$tmp_dir/runtime_basic.json" \
  -H "$basic_auth_header" \
  "$base_url/runtime/extensions/core.fw.billing"
expect_code \
  "RUNTIME STATUS CATALOG READER" \
  200 \
  "$tmp_dir/runtime_reader.json" \
  -H "$reader_auth_header" \
  "$base_url/runtime/extensions/core.fw.billing"

expect_code \
  "ARCHIVED PRODUCT READ WITHOUT PERMISSION" \
  403 \
  "$tmp_dir/basic_product.json" \
  -G \
  -H "$basic_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$deleted=archived"
expect_code \
  "ARCHIVED PRICE READ WITHOUT PERMISSION" \
  403 \
  "$tmp_dir/basic_price.json" \
  -G \
  -H "$basic_auth_header" \
  "$base_url/BillingPrices" \
  --data-urlencode "\$deleted=archived"

expect_code \
  "ARCHIVED PRODUCT READ AS CATALOG READER" \
  200 \
  "$tmp_dir/reader_product.json" \
  -G \
  -H "$reader_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$deleted=archived" \
  --data-urlencode "\$filter=Code eq '$product_code'"
expect_code \
  "ARCHIVED PRICE READ AS CATALOG READER" \
  200 \
  "$tmp_dir/reader_price.json" \
  -G \
  -H "$reader_auth_header" \
  "$base_url/BillingPrices" \
  --data-urlencode "\$deleted=archived" \
  --data-urlencode "\$filter=ProductId eq guid'$product_id'"

restore_price_payload="$(jq -cn \
  --argjson row_version "$price_archived_rv" \
  '{RowVersion:$row_version}')"
expect_code \
  "RESTORE PRICE AS CATALOG READER" \
  403 \
  "$tmp_dir/reader_restore_price.json" \
  -H "$reader_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices/$price_id/\$restore" \
  -d "$restore_price_payload"

stale_restore_price_payload="$(jq -cn \
  --argjson row_version "$price_pre_archive_rv" \
  '{RowVersion:$row_version}')"
expect_code \
  "RESTORE PRICE WITH STALE ROWVERSION" \
  409 \
  "$tmp_dir/stale_restore_price.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices/$price_id/\$restore" \
  -d "$stale_restore_price_payload"

restore_product_payload="$(jq -cn \
  --argjson row_version "$product_archived_rv" \
  '{RowVersion:$row_version}')"
expect_code \
  "RESTORE PRODUCT" \
  204 \
  "$tmp_dir/restore_product.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingProducts/$product_id/\$restore" \
  -d "$restore_product_payload"
expect_code \
  "RESTORE PRICE" \
  204 \
  "$tmp_dir/restore_price.json" \
  -H "$admin_auth_header" \
  -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices/$price_id/\$restore" \
  -d "$restore_price_payload"

expect_code \
  "RESTORED PRODUCT ACTIVE" \
  200 \
  "$tmp_dir/restored_product.json" \
  -G \
  -H "$reader_auth_header" \
  "$base_url/BillingProducts" \
  --data-urlencode "\$filter=Code eq '$product_code'"
expect_code \
  "RESTORED PRICE ACTIVE" \
  200 \
  "$tmp_dir/restored_price.json" \
  -G \
  -H "$reader_auth_header" \
  "$base_url/BillingPrices" \
  --data-urlencode "\$filter=Code eq '$price_code'"
if ! jq -e '
  (.value | length) == 1
  and .value[0].DeletedAt == null
  and .value[0].IsArchived == false
' "$tmp_dir/restored_product.json" >/dev/null; then
  echo "ERROR: restored Product lifecycle assertion failed." >&2
  exit 1
fi
if ! jq -e '
  (.value | length) == 1
  and .value[0].DeletedAt == null
  and .value[0].IsArchived == false
' "$tmp_dir/restored_price.json" >/dev/null; then
  echo "ERROR: restored Price lifecycle assertion failed." >&2
  exit 1
fi

echo "BILLING RUNTIME/ARCHIVE E2E: PASS"
