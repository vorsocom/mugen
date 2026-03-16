"""Provides a CRUD service for billing subscriptions (plus common lifecycle actions)."""

__all__ = ["SubscriptionService"]

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict

from mugen.core.plugin.acp.api.validation.generic import RowVersionValidation
from mugen.core.plugin.billing.contract.service.subscription import ISubscriptionService
from mugen.core.plugin.billing.domain import SubscriptionDE


class SubscriptionService(
    IRelationalService[SubscriptionDE],
    ISubscriptionService,
):
    """A CRUD service for billing subscriptions."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=SubscriptionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> SubscriptionDE:
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
            abort(404, "Subscription not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def action_cancel(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Cancel a subscription (entity action)."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status not in {"active", "trialing", "paused"}:
            abort(409, "Subscription can only be canceled from active/trialing/paused.")

        svc: ICrudServiceWithRowVersion[SubscriptionDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "canceled",
                    "canceled_at": datetime.now(timezone.utc),
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204

    async def action_reactivate(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RowVersionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Reactivate a canceled/paused subscription (entity action)."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status not in {"canceled", "paused"}:
            abort(409, "Subscription can only be reactivated from canceled/paused.")

        svc: ICrudServiceWithRowVersion[SubscriptionDE] = self
        try:
            updated = await svc.update_with_row_version(
                where=where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "active",
                    "cancel_at": None,
                    "canceled_at": None,
                    "ended_at": None,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Update not performed. No row matched.")

        return "", 204
