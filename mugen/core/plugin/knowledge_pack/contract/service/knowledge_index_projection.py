"""Provides the Knowledge Index Projection service contract."""

__all__ = ["IKnowledgeIndexProjectionService"]

from abc import ABC, abstractmethod
from typing import Any, Mapping
import uuid

from mugen.core.contract.gateway.storage.rdbms.crud_base import ICrudService
from mugen.core.plugin.acp.contract.api.validation import IValidationBase
from mugen.core.plugin.knowledge_pack.domain import KnowledgeIndexProjectionDE


class IKnowledgeIndexProjectionService(  # pylint: disable=too-few-public-methods
    ICrudService[KnowledgeIndexProjectionDE],
    ABC,
):
    """A service contract for system-created projection attempts."""

    # pylint: disable=too-many-arguments
    @abstractmethod
    async def action_retry(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: IValidationBase,
    ) -> tuple[dict[str, Any], int]:
        """Queue a failed projection for another bounded attempt."""
