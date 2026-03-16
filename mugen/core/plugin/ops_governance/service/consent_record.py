"""Provides a CRUD service for consent records and lifecycle actions."""

__all__ = ["ConsentRecordService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.plugin.ops_governance.api.validation import (
    RecordConsentActionValidation,
    WithdrawConsentActionValidation,
)
from mugen.core.plugin.ops_governance.contract.service.consent_record import (
    IConsentRecordService,
)
from mugen.core.plugin.ops_governance.domain import ConsentRecordDE


class ConsentRecordService(
    IRelationalService[ConsentRecordDE],
    IConsentRecordService,
):
    """A CRUD service for append-only consent records."""

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=ConsentRecordDE,
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
    ) -> ConsentRecordDE:
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
            abort(404, "Consent record not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def action_record_consent(
        self,
        *,
        tenant_id: uuid.UUID,
        where: Mapping[str, Any],  # noqa: ARG002
        auth_user_id: uuid.UUID,  # noqa: ARG002
        data: RecordConsentActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Append a new granted consent record."""
        now = self._now_utc()

        created = await self.create(
            {
                "tenant_id": tenant_id,
                "subject_user_id": data.subject_user_id,
                "controller_namespace": data.controller_namespace,
                "purpose": data.purpose,
                "scope": data.scope,
                "legal_basis": self._normalize_optional_text(data.legal_basis),
                "status": "granted",
                "effective_at": now,
                "expires_at": data.expires_at,
                "attributes": data.attributes,
            }
        )

        return {
            "Id": str(created.id),
            "Status": created.status,
        }, 201

    async def action_withdraw_consent(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: WithdrawConsentActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Append a withdrawn consent record for the selected consent."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if current.status != "granted":
            abort(409, "Only granted consent can be withdrawn.")

        now = self._now_utc()
        reason = self._normalize_optional_text(data.reason)

        created = await self.create(
            {
                "tenant_id": tenant_id,
                "subject_user_id": current.subject_user_id,
                "controller_namespace": current.controller_namespace,
                "purpose": current.purpose,
                "scope": current.scope,
                "legal_basis": current.legal_basis,
                "status": "withdrawn",
                "effective_at": now,
                "expires_at": current.expires_at,
                "source_consent_id": entity_id,
                "withdrawn_at": now,
                "withdrawn_by_user_id": auth_user_id,
                "withdrawal_reason": reason,
                "attributes": current.attributes,
            }
        )

        return {
            "Id": str(created.id),
            "Status": created.status,
        }, 201
