"""Provides a CRUD service for retention policies and metadata actions."""

__all__ = ["RetentionPolicyService"]

from datetime import datetime, timezone
import uuid
from typing import Any, Mapping

from quart import abort
from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.rdbms.crud_base import (
    ICrudServiceWithRowVersion,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import RowVersionConflict
from mugen.core.plugin.ops_governance.api.validation import (
    ApplyRetentionActionValidation,
)
from mugen.core.plugin.ops_governance.contract.service.retention_policy import (
    IRetentionPolicyService,
)
from mugen.core.plugin.ops_governance.domain import RetentionPolicyDE
from mugen.core.plugin.ops_governance.service.data_handling_record import (
    DataHandlingRecordService,
)


class RetentionPolicyService(
    IRelationalService[RetentionPolicyDE],
    IRetentionPolicyService,
):
    """A CRUD service for retention policy metadata and action signals."""

    _DATA_HANDLING_TABLE = "ops_governance_data_handling_record"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=RetentionPolicyDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._data_handling_service = DataHandlingRecordService(
            table=self._DATA_HANDLING_TABLE,
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

    async def _get_for_action(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
    ) -> RetentionPolicyDE:
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
            abort(404, "Retention policy not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> RetentionPolicyDE:
        svc: ICrudServiceWithRowVersion[RetentionPolicyDE] = self

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

    async def action_apply_retention_action(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: ApplyRetentionActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Persist metadata about a retention action request."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if not bool(current.is_active):
            abort(409, "Retention policy is inactive.")

        now = self._now_utc()

        record = await self._data_handling_service.create(
            {
                "tenant_id": tenant_id,
                "retention_policy_id": entity_id,
                "subject_namespace": data.subject_namespace,
                "subject_id": data.subject_id,
                "subject_ref": self._normalize_optional_text(data.subject_ref),
                "request_type": data.action_type.strip().lower(),
                "request_status": data.request_status.strip().lower(),
                "requested_at": now,
                "due_at": data.due_at,
                "resolution_note": self._normalize_optional_text(data.note),
                "handled_by_user_id": auth_user_id,
                "meta": data.meta,
            }
        )

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "last_action_applied_at": now,
                "last_action_type": data.action_type.strip().lower(),
                "last_action_status": data.request_status.strip().lower(),
                "last_action_note": self._normalize_optional_text(data.note),
                "last_action_by_user_id": auth_user_id,
            },
        )

        return {
            "DataHandlingRecordId": str(record.id),
            "RequestStatus": record.request_status,
        }, 200
