"""Provides guarded operations for billing entitlement buckets."""

__all__ = ["EntitlementBucketService"]

from typing import Any, Mapping
import uuid

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.billing.api.validation import BillingEntitlementAdjustValidation
from mugen.core.plugin.billing.contract.service.entitlement_bucket import (
    IEntitlementBucketService,
)
from mugen.core.plugin.billing.domain import EntitlementBucketDE


class EntitlementBucketService(  # pylint: disable=too-few-public-methods
    IRelationalService[EntitlementBucketDE],
    IEntitlementBucketService,
):
    """A CRUD service for billing entitlement buckets."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=EntitlementBucketDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def action_adjust(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,  # noqa: ARG002
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: BillingEntitlementAdjustValidation,
    ) -> tuple[dict[str, Any], int]:
        """Append an audited adjustment and update cached bucket capacity."""
        try:
            async with self._rsg.unit_of_work() as uow:
                existing = await uow.get_one(
                    "billing_entitlement_adjustment",
                    {
                        "tenant_id": tenant_id,
                        "idempotency_key": data.idempotency_key,
                    },
                )
                if existing is not None:
                    same_request = (
                        existing.get("bucket_id") == where.get("id")
                        and existing.get("quantity_delta") == data.quantity_delta
                        and existing.get("reason") == data.reason
                    )
                    if same_request:
                        return "", 204
                    abort(
                        409, "IdempotencyKey was already used for another adjustment."
                    )

                current = await uow.get_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                )
                if current is None:
                    base = await uow.get_one(self.table, dict(where))
                    if base is None:
                        abort(404, "Entitlement Bucket not found.")
                    abort(409, "RowVersion conflict. Refresh and retry.")

                adjustment_before = int(current.get("adjustment_quantity") or 0)
                adjustment_after = adjustment_before + int(data.quantity_delta)
                capacity_after = (
                    int(current.get("included_quantity") or 0)
                    + int(current.get("rollover_quantity") or 0)
                    + adjustment_after
                )
                consumed = int(current.get("consumed_quantity") or 0)
                if capacity_after < 0 or capacity_after < consumed:
                    abort(
                        409,
                        "Adjustment would reduce capacity below zero or below "
                        "consumed usage.",
                    )

                updated = await uow.update_one(
                    self.table,
                    {**dict(where), "row_version": int(data.row_version)},
                    {"adjustment_quantity": adjustment_after},
                )
                if updated is None:
                    abort(409, "RowVersion conflict. Refresh and retry.")

                await uow.insert(
                    "billing_entitlement_adjustment",
                    {
                        "tenant_id": tenant_id,
                        "bucket_id": current["id"],
                        "account_id": current["account_id"],
                        "subscription_id": current.get("subscription_id"),
                        "quantity_delta": int(data.quantity_delta),
                        "adjustment_before": adjustment_before,
                        "adjustment_after": adjustment_after,
                        "capacity_after": capacity_after,
                        "reason": data.reason,
                        "idempotency_key": data.idempotency_key,
                        "actor_user_id": auth_user_id,
                        "attributes": {"source": "guarded_adjust_action"},
                    },
                )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except IntegrityError:
            abort(409, "Duplicate entitlement adjustment or stale bucket state.")
        except SQLAlchemyError:
            abort(500)
        return "", 204
