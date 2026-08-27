"""Integration tests for the Ops Metering to Billing usage handoff."""

from datetime import datetime, timezone
import unittest
import uuid

from werkzeug.exceptions import HTTPException

from mugen.core.plugin.billing.service.usage_event import UsageEventService
from mugen.core.plugin.ops_metering.api.validation import UsageRecordRateValidation
from mugen.core.plugin.ops_metering.service.usage_record import UsageRecordService
from mugen_test.test_billing_normalized_workflows import _MemoryGateway


class TestOpsMeteringBillingUsageHandoff(unittest.IsolatedAsyncioTestCase):
    """Exercises rating through the real Billing UsageEventService contract."""

    async def asyncSetUp(self) -> None:
        self.rsg = _MemoryGateway()
        self.tenant_id = uuid.uuid4()
        self.meter_definition_id = uuid.uuid4()
        self.meter_code = "ops.canonical.units"
        await self.rsg.insert_one(
            "billing_meter_definition",
            {
                "id": self.meter_definition_id,
                "code": self.meter_code,
                "unit": "unit",
                "aggregation_mode": "sum",
                "is_active": True,
            },
        )

    async def test_rating_creates_canonical_idempotent_billing_event(self) -> None:
        account_id = uuid.uuid4()
        subscription_id = uuid.uuid4()
        price_id = uuid.uuid4()
        occurred_at = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        service = UsageRecordService("ops_metering_usage_record", self.rsg)
        record = await service.create(
            {
                "tenant_id": self.tenant_id,
                "account_id": account_id,
                "subscription_id": subscription_id,
                "price_id": price_id,
                "meter_definition_id": self.meter_definition_id,
                "occurred_at": occurred_at,
                "measured_units": 7,
                "status": "recorded",
            }
        )

        action = {
            "tenant_id": self.tenant_id,
            "entity_id": record.id,
            "where": {"tenant_id": self.tenant_id, "id": record.id},
            "auth_user_id": uuid.uuid4(),
        }
        self.assertEqual(
            await service.action_rate_record(
                **action,
                data=UsageRecordRateValidation(row_version=1),
            ),
            ("", 204),
        )

        events = self.rsg.rows["billing_usage_event"]
        rated_rows = self.rsg.rows["ops_metering_rated_usage"]
        self.assertEqual(len(events), 1)
        self.assertEqual(len(rated_rows), 1)

        event = events[0]
        rated = rated_rows[0]
        self.assertEqual(event["tenant_id"], self.tenant_id)
        self.assertEqual(event["account_id"], account_id)
        self.assertEqual(event["subscription_id"], subscription_id)
        self.assertEqual(event["price_id"], price_id)
        self.assertEqual(event["meter_definition_id"], self.meter_definition_id)
        self.assertEqual(rated["meter_definition_id"], self.meter_definition_id)
        self.assertEqual(event["meter_code"], self.meter_code)
        self.assertEqual(event["quantity"], 7)
        self.assertEqual(rated["billing_usage_event_id"], event["id"])

        self.assertEqual(
            await service.action_rate_record(
                **action,
                data=UsageRecordRateValidation(row_version=2),
            ),
            ("", 204),
        )
        self.assertEqual(len(self.rsg.rows["billing_usage_event"]), 1)
        self.assertEqual(len(self.rsg.rows["ops_metering_rated_usage"]), 1)

    async def test_usage_event_rejects_missing_and_inactive_meter(self) -> None:
        service = UsageEventService("billing_usage_event", self.rsg)
        inactive_meter_id = uuid.uuid4()
        await self.rsg.insert_one(
            "billing_meter_definition",
            {
                "id": inactive_meter_id,
                "code": "ops.inactive.units",
                "is_active": False,
            },
        )

        for meter_definition_id in (uuid.uuid4(), inactive_meter_id):
            with self.subTest(meter_definition_id=meter_definition_id):
                with self.assertRaises(HTTPException) as raised:
                    await service.create(
                        {
                            "tenant_id": self.tenant_id,
                            "account_id": uuid.uuid4(),
                            "meter_definition_id": meter_definition_id,
                            "quantity": 1,
                        }
                    )
                self.assertEqual(raised.exception.code, 400)
                self.assertEqual(
                    raised.exception.description,
                    "MeterDefinitionId must reference an active global meter.",
                )

