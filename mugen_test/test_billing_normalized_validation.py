"""Validation coverage for normalized global and tenant billing contracts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
import uuid

from pydantic import ValidationError

from mugen.core.plugin.billing.api import validation as validation_mod
from mugen.core.plugin.billing.api.validation import (
    BillingDiscountDefinitionCreateValidation,
    BillingDiscountDefinitionUpdateValidation,
    BillingEntitlementAdjustValidation,
    BillingInvoiceTemplateCreateValidation,
    BillingInvoiceTemplateUpdateValidation,
    BillingMeterDefinitionCreateValidation,
    BillingMeterDefinitionUpdateValidation,
    BillingPaymentTermCreateValidation,
    BillingPaymentTermUpdateValidation,
    BillingPriceCreateValidation,
    BillingPriceEntitlementCreateValidation,
    BillingPriceEntitlementUpdateValidation,
    BillingRunCreateValidation,
    BillingRunDefinitionCreateValidation,
    BillingRunDefinitionUpdateValidation,
    BillingRunFailValidation,
    BillingRunRetryValidation,
    BillingSubscriptionCreateValidation,
    BillingSubscriptionPeriodValidation,
    BillingTaxCodeCreateValidation,
    BillingTaxCodeUpdateValidation,
    BillingTaxRateCreateValidation,
    BillingTaxRateUpdateValidation,
)


class TestNormalizedBillingValidation(unittest.TestCase):
    """Cover normalization, global-safety, and temporal validation branches."""

    def setUp(self) -> None:
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        self.later = self.now + timedelta(days=1)
        self.identifiers = [uuid.uuid4() for _ in range(8)]

    def assert_invalid(self, schema, **values) -> None:
        with self.assertRaises(ValidationError):
            schema(**values)

    def test_global_helpers_reject_tenant_and_sensitive_attributes(self) -> None:
        base = (
            validation_mod._GlobalCatalogValidation
        )  # pylint: disable=protected-access
        self.assertEqual(base._reject_tenant_id("payload"), "payload")
        self.assertEqual(base._required_text(" value ", "Field"), "value")
        self.assertIsNone(base._optional_text(None, "Field"))
        self.assertEqual(base._optional_text(" value ", "Field"), "value")
        self.assertIsNone(base._normalize_attributes(None))
        safe = {"module": {"features": ["one", {"kind": "two"}]}}
        self.assertIs(base._normalize_attributes(safe), safe)
        with self.assertRaises(ValueError):
            base._required_text(None, "Field")
        with self.assertRaises(ValueError):
            base._required_text(" ", "Field")
        with self.assertRaises(ValueError):
            base._optional_text(" ", "Field")
        for payload in (
            {"TenantId": str(uuid.uuid4())},
            {"tenant_id": str(uuid.uuid4())},
        ):
            with self.assertRaises(ValueError):
                base._reject_tenant_id(payload)
        for attributes in (
            {"email": "customer@example.invalid"},
            {"nested": [{"api_secret_value": "redacted"}]},
        ):
            with self.assertRaises(ValueError):
                base._normalize_attributes(attributes)

    def test_meter_and_entitlement_validators(self) -> None:
        meter = BillingMeterDefinitionCreateValidation(
            code=" Demo.Meter ",
            unit=" Minute ",
            aggregation_mode=" SUM ",
            description=" Useful ",
            attributes={"module_key": "demo"},
        )
        self.assertEqual(
            (meter.code, meter.unit, meter.aggregation_mode, meter.description),
            ("demo.meter", "minute", "sum", "Useful"),
        )
        for field_name, value in (
            ("unit", "second"),
            ("aggregation_mode", "average"),
        ):
            values = {"code": "demo", "unit": "unit"}
            values[field_name] = value
            self.assert_invalid(BillingMeterDefinitionCreateValidation, **values)

        update = BillingMeterDefinitionUpdateValidation(
            code=" NEW ",
            unit=" TASK ",
            aggregation_mode=" LATEST ",
            description=None,
            attributes={"safe": True},
        )
        self.assertEqual((update.code, update.unit), ("new", "task"))
        self.assert_invalid(BillingMeterDefinitionUpdateValidation)
        self.assert_invalid(BillingMeterDefinitionUpdateValidation, unit="second")
        self.assert_invalid(
            BillingMeterDefinitionUpdateValidation,
            aggregation_mode="average",
        )

        price_id, meter_id = self.identifiers[:2]
        entitlement = BillingPriceEntitlementCreateValidation(
            price_id=price_id,
            meter_definition_id=meter_id,
            included_quantity=0,
            rollover_policy=" NONE ",
            attributes={"safe": []},
        )
        self.assertEqual(entitlement.rollover_policy, "none")
        self.assert_invalid(
            BillingPriceEntitlementCreateValidation,
            price_id=price_id,
            meter_definition_id=meter_id,
            included_quantity=1,
            rollover_policy="carry",
        )
        self.assert_invalid(BillingPriceEntitlementUpdateValidation)
        for field_name in ("price_id", "meter_definition_id", "included_quantity"):
            self.assert_invalid(
                BillingPriceEntitlementUpdateValidation,
                **{field_name: None},
            )
        entitlement_update = BillingPriceEntitlementUpdateValidation(
            price_id=price_id,
            meter_definition_id=meter_id,
            included_quantity=10,
            rollover_policy=" NONE ",
            attributes={"safe": True},
        )
        self.assertEqual(entitlement_update.included_quantity, 10)
        self.assert_invalid(
            BillingPriceEntitlementUpdateValidation,
            rollover_policy="carry",
        )

    def test_named_definition_validators(self) -> None:
        run = BillingRunDefinitionCreateValidation(
            code=" MONTHLY ",
            display_name=" Monthly ",
            description=" Standard ",
            frequency=" MONTHLY ",
            interval_count=1,
            timezone=" America/Guyana ",
            attributes={"safe": True},
        )
        self.assertEqual((run.code, run.frequency), ("monthly", "monthly"))
        for field_name, value in (
            ("frequency", "sometimes"),
            ("timezone", "Invalid/Nowhere"),
        ):
            values = {
                "code": "monthly",
                "display_name": "Monthly",
                "frequency": "monthly",
                "timezone": "UTC",
            }
            values[field_name] = value
            self.assert_invalid(BillingRunDefinitionCreateValidation, **values)
        run_update = BillingRunDefinitionUpdateValidation(
            code=" DAILY ",
            display_name=" Daily ",
            description=None,
            frequency=" DAILY ",
            interval_count=2,
            timezone=" UTC ",
            attributes={"safe": "value"},
        )
        self.assertEqual(run_update.frequency, "daily")
        self.assert_invalid(BillingRunDefinitionUpdateValidation)
        self.assert_invalid(BillingRunDefinitionUpdateValidation, frequency="sometimes")
        self.assert_invalid(BillingRunDefinitionUpdateValidation, interval_count=None)
        self.assert_invalid(
            BillingRunDefinitionUpdateValidation,
            timezone="Invalid/Nowhere",
        )

        tax_code = BillingTaxCodeCreateValidation(
            code=" VAT ",
            display_name=" Value added tax ",
            description=None,
            attributes={"safe": 1},
        )
        self.assertEqual(tax_code.code, "vat")
        tax_update = BillingTaxCodeUpdateValidation(
            code=" SALES ",
            display_name=" Sales tax ",
            description=None,
            attributes={"safe": 2},
        )
        self.assertEqual(tax_update.code, "sales")
        self.assert_invalid(BillingTaxCodeUpdateValidation)

        term = BillingPaymentTermCreateValidation(
            code=" NET30 ",
            display_name=" Net 30 ",
            due_days=30,
        )
        self.assertEqual(term.code, "net30")
        term_update = BillingPaymentTermUpdateValidation(
            code=" NET45 ",
            display_name=" Net 45 ",
            description=None,
            attributes={"safe": True},
            due_days=45,
        )
        self.assertEqual(term_update.due_days, 45)
        self.assert_invalid(BillingPaymentTermUpdateValidation, due_days=None)

        template = BillingInvoiceTemplateCreateValidation(
            code=" DEFAULT ",
            display_name=" Default ",
            locale=" en-GY ",
            template_format=" HTML ",
            subject_template=" Invoice ",
            body_template=" <p>Invoice</p> ",
        )
        self.assertEqual(template.template_format, "html")
        self.assert_invalid(
            BillingInvoiceTemplateCreateValidation,
            code="bad",
            display_name="Bad",
            locale="en",
            template_format="pdf",
            body_template="body",
        )
        template_update = BillingInvoiceTemplateUpdateValidation(
            code=" TEXT ",
            display_name=" Text ",
            description=None,
            attributes={"safe": True},
            locale=" en ",
            template_format=" TEXT ",
            subject_template=None,
            body_template=" Body ",
        )
        self.assertEqual(template_update.body_template, "Body")
        self.assert_invalid(BillingInvoiceTemplateUpdateValidation)
        self.assert_invalid(
            BillingInvoiceTemplateUpdateValidation,
            template_format="pdf",
        )

    def test_tax_rate_validators(self) -> None:
        tax_code_id = self.identifiers[0]
        rate = BillingTaxRateCreateValidation(
            code=" GY-VAT ",
            tax_code_id=tax_code_id,
            jurisdiction_code=" GY ",
            rate_basis_points=1400,
            effective_from=self.now,
            effective_to=self.later,
            attributes={"safe": True},
        )
        self.assertEqual((rate.code, rate.jurisdiction_code), ("gy-vat", "gy"))
        common = {
            "code": "rate",
            "tax_code_id": tax_code_id,
            "jurisdiction_code": "gy",
            "rate_basis_points": 100,
            "effective_from": self.now,
        }
        self.assert_invalid(
            BillingTaxRateCreateValidation,
            **{**common, "rate_basis_points": 10001},
        )
        self.assert_invalid(
            BillingTaxRateCreateValidation,
            **{**common, "effective_from": self.now.replace(tzinfo=None)},
        )
        self.assert_invalid(
            BillingTaxRateCreateValidation,
            **{**common, "effective_to": self.now},
        )

        update = BillingTaxRateUpdateValidation(
            code=" RATE-2 ",
            tax_code_id=tax_code_id,
            jurisdiction_code=" US-NY ",
            rate_basis_points=200,
            effective_from=self.now,
            effective_to=self.later,
            attributes={"safe": True},
        )
        self.assertEqual(update.code, "rate-2")
        self.assert_invalid(BillingTaxRateUpdateValidation)
        self.assert_invalid(BillingTaxRateUpdateValidation, tax_code_id=None)
        self.assert_invalid(BillingTaxRateUpdateValidation, rate_basis_points=10001)
        self.assert_invalid(BillingTaxRateUpdateValidation, effective_from=None)
        self.assert_invalid(
            BillingTaxRateUpdateValidation,
            effective_from=self.now.replace(tzinfo=None),
        )
        self.assert_invalid(
            BillingTaxRateUpdateValidation,
            effective_to=self.now.replace(tzinfo=None),
        )

    def test_discount_validators(self) -> None:
        currency_id = self.identifiers[0]
        percentage = BillingDiscountDefinitionCreateValidation(
            code=" SUMMER ",
            display_name=" Summer ",
            kind=" PERCENTAGE ",
            percentage_basis_points=1000,
            coupon_code=" SAVE10 ",
            valid_from=self.now,
            valid_until=self.later,
        )
        self.assertEqual(percentage.coupon_code, "save10")
        fixed = BillingDiscountDefinitionCreateValidation(
            code=" FIXED ",
            display_name=" Fixed ",
            kind=" FIXED_AMOUNT ",
            amount=500,
            currency_definition_id=currency_id,
        )
        self.assertEqual(fixed.kind, "fixed_amount")

        base = {"code": "bad", "display_name": "Bad"}
        invalid_benefits = (
            {"kind": "percentage"},
            {"kind": "percentage", "percentage_basis_points": 10001},
            {
                "kind": "percentage",
                "percentage_basis_points": 100,
                "amount": 1,
            },
            {"kind": "fixed_amount", "amount": 1},
            {
                "kind": "fixed_amount",
                "amount": 1,
                "currency_definition_id": currency_id,
                "percentage_basis_points": 1,
            },
            {"kind": "mystery"},
            {
                "kind": "percentage",
                "percentage_basis_points": 100,
                "valid_from": self.later,
                "valid_until": self.now,
            },
            {
                "kind": "percentage",
                "percentage_basis_points": 100,
                "valid_from": self.now.replace(tzinfo=None),
            },
        )
        for benefit in invalid_benefits:
            self.assert_invalid(
                BillingDiscountDefinitionCreateValidation,
                **base,
                **benefit,
            )

        update = BillingDiscountDefinitionUpdateValidation(
            display_name=" Updated ",
            description=None,
            coupon_code=" NEW ",
            valid_from=self.now,
            valid_until=self.later,
            attributes={"safe": True},
        )
        self.assertEqual(update.coupon_code, "new")
        self.assert_invalid(BillingDiscountDefinitionUpdateValidation)
        self.assert_invalid(
            BillingDiscountDefinitionUpdateValidation,
            valid_from=self.later,
            valid_until=self.now,
        )
        self.assert_invalid(
            BillingDiscountDefinitionUpdateValidation,
            valid_until=self.now.replace(tzinfo=None),
        )

    def test_tenant_operation_validators(self) -> None:
        tenant_id, account_id, price_id, definition_id = self.identifiers[:4]
        subscription = BillingSubscriptionCreateValidation(
            tenant_id=tenant_id,
            account_id=account_id,
            price_id=price_id,
            started_at=self.now,
            current_period_start=self.now,
            current_period_end=self.later,
            external_ref=" SUB-1 ",
        )
        self.assertEqual(subscription.external_ref, "SUB-1")
        BillingSubscriptionCreateValidation(
            tenant_id=tenant_id,
            account_id=account_id,
            price_id=price_id,
            external_ref=" ",
        )
        self.assert_invalid(
            BillingSubscriptionCreateValidation,
            tenant_id=tenant_id,
            account_id=account_id,
            price_id=price_id,
            started_at=self.now.replace(tzinfo=None),
        )
        self.assert_invalid(
            BillingSubscriptionCreateValidation,
            tenant_id=tenant_id,
            account_id=account_id,
            price_id=price_id,
            current_period_start=self.now,
        )
        self.assert_invalid(
            BillingSubscriptionCreateValidation,
            tenant_id=tenant_id,
            account_id=account_id,
            price_id=price_id,
            current_period_start=self.later,
            current_period_end=self.now,
        )

        period = BillingSubscriptionPeriodValidation(
            row_version=1,
            period_start=self.now,
            period_end=self.later,
        )
        self.assertEqual(period.period_start, self.now)
        self.assert_invalid(
            BillingSubscriptionPeriodValidation,
            row_version=1,
            period_start=self.now,
        )
        self.assert_invalid(
            BillingSubscriptionPeriodValidation,
            row_version=1,
            period_start=self.later,
            period_end=self.now,
        )
        self.assert_invalid(
            BillingSubscriptionPeriodValidation,
            row_version=1,
            period_end=self.now.replace(tzinfo=None),
        )

        run = BillingRunCreateValidation(
            tenant_id=tenant_id,
            account_id=account_id,
            subscription_id=uuid.uuid4(),
            definition_id=definition_id,
            period_start=self.now,
            period_end=self.later,
            idempotency_key=" RUN-1 ",
            external_ref=" REF ",
        )
        self.assertEqual((run.idempotency_key, run.external_ref), ("RUN-1", "REF"))
        run_base = {
            "tenant_id": tenant_id,
            "definition_id": definition_id,
            "period_start": self.now,
            "period_end": self.later,
            "idempotency_key": "run",
        }
        self.assert_invalid(
            BillingRunCreateValidation,
            **{**run_base, "period_start": self.later},
        )
        self.assert_invalid(
            BillingRunCreateValidation,
            **{**run_base, "idempotency_key": " "},
        )
        self.assert_invalid(
            BillingRunCreateValidation,
            **{**run_base, "subscription_id": uuid.uuid4()},
        )
        self.assert_invalid(
            BillingRunCreateValidation,
            **{**run_base, "period_start": self.now.replace(tzinfo=None)},
        )

        failure = BillingRunFailValidation(
            row_version=1,
            failure_code=" TIMEOUT ",
            failure_detail=" Retry later ",
        )
        self.assertEqual(failure.failure_code, "timeout")
        self.assert_invalid(
            BillingRunFailValidation,
            row_version=1,
            failure_code=" ",
            failure_detail="detail",
        )
        retry = BillingRunRetryValidation(row_version=1, idempotency_key=" retry ")
        self.assertEqual(retry.idempotency_key, "retry")
        self.assert_invalid(
            BillingRunRetryValidation,
            row_version=1,
            idempotency_key=" ",
        )
        adjustment = BillingEntitlementAdjustValidation(
            row_version=1,
            quantity_delta=1,
            reason=" Correction ",
            idempotency_key=" adjust-1 ",
        )
        self.assertEqual(adjustment.reason, "Correction")
        self.assert_invalid(
            BillingEntitlementAdjustValidation,
            row_version=1,
            quantity_delta=0,
            reason="reason",
            idempotency_key="key",
        )
        self.assert_invalid(
            BillingEntitlementAdjustValidation,
            row_version=1,
            quantity_delta=1,
            reason=" ",
            idempotency_key="key",
        )

    def test_unmetered_price_rejects_meter_reference(self) -> None:
        self.assert_invalid(
            BillingPriceCreateValidation,
            product_id=self.identifiers[0],
            code="package",
            price_type="recurring",
            currency_definition_id=self.identifiers[1],
            meter_definition_id=self.identifiers[2],
        )

    def test_optional_update_paths_can_omit_unrelated_fields(self) -> None:
        """Each update schema accepts a narrow patch without touching later fields."""
        self.assertEqual(
            BillingMeterDefinitionUpdateValidation(description=" Text ").description,
            "Text",
        )
        self.assertEqual(
            BillingMeterDefinitionUpdateValidation(
                attributes={"safe": True}
            ).attributes,
            {"safe": True},
        )
        self.assertEqual(
            BillingPriceEntitlementUpdateValidation(
                included_quantity=1
            ).included_quantity,
            1,
        )
        self.assertEqual(
            BillingRunDefinitionUpdateValidation(frequency="daily").frequency,
            "daily",
        )
        self.assertEqual(
            BillingTaxRateUpdateValidation(code=" Rate ").code,
            "rate",
        )
        self.assertEqual(
            BillingInvoiceTemplateUpdateValidation(locale=" en ").locale,
            "en",
        )
        self.assertEqual(
            BillingDiscountDefinitionUpdateValidation(
                display_name=" Updated "
            ).display_name,
            "Updated",
        )
        self.assertIsNone(
            BillingDiscountDefinitionUpdateValidation(coupon_code=None).coupon_code
        )
        BillingSubscriptionCreateValidation(
            tenant_id=self.identifiers[0],
            account_id=self.identifiers[1],
            price_id=self.identifiers[2],
        )
        BillingRunCreateValidation(
            tenant_id=self.identifiers[0],
            definition_id=self.identifiers[1],
            period_start=self.now,
            period_end=self.later,
            idempotency_key="run",
        )


if __name__ == "__main__":
    unittest.main()
