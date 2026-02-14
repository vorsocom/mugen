"""Branch coverage tests for ops_metering UsageRecordService."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_metering.api.validation import (
    UsageRecordRateValidation,
    UsageRecordVoidValidation,
)
from mugen.core.plugin.ops_metering.domain import (
    MeterDefinitionDE,
    MeterPolicyDE,
    RatedUsageDE,
    UsageRecordDE,
)
from mugen.core.plugin.ops_metering.service import usage_record as usage_mod
from mugen.core.plugin.ops_metering.service.usage_record import UsageRecordService


class _AbortCalled(Exception):
    def __init__(self, code: int, message: str | None = None):
        super().__init__(code, message)
        self.code = code
        self.message = message


def _abort_raiser(code: int, message: str | None = None):
    raise _AbortCalled(code, message)


def _record(
    *,
    record_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    meter_definition_id: uuid.UUID | None = None,
    meter_policy_id: uuid.UUID | None = None,
    rated_usage_id: uuid.UUID | None = None,
    status: str = "recorded",
    row_version: int = 1,
    measured_minutes: int | None = 0,
    measured_tasks: int | None = 0,
    measured_units: int | None = 0,
    occurred_at: datetime | None = None,
    account_id: uuid.UUID | None = None,
    idempotency_key: str | None = None,
    external_ref: str | None = None,
) -> UsageRecordDE:
    return UsageRecordDE(
        id=record_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        meter_definition_id=meter_definition_id or uuid.uuid4(),
        meter_policy_id=meter_policy_id,
        rated_usage_id=rated_usage_id,
        status=status,
        row_version=row_version,
        measured_minutes=measured_minutes,
        measured_tasks=measured_tasks,
        measured_units=measured_units,
        occurred_at=occurred_at,
        account_id=account_id,
        idempotency_key=idempotency_key,
        external_ref=external_ref,
    )


def _meter(
    *,
    meter_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    code: str = "ops.minutes",
    unit: str = "unit",
) -> MeterDefinitionDE:
    return MeterDefinitionDE(
        id=meter_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        code=code,
        unit=unit,
    )


def _policy(
    *,
    policy_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    meter_definition_id: uuid.UUID | None = None,
    cap_minutes: int | None = None,
    cap_tasks: int | None = None,
    cap_units: int | None = None,
    multiplier_bps: int | None = None,
    rounding_mode: str | None = None,
    rounding_step: int | None = None,
    billable_window_minutes: int | None = None,
    effective_from: datetime | None = None,
    effective_to: datetime | None = None,
) -> MeterPolicyDE:
    return MeterPolicyDE(
        id=policy_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        meter_definition_id=meter_definition_id,
        cap_minutes=cap_minutes,
        cap_tasks=cap_tasks,
        cap_units=cap_units,
        multiplier_bps=multiplier_bps,
        rounding_mode=rounding_mode,
        rounding_step=rounding_step,
        billable_window_minutes=billable_window_minutes,
        effective_from=effective_from,
        effective_to=effective_to,
        is_active=True,
    )


def _rated(
    *,
    rated_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
    usage_record_id: uuid.UUID | None = None,
    status: str = "rated",
    billing_usage_event_id: uuid.UUID | None = None,
) -> RatedUsageDE:
    return RatedUsageDE(
        id=rated_id or uuid.uuid4(),
        tenant_id=tenant_id or uuid.uuid4(),
        usage_record_id=usage_record_id,
        status=status,
        billing_usage_event_id=billing_usage_event_id,
    )


class TestMugenOpsMeteringUsageRecordService(unittest.IsolatedAsyncioTestCase):
    """Covers helper and action edge paths in UsageRecordService."""

    def test_static_helper_branches(self) -> None:
        now = UsageRecordService._now_utc()
        self.assertEqual(now.tzinfo, timezone.utc)

        self.assertIsNone(UsageRecordService._normalize_optional_text(None))
        self.assertIsNone(UsageRecordService._normalize_optional_text("  "))
        self.assertEqual(UsageRecordService._normalize_optional_text(" ok "), "ok")

        naive = datetime(2026, 2, 14, 9, 0)
        aware = datetime(2026, 2, 14, 9, 0, tzinfo=timezone.utc)
        self.assertIsNone(UsageRecordService._to_aware_utc(None))
        self.assertEqual(
            UsageRecordService._to_aware_utc(naive).tzinfo,
            timezone.utc,
        )
        self.assertEqual(
            UsageRecordService._to_aware_utc(aware).tzinfo,
            timezone.utc,
        )

        record = _record(measured_minutes=11, measured_tasks=7, measured_units=3)
        self.assertEqual(UsageRecordService._quantity_for_unit(record, "minute"), 11)
        self.assertEqual(UsageRecordService._quantity_for_unit(record, "task"), 7)
        self.assertEqual(UsageRecordService._quantity_for_unit(record, "unit"), 3)

        self.assertEqual(UsageRecordService._cap_for_unit(10, "unit", None), 10)
        policy = _policy(cap_minutes=8, cap_tasks=4, cap_units=6)
        self.assertEqual(UsageRecordService._cap_for_unit(10, "minute", policy), 8)
        self.assertEqual(UsageRecordService._cap_for_unit(10, "task", policy), 4)
        self.assertEqual(UsageRecordService._cap_for_unit(10, "unit", policy), 6)
        self.assertEqual(UsageRecordService._cap_for_unit(10, "other", policy), 10)

        self.assertEqual(
            UsageRecordService._round_scaled_quantity(
                scaled_numerator=0,
                rounding_mode="none",
                rounding_step=1,
            ),
            0,
        )
        self.assertEqual(
            UsageRecordService._round_scaled_quantity(
                scaled_numerator=25500,
                rounding_mode="none",
                rounding_step=1,
            ),
            2,
        )
        self.assertEqual(
            UsageRecordService._round_scaled_quantity(
                scaled_numerator=10001,
                rounding_mode="up",
                rounding_step=2,
            ),
            2,
        )
        self.assertEqual(
            UsageRecordService._round_scaled_quantity(
                scaled_numerator=19999,
                rounding_mode="down",
                rounding_step=1,
            ),
            1,
        )
        self.assertEqual(
            UsageRecordService._round_scaled_quantity(
                scaled_numerator=15000,
                rounding_mode="half_up",
                rounding_step=1,
            ),
            2,
        )

        self.assertTrue(
            UsageRecordService._is_within_billable_window(
                occurred_at=aware,
                policy=None,
                now=aware,
            )
        )
        window_policy = _policy(billable_window_minutes=60)
        self.assertFalse(
            UsageRecordService._is_within_billable_window(
                occurred_at=None,
                policy=window_policy,
                now=aware,
            )
        )
        self.assertFalse(
            UsageRecordService._is_within_billable_window(
                occurred_at=aware - timedelta(hours=2),
                policy=window_policy,
                now=aware,
            )
        )
        self.assertTrue(
            UsageRecordService._is_within_billable_window(
                occurred_at=aware - timedelta(minutes=30),
                policy=window_policy,
                now=aware,
            )
        )

    async def test_create_idempotency_and_integrity_paths(self) -> None:
        tenant_id = uuid.uuid4()
        existing = _record(
            tenant_id=tenant_id,
            idempotency_key="dup",
            external_ref="ext",
            measured_units=1,
        )

        rsg = Mock()
        rsg.insert_one = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "tenant_id": tenant_id,
                "idempotency_key": "fresh",
                "external_ref": "ext-2",
                "measured_units": 2,
                "status": "recorded",
            }
        )
        svc = UsageRecordService(table="ops_metering_usage_record", rsg=rsg)

        svc.get = AsyncMock(return_value=existing)
        reused = await svc.create(
            {
                "tenant_id": tenant_id,
                "meter_definition_id": uuid.uuid4(),
                "measured_units": 1,
                "idempotency_key": " dup ",
                "external_ref": " ext ",
            }
        )
        self.assertEqual(reused.id, existing.id)
        rsg.insert_one.assert_not_awaited()

        svc.get = AsyncMock(return_value=None)
        created = await svc.create(
            {
                "tenant_id": tenant_id,
                "meter_definition_id": uuid.uuid4(),
                "measured_units": 2,
                "idempotency_key": " fresh ",
                "external_ref": " ext-2 ",
            }
        )
        create_payload = rsg.insert_one.await_args.args[1]
        self.assertEqual(create_payload["idempotency_key"], "fresh")
        self.assertEqual(create_payload["external_ref"], "ext-2")
        self.assertEqual(created.idempotency_key, "fresh")

        svc.get = AsyncMock(return_value=existing)
        created_without_idempotency = await svc.create(
            {
                "tenant_id": tenant_id,
                "meter_definition_id": uuid.uuid4(),
                "measured_units": 3,
            }
        )
        self.assertEqual(created_without_idempotency.external_ref, "ext-2")
        svc.get.assert_not_awaited()

        integrity = IntegrityError("insert", {}, Exception("dup"))
        rsg_conflict = Mock()
        rsg_conflict.insert_one = AsyncMock(side_effect=integrity)
        svc_conflict = UsageRecordService(
            table="ops_metering_usage_record",
            rsg=rsg_conflict,
        )
        svc_conflict.get = AsyncMock(side_effect=[None, existing])
        resolved = await svc_conflict.create(
            {
                "tenant_id": tenant_id,
                "meter_definition_id": uuid.uuid4(),
                "measured_units": 1,
                "idempotency_key": "dup",
            }
        )
        self.assertEqual(resolved.id, existing.id)

        svc_raises = UsageRecordService(
            table="ops_metering_usage_record",
            rsg=rsg_conflict,
        )
        svc_raises.get = AsyncMock(side_effect=[None, None])
        with self.assertRaises(IntegrityError):
            await svc_raises.create(
                {
                    "tenant_id": tenant_id,
                    "meter_definition_id": uuid.uuid4(),
                    "measured_units": 1,
                    "idempotency_key": "dup",
                }
            )

        svc_raises_without_idempotency = UsageRecordService(
            table="ops_metering_usage_record",
            rsg=rsg_conflict,
        )
        svc_raises_without_idempotency.get = AsyncMock(return_value=existing)
        with self.assertRaises(IntegrityError):
            await svc_raises_without_idempotency.create(
                {
                    "tenant_id": tenant_id,
                    "meter_definition_id": uuid.uuid4(),
                    "measured_units": 1,
                }
            )
        svc_raises_without_idempotency.get.assert_not_awaited()

    async def test_get_update_policy_and_rated_resolver_branches(self) -> None:
        tenant_id = uuid.uuid4()
        record_id = uuid.uuid4()
        meter_definition_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": record_id}

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        current = _record(
            record_id=record_id,
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            measured_units=3,
            row_version=4,
        )

        svc.get = AsyncMock(return_value=current)
        found = await svc._get_for_action(where=where, expected_row_version=4)
        self.assertEqual(found.id, current.id)

        with patch.object(usage_mod, "abort", side_effect=_abort_raiser):
            svc.get = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=4)
            self.assertEqual(ex.exception.code, 500)

            svc.get = AsyncMock(side_effect=[None, None])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=4)
            self.assertEqual(ex.exception.code, 404)

            svc.get = AsyncMock(side_effect=[None, current])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=4)
            self.assertEqual(ex.exception.code, 409)

            svc.get = AsyncMock(side_effect=[None, SQLAlchemyError("boom")])
            with self.assertRaises(_AbortCalled) as ex:
                await svc._get_for_action(where=where, expected_row_version=4)
            self.assertEqual(ex.exception.code, 500)

        svc.update_with_row_version = AsyncMock(return_value=current)
        updated = await svc._update_record_with_row_version(
            where=where,
            expected_row_version=4,
            changes={"status": "rated"},
        )
        self.assertEqual(updated.id, current.id)

        with patch.object(usage_mod, "abort", side_effect=_abort_raiser):
            svc.update_with_row_version = AsyncMock(
                side_effect=RowVersionConflict("ops_metering_usage_record", where)
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_record_with_row_version(
                    where=where,
                    expected_row_version=4,
                    changes={"status": "rated"},
                )
            self.assertEqual(ex.exception.code, 409)

            svc.update_with_row_version = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_record_with_row_version(
                    where=where,
                    expected_row_version=4,
                    changes={"status": "rated"},
                )
            self.assertEqual(ex.exception.code, 500)

            svc.update_with_row_version = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc._update_record_with_row_version(
                    where=where,
                    expected_row_version=4,
                    changes={"status": "rated"},
                )
            self.assertEqual(ex.exception.code, 404)

        now = datetime(2026, 2, 14, 20, 0, tzinfo=timezone.utc)
        explicit_policy = _policy(
            policy_id=uuid.uuid4(),
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
        )
        record_with_policy = _record(
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            meter_policy_id=explicit_policy.id,
            measured_units=1,
        )
        svc._meter_policy_service.get = AsyncMock(return_value=explicit_policy)
        resolved = await svc._resolve_policy(
            tenant_id=tenant_id,
            record=record_with_policy,
            now=now,
        )
        self.assertEqual(resolved.id, explicit_policy.id)

        future = _policy(
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            effective_from=now + timedelta(hours=1),
        )
        expired = _policy(
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            effective_to=now - timedelta(hours=1),
        )
        valid = _policy(
            tenant_id=tenant_id,
            meter_definition_id=meter_definition_id,
            effective_from=now - timedelta(hours=1),
            effective_to=now + timedelta(hours=1),
        )
        svc._meter_policy_service.list = AsyncMock(return_value=[future, expired, valid])
        resolved = await svc._resolve_policy(
            tenant_id=tenant_id,
            record=_record(
                tenant_id=tenant_id,
                meter_definition_id=meter_definition_id,
                meter_policy_id=None,
                measured_units=2,
            ),
            now=now,
        )
        self.assertEqual(resolved.id, valid.id)

        svc._meter_policy_service.list = AsyncMock(return_value=[])
        resolved_none = await svc._resolve_policy(
            tenant_id=tenant_id,
            record=_record(
                tenant_id=tenant_id,
                meter_definition_id=meter_definition_id,
                meter_policy_id=None,
                measured_units=2,
            ),
            now=now,
        )
        self.assertIsNone(resolved_none)

        rated_by_id = _rated(
            tenant_id=tenant_id,
            usage_record_id=record_id,
        )
        record_with_rated_id = _record(
            record_id=record_id,
            tenant_id=tenant_id,
            rated_usage_id=rated_by_id.id,
            measured_units=1,
        )
        svc._rated_usage_service.get = AsyncMock(return_value=rated_by_id)
        resolved_rated = await svc._resolve_rated_usage(
            tenant_id=tenant_id,
            record=record_with_rated_id,
        )
        self.assertEqual(resolved_rated.id, rated_by_id.id)

        fallback_rated = _rated(
            tenant_id=tenant_id,
            usage_record_id=record_id,
        )
        svc._rated_usage_service.get = AsyncMock(side_effect=[None, fallback_rated])
        resolved_rated = await svc._resolve_rated_usage(
            tenant_id=tenant_id,
            record=record_with_rated_id,
        )
        self.assertEqual(resolved_rated.id, fallback_rated.id)

    async def test_ensure_rated_usage_and_billing_usage_event_branches(self) -> None:
        tenant_id = uuid.uuid4()
        record = _record(
            tenant_id=tenant_id,
            meter_definition_id=uuid.uuid4(),
            measured_units=3,
            account_id=uuid.uuid4(),
        )
        meter = _meter(
            meter_id=record.meter_definition_id,
            tenant_id=tenant_id,
            code="ops.units",
            unit="unit",
        )
        policy = _policy(tenant_id=tenant_id, meter_definition_id=record.meter_definition_id)
        now = datetime(2026, 2, 14, 20, 30, tzinfo=timezone.utc)
        external_ref = f"ops_metering:{tenant_id}:{record.id}"

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())

        existing_rated = _rated(tenant_id=tenant_id, usage_record_id=record.id)
        svc._resolve_rated_usage = AsyncMock(return_value=existing_rated)
        ensured = await svc._ensure_rated_usage(
            tenant_id=tenant_id,
            record=record,
            meter=meter,
            policy=policy,
            measured_quantity=3,
            capped_quantity=3,
            multiplier_bps=10000,
            billable_quantity=3,
            occurred_at=now,
            billing_external_ref=external_ref,
        )
        self.assertEqual(ensured.id, existing_rated.id)

        created_rated = _rated(tenant_id=tenant_id, usage_record_id=record.id)
        svc._resolve_rated_usage = AsyncMock(side_effect=[None, created_rated])
        svc._rated_usage_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("dup"))
        )
        ensured = await svc._ensure_rated_usage(
            tenant_id=tenant_id,
            record=record,
            meter=meter,
            policy=policy,
            measured_quantity=3,
            capped_quantity=3,
            multiplier_bps=10000,
            billable_quantity=3,
            occurred_at=now,
            billing_external_ref=external_ref,
        )
        self.assertEqual(ensured.id, created_rated.id)

        svc._resolve_rated_usage = AsyncMock(side_effect=[None, None])
        svc._rated_usage_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("dup"))
        )
        with self.assertRaises(IntegrityError):
            await svc._ensure_rated_usage(
                tenant_id=tenant_id,
                record=record,
                meter=meter,
                policy=policy,
                measured_quantity=3,
                capped_quantity=3,
                multiplier_bps=10000,
                billable_quantity=3,
                occurred_at=now,
                billing_external_ref=external_ref,
            )

        rated_with_event = _rated(
            tenant_id=tenant_id,
            usage_record_id=record.id,
            billing_usage_event_id=uuid.uuid4(),
        )
        self.assertIsNone(
            await svc._ensure_billing_usage_event(
                tenant_id=tenant_id,
                record=record,
                meter=meter,
                rated=rated_with_event,
                billable_quantity=0,
                occurred_at=now,
                billing_external_ref=external_ref,
            )
        )
        self.assertEqual(
            await svc._ensure_billing_usage_event(
                tenant_id=tenant_id,
                record=record,
                meter=meter,
                rated=rated_with_event,
                billable_quantity=3,
                occurred_at=now,
                billing_external_ref=external_ref,
            ),
            rated_with_event.billing_usage_event_id,
        )

        existing_event_id = uuid.uuid4()
        rated_no_event = _rated(
            tenant_id=tenant_id,
            usage_record_id=record.id,
            billing_usage_event_id=None,
        )
        svc._usage_event_service.get = AsyncMock(
            return_value=SimpleNamespace(id=existing_event_id)
        )
        event_id = await svc._ensure_billing_usage_event(
            tenant_id=tenant_id,
            record=record,
            meter=meter,
            rated=rated_no_event,
            billable_quantity=3,
            occurred_at=now,
            billing_external_ref=external_ref,
        )
        self.assertEqual(event_id, existing_event_id)

        created_event_id = uuid.uuid4()
        svc._usage_event_service.get = AsyncMock(return_value=None)
        svc._usage_event_service.create = AsyncMock(
            return_value=SimpleNamespace(id=created_event_id)
        )
        event_id = await svc._ensure_billing_usage_event(
            tenant_id=tenant_id,
            record=record,
            meter=meter,
            rated=rated_no_event,
            billable_quantity=3,
            occurred_at=now,
            billing_external_ref=external_ref,
        )
        self.assertEqual(event_id, created_event_id)

        svc._usage_event_service.get = AsyncMock(
            side_effect=[None, SimpleNamespace(id=existing_event_id)]
        )
        svc._usage_event_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("dup"))
        )
        event_id = await svc._ensure_billing_usage_event(
            tenant_id=tenant_id,
            record=record,
            meter=meter,
            rated=rated_no_event,
            billable_quantity=3,
            occurred_at=now,
            billing_external_ref=external_ref,
        )
        self.assertEqual(event_id, existing_event_id)

        svc._usage_event_service.get = AsyncMock(side_effect=[None, None])
        svc._usage_event_service.create = AsyncMock(
            side_effect=IntegrityError("insert", {}, Exception("dup"))
        )
        with self.assertRaises(IntegrityError):
            await svc._ensure_billing_usage_event(
                tenant_id=tenant_id,
                record=record,
                meter=meter,
                rated=rated_no_event,
                billable_quantity=3,
                occurred_at=now,
                billing_external_ref=external_ref,
            )

        with patch.object(usage_mod, "abort", side_effect=_abort_raiser):
            svc._usage_event_service.get = AsyncMock(return_value=None)
            svc._usage_event_service.create = AsyncMock(
                side_effect=SQLAlchemyError("boom")
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc._ensure_billing_usage_event(
                    tenant_id=tenant_id,
                    record=record,
                    meter=meter,
                    rated=rated_no_event,
                    billable_quantity=3,
                    occurred_at=now,
                    billing_external_ref=external_ref,
                )
            self.assertEqual(ex.exception.code, 500)

    async def test_action_rate_record_branches(self) -> None:
        tenant_id = uuid.uuid4()
        record_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": record_id}

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        with patch.object(usage_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(
                return_value=_record(
                    record_id=record_id,
                    tenant_id=tenant_id,
                    status="void",
                    row_version=5,
                    measured_units=1,
                )
            )
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_rate_record(
                    tenant_id=tenant_id,
                    entity_id=record_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=UsageRecordRateValidation(row_version=5),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_record(
                    record_id=record_id,
                    tenant_id=tenant_id,
                    status="recorded",
                    row_version=5,
                    measured_units=1,
                    meter_definition_id=uuid.uuid4(),
                )
            )
            svc._meter_definition_service.get = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_rate_record(
                    tenant_id=tenant_id,
                    entity_id=record_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=UsageRecordRateValidation(row_version=5),
                )
            self.assertEqual(ex.exception.code, 409)

            svc._get_for_action = AsyncMock(
                return_value=_record(
                    record_id=record_id,
                    tenant_id=tenant_id,
                    status="recorded",
                    row_version=5,
                    measured_units=0,
                    meter_definition_id=uuid.uuid4(),
                )
            )
            svc._meter_definition_service.get = AsyncMock(
                return_value=_meter(
                    meter_id=uuid.uuid4(),
                    tenant_id=tenant_id,
                    unit="unit",
                )
            )
            svc._resolve_policy = AsyncMock(return_value=None)
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_rate_record(
                    tenant_id=tenant_id,
                    entity_id=record_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=UsageRecordRateValidation(row_version=5),
                )
            self.assertEqual(ex.exception.code, 409)

        already_rated = _record(
            record_id=record_id,
            tenant_id=tenant_id,
            status="rated",
            row_version=6,
            rated_usage_id=uuid.uuid4(),
            measured_units=1,
        )
        svc._get_for_action = AsyncMock(return_value=already_rated)
        self.assertEqual(
            await svc.action_rate_record(
                tenant_id=tenant_id,
                entity_id=record_id,
                where=where,
                auth_user_id=actor_id,
                data=UsageRecordRateValidation(row_version=6),
            ),
            ("", 204),
        )

        current = _record(
            record_id=record_id,
            tenant_id=tenant_id,
            status="recorded",
            row_version=7,
            measured_units=3,
            meter_definition_id=uuid.uuid4(),
            account_id=uuid.uuid4(),
        )
        meter = _meter(
            meter_id=current.meter_definition_id,
            tenant_id=tenant_id,
            code="ops.units",
            unit="unit",
        )
        rated = _rated(
            tenant_id=tenant_id,
            usage_record_id=record_id,
            billing_usage_event_id=None,
        )
        svc._get_for_action = AsyncMock(return_value=current)
        svc._meter_definition_service.get = AsyncMock(return_value=meter)
        svc._resolve_policy = AsyncMock(return_value=None)
        svc._ensure_rated_usage = AsyncMock(return_value=rated)
        svc._ensure_billing_usage_event = AsyncMock(return_value=uuid.uuid4())
        svc._rated_usage_service.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
        svc._update_record_with_row_version = AsyncMock()

        with patch.object(usage_mod, "abort", side_effect=_abort_raiser):
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_rate_record(
                    tenant_id=tenant_id,
                    entity_id=record_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=UsageRecordRateValidation(row_version=7),
                )
            self.assertEqual(ex.exception.code, 500)

        rated_with_event = _rated(
            tenant_id=tenant_id,
            usage_record_id=record_id,
            billing_usage_event_id=uuid.uuid4(),
        )
        svc._ensure_rated_usage = AsyncMock(return_value=rated_with_event)
        svc._ensure_billing_usage_event = AsyncMock(
            return_value=rated_with_event.billing_usage_event_id
        )
        svc._rated_usage_service.update = AsyncMock()
        svc._update_record_with_row_version = AsyncMock()
        result = await svc.action_rate_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where=where,
            auth_user_id=actor_id,
            data=UsageRecordRateValidation(row_version=7),
        )
        self.assertEqual(result, ("", 204))
        svc._rated_usage_service.update.assert_not_awaited()
        self.assertEqual(
            svc._update_record_with_row_version.await_args.kwargs["changes"]["status"],
            "rated",
        )

        stale_now = datetime(2026, 2, 14, 21, 30, tzinfo=timezone.utc)
        stale_record = _record(
            record_id=record_id,
            tenant_id=tenant_id,
            status="recorded",
            row_version=8,
            measured_units=4,
            meter_definition_id=current.meter_definition_id,
            occurred_at=stale_now - timedelta(hours=2),
        )
        stale_policy = _policy(
            tenant_id=tenant_id,
            meter_definition_id=current.meter_definition_id,
            billable_window_minutes=30,
        )
        svc._now_utc = Mock(return_value=stale_now)
        svc._get_for_action = AsyncMock(return_value=stale_record)
        svc._meter_definition_service.get = AsyncMock(return_value=meter)
        svc._resolve_policy = AsyncMock(return_value=stale_policy)
        svc._ensure_rated_usage = AsyncMock(return_value=rated_with_event)
        svc._ensure_billing_usage_event = AsyncMock(return_value=None)
        svc._update_record_with_row_version = AsyncMock()
        result = await svc.action_rate_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where=where,
            auth_user_id=actor_id,
            data=UsageRecordRateValidation(row_version=8),
        )
        self.assertEqual(result, ("", 204))
        self.assertEqual(
            svc._ensure_rated_usage.await_args.kwargs["billable_quantity"],
            0,
        )

    async def test_action_void_record_branches(self) -> None:
        tenant_id = uuid.uuid4()
        record_id = uuid.uuid4()
        actor_id = uuid.uuid4()
        where = {"tenant_id": tenant_id, "id": record_id}
        now = datetime(2026, 2, 14, 21, 0, tzinfo=timezone.utc)

        svc = UsageRecordService(table="ops_metering_usage_record", rsg=Mock())
        svc._now_utc = Mock(return_value=now)

        svc._get_for_action = AsyncMock(
            return_value=_record(
                record_id=record_id,
                tenant_id=tenant_id,
                status="void",
                row_version=2,
                measured_units=1,
            )
        )
        self.assertEqual(
            await svc.action_void_record(
                tenant_id=tenant_id,
                entity_id=record_id,
                where=where,
                auth_user_id=actor_id,
                data=UsageRecordVoidValidation(row_version=2, reason="x"),
            ),
            ("", 204),
        )

        active_record = _record(
            record_id=record_id,
            tenant_id=tenant_id,
            status="rated",
            row_version=3,
            measured_units=2,
        )
        rated = _rated(
            tenant_id=tenant_id,
            usage_record_id=record_id,
            status="rated",
            billing_usage_event_id=uuid.uuid4(),
        )

        with patch.object(usage_mod, "abort", side_effect=_abort_raiser):
            svc._get_for_action = AsyncMock(return_value=active_record)
            svc._resolve_rated_usage = AsyncMock(return_value=rated)
            svc._rated_usage_service.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_void_record(
                    tenant_id=tenant_id,
                    entity_id=record_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=UsageRecordVoidValidation(row_version=3, reason="reason"),
                )
            self.assertEqual(ex.exception.code, 500)

            svc._rated_usage_service.update = AsyncMock()
            svc._usage_event_service.update = AsyncMock(side_effect=SQLAlchemyError("boom"))
            with self.assertRaises(_AbortCalled) as ex:
                await svc.action_void_record(
                    tenant_id=tenant_id,
                    entity_id=record_id,
                    where=where,
                    auth_user_id=actor_id,
                    data=UsageRecordVoidValidation(row_version=3, reason="reason"),
                )
            self.assertEqual(ex.exception.code, 500)

        svc._get_for_action = AsyncMock(return_value=active_record)
        svc._resolve_rated_usage = AsyncMock(return_value=rated)
        svc._rated_usage_service.update = AsyncMock()
        svc._usage_event_service.update = AsyncMock()
        svc._update_record_with_row_version = AsyncMock()
        result = await svc.action_void_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where=where,
            auth_user_id=actor_id,
            data=UsageRecordVoidValidation(row_version=3, reason=" ", note=" note "),
        )
        self.assertEqual(result, ("", 204))
        rated_changes = svc._rated_usage_service.update.await_args.kwargs["changes"]
        self.assertEqual(rated_changes["status"], "void")
        self.assertEqual(rated_changes["voided_at"], now)
        self.assertEqual(rated_changes["void_reason"], "note")
        event_changes = svc._usage_event_service.update.await_args.kwargs["changes"]
        self.assertEqual(event_changes["status"], "void")
        record_changes = svc._update_record_with_row_version.await_args.kwargs["changes"]
        self.assertEqual(record_changes["status"], "void")
        self.assertEqual(record_changes["void_reason"], "note")

        rated_without_event = _rated(
            tenant_id=tenant_id,
            usage_record_id=record_id,
            status="rated",
            billing_usage_event_id=None,
        )
        svc._resolve_rated_usage = AsyncMock(return_value=rated_without_event)
        svc._rated_usage_service.update = AsyncMock()
        svc._usage_event_service.update = AsyncMock()
        svc._update_record_with_row_version = AsyncMock()
        result = await svc.action_void_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where=where,
            auth_user_id=actor_id,
            data=UsageRecordVoidValidation(row_version=3, note="no-event"),
        )
        self.assertEqual(result, ("", 204))
        svc._usage_event_service.update.assert_not_awaited()

        svc._resolve_rated_usage = AsyncMock(return_value=None)
        svc._update_record_with_row_version = AsyncMock()
        result = await svc.action_void_record(
            tenant_id=tenant_id,
            entity_id=record_id,
            where=where,
            auth_user_id=actor_id,
            data=UsageRecordVoidValidation(row_version=3),
        )
        self.assertEqual(result, ("", 204))
