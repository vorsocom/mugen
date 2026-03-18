"""Validation schemas used by knowledge_pack ACP actions and creates."""

from typing import Any
import uuid

from pydantic import PositiveInt, model_validator

from mugen.core.plugin.acp.api.validation.crud_builder import (
    build_create_validation_from_pascal,
    build_update_validation_from_pascal,
)
from mugen.core.plugin.acp.contract.api.validation import IValidationBase

KnowledgePackCreateValidation = build_create_validation_from_pascal(
    "KnowledgePackCreateValidation",
    module=__name__,
    doc="Validate create payloads for KnowledgePack.",
    required_fields=("TenantId", "Key", "Name"),
)

KnowledgePackUpdateValidation = build_update_validation_from_pascal(
    "KnowledgePackUpdateValidation",
    module=__name__,
    doc="Validate update payloads for KnowledgePack.",
    optional_fields=(
        "Key",
        "Name",
        "Description",
        "IsActive",
        "CurrentVersionId",
        "Attributes",
    ),
)

KnowledgePackVersionCreateValidation = build_create_validation_from_pascal(
    "KnowledgePackVersionCreateValidation",
    module=__name__,
    doc="Validate create payloads for KnowledgePackVersion.",
    required_fields=("TenantId", "KnowledgePackId", "VersionNumber"),
)

KnowledgePackVersionUpdateValidation = build_update_validation_from_pascal(
    "KnowledgePackVersionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for KnowledgePackVersion.",
    optional_fields=("Note", "Attributes"),
)


class KnowledgePackVersionActionValidation(IValidationBase):
    """Base validator for version workflow actions that require RowVersion."""

    row_version: PositiveInt

    note: str | None = None


class KnowledgePackSubmitForReviewValidation(KnowledgePackVersionActionValidation):
    """Validate payload for submit_for_review actions."""


class KnowledgePackApproveValidation(KnowledgePackVersionActionValidation):
    """Validate payload for approve actions."""


class KnowledgePackRejectValidation(KnowledgePackVersionActionValidation):
    """Validate payload for reject actions."""

    reason: str | None = None


class KnowledgePackPublishValidation(KnowledgePackVersionActionValidation):
    """Validate payload for publish actions."""


class KnowledgePackArchiveValidation(KnowledgePackVersionActionValidation):
    """Validate payload for archive actions."""

    reason: str | None = None


class KnowledgePackRollbackVersionValidation(KnowledgePackVersionActionValidation):
    """Validate payload for rollback_version actions."""


class KnowledgeEntryCreateValidation(IValidationBase):
    """Validate generic create inputs for KnowledgeEntry."""

    tenant_id: uuid.UUID
    knowledge_pack_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID

    entry_key: str
    title: str

    summary: str | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_key_and_title(self) -> "KnowledgeEntryCreateValidation":
        if not (self.entry_key or "").strip():
            raise ValueError("EntryKey must be non-empty.")
        if not (self.title or "").strip():
            raise ValueError("Title must be non-empty.")
        if self.summary is not None and not (self.summary or "").strip():
            raise ValueError("Summary cannot be empty if provided.")
        return self


KnowledgeEntryUpdateValidation = build_update_validation_from_pascal(
    "KnowledgeEntryUpdateValidation",
    module=__name__,
    doc="Validate update payloads for KnowledgeEntry.",
    optional_fields=("EntryKey", "Title", "Summary", "IsActive", "Attributes"),
)


class KnowledgeEntryRevisionCreateValidation(IValidationBase):
    """Validate generic create inputs for KnowledgeEntryRevision."""

    tenant_id: uuid.UUID
    knowledge_entry_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID

    revision_number: PositiveInt

    body: str | None = None
    body_json: dict[str, Any] | None = None

    channel: str | None = None
    locale: str | None = None
    category: str | None = None

    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_content_and_scope(self) -> "KnowledgeEntryRevisionCreateValidation":
        has_body = bool((self.body or "").strip())
        has_json = bool(self.body_json)

        if not has_body and not has_json:
            raise ValueError("Provide Body or BodyJson.")

        if self.body is not None and not has_body:
            raise ValueError("Body cannot be empty if provided.")

        if self.channel is not None and not (self.channel or "").strip():
            raise ValueError("Channel cannot be empty if provided.")

        if self.locale is not None and not (self.locale or "").strip():
            raise ValueError("Locale cannot be empty if provided.")

        if self.category is not None and not (self.category or "").strip():
            raise ValueError("Category cannot be empty if provided.")

        return self


KnowledgeEntryRevisionUpdateValidation = build_update_validation_from_pascal(
    "KnowledgeEntryRevisionUpdateValidation",
    module=__name__,
    doc="Validate update payloads for KnowledgeEntryRevision.",
    optional_fields=("Body", "BodyJson", "Channel", "Locale", "Category", "Attributes"),
)


class KnowledgeScopeCreateValidation(IValidationBase):
    """Validate generic create inputs for KnowledgeScope."""

    tenant_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID
    knowledge_entry_revision_id: uuid.UUID

    channel: str | None = None
    locale: str | None = None
    category: str | None = None

    is_active: bool | None = None
    attributes: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _validate_scope_values(self) -> "KnowledgeScopeCreateValidation":
        if self.channel is not None and not (self.channel or "").strip():
            raise ValueError("Channel cannot be empty if provided.")

        if self.locale is not None and not (self.locale or "").strip():
            raise ValueError("Locale cannot be empty if provided.")

        if self.category is not None and not (self.category or "").strip():
            raise ValueError("Category cannot be empty if provided.")

        return self


KnowledgeScopeUpdateValidation = build_update_validation_from_pascal(
    "KnowledgeScopeUpdateValidation",
    module=__name__,
    doc="Validate update payloads for KnowledgeScope.",
    optional_fields=("Channel", "Locale", "Category", "IsActive", "Attributes"),
)
