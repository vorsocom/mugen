"""Provides a CRUD service for usage record rating and billing handoff."""

__all__ = ["UsageRecordService"]

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
)
from mugen.core.plugin.billing.service.usage_event import UsageEventService
from mugen.core.plugin.ops_metering.api.validation import (
    UsageRecordRateValidation,
    UsageRecordVoidValidation,
)
from mugen.core.plugin.ops_metering.contract.service.usage_record import (
    IUsageRecordService,
)
from mugen.core.plugin.ops_metering.domain import (
    MeterDefinitionDE,
    MeterPolicyDE,
    RatedUsageDE,
    UsageRecordDE,
)
from mugen.core.plugin.ops_metering.service.meter_definition import (
    MeterDefinitionService,
)
from mugen.core.plugin.ops_metering.service.meter_policy import MeterPolicyService
from mugen.core.plugin.ops_metering.service.rated_usage import RatedUsageService


class UsageRecordService(
    IRelationalService[UsageRecordDE],
    IUsageRecordService,
):
    """A CRUD service for usage records, rating, and billing usage handoff."""

    _METER_DEFINITION_TABLE = "ops_metering_meter_definition"
    _METER_POLICY_TABLE = "ops_metering_meter_policy"
    _RATED_USAGE_TABLE = "ops_metering_rated_usage"
    _BILLING_USAGE_EVENT_TABLE = "billing_usage_event"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=UsageRecordDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._meter_definition_service = MeterDefinitionService(
            table=self._METER_DEFINITION_TABLE,
            rsg=rsg,
        )
        self._meter_policy_service = MeterPolicyService(
            table=self._METER_POLICY_TABLE,
            rsg=rsg,
        )
        self._rated_usage_service = RatedUsageService(
            table=self._RATED_USAGE_TABLE,
            rsg=rsg,
        )
        self._usage_event_service = UsageEventService(
            table=self._BILLING_USAGE_EVENT_TABLE,
            rsg=rsg,
        )

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        if value is None:
            return None
        clean = str(value).strip()
        return clean or None

    @staticmethod
    def _to_aware_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    async def create(self, values: Mapping[str, Any]) -> UsageRecordDE:
        """Create usage records with idempotency support on IdempotencyKey."""
        create_values = dict(values)
        idempotency_key = self._normalize_optional_text(
            create_values.get("idempotency_key")
        )
        create_values["idempotency_key"] = idempotency_key
        create_values["external_ref"] = self._normalize_optional_text(
            create_values.get("external_ref")
        )

        tenant_id = create_values.get("tenant_id")
        if idempotency_key and tenant_id is not None:
            existing = await self.get(
                where={
                    "tenant_id": tenant_id,
                    "idempotency_key": idempotency_key,
                }
            )
            if existing is not None:
                return existing

        try:
            return await super().create(create_values)
        except IntegrityError:
            if idempotency_key and tenant_id is not None:
                existing = await self.get(
                    where={
                        "tenant_id": tenant_id,
                        "idempotency_key": idempotency_key,
                    }
                )
                if existing is not None:
                    return existing
            raise

    async def _get_for_action(
        self,
        *,
        where: dict,
        expected_row_version: int,
    ) -> UsageRecordDE:
        where_with_version = dict(where)
        where_with_version["row_version"] = expected_row_version

        try:
            current = await self.get(where_with_version)
        except SQLAlchemyError:
            abort(500)

        if current is not None:
            return current

        try:
            base = await self.get(where)
        except SQLAlchemyError:
            abort(500)

        if base is None:
            abort(404, "Usage record not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_record_with_row_version(
        self,
        *,
        where: dict,
        expected_row_version: int,
        changes: dict,
    ) -> UsageRecordDE:
        svc: ICrudServiceWithRowVersion[UsageRecordDE] = self

        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes=changes,
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return updated

    @staticmethod
    def _quantity_for_unit(record: UsageRecordDE, unit: str) -> int:
        if unit == "minute":
            return int(record.measured_minutes or 0)
        if unit == "task":
            return int(record.measured_tasks or 0)
        return int(record.measured_units or 0)

    @staticmethod
    def _cap_for_unit(quantity: int, unit: str, policy: MeterPolicyDE | None) -> int:
        if policy is None:
            return quantity

        if unit == "minute" and policy.cap_minutes is not None:
            return min(quantity, int(policy.cap_minutes))
        if unit == "task" and policy.cap_tasks is not None:
            return min(quantity, int(policy.cap_tasks))
        if unit == "unit" and policy.cap_units is not None:
            return min(quantity, int(policy.cap_units))
        return quantity

    @staticmethod
    def _round_scaled_quantity(
        *,
        scaled_numerator: int,
        rounding_mode: str,
        rounding_step: int,
    ) -> int:
        if scaled_numerator <= 0:
            return 0

        step = max(1, int(rounding_step or 1))
        mode = (rounding_mode or "none").strip().lower()

        if mode == "none":
            return max(0, scaled_numerator // 10000)

        denom = 10000 * step
        if mode == "up":
            quotient = (scaled_numerator + denom - 1) // denom
        elif mode == "down":
            quotient = scaled_numerator // denom
        else:
            quotient = (scaled_numerator + (denom // 2)) // denom

        return max(0, int(quotient) * step)

    @classmethod
    def _is_within_billable_window(
        cls,
        *,
        occurred_at: datetime | None,
        policy: MeterPolicyDE | None,
        now: datetime,
    ) -> bool:
        if policy is None or policy.billable_window_minutes is None:
            return True

        occurred_utc = cls._to_aware_utc(occurred_at)
        if occurred_utc is None:
            return False

        window = timedelta(minutes=int(policy.billable_window_minutes))
        return occurred_utc >= (now - window)

    async def _resolve_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        record: UsageRecordDE,
        now: datetime,
    ) -> MeterPolicyDE | None:
        if record.meter_policy_id is not None:
            return await self._meter_policy_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": record.meter_policy_id,
                }
            )

        candidates = await self._meter_policy_service.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "meter_definition_id": record.meter_definition_id,
                        "is_active": True,
                    }
                )
            ],
            order_by=[OrderBy(field="created_at", descending=True)],
            limit=100,
        )

        for policy in candidates:
            start = self._to_aware_utc(policy.effective_from)
            end = self._to_aware_utc(policy.effective_to)
            if start is not None and now < start:
                continue
            if end is not None and now > end:
                continue
            return policy

        return None

    async def _resolve_rated_usage(
        self,
        *,
        tenant_id: uuid.UUID,
        record: UsageRecordDE,
    ) -> RatedUsageDE | None:
        if record.rated_usage_id is not None:
            rated = await self._rated_usage_service.get(
                {
                    "tenant_id": tenant_id,
                    "id": record.rated_usage_id,
                }
            )
            if rated is not None:
                return rated

        return await self._rated_usage_service.get(
            {
                "tenant_id": tenant_id,
                "usage_record_id": record.id,
            }
        )

    async def _ensure_rated_usage(
        self,
        *,
        tenant_id: uuid.UUID,
        record: UsageRecordDE,
        meter: MeterDefinitionDE,
        policy: MeterPolicyDE | None,
        measured_quantity: int,
        capped_quantity: int,
        multiplier_bps: int,
        billable_quantity: int,
        occurred_at: datetime,
        billing_external_ref: str,
    ) -> RatedUsageDE:
        existing = await self._resolve_rated_usage(
            tenant_id=tenant_id,
            record=record,
        )
        if existing is not None:
            return existing

        payload = {
            "tenant_id": tenant_id,
            "usage_record_id": record.id,
            "meter_definition_id": record.meter_definition_id,
            "meter_policy_id": policy.id if policy is not None else None,
            "account_id": record.account_id,
            "subscription_id": record.subscription_id,
            "price_id": record.price_id,
            "meter_code": meter.code,
            "unit": meter.unit,
            "measured_quantity": measured_quantity,
            "capped_quantity": capped_quantity,
            "multiplier_bps": multiplier_bps,
            "billable_quantity": billable_quantity,
            "occurred_at": occurred_at,
            "status": "rated",
            "billing_external_ref": billing_external_ref,
            "attributes": {
                "source": "ops_metering",
                "usage_record_id": str(record.id),
            },
        }

        try:
            return await self._rated_usage_service.create(payload)
        except IntegrityError:
            existing = await self._resolve_rated_usage(
                tenant_id=tenant_id,
                record=record,
            )
            if existing is not None:
                return existing
            raise

    async def _ensure_billing_usage_event(
        self,
        *,
        tenant_id: uuid.UUID,
        record: UsageRecordDE,
        meter: MeterDefinitionDE,
        rated: RatedUsageDE,
        billable_quantity: int,
        occurred_at: datetime,
        billing_external_ref: str,
    ) -> uuid.UUID | None:
        if billable_quantity <= 0 or record.account_id is None:
            return None

        if rated.billing_usage_event_id is not None:
            return rated.billing_usage_event_id

        existing_event = await self._usage_event_service.get(
            {
                "tenant_id": tenant_id,
                "external_ref": billing_external_ref,
            }
        )
        if existing_event is not None:
            return existing_event.id

        payload = {
            "tenant_id": tenant_id,
            "account_id": record.account_id,
            "subscription_id": record.subscription_id,
            "price_id": record.price_id,
            "meter_code": meter.code,
            "occurred_at": occurred_at,
            "quantity": int(billable_quantity),
            "status": "recorded",
            "external_ref": billing_external_ref,
            "attributes": {
                "source": "ops_metering",
                "usage_record_id": str(record.id),
                "rated_usage_id": str(rated.id),
            },
        }

        try:
            created = await self._usage_event_service.create(payload)
            return created.id
        except IntegrityError:
            existing = await self._usage_event_service.get(
                {
                    "tenant_id": tenant_id,
                    "external_ref": billing_external_ref,
                }
            )
            if existing is not None:
                return existing.id
            raise
        except SQLAlchemyError:
            abort(500)

    async def action_rate_record(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: UsageRecordRateValidation,
    ) -> tuple[dict, int]:
        """Rate a usage record and write billable usage into billing usage events."""
        _auth_user_id = auth_user_id
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "void":
            abort(409, "Voided usage records cannot be rated.")
        if current.status == "rated" and current.rated_usage_id is not None:
            return "", 204

        now = self._now_utc()
        meter = await self._meter_definition_service.get(
            {
                "tenant_id": tenant_id,
                "id": current.meter_definition_id,
            }
        )
        if meter is None:
            abort(409, "MeterDefinition does not exist for this record.")

        policy = await self._resolve_policy(
            tenant_id=tenant_id,
            record=current,
            now=now,
        )

        unit = str(meter.unit or "unit").strip().lower() or "unit"
        measured_quantity = self._quantity_for_unit(current, unit)
        if measured_quantity <= 0:
            abort(409, "Measured quantity must be positive for rating.")

        capped_quantity = self._cap_for_unit(measured_quantity, unit, policy)
        multiplier_bps = int(policy.multiplier_bps or 10000) if policy else 10000
        scaled_numerator = int(capped_quantity) * int(multiplier_bps)
        rounding_mode = policy.rounding_mode if policy else "none"
        rounding_step = int(policy.rounding_step or 1) if policy else 1
        billable_quantity = self._round_scaled_quantity(
            scaled_numerator=scaled_numerator,
            rounding_mode=str(rounding_mode),
            rounding_step=rounding_step,
        )

        occurred_at = self._to_aware_utc(current.occurred_at) or now
        if not self._is_within_billable_window(
            occurred_at=occurred_at,
            policy=policy,
            now=now,
        ):
            billable_quantity = 0

        billing_external_ref = f"ops_metering:{tenant_id}:{entity_id}"
        rated = await self._ensure_rated_usage(
            tenant_id=tenant_id,
            record=current,
            meter=meter,
            policy=policy,
            measured_quantity=measured_quantity,
            capped_quantity=capped_quantity,
            multiplier_bps=multiplier_bps,
            billable_quantity=billable_quantity,
            occurred_at=occurred_at,
            billing_external_ref=billing_external_ref,
        )

        billing_usage_event_id = await self._ensure_billing_usage_event(
            tenant_id=tenant_id,
            record=current,
            meter=meter,
            rated=rated,
            billable_quantity=billable_quantity,
            occurred_at=occurred_at,
            billing_external_ref=billing_external_ref,
        )

        if (
            billing_usage_event_id is not None
            and billing_usage_event_id != rated.billing_usage_event_id
        ):
            try:
                await self._rated_usage_service.update(
                    where={"tenant_id": tenant_id, "id": rated.id},
                    changes={"billing_usage_event_id": billing_usage_event_id},
                )
            except SQLAlchemyError:
                abort(500)

        await self._update_record_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "rated",
                "rated_usage_id": rated.id,
                "rated_at": now,
            },
        )

        return "", 204

    async def action_void_record(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: dict,
        auth_user_id: uuid.UUID,
        data: UsageRecordVoidValidation,
    ) -> tuple[dict, int]:
        """Void a usage record and void related rated and billing usage rows."""
        _entity_id = entity_id
        _auth_user_id = auth_user_id
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )

        if current.status == "void":
            return "", 204

        now = self._now_utc()
        void_reason = self._normalize_optional_text(
            data.reason
        ) or self._normalize_optional_text(data.note)
        rated = await self._resolve_rated_usage(
            tenant_id=tenant_id,
            record=current,
        )

        if rated is not None and rated.status != "void":
            try:
                await self._rated_usage_service.update(
                    where={"tenant_id": tenant_id, "id": rated.id},
                    changes={
                        "status": "void",
                        "voided_at": now,
                        "void_reason": void_reason,
                    },
                )
            except SQLAlchemyError:
                abort(500)

            if rated.billing_usage_event_id is not None:
                try:
                    await self._usage_event_service.update(
                        where={
                            "tenant_id": tenant_id,
                            "id": rated.billing_usage_event_id,
                        },
                        changes={"status": "void"},
                    )
                except SQLAlchemyError:
                    abort(500)

        await self._update_record_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "status": "void",
                "voided_at": now,
                "void_reason": void_reason,
            },
        )

        return "", 204
