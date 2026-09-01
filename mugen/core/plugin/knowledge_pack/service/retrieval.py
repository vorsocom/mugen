"""Provides safe relationally revalidated Knowledge Pack semantic retrieval."""

from __future__ import annotations

__all__ = ["ApprovedKnowledgeResult", "KnowledgeRetrievalService"]

from dataclasses import dataclass
from typing import Any
import uuid

from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeSearchHit,
    KnowledgeSearchQuery,
)
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway


# pylint: disable=too-many-instance-attributes
@dataclass(slots=True, frozen=True)
class ApprovedKnowledgeResult:
    """Authoritative relational content with gateway score and provenance."""

    tenant_id: uuid.UUID
    knowledge_pack_id: uuid.UUID
    knowledge_pack_version_id: uuid.UUID
    knowledge_entry_id: uuid.UUID
    knowledge_entry_revision_id: uuid.UUID
    knowledge_scope_id: uuid.UUID
    entry_key: str
    title: str
    body: str | None
    body_json: dict[str, Any] | None
    channel: str | None
    locale: str | None
    category: str | None
    service_route_key: str | None
    client_profile_key: str | None
    service_profile_id: uuid.UUID | None
    similarity: float | None
    distance: float | None
    projection_provider: str
    projection_target_fingerprint: str


class KnowledgeRetrievalService:
    """Search a projection, then authorize and rehydrate every hit relationally."""

    _PACK_TABLE = "knowledge_pack_knowledge_pack"
    _VERSION_TABLE = "knowledge_pack_knowledge_pack_version"
    _ENTRY_TABLE = "knowledge_pack_knowledge_entry"
    _REVISION_TABLE = "knowledge_pack_knowledge_entry_revision"
    _SCOPE_TABLE = "knowledge_pack_knowledge_scope"
    _PROJECTION_TABLE = "knowledge_pack_knowledge_index_projection"
    _SERVICE_PROFILE_TABLE = "service_profile_service_profile"

    def __init__(
        self,
        *,
        rsg: IRelationalStorageGateway,
        gateway: IKnowledgeGateway,
    ) -> None:
        self._rsg = rsg
        self._gateway = gateway

    async def current_projection_ready(
        self,
        *,
        tenant_id: uuid.UUID,
        knowledge_pack_version_id: uuid.UUID,
    ) -> bool:
        """Report readiness for the active provider target only."""
        projection = await self._rsg.get_one(
            self._PROJECTION_TABLE,
            {
                "tenant_id": tenant_id,
                "knowledge_pack_version_id": knowledge_pack_version_id,
                "provider": self._gateway.provider_name,
                "target_fingerprint": self._gateway.configuration_fingerprint(),
                "status": "ready",
                "is_current_ready": True,
            },
        )
        return projection is not None

    @staticmethod
    def _effective_scope(
        scope: dict[str, Any],
        revision: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "channel": scope.get("channel") or revision.get("channel"),
            "locale": scope.get("locale") or revision.get("locale"),
            "category": scope.get("category") or revision.get("category"),
            "service_route_key": scope.get("service_route_key"),
            "client_profile_key": scope.get("client_profile_key"),
            "service_profile_id": scope.get("service_profile_id"),
        }

    @staticmethod
    def _scope_matches(
        effective_scope: dict[str, Any],
        query: KnowledgeSearchQuery,
    ) -> bool:
        for field_name in (
            "channel",
            "locale",
            "category",
            "service_route_key",
            "client_profile_key",
            "service_profile_id",
        ):
            requested = getattr(query, field_name)
            stored = effective_scope.get(field_name)
            if field_name == "service_profile_id":
                if requested is None:
                    if stored is not None:
                        return False
                elif stored not in (None, requested):
                    return False
                continue
            if requested is not None and stored not in (None, requested):
                return False
        return True

    @staticmethod
    def _specificity(scope: dict[str, Any], query: KnowledgeSearchQuery) -> int:
        return sum(
            1
            for field_name in (
                "channel",
                "locale",
                "category",
                "service_route_key",
                "client_profile_key",
                "service_profile_id",
            )
            if getattr(query, field_name) is not None
            and scope.get(field_name) == getattr(query, field_name)
        )

    # pylint: disable=too-many-return-statements
    async def _rehydrate_hit(
        self,
        *,
        query: KnowledgeSearchQuery,
        hit: KnowledgeSearchHit,
    ) -> tuple[ApprovedKnowledgeResult, int] | None:
        if hit.tenant_id != query.tenant_id:
            return None
        if (
            hit.knowledge_pack_id is None
            or hit.knowledge_entry_id is None
            or hit.knowledge_scope_id is None
            or hit.entry_key is None
        ):
            return None
        pack = await self._rsg.get_one(
            self._PACK_TABLE,
            {
                "tenant_id": query.tenant_id,
                "id": hit.knowledge_pack_id,
                "is_active": True,
            },
        )
        if (
            pack is None
            or pack.get("current_version_id") != hit.knowledge_pack_version_id
        ):
            return None
        if (
            query.knowledge_pack_id is not None
            and pack["id"] != query.knowledge_pack_id
        ):
            return None
        version = await self._rsg.get_one(
            self._VERSION_TABLE,
            {
                "tenant_id": query.tenant_id,
                "id": hit.knowledge_pack_version_id,
                "knowledge_pack_id": hit.knowledge_pack_id,
                "status": "published",
            },
        )
        if version is None or not await self.current_projection_ready(
            tenant_id=query.tenant_id,
            knowledge_pack_version_id=hit.knowledge_pack_version_id,
        ):
            return None
        entry = await self._rsg.get_one(
            self._ENTRY_TABLE,
            {
                "tenant_id": query.tenant_id,
                "id": hit.knowledge_entry_id,
                "knowledge_pack_id": hit.knowledge_pack_id,
                "knowledge_pack_version_id": hit.knowledge_pack_version_id,
                "is_active": True,
            },
        )
        if entry is None or str(entry.get("entry_key")) != hit.entry_key:
            return None
        revision = await self._rsg.get_one(
            self._REVISION_TABLE,
            {
                "tenant_id": query.tenant_id,
                "id": hit.knowledge_entry_revision_id,
                "knowledge_entry_id": hit.knowledge_entry_id,
                "knowledge_pack_version_id": hit.knowledge_pack_version_id,
                "status": "published",
            },
        )
        if revision is None:
            return None
        scope = await self._rsg.get_one(
            self._SCOPE_TABLE,
            {
                "tenant_id": query.tenant_id,
                "id": hit.knowledge_scope_id,
                "knowledge_pack_version_id": hit.knowledge_pack_version_id,
                "knowledge_entry_revision_id": hit.knowledge_entry_revision_id,
                "is_active": True,
            },
        )
        if scope is None:
            return None
        effective_scope = self._effective_scope(scope, revision)
        stored_service_profile_id = effective_scope["service_profile_id"]
        if stored_service_profile_id is not None and not await self._profile_active(
            tenant_id=query.tenant_id,
            service_profile_id=stored_service_profile_id,
        ):
            return None
        for field_name, value in effective_scope.items():
            if getattr(hit, field_name) != value:
                return None
        if not self._scope_matches(effective_scope, query):
            return None
        result = ApprovedKnowledgeResult(
            tenant_id=query.tenant_id,
            knowledge_pack_id=hit.knowledge_pack_id,
            knowledge_pack_version_id=hit.knowledge_pack_version_id,
            knowledge_entry_id=hit.knowledge_entry_id,
            knowledge_entry_revision_id=hit.knowledge_entry_revision_id,
            knowledge_scope_id=hit.knowledge_scope_id,
            entry_key=str(entry["entry_key"]),
            title=str(entry["title"]),
            body=revision.get("body"),
            body_json=revision.get("body_json"),
            channel=effective_scope["channel"],
            locale=effective_scope["locale"],
            category=effective_scope["category"],
            service_route_key=effective_scope["service_route_key"],
            client_profile_key=effective_scope["client_profile_key"],
            service_profile_id=effective_scope["service_profile_id"],
            similarity=hit.similarity,
            distance=hit.distance,
            projection_provider=self._gateway.provider_name,
            projection_target_fingerprint=(self._gateway.configuration_fingerprint()),
        )
        return result, self._specificity(effective_scope, query)

    async def _profile_active(
        self,
        *,
        tenant_id: uuid.UUID,
        service_profile_id: uuid.UUID,
    ) -> bool:
        profile = await self._rsg.get_one(
            self._SERVICE_PROFILE_TABLE,
            {
                "tenant_id": tenant_id,
                "id": service_profile_id,
                "status": "active",
                "deleted_at": None,
            },
        )
        return profile is not None

    async def search(
        self,
        query: KnowledgeSearchQuery,
    ) -> list[ApprovedKnowledgeResult]:
        """Return current approved relational content, ignoring gateway bodies."""
        if query.service_profile_id is not None and not await self._profile_active(
            tenant_id=query.tenant_id,
            service_profile_id=query.service_profile_id,
        ):
            return []
        gateway_result = await self._gateway.search(query)
        selected: dict[uuid.UUID, tuple[ApprovedKnowledgeResult, int]] = {}
        for hit in gateway_result.items:
            rehydrated = await self._rehydrate_hit(query=query, hit=hit)
            if rehydrated is None:
                continue
            result, specificity = rehydrated
            existing = selected.get(result.knowledge_entry_id)
            if existing is None or (
                specificity,
                result.similarity if result.similarity is not None else -1.0,
            ) > (
                existing[1],
                (
                    existing[0].similarity
                    if existing[0].similarity is not None
                    else -1.0
                ),
            ):
                selected[result.knowledge_entry_id] = (result, specificity)
        ordered = sorted(
            selected.values(),
            key=lambda item: (
                -item[1],
                -(item[0].similarity if item[0].similarity is not None else -1.0),
                item[0].entry_key,
            ),
        )
        return [item[0] for item in ordered[: query.candidate_limit]]
