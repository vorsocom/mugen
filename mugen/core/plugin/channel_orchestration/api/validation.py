"""Validation schemas used by channel_orchestration ACP actions."""

from datetime import datetime
from typing import Any
import uuid

from pydantic import NonNegativeInt, PositiveInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase


class ChannelProfileCreateValidation(IValidationBase):
    """Validate create payloads for channel profiles."""

    tenant_id: uuid.UUID
    channel_key: str
    profile_key: str
    client_profile_id: uuid.UUID | None = None
    service_route_default_key: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ChannelProfileCreateValidation":
        self.channel_key = self.channel_key.strip()
        if self.channel_key == "":
            raise ValueError("ChannelKey must be non-empty.")

        self.profile_key = self.profile_key.strip()
        if self.profile_key == "":
            raise ValueError("ProfileKey must be non-empty.")

        if self.service_route_default_key is not None:
            self.service_route_default_key = (
                self.service_route_default_key.strip() or None
            )

        return self


class ChannelProfileUpdateValidation(IValidationBase):
    """Validate update payloads for channel profiles."""

    client_profile_id: uuid.UUID | None = None
    display_name: str | None = None
    service_route_default_key: str | None = None
    route_default_key: str | None = None
    policy_id: uuid.UUID | None = None
    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> "ChannelProfileUpdateValidation":
        if not self.model_fields_set:
            raise ValueError("At least one mutable field must be provided.")

        for field_name in (
            "display_name",
            "service_route_default_key",
            "route_default_key",
        ):
            if field_name not in self.model_fields_set:
                continue
            value = getattr(self, field_name)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized == "":
                raise ValueError(
                    f"{''.join(part.title() for part in field_name.split('_'))} "
                    "must be non-empty when provided."
                )
            setattr(self, field_name, normalized)

        return self


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
    service_route_key: str | None = None

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

        if self.service_route_key is not None:
            self.service_route_key = self.service_route_key.strip() or None

        return self


IngressBindingUpdateValidation = build_update_validation_from_pascal(
    "IngressBindingUpdateValidation",
    module=__name__,
    doc="Validate update payloads for ingress bindings.",
    optional_fields=(
        "ChannelProfileId",
        "ChannelKey",
        "IdentifierType",
        "IdentifierValue",
        "ServiceRouteKey",
        "IsActive",
        "Attributes",
    ),
)

IntakeRuleCreateValidation = build_create_validation_from_pascal(
    "IntakeRuleCreateValidation",
    module=__name__,
    doc="Validate create payloads for intake rules.",
    required_fields=("TenantId", "Name", "MatchKind", "MatchValue"),
)

IntakeRuleUpdateValidation = build_update_validation_from_pascal(
    "IntakeRuleUpdateValidation",
    module=__name__,
    doc="Validate update payloads for intake rules.",
    optional_fields=(
        "ChannelProfileId",
        "Name",
        "MatchKind",
        "MatchValue",
        "RouteKey",
        "Priority",
        "IsActive",
        "Attributes",
    ),
)

RoutingRuleCreateValidation = build_create_validation_from_pascal(
    "RoutingRuleCreateValidation",
    module=__name__,
    doc="Validate create payloads for routing rules.",
    required_fields=("TenantId", "RouteKey"),
)

RoutingRuleUpdateValidation = build_update_validation_from_pascal(
    "RoutingRuleUpdateValidation",
    module=__name__,
    doc="Validate update payloads for routing rules.",
    optional_fields=(
        "ChannelProfileId",
        "RouteKey",
        "TargetQueueName",
        "OwnerUserId",
        "TargetServiceKey",
        "TargetNamespace",
        "Priority",
        "IsActive",
        "Attributes",
    ),
)

OrchestrationPolicyCreateValidation = build_create_validation_from_pascal(
    "OrchestrationPolicyCreateValidation",
    module=__name__,
    doc="Validate create payloads for orchestration policies.",
    required_fields=("TenantId", "Code", "Name"),
)

OrchestrationPolicyUpdateValidation = build_update_validation_from_pascal(
    "OrchestrationPolicyUpdateValidation",
    module=__name__,
    doc="Validate update payloads for orchestration policies.",
    optional_fields=(
        "Code",
        "Name",
        "HoursMode",
        "EscalationMode",
        "FallbackPolicy",
        "FallbackTarget",
        "EscalationTarget",
        "EscalationAfterSeconds",
        "IsActive",
        "Attributes",
    ),
)

ConversationStateCreateValidation = build_create_validation_from_pascal(
    "ConversationStateCreateValidation",
    module=__name__,
    doc="Validate create payloads for conversation states.",
    required_fields=("TenantId", "SenderKey"),
)

ConversationStateUpdateValidation = build_update_validation_from_pascal(
    "ConversationStateUpdateValidation",
    module=__name__,
    doc="Validate update payloads for conversation states.",
    optional_fields=(
        "ChannelProfileId",
        "PolicyId",
        "SenderKey",
        "ExternalConversationRef",
        "Status",
        "ServiceRouteKey",
        "RouteKey",
        "AssignedQueueName",
        "AssignedOwnerUserId",
        "AssignedServiceKey",
        "FallbackMode",
        "FallbackTarget",
        "FallbackReason",
        "IsFallbackActive",
        "Attributes",
    ),
)

ThrottleRuleCreateValidation = build_create_validation_from_pascal(
    "ThrottleRuleCreateValidation",
    module=__name__,
    doc="Validate create payloads for throttle rules.",
    required_fields=("TenantId", "Code"),
)

ThrottleRuleUpdateValidation = build_update_validation_from_pascal(
    "ThrottleRuleUpdateValidation",
    module=__name__,
    doc="Validate update payloads for throttle rules.",
    optional_fields=(
        "ChannelProfileId",
        "Code",
        "SenderScope",
        "WindowSeconds",
        "MaxMessages",
        "BlockOnViolation",
        "BlockDurationSeconds",
        "Priority",
        "IsActive",
        "Attributes",
    ),
)

BlocklistEntryCreateValidation = build_create_validation_from_pascal(
    "BlocklistEntryCreateValidation",
    module=__name__,
    doc="Validate create payloads for blocklist entries.",
    required_fields=("TenantId", "SenderKey"),
)

BlocklistEntryUpdateValidation = build_update_validation_from_pascal(
    "BlocklistEntryUpdateValidation",
    module=__name__,
    doc="Validate update payloads for blocklist entries.",
    optional_fields=(
        "ChannelProfileId",
        "SenderKey",
        "Reason",
        "ExpiresAt",
        "IsActive",
        "Attributes",
    ),
)

WorkItemCreateValidation = build_create_validation_from_pascal(
    "WorkItemCreateValidation",
    module=__name__,
    doc="Validate create payloads for work items.",
    required_fields=("TenantId", "TraceId", "Source"),
)

WorkItemUpdateValidation = build_update_validation_from_pascal(
    "WorkItemUpdateValidation",
    module=__name__,
    doc="Validate update payloads for work items.",
    optional_fields=(
        "Source",
        "Participants",
        "Content",
        "Attachments",
        "Signals",
        "Extractions",
        "LinkedCaseId",
        "LinkedWorkflowInstanceId",
        "Attributes",
    ),
)


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
