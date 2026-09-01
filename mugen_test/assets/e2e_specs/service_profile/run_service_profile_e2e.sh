#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run Service Profile routing and Subscription allocation HTTP E2E checks.

Usage:
  run_service_profile_e2e.sh --spec <path> [--print-config]
EOF
}

env_truthy() {
  case "${1:-}" in
    1|true|yes|on) return 0 ;;
    *) return 1 ;;
  esac
}

spec_path=""
print_config=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --spec) spec_path="$2"; shift 2 ;;
    --print-config) print_config=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "ERROR: unknown argument: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$spec_path" || ! -f "$spec_path" ]]; then
  echo "ERROR: --spec must name an existing file." >&2
  exit 1
fi
for command_name in curl jq mktemp; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "ERROR: required command not found: $command_name" >&2
    exit 1
  fi
done

spec_json="$(<"$spec_path")"
if [[ "$print_config" -eq 1 ]]; then
  echo "$spec_json" | jq .
  exit 0
fi

base_url="$(echo "$spec_json" | jq -r '.base_url // empty')"
username="$(echo "$spec_json" | jq -r '.credentials.username // empty')"
password="$(echo "$spec_json" | jq -r '.credentials.password // empty')"
code_prefix="$(echo "$spec_json" | jq -r '.catalog.code_prefix // empty')"
currency_id="$(echo "$spec_json" | jq -r '.catalog.currency_definition_id // empty')"
reader_username="$(echo "$spec_json" | jq -r '.unprivileged_user.username // empty')"
reader_password="$(echo "$spec_json" | jq -r '.unprivileged_user.password // empty')"
reader_email="$(echo "$spec_json" | jq -r '.unprivileged_user.email // empty')"
spawn_hypercorn="$(echo "$spec_json" | jq -r '.runtime.spawn_hypercorn // false')"
hypercorn_cmd="$(echo "$spec_json" | jq -r '.runtime.hypercorn_cmd // empty')"
health_url="$(echo "$spec_json" | jq -r '.runtime.health_url // empty')"
startup_timeout="$(echo "$spec_json" | jq -r '.runtime.startup_timeout_secs // 30')"

for required in "$base_url" "$username" "$password" "$code_prefix" \
  "$currency_id" "$reader_username" "$reader_password" "$reader_email"; do
  if [[ -z "$required" ]]; then
    echo "ERROR: Service Profile E2E spec is missing a required value." >&2
    exit 1
  fi
done

tmp_dir="$(mktemp -d /tmp/service_profile_e2e_XXXXXX)"
hypercorn_pid=""
cleanup() {
  if [[ -n "$hypercorn_pid" ]]; then
    kill "$hypercorn_pid" >/dev/null 2>&1 || true
    wait "$hypercorn_pid" >/dev/null 2>&1 || true
  fi
  rm -rf "$tmp_dir"
}
trap cleanup EXIT

if [[ "$spawn_hypercorn" == "true" ]] && ! env_truthy "${ACP_E2E_EXTERNAL_SERVER:-0}"; then
  bash -lc "$hypercorn_cmd" >"$tmp_dir/hypercorn.log" 2>&1 &
  hypercorn_pid="$!"
fi
healthy=0
for _ in $(seq 1 "$startup_timeout"); do
  if [[ -n "$hypercorn_pid" ]] && ! kill -0 "$hypercorn_pid" >/dev/null 2>&1; then
    tail -n 120 "$tmp_dir/hypercorn.log" >&2 || true
    exit 1
  fi
  if [[ "$(curl -sk -o /dev/null -w '%{http_code}' "$health_url" || true)" == "200" ]]; then
    healthy=1
    break
  fi
  sleep 1
done
if [[ "$healthy" -ne 1 ]]; then
  echo "ERROR: Service Profile E2E server did not become healthy." >&2
  exit 1
fi

expect_code() {
  local label="$1" expected="$2" output_file="$3"
  shift 3
  local actual
  actual="$(curl -sk -o "$output_file" -w '%{http_code}' "$@")"
  echo "$label: $actual" >&2
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: $label expected $expected, got $actual" >&2
    cat "$output_file" >&2 || true
    exit 1
  fi
}

login_payload="$(jq -cn --arg username "$username" --arg password "$password" \
  '{Username:$username,Password:$password}')"
expect_code "LOGIN ADMIN" 200 "$tmp_dir/login_admin.json" \
  -H "Content-Type: application/json" -X POST "$base_url/auth/login" \
  -d "$login_payload"
admin_token="$(jq -r '.access_token // empty' "$tmp_dir/login_admin.json")"
admin_auth="Authorization: Bearer $admin_token"

create_tenant() {
  local suffix="$1"
  local slug="${code_prefix}-${suffix}"
  local payload
  payload="$(jq -cn --arg slug "$slug" --arg suffix "$suffix" \
    '{Name:("Service Profile " + $suffix),Slug:$slug}')"
  expect_code "CREATE TENANT $suffix" 201 "$tmp_dir/tenant_${suffix}.json" \
    -H "$admin_auth" -H "Content-Type: application/json" \
    -X POST "$base_url/Tenants" -d "$payload"
  curl -sk -G -H "$admin_auth" "$base_url/Tenants" \
    --data-urlencode "\$filter=Slug eq '$slug'" --data-urlencode "\$top=1" \
    | jq -r '.value[0].Id // empty'
}

lookup_id() {
  local tenant_id="$1" entity_set="$2" field="$3" value="$4"
  curl -sk -G -H "$admin_auth" "$base_url/tenants/$tenant_id/$entity_set" \
    --data-urlencode "\$filter=$field eq '$value'" --data-urlencode "\$top=1" \
    | jq -r '.value[0].Id // empty'
}

tenant_one="$(create_tenant one)"
tenant_two="$(create_tenant two)"
if [[ -z "$tenant_one" || -z "$tenant_two" ]]; then
  echo "ERROR: tenant provisioning failed." >&2
  exit 1
fi

channel_key="${code_prefix}-channel"
channel_payload="$(jq -cn --arg channel "$channel_key" \
  '{ChannelKey:$channel,ProfileKey:"primary",ServiceRouteDefaultKey:"support.primary"}')"
expect_code "CREATE CHANNEL PROFILE" 201 "$tmp_dir/channel.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ChannelProfiles" -d "$channel_payload"
channel_profile_id="$(lookup_id "$tenant_one" ChannelProfiles ChannelKey "$channel_key")"

binding_value="${code_prefix}-endpoint"
binding_payload="$(jq -cn --arg profile "$channel_profile_id" \
  --arg channel "$channel_key" --arg value "$binding_value" \
  '{ChannelProfileId:$profile,ChannelKey:$channel,IdentifierType:"endpoint",IdentifierValue:$value,ServiceRouteKey:"support.primary"}')"
expect_code "CREATE INGRESS BINDING" 201 "$tmp_dir/binding.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/IngressBindings" -d "$binding_payload"
binding_id="$(lookup_id "$tenant_one" IngressBindings IdentifierValue "$binding_value")"

profile_key="${code_prefix}-main"
profile_payload="$(jq -cn --arg key "  ${profile_key^^}  " \
  '{Key:$key,DisplayName:" Main Service ",Attributes:{}}')"
expect_code "CREATE SERVICE PROFILE" 201 "$tmp_dir/profile.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfiles" -d "$profile_payload"
profile_id="$(lookup_id "$tenant_one" ServiceProfiles Key "$profile_key")"
expect_code "GET NORMALIZED PROFILE" 200 "$tmp_dir/profile_get.json" \
  -H "$admin_auth" "$base_url/tenants/$tenant_one/ServiceProfiles/$profile_id"
if ! jq -e --arg key "$profile_key" '.Key == $key and .Status == "draft"' \
  "$tmp_dir/profile_get.json" >/dev/null; then
  echo "ERROR: Service Profile normalization/draft lifecycle failed." >&2
  exit 1
fi
profile_rv="$(jq -r '.RowVersion' "$tmp_dir/profile_get.json")"

assignment_payload="$(jq -cn --arg profile "$profile_id" --arg binding "$binding_id" \
  '{ServiceProfileId:$profile,IngressBindingId:$binding,IsActive:true,Attributes:{}}')"
expect_code "CREATE INGRESS ASSIGNMENT" 201 "$tmp_dir/assignment.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfileIngressBindings" \
  -d "$assignment_payload"
expect_code "REJECT CROSS TENANT INGRESS ASSIGNMENT" 400 "$tmp_dir/cross_tenant.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_two/ServiceProfileIngressBindings" \
  -d "$assignment_payload"

second_profile_payload="$(jq -cn --arg key "${profile_key}-alternate" \
  '{Key:$key,DisplayName:"Alternate Service",Attributes:{}}')"
expect_code "CREATE ALTERNATE SERVICE PROFILE" 201 "$tmp_dir/profile_alternate.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfiles" \
  -d "$second_profile_payload"
second_profile_id="$(lookup_id "$tenant_one" ServiceProfiles Key "${profile_key}-alternate")"
duplicate_assignment_payload="$(jq -cn --arg profile "$second_profile_id" \
  --arg binding "$binding_id" \
  '{ServiceProfileId:$profile,IngressBindingId:$binding,IsActive:true,Attributes:{}}')"
expect_code "REJECT DUPLICATE ACTIVE INGRESS ASSIGNMENT" 409 \
  "$tmp_dir/duplicate_assignment.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfileIngressBindings" \
  -d "$duplicate_assignment_payload"

stale_action="$(jq -cn --argjson rv "$((profile_rv + 10))" '{RowVersion:$rv}')"
expect_code "REJECT STALE PROFILE ACTIVATION" 409 "$tmp_dir/stale_profile.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfiles/$profile_id/\$action/activate" \
  -d "$stale_action"

expect_code "GET USD CURRENCY" 200 "$tmp_dir/currency.json" \
  -H "$admin_auth" "$base_url/BillingCurrencyDefinitions/$currency_id"
currency_rv="$(jq -r '.RowVersion' "$tmp_dir/currency.json")"
currency_action="$(jq -cn --argjson rv "$currency_rv" '{RowVersion:$rv}')"
currency_status="$(jq -r '.Status // empty' "$tmp_dir/currency.json")"
if [[ "$currency_status" != "active" ]]; then
  expect_code "ACTIVATE USD CURRENCY" 204 "$tmp_dir/currency_activate.json" \
    -H "$admin_auth" -H "Content-Type: application/json" \
    -X POST "$base_url/BillingCurrencyDefinitions/$currency_id/\$action/activate" \
    -d "$currency_action"
fi

product_code="${code_prefix}.product"
product_payload="$(jq -cn --arg code "$product_code" '{Code:$code,Name:"Service Profile Product"}')"
expect_code "CREATE PRODUCT" 201 "$tmp_dir/product.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingProducts" -d "$product_payload"
product_id="$(curl -sk -G -H "$admin_auth" "$base_url/BillingProducts" \
  --data-urlencode "\$filter=Code eq '$product_code'" --data-urlencode "\$top=1" \
  | jq -r '.value[0].Id // empty')"

price_code="${code_prefix}-monthly"
price_payload="$(jq -cn --arg product "$product_id" --arg currency "$currency_id" \
  --arg code "$price_code" \
  '{ProductId:$product,Code:$code,PriceType:"recurring",CurrencyDefinitionId:$currency,UnitAmount:1000,IntervalUnit:"month",IntervalCount:1}')"
expect_code "CREATE PRICE" 201 "$tmp_dir/price.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices" -d "$price_payload"
price_id="$(curl -sk -G -H "$admin_auth" "$base_url/BillingPrices" \
  --data-urlencode "\$filter=Code eq '$price_code'" --data-urlencode "\$top=1" \
  | jq -r '.value[0].Id // empty')"

account_code="${code_prefix}-account"
account_payload="$(jq -cn --arg code "$account_code" '{Code:$code,DisplayName:"Service Profile Account"}')"
expect_code "CREATE BILLING ACCOUNT" 201 "$tmp_dir/account.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingAccounts" -d "$account_payload"
account_id="$(lookup_id "$tenant_one" BillingAccounts Code "$account_code")"

subscription_payload="$(jq -cn --arg account "$account_id" --arg price "$price_id" \
  '{AccountId:$account,PriceId:$price,StartedAt:"2026-01-01T00:00:00Z",CurrentPeriodStart:"2026-01-01T00:00:00Z",CurrentPeriodEnd:"2099-01-01T00:00:00Z"}')"
expect_code "CREATE BILLING SUBSCRIPTION" 201 "$tmp_dir/subscription.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingSubscriptions" \
  -d "$subscription_payload"
subscription_id="$(curl -sk -G -H "$admin_auth" \
  "$base_url/tenants/$tenant_one/BillingSubscriptions" \
  --data-urlencode "\$filter=AccountId eq guid'$account_id'" \
  --data-urlencode "\$top=1" \
  | jq -r '.value[0].Id // empty')"

allocation_payload="$(jq -cn --arg profile "$profile_id" --arg subscription "$subscription_id" \
  '{ServiceProfileId:$profile,BillingSubscriptionId:$subscription,Attributes:{}}')"
client_code_payload="$(echo "$allocation_payload" | jq --arg code "$product_code" '. + {ProductCode:$code}')"
expect_code "REJECT CLIENT PRODUCT CODE" 400 "$tmp_dir/client_product_code.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions" \
  -d "$client_code_payload"
expect_code "CREATE SUBSCRIPTION ALLOCATION" 201 "$tmp_dir/allocation.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions" \
  -d "$allocation_payload"
allocation_id="$(curl -sk -G -H "$admin_auth" \
  "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions" \
  --data-urlencode "\$filter=BillingSubscriptionId eq guid'$subscription_id'" \
  --data-urlencode "\$top=1" \
  | jq -r '.value[0].Id // empty')"
expect_code "GET SUBSCRIPTION ALLOCATION" 200 "$tmp_dir/allocation_get.json" \
  -H "$admin_auth" "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions/$allocation_id"
allocation_rv="$(jq -r '.RowVersion' "$tmp_dir/allocation_get.json")"
allocation_action="$(jq -cn --argjson rv "$allocation_rv" '{RowVersion:$rv}')"
expect_code "ACTIVATE SUBSCRIPTION ALLOCATION" 204 "$tmp_dir/allocation_activate.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions/$allocation_id/\$action/activate" \
  -d "$allocation_action"
expect_code "GET ACTIVE ALLOCATION" 200 "$tmp_dir/allocation_active.json" \
  -H "$admin_auth" "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions/$allocation_id"
if ! jq -e --arg code "$product_code" '.Status == "active" and .ProductCode == $code' \
  "$tmp_dir/allocation_active.json" >/dev/null; then
  echo "ERROR: Subscription allocation activation/derived Product code failed." >&2
  exit 1
fi

profile_action="$(jq -cn --argjson rv "$profile_rv" '{RowVersion:$rv}')"
expect_code "ACTIVATE SERVICE PROFILE" 204 "$tmp_dir/profile_activate.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfiles/$profile_id/\$action/activate" \
  -d "$profile_action"

reader_payload="$(jq -cn --arg username "$reader_username" --arg password "$reader_password" \
  --arg email "$reader_email" \
  '{Username:$username,Password:$password,LoginEmail:$email,FirstName:"Service",LastName:"Reader"}')"
expect_code "PROVISION UNPRIVILEGED USER" 204 "$tmp_dir/reader_create.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/Users/\$action/provision" -d "$reader_payload"
reader_login="$(jq -cn --arg username "$reader_username" --arg password "$reader_password" \
  '{Username:$username,Password:$password}')"
expect_code "LOGIN UNPRIVILEGED USER" 200 "$tmp_dir/reader_login.json" \
  -H "Content-Type: application/json" -X POST "$base_url/auth/login" \
  -d "$reader_login"
reader_token="$(jq -r '.access_token // empty' "$tmp_dir/reader_login.json")"
expect_code "REJECT UNPRIVILEGED PROFILE READ" 403 "$tmp_dir/reader_denied.json" \
  -H "Authorization: Bearer $reader_token" \
  "$base_url/tenants/$tenant_one/ServiceProfiles/$profile_id"

expect_code "GET PROFILE BEFORE DISABLE" 200 "$tmp_dir/profile_active.json" \
  -H "$admin_auth" "$base_url/tenants/$tenant_one/ServiceProfiles/$profile_id"
profile_rv="$(jq -r '.RowVersion' "$tmp_dir/profile_active.json")"
profile_action="$(jq -cn --argjson rv "$profile_rv" '{RowVersion:$rv}')"
expect_code "DISABLE SERVICE PROFILE" 204 "$tmp_dir/profile_disable.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfiles/$profile_id/\$action/disable" \
  -d "$profile_action"

allocation_rv="$(jq -r '.RowVersion' "$tmp_dir/allocation_active.json")"
allocation_action="$(jq -cn --argjson rv "$allocation_rv" '{RowVersion:$rv}')"
expect_code "DISABLE SUBSCRIPTION ALLOCATION" 204 "$tmp_dir/allocation_disable.json" \
  -H "$admin_auth" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/ServiceProfileSubscriptions/$allocation_id/\$action/disable" \
  -d "$allocation_action"

echo "Service Profile HTTP E2E passed." >&2
