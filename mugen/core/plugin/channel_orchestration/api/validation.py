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
