"""Provides a domain entity for the SchemaBinding DB model."""

__all__ = ["SchemaBindingDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE


@dataclass
class SchemaBindingDE(BaseDE):
    """A domain entity for ACP schema bindings."""

    tenant_id: uuid.UUID | None = None

    schema_definition_id: uuid.UUID | None = None

    target_namespace: str | None = None

    target_entity_set: str | None = None

    target_action: str | None = None

    binding_kind: str | None = None

    is_required: bool | None = None

    is_active: bool | None = None

    attributes: dict[str, Any] | None = None
