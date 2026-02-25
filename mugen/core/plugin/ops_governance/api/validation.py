"""Validation schemas used by ops_governance ACP actions and create payloads."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import Field, NonNegativeInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class ConsentRecordCreateValidation(IValidationBase):
    """Validate generic create inputs for ConsentRecord."""

    tenant_id: uuid.UUID
    subject_user_id: uuid.UUID

    controller_namespace: str
    purpose: str
    scope: str

    legal_basis: str | None = None
    expires_at: datetime | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "ConsentRecordCreateValidation":
        if not (self.controller_namespace or "").strip():
            raise ValueError("ControllerNamespace must be non-empty.")
        if not (self.purpose or "").strip():
            raise ValueError("Purpose must be non-empty.")
        if not (self.scope or "").strip():
            raise ValueError("Scope must be non-empty.")
        if self.legal_basis is not None and not (self.legal_basis or "").strip():
            raise ValueError("LegalBasis cannot be empty if provided.")
        return self


class DelegationGrantCreateValidation(IValidationBase):
    """Validate generic create inputs for DelegationGrant."""

    tenant_id: uuid.UUID
    principal_user_id: uuid.UUID
    delegate_user_id: uuid.UUID

    scope: str
    purpose: str | None = None

    effective_from: datetime | None = None
    expires_at: datetime | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "DelegationGrantCreateValidation":
        if self.principal_user_id == self.delegate_user_id:
            raise ValueError("PrincipalUserId and DelegateUserId must differ.")
        if not (self.scope or "").strip():
            raise ValueError("Scope must be non-empty.")
        if self.purpose is not None and not (self.purpose or "").strip():
            raise ValueError("Purpose cannot be empty if provided.")
        return self


class PolicyDefinitionCreateValidation(IValidationBase):
    """Validate generic create inputs for PolicyDefinition."""

    tenant_id: uuid.UUID

    code: str
    name: str

    description: str | None = None
    policy_type: str | None = None
    rule_ref: str | None = None

    evaluation_mode: str = "advisory"
    engine: str = "dsl"
    is_active: bool = True

    document_json: dict[str, Any] = Field(default_factory=dict)
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "PolicyDefinitionCreateValidation":
        if not (self.code or "").strip():
            raise ValueError("Code must be non-empty.")
        if not (self.name or "").strip():
            raise ValueError("Name must be non-empty.")
        if self.description is not None and not (self.description or "").strip():
            raise ValueError("Description cannot be empty if provided.")
        if self.policy_type is not None and not (self.policy_type or "").strip():
            raise ValueError("PolicyType cannot be empty if provided.")
        if self.rule_ref is not None and not (self.rule_ref or "").strip():
            raise ValueError("RuleRef cannot be empty if provided.")
        if not (self.evaluation_mode or "").strip():
            raise ValueError("EvaluationMode must be non-empty.")
        if not (self.engine or "").strip():
            raise ValueError("Engine must be non-empty.")
        return self


class RetentionPolicyCreateValidation(IValidationBase):
    """Validate generic create inputs for RetentionPolicy."""

    tenant_id: uuid.UUID

    code: str
    name: str

    target_namespace: str
    target_entity: str | None = None

    description: str | None = None

    retention_days: NonNegativeInt = 0
    redaction_after_days: NonNegativeInt | None = None

    legal_hold_allowed: bool = True
    action_mode: str = "mark"
    downstream_job_ref: str | None = None

    is_active: bool = True
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "RetentionPolicyCreateValidation":
        if not (self.code or "").strip():
            raise ValueError("Code must be non-empty.")
        if not (self.name or "").strip():
            raise ValueError("Name must be non-empty.")
        if not (self.target_namespace or "").strip():
            raise ValueError("TargetNamespace must be non-empty.")
        if self.target_entity is not None and not (self.target_entity or "").strip():
            raise ValueError("TargetEntity cannot be empty if provided.")
        if self.description is not None and not (self.description or "").strip():
            raise ValueError("Description cannot be empty if provided.")
        if self.downstream_job_ref is not None and not (
            self.downstream_job_ref or ""
        ).strip():
            raise ValueError("DownstreamJobRef cannot be empty if provided.")
        if not (self.action_mode or "").strip():
            raise ValueError("ActionMode must be non-empty.")
        return self


class DataHandlingRecordCreateValidation(IValidationBase):
    """Validate generic create inputs for DataHandlingRecord."""

    tenant_id: uuid.UUID
    retention_policy_id: uuid.UUID | None = None

    subject_namespace: str
    subject_id: uuid.UUID | None = None
    subject_ref: str | None = None

    request_type: str = "retention"
    request_status: str = "pending"

    requested_at: datetime | None = None
    due_at: datetime | None = None

    resolution_note: str | None = None
    evidence_ref: str | None = None

    meta: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "DataHandlingRecordCreateValidation":
        if not (self.subject_namespace or "").strip():
            raise ValueError("SubjectNamespace must be non-empty.")
        if self.subject_id is None and not (self.subject_ref or "").strip():
            raise ValueError("Provide SubjectId or SubjectRef.")
        if self.subject_ref is not None and not (self.subject_ref or "").strip():
            raise ValueError("SubjectRef cannot be empty if provided.")
        if not (self.request_type or "").strip():
            raise ValueError("RequestType must be non-empty.")
        if not (self.request_status or "").strip():
            raise ValueError("RequestStatus must be non-empty.")
        if self.resolution_note is not None and not (
            self.resolution_note or ""
        ).strip():
            raise ValueError("ResolutionNote cannot be empty if provided.")
        if self.evidence_ref is not None and not (self.evidence_ref or "").strip():
            raise ValueError("EvidenceRef cannot be empty if provided.")
        return self


class RecordConsentActionValidation(IValidationBase):
    """Validate payload for record_consent actions."""

    subject_user_id: uuid.UUID

    controller_namespace: str
    purpose: str
    scope: str

    legal_basis: str | None = None
    expires_at: datetime | None = None

    attributes: dict[str, Any] | None = None


class WithdrawConsentActionValidation(IValidationBase):
    """Validate payload for withdraw_consent actions."""

    row_version: NonNegativeInt
    reason: str | None = None


class GrantDelegationActionValidation(IValidationBase):
    """Validate payload for grant_delegation actions."""

    principal_user_id: uuid.UUID
    delegate_user_id: uuid.UUID

    scope: str
    purpose: str | None = None

    effective_from: datetime | None = None
    expires_at: datetime | None = None

    attributes: dict[str, Any] | None = None


class RevokeDelegationActionValidation(IValidationBase):
    """Validate payload for revoke_delegation actions."""

    row_version: NonNegativeInt

    reason: str | None = None
    revoke_effective_at: datetime | None = None


class EvaluatePolicyActionValidation(IValidationBase):
    """Validate payload for evaluate_policy actions."""

    row_version: NonNegativeInt

    trace_id: str | None = None

    subject_namespace: str
    subject_id: uuid.UUID | None = None
    subject_ref: str | None = None

    input_json: dict[str, Any] | None = None
    actor_json: dict[str, Any] | None = None

    decision: str | None = None
    outcome: str | None = None

    reason: str | None = None
    request_context: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "EvaluatePolicyActionValidation":
        if not (self.subject_namespace or "").strip():
            raise ValueError("SubjectNamespace must be non-empty.")
        if self.subject_id is None and not (self.subject_ref or "").strip():
            raise ValueError("Provide SubjectId or SubjectRef.")
        if self.subject_ref is not None and not (self.subject_ref or "").strip():
            raise ValueError("SubjectRef cannot be empty if provided.")
        if self.trace_id is not None and not (self.trace_id or "").strip():
            raise ValueError("TraceId cannot be empty if provided.")

        if self.decision is not None:
            if not (self.decision or "").strip():
                raise ValueError("Decision cannot be empty if provided.")
            if self.outcome is not None and not (self.outcome or "").strip():
                raise ValueError("Outcome cannot be empty if provided.")
            if self.reason is not None and not (self.reason or "").strip():
                raise ValueError("Reason cannot be empty if provided.")
            return self

        if self.input_json is None:
            raise ValueError("InputJson must be provided in PDP mode.")
        if self.outcome is not None:
            raise ValueError("Outcome is supported only in legacy explicit mode.")
        if self.reason is not None and not (self.reason or "").strip():
            raise ValueError("Reason cannot be empty if provided.")
        return self


class ActivatePolicyVersionActionValidation(IValidationBase):
    """Validate payload for activate_version actions."""

    row_version: NonNegativeInt
    version: NonNegativeInt

    @model_validator(mode="after")
    def _validate_fields(self) -> "ActivatePolicyVersionActionValidation":
        if int(self.version) <= 0:
            raise ValueError("Version must be > 0.")
        return self


class ApplyRetentionActionValidation(IValidationBase):
    """Validate payload for apply_retention_action actions."""

    row_version: NonNegativeInt

    action_type: str

    subject_namespace: str
    subject_id: uuid.UUID | None = None
    subject_ref: str | None = None

    request_status: str = "pending"
    due_at: datetime | None = None

    note: str | None = None
    meta: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "ApplyRetentionActionValidation":
        if not (self.action_type or "").strip():
            raise ValueError("ActionType must be non-empty.")
        if not (self.subject_namespace or "").strip():
            raise ValueError("SubjectNamespace must be non-empty.")
        if self.subject_id is None and not (self.subject_ref or "").strip():
            raise ValueError("Provide SubjectId or SubjectRef.")
        if self.subject_ref is not None and not (self.subject_ref or "").strip():
            raise ValueError("SubjectRef cannot be empty if provided.")
        if not (self.request_status or "").strip():
            raise ValueError("RequestStatus must be non-empty.")
        if self.note is not None and not (self.note or "").strip():
            raise ValueError("Note cannot be empty if provided.")
        return self
