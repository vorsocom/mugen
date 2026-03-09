"""Validation schemas used by channel_orchestration ACP actions."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class EvaluateIntakeValidation(IValidationBase):
    """Validate payload for evaluate_intake actions."""

    row_version: NonNegativeInt

    keyword: str | None = None
    menu_option: str | None = None
    intent: str | None = None

    @model_validator(mode="after")
    def _validate_input(self) -> "EvaluateIntakeValidation":
        keyword = (self.keyword or "").strip()
        menu_option = (self.menu_option or "").strip()
        intent = (self.intent or "").strip()

        if not keyword and not menu_option and not intent:
            raise ValueError("Provide Keyword, MenuOption, or Intent.")

        return self


class IngressBindingCreateValidation(IValidationBase):
    """Validate create payloads for ingress bindings."""

    tenant_id: uuid.UUID

    channel_profile_id: uuid.UUID | None = None
    channel_key: str
    identifier_type: str
    identifier_value: str

    @model_validator(mode="after")
    def _validate_required_strings(self) -> "IngressBindingCreateValidation":
        self.channel_key = self.channel_key.strip()
        if self.channel_key == "":
            raise ValueError("ChannelKey must be non-empty.")

        self.identifier_type = self.identifier_type.strip()
        if self.identifier_type == "":
            raise ValueError("IdentifierType must be non-empty.")

        self.identifier_value = self.identifier_value.strip()
        if self.identifier_value == "":
            raise ValueError("IdentifierValue must be non-empty.")

        return self


class RouteConversationValidation(IValidationBase):
    """Validate payload for route actions."""

    row_version: NonNegativeInt

    route_key: str | None = None
    queue_name: str | None = None
    owner_user_id: uuid.UUID | None = None
    service_key: str | None = None


class EscalateConversationValidation(IValidationBase):
    """Validate payload for escalate actions."""

    row_version: NonNegativeInt

    escalation_level: NonNegativeInt | None = None
    reason: str | None = None


class ApplyThrottleValidation(IValidationBase):
    """Validate payload for apply_throttle actions."""

    row_version: NonNegativeInt

    increment_count: PositiveInt = 1


class SetFallbackValidation(IValidationBase):
    """Validate payload for set_fallback actions."""

    row_version: NonNegativeInt

    fallback_mode: str
    fallback_target: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_mode(self) -> "SetFallbackValidation":
        if not (self.fallback_mode or "").strip():
            raise ValueError("FallbackMode must be non-empty.")
        return self


class BlockSenderActionValidation(IValidationBase):
    """Validate payload for block_sender actions."""

    sender_key: str

    channel_profile_id: uuid.UUID | None = None
    reason: str | None = None
    expires_at: datetime | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_sender(self) -> "BlockSenderActionValidation":
        if not (self.sender_key or "").strip():
            raise ValueError("SenderKey must be non-empty.")
        return self


class UnblockSenderActionValidation(IValidationBase):
    """Validate payload for unblock_sender actions."""

    sender_key: str

    channel_profile_id: uuid.UUID | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def _validate_sender(self) -> "UnblockSenderActionValidation":
        if not (self.sender_key or "").strip():
            raise ValueError("SenderKey must be non-empty.")
        return self


class WorkItemCreateFromChannelValidation(IValidationBase):
    """Validate payload for create_from_channel actions."""

    trace_id: str | None = None
    source: str

    participants: dict[str, Any] | list[Any] | None = None
    content: dict[str, Any] | list[Any] | None = None
    attachments: dict[str, Any] | list[Any] | None = None
    signals: dict[str, Any] | list[Any] | None = None
    extractions: dict[str, Any] | list[Any] | None = None

    linked_case_id: uuid.UUID | None = None
    linked_workflow_instance_id: uuid.UUID | None = None

    note: str | None = None

    @model_validator(mode="after")
    def _validate_strings(self) -> "WorkItemCreateFromChannelValidation":
        if self.trace_id is not None and not self.trace_id.strip():
            raise ValueError("TraceId cannot be empty if provided.")
        if not (self.source or "").strip():
            raise ValueError("Source must be non-empty.")
        return self


class WorkItemLinkToCaseValidation(IValidationBase):
    """Validate payload for link_to_case actions."""

    row_version: NonNegativeInt

    linked_case_id: uuid.UUID | None = None
    linked_workflow_instance_id: uuid.UUID | None = None
    note: str | None = None

    @model_validator(mode="after")
    def _validate_link_target(self) -> "WorkItemLinkToCaseValidation":
        if self.linked_case_id is None and self.linked_workflow_instance_id is None:
            raise ValueError("Provide LinkedCaseId or LinkedWorkflowInstanceId.")
        return self


class WorkItemReplayValidation(IValidationBase):
    """Validate payload for replay actions."""

    include_metadata: bool = False
