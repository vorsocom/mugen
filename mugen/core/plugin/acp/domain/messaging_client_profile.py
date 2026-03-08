"""Provides a domain entity for the MessagingClientProfile DB model."""

__all__ = ["MessagingClientProfileDE"]

import uuid
from dataclasses import dataclass
from typing import Any

from mugen.core.plugin.acp.domain.base import BaseDE
from mugen.core.plugin.acp.domain.mixin.tenant_scoped import TenantScopedDEMixin


@dataclass
class MessagingClientProfileDE(BaseDE, TenantScopedDEMixin):
    """A domain entity for ACP-owned messaging client profiles."""

    platform_key: str | None = None
    profile_key: str | None = None
    display_name: str | None = None
    is_active: bool | None = None

    settings: dict[str, Any] | None = None
    secret_refs: dict[str, str] | None = None

    path_token: str | None = None
    recipient_user_id: str | None = None
    account_number: str | None = None
    phone_number_id: str | None = None
    provider: str | None = None
