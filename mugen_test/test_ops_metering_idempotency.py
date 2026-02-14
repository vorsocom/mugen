"""Unit tests for ops_metering ingestion and rating idempotency."""

import unittest
from unittest.mock import AsyncMock, Mock
import uuid

from mugen.core.plugin.ops_metering.api.validation import UsageRecordRateValidation
from mugen.core.plugin.ops_metering.domain import UsageRecordDE
from mugen.core.plugin.ops_metering.service.usage_record import UsageRecordService


class TestOpsMeteringIdempotency(unittest.IsolatedAsyncioTestCase):
    """Tests idempotent create and rating behavior in UsageRecordService."""

    async def test_create_uses_idempotency_key(self) -> None:
        tenant_id = uuid.uuid4()
        existing_id = uuid.uuid4()

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        existing = UsageRecordDE(
            id=existing_id,
            tenant_id=tenant_id,
            idempotency_key="idem-1",
            measured_units=3,
        )
        svc.get = AsyncMock(return_value=existing)

        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "meter_definition_id": uuid.uuid4(),
                "measured_units": 3,
                "idempotency_key": "idem-1",
            }
        )

        self.assertEqual(created.id, existing_id)
        lookup_where = svc.get.await_args.kwargs["where"]
        self.assertEqual(lookup_where["tenant_id"], tenant_id)
        self.assertEqual(lookup_where["idempotency_key"], "idem-1")

    async def test_rate_record_is_idempotent_if_already_rated(self) -> None:
        tenant_id = uuid.uuid4()
        record_id = uuid.uuid4()

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        current = UsageRecordDE(
            id=record_id,
            tenant_id=tenant_id,
            meter_definition_id=uuid.uuid4(),
            status="rated",
            rated_usage_id=uuid.uuid4(),
            row_version=9,
        )

        svc.get = AsyncMock(return_value=current)
        svc._meter_definition_service.get = AsyncMock()

        result = await svc.action_rate_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where={"tenant_id": tenant_id, "id": record_id},
            auth_user_id=uuid.uuid4(),
            data=UsageRecordRateValidation(row_version=9),
        )

        self.assertEqual(result, ("", 204))
        svc._meter_definition_service.get.assert_not_called()
