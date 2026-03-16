"""Validation schemas used by ops_workflow ACP actions."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import NonNegativeInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class WorkflowStartInstanceValidation(IValidationBase):
    """Validate payload for start_instance actions."""

    row_version: NonNegativeInt

    start_state_id: uuid.UUID | None = None
    client_action_key: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_client_action_key(self) -> "WorkflowStartInstanceValidation":
        if self.client_action_key is not None and not self.client_action_key.strip():
            raise ValueError("ClientActionKey cannot be empty if provided.")
        return self


class WorkflowAdvanceValidation(IValidationBase):
    """Validate payload for advance actions."""

    row_version: NonNegativeInt

    transition_key: str | None = None
    to_state_id: uuid.UUID | None = None

    assignee_user_id: uuid.UUID | None = None
    queue_name: str | None = None

    task_title: str | None = None
    task_description: str | None = None

    policy_definition_id: uuid.UUID | None = None
    policy_code: str | None = None

    client_action_key: str | None = None
    note: str | None = None
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_transition_selector(self) -> "WorkflowAdvanceValidation":
        has_key = bool((self.transition_key or "").strip())
        has_state = self.to_state_id is not None
        if not has_key and not has_state:
            raise ValueError("Provide TransitionKey or ToStateId.")
        if self.policy_code is not None and not self.policy_code.strip():
            raise ValueError("PolicyCode cannot be empty if provided.")
        if self.client_action_key is not None and not self.client_action_key.strip():
            raise ValueError("ClientActionKey cannot be empty if provided.")
        return self


class WorkflowApproveValidation(IValidationBase):
    """Validate payload for approve actions."""

    row_version: NonNegativeInt

    client_action_key: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_client_action_key(self) -> "WorkflowApproveValidation":
        if self.client_action_key is not None and not self.client_action_key.strip():
            raise ValueError("ClientActionKey cannot be empty if provided.")
        return self


class WorkflowRejectValidation(IValidationBase):
    """Validate payload for reject actions."""

    row_version: NonNegativeInt

    client_action_key: str | None = None
    reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_client_action_key(self) -> "WorkflowRejectValidation":
        if self.client_action_key is not None and not self.client_action_key.strip():
            raise ValueError("ClientActionKey cannot be empty if provided.")
        return self


class WorkflowCancelInstanceValidation(IValidationBase):
    """Validate payload for cancel_instance actions."""

    row_version: NonNegativeInt

    client_action_key: str | None = None
    reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_client_action_key(self) -> "WorkflowCancelInstanceValidation":
        if self.client_action_key is not None and not self.client_action_key.strip():
            raise ValueError("ClientActionKey cannot be empty if provided.")
        return self


class WorkflowReplayValidation(IValidationBase):
    """Validate payload for replay actions."""

    repair: bool = False


class WorkflowCompensateValidation(IValidationBase):
    """Validate payload for compensate actions."""

    row_version: NonNegativeInt
    transition_key: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_transition_key(self) -> "WorkflowCompensateValidation":
        if self.transition_key is not None and not self.transition_key.strip():
            raise ValueError("TransitionKey cannot be empty if provided.")
        return self


class WorkflowAssignTaskValidation(IValidationBase):
    """Validate payload for assign_task actions."""

    row_version: NonNegativeInt

    assignee_user_id: uuid.UUID | None = None
    queue_name: str | None = None
    reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_assignment_target(self) -> "WorkflowAssignTaskValidation":
        if self.assignee_user_id is None and not (self.queue_name or "").strip():
            raise ValueError("Provide AssigneeUserId or QueueName.")
        return self


class WorkflowCompleteTaskValidation(IValidationBase):
    """Validate payload for complete_task actions."""

    row_version: NonNegativeInt

    outcome: str | None = None
    note: str | None = None


class WorkflowDecisionRequestOpenValidation(IValidationBase):
    """Validate payload for opening workflow decision requests."""

    trace_id: str | None = None
    template_key: str

    requester_actor_json: dict[str, Any] | None = None
    assigned_to_json: dict[str, Any] | None = None
    options_json: dict[str, Any] | None = None
    context_json: dict[str, Any] | None = None

    workflow_instance_id: uuid.UUID | None = None
    workflow_task_id: uuid.UUID | None = None

    due_at: datetime | None = None
    attributes: dict[str, Any] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "WorkflowDecisionRequestOpenValidation":
        if not (self.template_key or "").strip():
            raise ValueError("TemplateKey must be non-empty.")
        if self.trace_id is not None and not (self.trace_id or "").strip():
            raise ValueError("TraceId cannot be empty if provided.")
        if self.note is not None and not (self.note or "").strip():
            raise ValueError("Note cannot be empty if provided.")
        return self


class WorkflowDecisionRequestResolveValidation(IValidationBase):
    """Validate payload for resolving workflow decision requests."""

    row_version: NonNegativeInt

    outcome: str
    reason: str | None = None

    resolver_actor_json: dict[str, Any] | None = None
    outcome_json: dict[str, Any] | None = None
    signature_json: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_required_fields(self) -> "WorkflowDecisionRequestResolveValidation":
        if not (self.outcome or "").strip():
            raise ValueError("Outcome must be non-empty.")
        if self.reason is not None and not (self.reason or "").strip():
            raise ValueError("Reason cannot be empty if provided.")
        if self.note is not None and not (self.note or "").strip():
            raise ValueError("Note cannot be empty if provided.")
        return self


class WorkflowDecisionRequestCancelValidation(IValidationBase):
    """Validate payload for cancelling workflow decision requests."""

    row_version: NonNegativeInt

    reason: str | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_optional_fields(self) -> "WorkflowDecisionRequestCancelValidation":
        if self.reason is not None and not (self.reason or "").strip():
            raise ValueError("Reason cannot be empty if provided.")
        if self.note is not None and not (self.note or "").strip():
            raise ValueError("Note cannot be empty if provided.")
        return self


class WorkflowDecisionRequestExpireOverdueValidation(IValidationBase):
    """Validate payload for expiring overdue workflow decision requests."""

    as_of_utc: datetime | None = None
    limit: NonNegativeInt = 100
    note: str | None = None

    @model_validator(mode="after")
    def _validate_limit(self) -> "WorkflowDecisionRequestExpireOverdueValidation":
        if int(self.limit) <= 0:
            raise ValueError("Limit must be > 0.")
        if self.note is not None and not (self.note or "").strip():
            raise ValueError("Note cannot be empty if provided.")
        return self
