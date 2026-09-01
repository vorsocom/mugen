"""Runs durable Knowledge Pack projection jobs with bounded leases and retries."""

from __future__ import annotations

__all__ = ["KnowledgeProjectionWorker"]

import asyncio
from datetime import datetime, timedelta, timezone
import uuid

from mugen.core.contract.gateway.knowledge import (
    IKnowledgeGateway,
    KnowledgeDeleteSelector,
    KnowledgeSearchQuery,
)
from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.rdbms.gateway import IRelationalStorageGateway
from mugen.core.contract.gateway.storage.rdbms.types import (
    FilterGroup,
    OrderBy,
    RowVersionConflict,
    ScalarFilter,
    ScalarFilterOp,
)
from mugen.core.plugin.knowledge_pack.domain import KnowledgeIndexProjectionDE
from mugen.core.plugin.knowledge_pack.service.knowledge_index_projection import (
    KnowledgeIndexProjectionService,
)
from mugen.core.plugin.knowledge_pack.service.projection_document import (
    KnowledgeProjectionDocumentBuilder,
)


class KnowledgeProjectionWorker:  # pylint: disable=too-many-instance-attributes
    """Lease and execute projection rows while preserving relational authority."""

    _PROJECTION_TABLE = "knowledge_pack_knowledge_index_projection"
    _PACK_TABLE = "knowledge_pack_knowledge_pack"
    _VERSION_TABLE = "knowledge_pack_knowledge_pack_version"
    _REVISION_TABLE = "knowledge_pack_knowledge_entry_revision"
    _APPROVAL_TABLE = "knowledge_pack_knowledge_approval"

    # pylint: disable=too-many-arguments
    def __init__(
        self,
        *,
        rsg: IRelationalStorageGateway,
        gateway: IKnowledgeGateway,
        logging_gateway: ILoggingGateway,
        lease_seconds: int = 120,
        poll_seconds: float = 1.0,
        worker_id: str | None = None,
    ) -> None:
        self._rsg = rsg
        self._gateway = gateway
        self._logging_gateway = logging_gateway
        self._lease_seconds = max(10, int(lease_seconds))
        self._poll_seconds = max(0.05, float(poll_seconds))
        self._worker_id = worker_id or f"knowledge-projection-{uuid.uuid4()}"
        self._stop = asyncio.Event()
        self._projection_service = KnowledgeIndexProjectionService(
            table=self._PROJECTION_TABLE,
            rsg=rsg,
            gateway_provider=lambda: gateway,
        )
        self._document_builder = KnowledgeProjectionDocumentBuilder(rsg)

    @staticmethod
    def _now_utc() -> datetime:
        return datetime.now(timezone.utc)

    async def stop(self) -> None:
        """Request a graceful worker-loop stop."""
        self._stop.set()

    async def aclose(self) -> None:
        """Container-shutdown alias for stopping the background worker."""
        await self.stop()

    async def run(self) -> None:
        """Poll the durable queue until application shutdown."""
        while not self._stop.is_set():
            try:
                processed = await self.run_once()
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Knowledge projection queue poll failed "
                    f"error_type={type(exc).__name__}"
                )
                processed = False
            if processed:
                continue
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=self._poll_seconds,
                )
            except asyncio.TimeoutError:
                continue

    async def _recover_expired_leases(self) -> int:
        now = self._now_utc()
        rows = await self._projection_service.list(
            filter_groups=[
                FilterGroup(
                    where={"status": "processing"},
                    scalar_filters=[
                        ScalarFilter(
                            field="lease_expires_at",
                            op=ScalarFilterOp.LTE,
                            value=now,
                        )
                    ],
                )
            ],
            limit=100,
        )
        recovered = 0
        for row in rows:
            if row.id is None:
                continue
            updated = await self._projection_service.update(
                where={
                    "id": row.id,
                    "status": "processing",
                    "lease_expires_at": row.lease_expires_at,
                },
                changes={
                    "status": "queued",
                    "lease_owner": None,
                    "lease_expires_at": None,
                },
            )
            if updated is not None:
                recovered += 1
        if recovered:
            self._logging_gateway.warning(
                "Knowledge projection worker recovered expired leases "
                f"count={recovered}"
            )
        return recovered

    async def _claim_next(self) -> KnowledgeIndexProjectionDE | None:
        await self._recover_expired_leases()
        rows = await self._projection_service.list(
            filter_groups=[FilterGroup(where={"status": "queued"})],
            order_by=[OrderBy(field="requested_at")],
            limit=20,
        )
        now = self._now_utc()
        for row in rows:
            if row.id is None:
                continue
            attempt_count = int(row.attempt_count or 0)
            max_attempts = int(row.max_attempts or 3)
            if attempt_count >= max_attempts:
                await self._projection_service.update(
                    where={"id": row.id, "status": "queued"},
                    changes={
                        "status": "failed",
                        "failed_at": now,
                        "failure_code": "retry_limit_reached",
                        "failure_detail": "Projection retry limit reached.",
                    },
                )
                continue
            try:
                claimed = await self._projection_service.update(
                    where={
                        "id": row.id,
                        "status": "queued",
                        "row_version": row.row_version,
                    },
                    changes={
                        "status": "processing",
                        "attempt_count": attempt_count + 1,
                        "lease_owner": self._worker_id,
                        "lease_expires_at": now
                        + timedelta(seconds=self._lease_seconds),
                        "started_at": row.started_at or now,
                        "failed_at": None,
                        "failure_code": None,
                        "failure_detail": None,
                    },
                )
            except RowVersionConflict:
                continue
            if claimed is not None:
                return claimed
        return None

    async def run_once(self) -> bool:
        """Claim and process at most one durable projection row."""
        projection = await self._claim_next()
        if projection is None:
            return False
        heartbeat = asyncio.create_task(self._heartbeat(projection))
        try:
            await self._process(projection)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            await self._record_failure(projection, exc)
        finally:
            heartbeat.cancel()
            try:
                await heartbeat
            except asyncio.CancelledError:
                pass
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._logging_gateway.warning(
                    "Knowledge projection heartbeat failed "
                    f"projection_id={projection.id} error_type={type(exc).__name__}"
                )
        return True

    async def _heartbeat(self, projection: KnowledgeIndexProjectionDE) -> None:
        interval = max(3.0, self._lease_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            updated = await self._projection_service.update(
                where={
                    "id": projection.id,
                    "status": "processing",
                    "lease_owner": self._worker_id,
                },
                changes={
                    "lease_expires_at": self._now_utc()
                    + timedelta(seconds=self._lease_seconds)
                },
            )
            if updated is None:
                return

    async def _lease_is_active(
        self,
        projection: KnowledgeIndexProjectionDE,
    ) -> bool:
        row = await self._projection_service.get(
            {
                "id": projection.id,
                "tenant_id": projection.tenant_id,
                "status": "processing",
                "lease_owner": self._worker_id,
            }
        )
        return row is not None

    def _validate_target(self, projection: KnowledgeIndexProjectionDE) -> None:
        if projection.provider != self._gateway.provider_name:
            raise RuntimeError("Configured knowledge provider changed.")
        if projection.target_fingerprint != self._gateway.configuration_fingerprint():
            raise RuntimeError("Configured knowledge provider target changed.")

    async def _process(self, projection: KnowledgeIndexProjectionDE) -> None:
        self._validate_target(projection)
        if (
            projection.id is None
            or projection.tenant_id is None
            or projection.knowledge_pack_id is None
            or projection.knowledge_pack_version_id is None
        ):
            raise RuntimeError("Projection identity is incomplete.")
        if projection.operation == "cleanup":
            await self._gateway.delete_documents(
                KnowledgeDeleteSelector(
                    tenant_id=projection.tenant_id,
                    knowledge_pack_id=projection.knowledge_pack_id,
                    knowledge_pack_version_id=projection.knowledge_pack_version_id,
                )
            )
            await self._finalize_cleanup(projection)
            return

        documents, checksum = await self._document_builder.build(
            tenant_id=projection.tenant_id,
            knowledge_pack_id=projection.knowledge_pack_id,
            knowledge_pack_version_id=projection.knowledge_pack_version_id,
        )
        if checksum != projection.content_checksum:
            raise RuntimeError("Governed content changed after projection was queued.")
        result = await self._gateway.upsert_documents(documents)
        if not result.acknowledged or result.requested_count != len(documents):
            raise RuntimeError("Knowledge provider did not acknowledge the full write.")
        if not await self._lease_is_active(projection):
            await self._gateway.delete_documents(
                KnowledgeDeleteSelector(
                    tenant_id=projection.tenant_id,
                    knowledge_pack_id=projection.knowledge_pack_id,
                    knowledge_pack_version_id=projection.knowledge_pack_version_id,
                )
            )
            return
        await self._verify(documents)
        await self._finalize_ready(projection, document_count=len(documents))

    async def _verify(self, documents) -> None:
        for document in documents:
            result = await self._gateway.search(
                KnowledgeSearchQuery(
                    tenant_id=document.tenant_id,
                    query_text=document.content,
                    knowledge_pack_id=document.knowledge_pack_id,
                    knowledge_pack_version_id=document.knowledge_pack_version_id,
                    channel=document.channel,
                    locale=document.locale,
                    category=document.category,
                    service_route_key=document.service_route_key,
                    client_profile_key=document.client_profile_key,
                    candidate_limit=10,
                    min_similarity=0.0,
                )
            )
            if not any(
                hit.knowledge_entry_revision_id == document.knowledge_entry_revision_id
                and hit.knowledge_scope_id == document.knowledge_scope_id
                for hit in result.items
            ):
                raise RuntimeError(
                    "Knowledge provider verification did not find a document."
                )

    async def _unset_current_ready(self, uow, projection) -> None:
        current_rows = await uow.find(
            self._PROJECTION_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": projection.tenant_id,
                        "knowledge_pack_version_id": (
                            projection.knowledge_pack_version_id
                        ),
                        "provider": projection.provider,
                        "target_fingerprint": projection.target_fingerprint,
                        "is_current_ready": True,
                    }
                )
            ],
            limit=100,
        )
        for row in current_rows:
            if row.get("id") == projection.id:
                continue
            await uow.update_one(
                self._PROJECTION_TABLE,
                {"id": row["id"], "is_current_ready": True},
                {"is_current_ready": False},
            )

    async def _publish_relational(self, uow, projection, now: datetime) -> None:
        versions = await uow.find(
            self._VERSION_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": projection.tenant_id,
                        "knowledge_pack_id": projection.knowledge_pack_id,
                        "status": "published",
                    }
                )
            ],
            limit=500,
        )
        previous_version_id = None
        for version in versions:
            if version.get("id") == projection.knowledge_pack_version_id:
                continue
            previous_version_id = version["id"]
            await uow.update_one(
                self._VERSION_TABLE,
                {"tenant_id": projection.tenant_id, "id": version["id"]},
                {
                    "status": "archived",
                    "archived_at": now,
                    "archived_by_user_id": projection.requested_by_user_id,
                },
            )
            await self._transition_revisions(
                uow,
                tenant_id=projection.tenant_id,
                version_id=version["id"],
                from_statuses={"published"},
                to_status="archived",
                actor_user_id=projection.requested_by_user_id,
                now=now,
            )

        changes = {
            "status": "published",
            "published_at": now,
            "published_by_user_id": projection.requested_by_user_id,
            "archived_at": None,
            "archived_by_user_id": None,
        }
        if projection.operation == "rollback":
            changes["rollback_of_version_id"] = previous_version_id
        await uow.update_one(
            self._VERSION_TABLE,
            {
                "tenant_id": projection.tenant_id,
                "id": projection.knowledge_pack_version_id,
            },
            changes,
        )
        await self._transition_revisions(
            uow,
            tenant_id=projection.tenant_id,
            version_id=projection.knowledge_pack_version_id,
            from_statuses={"approved", "archived", "published"},
            to_status="published",
            actor_user_id=projection.requested_by_user_id,
            now=now,
        )
        await uow.update_one(
            self._PACK_TABLE,
            {
                "tenant_id": projection.tenant_id,
                "id": projection.knowledge_pack_id,
            },
            {"current_version_id": projection.knowledge_pack_version_id},
        )
        await uow.insert(
            self._APPROVAL_TABLE,
            {
                "tenant_id": projection.tenant_id,
                "knowledge_pack_version_id": projection.knowledge_pack_version_id,
                "action": (
                    "rollback_version"
                    if projection.operation == "rollback"
                    else "publish"
                ),
                "actor_user_id": projection.requested_by_user_id,
                "occurred_at": now,
                "payload": {"projection_id": str(projection.id)},
            },
        )

    # pylint: disable=too-many-arguments
    async def _transition_revisions(
        self,
        uow,
        *,
        tenant_id: uuid.UUID,
        version_id: uuid.UUID,
        from_statuses: set[str],
        to_status: str,
        actor_user_id: uuid.UUID | None,
        now: datetime,
    ) -> None:
        rows = await uow.find(
            self._REVISION_TABLE,
            filter_groups=[
                FilterGroup(
                    where={
                        "tenant_id": tenant_id,
                        "knowledge_pack_version_id": version_id,
                    },
                    scalar_filters=[
                        ScalarFilter(
                            field="status",
                            op=ScalarFilterOp.IN,
                            value=list(from_statuses),
                        )
                    ],
                )
            ],
            limit=20_000,
        )
        for row in rows:
            changes = {"status": to_status}
            if to_status == "published":
                changes.update(
                    {
                        "published_at": now,
                        "published_by_user_id": actor_user_id,
                        "archived_at": None,
                        "archived_by_user_id": None,
                    }
                )
            else:
                changes.update(
                    {
                        "archived_at": now,
                        "archived_by_user_id": actor_user_id,
                    }
                )
            await uow.update_one(
                self._REVISION_TABLE,
                {"tenant_id": tenant_id, "id": row["id"]},
                changes,
            )

    async def _finalize_ready(
        self,
        projection: KnowledgeIndexProjectionDE,
        *,
        document_count: int,
    ) -> None:
        now = self._now_utc()
        async with self._rsg.unit_of_work() as uow:
            await self._unset_current_ready(uow, projection)
            if projection.operation in {"publish", "rollback"}:
                await self._publish_relational(uow, projection, now)
            updated = await uow.update_one(
                self._PROJECTION_TABLE,
                {
                    "id": projection.id,
                    "tenant_id": projection.tenant_id,
                    "status": "processing",
                    "lease_owner": self._worker_id,
                },
                {
                    "status": "ready",
                    "document_count": document_count,
                    "completed_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "failed_at": None,
                    "failure_code": None,
                    "failure_detail": None,
                    "is_current_ready": True,
                },
            )
            if updated is None:
                raise RuntimeError("Projection lease was lost before finalization.")
        self._logging_gateway.info(
            "Knowledge projection ready "
            f"projection_id={projection.id} provider={projection.provider} "
            f"document_count={document_count}"
        )

    async def _finalize_cleanup(
        self,
        projection: KnowledgeIndexProjectionDE,
    ) -> None:
        now = self._now_utc()
        async with self._rsg.unit_of_work() as uow:
            await self._unset_current_ready(uow, projection)
            updated = await uow.update_one(
                self._PROJECTION_TABLE,
                {
                    "id": projection.id,
                    "tenant_id": projection.tenant_id,
                    "status": "processing",
                    "lease_owner": self._worker_id,
                },
                {
                    "status": "ready",
                    "completed_at": now,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "is_current_ready": False,
                },
            )
            if updated is None:
                raise RuntimeError("Projection cleanup lease was lost.")

    async def _record_failure(
        self,
        projection: KnowledgeIndexProjectionDE,
        exc: Exception,
    ) -> None:
        now = self._now_utc()
        attempts = int(projection.attempt_count or 1)
        max_attempts = int(projection.max_attempts or 3)
        retry = attempts < max_attempts
        await self._projection_service.update(
            where={
                "id": projection.id,
                "status": "processing",
                "lease_owner": self._worker_id,
            },
            changes={
                "status": "queued" if retry else "failed",
                "lease_owner": None,
                "lease_expires_at": None,
                "failed_at": now,
                "failure_code": type(exc).__name__[:128],
                "failure_detail": "Projection provider operation failed.",
                "is_current_ready": False,
            },
        )
        self._logging_gateway.warning(
            "Knowledge projection attempt failed "
            f"projection_id={projection.id} provider={projection.provider} "
            f"attempt={attempts}/{max_attempts} retry={str(retry).lower()} "
            f"error_type={type(exc).__name__}"
        )
