"""Provides tenant billing-run execution lifecycle services."""

from __future__ import annotations

__all__ = ["BillingRunService"]

import calendar
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping
import uuid
from zoneinfo import ZoneInfo

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
)
from mugen.core.contract.gateway.storage.rdbms.uow import IRelationalUnitOfWork
from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.api.validation import (
    BillingRunFailValidation,
    BillingRunRetryValidation,
)
from mugen.core.plugin.billing.contract.service.billing_run import IBillingRunService
from mugen.core.plugin.billing.domain import BillingRunDE
from mugen.core.plugin.billing.service.subscription import SubscriptionService


class BillingRunService(
    IRelationalService[BillingRunDE],
    IBillingRunService,
):
    """Manage idempotent tenant execution attempts for global run definitions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(de_type=BillingRunDE, table=table, rsg=rsg, **kwargs)
        self._subscription_service = SubscriptionService(
            table="billing_subscription",
            rsg=rsg,
        )

    @staticmethod
    def _same_create_request(
        existing: Mapping[str, Any], payload: Mapping[str, Any]
    ) -> bool:
        fields = (
            "definition_id",
            "period_start",
            "period_end",
            "account_id",
            "subscription_id",
        )
        return all(existing.get(field) == payload.get(field) for field in fields)

    async def _validate_scope(
        self,
        uow: IRelationalUnitOfWork,
        payload: Mapping[str, Any],
        *,
        status_code: int,
    ) -> Mapping[str, Any]:
        definition = await uow.get_one(
            "billing_run_definition",
            {"id": payload["definition_id"]},
        )
        if definition is None or not definition.get("is_active"):
            abort(status_code, "DefinitionId must reference an active Run Definition.")
        tenant_id = payload["tenant_id"]
        account_id = payload.get("account_id")
        if account_id is not None:
            account = await uow.get_one(
                "billing_account",
                {"tenant_id": tenant_id, "id": account_id, "deleted_at": None},
            )
            if account is None:
                abort(status_code, "AccountId is not available in the route tenant.")
        subscription_id = payload.get("subscription_id")
        if subscription_id is not None:
            subscription = await uow.get_one(
                "billing_subscription",
                {"tenant_id": tenant_id, "id": subscription_id},
            )
            if subscription is None or subscription.get("account_id") != account_id:
                abort(
                    status_code,
                    "SubscriptionId does not belong to the selected account.",
                )
        self._validate_definition_period(definition, payload)
        return definition

    @staticmethod
    def _add_local_interval(
        start: datetime,
        frequency: str,
        interval_count: int,
    ) -> datetime:
        if frequency == "daily":
            return start + timedelta(days=interval_count)
        if frequency == "weekly":
            return start + timedelta(weeks=interval_count)
        month_delta = interval_count if frequency == "monthly" else interval_count * 12
        absolute_month = (start.year * 12 + start.month - 1) + month_delta
        year, month_index = divmod(absolute_month, 12)
        month = month_index + 1
        day = min(start.day, calendar.monthrange(year, month)[1])
        return start.replace(year=year, month=month, day=day)

    @staticmethod
    def _validate_definition_period(
        definition: Mapping[str, Any],
        payload: Mapping[str, Any],
    ) -> None:
        frequency = definition.get("frequency")
        if frequency == "manual":
            return
        start = payload["period_start"]
        end = payload["period_end"]
        timezone_value = ZoneInfo(str(definition["timezone"]))
        local_start = start.astimezone(timezone_value)
        expected_end = BillingRunService._add_local_interval(
            local_start,
            str(frequency),
            int(definition["interval_count"]),
        ).astimezone(timezone.utc)
        if end.astimezone(timezone.utc) != expected_end:
            abort(409, "Billing Run period does not match its global definition.")

    async def create(self, values: Mapping[str, Any]) -> BillingRunDE:
        payload = dict(values)
        payload["idempotency_key"] = str(payload["idempotency_key"]).strip()
        existing = await self.get(
            {
                "tenant_id": payload["tenant_id"],
                "idempotency_key": payload["idempotency_key"],
            }
        )
        if existing is not None:
            if self._same_create_request(existing.__dict__, payload):
                return existing
            abort(409, "IdempotencyKey was already used for another Billing Run.")
        payload["status"] = "pending"
        payload["attempt_number"] = 1
        payload["retry_of_run_id"] = None
        try:
            async with self._rsg.unit_of_work() as uow:
                await self._validate_scope(uow, payload, status_code=400)
                inserted = await uow.insert(self.table, payload)
                if inserted is None:
                    abort(500)
        except IntegrityError:
            existing = await self.get(
                {
                    "tenant_id": payload["tenant_id"],
                    "idempotency_key": payload["idempotency_key"],
                }
            )
            if existing is not None and self._same_create_request(
                existing.__dict__, payload
            ):
                return existing
            abort(409, "Billing Run idempotency conflict.")
        except SQLAlchemyError:
            abort(500)
        return self._from_record(inserted)

    async def _load_action_run(
        self,
        uow: IRelationalUnitOfWork,
        *,
        where: Mapping[str, Any],
        row_version: int,
    ) -> Mapping[str, Any]:
        current = await uow.get_one(
            self.table,
            {**dict(where), "row_version": row_version},
        )
        if current is not None:
            return current
        if await uow.get_one(self.table, dict(where)) is None:
            abort(404, "Billing Run not found.")
        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _provision_scoped_subscriptions(
        self,
        uow: IRelationalUnitOfWork,
        run: Mapping[str, Any],
        *,
        allow_advance: bool,
    ) -> int:
        where_base: dict[str, Any] = {"tenant_id": run["tenant_id"]}
        if run.get("account_id") is not None:
            where_base["account_id"] = run["account_id"]
        if run.get("subscription_id") is not None:
            where_base["id"] = run["subscription_id"]
        subscriptions = await uow.find(
            "billing_subscription",
            filter_groups=[
                FilterGroup(where={**where_base, "status": status})
                for status in ("active", "trialing")
            ],
        )
        generated = 0
        for subscription in subscriptions:
            period_start = run["period_start"]
            period_end = run["period_end"]
            current_pair = (
                subscription.get("current_period_start"),
                subscription.get("current_period_end"),
            )
            if current_pair != (period_start, period_end):
                if (
                    not allow_advance
                    or subscription.get("current_period_end") != period_start
                ):
                    continue
                subscription = await uow.update_one(
                    "billing_subscription",
                    {
                        "tenant_id": run["tenant_id"],
                        "id": subscription["id"],
                        "row_version": subscription["row_version"],
                    },
                    {
                        "current_period_start": period_start,
                        "current_period_end": period_end,
                    },
                )
                if subscription is None:
                    abort(409, "Subscription changed while Billing Run was opening.")
            generated += await self._subscription_service._provision_buckets(
                uow,
                subscription=subscription,
                period_start=period_start,
                period_end=period_end,
                generation_source="billing_run",
                billing_run_id=run["id"],
            )
        return generated

    async def _transition(
        self,
        *,
        where: Mapping[str, Any],
        row_version: int,
        allowed: set[str],
        changes: Mapping[str, Any],
    ) -> tuple[dict[str, Any], int]:
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await self._load_action_run(
                    uow,
                    where=where,
                    row_version=row_version,
                )
                if current["status"] not in allowed:
                    abort(
                        409, f"Billing Run cannot transition from {current['status']}."
                    )
                updated = await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": row_version},
                    dict(changes),
                )
                if updated is None:
                    abort(409, "RowVersion conflict. Refresh and retry.")
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
        return "", 204

    async def action_start(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Start a pending run and open applicable entitlement periods."""
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await self._load_action_run(
                    uow,
                    where=where,
                    row_version=int(data.row_version),
                )
                if current["status"] != "pending":
                    abort(409, "Only pending Billing Runs may start.")
                await self._validate_scope(uow, current, status_code=409)
                updated = await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {
                        "status": "running",
                        "started_at": datetime.now(timezone.utc),
                        "failure_code": None,
                        "failure_detail": None,
                    },
                )
                if updated is None:
                    abort(409, "RowVersion conflict. Refresh and retry.")
                await self._provision_scoped_subscriptions(
                    uow,
                    updated,
                    allow_advance=True,
                )
        except (IntegrityError, RowVersionConflict):
            abort(409, "Billing Run conflicts with entitlement or Subscription state.")
        except SQLAlchemyError:
            abort(500)
        return "", 204

    async def action_complete(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Complete a running Billing Run."""
        return await self._transition(
            where=where,
            row_version=int(data.row_version),
            allowed={"running"},
            changes={"status": "succeeded", "completed_at": datetime.now(timezone.utc)},
        )

    async def action_fail(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: BillingRunFailValidation,
    ) -> tuple[dict[str, Any], int]:
        """Fail a running Billing Run with safe diagnostic detail."""
        return await self._transition(
            where=where,
            row_version=int(data.row_version),
            allowed={"running"},
            changes={
                "status": "failed",
                "completed_at": datetime.now(timezone.utc),
                "failure_code": data.failure_code,
                "failure_detail": data.failure_detail,
            },
        )

    async def action_cancel(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel a pending or running Billing Run."""
        return await self._transition(
            where=where,
            row_version=int(data.row_version),
            allowed={"pending", "running"},
            changes={"status": "canceled", "completed_at": datetime.now(timezone.utc)},
        )

    async def action_retry(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: BillingRunRetryValidation,
    ) -> tuple[dict[str, Any], int]:
        """Create one explicit retry attempt for a failed Billing Run."""
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await self._load_action_run(
                    uow,
                    where=where,
                    row_version=int(data.row_version),
                )
                if current["status"] != "failed":
                    abort(409, "Only failed Billing Runs may be retried.")
                existing = await uow.get_one(
                    self.table,
                    {"tenant_id": tenant_id, "idempotency_key": data.idempotency_key},
                )
                if existing is not None:
                    if existing.get("retry_of_run_id") == current["id"]:
                        return {"Id": str(existing["id"])}, 200
                    abort(409, "IdempotencyKey belongs to another Billing Run.")
                touched = await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {"completed_at": current["completed_at"]},
                )
                if touched is None:
                    abort(409, "RowVersion conflict. Refresh and retry.")
                retry = await uow.insert(
                    self.table,
                    {
                        "tenant_id": tenant_id,
                        "account_id": current.get("account_id"),
                        "subscription_id": current.get("subscription_id"),
                        "definition_id": current["definition_id"],
                        "retry_of_run_id": current["id"],
                        "attempt_number": int(current.get("attempt_number") or 1) + 1,
                        "period_start": current["period_start"],
                        "period_end": current["period_end"],
                        "status": "pending",
                        "idempotency_key": data.idempotency_key,
                        "external_ref": None,
                        "attributes": {"retry_of_run_id": str(current["id"])},
                    },
                )
                if retry is None:
                    abort(500)
        except (IntegrityError, RowVersionConflict):
            abort(409, "Billing Run retry conflicts with current state.")
        except SQLAlchemyError:
            abort(500)
        return {"Id": str(retry["id"])}, 201

    async def action_reconcile_entitlements(
        self,
        *,
        tenant_id: uuid.UUID,  # noqa: ARG002
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Idempotently restore buckets associated with a non-canceled run."""
        try:
            async with self._rsg.unit_of_work() as uow:
                current = await self._load_action_run(
                    uow,
                    where=where,
                    row_version=int(data.row_version),
                )
                if current["status"] not in {"running", "succeeded", "failed"}:
                    abort(409, "Billing Run is not eligible for reconciliation.")
                await self._provision_scoped_subscriptions(
                    uow,
                    current,
                    allow_advance=False,
                )
                await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {"status": current["status"]},
                )
        except (IntegrityError, RowVersionConflict):
            abort(409, "Billing Run reconciliation conflicts with current state.")
        except SQLAlchemyError:
            abort(500)
        return "", 204
