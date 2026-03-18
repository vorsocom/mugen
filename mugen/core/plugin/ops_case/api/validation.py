"""Validation schemas used by ops_case ACP actions."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import NonNegativeInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase

CaseCreateValidation = build_create_validation_from_pascal(
    "CaseCreateValidation",
    module=__name__,
    doc="Validate create payloads for Case.",
    required_fields=("TenantId", "Title"),
)

CaseUpdateValidation = build_update_validation_from_pascal(
    "CaseUpdateValidation",
    module=__name__,
    doc="Validate update payloads for Case.",
    optional_fields=(
        "Title",
        "Description",
        "Priority",
        "Severity",
        "DueAt",
        "SlaTargetAt",
        "Attributes",
    ),
)


class CaseTriageValidation(IValidationBase):
    """Validate payload for case triage actions."""

    row_version: NonNegativeInt

    priority: str | None = None
    severity: str | None = None
    due_at: datetime | None = None
    sla_target_at: datetime | None = None
    target_status: str | None = None
    note: str | None = None


class CaseAssignValidation(IValidationBase):
    """Validate payload for assignment actions."""

    row_version: NonNegativeInt

    owner_user_id: uuid.UUID | None = None
    queue_name: str | None = None
    reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_assignment_target(self) -> "CaseAssignValidation":
        if self.owner_user_id is None and not (self.queue_name or "").strip():
            raise ValueError("Provide OwnerUserId or QueueName.")
        return self


class CaseEscalateValidation(IValidationBase):
    """Validate payload for escalation actions."""

    row_version: NonNegativeInt

    escalation_level: NonNegativeInt | None = None
    reason: str | None = None
    note: str | None = None


class CaseResolveValidation(IValidationBase):
    """Validate payload for resolve actions."""

    row_version: NonNegativeInt

    resolution_summary: str | None = None
    note: str | None = None


class CaseCloseValidation(IValidationBase):
    """Validate payload for close actions."""

    row_version: NonNegativeInt

    note: str | None = None


class CaseReopenValidation(IValidationBase):
    """Validate payload for reopen actions."""

    row_version: NonNegativeInt

    note: str | None = None


class CaseCancelValidation(IValidationBase):
    """Validate payload for cancel actions."""

    row_version: NonNegativeInt

    reason: str | None = None
    note: str | None = None


class CaseLinkCreateValidation(IValidationBase):
    """Validate generic create inputs for CaseLink."""

    tenant_id: uuid.UUID

    case_id: uuid.UUID
    link_type: str
    target_type: str

    target_namespace: str | None = None
    target_id: uuid.UUID | None = None
    target_ref: str | None = None
    target_display: str | None = None
    relationship_kind: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_reference(self) -> "CaseLinkCreateValidation":
        if not (self.link_type or "").strip():
            raise ValueError("LinkType must be non-empty.")
        if not (self.target_type or "").strip():
            raise ValueError("TargetType must be non-empty.")

        target_ref = (self.target_ref or "").strip()
        if self.target_ref is not None and not target_ref:
            raise ValueError("TargetRef cannot be empty if provided.")

        if self.target_id is None and not target_ref:
            raise ValueError("Provide TargetId or TargetRef.")

        return self


CaseLinkUpdateValidation = build_update_validation_from_pascal(
    "CaseLinkUpdateValidation",
    module=__name__,
    doc="Validate update payloads for CaseLink.",
    optional_fields=(
        "TargetNamespace",
        "TargetId",
        "TargetRef",
        "TargetDisplay",
        "RelationshipKind",
        "Attributes",
    ),
)
