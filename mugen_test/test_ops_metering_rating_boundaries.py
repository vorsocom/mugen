"""Unit tests for ops_metering rating caps, multipliers, and windows."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_metering.api.validation import UsageRecordRateValidation
from mugen.core.plugin.ops_metering.domain import (
    MeterDefinitionDE,
    MeterPolicyDE,
    RatedUsageDE,
    UsageRecordDE,
)
from mugen.core.plugin.ops_metering.service.usage_record import UsageRecordService


class TestOpsMeteringRatingBoundaries(unittest.IsolatedAsyncioTestCase):
    """Tests policy-driven rating boundaries in UsageRecordService."""

    async def test_rate_record_applies_caps_multiplier_and_rounding(self) -> None:
        tenant_id = uuid.uuid4()
        record_id = uuid.uuid4()
        meter_definition_id = uuid.uuid4()
        account_id = uuid.uuid4()
        now = datetime(2026, 2, 13, 16, 30, tzinfo=timezone.utc)

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        svc._now_utc = lambda: now

        current = UsageRecordDE(
            id=record_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            account_id=account_id,
            measured_units=10,
            status="recorded",
            row_version=2,
            occurred_at=now,
        )

        policy = MeterPolicyDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            cap_units=8,
            multiplier_bps=15000,
            rounding_mode="up",
            rounding_step=2,
            is_active=True,
        )

        rated = RatedUsageDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            usage_record_id=record_id,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._meter_definition_service.get = AsyncMock(
            return_value=MeterDefinitionDE(
                id=meter_definition_id,
                tenant_id=tenant_id,
                code="ops.units",
                unit="unit",
            )
        )
        svc._meter_policy_service.list = AsyncMock(return_value=[policy])
        svc._rated_usage_service.get = AsyncMock(return_value=None)
        svc._rated_usage_service.create = AsyncMock(return_value=rated)
        svc._rated_usage_service.update = AsyncMock(return_value=rated)
        svc._usage_event_service.get = AsyncMock(return_value=None)
        svc._usage_event_service.create = AsyncMock(
            return_value=SimpleNamespace(id=uuid.uuid4())
        )

        result = await svc.action_rate_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where={"tenant_id": tenant_id, "id": record_id},
            auth_user_id=uuid.uuid4(),
            data=UsageRecordRateValidation(row_version=2),
        )

        self.assertEqual(result, ("", 204))
        rated_payload = svc._rated_usage_service.create.await_args.args[0]
        self.assertEqual(rated_payload["measured_quantity"], 10)
        self.assertEqual(rated_payload["capped_quantity"], 8)
        self.assertEqual(rated_payload["billable_quantity"], 12)

        billing_payload = svc._usage_event_service.create.await_args.args[0]
        self.assertEqual(billing_payload["quantity"], 12)
        self.assertEqual(billing_payload["meter_code"], "ops.units")

    async def test_rate_record_respects_billable_window(self) -> None:
        tenant_id = uuid.uuid4()
        record_id = uuid.uuid4()
        meter_definition_id = uuid.uuid4()
        now = datetime(2026, 2, 13, 18, 0, tzinfo=timezone.utc)

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        svc._now_utc = lambda: now

        current = UsageRecordDE(
            id=record_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            measured_units=5,
            status="recorded",
            row_version=5,
            occurred_at=datetime(2026, 2, 13, 15, 0, tzinfo=timezone.utc),
        )

        policy = MeterPolicyDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            multiplier_bps=20000,
            rounding_mode="none",
            rounding_step=1,
            billable_window_minutes=30,
            is_active=True,
        )

        rated = RatedUsageDE(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            usage_record_id=record_id,
        )

        svc.get = AsyncMock(return_value=current)
        svc.update_with_row_version = AsyncMock(return_value=current)
        svc._meter_definition_service.get = AsyncMock(
            return_value=MeterDefinitionDE(
                id=meter_definition_id,
                tenant_id=tenant_id,
                code="ops.units",
                unit="unit",
            )
        )
        svc._meter_policy_service.list = AsyncMock(return_value=[policy])
        svc._rated_usage_service.get = AsyncMock(return_value=None)
        svc._rated_usage_service.create = AsyncMock(return_value=rated)
        svc._rated_usage_service.update = AsyncMock(return_value=rated)
        svc._usage_event_service.get = AsyncMock(return_value=None)
        svc._usage_event_service.create = AsyncMock()

        result = await svc.action_rate_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where={"tenant_id": tenant_id, "id": record_id},
            auth_user_id=uuid.uuid4(),
            data=UsageRecordRateValidation(row_version=5),
        )

        self.assertEqual(result, ("", 204))
        rated_payload = svc._rated_usage_service.create.await_args.args[0]
        self.assertEqual(rated_payload["billable_quantity"], 0)
        svc._usage_event_service.create.assert_not_called()
