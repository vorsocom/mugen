"""Validation schemas used by ops_workflow ACP actions."""

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

    client_action_key: str | None = None
    note: str | None = None
    payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_transition_selector(self) -> "WorkflowAdvanceValidation":
        has_key = bool((self.transition_key or "").strip())
        has_state = self.to_state_id is not None
        if not has_key and not has_state:
            raise ValueError("Provide TransitionKey or ToStateId.")
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
