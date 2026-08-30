#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Run normalized global-definition and tenant-operation Billing HTTP E2E checks.

Usage:
  run_billing_normalized_definitions_e2e.sh --spec <path> [--print-config]
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
meter_code="$(echo "$spec_json" | jq -r '.catalog.meter_code // empty')"
currency_id="$(echo "$spec_json" | jq -r '.catalog.currency_definition_id // empty')"
spawn_hypercorn="$(echo "$spec_json" | jq -r '.runtime.spawn_hypercorn // false')"
hypercorn_cmd="$(echo "$spec_json" | jq -r '.runtime.hypercorn_cmd // empty')"
health_url="$(echo "$spec_json" | jq -r '.runtime.health_url // empty')"
startup_timeout="$(echo "$spec_json" | jq -r '.runtime.startup_timeout_secs // 30')"

for required in "$base_url" "$username" "$password" "$code_prefix" "$meter_code" "$currency_id"; do
  if [[ -z "$required" ]]; then
    echo "ERROR: normalized Billing spec is missing a required value." >&2
    exit 1
  fi
done

tmp_dir="$(mktemp -d /tmp/billing_normalized_e2e_XXXXXX)"
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
  bash -lc "$hypercorn_cmd" >"$tmp_dir/hypercorn.log" 2>&1 &
  hypercorn_pid="$!"
  started=0
  for _ in $(seq 1 "$startup_timeout"); do
    if ! kill -0 "$hypercorn_pid" >/dev/null 2>&1; then
      tail -n 120 "$tmp_dir/hypercorn.log" >&2 || true
      exit 1
    fi
    if [[ "$(curl -sk -o /dev/null -w '%{http_code}' "$health_url" || true)" == "200" ]]; then
      started=1
      break
    fi
    sleep 1
  done
  if [[ "$started" -ne 1 ]]; then
    echo "ERROR: Hypercorn did not become healthy." >&2
    tail -n 120 "$tmp_dir/hypercorn.log" >&2 || true
    exit 1
  fi
fi

expect_code() {
  local label="$1"
  local expected="$2"
  local output_file="$3"
  shift 3
  local actual
  actual="$(curl -sk -o "$output_file" -w '%{http_code}' "$@")"
  echo "$label: $actual" >&2
  if [[ "$actual" != "$expected" ]]; then
    echo "ERROR: $label expected $expected, got $actual" >&2
    cat "$output_file" >&2
    exit 1
  fi
}

login_payload="$(jq -cn --arg username "$username" --arg password "$password" \
  '{Username:$username,Password:$password}')"
expect_code "LOGIN" 200 "$tmp_dir/login.json" \
  -H "Content-Type: application/json" -X POST "$base_url/auth/login" -d "$login_payload"
token="$(jq -r '.access_token // empty' "$tmp_dir/login.json")"
if [[ -z "$token" ]]; then
  echo "ERROR: login response omitted access_token." >&2
  exit 1
fi
auth_header="Authorization: Bearer $token"

create_tenant() {
  local suffix="$1"
  local slug="${code_prefix}-${suffix}"
  local payload
  payload="$(jq -cn --arg slug "$slug" --arg suffix "$suffix" \
    '{Name:("Billing normalized " + $suffix),Slug:$slug}')"
  expect_code "CREATE TENANT $suffix" 201 "$tmp_dir/tenant_${suffix}.json" \
    -H "$auth_header" -H "Content-Type: application/json" \
    -X POST "$base_url/Tenants" -d "$payload"
  curl -sk -G -H "$auth_header" "$base_url/Tenants" \
    --data-urlencode "\$filter=Slug eq '$slug'" \
    --data-urlencode "\$top=1" \
    | jq -r '.value[0].Id // empty'
}

tenant_one="$(create_tenant one)"
tenant_two="$(create_tenant two)"
if [[ -z "$tenant_one" || -z "$tenant_two" || "$tenant_one" == "$tenant_two" ]]; then
  echo "ERROR: tenant bootstrap failed." >&2
  exit 1
fi

expect_code "GET CURRENCY" 200 "$tmp_dir/currency.json" \
  -H "$auth_header" "$base_url/BillingCurrencyDefinitions/$currency_id"
currency_rv="$(jq -r '.RowVersion // empty' "$tmp_dir/currency.json")"
currency_action="$(jq -cn --argjson row_version "$currency_rv" '{RowVersion:$row_version}')"
expect_code "ACTIVATE CURRENCY" 204 "$tmp_dir/currency_activate.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingCurrencyDefinitions/$currency_id/\$action/activate" \
  -d "$currency_action"

tax_code="${code_prefix}-tax"
tax_payload="$(jq -cn --arg code "$tax_code" \
  '{Code:$code,DisplayName:"Normalized tax"}')"
expect_code "CREATE TAX CODE" 201 "$tmp_dir/tax_code_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingTaxCodes" -d "$tax_payload"
expect_code "LOOKUP TAX CODE" 200 "$tmp_dir/tax_code_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingTaxCodes" \
  --data-urlencode "\$filter=Code eq '$tax_code'" --data-urlencode "\$top=1"
tax_code_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/tax_code_lookup.json")"

tax_rate_code="${code_prefix}-tax-rate"
tax_rate_payload="$(jq -cn --arg code "$tax_rate_code" --arg tax "$tax_code_id" \
  '{Code:$code,TaxCodeId:$tax,JurisdictionCode:"gy",RateBasisPoints:1400,EffectiveFrom:"2026-01-01T00:00:00Z"}')"
expect_code "CREATE TAX RATE" 201 "$tmp_dir/tax_rate_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingTaxRates" -d "$tax_rate_payload"
expect_code "LOOKUP TAX RATE" 200 "$tmp_dir/tax_rate_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingTaxRates" \
  --data-urlencode "\$filter=Code eq '$tax_rate_code'" --data-urlencode "\$top=1"
tax_rate_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/tax_rate_lookup.json")"

payment_term_code="${code_prefix}-net-14"
payment_term_payload="$(jq -cn --arg code "$payment_term_code" \
  '{Code:$code,DisplayName:"Net 14",DueDays:14}')"
expect_code "CREATE PAYMENT TERM" 201 "$tmp_dir/payment_term_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPaymentTerms" -d "$payment_term_payload"
expect_code "LOOKUP PAYMENT TERM" 200 "$tmp_dir/payment_term_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingPaymentTerms" \
  --data-urlencode "\$filter=Code eq '$payment_term_code'" --data-urlencode "\$top=1"
payment_term_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/payment_term_lookup.json")"

invoice_template_code="${code_prefix}-invoice"
invoice_template_payload="$(jq -cn --arg code "$invoice_template_code" \
  '{Code:$code,DisplayName:"Normalized invoice",Locale:"en-GY",TemplateFormat:"text",BodyTemplate:"Invoice {{ number }}"}')"
expect_code "CREATE INVOICE TEMPLATE" 201 "$tmp_dir/invoice_template_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingInvoiceTemplates" -d "$invoice_template_payload"
expect_code "LOOKUP INVOICE TEMPLATE" 200 "$tmp_dir/invoice_template_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingInvoiceTemplates" \
  --data-urlencode "\$filter=Code eq '$invoice_template_code'" --data-urlencode "\$top=1"
invoice_template_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/invoice_template_lookup.json")"

discount_code="${code_prefix}-discount"
discount_payload="$(jq -cn --arg code "$discount_code" --arg currency "$currency_id" \
  '{Code:$code,DisplayName:"Normalized discount",Kind:"fixed_amount",Amount:100,CurrencyDefinitionId:$currency}')"
expect_code "CREATE DISCOUNT" 201 "$tmp_dir/discount_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingDiscountDefinitions" -d "$discount_payload"
expect_code "LOOKUP DISCOUNT" 200 "$tmp_dir/discount_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingDiscountDefinitions" \
  --data-urlencode "\$filter=Code eq '$discount_code'" --data-urlencode "\$top=1"
discount_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/discount_lookup.json")"

meter_payload="$(jq -cn --arg code "$meter_code" \
  '{Code:$code,Unit:"minute",AggregationMode:"sum",Description:"Normalized Billing E2E meter",Attributes:{module_key:"e2e"}}')"
expect_code "CREATE GLOBAL METER" 201 "$tmp_dir/meter_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingMeterDefinitions" -d "$meter_payload"
expect_code "LOOKUP GLOBAL METER" 200 "$tmp_dir/meter_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingMeterDefinitions" \
  --data-urlencode "\$filter=Code eq '$meter_code'" --data-urlencode "\$top=1"
meter_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/meter_lookup.json")"
meter_rv="$(jq -r '.value[0].RowVersion // empty' "$tmp_dir/meter_lookup.json")"
if ! jq -e '.value | length == 1 and (.[0] | has("TenantId") | not)' "$tmp_dir/meter_lookup.json" >/dev/null; then
  echo "ERROR: meter is not a unique global definition." >&2
  exit 1
fi
expect_code "GET DEPRECATED TENANT METER PROJECTION" 200 "$tmp_dir/meter_compat.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/OpsMeterDefinitions" \
  --data-urlencode "\$filter=Code eq '$meter_code'" --data-urlencode "\$top=1"
if ! jq -e --arg tenant "$tenant_one" --arg meter "$meter_id" '
  .value | length == 1
  and .[0].Id == $meter
  and .[0].TenantId == $tenant
  and .[0].IsDeprecated == true
  and .[0].SuccessorEntitySet == "BillingMeterDefinitions"
' "$tmp_dir/meter_compat.json" >/dev/null; then
  echo "ERROR: deprecated tenant meter projection is incorrect." >&2
  exit 1
fi
expect_code "REJECT TENANT METER ROUTE" 400 "$tmp_dir/meter_tenant_route.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingMeterDefinitions" -d "$meter_payload"

meter_action="$(jq -cn --argjson row_version "$meter_rv" '{RowVersion:$row_version}')"
expect_code "DEACTIVATE UNREFERENCED METER" 204 "$tmp_dir/meter_deactivate.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingMeterDefinitions/$meter_id/\$action/deactivate" -d "$meter_action"
expect_code "GET INACTIVE METER" 200 "$tmp_dir/meter_inactive.json" \
  -H "$auth_header" "$base_url/BillingMeterDefinitions/$meter_id"
meter_rv="$(jq -r '.RowVersion' "$tmp_dir/meter_inactive.json")"

product_code="${code_prefix}-package"
product_payload="$(jq -cn --arg code "$product_code" '{Code:$code,Name:"Normalized package"}')"
expect_code "CREATE PRODUCT" 201 "$tmp_dir/product_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingProducts" -d "$product_payload"
expect_code "LOOKUP PRODUCT" 200 "$tmp_dir/product_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingProducts" \
  --data-urlencode "\$filter=Code eq '$product_code'" --data-urlencode "\$top=1"
product_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/product_lookup.json")"

inactive_metered_payload="$(jq -cn \
  --arg product "$product_id" --arg currency "$currency_id" --arg meter "$meter_id" \
  --arg code "${code_prefix}-inactive-meter" \
  '{ProductId:$product,Code:$code,PriceType:"metered",CurrencyDefinitionId:$currency,MeterDefinitionId:$meter,UnitAmount:10}')"
expect_code "REJECT INACTIVE METER PRICE" 400 "$tmp_dir/inactive_meter_price.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices" -d "$inactive_metered_payload"

meter_action="$(jq -cn --argjson row_version "$meter_rv" '{RowVersion:$row_version}')"
expect_code "REACTIVATE METER" 204 "$tmp_dir/meter_activate.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingMeterDefinitions/$meter_id/\$action/activate" -d "$meter_action"

metered_code="${code_prefix}-metered"
metered_payload="$(jq -cn \
  --arg product "$product_id" --arg currency "$currency_id" --arg meter "$meter_id" --arg code "$metered_code" \
  '{ProductId:$product,Code:$code,PriceType:"metered",CurrencyDefinitionId:$currency,MeterDefinitionId:$meter,UnitAmount:10}')"
expect_code "CREATE METERED PRICE" 201 "$tmp_dir/metered_price.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices" -d "$metered_payload"

package_code="${code_prefix}-monthly"
package_payload="$(jq -cn \
  --arg product "$product_id" --arg currency "$currency_id" --arg code "$package_code" \
  '{ProductId:$product,Code:$code,PriceType:"recurring",CurrencyDefinitionId:$currency,UnitAmount:2500,IntervalUnit:"month",IntervalCount:1}')"
expect_code "CREATE PACKAGE PRICE" 201 "$tmp_dir/package_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices" -d "$package_payload"
expect_code "LOOKUP PACKAGE PRICE" 200 "$tmp_dir/package_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingPrices" \
  --data-urlencode "\$filter=Code eq '$package_code'" --data-urlencode "\$top=1"
package_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/package_lookup.json")"

entitlement_payload="$(jq -cn --arg price "$package_id" --arg meter "$meter_id" \
  '{PriceId:$price,MeterDefinitionId:$meter,IncludedQuantity:150,RolloverPolicy:"none",Attributes:{}}')"
expect_code "CREATE PRICE ENTITLEMENT" 201 "$tmp_dir/entitlement_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPriceEntitlements" -d "$entitlement_payload"
expect_code "LOOKUP PRICE ENTITLEMENT" 200 "$tmp_dir/entitlement_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingPriceEntitlements" \
  --data-urlencode "\$filter=PriceId eq guid'$package_id'" --data-urlencode "\$top=1"
entitlement_id="$(jq -r '.value[0].Id // empty' "$tmp_dir/entitlement_lookup.json")"
expect_code "EXPAND PRICE ENTITLEMENT REFERENCES" 200 "$tmp_dir/entitlement_expand.json" \
  -G -H "$auth_header" "$base_url/BillingPriceEntitlements" \
  --data-urlencode "\$filter=Id eq guid'$entitlement_id'" \
  --data-urlencode "\$top=1" \
  --data-urlencode "\$expand=Price(\$select=Code,PriceType,Currency),MeterDefinition(\$select=Code,Unit)"
if ! jq -e --arg price "$package_id" --arg price_code "$package_code" \
  --arg meter "$meter_id" --arg meter_code "$meter_code" '
  .value | length == 1
  and .[0].PriceId == $price
  and .[0].Price.Code == $price_code
  and .[0].Price.PriceType == "recurring"
  and .[0].Price.Currency == "USD"
  and (.[0].Price | has("ProductId") | not)
  and (.[0].Price | has("UnitAmount") | not)
  and .[0].MeterDefinitionId == $meter
  and .[0].MeterDefinition.Code == $meter_code
  and .[0].MeterDefinition.Unit == "minute"
  and (.[0].MeterDefinition | has("AggregationMode") | not)
' "$tmp_dir/entitlement_expand.json" >/dev/null; then
  echo "ERROR: Price Entitlement navigation expansion is incorrect." >&2
  exit 1
fi

create_account() {
  local tenant="$1"
  local suffix="$2"
  local code="${code_prefix}-account-${suffix}"
  local payload
  payload="$(jq -cn \
    --arg code "$code" --arg currency "$currency_id" --arg tax "$tax_code_id" \
    --arg term "$payment_term_id" --arg template "$invoice_template_id" \
    --arg discount "$discount_id" \
    '{Code:$code,DisplayName:("Account " + $code),CurrencyDefinitionId:$currency,TaxCodeId:$tax,PaymentTermId:$term,InvoiceTemplateId:$template,DiscountDefinitionId:$discount}')"
  expect_code "CREATE ACCOUNT $suffix" 201 "$tmp_dir/account_${suffix}.json" \
    -H "$auth_header" -H "Content-Type: application/json" \
    -X POST "$base_url/tenants/$tenant/BillingAccounts" -d "$payload"
  curl -sk -G -H "$auth_header" "$base_url/tenants/$tenant/BillingAccounts" \
    --data-urlencode "\$filter=Code eq '$code'" --data-urlencode "\$top=1" \
    | jq -r '.value[0].Id // empty'
}

create_subscription() {
  local tenant="$1"
  local account="$2"
  local suffix="$3"
  local payload
  payload="$(jq -cn --arg account "$account" --arg price "$package_id" --arg ref "${code_prefix}-sub-${suffix}" \
    '{AccountId:$account,PriceId:$price,StartedAt:"2026-08-01T00:00:00-04:00",CurrentPeriodStart:"2026-08-01T00:00:00-04:00",CurrentPeriodEnd:"2026-09-01T00:00:00-04:00",ExternalRef:$ref}')"
  expect_code "CREATE SUBSCRIPTION $suffix" 201 "$tmp_dir/subscription_${suffix}.json" \
    -H "$auth_header" -H "Content-Type: application/json" \
    -X POST "$base_url/tenants/$tenant/BillingSubscriptions" -d "$payload"
  curl -sk -G -H "$auth_header" "$base_url/tenants/$tenant/BillingSubscriptions" \
    --data-urlencode "\$filter=ExternalRef eq '${code_prefix}-sub-${suffix}'" --data-urlencode "\$top=1" \
    | jq -r '.value[0].Id // empty'
}

account_one="$(create_account "$tenant_one" one)"
account_two="$(create_account "$tenant_two" two)"
subscription_one="$(create_subscription "$tenant_one" "$account_one" one)"
subscription_two="$(create_subscription "$tenant_two" "$account_two" two)"
bucket_expand='PriceEntitlement($select=IncludedQuantity,PriceId,MeterDefinitionId;$expand=Price($select=Code,ProductId;$expand=Product($select=Name)),MeterDefinition($select=Code,Description,Unit)),MeterDefinition($select=Code,Description,Unit)'

expect_code "EXPAND SUBSCRIPTION REFERENCES" 200 "$tmp_dir/subscription_expand.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingSubscriptions" \
  --data-urlencode "\$filter=Id eq guid'$subscription_one'" \
  --data-urlencode "\$top=1" \
  --data-urlencode "\$expand=Account(\$select=DisplayName,Code),Price(\$select=Code,PriceType,Currency)"
if ! jq -e --arg account "$account_one" \
  --arg account_code "${code_prefix}-account-one" \
  --arg price "$package_id" --arg price_code "$package_code" '
  .value | length == 1
  and .[0].AccountId == $account
  and .[0].Account.DisplayName == ("Account " + $account_code)
  and .[0].Account.Code == $account_code
  and (.[0].Account | has("CurrencyDefinitionId") | not)
  and .[0].PriceId == $price
  and .[0].Price.Code == $price_code
  and .[0].Price.PriceType == "recurring"
  and .[0].Price.Currency == "USD"
  and (.[0].Price | has("UnitAmount") | not)
' "$tmp_dir/subscription_expand.json" >/dev/null; then
  echo "ERROR: Subscription navigation expansion is incorrect." >&2
  exit 1
fi
expect_code "TENANT ACCOUNT ISOLATION" 404 "$tmp_dir/cross_tenant_account.json" \
  -H "$auth_header" "$base_url/tenants/$tenant_one/BillingAccounts/$account_two"
expect_code "TENANT SUBSCRIPTION ISOLATION" 404 "$tmp_dir/cross_tenant_subscription.json" \
  -H "$auth_header" "$base_url/tenants/$tenant_one/BillingSubscriptions/$subscription_two"

expect_code "TENANT ONE BUCKETS" 200 "$tmp_dir/buckets_one.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingEntitlementBuckets" \
  --data-urlencode "\$filter=SubscriptionId eq guid'$subscription_one'" \
  --data-urlencode "\$expand=$bucket_expand"
expect_code "TENANT TWO BUCKETS" 200 "$tmp_dir/buckets_two.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_two/BillingEntitlementBuckets" \
  --data-urlencode "\$filter=SubscriptionId eq guid'$subscription_two'" \
  --data-urlencode "\$expand=$bucket_expand"
if ! jq -e --arg entitlement "$entitlement_id" --arg meter "$meter_id" \
  --arg price_code "$package_code" --arg product_name "Normalized package" \
  --arg meter_code "$meter_code" '
  .value | length == 1
  and .[0].PriceEntitlementId == $entitlement
  and .[0].MeterDefinitionId == $meter
  and .[0].IncludedQuantity == 150
  and .[0].GenerationSource == "subscription_activation"
  and .[0].PriceEntitlement.IncludedQuantity == 150
  and .[0].PriceEntitlement.Price.Code == $price_code
  and .[0].PriceEntitlement.Price.Product.Name == $product_name
  and .[0].PriceEntitlement.MeterDefinition.Code == $meter_code
  and .[0].PriceEntitlement.MeterDefinition.Description == "Normalized Billing E2E meter"
  and .[0].PriceEntitlement.MeterDefinition.Unit == "minute"
  and .[0].MeterDefinition.Code == $meter_code
  and .[0].MeterDefinition.Description == "Normalized Billing E2E meter"
  and .[0].MeterDefinition.Unit == "minute"
' "$tmp_dir/buckets_one.json" >/dev/null; then
  echo "ERROR: tenant one generated bucket expansion is incorrect." >&2
  exit 1
fi
if ! jq -e --arg entitlement "$entitlement_id" --arg meter "$meter_id" \
  --arg price_code "$package_code" --arg meter_code "$meter_code" '
  .value | length == 1
  and .[0].PriceEntitlementId == $entitlement
  and .[0].MeterDefinitionId == $meter
  and .[0].IncludedQuantity == 150
  and .[0].PriceEntitlement.Price.Code == $price_code
  and .[0].PriceEntitlement.MeterDefinition.Code == $meter_code
  and .[0].MeterDefinition.Code == $meter_code
' "$tmp_dir/buckets_two.json" >/dev/null; then
  echo "ERROR: tenant two did not reuse the global entitlement contract." >&2
  exit 1
fi
bucket_one="$(jq -r '.value[0].Id' "$tmp_dir/buckets_one.json")"
bucket_two="$(jq -r '.value[0].Id' "$tmp_dir/buckets_two.json")"
bucket_one_rv="$(jq -r '.value[0].RowVersion' "$tmp_dir/buckets_one.json")"
expect_code "GET EXPANDED BUCKET" 200 "$tmp_dir/bucket_expanded.json" \
  -G -H "$auth_header" \
  "$base_url/tenants/$tenant_one/BillingEntitlementBuckets/$bucket_one" \
  --data-urlencode "\$expand=$bucket_expand"
if ! jq -e --arg entitlement "$entitlement_id" --arg meter "$meter_id" \
  --arg price_code "$package_code" --arg meter_code "$meter_code" '
  .PriceEntitlementId == $entitlement
  and .MeterDefinitionId == $meter
  and .PriceEntitlement.Price.Code == $price_code
  and .PriceEntitlement.MeterDefinition.Code == $meter_code
  and .MeterDefinition.Code == $meter_code
' "$tmp_dir/bucket_expanded.json" >/dev/null; then
  echo "ERROR: entity-by-ID bucket expansion is incorrect." >&2
  exit 1
fi
expect_code "TENANT ISOLATION" 404 "$tmp_dir/cross_tenant_bucket.json" \
  -G -H "$auth_header" \
  "$base_url/tenants/$tenant_one/BillingEntitlementBuckets/$bucket_two" \
  --data-urlencode "\$expand=$bucket_expand"

adjust_payload="$(jq -cn --argjson rv "$bucket_one_rv" \
  '{RowVersion:$rv,QuantityDelta:5,Reason:"E2E correction",IdempotencyKey:"normalized-e2e-adjust"}')"
expect_code "ADJUST BUCKET" 204 "$tmp_dir/adjust_bucket.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingEntitlementBuckets/$bucket_one/\$action/adjust" \
  -d "$adjust_payload"
expect_code "GET ADJUSTED BUCKET" 200 "$tmp_dir/adjusted_bucket.json" \
  -H "$auth_header" "$base_url/tenants/$tenant_one/BillingEntitlementBuckets/$bucket_one"
if ! jq -e '.AdjustmentQuantity == 5' "$tmp_dir/adjusted_bucket.json" >/dev/null; then
  echo "ERROR: guarded entitlement adjustment was not applied." >&2
  exit 1
fi

expect_code "GET SUBSCRIPTION" 200 "$tmp_dir/subscription_one.json" \
  -H "$auth_header" "$base_url/tenants/$tenant_one/BillingSubscriptions/$subscription_one"
if ! jq -e --arg tax "$tax_code_id" --arg term "$payment_term_id" \
  --arg template "$invoice_template_id" --arg discount "$discount_id" '
  .TaxCodeId == $tax
  and .PaymentTermId == $term
  and .InvoiceTemplateId == $template
  and .DiscountDefinitionId == $discount
' "$tmp_dir/subscription_one.json" >/dev/null; then
  echo "ERROR: Subscription did not inherit global account references." >&2
  exit 1
fi
subscription_rv="$(jq -r '.RowVersion' "$tmp_dir/subscription_one.json")"
reconcile_payload="$(jq -cn --argjson rv "$subscription_rv" '{RowVersion:$rv}')"
expect_code "RECONCILE SUBSCRIPTION" 204 "$tmp_dir/reconcile.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingSubscriptions/$subscription_one/\$action/reconcile_entitlements" \
  -d "$reconcile_payload"
expect_code "BUCKETS AFTER RECONCILE" 200 "$tmp_dir/buckets_reconciled.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingEntitlementBuckets" \
  --data-urlencode "\$filter=SubscriptionId eq guid'$subscription_one'" \
  --data-urlencode "\$expand=$bucket_expand"
if ! jq -e --arg price_code "$package_code" --arg meter_code "$meter_code" '
  .value | length == 1
  and .[0].IncludedQuantity == 150
  and .[0].PriceEntitlement.Price.Code == $price_code
  and .[0].PriceEntitlement.MeterDefinition.Code == $meter_code
  and .[0].MeterDefinition.Code == $meter_code
' "$tmp_dir/buckets_reconciled.json" >/dev/null; then
  echo "ERROR: reconciliation duplicated or mutated a historical allowance." >&2
  exit 1
fi

run_definition_code="${code_prefix}-monthly-run"
run_definition_payload="$(jq -cn --arg code "$run_definition_code" \
  '{Code:$code,DisplayName:"Monthly billing",Frequency:"monthly",IntervalCount:1,Timezone:"America/Guyana",Attributes:{}}')"
expect_code "CREATE RUN DEFINITION" 201 "$tmp_dir/run_definition_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingRunDefinitions" -d "$run_definition_payload"
expect_code "LOOKUP RUN DEFINITION" 200 "$tmp_dir/run_definition_lookup.json" \
  -G -H "$auth_header" "$base_url/BillingRunDefinitions" \
  --data-urlencode "\$filter=Code eq '$run_definition_code'" --data-urlencode "\$top=1"
run_definition_id="$(jq -r '.value[0].Id' "$tmp_dir/run_definition_lookup.json")"

run_key="${code_prefix}-run-september"
run_payload="$(jq -cn \
  --arg account "$account_one" --arg subscription "$subscription_one" \
  --arg definition "$run_definition_id" --arg key "$run_key" \
  '{AccountId:$account,SubscriptionId:$subscription,DefinitionId:$definition,PeriodStart:"2026-09-01T00:00:00-04:00",PeriodEnd:"2026-10-01T00:00:00-04:00",IdempotencyKey:$key}')"
expect_code "CREATE BILLING RUN" 201 "$tmp_dir/run_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingRuns" -d "$run_payload"
expect_code "REPLAY BILLING RUN CREATE" 201 "$tmp_dir/run_replay.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingRuns" -d "$run_payload"
expect_code "LOOKUP BILLING RUN" 200 "$tmp_dir/run_lookup.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingRuns" \
  --data-urlencode "\$filter=IdempotencyKey eq '$run_key'" --data-urlencode "\$top=2"
if ! jq -e '.value | length == 1' "$tmp_dir/run_lookup.json" >/dev/null; then
  echo "ERROR: Billing Run idempotency created duplicate executions." >&2
  exit 1
fi
run_id="$(jq -r '.value[0].Id' "$tmp_dir/run_lookup.json")"
run_rv="$(jq -r '.value[0].RowVersion' "$tmp_dir/run_lookup.json")"
run_action="$(jq -cn --argjson rv "$run_rv" '{RowVersion:$rv}')"
expect_code "START BILLING RUN" 204 "$tmp_dir/run_start.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingRuns/$run_id/\$action/start" -d "$run_action"
expect_code "GET RUNNING BILLING RUN" 200 "$tmp_dir/run_running.json" \
  -H "$auth_header" "$base_url/tenants/$tenant_one/BillingRuns/$run_id"
run_rv="$(jq -r '.RowVersion' "$tmp_dir/run_running.json")"
run_action="$(jq -cn --argjson rv "$run_rv" '{RowVersion:$rv}')"
expect_code "COMPLETE BILLING RUN" 204 "$tmp_dir/run_complete.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingRuns/$run_id/\$action/complete" -d "$run_action"

invoice_payload="$(jq -cn --arg account "$account_one" --arg subscription "$subscription_one" --arg run "$run_id" \
  '{AccountId:$account,SubscriptionId:$subscription,BillingRunId:$run}')"
expect_code "CREATE RUN INVOICE" 201 "$tmp_dir/invoice_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingInvoices" -d "$invoice_payload"
expect_code "LOOKUP RUN INVOICE" 200 "$tmp_dir/invoice_lookup.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingInvoices" \
  --data-urlencode "\$filter=BillingRunId eq guid'$run_id'" --data-urlencode "\$top=1"
if ! jq -e --arg currency "$currency_id" --arg tax "$tax_code_id" \
  --arg term "$payment_term_id" --arg template "$invoice_template_id" \
  --arg discount "$discount_id" '
  .value | length == 1
  and .[0].CurrencyDefinitionId == $currency
  and .[0].TaxCodeId == $tax
  and .[0].PaymentTermId == $term
  and .[0].InvoiceTemplateId == $template
  and .[0].DiscountDefinitionId == $discount
' "$tmp_dir/invoice_lookup.json" >/dev/null; then
  echo "ERROR: Invoice did not snapshot the selected global references." >&2
  exit 1
fi
invoice_id="$(jq -r '.value[0].Id' "$tmp_dir/invoice_lookup.json")"
invoice_line_payload="$(jq -cn --arg invoice "$invoice_id" --arg tax "$tax_code_id" --arg rate "$tax_rate_id" \
  '{InvoiceId:$invoice,TaxCodeId:$tax,TaxRateId:$rate,Quantity:1,Amount:100}')"
expect_code "CREATE TAXED INVOICE LINE" 201 "$tmp_dir/invoice_line_create.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/tenants/$tenant_one/BillingInvoiceLines" -d "$invoice_line_payload"

expect_code "BUCKETS AFTER RUN" 200 "$tmp_dir/buckets_after_run.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingEntitlementBuckets" \
  --data-urlencode "\$filter=SubscriptionId eq guid'$subscription_one'"
if ! jq -e --arg run "$run_id" '
  .value | length == 2
  and any(.[]; .BillingRunId == $run and .IncludedQuantity == 150 and .GenerationSource == "billing_run")
' "$tmp_dir/buckets_after_run.json" >/dev/null; then
  echo "ERROR: Billing Run did not open exactly one new entitlement period." >&2
  exit 1
fi

expect_code "GET REFERENCED METER" 200 "$tmp_dir/meter_referenced.json" \
  -H "$auth_header" "$base_url/BillingMeterDefinitions/$meter_id"
meter_rv="$(jq -r '.RowVersion' "$tmp_dir/meter_referenced.json")"
meter_action="$(jq -cn --argjson row_version "$meter_rv" '{RowVersion:$row_version}')"
expect_code "BLOCK REFERENCED METER DEACTIVATION" 409 "$tmp_dir/meter_blocked.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingMeterDefinitions/$meter_id/\$action/deactivate" -d "$meter_action"

expect_code "GET REFERENCED PACKAGE PRICE" 200 "$tmp_dir/package_referenced.json" \
  -H "$auth_header" "$base_url/BillingPrices/$package_id"
package_rv="$(jq -r '.RowVersion' "$tmp_dir/package_referenced.json")"
package_action="$(jq -cn --argjson row_version "$package_rv" '{RowVersion:$row_version}')"
expect_code "ARCHIVE REFERENCED PACKAGE PRICE" 204 "$tmp_dir/package_archive.json" \
  -H "$auth_header" -H "Content-Type: application/json" \
  -X POST "$base_url/BillingPrices/$package_id/\$action/archive" -d "$package_action"

expect_code "EXPAND ARCHIVED ENTITLEMENT PRICE" 200 "$tmp_dir/archived_entitlement_expand.json" \
  -G -H "$auth_header" "$base_url/BillingPriceEntitlements" \
  --data-urlencode "\$filter=Id eq guid'$entitlement_id'" \
  --data-urlencode "\$top=1" \
  --data-urlencode "\$expand=Price(\$select=Code,PriceType,Currency)"
if ! jq -e --arg price_code "$package_code" '
  .value | length == 1
  and .[0].Price.Code == $price_code
  and .[0].Price.IsArchived == true
  and .[0].Price.DeletedAt != null
' "$tmp_dir/archived_entitlement_expand.json" >/dev/null; then
  echo "ERROR: Price Entitlement did not resolve its archived Price." >&2
  exit 1
fi

expect_code "EXPAND ARCHIVED SUBSCRIPTION PRICE" 200 "$tmp_dir/archived_subscription_expand.json" \
  -G -H "$auth_header" "$base_url/tenants/$tenant_one/BillingSubscriptions" \
  --data-urlencode "\$filter=Id eq guid'$subscription_one'" \
  --data-urlencode "\$top=1" \
  --data-urlencode "\$expand=Price(\$select=Code,PriceType,Currency)"
if ! jq -e --arg price_code "$package_code" '
  .value | length == 1
  and .[0].Price.Code == $price_code
  and .[0].Price.IsArchived == true
  and .[0].Price.DeletedAt != null
' "$tmp_dir/archived_subscription_expand.json" >/dev/null; then
  echo "ERROR: Subscription did not resolve its archived Price." >&2
  exit 1
fi

expect_code "EXPAND BUCKET ARCHIVED CATALOG REFERENCES" 200 \
  "$tmp_dir/bucket_archived_catalog_expand.json" \
  -G -H "$auth_header" \
  "$base_url/tenants/$tenant_one/BillingEntitlementBuckets/$bucket_one" \
  --data-urlencode "\$expand=$bucket_expand"
if ! jq -e --arg entitlement "$entitlement_id" --arg meter "$meter_id" \
  --arg price_code "$package_code" --arg meter_code "$meter_code" '
  .PriceEntitlementId == $entitlement
  and .MeterDefinitionId == $meter
  and .PriceEntitlement.Price.Code == $price_code
  and .PriceEntitlement.Price.IsArchived == true
  and .PriceEntitlement.Price.DeletedAt != null
  and .PriceEntitlement.MeterDefinition.Code == $meter_code
  and .MeterDefinition.Code == $meter_code
' "$tmp_dir/bucket_archived_catalog_expand.json" >/dev/null; then
  echo "ERROR: bucket did not resolve its historical global catalog references." >&2
  exit 1
fi

echo "PASS: normalized Billing global definitions and tenant operations"
