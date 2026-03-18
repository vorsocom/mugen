"""Helpers for building CRUD payload validators for ACP generic endpoints."""

from __future__ import annotations

__all__ = [
    "build_create_validation",
    "build_create_validation_from_pascal",
    "build_update_validation",
    "build_update_validation_from_pascal",
]

from datetime import datetime
from typing import Any, ClassVar
import uuid

from pydantic import create_model, model_validator
from pydantic.alias_generators import to_pascal

from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.utility.string.case_conversion_helper import title_to_snake

_BOOL_FIELD_NAMES = frozenset(
    {
        "AutoBreach",
        "BlockOnViolation",
        "CacheEnabled",
        "CaptureCommit",
        "CaptureDroppedItems",
        "CapturePrepare",
        "CaptureSelectedItems",
        "LegalHoldAllowed",
        "RequireAllMetrics",
        "RequiresApproval",
        "TraceEnabled",
    }
)

_TEXT_FIELD_NAMES = frozenset(
    {
        "PhoneNumberId",
        "RecipientUserId",
        "TraceId",
    }
)

_DATETIME_FIELD_NAMES = frozenset(
    {
        "CancelAt",
        "CheckedAt",
        "CompletedAt",
        "CurrentPeriodEnd",
        "CurrentPeriodStart",
        "DueAt",
        "EffectiveFrom",
        "EffectiveTo",
        "ExpiresAt",
        "FailedAt",
        "FinishedAt",
        "IssuedAt",
        "LastRunAt",
        "OccurredAt",
        "PeriodEnd",
        "PeriodStart",
        "PublishedAt",
        "ReceivedAt",
        "RequestedAt",
        "StartedAt",
        "UploadedAt",
        "VoidedAt",
        "WindowEnd",
        "WindowStart",
    }
)

_ANY_FIELD_NAMES = frozenset(
    {
        "ActionsJson",
        "AllocatedQuantity",
        "Amount",
        "Attachments",
        "Attributes",
        "BillableWindowMinutes",
        "BodyJson",
        "BudgetJson",
        "BusinessDays",
        "BusinessEndTime",
        "BusinessStartTime",
        "CapabilitiesJson",
        "CapMinutes",
        "CapTasks",
        "CapUnits",
        "CompensationJson",
        "ConfigJson",
        "Content",
        "ContributorAllow",
        "ContributorDeny",
        "CriticalHigh",
        "CriticalLow",
        "DocumentJson",
        "Extractions",
        "FiltersJson",
        "GroupByJson",
        "HolidayRefs",
        "IncludedQuantity",
        "IntervalCount",
        "Meta",
        "MetricCodes",
        "MinimumOverallScore",
        "MinSampleSize",
        "MultiplierBps",
        "Participants",
        "Quantity",
        "RedactionAfterDays",
        "RedactionJson",
        "RetentionDays",
        "RetentionJson",
        "RetryPolicyJson",
        "RolloverQuantity",
        "RoundingStep",
        "SecretRefs",
        "Settings",
        "SettingsJson",
        "Signals",
        "SortOrder",
        "SourceAllow",
        "SourceDeny",
        "SourceFilter",
        "SubtotalAmount",
        "TargetMinutes",
        "TargetValue",
        "TaxAmount",
        "TimeToQuoteWeight",
        "TotalAmount",
        "TrialPeriodDays",
        "TriggersJson",
        "UnitAmount",
        "Version",
        "VersionNumber",
        "WarnBeforeMinutes",
        "WarnedOffsetsJson",
        "WarnHigh",
        "WarnLow",
        "WarnOffsetsJson",
        "WindowSeconds",
    }
)


class _CrudValidationBase(IValidationBase):
    """Shared normalization helpers for generated CRUD validation models."""

    _required_text_fields: ClassVar[tuple[str, ...]] = ()
    _optional_text_fields: ClassVar[tuple[str, ...]] = ()
    _update_fields: ClassVar[tuple[str, ...]] = ()
    _empty_update_message: ClassVar[str] = (
        "At least one mutable field must be provided."
    )

    @model_validator(mode="after")
    def _normalize_text_fields(self) -> "_CrudValidationBase":
        for field_name in self._required_text_fields:
            value = getattr(self, field_name)
            normalized = str(value).strip()
            if normalized == "":
                raise ValueError(f"{to_pascal(field_name)} must be non-empty.")
            setattr(self, field_name, normalized)

        for field_name in self._optional_text_fields:
            value = getattr(self, field_name)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized == "":
                raise ValueError(
                    f"{to_pascal(field_name)} must be non-empty when provided."
                )
            setattr(self, field_name, normalized)

        if self._update_fields and all(
            getattr(self, field_name) is None for field_name in self._update_fields
        ):
            raise ValueError(self._empty_update_message)

        return self


def _required_fields(
    annotation: Any,
    names: tuple[str, ...],
) -> dict[str, tuple[Any, Any]]:
    return {name: (annotation, ...) for name in names}


def _optional_fields(
    annotation: Any,
    names: tuple[str, ...],
) -> dict[str, tuple[Any, Any]]:
    return {name: (annotation | None, None) for name in names}


def _build_fields(
    *,
    required_text: tuple[str, ...] = (),
    optional_text: tuple[str, ...] = (),
    required_uuid: tuple[str, ...] = (),
    optional_uuid: tuple[str, ...] = (),
    required_bool: tuple[str, ...] = (),
    optional_bool: tuple[str, ...] = (),
    required_datetime: tuple[str, ...] = (),
    optional_datetime: tuple[str, ...] = (),
    required_any: tuple[str, ...] = (),
    optional_any: tuple[str, ...] = (),
) -> dict[str, tuple[Any, Any]]:
    fields: dict[str, tuple[Any, Any]] = {}
    fields.update(_required_fields(str, required_text))
    fields.update(_optional_fields(str, optional_text))
    fields.update(_required_fields(uuid.UUID, required_uuid))
    fields.update(_optional_fields(uuid.UUID, optional_uuid))
    fields.update(_required_fields(bool, required_bool))
    fields.update(_optional_fields(bool, optional_bool))
    fields.update(_required_fields(datetime, required_datetime))
    fields.update(_optional_fields(datetime, optional_datetime))
    fields.update(_required_fields(Any, required_any))
    fields.update(_optional_fields(Any, optional_any))
    return fields


def _classify_pascal_field(field_name: str) -> str:
    if field_name in _TEXT_FIELD_NAMES:
        return "text"
    if field_name.startswith("Is") or field_name in _BOOL_FIELD_NAMES:
        return "bool"
    if field_name.endswith("Id"):
        return "uuid"
    if field_name.endswith("At") or field_name in _DATETIME_FIELD_NAMES:
        return "datetime"
    if field_name in _ANY_FIELD_NAMES or field_name.endswith("Json"):
        return "any"
    return "text"


def _group_pascal_fields(
    names: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {
        "text": [],
        "uuid": [],
        "bool": [],
        "datetime": [],
        "any": [],
    }
    for field_name in names:
        grouped[_classify_pascal_field(field_name)].append(title_to_snake(field_name))

    return {
        key: tuple(values)
        for key, values in grouped.items()
    }


def build_create_validation(
    name: str,
    *,
    module: str,
    doc: str,
    required_text: tuple[str, ...] = (),
    optional_text: tuple[str, ...] = (),
    required_uuid: tuple[str, ...] = (),
    optional_uuid: tuple[str, ...] = (),
    required_bool: tuple[str, ...] = (),
    optional_bool: tuple[str, ...] = (),
    required_datetime: tuple[str, ...] = (),
    optional_datetime: tuple[str, ...] = (),
    required_any: tuple[str, ...] = (),
    optional_any: tuple[str, ...] = (),
) -> type[IValidationBase]:
    """Build one create validator with explicit required and optional fields."""
    model = create_model(
        name,
        __base__=_CrudValidationBase,
        __module__=module,
        **_build_fields(
            required_text=required_text,
            optional_text=optional_text,
            required_uuid=required_uuid,
            optional_uuid=optional_uuid,
            required_bool=required_bool,
            optional_bool=optional_bool,
            required_datetime=required_datetime,
            optional_datetime=optional_datetime,
            required_any=required_any,
            optional_any=optional_any,
        ),
    )
    model.__doc__ = doc
    model._required_text_fields = required_text
    model._optional_text_fields = optional_text
    return model


def build_update_validation(
    name: str,
    *,
    module: str,
    doc: str,
    optional_text: tuple[str, ...] = (),
    optional_uuid: tuple[str, ...] = (),
    optional_bool: tuple[str, ...] = (),
    optional_datetime: tuple[str, ...] = (),
    optional_any: tuple[str, ...] = (),
    empty_update_message: str = "At least one mutable field must be provided.",
) -> type[IValidationBase]:
    """Build one update validator with optional fields and no-op patch rejection."""
    model = create_model(
        name,
        __base__=_CrudValidationBase,
        __module__=module,
        **_build_fields(
            optional_text=optional_text,
            optional_uuid=optional_uuid,
            optional_bool=optional_bool,
            optional_datetime=optional_datetime,
            optional_any=optional_any,
        ),
    )
    model.__doc__ = doc
    model._optional_text_fields = optional_text
    model._update_fields = (
        optional_text
        + optional_uuid
        + optional_bool
        + optional_datetime
        + optional_any
    )
    model._empty_update_message = empty_update_message
    return model


def build_create_validation_from_pascal(
    name: str,
    *,
    module: str,
    doc: str,
    required_fields: tuple[str, ...],
    optional_fields: tuple[str, ...] = (),
) -> type[IValidationBase]:
    """Build one create validator from ACP PascalCase field names."""
    required_grouped = _group_pascal_fields(required_fields)
    optional_grouped = _group_pascal_fields(optional_fields)
    return build_create_validation(
        name,
        module=module,
        doc=doc,
        required_text=required_grouped["text"],
        optional_text=optional_grouped["text"],
        required_uuid=required_grouped["uuid"],
        optional_uuid=optional_grouped["uuid"],
        required_bool=required_grouped["bool"],
        optional_bool=optional_grouped["bool"],
        required_datetime=required_grouped["datetime"],
        optional_datetime=optional_grouped["datetime"],
        required_any=required_grouped["any"],
        optional_any=optional_grouped["any"],
    )


def build_update_validation_from_pascal(
    name: str,
    *,
    module: str,
    doc: str,
    optional_fields: tuple[str, ...],
    empty_update_message: str = "At least one mutable field must be provided.",
) -> type[IValidationBase]:
    """Build one update validator from ACP PascalCase field names."""
    grouped = _group_pascal_fields(optional_fields)
    return build_update_validation(
        name,
        module=module,
        doc=doc,
        optional_text=grouped["text"],
        optional_uuid=grouped["uuid"],
        optional_bool=grouped["bool"],
        optional_datetime=grouped["datetime"],
        optional_any=grouped["any"],
        empty_update_message=empty_update_message,
    )
