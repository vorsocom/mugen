"""Provides a CRUD service for policy definitions and evaluation actions."""

__all__ = ["PolicyDefinitionService"]

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
    EvaluatePolicyActionValidation,
)
from mugen.core.plugin.ops_governance.contract.service.policy_definition import (
    IPolicyDefinitionService,
)
from mugen.core.plugin.ops_governance.domain import PolicyDefinitionDE
from mugen.core.plugin.ops_governance.service.policy_decision_log import (
    PolicyDecisionLogService,
)


class PolicyDefinitionService(
    IRelationalService[PolicyDefinitionDE],
    IPolicyDefinitionService,
):
    """A CRUD service for policy definitions and evaluation events."""

    _DECISION_LOG_TABLE = "ops_governance_policy_decision_log"

    def __init__(self, table: str, rsg: IRelationalStorageGateway, **kwargs):
        super().__init__(
            de_type=PolicyDefinitionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._decision_log_service = PolicyDecisionLogService(
            table=self._DECISION_LOG_TABLE,
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
    ) -> PolicyDefinitionDE:
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
            abort(404, "Policy definition not found.")

        abort(409, "RowVersion conflict. Refresh and retry.")

    async def _update_with_row_version(
        self,
        *,
        where: Mapping[str, Any],
        expected_row_version: int,
        changes: Mapping[str, Any],
    ) -> PolicyDefinitionDE:
        svc: ICrudServiceWithRowVersion[PolicyDefinitionDE] = self

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

    async def action_evaluate_policy(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: EvaluatePolicyActionValidation,
    ) -> tuple[dict[str, Any], int]:
        """Evaluate a policy and append a policy decision log record."""
        expected_row_version = int(data.row_version)
        current = await self._get_for_action(
            where=where,
            expected_row_version=expected_row_version,
        )
        if not bool(current.is_active):
            abort(409, "Policy definition is inactive.")

        now = self._now_utc()
        decision = await self._decision_log_service.create(
            {
                "tenant_id": tenant_id,
                "policy_definition_id": entity_id,
                "subject_namespace": data.subject_namespace,
                "subject_id": data.subject_id,
                "subject_ref": self._normalize_optional_text(data.subject_ref),
                "decision": data.decision.strip().lower(),
                "outcome": data.outcome.strip().lower(),
                "reason": self._normalize_optional_text(data.reason),
                "evaluated_at": now,
                "evaluator_user_id": auth_user_id,
                "request_context": data.request_context,
                "attributes": data.attributes,
            }
        )

        await self._update_with_row_version(
            where=where,
            expected_row_version=expected_row_version,
            changes={
                "last_evaluated_at": now,
                "last_evaluated_by_user_id": auth_user_id,
                "last_decision_log_id": decision.id,
            },
        )

        return {
            "DecisionLogId": str(decision.id),
            "Decision": decision.decision,
            "Outcome": decision.outcome,
        }, 200
