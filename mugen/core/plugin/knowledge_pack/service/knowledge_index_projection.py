"""Provides durable Knowledge Pack projection queue operations."""

from __future__ import annotations

__all__ = ["KnowledgeIndexProjectionService", "projection_action_response"]

from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, Mapping
import uuid

from quart import abort
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from mugen.core.contract.gateway.knowledge import IKnowledgeGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.service_base import IRelationalService
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.knowledge_pack.api.validation import (
    KnowledgeIndexProjectionRetryValidation,
)
from mugen.core.plugin.knowledge_pack.contract.service import (
    IKnowledgeIndexProjectionService,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgeIndexProjectionDE
from mugen.core.plugin.knowledge_pack.runtime import get_knowledge_gateway
from mugen.core.plugin.knowledge_pack.service.projection_document import (
    PROJECTION_SCHEMA_VERSION,
    KnowledgeProjectionDocumentBuilder,
)


def projection_action_response(
    projection: KnowledgeIndexProjectionDE,
) -> dict[str, Any]:
    """Render a stable action response without exposing internal request payloads."""
    return {
        "ProjectionId": None if projection.id is None else str(projection.id),
        "Status": projection.status,
        "Provider": projection.provider,
        "TargetFingerprint": projection.target_fingerprint,
        "KnowledgePackId": (
            None
            if projection.knowledge_pack_id is None
            else str(projection.knowledge_pack_id)
        ),
        "KnowledgePackVersionId": (
            None
            if projection.knowledge_pack_version_id is None
            else str(projection.knowledge_pack_version_id)
        ),
    }


class KnowledgeIndexProjectionService(
    IRelationalService[KnowledgeIndexProjectionDE],
    IKnowledgeIndexProjectionService,
):
    """A system-owned CRUD service and controlled projection retry surface."""

    def __init__(
        self,
        table: str,
        rsg: IRelationalStorageGateway,
        gateway_provider=get_knowledge_gateway,
        **kwargs,
    ):
        super().__init__(
            de_type=KnowledgeIndexProjectionDE,
            table=table,
            rsg=rsg,
            **kwargs,
        )
        self._gateway_provider = gateway_provider
        self._document_builder = KnowledgeProjectionDocumentBuilder(rsg)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    def gateway(self) -> IKnowledgeGateway | None:
        """Return the active gateway at action time."""
        return self._gateway_provider()

    async def _active_attempt(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
        provider: str,
        target_fingerprint: str,
    ) -> KnowledgeIndexProjectionDE | None:
        rows = await self.list(
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "knowledge_pack_version_id": knowledge_pack_version_id,
                        "provider": provider,
                        "target_fingerprint": target_fingerprint,
                    },
                    scalar_filters=[
                        ScalarFilter(
                            field="status",
                            op=ScalarFilterOp.IN,
                            value=["queued", "processing"],
                        )
                    ],
                )
            ],
            limit=1,
        )
        return rows[0] if rows else None

    # pylint: disable=too-many-arguments
    async def queue_projection(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
        requested_by_user_id: uuid.UUID,
        operation: str,
        note: str | None = None,
    ) -> KnowledgeIndexProjectionDE:
        """Create or return the single active attempt for a provider target."""
        gateway = self.gateway()
        if gateway is None:
            abort(409, "A knowledge gateway is not configured.")
        provider = gateway.provider_name
        target_fingerprint = gateway.configuration_fingerprint()
        try:
            active = await self._active_attempt(
                tenant_id=tenant_id,
                knowledge_pack_version_id=knowledge_pack_version_id,
                provider=provider,
                target_fingerprint=target_fingerprint,
            )
        except SQLAlchemyError:
            abort(500)
        if active is not None:
            return active

        if operation == "cleanup":
            documents = []
            content_checksum = sha256(b"[]").hexdigest()
        else:
            try:
                documents, content_checksum = await self._document_builder.build(
                    tenant_id=tenant_id,
                    knowledge_pack_id=knowledge_pack_id,
                    knowledge_pack_version_id=knowledge_pack_version_id,
                )
            except SQLAlchemyError:
                abort(500)
        requested_at = self._now_utc()
        try:
            return await self.create(
                {
                    "tenant_id": tenant_id,
                    "knowledge_pack_id": knowledge_pack_id,
                    "knowledge_pack_version_id": knowledge_pack_version_id,
                    "provider": provider,
                    "target_fingerprint": target_fingerprint,
                    "content_checksum": content_checksum,
                    "projection_schema_version": PROJECTION_SCHEMA_VERSION,
                    "operation": operation,
                    "status": "queued",
                    "document_count": len(documents),
                    "attempt_count": 0,
                    "max_attempts": 3,
                    "requested_by_user_id": requested_by_user_id,
                    "requested_at": requested_at,
                    "is_current_ready": False,
                    "request_payload": {
                        "note": str(note).strip()[:1024] if note else None,
                    },
                }
            )
        except IntegrityError:
            try:
                active = await self._active_attempt(
                    tenant_id=tenant_id,
                    knowledge_pack_version_id=knowledge_pack_version_id,
                    provider=provider,
                    target_fingerprint=target_fingerprint,
                )
            except SQLAlchemyError:
                abort(500)
            if active is not None:
                return active
            abort(409, "A projection attempt is already active.")
        except SQLAlchemyError:
            abort(500)

    # pylint: disable=too-many-arguments
    async def action_retry(
        self,
        *,
        tenant_id: uuid.UUID,
        entity_id: uuid.UUID,
        where: Mapping[str, Any],
        auth_user_id: uuid.UUID,
        data: KnowledgeIndexProjectionRetryValidation,
    ) -> tuple[dict[str, Any], int]:
        """Queue a failed attempt if the same target is still active."""
        scoped_where = {
            **where,
            "tenant_id": tenant_id,
            "id": entity_id,
        }
        expected_row_version = int(data.row_version)
        versioned_where = {**scoped_where, "row_version": expected_row_version}
        try:
            current = await self.get(versioned_where)
            if current is None:
                base = await self.get(scoped_where)
                if base is None:
                    abort(404, "Knowledge index projection not found.")
                abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
        if current.status != "failed":
            abort(409, "Only failed projections can be retried.")
        if (current.attempt_count or 0) >= (current.max_attempts or 3):
            abort(409, "Projection retry limit has been reached.")
        gateway = self.gateway()
        if gateway is None:
            abort(409, "A knowledge gateway is not configured.")
        if (
            current.provider != gateway.provider_name
            or current.target_fingerprint != gateway.configuration_fingerprint()
        ):
            abort(409, "The active provider target changed; submit a reindex instead.")
        try:
            updated = await self.update_with_row_version(
                where=scoped_where,
                expected_row_version=expected_row_version,
                changes={
                    "status": "queued",
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "requested_by_user_id": auth_user_id,
                    "requested_at": self._now_utc(),
                    "started_at": None,
                    "completed_at": None,
                    "failed_at": None,
                    "failure_code": None,
                    "failure_detail": None,
                },
            )
        except RowVersionConflict:
            abort(409, "RowVersion conflict. Refresh and retry.")
        except SQLAlchemyError:
            abort(500)
        if updated is None:
            abort(404, "Knowledge index projection not found.")
        return projection_action_response(updated), 202
