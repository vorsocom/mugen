"""Provides a CRUD service for delegation grants and lifecycle actions."""

__all__ = ["DelegationGrantService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_governance.api.validation import (
    GrantDelegationActionValidation,
    RevokeDelegationActionValidation,
)
from mugen.core.plugin.ops_governance.contract.service.delegation_grant import (
    IDelegationGrantService,
)
from mugen.core.plugin.ops_governance.domain import DelegationGrantDE


class DelegationGrantService(
    IRelationalService[DelegationGrantDE],
    IDelegationGrantService,
):
    """A CRUD service for append-only delegation records."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=DelegationGrantDE,
            table=table,
            rsg=rsg,
            **kwargs,
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

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> DelegationGrantDE:
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
            abort(404, "Delegation grant not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def action_grant_delegation(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: GrantDelegationActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Append a new active delegation grant record."""
        now = data.effective_from or self._now_utc()
        created = await self.create(
            {
                "tenant_id": tenant_id,
                "principal_user_id": data.principal_user_id,
                "delegate_user_id": data.delegate_user_id,
                "scope": data.scope,
                "purpose": self._normalize_optional_text(data.purpose),
                "status": "active",
                "effective_from": now,
                "expires_at": data.expires_at,
                "attributes": data.attributes,
            }
        )

        return {
            "Id": str(created.id),
            "Status": created.status,
        }, 201

    async def action_revoke_delegation(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: RevokeDelegationActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Append a revocation record for the selected delegation grant."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "active":
            abort(409, "Only active delegation can be revoked.")

        revoked_at = data.revoke_effective_at or self._now_utc()

        created = await self.create(
            {
                "tenant_id": tenant_id,
                "principal_user_id": current.principal_user_id,
                "delegate_user_id": current.delegate_user_id,
                "scope": current.scope,
                "purpose": current.purpose,
                "status": "revoked",
                "effective_from": current.effective_from,
                "expires_at": current.expires_at,
                "source_grant_id": entity_id,
                "revoked_at": revoked_at,
                "revoked_by_user_id": auth_user_id,
                "revocation_reason": self._normalize_optional_text(data.reason),
                "attributes": current.attributes,
            }
        )

        return {
            "Id": str(created.id),
            "Status": created.status,
        }, 201
