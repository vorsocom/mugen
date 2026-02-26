"""Provides a domain entity for the ConnectorInstance DB model."""

__all__ = ["ConnectorInstanceDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class ConnectorInstanceDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for the ops_connector ConnectorInstance DB model."""

    connector_type_id: uuid.UUID | None = None
    display_name: str | None = None
    config_json: dict[str, Any] | None = None
    secret_ref: str | None = None
    status: str | None = None
    escalation_policy_key: str | None = None
    retry_policy_json: dict[str, Any] | None = None
    attributes: dict[str, Any] | None = None
