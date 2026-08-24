"""Provides a CRUD service for billing products."""

__all__ = ["ProductService"]

from datetime import datetime, timezone
from typing import Any, Mapping
import uuid

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict

from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.billing.contract.service.product import IProductService
from mugen.core.plugin.billing.domain import ProductDE


class ProductService(  # pylint: disable=too-few-public-methods
    IRelationalService[ProductDE],
    IProductService,
):
    """A CRUD service for billing products."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ProductDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )

    @staticmethod
    def _normalize_changes(values: Mapping[str, Any]) -> dict[str, Any]:
        payload = dict(values)
        for field_name in ("code", "name", "description"):
            value = payload.get(field_name)
            if isinstance(value, str):
                payload[field_name] = value.strip()
        return payload

    async def create(self, values: Mapping[str, Any]) -> ProductDE:
        return await super().create(self._normalize_changes(values))

    async def update(
        self,
        where: Mapping[str, Any],
        changes: Mapping[str, Any],
    ) -> ProductDE | None:
        return await super().update(where, self._normalize_changes(changes))

    async def update_with_row_version(
        self,
        where: Mapping[str, Any],
        *,
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> ProductDE | None:
        return await super().update_with_row_version(
            where,
            expected_row_version=expected_row_version,
            changes=self._normalize_changes(changes),
        )

    async def entity_action_archive(
        self,
        *,
        entity_id: uuid.UUID,
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Soft-delete a global Product."""
        try:
            current = await self.get({"id": entity_id})
        except SQLAlchemyError:
            abort(500)

        if current is None:
            abort(404, "Product not found.")
        if current.deleted_at is not None:
            return "", 204

        try:
            updated = await self.update_with_row_version(
                {"id": entity_id},
                expected_row_version=int(data.row_version),
                changes={
                    "deleted_at": datetime.now(timezone.utc),
                    "deleted_by_user_id": auth_user_id,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)

        if updated is None:
            abort(404, "Archive not performed. No row matched.")
        return "", 204
